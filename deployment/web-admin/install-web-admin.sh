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

die() { printf 'install-web-admin: %s\n' "$*" >&2; exit 1; }

check_sources() {
  local file
  for file in \
    "$SCRIPT_DIR/siftalpha-web-admin" \
    "$SCRIPT_DIR/lib/siftalpha-web-admin-lib.sh" \
    "$SCRIPT_DIR/lib/verify_buildkit_provenance.py" \
    "$SCRIPT_DIR/compose.yaml.template" \
    "$SCRIPT_DIR/siftalpha-web-admin.conf.example" \
    "$SCRIPT_DIR/rdc-agent-sudoers"; do
    [[ -f "$file" ]] || die "missing source file: $file"
  done
  bash -n "$SCRIPT_DIR/siftalpha-web-admin" "$SCRIPT_DIR/lib/siftalpha-web-admin-lib.sh"
  grep -qxF 'rdc-agent ALL=(root) NOPASSWD: /usr/local/sbin/siftalpha-web-admin' "$SCRIPT_DIR/rdc-agent-sudoers" || die 'sudoers template is not fixed-target'
  printf 'install-web-admin: source check ok\n'
}

install_files() {
  [[ "${EUID}" -eq 0 ]] || die '--install requires root'
  command -v visudo >/dev/null || die 'visudo is required for a safe sudoers installation'
  check_sources
  install -d -o root -g root -m 0750 /usr/local/sbin "$LIB_DIR"
  install -d -o root -g root -m 0700 "$STATE_PATH" "$STATE_PATH/backups" "$STATE_PATH/rollbacks" "$STATE_PATH/recovery-checks" "$STATE_PATH/ghcr-docker-config"
  install -o root -g root -m 0750 "$SCRIPT_DIR/siftalpha-web-admin" "$BIN_PATH"
  install -o root -g root -m 0750 "$SCRIPT_DIR/lib/siftalpha-web-admin-lib.sh" "$LIB_DIR/siftalpha-web-admin-lib.sh"
  install -o root -g root -m 0750 "$SCRIPT_DIR/lib/verify_buildkit_provenance.py" "$LIB_DIR/verify_buildkit_provenance.py"
  install -o root -g root -m 0640 "$SCRIPT_DIR/compose.yaml.template" "$LIB_DIR/compose.yaml.template"
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
  printf 'install-web-admin: installed management capability only; no website container was started, stopped, replaced, or restarted\n'
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
