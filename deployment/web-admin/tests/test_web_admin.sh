#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
LIB="$ROOT/deployment/web-admin/lib/siftalpha-web-admin-lib.sh"
TEST_ROOT="$(mktemp -d)"

cleanup() {
  find "$TEST_ROOT" -depth -type f -delete 2>/dev/null || true
  find "$TEST_ROOT" -depth -type d -empty -delete 2>/dev/null || true
}
trap cleanup EXIT

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
assert_ok() { "$@" || fail "expected success: $*"; }
assert_fail() { if "$@"; then fail "expected failure: $*"; fi; }

if [[ ! -f "$LIB" ]]; then
  fail "web-admin library is missing: $LIB"
fi
if grep -F ',rw"' "$LIB" >/dev/null; then
  fail "Docker --mount must not use the unsupported rw shorthand"
fi
if ! sed -n '/^isolated_deploy_and_rollback_test()/,/^record_snapshot_database_state()/p' "$LIB" \
  | grep -F -- '--env-file "$ENV_FILE" --env HUNTALPHA_DATABASE_PATH=/data/db.sqlite3 --env HOME=/tmp' >/dev/null; then
  fail "isolated legacy container must use the writable temporary home"
fi
if ! grep -F 'HOME: /tmp' "$ROOT/deployment/web-admin/compose.selftest.yaml.template" >/dev/null; then
  fail "isolated candidate container must use the writable temporary home"
fi
if ! sed -n '/^install_files()/,/^install_rdc_write_allowance()/p' "$ROOT/deployment/web-admin/install-web-admin.sh" \
  | grep -F 'assert_secure_config_file "$CONFIG_PATH"' >/dev/null; then
  fail "installer must refuse an unsafe pre-existing root configuration"
fi
if ! sed -n '/^health_check()/,/^current_container()/p' "$LIB" | grep -F 'docker_cli exec' >/dev/null; then
  fail "self-test health checks must run inside the isolated container"
fi
if ! sed -n '/^rehearse_migrations()/,/^audit_deployment_event()/p' "$LIB" | grep -F 'validate-result' >/dev/null; then
  fail "migration rehearsal must validate the exact approved database result"
fi
if grep -F 'ports:' "$ROOT/deployment/web-admin/compose.selftest.yaml.template" >/dev/null; then
  fail "isolated self-test containers must not publish host ports"
fi

FAKE_BIN="$TEST_ROOT/bin"
STATE_DIR="$TEST_ROOT/state"
DATA_DIR="$TEST_ROOT/data"
mkdir -p "$FAKE_BIN" "$STATE_DIR" "$DATA_DIR"
export FAKE_LOG="$TEST_ROOT/fake.log"
: > "$FAKE_LOG"
export FAKE_DIGEST="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
export FAKE_COMMIT="0123456789abcdef0123456789abcdef01234567"
export FAKE_RUN_ID="424242"
export FAKE_PLAN_MODE='none'
export FAKE_LOG

cat > "$FAKE_BIN/docker" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
{ printf 'docker'; printf ' %s' "$@"; printf '\n'; } >> "$FAKE_LOG"
case "${1:-}" in
  pull) exit 0 ;;
  buildx)
    if [[ "$*" == *".Manifest"* ]]; then
      printf '{"digest":"%s","manifests":[{"digest":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","platform":{"architecture":"arm64","os":"linux"}},{"digest":"sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","annotations":{"vnd.docker.reference.type":"attestation-manifest","vnd.docker.reference.digest":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"},"platform":{"architecture":"unknown","os":"unknown"}}]}\n' "$FAKE_DIGEST"
    elif [[ "$*" == *".Provenance.SLSA"* ]]; then
      [[ "${FAKE_GH_MODE:-ok}" == provenance-fail ]] && exit 1
      if [[ "${FAKE_PROVENANCE_VERSION:-v1}" == v0.2 ]]; then
        printf '{"buildType":"https://mobyproject.org/buildkit@v1","invocation":{},"metadata":{}}\n'
      else
        printf '{"buildDefinition":{"buildType":"https://github.com/moby/buildkit/blob/master/docs/attestations/slsa-definitions.md","externalParameters":{},"internalParameters":{"github_repository":"kuashan/huntalpha","github_workflow":"SiftAlpha Web CI and ARM64","github_workflow_ref":"kuashan/huntalpha/.github/workflows/siftalpha-web-arm64.yml@refs/heads/release/siftalpha-web-v1","github_workflow_sha":"%s","github_run_id":"%s","github_ref":"refs/heads/release/siftalpha-web-v1","github_event_name":"push"},"resolvedDependencies":[]},"runDetails":{"builder":{"id":""},"metadata":{}}}\n' "$FAKE_COMMIT" "$FAKE_RUN_ID"
      fi
    else
      printf '{"manifests":[{"platform":{"architecture":"arm64","os":"linux"}}]}\n'
    fi
    exit 0 ;;
  image)
    case "${4:-}" in
      '{{ index .Config.Labels "org.opencontainers.image.source" }}') [[ "${FAKE_GH_MODE:-ok}" == label-mismatch ]] && printf 'https://github.com/evil/repository\n' || printf 'https://github.com/kuashan/huntalpha\n' ;;
      '{{ index .Config.Labels "org.opencontainers.image.revision" }}') [[ "${FAKE_GH_MODE:-ok}" == label-mismatch ]] && printf 'deadbeef\n' || printf '%s\n' "$FAKE_COMMIT" ;;
      '{{ index .Config.Labels "io.siftalpha.build.run-id" }}') [[ "${FAKE_GH_MODE:-ok}" == label-mismatch ]] && printf '999999\n' || printf '%s\n' "$FAKE_RUN_ID" ;;
      '{{ index .Config.Labels "io.siftalpha.build.ref" }}') printf 'release/siftalpha-web-v1\n' ;;
      '{{ index .Config.Labels "org.opencontainers.image.version" }}') printf 'V1.0.0\n' ;;
      *) printf 'arm64\n' ;;
    esac
    exit 0 ;;
  container)
    if [[ "${2:-}" == ls ]]; then
      [[ "${FAKE_CONTAINER_LIST_FAIL:-0}" == 1 ]] && exit 1
      [[ "${FAKE_CONTAINER_LIST_FAIL_AFTER_STOP:-0}" == 1 && -f "$FAKE_STOP_MARKER_FILE" ]] && exit 1
      if [[ "$*" == *'name=^/siftalpha-web-compose$'* ]]; then
        [[ -f "$FAKE_CANDIDATE_MARKER_FILE" ]] && printf 'siftalpha-web-compose\n'
      elif [[ "$*" == *'name=^/siftalpha-task011-ebd23f4$'* ]]; then
        [[ "${FAKE_LEGACY_ABSENT:-0}" == 1 ]] || printf 'siftalpha-task011-ebd23f4\n'
      fi
      exit 0
    fi
    if [[ "${2:-}" == inspect ]]; then
      if [[ "${3:-}" == siftalpha-web-compose ]]; then
        [[ -f "$FAKE_CANDIDATE_MARKER_FILE" ]] || exit 1
      else
        [[ "${FAKE_LEGACY_ABSENT:-0}" == 0 ]]
      fi
    fi
    exit 0 ;;
  run)
    [[ "$*" == *'--network none'* && "$*" == *'--read-only'* ]] || exit 1
    if [[ "$*" == *'manage.py migrate --noinput'* ]]; then
      [[ "$*" == *'--env HOME=/tmp'* ]] || { printf 'isolated migrations must use the writable temporary home\n' >&2; exit 125; }
    fi
    for argument in "$@"; do
      [[ "$argument" == type=bind*,rw ]] && { printf 'invalid Docker --mount rw shorthand\n' >&2; exit 125; }
    done
    mount_specs=()
    previous=''
    for argument in "$@"; do
      if [[ "$previous" == --mount ]]; then
        mount_specs+=("$argument")
        previous=''
        continue
      fi
      previous="$argument"
    done
    mount_source=''
    for mount_spec in "${mount_specs[@]}"; do
      IFS=',' read -ra mount_parts <<< "$mount_spec"
      mount_destination=''
      candidate_source=''
      for part in "${mount_parts[@]}"; do
        [[ "$part" == src=* ]] && candidate_source="${part#src=}"
        [[ "$part" == dst=* ]] && mount_destination="${part#dst=}"
      done
      if [[ "$mount_destination" == /deploy/db.sqlite3 || "$mount_destination" == /deploy ]]; then
        mount_source="$candidate_source"
      fi
    done
    [[ -n "$mount_source" ]] || exit 1
    if [[ "$*" == *'migration_probe.py'* ]]; then
      database_path="$mount_source"
      [[ -d "$mount_source" ]] && database_path="$mount_source/db.sqlite3"
      python - "$database_path" "${FAKE_PLAN_MODE:-none}" <<'PY'
import json
import sqlite3
import sys

database_path, mode = sys.argv[1:]
connection = sqlite3.connect(database_path)
try:
    table_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='formula_editor_fixedindicatorstate'"
    ).fetchone() is not None
    migration_applied = connection.execute(
        "SELECT 1 FROM django_migrations WHERE app=? AND name=?",
        ("formula_editor", "0002_fixedindicatorstate"),
    ).fetchone() is not None
finally:
    connection.close()

if mode == "none":
    pending = []
elif mode == "unknown":
    pending = [{"name": "core.9999_unknown", "backwards": False, "sha256": "0" * 64}]
else:
    pending = [] if table_exists and migration_applied else [{
        "name": "formula_editor.0002_fixedindicatorstate",
        "backwards": False,
        "sha256": "72514513ca8f6b801b2b68fef42f7b35e998c78d7cdcd9cd236e0dbffefa977a",
    }]
applied = [{
    "name": "formula_editor.0002_fixedindicatorstate",
    "sha256": "72514513ca8f6b801b2b68fef42f7b35e998c78d7cdcd9cd236e0dbffefa977a",
}] if migration_applied else []
print(json.dumps({"pending": pending, "applied": applied}, separators=(",", ":")))
PY
      exit $?
    fi
    if [[ "$*" == *'manage.py migrate --noinput'* ]]; then
      [[ "${FAKE_MIGRATE_FAIL:-0}" == 1 ]] && exit 1
      database_path="$mount_source/db.sqlite3"
      python - "$database_path" <<'PY'
import sqlite3
import sys
connection = sqlite3.connect(sys.argv[1])
try:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS formula_editor_fixedindicatorstate "
        "(code varchar(32) NOT NULL PRIMARY KEY, enabled bool NOT NULL)"
    )
    connection.execute(
        "INSERT INTO django_migrations (app, name, applied) VALUES (?, ?, ?)",
        ("formula_editor", "0002_fixedindicatorstate", "2026-01-01 00:01:00"),
    )
    content_type_id = connection.execute(
        "INSERT INTO django_content_type (app_label, model) VALUES (?, ?)",
        ("formula_editor", "fixedindicatorstate"),
    ).lastrowid
    for codename, name in (
        ("add_fixedindicatorstate", "Can add 固定公式（服务器已安装）"),
        ("change_fixedindicatorstate", "Can change 固定公式（服务器已安装）"),
        ("delete_fixedindicatorstate", "Can delete 固定公式（服务器已安装）"),
        ("view_fixedindicatorstate", "Can view 固定公式（服务器已安装）"),
    ):
        connection.execute(
            "INSERT INTO auth_permission (name, content_type_id, codename) VALUES (?, ?, ?)",
            (name, content_type_id, codename),
        )
    connection.commit()
finally:
    connection.close()
PY
      exit $?
    fi
    exit 1 ;;
  exec)
    [[ "$*" == *'http://127.0.0.1:8000'* && "$*" == *'/healthz/'* && "$*" == *'/static/'* ]] || exit 1
    exit 0 ;;
  container)
    if [[ "${3:-}" == 'siftalpha-web-compose' ]]; then
      [[ -f "$FAKE_CANDIDATE_MARKER_FILE" ]] || exit 1
    fi
    exit 0 ;;
  inspect)
    if [[ "${3:-}" == '{{.State.Status}}' ]]; then
      if [[ "${!#}" == 'siftalpha-web-compose' ]]; then
        [[ -f "$FAKE_CANDIDATE_MARKER_FILE" ]] || exit 1
        printf '%s\n' "${FAKE_COMPOSE_STATE:-running}"
      elif [[ -f "$FAKE_CANDIDATE_MARKER_FILE" ]]; then
        printf 'exited\n'
      else
        cat "$FAKE_CONTAINER_STATE_FILE"
      fi
    elif [[ "${3:-}" == '{{.Config.Image}}' ]]; then
      if [[ "${!#}" == 'siftalpha-web-compose' ]]; then
        if [[ -n "${FAKE_CANDIDATE_IMAGE_MISMATCH_PENDING_FILE:-}" && -f "$FAKE_CANDIDATE_IMAGE_MISMATCH_PENDING_FILE" ]]; then
          rm -f "$FAKE_CANDIDATE_IMAGE_MISMATCH_PENDING_FILE"
          printf 'ghcr.io/kuashan/siftalpha-web@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'
        else
          printf 'ghcr.io/kuashan/siftalpha-web@%s\n' "$FAKE_DIGEST"
        fi
      else
        printf 'siftalpha-task011:ebd23f4\n'
      fi
    else
      printf 'siftalpha-task011:ebd23f4\n'
    fi
    exit 0 ;;
  logs)
    printf 'Traceback (most recent call last):\n'
    printf 'PermissionError: synthetic startup failure\n'
    printf 'django.db.utils.OperationalError: synthetic startup failure\n'
    printf 'SYNTHETIC_PRIVATE_SENTINEL_DO_NOT_EMIT\n'
    exit 0 ;;
  compose)
    [[ "${FAKE_COMPOSE_FAIL:-0}" == 1 ]] && exit 1
    if [[ "${FAKE_REQUIRE_LEGACY_STOPPED:-0}" == 1 && "$(<"$FAKE_CONTAINER_STATE_FILE")" == running ]]; then
      printf 'Bind for 127.0.0.1:19091 failed: port is already allocated\n' >&2
      exit 1
    fi
    if [[ "${FAKE_CANDIDATE_IMAGE_MISMATCH:-0}" == 1 \
      && -n "${FAKE_CANDIDATE_IMAGE_MISMATCH_FILE:-}" \
      && ! -e "$FAKE_CANDIDATE_IMAGE_MISMATCH_FILE" ]]; then
      : > "$FAKE_CANDIDATE_IMAGE_MISMATCH_FILE"
      : > "$FAKE_CANDIDATE_IMAGE_MISMATCH_PENDING_FILE"
    fi
    printf 'running\n' > "$FAKE_CONTAINER_STATE_FILE"
    printf 'candidate\n' > "$FAKE_CANDIDATE_MARKER_FILE"
    exit 0 ;;
  stop)
    [[ "${FAKE_STOP_FAIL:-0}" == 1 ]] && exit 1
    if [[ "${FAKE_STOP_NOOP:-0}" != 1 ]]; then
      printf 'exited\n' > "$FAKE_CONTAINER_STATE_FILE"
      : > "$FAKE_STOP_MARKER_FILE"
    fi
    exit 0 ;;
  start) printf 'running\n' > "$FAKE_CONTAINER_STATE_FILE"; rm -f "$FAKE_CANDIDATE_MARKER_FILE" "$FAKE_STOP_MARKER_FILE"; exit 0 ;;
  rm)
    [[ "$*" == *siftalpha-web-compose* ]] && rm -f "$FAKE_CANDIDATE_MARKER_FILE"
    exit 0 ;;
  *) exit 0 ;;
esac
EOF

cat > "$FAKE_BIN/curl" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
curl_timeout=''
while (($#)); do
  if [[ "$1" == --max-time ]]; then
    curl_timeout="${2:-}"
    shift 2
  else
    url="$1"
    shift
  fi
done
if [[ -n "${FAKE_CURL_TIMEOUT_FILE:-}" ]]; then
  printf '%s\n' "${curl_timeout:-missing}" >> "$FAKE_CURL_TIMEOUT_FILE"
fi
if [[ -n "${FAKE_CURL_COUNT_FILE:-}" ]]; then
  curl_count=0
  [[ ! -f "$FAKE_CURL_COUNT_FILE" ]] || curl_count="$(<"$FAKE_CURL_COUNT_FILE")"
  curl_count=$((curl_count + 1))
  printf '%s\n' "$curl_count" > "$FAKE_CURL_COUNT_FILE"
  if [[ "${FAKE_CURL_FAIL_ALWAYS:-0}" == 1 ]] || (( curl_count <= ${FAKE_CURL_FAIL_FIRST_CALLS:-0} )); then
    exit 56
  fi
fi
if [[ "${FAKE_CURL_STALL:-0}" == 1 ]]; then
  [[ -n "$curl_timeout" ]] || exit 28
  sleep "$curl_timeout"
  exit 28
fi
if [[ -f "${FAKE_CANDIDATE_MARKER_FILE:-/dev/null}" && "${FAKE_CANDIDATE_FAIL_ALWAYS:-0}" == 1 ]]; then
  exit 56
fi
url="${!#}"
case "$url" in
  */healthz/) printf '{"status":"ok"}' ;;
  */static/*) printf 'window.siftAlphaRuntime = true;' ;;
  *) printf '<!doctype html><script src="/static/assets/app.js"></script>' ;;
esac
EOF

cat > "$FAKE_BIN/gh" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ "${GH_CONFIG_DIR:-}" == */gh-cli-config ]] || { printf 'GitHub CLI config directory is not isolated under web-admin state\n' >&2; exit 1; }
mkdir -p "$GH_CONFIG_DIR"
[[ -w "$GH_CONFIG_DIR" ]] || exit 1
case "${1:-}" in
  api)
    [[ "${FAKE_GH_MODE:-ok}" == run-mismatch ]] && { printf '{"conclusion":"failure"}\n'; exit 0; }
    if [[ "${FAKE_GH_MODE:-ok}" == workflow-mismatch ]]; then
      printf '{"status":"completed","conclusion":"success","head_sha":"%s","head_branch":"release/siftalpha-web-v1","name":"SiftAlpha Web CI and ARM64","workflow_id":123456,"path":".github/workflows/other.yml","html_url":"https://github.com/kuashan/huntalpha/actions/runs/%s"}\n' "$FAKE_COMMIT" "$FAKE_RUN_ID"
      exit 0
    fi
    printf '{"status":"completed","conclusion":"success","head_sha":"%s","head_branch":"release/siftalpha-web-v1","name":"SiftAlpha Web CI and ARM64","workflow_id":387611326,"path":".github/workflows/siftalpha-web-arm64.yml","html_url":"https://github.com/kuashan/huntalpha/actions/runs/%s"}\n' "$FAKE_COMMIT" "$FAKE_RUN_ID"
    ;;
  run)
    destination=""
    for ((i = 1; i <= $#; i++)); do
      [[ "${!i}" == --dir ]] && { j=$((i + 1)); destination="${!j}"; }
    done
    mkdir -p "$destination"
    [[ "${FAKE_GH_MODE:-ok}" == manifest-missing ]] && exit 0
    [[ "${FAKE_GH_MODE:-ok}" == manifest-mismatch ]] && digest='sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' || digest="$FAKE_DIGEST"
    [[ "${FAKE_GH_MODE:-ok}" == metadata-forged ]] && record_commit='deadbeef' || record_commit="$FAKE_COMMIT"
    printf '{"image":"ghcr.io/kuashan/siftalpha-web","digest":"%s","source_commit":"%s","run_id":"%s","run_url":"https://github.com/kuashan/huntalpha/actions/runs/%s","ref":"release/siftalpha-web-v1","source_ref":"refs/heads/release/siftalpha-web-v1","workflow":"SiftAlpha Web CI and ARM64","platform":"linux/arm64","tags":["sha-%s","v1.0.0-sha-%s"],"provenance":"buildkit-oci-slsa"}\n' "$digest" "$record_commit" "$FAKE_RUN_ID" "$FAKE_RUN_ID" "$record_commit" "$record_commit" > "$destination/siftalpha-web-build-manifest.json"
    ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$FAKE_BIN/docker" "$FAKE_BIN/curl" "$FAKE_BIN/gh"
cat > "$FAKE_BIN/chmod" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${FAKE_CHMOD_FAIL:-0}" == 1 ]]; then
  printf 'chmod: simulated read-only filesystem\n' >&2
  exit 1
fi
exec /usr/bin/chmod "$@"
EOF
chmod +x "$FAKE_BIN/chmod"
cat > "$FAKE_BIN/stat" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ -n "${FAKE_STAT_UNSAFE_CONFIG:-}" && "${!#}" == "$FAKE_STAT_UNSAFE_CONFIG" ]]; then
  printf '%s 666\n' "$EUID"
  exit 0
fi
exec /usr/bin/stat "$@"
EOF
chmod +x "$FAKE_BIN/stat"
GH_SHA256="$(sha256sum "$FAKE_BIN/gh" | awk '{print $1}')"
FAKE_CONTAINER_STATE_FILE="$TEST_ROOT/container.state"
FAKE_CANDIDATE_MARKER_FILE="$TEST_ROOT/candidate.started"
FAKE_STOP_MARKER_FILE="$TEST_ROOT/legacy.stopped"
printf 'running\n' > "$FAKE_CONTAINER_STATE_FILE"
export FAKE_CONTAINER_STATE_FILE FAKE_CANDIDATE_MARKER_FILE FAKE_STOP_MARKER_FILE

cat > "$TEST_ROOT/web-admin.conf" <<EOF
IMAGE_REPOSITORY=ghcr.io/kuashan/siftalpha-web
GITHUB_REPOSITORY=kuashan/huntalpha
GITHUB_WORKFLOW_NAME='SiftAlpha Web CI and ARM64'
RELEASE_BRANCH=release/siftalpha-web-v1
LEGACY_CONTAINER=siftalpha-task011-ebd23f4
COMPOSE_CONTAINER=siftalpha-web-compose
DATA_DIR=$DATA_DIR
DATABASE_PATH=$DATA_DIR/db.sqlite3
LOOPBACK_PORT=127.0.0.1:19091
COMPOSE_FILE=$STATE_DIR/compose.yaml
COMPOSE_TEMPLATE=$ROOT/deployment/web-admin/compose.yaml.template
ENV_FILE=$TEST_ROOT/web-admin.env
BREVO_ENV_FILE=$TEST_ROOT/secret/brevo.env
STATE_DIR=$STATE_DIR
BACKUP_DIR=$STATE_DIR/backups
ROLLBACK_DIR=$STATE_DIR/rollbacks
RECOVERY_DIR=$STATE_DIR/recovery
DOCKER_CONFIG_DIR=$TEST_ROOT/docker-config
GITHUB_TOKEN_FILE=$TEST_ROOT/github-token
GH_BIN=$FAKE_BIN/gh
GH_SHA256=$GH_SHA256
DOCKER_BIN=$FAKE_BIN/docker
CURL_BIN=$FAKE_BIN/curl
PYTHON_BIN=python
EOF
printf 'test-token\n' > "$TEST_ROOT/github-token"
printf 'DJANGO_SECRET_KEY=test-only\n' > "$TEST_ROOT/web-admin.env"
mkdir -p "$TEST_ROOT/secret"
chmod 700 "$TEST_ROOT/secret"
printf 'BREVO_API_KEY=synthetic-not-real-key-for-tests-only\n' > "$TEST_ROOT/secret/brevo.env"
chmod 600 "$TEST_ROOT/secret/brevo.env"


python - "$DATA_DIR/db.sqlite3" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
try:
    connection.executescript("""
        create table fixture (id integer primary key, value text);
        insert into fixture (value) values ('safe');
        create table auth_user (id integer primary key, username text, password text);
        insert into auth_user values (1, 'synthetic-user', 'synthetic-hash');
        create table core_accountprofile (id integer primary key, user_id integer, market text);
        insert into core_accountprofile values (1, 1, 'us');
        create table core_accountmembership (id integer primary key, user_id integer, tier text);
        insert into core_accountmembership values (1, 1, 'pro');
        create table core_watchlistentry (id integer primary key, user_id integer, symbol_id integer);
        insert into core_watchlistentry values (1, 1, 77);
        create table formula_editor_formula (id integer primary key, code text, source text);
        insert into formula_editor_formula values (1, 'SYNTHETIC_ONLY', 'synthetic test content');
        create table django_content_type (
            id integer primary key autoincrement, app_label text not null,
            model text not null, unique(app_label, model)
        );
        insert into django_content_type (id, app_label, model) values (1, 'auth', 'user');
        create table auth_permission (
            id integer primary key autoincrement, name text not null,
            content_type_id integer not null, codename text not null,
            unique(content_type_id, codename)
        );
        insert into auth_permission (id, name, content_type_id, codename)
            values (1, 'Can view user', 1, 'view_user');
        create table django_migrations (
            id integer primary key autoincrement, app text, name text, applied text
        );
        insert into django_migrations values (1, 'formula_editor', '0001_initial', '2026-01-01 00:00:00');
    """)
    connection.commit()
finally:
    connection.close()
PY

source "$LIB"
load_config "$TEST_ROOT/web-admin.conf"
assert_ok verify_brevo_secret_file
chmod 644 "$BREVO_ENV_FILE"
assert_fail verify_brevo_secret_file
chmod 600 "$BREVO_ENV_FILE"
printf 'BREVO_API_KEY=\n' > "$BREVO_ENV_FILE"
assert_fail verify_brevo_secret_file
printf 'BREVO_API_KEY=synthetic-not-real-key-for-tests-only\n' > "$BREVO_ENV_FILE"
assert_ok verify_brevo_secret_file
for template in "$ROOT/deployment/web-admin/compose.yaml.template" "$ROOT/deployment/web-admin/compose.selftest.yaml.template"; do
  grep -F -- '- __BREVO_ENV_FILE__' "$template" >/dev/null || fail "Compose must inject Brevo secret only into website service"
done
assert_ok render_compose "$FAKE_DIGEST"
grep -F "$BREVO_ENV_FILE" "$COMPOSE_FILE" >/dev/null || fail "rendered website Compose lacks secret env_file"


PATH="$FAKE_BIN:$PATH"
export PATH

insecure_config="$TEST_ROOT/insecure-web-admin.conf"
cp "$TEST_ROOT/web-admin.conf" "$insecure_config"
printf '\n: > "%s/config-sourced"\n' "$TEST_ROOT" >> "$insecure_config"
chmod 0666 "$insecure_config"
FAKE_STAT_UNSAFE_CONFIG="$insecure_config"
export FAKE_STAT_UNSAFE_CONFIG
if load_config "$insecure_config"; then
  fail "writable configuration was accepted"
fi
[[ ! -e "$TEST_ROOT/config-sourced" ]] || fail "unsafe configuration was sourced before validation"
unset FAKE_STAT_UNSAFE_CONFIG
load_config "$TEST_ROOT/web-admin.conf"

FAKE_CONTAINER_LIST_FAIL=1 assert_fail current_container
unset FAKE_CONTAINER_LIST_FAIL

SELF_TEST_NETWORK_NAME=web-admin-selftest-contract
assert_ok health_check
unset SELF_TEST_NETWORK_NAME

FAKE_CURL_COUNT_FILE="$TEST_ROOT/curl.calls"
FAKE_SLEEP_CALLS_FILE="$TEST_ROOT/sleep.calls"
printf '0\n' > "$FAKE_CURL_COUNT_FILE"
export FAKE_CURL_COUNT_FILE FAKE_SLEEP_CALLS_FILE FAKE_CURL_FAIL_FIRST_CALLS=2
sleep() { printf '%s\n' "$1" >> "$FAKE_SLEEP_CALLS_FILE"; }
assert_ok wait_for_health
curl_calls="$(<"$FAKE_CURL_COUNT_FILE")"
[[ "$curl_calls" -gt 2 ]] || fail "startup readiness did not retry transient connection failures"

printf '0\n' > "$FAKE_CURL_COUNT_FILE"
: > "$FAKE_SLEEP_CALLS_FILE"
unset FAKE_CURL_FAIL_FIRST_CALLS
export FAKE_CURL_FAIL_ALWAYS=1
FAKE_HEALTH_CLOCK_FILE="$TEST_ROOT/health.clock"
printf '0\n' > "$FAKE_HEALTH_CLOCK_FILE"
health_clock_seconds() {
  if [[ -z "${FAKE_HEALTH_CLOCK_FILE:-}" ]]; then
    printf '%s\n' "$SECONDS"
    return 0
  fi
  local now="$(<"$FAKE_HEALTH_CLOCK_FILE")"
  printf '%s\n' "$now"
  printf '%s\n' "$((now + 1))" > "$FAKE_HEALTH_CLOCK_FILE"
}
assert_fail wait_for_health
curl_calls="$(<"$FAKE_CURL_COUNT_FILE")"
sleep_calls="$(wc -l < "$FAKE_SLEEP_CALLS_FILE")"
[[ "$curl_calls" -gt 1 && "$curl_calls" -le 60 ]] || fail "startup readiness did not stop within its bounded retry window"
[[ "$sleep_calls" -gt 0 && "$sleep_calls" -lt "$curl_calls" ]] || fail "startup readiness did not poll between failed checks"
unset FAKE_CURL_FAIL_ALWAYS FAKE_CURL_COUNT_FILE FAKE_HEALTH_CLOCK_FILE
unset -f sleep

FAKE_CURL_TIMEOUT_FILE="$TEST_ROOT/curl.timeouts"
FAKE_CURL_COUNT_FILE="$TEST_ROOT/curl.timeout-count"
: > "$FAKE_CURL_TIMEOUT_FILE"
printf '0\n' > "$FAKE_CURL_COUNT_FILE"
export FAKE_CURL_TIMEOUT_FILE FAKE_CURL_COUNT_FILE FAKE_CURL_FAIL_ALWAYS=1
sleep() { :; }
assert_fail wait_for_health 2
unset -f sleep
unset FAKE_CURL_FAIL_ALWAYS FAKE_CURL_COUNT_FILE
grep -Fx 'missing' "$FAKE_CURL_TIMEOUT_FILE" >/dev/null \
  && fail "health probes were launched without a per-request timeout"

FAKE_CURL_STALL=1
: > "$FAKE_CURL_TIMEOUT_FILE"
export FAKE_CURL_STALL
health_start_seconds="$SECONDS"
assert_fail wait_for_health 2
health_elapsed_seconds=$((SECONDS - health_start_seconds))
[[ "$health_elapsed_seconds" -le 3 ]] || fail "stalled health probe exceeded its overall deadline"
health_first_timeout="$(head -n 1 "$FAKE_CURL_TIMEOUT_FILE")"
[[ "$health_first_timeout" =~ ^[1-2]$ ]] || fail "health probe timeout was not bounded by the remaining deadline"
unset FAKE_CURL_STALL FAKE_CURL_TIMEOUT_FILE

assert_ok validate_command status
assert_ok validate_command health
assert_ok validate_command preflight "$FAKE_DIGEST"
assert_ok validate_command deploy "$FAKE_DIGEST"
assert_ok validate_command test-deploy "$FAKE_DIGEST"
assert_ok validate_command upgrade "$FAKE_COMMIT"
assert_fail validate_command upgrade "not-a-sha"
assert_fail validate_command upgrade "${FAKE_COMMIT}extra"
assert_ok validate_command rollback
assert_fail validate_command deploy
assert_fail validate_command preflight sha256:bad
assert_fail validate_command test-deploy sha256:bad
assert_fail validate_command status unexpected
assert_fail validate_command

log_before="$(wc -l < "$FAKE_LOG")"
FAKE_CHMOD_FAIL=1 assert_fail verify_trusted_source "$FAKE_DIGEST"
[[ "$(wc -l < "$FAKE_LOG")" == "$log_before" ]] || fail "read-only state failure continued into Docker verification"
find "$RECOVERY_DIR" -mindepth 1 -print -quit | grep -q . && fail "read-only state failure left a temporary provenance copy"

IMAGE_REPOSITORY=ghcr.io/evil/repository
load_config "$TEST_ROOT/web-admin.conf"
[[ "$IMAGE_REPOSITORY" == ghcr.io/kuashan/siftalpha-web ]] || fail "environment override changed fixed repository"

assert_ok preflight_candidate "$FAKE_DIGEST"
export FAKE_PROVENANCE_VERSION=v0.2
assert_fail preflight_candidate "$FAKE_DIGEST"
export FAKE_PROVENANCE_VERSION=v1
export FAKE_GH_MODE=manifest-mismatch
assert_fail preflight_candidate "$FAKE_DIGEST"
export FAKE_GH_MODE=manifest-missing
assert_fail preflight_candidate "$FAKE_DIGEST"
export FAKE_GH_MODE=metadata-forged
assert_fail preflight_candidate "$FAKE_DIGEST"
export FAKE_GH_MODE=label-mismatch
assert_fail preflight_candidate "$FAKE_DIGEST"
export FAKE_GH_MODE=provenance-fail
assert_fail preflight_candidate "$FAKE_DIGEST"
export FAKE_GH_MODE=workflow-mismatch
assert_fail preflight_candidate "$FAKE_DIGEST"
export FAKE_GH_MODE=run-mismatch
assert_fail preflight_candidate "$FAKE_DIGEST"
unset FAKE_GH_MODE

export FAKE_PLAN_MODE=unknown
assert_fail preflight_candidate "$FAKE_DIGEST"
export FAKE_PLAN_MODE=approved
export FAKE_MIGRATE_FAIL=1
log_before="$(wc -l < "$FAKE_LOG")"
assert_fail preflight_candidate "$FAKE_DIGEST"
[[ "$(wc -l < "$FAKE_LOG")" -gt "$log_before" ]] || fail "migration rehearsal was not attempted"
if tail -n "+$((log_before + 1))" "$FAKE_LOG" | grep -F 'docker stop ' >/dev/null; then
  fail "preflight failure stopped the running website"
fi
unset FAKE_MIGRATE_FAIL
assert_ok preflight_candidate "$FAKE_DIGEST"
find "$RECOVERY_DIR" -mindepth 1 -print -quit | grep -q . && fail "migration rehearsal copy was not cleaned"

assert_ok deploy_candidate "$FAKE_DIGEST"
python - "$DATABASE_PATH" <<'PY'
import sqlite3
import sys
connection = sqlite3.connect(sys.argv[1])
try:
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='formula_editor_fixedindicatorstate'"
    ).fetchone()
finally:
    connection.close()
PY
rollback_output="$(rollback)"
[[ "$rollback_output" == *'database rollback: retained reviewed additive migration formula_editor.0002_fixedindicatorstate'* ]] \
  || fail "database rollback compatibility was not reported"
grep -F 'docker stop siftalpha-task011-ebd23f4' "$FAKE_LOG" >/dev/null || fail "migration deploy did not stop the old writer first"
[[ "$(<"$FAKE_CONTAINER_STATE_FILE")" == running ]] || fail "original website container was not running after rollback"

assert_ok backup_and_restore_check
find "$BACKUP_DIR" -name '*.sqlite3' -type f | grep -q . || fail "backup was not created"
find "$RECOVERY_DIR" -type f | grep -q . && fail "recovery fixture was not cleaned"

snapshot_current_runtime
[[ -f "$ROLLBACK_DIR/latest" ]] || fail "deployment snapshot was not recorded"
snapshot_path="$(<"$ROLLBACK_DIR/latest")"
[[ -f "$snapshot_path/metadata" ]] || fail "deployment snapshot metadata is missing"
grep -Fx 'runtime=legacy' "$snapshot_path/metadata" >/dev/null || fail "legacy runtime was not recorded"

export FAKE_COMPOSE_STATE=paused
printf 'candidate\n' > "$FAKE_CANDIDATE_MARKER_FILE"
assert_fail current_container
rm -f "$FAKE_CANDIDATE_MARKER_FILE"
unset FAKE_COMPOSE_STATE

export FAKE_STOP_FAIL=1
: > "$FAKE_LOG"
assert_fail first_compose_cutover "$FAKE_DIGEST"
unset FAKE_STOP_FAIL
grep -F 'docker compose -f ' "$FAKE_LOG" >/dev/null && fail "Compose started after Docker failed to stop the legacy container"
[[ "$(<"$FAKE_CONTAINER_STATE_FILE")" == running ]] || fail "legacy service state changed after stop failure"

export FAKE_STOP_NOOP=1
: > "$FAKE_LOG"
assert_fail first_compose_cutover "$FAKE_DIGEST"
unset FAKE_STOP_NOOP
grep -F 'docker compose -f ' "$FAKE_LOG" >/dev/null && fail "Compose started before the legacy container was confirmed stopped"
[[ "$(<"$FAKE_CONTAINER_STATE_FILE")" == running ]] || fail "legacy service was not left available when stop did not take effect"

export FAKE_CONTAINER_LIST_FAIL_AFTER_STOP=1
: > "$FAKE_LOG"
assert_fail first_compose_cutover "$FAKE_DIGEST"
unset FAKE_CONTAINER_LIST_FAIL_AFTER_STOP
[[ "$(<"$FAKE_CONTAINER_STATE_FILE")" == running ]] || fail "legacy service was not restored when post-stop inspection failed"
grep -F 'docker compose -f ' "$FAKE_LOG" >/dev/null && fail "Compose started without verifying the legacy container stopped"

printf 'stale compose configuration\n' > "$COMPOSE_FILE"
missing_template="$TEST_ROOT/missing-compose-template.yaml"
: > "$FAKE_LOG"
COMPOSE_TEMPLATE="$missing_template" assert_fail first_compose_cutover "$FAKE_DIGEST"
[[ "$(<"$FAKE_CONTAINER_STATE_FILE")" == running ]] || fail "legacy service was not retained when Compose rendering failed"
grep -F 'docker compose -f ' "$FAKE_LOG" >/dev/null && fail "stale Compose configuration was started after rendering failed"

printf 'exited\n' > "$FAKE_CONTAINER_STATE_FILE"
: > "$FAKE_LOG"
COMPOSE_TEMPLATE="$missing_template" assert_fail first_compose_cutover "$FAKE_DIGEST"
[[ "$(<"$FAKE_CONTAINER_STATE_FILE")" == running ]] || fail "legacy service was not restored after render failure with the old writer stopped"
grep -F 'docker compose -f ' "$FAKE_LOG" >/dev/null && fail "stale Compose configuration was started after rendering failed with the old writer stopped"

FAKE_COMPOSE_FAIL=1 assert_fail first_compose_cutover "$FAKE_DIGEST"
grep -F 'docker start siftalpha-task011-ebd23f4' "$FAKE_LOG" >/dev/null || fail "legacy container was not restarted"
grep -F 'docker rm siftalpha-task011-ebd23f4' "$FAKE_LOG" >/dev/null && fail "legacy container was removed"

: > "$FAKE_LOG"
FAKE_CANDIDATE_FAIL_ALWAYS=1
export FAKE_CANDIDATE_FAIL_ALWAYS
FAKE_HEALTH_CLOCK_FILE="$TEST_ROOT/health.cutover.clock"
printf '0\n' > "$FAKE_HEALTH_CLOCK_FILE"
sleep() { :; }
if candidate_failure_output="$(first_compose_cutover "$FAKE_DIGEST" 2>&1)"; then
  fail "candidate that never became ready was accepted"
fi
unset -f sleep
unset FAKE_CANDIDATE_FAIL_ALWAYS FAKE_HEALTH_CLOCK_FILE
[[ "$candidate_failure_output" == *'candidate startup diagnostics'* ]] || fail "failed candidate diagnostics were not summarized before cleanup"
[[ "$candidate_failure_output" == *'permission_errors=1'* && "$candidate_failure_output" == *'database_errors=1'* ]] || fail "candidate startup error categories were not captured"
[[ "$candidate_failure_output" != *'SYNTHETIC_PRIVATE_SENTINEL_DO_NOT_EMIT'* ]] || fail "candidate logs leaked raw content"
[[ "$(<"$FAKE_CONTAINER_STATE_FILE")" == running ]] || fail "legacy container was not restored after candidate readiness timeout"
[[ ! -e "$FAKE_CANDIDATE_MARKER_FILE" ]] || fail "unhealthy candidate was not removed before restoring legacy service"
grep -F 'docker logs --tail 200 siftalpha-web-compose' "$FAKE_LOG" >/dev/null || fail "candidate logs were not summarized before removal"
grep -F 'docker start siftalpha-task011-ebd23f4' "$FAKE_LOG" >/dev/null || fail "legacy container was not restarted after candidate readiness timeout"

: > "$COMPOSE_FILE"
: > "$FAKE_LOG"
export FAKE_PLAN_MODE=none FAKE_CANDIDATE_FAIL_ALWAYS=1 FAKE_REQUIRE_LEGACY_STOPPED=1
FAKE_HEALTH_CLOCK_FILE="$TEST_ROOT/health.deploy.clock"
printf '0\n' > "$FAKE_HEALTH_CLOCK_FILE"
export FAKE_HEALTH_CLOCK_FILE
sleep() { :; }
if deploy_failure_output="$(deploy_candidate "$FAKE_DIGEST" 2>&1)"; then
  fail "deploy_candidate accepted a Compose service that never became ready"
fi
unset -f sleep
unset FAKE_CANDIDATE_FAIL_ALWAYS FAKE_REQUIRE_LEGACY_STOPPED FAKE_HEALTH_CLOCK_FILE
[[ "$deploy_failure_output" == *'candidate startup diagnostics'* ]] || fail "deploy_candidate omitted bounded startup diagnostics"
[[ "$deploy_failure_output" != *'SYNTHETIC_PRIVATE_SENTINEL_DO_NOT_EMIT'* ]] || fail "deploy_candidate exposed raw container logs"
[[ "$deploy_failure_output" != *'port is already allocated'* ]] || fail "stale Compose file bypassed the running legacy-container cutover"
[[ "$(<"$FAKE_CONTAINER_STATE_FILE")" == running ]] || fail "deploy_candidate did not restore the prior website after readiness timeout"
[[ ! -e "$FAKE_CANDIDATE_MARKER_FILE" ]] || fail "deploy_candidate left its unhealthy candidate active"
grep -F 'docker compose -f ' "$FAKE_LOG" >/dev/null || fail "deploy_candidate did not exercise its Compose cutover path"
grep -F 'docker start siftalpha-task011-ebd23f4' "$FAKE_LOG" >/dev/null || fail "deploy_candidate did not restart the prior website"
stop_line="$(grep -n -F 'docker stop siftalpha-task011-ebd23f4' "$FAKE_LOG" | head -n 1 | cut -d: -f1)"
compose_line="$(grep -n -F 'docker compose -f ' "$FAKE_LOG" | head -n 1 | cut -d: -f1)"
[[ -n "$stop_line" && -n "$compose_line" && "$stop_line" -lt "$compose_line" ]] \
  || fail "running legacy container was not stopped before the stale Compose file was applied"

export FAKE_CANDIDATE_IMAGE_MISMATCH=1
FAKE_CANDIDATE_IMAGE_MISMATCH_FILE="$TEST_ROOT/image-mismatch.once"
FAKE_CANDIDATE_IMAGE_MISMATCH_PENDING_FILE="$TEST_ROOT/image-mismatch.pending"
export FAKE_CANDIDATE_IMAGE_MISMATCH_FILE FAKE_CANDIDATE_IMAGE_MISMATCH_PENDING_FILE
: > "$FAKE_LOG"
assert_fail deploy_candidate "$FAKE_DIGEST"
unset FAKE_CANDIDATE_IMAGE_MISMATCH FAKE_CANDIDATE_IMAGE_MISMATCH_FILE FAKE_CANDIDATE_IMAGE_MISMATCH_PENDING_FILE
[[ "$(<"$FAKE_CONTAINER_STATE_FILE")" == running ]] || fail "legacy service was not restored when the candidate image digest differed"
[[ ! -e "$FAKE_CANDIDATE_MARKER_FILE" ]] || fail "candidate with the wrong immutable image reference remained active"

assert_ok deploy_candidate "$FAKE_DIGEST"
[[ -e "$FAKE_CANDIDATE_MARKER_FILE" ]] || fail "valid Compose deployment did not remain active for upgrade-path validation"
export FAKE_CANDIDATE_IMAGE_MISMATCH=1
FAKE_CANDIDATE_IMAGE_MISMATCH_FILE="$TEST_ROOT/image-mismatch-compose.once"
FAKE_CANDIDATE_IMAGE_MISMATCH_PENDING_FILE="$TEST_ROOT/image-mismatch-compose.pending"
export FAKE_CANDIDATE_IMAGE_MISMATCH_FILE FAKE_CANDIDATE_IMAGE_MISMATCH_PENDING_FILE
: > "$FAKE_LOG"
assert_fail deploy_candidate "$FAKE_DIGEST"
unset FAKE_CANDIDATE_IMAGE_MISMATCH FAKE_CANDIDATE_IMAGE_MISMATCH_FILE FAKE_CANDIDATE_IMAGE_MISMATCH_PENDING_FILE
[[ "$(<"$FAKE_CONTAINER_STATE_FILE")" == running && -e "$FAKE_CANDIDATE_MARKER_FILE" ]] \
  || fail "Compose upgrade mismatch did not restore the previously active Compose service"
[[ "$(grep -Fc 'docker compose -f ' "$FAKE_LOG")" -ge 2 ]] \
  || fail "Compose upgrade mismatch did not run the candidate and snapshot restoration paths"

assert_ok rollback

# A reviewed additive account migration must be recorded in the snapshot.
account_snapshot="$(latest_snapshot)"
approved_account_history='["formula_editor.0002_fixedindicatorstate","core.0012_auth_verification"]'
assert_ok record_snapshot_database_state "$account_snapshot" "$approved_account_history"
[[ "$(snapshot_value "$account_snapshot" database_migrations)" == "$approved_account_history" ]] \
  || fail "approved account migration was not recorded in rollback metadata"
assert_fail record_snapshot_database_state "$account_snapshot" '["core.9999_unreviewed"]'

for source_file in \
  deployment/web-admin/install-web-admin.sh \
  deployment/web-admin/siftalpha-web-admin \
  deployment/web-admin/lib/siftalpha-web-admin-lib.sh; do
  eol_attribute="$(git check-attr eol -- "$source_file")"
  [[ "$eol_attribute" == "$source_file: eol: lf" ]] \
    || fail "deployment source must be archived with LF line endings: $source_file"
done

grep -F 'upgrade_web_admin.py' "$ROOT/deployment/web-admin/install-web-admin.sh" >/dev/null \
  || fail "initial installer must deploy self-upgrade helper"
grep -F 'deploy|rollback|test-deploy|upgrade' "$LIB" >/dev/null \
  || fail "upgrade must participate in existing deployment operation lock"
assert_ok "$ROOT/deployment/web-admin/install-web-admin.sh" --check

printf 'web-admin contract: ok\n'
