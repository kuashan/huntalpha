#!/usr/bin/env bash
# Installs only the fixed-target website admin capability. It never starts,
# replaces, rolls back, or otherwise changes the SiftAlpha website service.
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR=/usr/local/libexec/siftalpha-web-admin
BIN_PATH=/usr/local/sbin/siftalpha-web-admin
CONFIG_PATH=/etc/siftalpha-web-admin.conf
SUDOERS_PATH=/etc/sudoers.d/rdc-agent-siftalpha-web
STATE_PATH=/var/lib/siftalpha-web-admin
RDC_DROPIN_PATH=/etc/systemd/system/remote-desktop-commander.service.d/20-siftalpha-web-admin.conf

die() { printf 'install-web-admin: %s\n' "$*" >&2; exit 1; }

check_sources() {
  local file
  for file in \
    "$SCRIPT_DIR/siftalpha-web-admin" \
    "$SCRIPT_DIR/lib/siftalpha-web-admin-lib.sh" \
    "$SCRIPT_DIR/lib/verify_buildkit_provenance.py" \
    "$SCRIPT_DIR/lib/verify_database_migration.py" \
    "$SCRIPT_DIR/lib/migration_probe.py" \
    "$SCRIPT_DIR/compose.yaml.template" \
    "$SCRIPT_DIR/compose.selftest.yaml.template" \
    "$SCRIPT_DIR/siftalpha-web-admin.conf.example" \
    "$SCRIPT_DIR/rdc-agent-web-admin.conf" \
    "$SCRIPT_DIR/rdc-agent-sudoers"; do
    [[ -f "$file" ]] || die "missing source file: $file"
  done
  bash -n "$SCRIPT_DIR/siftalpha-web-admin" "$SCRIPT_DIR/lib/siftalpha-web-admin-lib.sh"
  python3 - "$SCRIPT_DIR/lib/verify_database_migration.py" "$SCRIPT_DIR/lib/migration_probe.py" <<'PY'
import ast
import pathlib
import sys
for source in sys.argv[1:]:
    ast.parse(pathlib.Path(source).read_text(encoding="utf-8"), filename=source)
PY
  grep -qxF '[Service]' "$SCRIPT_DIR/rdc-agent-web-admin.conf" || die 'RDC drop-in unit section is invalid'
  grep -qxF 'ReadWritePaths=/var/lib/siftalpha-web-admin' "$SCRIPT_DIR/rdc-agent-web-admin.conf" || die 'RDC write allowance is not limited to the web-admin state directory'
  grep -qxF 'rdc-agent ALL=(root) NOPASSWD: /usr/local/sbin/siftalpha-web-admin' "$SCRIPT_DIR/rdc-agent-sudoers" || die 'sudoers template is not fixed-target'
  printf 'install-web-admin: source check ok\n'
}

install_files() {
  [[ "${EUID}" -eq 0 ]] || die '--install requires root'
  command -v visudo >/dev/null || die 'visudo is required for a safe sudoers installation'
  check_sources
  if [[ -e "$CONFIG_PATH" || -L "$CONFIG_PATH" ]]; then
    # shellcheck disable=SC1090
    source "$SCRIPT_DIR/lib/siftalpha-web-admin-lib.sh"
    assert_secure_config_file "$CONFIG_PATH" || die 'existing web-admin configuration is unsafe'
  fi
  if [[ -e "$RDC_DROPIN_PATH" ]]; then
    cmp -s "$SCRIPT_DIR/rdc-agent-web-admin.conf" "$RDC_DROPIN_PATH" \
      || die 'existing RDC web-admin drop-in differs; refusing to overwrite it'
  else
    systemctl is-active --quiet remote-desktop-commander.service \
      || die 'RDC service must be active before adding its web-admin write allowance'
  fi
  install -d -o root -g root -m 0750 /usr/local/sbin "$LIB_DIR"
  install -d -o root -g root -m 0700 "$STATE_PATH" "$STATE_PATH/backups" "$STATE_PATH/rollbacks" "$STATE_PATH/recovery-checks" "$STATE_PATH/ghcr-docker-config"
  install -o root -g root -m 0750 "$SCRIPT_DIR/siftalpha-web-admin" "$BIN_PATH"
  install -o root -g root -m 0750 "$SCRIPT_DIR/lib/siftalpha-web-admin-lib.sh" "$LIB_DIR/siftalpha-web-admin-lib.sh"
  install -o root -g root -m 0750 "$SCRIPT_DIR/lib/verify_buildkit_provenance.py" "$LIB_DIR/verify_buildkit_provenance.py"
  install -o root -g root -m 0750 "$SCRIPT_DIR/lib/verify_database_migration.py" "$LIB_DIR/verify_database_migration.py"
  install -o root -g root -m 0750 "$SCRIPT_DIR/lib/migration_probe.py" "$LIB_DIR/migration_probe.py"
  install -o root -g root -m 0640 "$SCRIPT_DIR/compose.yaml.template" "$LIB_DIR/compose.yaml.template"
  install -o root -g root -m 0640 "$SCRIPT_DIR/compose.selftest.yaml.template" "$LIB_DIR/compose.selftest.yaml.template"
  if [[ ! -e "$CONFIG_PATH" ]]; then
    install -o root -g root -m 0600 "$SCRIPT_DIR/siftalpha-web-admin.conf.example" "$CONFIG_PATH"
    printf 'install-web-admin: installed configuration template; a root administrator must set the verified GitHub CLI checksum and server-specific values before preflight\n' >&2
  fi
  local staged_sudoers
  staged_sudoers="$(mktemp /etc/sudoers.d/.rdc-agent-siftalpha-web.XXXXXX)"
  trap 'rm -f "$staged_sudoers"' EXIT
  install -o root -g root -m 0440 "$SCRIPT_DIR/rdc-agent-sudoers" "$staged_sudoers"
  visudo -cf "$staged_sudoers" >/dev/null
  mv -f "$staged_sudoers" "$SUDOERS_PATH"
  trap - EXIT
  install_rdc_write_allowance
  printf 'install-web-admin: installed management capability only; no website container was started, stopped, replaced, or restarted\n'
}

install_rdc_write_allowance() {
  local source="$SCRIPT_DIR/rdc-agent-web-admin.conf" dropin_dir
  dropin_dir="$(dirname "$RDC_DROPIN_PATH")"
  if [[ -e "$RDC_DROPIN_PATH" ]]; then
    cmp -s "$source" "$RDC_DROPIN_PATH" || die 'existing RDC web-admin drop-in differs; refusing to overwrite it'
    return 0
  fi
  install -d -o root -g root -m 0755 "$dropin_dir"
  local staged
  staged="$(mktemp "$dropin_dir/.20-siftalpha-web-admin.XXXXXX")"
  install -o root -g root -m 0644 "$source" "$staged"
  mv -f "$staged" "$RDC_DROPIN_PATH"
  if ! systemctl daemon-reload || ! systemctl restart remote-desktop-commander.service \
    || ! systemctl is-active --quiet remote-desktop-commander.service; then
    rm -f "$RDC_DROPIN_PATH"
    systemctl daemon-reload || true
    systemctl restart remote-desktop-commander.service || true
    die 'RDC write allowance was not activated; the newly added drop-in was removed'
  fi
  printf 'install-web-admin: RDC can write only its existing command-admin state directory; allowedDirectories and sudoers remain unchanged\n'
}

case "${1:-}" in
  --check)
    [[ "$#" -eq 1 ]] || die 'usage: install-web-admin.sh --check | --install'
    check_sources
    ;;
  --install)
    [[ "$#" -eq 1 ]] || die 'usage: install-web-admin.sh --check | --install'
    install_files
    ;;
  *) die 'usage: install-web-admin.sh --check | --install' ;;
esac
