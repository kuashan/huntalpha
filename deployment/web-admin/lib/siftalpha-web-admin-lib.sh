#!/usr/bin/env bash
# shellcheck shell=bash
# Fixed-target deployment helpers. This library accepts configuration only from
# root-owned files supplied by the dispatcher; callers never provide paths,
# image names, Docker arguments, or shell fragments.

set -Eeuo pipefail

readonly SIFTALPHA_DIGEST_PATTERN='^sha256:[0-9a-f]{64}$'
readonly SIFTALPHA_IMAGE_REPOSITORY='ghcr.io/kuashan/siftalpha-web'
readonly SIFTALPHA_GITHUB_REPOSITORY='kuashan/huntalpha'
readonly SIFTALPHA_RELEASE_BRANCH='release/siftalpha-web-v1'
readonly SIFTALPHA_WORKFLOW_NAME='SiftAlpha Web CI and ARM64'
readonly SIFTALPHA_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { printf 'siftalpha-web-admin: %s\n' "$*" >&2; return 1; }

require_value() { [[ -n "${!1:-}" ]] || { die "missing required configuration: $1"; return 1; }; }

require_safe_absolute_path() {
  local name="$1" value="${!1:-}"
  [[ "$value" == /* && "$value" != *'..'* ]] || { die "unsafe configuration path: $name"; return 1; }
}

load_config() {
  local config_path="$1"
  [[ -r "$config_path" ]] || { die "configuration is unreadable"; return 1; }
  # Clear all deploy-sensitive values before sourcing the root-owned config.
  unset IMAGE_REPOSITORY GITHUB_REPOSITORY GITHUB_WORKFLOW_NAME RELEASE_BRANCH
  unset LEGACY_CONTAINER COMPOSE_CONTAINER DATA_DIR DATABASE_PATH LOOPBACK_PORT COMPOSE_FILE COMPOSE_TEMPLATE ENV_FILE
  unset STATE_DIR BACKUP_DIR ROLLBACK_DIR RECOVERY_DIR DOCKER_CONFIG_DIR GITHUB_TOKEN_FILE GH_BIN GH_SHA256
  unset DOCKER_BIN CURL_BIN PYTHON_BIN
  # shellcheck disable=SC1090
  source "$config_path"
  validate_config
}

validate_config() {
  local name
  for name in IMAGE_REPOSITORY GITHUB_REPOSITORY GITHUB_WORKFLOW_NAME RELEASE_BRANCH \
    LEGACY_CONTAINER COMPOSE_CONTAINER DATA_DIR DATABASE_PATH LOOPBACK_PORT COMPOSE_FILE COMPOSE_TEMPLATE ENV_FILE \
    STATE_DIR BACKUP_DIR ROLLBACK_DIR RECOVERY_DIR DOCKER_CONFIG_DIR GITHUB_TOKEN_FILE GH_BIN GH_SHA256 DOCKER_BIN CURL_BIN PYTHON_BIN; do
    require_value "$name" || return 1
  done
  [[ "$IMAGE_REPOSITORY" == "$SIFTALPHA_IMAGE_REPOSITORY" ]] || { die 'unexpected image repository'; return 1; }
  [[ "$GITHUB_REPOSITORY" == "$SIFTALPHA_GITHUB_REPOSITORY" ]] || { die 'unexpected GitHub repository'; return 1; }
  [[ "$RELEASE_BRANCH" == "$SIFTALPHA_RELEASE_BRANCH" ]] || { die 'unexpected release branch'; return 1; }
  [[ "$GITHUB_WORKFLOW_NAME" == "$SIFTALPHA_WORKFLOW_NAME" ]] || { die 'unexpected workflow name'; return 1; }
  [[ "$LOOPBACK_PORT" == '127.0.0.1:19091' ]] || { die 'unexpected website loopback port'; return 1; }
  [[ "$LEGACY_CONTAINER" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || { die 'unsafe legacy container name'; return 1; }
  [[ "$COMPOSE_CONTAINER" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || { die 'unsafe Compose container name'; return 1; }
  [[ "$LEGACY_CONTAINER" != "$COMPOSE_CONTAINER" ]] || { die 'legacy and Compose container names must differ'; return 1; }
  [[ "$GH_SHA256" =~ ^[0-9a-f]{64}$ ]] || { die 'invalid GitHub CLI checksum'; return 1; }
  for name in DATA_DIR DATABASE_PATH COMPOSE_FILE COMPOSE_TEMPLATE ENV_FILE STATE_DIR BACKUP_DIR ROLLBACK_DIR RECOVERY_DIR DOCKER_CONFIG_DIR GITHUB_TOKEN_FILE GH_BIN; do
    require_safe_absolute_path "$name" || return 1
  done
}

validate_command() {
  case "$#:$1" in
    1:status|1:health|1:rollback) return 0 ;;
    2:preflight|2:deploy)
      [[ "$2" =~ $SIFTALPHA_DIGEST_PATTERN ]] || { die 'digest must be lowercase sha256:<64 hexadecimal characters>'; return 1; }
      return 0
      ;;
    *) die 'usage: status | health | preflight <digest> | deploy <digest> | rollback' ;;
  esac
}

candidate_image() {
  local digest="$1"
  [[ "$digest" =~ $SIFTALPHA_DIGEST_PATTERN ]] || { die 'invalid candidate digest'; return 1; }
  printf '%s@%s\n' "$IMAGE_REPOSITORY" "$digest"
}

ensure_state_directories() {
  mkdir -p "$STATE_DIR" "$BACKUP_DIR" "$ROLLBACK_DIR" "$RECOVERY_DIR"
  chmod 700 "$STATE_DIR" "$BACKUP_DIR" "$ROLLBACK_DIR" "$RECOVERY_DIR"
}

image_label() {
  local image="$1" label="$2"
  "$DOCKER_BIN" image inspect --format "{{ index .Config.Labels \"$label\" }}" "$image"
}

verify_arm64_image() {
  local image="$1" manifest
  manifest="$($DOCKER_BIN buildx imagetools inspect "$image" --raw)" || { die 'cannot inspect image manifest'; return 1; }
  "$PYTHON_BIN" - "$manifest" <<'PY'
import json
import sys

manifest = json.loads(sys.argv[1])
manifests = manifest.get("manifests", [])
if not any(item.get("platform", {}).get("os") == "linux" and item.get("platform", {}).get("architecture") == "arm64" for item in manifests):
    raise SystemExit("candidate image has no linux/arm64 manifest")
PY
}

verify_oci_labels() {
  local image="$1" expected_commit="$2" expected_run_id="$3"
  [[ "$(image_label "$image" 'org.opencontainers.image.source')" == "https://github.com/$GITHUB_REPOSITORY" ]] || { die 'OCI source label mismatch'; return 1; }
  [[ "$(image_label "$image" 'org.opencontainers.image.revision')" == "$expected_commit" ]] || { die 'OCI revision label mismatch'; return 1; }
  [[ "$(image_label "$image" 'io.siftalpha.build.run-id')" == "$expected_run_id" ]] || { die 'OCI run-id label mismatch'; return 1; }
  [[ "$(image_label "$image" 'io.siftalpha.build.ref')" == "$RELEASE_BRANCH" ]] || { die 'OCI ref label mismatch'; return 1; }
}

verify_gh_binary() {
  [[ -x "$GH_BIN" ]] || { die 'GitHub CLI is unavailable'; return 1; }
  [[ -r "$GITHUB_TOKEN_FILE" ]] || { die 'GitHub verification token is unavailable'; return 1; }
  local actual_checksum
  actual_checksum="$(sha256sum "$GH_BIN" | awk '{print $1}')"
  [[ "$actual_checksum" == "$GH_SHA256" ]] || { die 'GitHub CLI checksum mismatch'; return 1; }
}

verify_trusted_source() {
  local digest="$1" image run_id run_json temp_dir manifest_file oci_manifest_file oci_provenance_file token
  image="$(candidate_image "$digest")"
  verify_gh_binary || return 1
  token="$(<"$GITHUB_TOKEN_FILE")"
  [[ -n "$token" ]] || { die 'GitHub verification token is empty'; return 1; }
  ensure_state_directories
  temp_dir="$(mktemp -d "$RECOVERY_DIR/provenance.XXXXXX")"
  run_json="$temp_dir/run.json"
  manifest_file="$temp_dir/siftalpha-web-build-manifest.json"
  oci_manifest_file="$temp_dir/oci-manifest.json"
  oci_provenance_file="$temp_dir/oci-provenance.json"
  "$DOCKER_BIN" pull "$image" >/dev/null || { cleanup_provenance "$temp_dir"; return 1; }
  run_id="$(image_label "$image" 'io.siftalpha.build.run-id')"
  [[ "$run_id" =~ ^[0-9]+$ ]] || { die 'OCI run-id label is invalid'; cleanup_provenance "$temp_dir"; return 1; }
  GH_TOKEN="$token" DOCKER_CONFIG="$DOCKER_CONFIG_DIR" "$GH_BIN" api "repos/$GITHUB_REPOSITORY/actions/runs/$run_id" > "$run_json" || { cleanup_provenance "$temp_dir"; return 1; }
  GH_TOKEN="$token" DOCKER_CONFIG="$DOCKER_CONFIG_DIR" "$GH_BIN" run download "$run_id" --repo "$GITHUB_REPOSITORY" --name siftalpha-web-build-manifest --dir "$temp_dir" || { cleanup_provenance "$temp_dir"; return 1; }
  [[ -f "$manifest_file" ]] || { die 'build manifest artifact is unavailable'; cleanup_provenance "$temp_dir"; return 1; }
  if ! "$PYTHON_BIN" - "$run_json" "$manifest_file" "$digest" "$run_id" "$RELEASE_BRANCH" "$GITHUB_WORKFLOW_NAME" <<'PY'
import json
import sys

run_path, manifest_path, digest, run_id, branch, workflow_name = sys.argv[1:]
run = json.loads(open(run_path, encoding="utf-8").read())
manifest = json.loads(open(manifest_path, encoding="utf-8").read())
if run.get("status") != "completed" or run.get("conclusion") != "success":
    raise SystemExit("GitHub Actions Run is not successful")
if run.get("head_branch") != branch or run.get("name") != workflow_name:
    raise SystemExit("GitHub Actions Run identity mismatch")
if manifest.get("digest") != digest or str(manifest.get("run_id")) != run_id:
    raise SystemExit("build manifest digest or Run ID mismatch")
if manifest.get("source_commit") != run.get("head_sha"):
    raise SystemExit("build manifest commit mismatch")
if manifest.get("image") != "ghcr.io/kuashan/siftalpha-web" or manifest.get("platform") != "linux/arm64" or manifest.get("ref") != branch:
    raise SystemExit("build manifest identity mismatch")
if manifest.get("source_ref") != f"refs/heads/{branch}" or manifest.get("workflow") != workflow_name:
    raise SystemExit("build manifest workflow identity mismatch")
if manifest.get("run_url") != run.get("html_url"):
    raise SystemExit("build manifest Run URL mismatch")
PY
  then
    cleanup_provenance "$temp_dir"
    return 1
  fi
  local expected_commit
  expected_commit="$($PYTHON_BIN - "$run_json" <<'PY'
import json
import sys
print(json.loads(open(sys.argv[1], encoding="utf-8").read())["head_sha"])
PY
)" || { cleanup_provenance "$temp_dir"; return 1; }
  verify_oci_labels "$image" "$expected_commit" "$run_id" || { cleanup_provenance "$temp_dir"; return 1; }
  "$DOCKER_BIN" buildx imagetools inspect "$image" --format '{{json .Manifest}}' > "$oci_manifest_file" \
    || { die 'cannot read OCI image index from GHCR'; cleanup_provenance "$temp_dir"; return 1; }
  "$DOCKER_BIN" buildx imagetools inspect "$image" --format '{{json .Provenance.SLSA}}' > "$oci_provenance_file" \
    || { die 'cannot read BuildKit OCI provenance from GHCR'; cleanup_provenance "$temp_dir"; return 1; }
  "$PYTHON_BIN" "$SIFTALPHA_LIB_DIR/verify_buildkit_provenance.py" \
    "$manifest_file" "$oci_manifest_file" "$oci_provenance_file" "$digest" "$expected_commit" "$run_id" \
    "refs/heads/$RELEASE_BRANCH" "$GITHUB_WORKFLOW_NAME" \
    || { cleanup_provenance "$temp_dir"; return 1; }
  printf 'trusted source: commit=%s run_id=%s digest=%s\n' "$expected_commit" "$run_id" "$digest"
  cleanup_provenance "$temp_dir"
}

cleanup_provenance() {
  local directory="$1"
  find "$directory" -depth -type f -delete 2>/dev/null || true
  find "$directory" -depth -type d -empty -delete 2>/dev/null || true
}

backup_and_restore_check() {
  [[ -r "$DATABASE_PATH" ]] || { die 'website database is unavailable'; return 1; }
  ensure_state_directories
  "$PYTHON_BIN" - "$DATABASE_PATH" "$BACKUP_DIR" "$RECOVERY_DIR" <<'PY'
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sqlite3
import sys

source_path = Path(sys.argv[1])
backup_dir = Path(sys.argv[2])
recovery_dir = Path(sys.argv[3])
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
partial_path = backup_dir / f"siftalpha-web-{stamp}.sqlite3.partial"
backup_path = backup_dir / f"siftalpha-web-{stamp}.sqlite3"
recovery_path = recovery_dir / f"siftalpha-web-{stamp}.sqlite3"

def integrity(path):
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()

try:
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    target = sqlite3.connect(partial_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    if integrity(partial_path) != "ok":
        raise RuntimeError("backup integrity check failed")
    os.replace(partial_path, backup_path)
    source = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    target = sqlite3.connect(recovery_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    if integrity(recovery_path) != "ok":
        raise RuntimeError("restore integrity check failed")
    size = backup_path.stat().st_size
    digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    print(f"backup path: {backup_path}")
    print(f"backup size: {size}")
    print(f"backup sha256: {digest}")
    print("integrity_check: ok")
finally:
    recovery_path.unlink(missing_ok=True)
    partial_path.unlink(missing_ok=True)
    if 'backup_path' in locals() and backup_path.exists() and 'digest' not in locals():
        backup_path.unlink()
PY
}

health_check() {
  local base="http://$LOOPBACK_PORT" page static_path
  for page in / /account /account/ /healthz/; do
    "$CURL_BIN" --fail --silent --show-error "$base$page" >/dev/null || { die "health endpoint failed: $page"; return 1; }
  done
  static_path="$($CURL_BIN --fail --silent --show-error "$base/" | sed -n 's|.*src="\(/static/[A-Za-z0-9._/-]*\)".*|\1|p' | head -n 1)"
  [[ "$static_path" =~ ^/static/[A-Za-z0-9._/-]+$ && "$static_path" != *..* ]] || { die 'homepage has no safe static asset reference'; return 1; }
  "$CURL_BIN" --fail --silent --show-error "$base$static_path" >/dev/null || { die 'homepage static asset failed'; return 1; }
}

current_container() {
  if "$DOCKER_BIN" container inspect "$COMPOSE_CONTAINER" >/dev/null 2>&1; then
    printf '%s\n' "$COMPOSE_CONTAINER"
  elif "$DOCKER_BIN" container inspect "$LEGACY_CONTAINER" >/dev/null 2>&1; then
    printf '%s\n' "$LEGACY_CONTAINER"
  else
    die 'neither fixed website container exists'
  fi
}

snapshot_current_runtime() {
  local container runtime config_image image_id snapshot created
  ensure_state_directories
  container="$(current_container)" || return 1
  if [[ "$container" == "$LEGACY_CONTAINER" ]]; then
    runtime='legacy'
  else
    runtime='compose'
  fi
  config_image="$($DOCKER_BIN inspect --format '{{.Config.Image}}' "$container")" || { die 'cannot inspect current website image'; return 1; }
  image_id="$($DOCKER_BIN inspect --format '{{.Image}}' "$container")" || { die 'cannot inspect current website image ID'; return 1; }
  [[ -n "$config_image" && -n "$image_id" ]] || { die 'current website image metadata is empty'; return 1; }
  snapshot="$(mktemp -d "$ROLLBACK_DIR/siftalpha-web.XXXXXX")" || { die 'cannot create deployment snapshot'; return 1; }
  chmod 700 "$snapshot"
  created="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  {
    printf 'runtime=%s\n' "$runtime"
    printf 'container=%s\n' "$container"
    printf 'config_image=%s\n' "$config_image"
    printf 'image_id=%s\n' "$image_id"
    printf 'data_dir=%s\n' "$DATA_DIR"
    printf 'created_at=%s\n' "$created"
  } > "$snapshot/metadata"
  chmod 600 "$snapshot/metadata"
  printf '%s\n' "$snapshot" > "$ROLLBACK_DIR/latest"
  chmod 600 "$ROLLBACK_DIR/latest"
  printf 'deployment snapshot: %s\n' "$snapshot"
}

snapshot_value() {
  local snapshot="$1" key="$2"
  [[ "$snapshot" == "$ROLLBACK_DIR"/* && -r "$snapshot/metadata" ]] || { die 'deployment snapshot is unavailable'; return 1; }
  case "$key" in runtime|container|config_image|image_id|data_dir) ;; *) die 'invalid deployment snapshot field'; return 1 ;; esac
  sed -n "s/^${key}=//p" "$snapshot/metadata" | head -n 1
}

latest_snapshot() {
  local snapshot
  [[ -r "$ROLLBACK_DIR/latest" ]] || { die 'no deployment snapshot is available'; return 1; }
  snapshot="$(<"$ROLLBACK_DIR/latest")"
  [[ "$snapshot" == "$ROLLBACK_DIR"/* && -d "$snapshot" ]] || { die 'deployment snapshot path is invalid'; return 1; }
  printf '%s\n' "$snapshot"
}

restore_snapshot() {
  local snapshot="$1" runtime image
  runtime="$(snapshot_value "$snapshot" runtime)" || return 1
  case "$runtime" in
    legacy)
      [[ "$(snapshot_value "$snapshot" container)" == "$LEGACY_CONTAINER" ]] || { die 'legacy snapshot container mismatch'; return 1; }
      "$DOCKER_BIN" rm -f "$COMPOSE_CONTAINER" >/dev/null 2>&1 || true
      "$DOCKER_BIN" start "$LEGACY_CONTAINER" || { die 'cannot restart retained legacy website container'; return 1; }
      ;;
    compose)
      image="$(snapshot_value "$snapshot" config_image)" || return 1
      [[ "$image" == "$IMAGE_REPOSITORY"@sha256:* ]] || { die 'Compose snapshot image is not immutable'; return 1; }
      render_compose "${image#*@}" || return 1
      "$DOCKER_BIN" compose -f "$COMPOSE_FILE" --project-name siftalpha-web up -d --force-recreate || { die 'cannot restore prior Compose website service'; return 1; }
      ;;
    *) die 'deployment snapshot runtime is invalid'; return 1 ;;
  esac
  health_check || { die 'restored website service is unhealthy'; return 1; }
  printf 'rollback: restored snapshot=%s\n' "$snapshot"
}

status() {
  local container image state
  container="$(current_container)"
  state="$($DOCKER_BIN inspect --format '{{.State.Status}}' "$container")"
  image="$($DOCKER_BIN inspect --format '{{.Config.Image}}' "$container")"
  printf 'container: %s\nstate: %s\nimage: %s\nport: %s\n' "$container" "$state" "$image" "$LOOPBACK_PORT"
}

preflight_candidate() {
  local digest="$1"
  [[ "$digest" =~ $SIFTALPHA_DIGEST_PATTERN ]] || { die 'invalid candidate digest'; return 1; }
  health_check || return 1
  [[ -r "$DATABASE_PATH" && -d "$DATA_DIR" ]] || { die 'website data bind is unavailable'; return 1; }
  verify_trusted_source "$digest" || return 1
  verify_arm64_image "$(candidate_image "$digest")" || return 1
  backup_and_restore_check || return 1
  printf 'preflight: ok\n'
}

render_compose() {
  local digest="$1" image
  image="$(candidate_image "$digest")"
  [[ -r "$COMPOSE_TEMPLATE" ]] || { die 'Compose template is unavailable'; return 1; }
  "$PYTHON_BIN" - "$COMPOSE_TEMPLATE" "$COMPOSE_FILE" "$image" "$COMPOSE_CONTAINER" "$DATA_DIR" "$ENV_FILE" "$LOOPBACK_PORT" <<'PY'
from pathlib import Path
import sys

template_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
image, container, data_dir, env_file, port = sys.argv[3:]
content = template_path.read_text(encoding="utf-8")
for key, value in {
    "__IMAGE_REFERENCE__": image,
    "__COMPOSE_CONTAINER__": container,
    "__DATA_DIR__": data_dir,
    "__ENV_FILE__": env_file,
    "__LOOPBACK_PORT__": port,
}.items():
    content = content.replace(key, value)
if "__" in content:
    raise SystemExit("unresolved Compose template placeholder")
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(content, encoding="utf-8")
PY
}

first_compose_cutover() {
  local digest="$1"
  render_compose "$digest"
  "$DOCKER_BIN" stop "$LEGACY_CONTAINER"
  if ! "$DOCKER_BIN" compose -f "$COMPOSE_FILE" --project-name siftalpha-web up -d --force-recreate; then
    "$DOCKER_BIN" rm -f "$COMPOSE_CONTAINER" || true
    "$DOCKER_BIN" start "$LEGACY_CONTAINER"
    die 'candidate Compose service failed; legacy container was restarted'
    return 1
  fi
  if ! health_check; then
    "$DOCKER_BIN" rm -f "$COMPOSE_CONTAINER" || true
    "$DOCKER_BIN" start "$LEGACY_CONTAINER"
    die 'candidate Compose service was unhealthy; legacy container was restarted'
    return 1
  fi
}

deploy_candidate() {
  local digest="$1"
  preflight_candidate "$digest" || return 1
  snapshot_current_runtime || return 1
  if [[ ! -f "$COMPOSE_FILE" ]]; then
    first_compose_cutover "$digest" || return 1
  else
    if ! render_compose "$digest" || ! "$DOCKER_BIN" compose -f "$COMPOSE_FILE" --project-name siftalpha-web up -d --force-recreate || ! health_check; then
      restore_snapshot "$(latest_snapshot)" || return 1
      die 'candidate Compose service failed; prior website service was restored'
      return 1
    fi
  fi
}

rollback() {
  restore_snapshot "$(latest_snapshot)"
}

web_admin_main() {
  validate_command "$@" || return 1
  case "$1" in
    status) status ;;
    health) health_check; printf 'health: ok\n' ;;
    preflight) preflight_candidate "$2" ;;
    deploy) deploy_candidate "$2" ;;
    rollback) rollback ;;
  esac
}
