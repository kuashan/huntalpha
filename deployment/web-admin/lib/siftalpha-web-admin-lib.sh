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
readonly SIFTALPHA_WORKFLOW_ID='387611326'
readonly SIFTALPHA_WORKFLOW_PATH='.github/workflows/siftalpha-web-arm64.yml'
readonly SIFTALPHA_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SIFTALPHA_MIGRATION_GUARD="$SIFTALPHA_LIB_DIR/verify_database_migration.py"
readonly SIFTALPHA_MIGRATION_PROBE="$SIFTALPHA_LIB_DIR/migration_probe.py"
readonly SIFTALPHA_UPGRADER="$SIFTALPHA_LIB_DIR/upgrade_web_admin.py"
readonly SIFTALPHA_APPROVED_MIGRATION='formula_editor.0002_fixedindicatorstate'
readonly SIFTALPHA_ACCOUNT_MIGRATION='core.0012_auth_verification'
readonly SIFTALPHA_BREVO_ENV_DEFAULT='/etc/siftalpha/secrets/brevo.env'
readonly SIFTALPHA_COMPOSE_PROJECT_NAME='siftalpha-web'

LAST_BACKUP_PATH=''
LAST_BACKUP_SHA256=''
LAST_MIGRATION_PLAN='[]'
LAST_APPLIED_MIGRATIONS='[]'

die() { printf 'siftalpha-web-admin: %s\n' "$*" >&2; return 1; }

require_value() { [[ -n "${!1:-}" ]] || { die "missing required configuration: $1"; return 1; }; }

validate_config_metadata() {
  local owner="$1" mode="$2" effective_uid="$3" group_permission other_permission
  [[ "$owner" =~ ^[0-9]+$ && "$effective_uid" =~ ^[0-9]+$ && "$mode" =~ ^[0-7]{3}$ ]] \
    || { die 'web-admin configuration metadata is invalid'; return 1; }
  [[ "$owner" == "$effective_uid" ]] \
    || { die 'web-admin configuration must be owned by the effective user'; return 1; }
  group_permission="${mode:1:1}"
  other_permission="${mode:2:1}"
  case "$group_permission:$other_permission" in
    *2*|*3*|*6*|*7*) die 'web-admin configuration must not be writable by group or others'; return 1 ;;
  esac
}

assert_secure_config_file() {
  local config_path="$1" metadata owner mode
  [[ -f "$config_path" && ! -L "$config_path" ]] \
    || { die 'web-admin configuration must be a regular non-symlink file'; return 1; }
  metadata="$(stat -c '%u %a' -- "$config_path")" \
    || { die 'cannot inspect web-admin configuration ownership and mode'; return 1; }
  read -r owner mode <<<"$metadata"
  validate_config_metadata "$owner" "$mode" "$EUID"
}

require_safe_absolute_path() {
  local name="$1" value="${!1:-}"
  [[ "$value" == /* && "$value" != *'..'* ]] || { die "unsafe configuration path: $name"; return 1; }
}

load_config() {
  local config_path="$1"
  assert_secure_config_file "$config_path" || return 1
  [[ -r "$config_path" ]] || { die "configuration is unreadable"; return 1; }
  # Clear all deploy-sensitive values before sourcing the root-owned config.
  unset IMAGE_REPOSITORY GITHUB_REPOSITORY GITHUB_WORKFLOW_NAME RELEASE_BRANCH
  unset LEGACY_CONTAINER COMPOSE_CONTAINER DATA_DIR DATABASE_PATH LOOPBACK_PORT COMPOSE_FILE COMPOSE_TEMPLATE ENV_FILE
  unset STATE_DIR BACKUP_DIR ROLLBACK_DIR RECOVERY_DIR DOCKER_CONFIG_DIR GITHUB_TOKEN_FILE GH_BIN GH_SHA256
  unset DOCKER_BIN CURL_BIN PYTHON_BIN BREVO_ENV_FILE
  # shellcheck disable=SC1090
  source "$config_path"
  BREVO_ENV_FILE="${BREVO_ENV_FILE:-$SIFTALPHA_BREVO_ENV_DEFAULT}"
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
  for name in BREVO_ENV_FILE DATA_DIR DATABASE_PATH COMPOSE_FILE COMPOSE_TEMPLATE ENV_FILE STATE_DIR BACKUP_DIR ROLLBACK_DIR RECOVERY_DIR DOCKER_CONFIG_DIR GITHUB_TOKEN_FILE GH_BIN; do
    require_safe_absolute_path "$name" || return 1
  done
}

validate_command() {
  case "$#:${1:-}" in
    1:status|1:health|1:rollback) return 0 ;;
    2:upgrade)
      [[ "$2" =~ ^[0-9a-f]{40}$ ]] || { die 'upgrade requires a complete lowercase Git commit SHA'; return 1; }
      return 0
      ;;
    2:preflight|2:deploy|2:test-deploy)
      [[ "$2" =~ $SIFTALPHA_DIGEST_PATTERN ]] || { die 'digest must be lowercase sha256:<64 hexadecimal characters>'; return 1; }
      return 0
      ;;
    *) die 'usage: status | health | upgrade <commit-sha> | preflight <digest> | deploy <digest> | test-deploy <digest> | rollback' ;;
  esac
}

candidate_image() {
  local digest="$1"
  [[ "$digest" =~ $SIFTALPHA_DIGEST_PATTERN ]] || { die 'invalid candidate digest'; return 1; }
  printf '%s@%s\n' "$IMAGE_REPOSITORY" "$digest"
}

docker_cli() {
  DOCKER_CONFIG="$DOCKER_CONFIG_DIR" "$DOCKER_BIN" "$@"
}

ensure_state_directories() {
  mkdir -p "$STATE_DIR" "$BACKUP_DIR" "$ROLLBACK_DIR" "$RECOVERY_DIR" "$STATE_DIR/gh-cli-config" \
    || { die 'cannot create protected deployment state directories'; return 1; }
  chmod 700 "$STATE_DIR" "$BACKUP_DIR" "$ROLLBACK_DIR" "$RECOVERY_DIR" "$STATE_DIR/gh-cli-config" \
    || { die 'cannot secure protected deployment state directories'; return 1; }
  [[ -d "$STATE_DIR" && -w "$STATE_DIR" && -w "$BACKUP_DIR" && -w "$ROLLBACK_DIR" && -w "$RECOVERY_DIR" && -w "$STATE_DIR/gh-cli-config" ]] \
    || { die 'protected deployment state directories are not writable'; return 1; }
  command -v "$PYTHON_BIN" >/dev/null 2>&1 \
    && [[ -r "$SIFTALPHA_MIGRATION_GUARD" ]] \
    || { die 'database migration guard is unavailable'; return 1; }
}

image_label() {
  local image="$1" label="$2"
  docker_cli image inspect --format "{{ index .Config.Labels \"$label\" }}" "$image"
}

verify_arm64_image() {
  local image="$1" manifest
  manifest="$(docker_cli buildx imagetools inspect "$image" --raw)" || { die 'cannot inspect image manifest'; return 1; }
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
  local digest="$1" image run_id run_json temp_dir manifest_file oci_manifest_file oci_provenance_file token gh_config_dir
  image="$(candidate_image "$digest")"
  verify_gh_binary || return 1
  token="$(<"$GITHUB_TOKEN_FILE")"
  [[ -n "$token" ]] || { die 'GitHub verification token is empty'; return 1; }
  ensure_state_directories || return 1
  gh_config_dir="$STATE_DIR/gh-cli-config"
  temp_dir="$(mktemp -d "$RECOVERY_DIR/provenance.XXXXXX")" \
    || { die 'cannot create protected provenance workspace'; return 1; }
  run_json="$temp_dir/run.json"
  manifest_file="$temp_dir/siftalpha-web-build-manifest.json"
  oci_manifest_file="$temp_dir/oci-manifest.json"
  oci_provenance_file="$temp_dir/oci-provenance.json"
  docker_cli pull "$image" >/dev/null || { cleanup_provenance "$temp_dir"; return 1; }
  run_id="$(image_label "$image" 'io.siftalpha.build.run-id')"
  [[ "$run_id" =~ ^[0-9]+$ ]] || { die 'OCI run-id label is invalid'; cleanup_provenance "$temp_dir"; return 1; }
  GH_TOKEN="$token" GH_CONFIG_DIR="$gh_config_dir" DOCKER_CONFIG="$DOCKER_CONFIG_DIR" "$GH_BIN" api "repos/$GITHUB_REPOSITORY/actions/runs/$run_id" > "$run_json" || { cleanup_provenance "$temp_dir"; return 1; }
  GH_TOKEN="$token" GH_CONFIG_DIR="$gh_config_dir" DOCKER_CONFIG="$DOCKER_CONFIG_DIR" "$GH_BIN" run download "$run_id" --repo "$GITHUB_REPOSITORY" --name siftalpha-web-build-manifest --dir "$temp_dir" || { cleanup_provenance "$temp_dir"; return 1; }
  [[ -f "$manifest_file" ]] || { die 'build manifest artifact is unavailable'; cleanup_provenance "$temp_dir"; return 1; }
  if ! "$PYTHON_BIN" - "$run_json" "$manifest_file" "$digest" "$run_id" \
    "$RELEASE_BRANCH" "$GITHUB_WORKFLOW_NAME" "$SIFTALPHA_WORKFLOW_ID" "$SIFTALPHA_WORKFLOW_PATH" <<'PY'
import json
import sys

run_path, manifest_path, digest, run_id, branch, workflow_name, workflow_id, workflow_path = sys.argv[1:]
run = json.loads(open(run_path, encoding="utf-8").read())
manifest = json.loads(open(manifest_path, encoding="utf-8").read())
if run.get("status") != "completed" or run.get("conclusion") != "success":
    raise SystemExit("GitHub Actions Run is not successful")
if (
    run.get("head_branch") != branch
    or run.get("name") != workflow_name
    or str(run.get("workflow_id")) != workflow_id
    or run.get("path") != workflow_path
):
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
  docker_cli buildx imagetools inspect "$image" --format '{{json .Manifest}}' > "$oci_manifest_file" \
    || { die 'cannot read OCI image index from GHCR'; cleanup_provenance "$temp_dir"; return 1; }
  docker_cli buildx imagetools inspect "$image" --format '{{json .Provenance.SLSA}}' > "$oci_provenance_file" \
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
  ensure_state_directories || return 1
  local output
  output="$("$PYTHON_BIN" - "$DATABASE_PATH" "$BACKUP_DIR" "$RECOVERY_DIR" "$SIFTALPHA_MIGRATION_GUARD" <<'PY'
from datetime import datetime, timezone
import hashlib
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys

source_path = Path(sys.argv[1])
backup_dir = Path(sys.argv[2])
recovery_dir = Path(sys.argv[3])
guard_path = Path(sys.argv[4])
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
partial_path = backup_dir / f"siftalpha-web-{stamp}.sqlite3.partial"
backup_path = backup_dir / f"siftalpha-web-{stamp}.sqlite3"
recovery_path = recovery_dir / f"siftalpha-web-{stamp}.sqlite3"

spec = importlib.util.spec_from_file_location("web_admin_migration_guard", guard_path)
if spec is None or spec.loader is None:
    raise RuntimeError("database recovery verifier is unavailable")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

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
    guard.compare_database_contents(backup_path, recovery_path)
    size = backup_path.stat().st_size
    hasher = hashlib.sha256()
    with backup_path.open("rb") as backup_file:
        for chunk in iter(lambda: backup_file.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    print(f"backup filename: {backup_path.name}")
    print(f"backup size: {size}")
    print(f"backup sha256: {digest}")
    print("integrity_check: ok")
finally:
    recovery_path.unlink(missing_ok=True)
    partial_path.unlink(missing_ok=True)
    if 'backup_path' in locals() and backup_path.exists() and 'digest' not in locals():
        backup_path.unlink()
PY
)" || return 1
  output="$(printf '%s\n' "$output" | tr -d '\r')"
  local backup_filename
  backup_filename="$(sed -n 's/^backup filename: //p' <<<"$output" | head -n 1)"
  LAST_BACKUP_SHA256="$(sed -n 's/^backup sha256: //p' <<<"$output" | head -n 1)"
  [[ "$backup_filename" =~ ^siftalpha-web-[0-9TZ]+\.sqlite3$ && "$LAST_BACKUP_SHA256" =~ ^[0-9a-f]{64}$ ]] \
    || { die 'database backup metadata is invalid'; return 1; }
  LAST_BACKUP_PATH="$BACKUP_DIR/$backup_filename"
  printf '%s\n' "$output" | sed '/^backup filename:/d'
  printf 'backup path: %s\n' "$LAST_BACKUP_PATH"
}

verify_brevo_secret_file() {
  local path="$BREVO_ENV_FILE" dir
  dir="$(dirname -- "$path")"
  [[ -f "$path" && ! -L "$path" && -d "$dir" && ! -L "$dir" ]] || { die 'Brevo secret file unavailable'; return 1; }
  [[ "$(stat -c '%u %a' -- "$path")" == "$EUID 600" && "$(stat -c '%u %a' -- "$dir")" == "$EUID 700" ]] || { die 'Brevo secret permissions unsafe'; return 1; }
  "$PYTHON_BIN" - "$path" <<'PY'
from pathlib import Path
import sys
lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
if len(lines) != 1 or not lines[0].startswith("BREVO_API_KEY=") or len(lines[0].split("=", 1)[1]) < 20:
    raise SystemExit("Brevo secret format invalid")
PY
}

inspect_migration_plan() {
  local image="$1" database_path="$2" raw_plan validated_plan
  raw_plan="$(docker_cli run --rm --network none --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=16m \
    --cap-drop ALL --security-opt no-new-privileges \
    --mount "type=bind,src=$database_path,dst=/deploy/db.sqlite3,readonly" \
    --mount "type=bind,src=$SIFTALPHA_MIGRATION_PROBE,dst=/deploy/migration_probe.py,readonly" \
    --env-file "$ENV_FILE" --env HUNTALPHA_DATABASE_PATH=/deploy/db.sqlite3 \
    "$image" python /deploy/migration_probe.py 2>&1)" \
    || { die 'candidate migration plan inspection failed'; return 1; }
  validated_plan="$(printf '%s\n' "$raw_plan" | "$PYTHON_BIN" "$SIFTALPHA_MIGRATION_GUARD" validate-state)" \
    || { die 'candidate contains an unapproved Django migration plan'; return 1; }
  case "$validated_plan" in
    '{"pending":[],"applied":[]}') LAST_MIGRATION_PLAN='[]'; LAST_APPLIED_MIGRATIONS='[]' ;;
    "{\"pending\":[\"$SIFTALPHA_APPROVED_MIGRATION\"],\"applied\":[]}")
      LAST_MIGRATION_PLAN="[\"$SIFTALPHA_APPROVED_MIGRATION\"]"; LAST_APPLIED_MIGRATIONS='[]' ;;
    "{\"pending\":[],\"applied\":[\"$SIFTALPHA_APPROVED_MIGRATION\"]}")
      LAST_MIGRATION_PLAN='[]'; LAST_APPLIED_MIGRATIONS="[\"$SIFTALPHA_APPROVED_MIGRATION\"]" ;;
    "{\"pending\":[\"$SIFTALPHA_ACCOUNT_MIGRATION\"],\"applied\":[\"$SIFTALPHA_APPROVED_MIGRATION\"]}")
      LAST_MIGRATION_PLAN="[\"$SIFTALPHA_ACCOUNT_MIGRATION\"]"; LAST_APPLIED_MIGRATIONS="[\"$SIFTALPHA_APPROVED_MIGRATION\"]" ;;
    "{\"pending\":[],\"applied\":[\"$SIFTALPHA_APPROVED_MIGRATION\",\"$SIFTALPHA_ACCOUNT_MIGRATION\"]}")
      LAST_MIGRATION_PLAN='[]'; LAST_APPLIED_MIGRATIONS="[\"$SIFTALPHA_APPROVED_MIGRATION\",\"$SIFTALPHA_ACCOUNT_MIGRATION\"]" ;;
    *) die 'candidate migration plan validation returned an invalid result'; return 1 ;;
  esac
}

cleanup_migration_workspace() {
  local workspace="$1"
  [[ "$workspace" == "$RECOVERY_DIR"/migration.* && -d "$workspace" && ! -L "$workspace" ]] \
    || { die 'refusing to clean an unrecognized migration recovery directory'; return 1; }
  find "$workspace" -depth -delete || { die 'cannot clean migration recovery copy'; return 1; }
}

LAST_MIGRATED_DATABASE=''
LAST_MIGRATION_WORKSPACE=''

rehearse_migrations() {
  local image="$1" source_database="$2" workspace migrated_database post_plan approved_plan="$LAST_MIGRATION_PLAN" approved_applied="$LAST_APPLIED_MIGRATIONS"
  workspace="$(mktemp -d "$RECOVERY_DIR/migration.XXXXXX")" \
    || { die 'cannot create isolated migration recovery copy'; return 1; }
  chmod 700 "$workspace" || { cleanup_migration_workspace "$workspace" || true; die 'cannot secure migration recovery copy'; return 1; }
  migrated_database="$workspace/db.sqlite3"
  if ! "$PYTHON_BIN" "$SIFTALPHA_MIGRATION_GUARD" copy "$source_database" "$migrated_database"; then
    cleanup_migration_workspace "$workspace" || true
    die 'cannot create isolated migration database copy'
    return 1
  fi
  if ! docker_cli run --rm --network none --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=16m \
    --cap-drop ALL --security-opt no-new-privileges \
    --mount "type=bind,src=$workspace,dst=/deploy" \
    --env-file "$ENV_FILE" --env HUNTALPHA_DATABASE_PATH=/deploy/db.sqlite3 --env HOME=/tmp \
    "$image" python manage.py migrate --noinput >/dev/null 2>&1; then
    cleanup_migration_workspace "$workspace" || true
    die 'Django migration rehearsal failed on the isolated copy'
    return 1
  fi
  if ! "$PYTHON_BIN" "$SIFTALPHA_MIGRATION_GUARD" check-integrity "$migrated_database" >/dev/null; then
    cleanup_migration_workspace "$workspace" || true
    die 'isolated migrated database failed integrity check'
    return 1
  fi
  if ! "$PYTHON_BIN" "$SIFTALPHA_MIGRATION_GUARD" validate-result \
    "$source_database" "$migrated_database" >/dev/null; then
    cleanup_migration_workspace "$workspace" || true
    die 'isolated migration produced changes outside the approved Task 012 database scope'
    return 1
  fi
  if ! "$PYTHON_BIN" "$SIFTALPHA_MIGRATION_GUARD" compare "$source_database" "$migrated_database" >/dev/null; then
    cleanup_migration_workspace "$workspace" || true
    die 'migration changed protected user or private-data tables'
    return 1
  fi
  if ! inspect_migration_plan "$image" "$migrated_database"; then
    cleanup_migration_workspace "$workspace" || true
    return 1
  fi
  post_plan="$LAST_MIGRATION_PLAN"
  if [[ "$post_plan" != '[]' ]]; then
    cleanup_migration_workspace "$workspace" || true
    die 'candidate still has pending migrations after isolated rehearsal'
    return 1
  fi
  LAST_MIGRATION_PLAN="$approved_plan"
  LAST_APPLIED_MIGRATIONS="$approved_applied"
  LAST_MIGRATED_DATABASE="$migrated_database"
  LAST_MIGRATION_WORKSPACE="$workspace"
}

audit_deployment_event() {
  local event="$1" result="$2" digest="${3:--}" migrations="${4:-$LAST_MIGRATION_PLAN}"
  local backup_path="${LAST_BACKUP_PATH:--}" backup_sha="${LAST_BACKUP_SHA256:--}"
  ensure_state_directories || return 1
  printf '%s event=%s result=%s digest=%s backup=%s backup_sha256=%s pending_migrations=%s applied_migrations=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$event" "$result" "$digest" \
    "$backup_path" "$backup_sha" "$migrations" "$LAST_APPLIED_MIGRATIONS" >> "$STATE_DIR/deployment-audit.log" \
    || { die 'cannot record protected deployment audit event'; return 1; }
  chmod 600 "$STATE_DIR/deployment-audit.log" \
    || { die 'cannot secure protected deployment audit log'; return 1; }
}

health_clock_seconds() {
  printf '%s\n' "$SECONDS"
}

health_curl() {
  local deadline="$1" max_time
  shift
  if [[ -n "$deadline" ]]; then
    local now
    now="$(health_clock_seconds)" || return 1
    max_time=$((deadline - now))
    (( max_time > 0 )) || return 28
  else
    max_time=10
  fi
  "$CURL_BIN" --max-time "$max_time" --fail --silent --show-error "$@"
}

health_check() {
  local deadline="${1:-}" base="http://$LOOPBACK_PORT" page static_path self_test_container self_test_probe attempt
  if [[ -n "${SELF_TEST_NETWORK_NAME:-}" ]]; then
    self_test_container="$(running_container)" || return 1
    self_test_probe="$(printf '%s\n' \
      'import re' \
      'from urllib.request import urlopen' \
      'base = "http://127.0.0.1:8000"' \
      'for path in ("/", "/account", "/account/", "/healthz/"):' \
      '    with urlopen(base + path, timeout=4) as response:' \
      '        if not 200 <= response.status < 400: raise SystemExit(1)' \
      'with urlopen(base + "/", timeout=4) as response:' \
      '    page = response.read().decode("utf-8", "replace")' \
      'match = re.search("src=" + chr(34) + r"(/static/[A-Za-z0-9._/-]+)" + chr(34), page)' \
      'if not match or ".." in match.group(1): raise SystemExit(1)' \
      'with urlopen(base + match.group(1), timeout=4) as response:' \
      '    response.read(1)')"
    for attempt in {1..20}; do
      if docker_cli exec "$self_test_container" python -c "$self_test_probe" >/dev/null 2>&1; then
        return 0
      fi
      sleep 1
    done
    die 'isolated website container failed health checks'
    return 1
  fi
  for page in / /account /account/ /healthz/; do
    health_curl "$deadline" "$base$page" >/dev/null || { die "health endpoint failed: $page"; return 1; }
  done
  static_path="$(health_curl "$deadline" "$base/" | sed -n 's|.*src="\(/static/[A-Za-z0-9._/-]*\)".*|\1|p' | head -n 1)"
  [[ "$static_path" =~ ^/static/[A-Za-z0-9._/-]+$ && "$static_path" != *..* ]] || { die 'homepage has no safe static asset reference'; return 1; }
  health_curl "$deadline" "$base$static_path" >/dev/null || { die 'homepage static asset failed'; return 1; }
}

wait_for_health() {
  local budget_seconds="${1:-60}" start deadline now remaining
  [[ "$budget_seconds" =~ ^[1-9][0-9]*$ ]] || { die 'health readiness budget must be a positive integer'; return 1; }
  # Compose starts containers asynchronously; probe readiness once per second,
  # but keep the isolated self-test retry budget instead of nesting it.
  if [[ -n "${SELF_TEST_NETWORK_NAME:-}" ]]; then
    health_check
    return $?
  fi
  start="$(health_clock_seconds)" || return 1
  deadline=$((start + budget_seconds))
  while :; do
    if health_check "$deadline" >/dev/null 2>&1; then
      return 0
    fi
    now="$(health_clock_seconds)" || return 1
    (( now < deadline )) || break
    remaining=$((deadline - now))
    sleep "$((remaining < 1 ? remaining : 1))"
  done
  die "website did not become healthy within ${budget_seconds} seconds"
}

candidate_startup_diagnostics() {
  local summary
  if summary="$(docker_cli logs --tail 200 "$COMPOSE_CONTAINER" 2>/dev/null | "$PYTHON_BIN" -c '
import re
import sys

patterns = {
    "tracebacks": re.compile(r"Traceback \(most recent call last\)", re.I),
    "permission_errors": re.compile(r"PermissionError|permission denied|readonly database", re.I),
    "database_errors": re.compile(r"sqlite|OperationalError|DatabaseError", re.I),
    "import_errors": re.compile(r"ImportError|ModuleNotFoundError", re.I),
    "django_config_errors": re.compile(r"ImproperlyConfigured", re.I),
    "server_start_markers": re.compile(r"Starting gunicorn|Listening at|Booting worker", re.I),
}
counts = {name: 0 for name in patterns}
for line in sys.stdin:
    for name, pattern in patterns.items():
        counts[name] += bool(pattern.search(line))
print(" ".join(f"{name}={count}" for name, count in counts.items()))
')"; then
    printf 'candidate startup diagnostics (last 200 log lines; categories only): %s\n' "$summary"
  else
    printf 'candidate startup diagnostics: container logs unavailable\n'
  fi
}

fixed_container_state() {
  local container="$1" matches state
  matches="$(docker_cli container ls --all --filter "name=^/${container}$" --format '{{.Names}}')" \
    || { die 'cannot enumerate fixed website containers'; return 1; }
  if [[ -z "$matches" ]]; then
    printf 'absent\n'
    return 0
  fi
  [[ "$matches" == "$container" ]] || { die 'fixed website container lookup was ambiguous'; return 1; }
  state="$(docker_cli inspect --format '{{.State.Status}}' "$container")" \
    || { die 'cannot inspect fixed website container state'; return 1; }
  case "$state" in
    running|exited|dead) printf '%s\n' "$state" ;;
    *) die 'fixed website container is in an unsafe or unknown state'; return 1 ;;
  esac
}

current_container() {
  local compose_status legacy_status
  compose_status="$(fixed_container_state "$COMPOSE_CONTAINER")" || return 1
  legacy_status="$(fixed_container_state "$LEGACY_CONTAINER")" || return 1
  if [[ "$compose_status" == running && "$legacy_status" == running ]]; then
    die 'both fixed website containers are running; refusing to select a deployment runtime'
    return 1
  elif [[ "$compose_status" == running ]]; then
    printf '%s\n' "$COMPOSE_CONTAINER"
  elif [[ "$legacy_status" == running ]]; then
    printf '%s\n' "$LEGACY_CONTAINER"
  elif [[ "$compose_status" != absent ]]; then
    printf '%s\n' "$COMPOSE_CONTAINER"
  elif [[ "$legacy_status" != absent ]]; then
    printf '%s\n' "$LEGACY_CONTAINER"
  else
    die 'neither fixed website container exists'
  fi
}

running_container() {
  local container state
  container="$(current_container)" || return 1
  state="$(docker_cli inspect --format '{{.State.Status}}' "$container")" \
    || { die 'cannot inspect selected website container state'; return 1; }
  [[ "$state" == running ]] || { die 'no fixed website container is running; refusing deployment'; return 1; }
  printf '%s\n' "$container"
}

ensure_legacy_service() {
  local state
  state="$(fixed_container_state "$LEGACY_CONTAINER")" || return 1
  case "$state" in
    running)
      ;;
    exited|dead)
      docker_cli start "$LEGACY_CONTAINER" >/dev/null \
        || { die 'cannot restart the retained legacy website'; return 1; }
      ;;
    *)
      die 'legacy website is absent or in an unsafe state'; return 1 ;;
  esac
  wait_for_health || { die 'legacy website is not healthy'; return 1; }
}

restore_legacy_service() {
  docker_cli start "$LEGACY_CONTAINER" >/dev/null 2>&1 || true
  wait_for_health || { die 'legacy website could not be confirmed healthy'; return 1; }
}

verify_candidate_image() {
  local digest="$1" expected actual container
  expected="$(candidate_image "$digest")" || return 1
  container="$(current_container)" || return 1
  [[ "$container" == "$COMPOSE_CONTAINER" ]] \
    || { die 'candidate Compose container is not the active website'; return 1; }
  actual="$(docker_cli inspect --format '{{.Config.Image}}' "$COMPOSE_CONTAINER")" \
    || { die 'cannot inspect candidate website image reference'; return 1; }
  [[ "$actual" == "$expected" ]] \
    || { die 'running website image does not match the requested immutable digest'; return 1; }
}

snapshot_current_runtime() {
  local container runtime config_image image_id snapshot created
  ensure_state_directories || return 1
  container="$(running_container)" || return 1
  if [[ "$container" == "$LEGACY_CONTAINER" ]]; then
    runtime='legacy'
  else
    runtime='compose'
  fi
  config_image="$(docker_cli inspect --format '{{.Config.Image}}' "$container")" || { die 'cannot inspect current website image'; return 1; }
  image_id="$(docker_cli inspect --format '{{.Image}}' "$container")" || { die 'cannot inspect current website image ID'; return 1; }
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
  case "$key" in runtime|container|config_image|image_id|data_dir|database_migrations|database_backup|database_backup_sha256) ;; *) die 'invalid deployment snapshot field'; return 1 ;; esac
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
  local snapshot="$1" runtime image migrations backup backup_sha actual_sha
  runtime="$(snapshot_value "$snapshot" runtime)" || return 1
  migrations="$(snapshot_value "$snapshot" database_migrations)"
  migrations="${migrations:-[]}"
  case "$migrations" in
    '[]') ;;
    "[\"$SIFTALPHA_APPROVED_MIGRATION\"]") ;;
    "[\"$SIFTALPHA_APPROVED_MIGRATION\",\"$SIFTALPHA_ACCOUNT_MIGRATION\"]") ;;
    *) die 'database migration history is not compatible with automatic rollback'; return 1 ;;
  esac
  if [[ "$migrations" != '[]' ]]; then
    backup="$(snapshot_value "$snapshot" database_backup)"
    backup_sha="$(snapshot_value "$snapshot" database_backup_sha256)"
    [[ "$backup" == "$BACKUP_DIR"/*.sqlite3 && -f "$backup" && "$backup_sha" =~ ^[0-9a-f]{64}$ ]] \
      || { die 'verified deployment database backup is unavailable; refusing application rollback'; return 1; }
    actual_sha="$(sha256sum "$backup" | awk '{print $1}')"
    [[ "$actual_sha" == "$backup_sha" ]] \
      || { die 'deployment database backup SHA-256 mismatch; refusing application rollback'; return 1; }
    "$PYTHON_BIN" "$SIFTALPHA_MIGRATION_GUARD" check-integrity "$backup" >/dev/null \
      || { die 'deployment database backup integrity check failed; refusing application rollback'; return 1; }
  fi
  case "$runtime" in
    legacy)
      [[ "$(snapshot_value "$snapshot" container)" == "$LEGACY_CONTAINER" ]] || { die 'legacy snapshot container mismatch'; return 1; }
      docker_cli rm -f "$COMPOSE_CONTAINER" >/dev/null 2>&1 || true
      docker_cli start "$LEGACY_CONTAINER" || { die 'cannot restart retained legacy website container'; return 1; }
      ;;
    compose)
      image="$(snapshot_value "$snapshot" config_image)" || return 1
      [[ "$image" == "$IMAGE_REPOSITORY"@sha256:* ]] || { die 'Compose snapshot image is not immutable'; return 1; }
      render_compose "${image#*@}" || return 1
      docker_cli compose -f "$COMPOSE_FILE" --project-name "${COMPOSE_PROJECT_NAME:-$SIFTALPHA_COMPOSE_PROJECT_NAME}" up -d --force-recreate || { die 'cannot restore prior Compose website service'; return 1; }
      ;;
    *) die 'deployment snapshot runtime is invalid'; return 1 ;;
  esac
  wait_for_health || { die 'restored website service is unhealthy'; return 1; }
  printf 'rollback: restored snapshot=%s\n' "$snapshot"
  if [[ "$migrations" != '[]' ]]; then
    printf 'database rollback: retained reviewed additive migration %s; it is backward-compatible with the restored application\n' "$SIFTALPHA_APPROVED_MIGRATION"
  else
    printf 'database rollback: no schema migration to reverse\n'
  fi
}

status() {
  local container image state
  container="$(current_container)"
  state="$(docker_cli inspect --format '{{.State.Status}}' "$container")"
  image="$(docker_cli inspect --format '{{.Config.Image}}' "$container")"
  printf 'container: %s\nstate: %s\nimage: %s\nport: %s\n' "$container" "$state" "$image" "$LOOPBACK_PORT"
}

preflight_candidate() {
  local digest="$1" image planned
  [[ "$digest" =~ $SIFTALPHA_DIGEST_PATTERN ]] || { die 'invalid candidate digest'; return 1; }
  LAST_BACKUP_PATH=''
  LAST_BACKUP_SHA256=''
  LAST_MIGRATION_PLAN='[]'
  LAST_APPLIED_MIGRATIONS='[]'
  image="$(candidate_image "$digest")"
  if ! verify_brevo_secret_file; then
    audit_deployment_event preflight blocked "$digest" "$LAST_MIGRATION_PLAN" || true
    return 1
  fi
  if ! health_check; then
    audit_deployment_event preflight blocked "$digest" "$LAST_MIGRATION_PLAN" || true
    return 1
  fi
  if [[ ! -r "$DATABASE_PATH" || ! -d "$DATA_DIR" ]]; then
    die 'website data bind is unavailable'
    audit_deployment_event preflight blocked "$digest" "$LAST_MIGRATION_PLAN" || true
    return 1
  fi
  if ! verify_trusted_source "$digest" || ! verify_arm64_image "$image" \
    || ! backup_and_restore_check || ! inspect_migration_plan "$image" "$LAST_BACKUP_PATH"; then
    audit_deployment_event preflight blocked "$digest" "$LAST_MIGRATION_PLAN" || true
    return 1
  fi
  planned="$LAST_MIGRATION_PLAN"
  local database_state="$LAST_APPLIED_MIGRATIONS"
  if [[ "$planned" != '[]' ]]; then
    if ! rehearse_migrations "$image" "$LAST_BACKUP_PATH"; then
      audit_deployment_event preflight blocked "$digest" "$planned" || true
      return 1
    fi
    if ! cleanup_migration_workspace "$LAST_MIGRATION_WORKSPACE"; then
      audit_deployment_event preflight blocked "$digest" "$planned" || true
      return 1
    fi
    LAST_MIGRATION_WORKSPACE=''
    LAST_MIGRATED_DATABASE=''
  else
    if [[ "$database_state" == '[]' ]]; then
      printf 'migration plan: none\n'
    else
      printf 'migration plan: none; reviewed migration already applied\n'
    fi
  fi
  LAST_MIGRATION_PLAN="$planned"
  audit_deployment_event preflight ok "$digest" "$planned" || return 1
  printf 'preflight: ok\n'
}

render_compose() {
  local digest="$1" image project_name="${COMPOSE_PROJECT_NAME:-$SIFTALPHA_COMPOSE_PROJECT_NAME}" self_test_network="${SELF_TEST_NETWORK_NAME:-}" self_test_id="${SELF_TEST_ID:-}"
  image="$(candidate_image "$digest")"
  [[ -r "$COMPOSE_TEMPLATE" ]] || { die 'Compose template is unavailable'; return 1; }
  "$PYTHON_BIN" - "$COMPOSE_TEMPLATE" "$COMPOSE_FILE" "$image" "$COMPOSE_CONTAINER" "$DATA_DIR" "$ENV_FILE" "$BREVO_ENV_FILE" "$LOOPBACK_PORT" "$self_test_network" "$self_test_id" <<'PY'
from pathlib import Path
import sys

template_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
image, container, data_dir, env_file, brevo_env_file, port, self_test_network, self_test_id = sys.argv[3:]
content = template_path.read_text(encoding="utf-8")
for key, value in {
    "__IMAGE_REFERENCE__": image,
    "__COMPOSE_CONTAINER__": container,
    "__DATA_DIR__": data_dir,
    "__ENV_FILE__": env_file,
    "__BREVO_ENV_FILE__": brevo_env_file,
    "__LOOPBACK_PORT__": port,
    "__SELF_TEST_NETWORK__": self_test_network,
    "__SELF_TEST_ID__": self_test_id,
}.items():
    content = content.replace(key, value)
if "__" in content:
    raise SystemExit("unresolved Compose template placeholder")
if "selftest" in template_path.name and (not self_test_network or not self_test_id):
    raise SystemExit("isolated Compose template requires its fixed self-test network and label")
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(content, encoding="utf-8")
PY
}

first_compose_cutover() {
  local digest="$1" legacy_status
  if ! render_compose "$digest"; then
    if ! ensure_legacy_service; then
      die 'candidate Compose rendering failed and the legacy website could not be confirmed healthy'
      return 1
    fi
    die 'candidate Compose configuration could not be rendered; legacy website was retained'
    return 1
  fi
  if ! docker_cli stop "$LEGACY_CONTAINER"; then
    if ! restore_legacy_service; then
      die 'legacy website stop failed and the prior service could not be confirmed healthy'
      return 1
    fi
    die 'could not stop the legacy website; candidate was not started'
    return 1
  fi
  if ! legacy_status="$(fixed_container_state "$LEGACY_CONTAINER")"; then
    if ! restore_legacy_service; then
      die 'legacy website state could not be verified after stop and service recovery failed'
      return 1
    fi
    die 'legacy website state could not be verified after stop; candidate was not started'
    return 1
  fi
  if [[ "$legacy_status" != exited && "$legacy_status" != dead ]]; then
    if ! restore_legacy_service; then
      die 'legacy website did not stop and could not be confirmed healthy'
      return 1
    fi
    die 'legacy website is still active; candidate was not started'
    return 1
  fi
  if ! docker_cli compose -f "$COMPOSE_FILE" --project-name "${COMPOSE_PROJECT_NAME:-$SIFTALPHA_COMPOSE_PROJECT_NAME}" up -d --force-recreate; then
    docker_cli rm -f "$COMPOSE_CONTAINER" || true
    docker_cli start "$LEGACY_CONTAINER" || { die 'candidate failed to start and legacy website could not be restarted'; return 1; }
    wait_for_health || { die 'candidate failed to start and legacy website did not recover'; return 1; }
    die 'candidate Compose service failed; legacy container was restarted'
    return 1
  fi
  if ! wait_for_health; then
    candidate_startup_diagnostics
    docker_cli rm -f "$COMPOSE_CONTAINER" || true
    docker_cli start "$LEGACY_CONTAINER" || { die 'candidate was unhealthy and legacy website could not be restarted'; return 1; }
    wait_for_health || { die 'candidate was unhealthy and legacy website did not recover'; return 1; }
    die 'candidate Compose service was unhealthy; legacy container was restarted'
    return 1
  fi
  if ! verify_candidate_image "$digest"; then
    docker_cli rm -f "$COMPOSE_CONTAINER" >/dev/null 2>&1 || true
    docker_cli start "$LEGACY_CONTAINER" || { die 'candidate image did not match and legacy website could not be restarted'; return 1; }
    wait_for_health || { die 'candidate image did not match and legacy website did not recover'; return 1; }
    die 'candidate image did not match the requested immutable digest; legacy website was restarted'
    return 1
  fi
}

cleanup_isolated_deploy_test() {
  local container label
  if [[ "${SELF_TEST_CANDIDATE_CREATED:-no}" == yes ]] \
    && docker_cli container inspect "$COMPOSE_CONTAINER" >/dev/null 2>&1; then
    label="$(docker_cli inspect --format '{{ index .Config.Labels "io.siftalpha.web-admin.selftest" }}' "$COMPOSE_CONTAINER")" \
      || { die 'cannot verify isolated candidate container label'; return 1; }
    [[ "$label" == "$SELF_TEST_ID" ]] \
      || { die 'isolated candidate container label changed; refusing cleanup'; return 1; }
    docker_cli rm -f "$COMPOSE_CONTAINER" >/dev/null \
      || { die 'cannot remove isolated candidate container'; return 1; }
  fi
  if [[ "${SELF_TEST_LEGACY_CREATED:-no}" == yes ]] \
    && docker_cli container inspect "$LEGACY_CONTAINER" >/dev/null 2>&1; then
    label="$(docker_cli inspect --format '{{ index .Config.Labels "io.siftalpha.web-admin.selftest" }}' "$LEGACY_CONTAINER")" \
      || { die 'cannot verify isolated prior-version container label'; return 1; }
    [[ "$label" == "$SELF_TEST_ID" ]] \
      || { die 'isolated prior-version container label changed; refusing cleanup'; return 1; }
    docker_cli rm -f "$LEGACY_CONTAINER" >/dev/null \
      || { die 'cannot remove isolated prior-version container'; return 1; }
  fi
  if [[ "${SELF_TEST_NETWORK_CREATED:-no}" == yes ]]; then
    docker_cli network rm "$SELF_TEST_NETWORK_NAME" >/dev/null \
      || { die 'cannot remove isolated self-test network'; return 1; }
  fi
  local workspace="${SELF_TEST_WORKSPACE:-}"
  if [[ -n "$workspace" ]]; then
    [[ "$workspace" == "$SELF_TEST_PARENT"/selftest.* && -d "$workspace" && ! -L "$workspace" ]] \
      || { die 'refusing to clean an unrecognized self-test directory'; return 1; }
    find "$workspace" -depth -delete || { die 'cannot clean isolated self-test data'; return 1; }
  fi
}

abort_isolated_deploy_test() {
  local message="$1"
  cleanup_isolated_deploy_test || return 1
  die "$message"
  return 1
}

isolated_deploy_and_rollback_test() {
  local digest="$1" image original_container original_state original_image_id original_platform
  local workspace network project legacy candidate self_test_state
  local SELF_TEST_PARENT="$RECOVERY_DIR" SELF_TEST_WORKSPACE='' SELF_TEST_NETWORK_NAME=''
  local SELF_TEST_NETWORK_CREATED=no SELF_TEST_LEGACY_CREATED=no SELF_TEST_CANDIDATE_CREATED=no
  local SELF_TEST_ID="web-admin-selftest-$BASHPID"
  [[ "$digest" =~ $SIFTALPHA_DIGEST_PATTERN ]] || { die 'invalid candidate digest'; return 1; }
  ensure_state_directories || return 1
  original_container="$(running_container)" || return 1
  original_state="$(docker_cli inspect --format '{{.State.Status}}' "$original_container")" \
    || { die 'cannot inspect the current website for isolated self-test'; return 1; }
  [[ "$original_state" == running ]] || { die 'current website is not running; isolated self-test is blocked'; return 1; }
  original_image_id="$(docker_cli inspect --format '{{.Image}}' "$original_container")" \
    || { die 'cannot identify the current website image for rollback test'; return 1; }
  [[ "$original_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || { die 'current website image ID is invalid; isolated rollback test is blocked'; return 1; }
  original_platform="$(docker_cli image inspect --format '{{.Os}}/{{.Architecture}}' "$original_image_id")" \
    || { die 'cannot verify the current website rollback image'; return 1; }
  [[ "$original_platform" == linux/arm64 ]] \
    || { die 'current website rollback image is not linux/arm64'; return 1; }

  image="$(candidate_image "$digest")"

  SELF_TEST_WORKSPACE="$(mktemp -d "$SELF_TEST_PARENT/selftest.XXXXXX")" \
    || { die 'cannot create isolated self-test workspace'; return 1; }
  SELF_TEST_NETWORK_CREATED=no
  SELF_TEST_LEGACY_CREATED=no
  SELF_TEST_CANDIDATE_CREATED=no
  workspace="$SELF_TEST_WORKSPACE"
  network="siftalpha-web-admin-selftest-$BASHPID"
  project="$network"
  legacy="$network-old"
  candidate="$network-new"
  SELF_TEST_NETWORK_NAME="$network"
  [[ "$network" =~ ^[a-z0-9][a-z0-9_.-]*$ && "$project" =~ ^[a-z0-9][a-z0-9_.-]*$ \
    && "$legacy" =~ ^[a-z0-9][a-z0-9_.-]*$ && "$candidate" =~ ^[a-z0-9][a-z0-9_.-]*$ ]] \
    || { cleanup_isolated_deploy_test || true; die 'generated self-test resource name is invalid'; return 1; }
  if docker_cli container inspect "$legacy" >/dev/null 2>&1 \
    || docker_cli container inspect "$candidate" >/dev/null 2>&1 \
    || docker_cli network inspect "$network" >/dev/null 2>&1; then
    cleanup_isolated_deploy_test || true
    die 'an isolated self-test resource name is already in use; nothing was changed'
    return 1
  fi
  if ! docker_cli network create --internal \
    --label io.siftalpha.web-admin.selftest=managed "$network" >/dev/null; then
    cleanup_isolated_deploy_test || true
    die 'cannot create isolated egress-disabled self-test network'
    return 1
  fi
  SELF_TEST_NETWORK_CREATED=yes

  local LEGACY_CONTAINER="$legacy"
  local COMPOSE_CONTAINER="$candidate"
  local COMPOSE_PROJECT_NAME="$project"
  local DATA_DIR="$workspace/data"
  local DATABASE_PATH="$workspace/data/db.sqlite3"
  local COMPOSE_FILE="$workspace/compose.yaml"
  local COMPOSE_TEMPLATE="$SIFTALPHA_LIB_DIR/compose.selftest.yaml.template"
  local ENV_FILE="$workspace/self-test.env"
  local LOOPBACK_PORT='127.0.0.1:19092'
  local STATE_DIR="$workspace/state"
  local BACKUP_DIR="$workspace/state/backups"
  local ROLLBACK_DIR="$workspace/state/rollbacks"
  local RECOVERY_DIR="$workspace/state/recovery-checks"
  local LAST_BACKUP_PATH=''
  local LAST_BACKUP_SHA256=''
  local LAST_MIGRATION_PLAN='[]'
  local LAST_APPLIED_MIGRATIONS='[]'
  local LAST_MIGRATED_DATABASE=''
  local LAST_MIGRATION_WORKSPACE=''

  chmod 700 "$workspace" || { abort_isolated_deploy_test 'cannot secure isolated self-test workspace'; return 1; }
  mkdir -p "$DATA_DIR" "$STATE_DIR" "$BACKUP_DIR" "$ROLLBACK_DIR" "$RECOVERY_DIR" \
    || { abort_isolated_deploy_test 'cannot prepare isolated self-test directories'; return 1; }
  printf 'DJANGO_SECRET_KEY=siftalpha-web-self-test-only\nDJANGO_DEBUG=0\nHUNTALPHA_ALLOWED_HOSTS=127.0.0.1,localhost\nHUNTALPHA_DATABASE_PATH=/data/db.sqlite3\n' \
    > "$ENV_FILE" || { abort_isolated_deploy_test 'cannot create synthetic self-test settings'; return 1; }
  chmod 600 "$ENV_FILE" || { abort_isolated_deploy_test 'cannot secure synthetic self-test settings'; return 1; }

  if ! docker_cli run --rm --network none --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=16m --cap-drop ALL --security-opt no-new-privileges \
    --mount "type=bind,src=$DATA_DIR,dst=/deploy" \
    --env-file "$ENV_FILE" --env HUNTALPHA_DATABASE_PATH=/deploy/db.sqlite3 --env HOME=/tmp \
    "$original_image_id" python manage.py migrate --noinput >/dev/null 2>&1; then
    abort_isolated_deploy_test 'cannot initialize a synthetic rollback database with the retained application image'
    return 1
  fi
  SELF_TEST_LEGACY_CREATED=yes
  if ! docker_cli run --detach --name "$legacy" \
    --label "io.siftalpha.web-admin.selftest=$SELF_TEST_ID" \
    --network "$network" \
    --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m --cap-drop ALL --security-opt no-new-privileges \
    --mount "type=bind,src=$DATA_DIR,dst=/data" \
    --env-file "$ENV_FILE" --env HUNTALPHA_DATABASE_PATH=/data/db.sqlite3 --env HOME=/tmp \
    "$original_image_id" >/dev/null; then
    abort_isolated_deploy_test 'cannot start isolated prior-version test container'
    return 1
  fi
  health_check || { abort_isolated_deploy_test 'isolated prior-version container failed health checks'; return 1; }

  SELF_TEST_CANDIDATE_CREATED=yes
  if ! deploy_candidate "$digest"; then
    abort_isolated_deploy_test 'isolated controlled deployment failed; production website was not touched'
    return 1
  fi
  if ! rollback; then
    abort_isolated_deploy_test 'isolated application rollback failed; production website was not touched'
    return 1
  fi
  self_test_state="$LAST_APPLIED_MIGRATIONS"
  if ! inspect_migration_plan "$image" "$DATABASE_PATH"; then
    abort_isolated_deploy_test 'cannot verify isolated database after application rollback'
    return 1
  fi
  if [[ "$LAST_MIGRATION_PLAN" != '[]' || "$LAST_APPLIED_MIGRATIONS" != "$self_test_state" ]]; then
    abort_isolated_deploy_test 'isolated rollback did not preserve the reviewed database state'
    return 1
  fi
  if ! cleanup_isolated_deploy_test; then
    die 'isolated deploy/rollback passed but its temporary resources could not be fully cleaned'
    return 1
  fi
  SELF_TEST_WORKSPACE=''
  printf 'test-deploy: isolated deploy and rollback passed; production container and database were not mounted or switched\n'
}

record_snapshot_database_state() {
  local snapshot="$1" migrations="$2" staged
  case "$migrations" in
    '[]'|"[\"$SIFTALPHA_APPROVED_MIGRATION\"]") ;;
    *) die 'refusing to record an unapproved database migration'; return 1 ;;
  esac
  [[ "$LAST_BACKUP_PATH" == "$BACKUP_DIR"/*.sqlite3 && "$LAST_BACKUP_SHA256" =~ ^[0-9a-f]{64}$ ]] \
    || { die 'cannot record an unverified database backup'; return 1; }
  staged="$(mktemp "$snapshot/.metadata.XXXXXX")" \
    || { die 'cannot stage database rollback metadata'; return 1; }
  if ! awk '!/^database_migrations=/ && !/^database_backup=/ && !/^database_backup_sha256=/' \
    "$snapshot/metadata" > "$staged"; then
    rm -f "$staged"
    die 'cannot stage database rollback metadata'
    return 1
  fi
  if ! {
    printf 'database_migrations=%s\n' "$migrations"
    printf 'database_backup=%s\n' "$LAST_BACKUP_PATH"
    printf 'database_backup_sha256=%s\n' "$LAST_BACKUP_SHA256"
  } >> "$staged"; then
    rm -f "$staged"
    die 'cannot stage database rollback metadata'
    return 1
  fi
  chmod 600 "$staged" && mv -f "$staged" "$snapshot/metadata" \
    || { rm -f "$staged"; die 'cannot securely record database rollback metadata'; return 1; }
}

restart_after_migration_preflight_failure() {
  local container="$1"
  docker_cli start "$container" >/dev/null \
    || { die 'cannot restart the original website container'; return 1; }
  wait_for_health || { die 'original website did not recover after migration was stopped'; return 1; }
  printf 'migration recovery: no production migration was applied; original container restarted\n'
}

deploy_candidate() {
  local digest="$1" image planned database_state snapshot container state runtime
  preflight_candidate "$digest" || return 1
  image="$(candidate_image "$digest")"
  planned="$LAST_MIGRATION_PLAN"
  database_state="$LAST_APPLIED_MIGRATIONS"
  snapshot_current_runtime || return 1
  snapshot="$(latest_snapshot)" || return 1
  runtime="$(snapshot_value "$snapshot" runtime)" || return 1
  if [[ "$planned" == '[]' ]]; then
    record_snapshot_database_state "$snapshot" "$database_state" || return 1
    if [[ "$database_state" != '[]' ]]; then
      printf 'migration plan: none; reviewed migration already applied\n'
    else
      printf 'migration plan: none; continuing with the existing deployment path\n'
    fi
  else
    container="$(running_container)" || return 1
    state="$(docker_cli inspect --format '{{.State.Status}}' "$container")" \
      || { die 'cannot inspect current website state'; return 1; }
    [[ "$state" == 'running' ]] || { die 'website container is not running; refusing migration'; return 1; }
    docker_cli stop "$container" >/dev/null || { die 'cannot stop the current website before migration'; return 1; }
    state="$(docker_cli inspect --format '{{.State.Status}}' "$container")" \
      || { docker_cli start "$container" >/dev/null || true; die 'cannot verify stopped website state'; return 1; }
    if [[ "$state" == 'running' ]]; then
      docker_cli start "$container" >/dev/null || true
      die 'current website is still running; refusing to migrate its database'
      return 1
    fi

    if ! backup_and_restore_check; then
      restart_after_migration_preflight_failure "$container" || return 1
      audit_deployment_event deploy blocked "$digest" "$planned" || true
      return 1
    fi
    if ! inspect_migration_plan "$image" "$LAST_BACKUP_PATH"; then
      audit_deployment_event deploy blocked "$digest" "$planned" || true
      die 'cannot safely revalidate the stopped website database; leaving it stopped for operator review'
      return 1
    fi
    if [[ "$LAST_MIGRATION_PLAN" != "$planned" ]]; then
      audit_deployment_event deploy blocked "$digest" "$planned" || true
      die 'database migration plan changed while the website was stopped; leaving it stopped for operator review'
      return 1
    fi
    if ! rehearse_migrations "$image" "$LAST_BACKUP_PATH"; then
      restart_after_migration_preflight_failure "$container" || return 1
      audit_deployment_event deploy blocked "$digest" "$planned" || true
      return 1
    fi
    if ! "$PYTHON_BIN" "$SIFTALPHA_MIGRATION_GUARD" promote \
      "$LAST_BACKUP_PATH" "$LAST_MIGRATED_DATABASE" "$DATABASE_PATH" >/dev/null; then
      cleanup_migration_workspace "$LAST_MIGRATION_WORKSPACE" || true
      audit_deployment_event deploy blocked "$digest" "$planned" || true
      die 'production migration promotion failed; website remains stopped for database-state review'
      return 1
    fi
    local expected_applied="[\"$SIFTALPHA_APPROVED_MIGRATION\"]"
    if [[ "$planned" == "[\"$SIFTALPHA_ACCOUNT_MIGRATION\"]" ]]; then
      expected_applied="[\"$SIFTALPHA_APPROVED_MIGRATION\",\"$SIFTALPHA_ACCOUNT_MIGRATION\"]"
    fi
    if ! inspect_migration_plan "$image" "$DATABASE_PATH" \
      || [[ "$LAST_MIGRATION_PLAN" != '[]' || "$LAST_APPLIED_MIGRATIONS" != "$expected_applied" ]]; then
      cleanup_migration_workspace "$LAST_MIGRATION_WORKSPACE" || true
      audit_deployment_event deploy blocked "$digest" "$planned" || true
      die 'production migration state could not be verified; website remains stopped for operator review'
      return 1
    fi
    if ! cleanup_migration_workspace "$LAST_MIGRATION_WORKSPACE"; then
      audit_deployment_event deploy blocked "$digest" "$planned" || true
      return 1
    fi
    LAST_MIGRATION_WORKSPACE=''
    LAST_MIGRATED_DATABASE=''
    audit_deployment_event migration promoted "$digest" "$planned" || {
      die 'migration was applied but audit logging failed; website remains stopped for operator review'
      return 1
    }
    record_snapshot_database_state "$snapshot" "$LAST_APPLIED_MIGRATIONS" || {
      die 'migration was applied but rollback metadata could not be recorded; website remains stopped for operator review'
      return 1
    }
  fi

  case "$runtime" in
    legacy)
      if ! first_compose_cutover "$digest"; then
        audit_deployment_event deploy blocked "$digest" "$planned" || true
        return 1
      fi
      ;;
    compose)
      if ! render_compose "$digest" || ! docker_cli compose -f "$COMPOSE_FILE" --project-name "${COMPOSE_PROJECT_NAME:-$SIFTALPHA_COMPOSE_PROJECT_NAME}" up -d --force-recreate; then
        restore_snapshot "$(latest_snapshot)" || return 1
        die 'candidate Compose service failed; prior website service was restored'
        audit_deployment_event deploy blocked "$digest" "$planned" || true
        return 1
      fi
      if ! wait_for_health; then
        candidate_startup_diagnostics
        restore_snapshot "$(latest_snapshot)" || return 1
        die 'candidate Compose service failed health checks; prior website service was restored'
        audit_deployment_event deploy blocked "$digest" "$planned" || true
        return 1
      fi
      if ! verify_candidate_image "$digest"; then
        restore_snapshot "$(latest_snapshot)" || return 1
        die 'candidate image did not match the requested immutable digest; prior website service was restored'
        audit_deployment_event deploy blocked "$digest" "$planned" || true
        return 1
      fi
      ;;
    *)
      die 'deployment snapshot has an invalid runtime; refusing candidate cutover'
      return 1
      ;;
  esac
  audit_deployment_event deploy ok "$digest" "$planned" || return 1
}

rollback() {
  restore_snapshot "$(latest_snapshot)"
}

web_admin_main() {
  validate_command "$@" || return 1
  case "$1" in
    deploy|rollback|test-deploy|upgrade)
      ensure_state_directories || return 1
      command -v flock >/dev/null 2>&1 || { die 'deployment lock utility is unavailable'; return 1; }
      exec 9>"$STATE_DIR/operation.lock" || { die 'cannot open deployment lock'; return 1; }
      flock -n 9 || { die 'another controlled deployment or rollback is already running'; return 1; }
      ;;
  esac
  case "$1" in
    status) status ;;
    health) health_check; printf 'health: ok\n' ;;
    preflight) preflight_candidate "$2" ;;
    upgrade)
      verify_gh_binary || return 1
      [[ -f "$SIFTALPHA_UPGRADER" && ! -L "$SIFTALPHA_UPGRADER" ]] || { die 'web-admin upgrade helper not installed'; return 1; }
      "$PYTHON_BIN" "$SIFTALPHA_UPGRADER" "$2" "$GH_BIN" "$GITHUB_TOKEN_FILE" "$STATE_DIR/gh-cli-config" "$STATE_DIR/tool-backups"
      ;;
    deploy) deploy_candidate "$2" ;;
    test-deploy) isolated_deploy_and_rollback_test "$2" ;;
    rollback) rollback ;;
  esac
}
