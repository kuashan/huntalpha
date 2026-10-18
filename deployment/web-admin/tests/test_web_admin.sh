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
        printf '{"buildDefinition":{"buildType":"https://github.com/moby/buildkit/blob/master/docs/attestations/slsa-definitions.md","externalParameters":{},"resolvedDependencies":[]},"runDetails":{"builder":{"id":""},"metadata":{}}}\n'
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
    [[ "${3:-}" == siftalpha-web-compose ]] && exit 1
    exit 0 ;;
  run)
    [[ "$*" == *'--network none'* && "$*" == *'--read-only'* ]] || exit 1
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
    connection.commit()
finally:
    connection.close()
PY
      exit $?
    fi
    exit 1 ;;
  inspect)
    if [[ "${3:-}" == '{{.State.Status}}' ]]; then cat "$FAKE_CONTAINER_STATE_FILE"; else printf 'siftalpha-task011:ebd23f4\n'; fi
    exit 0 ;;
  compose)
    [[ "${FAKE_COMPOSE_FAIL:-0}" == 1 ]] && exit 1
    printf 'running\n' > "$FAKE_CONTAINER_STATE_FILE"
    exit 0 ;;
  stop) printf 'exited\n' > "$FAKE_CONTAINER_STATE_FILE"; exit 0 ;;
  start) printf 'running\n' > "$FAKE_CONTAINER_STATE_FILE"; exit 0 ;;
  rm) exit 0 ;;
  *) exit 0 ;;
esac
EOF

cat > "$FAKE_BIN/curl" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
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
    printf '{"status":"completed","conclusion":"success","head_sha":"%s","head_branch":"release/siftalpha-web-v1","name":"SiftAlpha Web CI and ARM64","html_url":"https://github.com/kuashan/huntalpha/actions/runs/%s"}\n' "$FAKE_COMMIT" "$FAKE_RUN_ID"
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
GH_SHA256="$(sha256sum "$FAKE_BIN/gh" | awk '{print $1}')"
FAKE_CONTAINER_STATE_FILE="$TEST_ROOT/container.state"
printf 'running\n' > "$FAKE_CONTAINER_STATE_FILE"
export FAKE_CONTAINER_STATE_FILE

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
PATH="$FAKE_BIN:$PATH"
export PATH

assert_ok validate_command status
assert_ok validate_command health
assert_ok validate_command preflight "$FAKE_DIGEST"
assert_ok validate_command deploy "$FAKE_DIGEST"
assert_ok validate_command test-deploy "$FAKE_DIGEST"
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
assert_ok preflight_candidate "$FAKE_DIGEST"
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

FAKE_COMPOSE_FAIL=1 assert_fail first_compose_cutover "$FAKE_DIGEST"
grep -F 'docker start siftalpha-task011-ebd23f4' "$FAKE_LOG" >/dev/null || fail "legacy container was not restarted"
grep -F 'docker rm siftalpha-task011-ebd23f4' "$FAKE_LOG" >/dev/null && fail "legacy container was removed"

assert_ok rollback

for source_file in \
  deployment/web-admin/install-web-admin.sh \
  deployment/web-admin/siftalpha-web-admin \
  deployment/web-admin/lib/siftalpha-web-admin-lib.sh; do
  eol_attribute="$(git check-attr eol -- "$source_file")"
  [[ "$eol_attribute" == "$source_file: eol: lf" ]] \
    || fail "deployment source must be archived with LF line endings: $source_file"
done

assert_ok "$ROOT/deployment/web-admin/install-web-admin.sh" --check

printf 'web-admin contract: ok\n'
