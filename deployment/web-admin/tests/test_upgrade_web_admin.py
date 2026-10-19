#!/usr/bin/env python3
"""No-network, non-root tests for the fixed-target self-upgrade contract."""
import base64
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

LIBRARY = Path(__file__).resolve().parents[1] / "lib" / "upgrade_web_admin.py"
SPEC = importlib.util.spec_from_file_location("siftalpha_upgrade_web_admin", LIBRARY)
upgrade = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(upgrade)
GOOD_SHA = "a" * 40


class ApprovedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.client = object.__new__(upgrade.GitHubSource)

    def test_approved_release_head_is_sufficient_without_actions_lookup(self):
        calls = []
        def api(path):
            calls.append(path)
            if path.startswith("repos/kuashan/huntalpha/git/ref/"):
                return {"object": {"sha": GOOD_SHA}}
            raise AssertionError(f"unexpected GitHub API request: {path}")
        self.client.api = api
        self.client.verify_release(GOOD_SHA)
        self.assertEqual(calls, [f"repos/{upgrade.REPO}/git/ref/heads/{upgrade.BRANCH}"])

    def test_commit_that_is_not_the_current_release_head_is_refused(self):
        self.client.api = lambda path: {"object": {"sha": "b" * 40}}
        with self.assertRaises(ValueError):
            self.client.verify_release(GOOD_SHA)

    def test_malformed_release_head_is_refused(self):
        self.client.api = lambda path: {"object": {"sha": "not-a-full-commit"}}
        with self.assertRaises(ValueError):
            self.client.verify_release(GOOD_SHA)

    def test_all_files_are_content_and_blob_verified(self):
        self.client.api = lambda path: {
            "type": "file",
            "path": path.split("/contents/", 1)[1].split("?ref=", 1)[0],
            "encoding": "base64",
            "content": base64.b64encode(b"synthetic content").decode(),
            "sha": upgrade._git_blob_sha(b"synthetic content"),
        }
        contents = self.client.reviewed_files(GOOD_SHA)
        self.assertEqual(set(contents), set(upgrade.SOURCES))
        self.client.api = lambda path: {
            "type": "file",
            "path": path.split("/contents/", 1)[1].split("?ref=", 1)[0],
            "encoding": "base64",
            "content": base64.b64encode(b"tampered").decode(),
            "sha": "0" * 40,
        }
        with self.assertRaises(ValueError):
            self.client.reviewed_files(GOOD_SHA)


class AtomicReplacementTests(unittest.TestCase):
    def setUp(self):
        geteuid = patch.object(upgrade.os, "geteuid", return_value=1000, create=True)
        geteuid.start()
        self.addCleanup(geteuid.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin_dir, self.lib_dir = self.root / "bin", self.root / "lib"
        self.bin_dir.mkdir()
        self.lib_dir.mkdir()
        self.targets = {
            "deployment/web-admin/siftalpha-web-admin": (self.bin_dir / "siftalpha-web-admin", 0o750),
            "deployment/web-admin/lib/siftalpha-web-admin-lib.sh": (self.lib_dir / "siftalpha-web-admin-lib.sh", 0o750),
            "deployment/web-admin/lib/upgrade_web_admin.py": (self.lib_dir / "upgrade_web_admin.py", 0o750),
        }
        self.new = {name: ("new " + name).encode() for name in self.targets}
        for source, (path, _) in self.targets.items():
            if source.endswith("upgrade_web_admin.py"):
                continue
            path.write_bytes(("old " + source).encode())

    def test_success_preserves_snapshot_and_does_not_modify_unrelated_file(self):
        unrelated = self.root / "private-db.sqlite3"
        unrelated.write_text("user data must not change")
        backup = upgrade.install_reviewed_files(
            self.new, self.root / "backups", targets=self.targets,
        )
        for source, (path, _) in self.targets.items():
            self.assertEqual(path.read_bytes(), self.new[source])
        self.assertEqual(unrelated.read_text(), "user data must not change")
        self.assertEqual(len(list(backup.iterdir())), 2)

    def test_health_failure_restores_old_files_and_removes_new_helper(self):
        def bad_health():
            raise RuntimeError("synthetic health failed")
        with self.assertRaises(RuntimeError):
            upgrade.install_reviewed_files(
                self.new, self.root / "backups", postcheck=bad_health,
                targets=self.targets,
            )
        for source, (path, _) in self.targets.items():
            if source.endswith("upgrade_web_admin.py"):
                self.assertFalse(path.exists())
            else:
                self.assertEqual(path.read_bytes(), ("old " + source).encode())

    def test_refuses_symlink_destination(self):
        destination = self.targets["deployment/web-admin/siftalpha-web-admin"][0]
        destination.unlink()
        destination.symlink_to(self.root / "unrelated.txt")
        with self.assertRaises(ValueError):
            upgrade.install_reviewed_files(self.new, self.root / "backups", targets=self.targets)

    def test_rejects_unreviewed_file_set(self):
        with self.assertRaises(ValueError):
            upgrade.install_reviewed_files(
                {**self.new, "arbitrary-script.sh": b"unsafe"}, self.root / "backups",
                targets=self.targets,
            )


if __name__ == "__main__":
    unittest.main()
