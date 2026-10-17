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
export FAKE_DIGEST="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
export FAKE_COMMIT="0123456789abcdef0123456789abcdef01234567"
export FAKE_RUN_ID="424242"

cat > "$FAKE_BIN/docker" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
{ printf 'docker'; printf ' %s' "$@"; printf '\n'; } >> "$FAKE_LOG"
case "${1:-}" in
  pull) exit 0 ;;
  buildx)
    printf '{"manifests":[{"platform":{"architecture":"arm64","os":"linux"}}]}\n'
    exit 0 ;;
  image)
    case "${4:-}" in
      '{{ index .Config.Labels "org.opencontainers.image.source" }}') printf 'https://github.com/kuashan/huntalpha\n' ;;
      '{{ index .Config.Labels "org.opencontainers.image.revision" }}') printf '%s\n' "$FAKE_COMMIT" ;;
      '{{ index .Config.Labels "io.siftalpha.build.run-id" }}') printf '%s\n' "$FAKE_RUN_ID" ;;
      '{{ index .Config.Labels "io.siftalpha.build.ref" }}') printf 'release/siftalpha-web-v1\n' ;;
      '{{ index .Config.Labels "org.opencontainers.image.version" }}') printf 'V1.0.0\n' ;;
      *) printf 'arm64\n' ;;
    esac
    exit 0 ;;
  container)
    [[ "${3:-}" == siftalpha-web-compose ]] && exit 1
    exit 0 ;;
  inspect)
    if [[ "${3:-}" == '{{.State.Status}}' ]]; then printf 'running\n'; else printf 'siftalpha-task011:ebd23f4\n'; fi
    exit 0 ;;
  compose)
    [[ "${FAKE_COMPOSE_FAIL:-0}" == 1 ]] && exit 1
    exit 0 ;;
  stop|start|rm) exit 0 ;;
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
case "${1:-}" in
  api)
    [[ "${FAKE_GH_MODE:-ok}" == run-mismatch ]] && { printf '{"conclusion":"failure"}\n'; exit 0; }
    printf '{"status":"completed","conclusion":"success","head_sha":"%s","head_branch":"release/siftalpha-web-v1","name":"SiftAlpha Web CI and ARM64"}\n' "$FAKE_COMMIT"
    ;;
  run)
    destination=""
    for ((i = 1; i <= $#; i++)); do
      [[ "${!i}" == --dir ]] && { j=$((i + 1)); destination="${!j}"; }
    done
    mkdir -p "$destination"
    [[ "${FAKE_GH_MODE:-ok}" == manifest-mismatch ]] && digest='sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' || digest="$FAKE_DIGEST"
    printf '{"image":"ghcr.io/kuashan/siftalpha-web","digest":"%s","source_commit":"%s","run_id":"%s","run_url":"https://github.com/kuashan/huntalpha/actions/runs/%s","ref":"release/siftalpha-web-v1","platform":"linux/arm64"}\n' "$digest" "$FAKE_COMMIT" "$FAKE_RUN_ID" "$FAKE_RUN_ID" > "$destination/siftalpha-web-build-manifest.json"
    ;;
  attestation)
    [[ "${FAKE_GH_MODE:-ok}" == attestation-fail ]] && exit 1
    printf '[]\n'
    ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$FAKE_BIN/docker" "$FAKE_BIN/curl" "$FAKE_BIN/gh"
GH_SHA256="$(sha256sum "$FAKE_BIN/gh" | awk '{print $1}')"

cat > "$TEST_ROOT/web-admin.conf" <<EOF
IMAGE_REPOSITORY=ghcr.io/kuashan/siftalpha-web
GITHUB_REPOSITORY=kuashan/huntalpha
GITHUB_WORKFLOW_NAME='SiftAlpha Web CI and ARM64'
GITHUB_SIGNER_WORKFLOW=kuashan/huntalpha/.github/workflows/siftalpha-web-arm64.yml
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
connection.execute("create table fixture (id integer primary key, value text)")
connection.execute("insert into fixture (value) values ('safe')")
connection.commit()
connection.close()
PY

source "$LIB"
load_config "$TEST_ROOT/web-admin.conf"

assert_ok validate_command status
assert_ok validate_command health
assert_ok validate_command preflight "$FAKE_DIGEST"
assert_ok validate_command deploy "$FAKE_DIGEST"
assert_ok validate_command rollback
assert_fail validate_command deploy
assert_fail validate_command preflight sha256:bad
assert_fail validate_command status unexpected

IMAGE_REPOSITORY=ghcr.io/evil/repository
load_config "$TEST_ROOT/web-admin.conf"
[[ "$IMAGE_REPOSITORY" == ghcr.io/kuashan/siftalpha-web ]] || fail "environment override changed fixed repository"

assert_ok preflight_candidate "$FAKE_DIGEST"
export FAKE_GH_MODE=manifest-mismatch
assert_fail preflight_candidate "$FAKE_DIGEST"
export FAKE_GH_MODE=attestation-fail
assert_fail preflight_candidate "$FAKE_DIGEST"
export FAKE_GH_MODE=run-mismatch
assert_fail preflight_candidate "$FAKE_DIGEST"
unset FAKE_GH_MODE

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

assert_ok "$ROOT/deployment/web-admin/install-web-admin.sh" --check

printf 'web-admin contract: ok\n'
