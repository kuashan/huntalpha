#!/usr/bin/env python3
"""Fixed-target, reviewed-commit self-update for the SiftAlpha website admin.

Only the website admin executable and its installed support files may change.
The installed root-owned config, secrets, sudoers, database and containers are
never touched by this action.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

REPO = "kuashan/huntalpha"
BRANCH = "release/siftalpha-web-v1"
EXECUTABLE = Path("/usr/local/sbin/siftalpha-web-admin")
LIBRARY = Path("/usr/local/libexec/siftalpha-web-admin")
SOURCES = {
    "deployment/web-admin/siftalpha-web-admin": (EXECUTABLE, 0o750),
    "deployment/web-admin/lib/siftalpha-web-admin-lib.sh": (LIBRARY / "siftalpha-web-admin-lib.sh", 0o750),
    "deployment/web-admin/lib/verify_buildkit_provenance.py": (LIBRARY / "verify_buildkit_provenance.py", 0o750),
    "deployment/web-admin/lib/verify_database_migration.py": (LIBRARY / "verify_database_migration.py", 0o750),
    "deployment/web-admin/lib/migration_probe.py": (LIBRARY / "migration_probe.py", 0o750),
    "deployment/web-admin/lib/upgrade_web_admin.py": (LIBRARY / "upgrade_web_admin.py", 0o750),
    "deployment/web-admin/compose.yaml.template": (LIBRARY / "compose.yaml.template", 0o640),
    "deployment/web-admin/compose.selftest.yaml.template": (LIBRARY / "compose.selftest.yaml.template", 0o640),
}


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


class GitHubSource:
    def __init__(self, gh_bin: str, token_file: str, gh_config_dir: str):
        self.gh_bin = gh_bin
        token = Path(token_file).read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError("GitHub verification token is missing")
        self.env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "GH_TOKEN": token,
            "GH_CONFIG_DIR": gh_config_dir,
            "HOME": "/var/empty",
        }

    def api(self, url: str) -> dict:
        result = subprocess.run(
            [self.gh_bin, "api", "-H", "Accept: application/vnd.github+json", url],
            env=self.env, capture_output=True, timeout=35, check=True,
        )
        return json.loads(result.stdout)

    def verify_release(self, sha: str) -> None:
        branch = self.api(f"repos/{REPO}/git/ref/heads/{BRANCH}")
        head = branch.get("object", {}).get("sha")
        if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
            raise ValueError("release branch HEAD is not a full commit SHA")
        if head != sha:
            raise ValueError("commit is not the current approved release branch HEAD")

    def reviewed_files(self, sha: str) -> dict[str, bytes]:
        result = {}
        for source in SOURCES:
            record = self.api(f"repos/{REPO}/contents/{source}?ref={sha}")
            if (
                record.get("type") != "file"
                or record.get("path") != source
                or record.get("encoding") != "base64"
                or not isinstance(record.get("content"), str)
            ):
                raise ValueError("unexpected GitHub source file")
            data = base64.b64decode(record["content"], validate=False)
            if not data or len(data) > 160_000 or _git_blob_sha(data) != record.get("sha"):
                raise ValueError("GitHub source integrity check failed")
            result[source] = data
        return result


def _check_files(contents: dict[str, bytes]) -> None:
    if set(contents) != set(SOURCES):
        raise ValueError("unexpected web-admin update file set")
    for source, data in contents.items():
        text = data.decode("utf-8")
        if source.endswith(".py"):
            ast.parse(text, filename=source)
        elif source.endswith(".sh") or source.endswith("/siftalpha-web-admin"):
            subprocess.run(["/bin/bash", "-n"], input=data, capture_output=True, check=True, timeout=10)


def _atomic_write(target: Path, data: bytes, mode: int) -> None:
    fd, name = tempfile.mkstemp(prefix=".web-admin-upgrade-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        if os.geteuid() == 0:
            os.chown(name, 0, 0)
        os.replace(name, target)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


def install_reviewed_files(
    contents: dict[str, bytes], backup_parent: Path, postcheck=None,
    targets: dict[str, tuple[Path, int]] | None = None,
) -> Path:
    """Purely local swap with full backup, and restoration on ordinary failure.

    Injectable targets are for isolated tests; the executable entry uses SOURCES.
    """
    targets = SOURCES if targets is None else targets
    if set(contents) != set(targets):
        raise ValueError("unexpected update file set")
    for source, (path, _) in targets.items():
        if not path.parent.is_dir() or path.parent.is_symlink():
            raise ValueError("web-admin target directory is unsafe")
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("web-admin target is unsafe")
        if source != "deployment/web-admin/lib/upgrade_web_admin.py" and not path.is_file():
            raise ValueError("installed web-admin file missing")
    backup_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if backup_parent.is_symlink():
        raise ValueError("web-admin backup directory is unsafe")
    backup = Path(tempfile.mkdtemp(prefix="upgrade-", dir=backup_parent))
    old = {}
    for source, (path, _) in targets.items():
        if path.exists():
            old[source] = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
            shutil.copy2(path, backup / path.name)
    try:
        for source, (path, mode) in targets.items():
            _atomic_write(path, contents[source], mode)
        if postcheck is not None:
            postcheck()
    except Exception:
        for source, (path, _) in targets.items():
            if source in old:
                data, mode = old[source]
                _atomic_write(path, data, mode)
            elif path.exists():
                path.unlink()
        raise
    return backup


def main() -> int:
    if len(sys.argv) != 6:
        raise ValueError("usage: upgrade_web_admin.py SHA GH_BIN TOKEN_FILE GH_CONFIG_DIR BACKUP_DIR")
    sha, gh_bin, token_file, gh_config_dir, backup_dir = sys.argv[1:]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("commit must be a full lowercase SHA")
    if os.geteuid() != 0:
        raise ValueError("web-admin upgrade must run as root via approved command")
    client = GitHubSource(gh_bin, token_file, gh_config_dir)
    client.verify_release(sha)
    contents = client.reviewed_files(sha)
    _check_files(contents)

    def postcheck():
        for command in ("status", "health"):
            subprocess.run([str(EXECUTABLE), command], check=True, capture_output=True, timeout=25)

    backup = install_reviewed_files(contents, Path(backup_dir), postcheck)
    print("web-admin upgrade: ok")
    print("source commit: " + sha)
    print("backup directory: " + str(backup))
    print("website service and database: unchanged")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # No token, mail key, user data or provider response is ever printed.
        print("siftalpha-web-admin: upgrade failed; existing files retained or restored", file=sys.stderr)
        raise SystemExit(1)
