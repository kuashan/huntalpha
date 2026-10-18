#!/usr/bin/env python3
"""Tests for fail-closed migration approval and private-data preservation."""

import importlib.util
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HELPER_PATH = ROOT / "deployment" / "web-admin" / "lib" / "verify_database_migration.py"
SPEC = importlib.util.spec_from_file_location("verify_database_migration", HELPER_PATH)
MIGRATION_GUARD = None
if SPEC is not None and SPEC.loader is not None and HELPER_PATH.is_file():
    MIGRATION_GUARD = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(MIGRATION_GUARD)


APPROVED_HASH = "72514513ca8f6b801b2b68fef42f7b35e998c78d7cdcd9cd236e0dbffefa977a"


class MigrationGuardTestCase(unittest.TestCase):
    def guard(self):
        self.assertIsNotNone(MIGRATION_GUARD, "migration guard has not been implemented")
        return MIGRATION_GUARD


class MigrationPlanTests(MigrationGuardTestCase):
    def test_probe_state_tracks_the_approved_migration_when_applied(self):
        payload = {
            "pending": [],
            "applied": [{"name": "formula_editor.0002_fixedindicatorstate", "sha256": APPROVED_HASH}],
        }
        self.assertEqual(
            self.guard().validate_probe_state(payload),
            {"pending": [], "applied": ["formula_editor.0002_fixedindicatorstate"]},
        )

    def test_probe_state_rejects_unknown_or_ambiguous_applied_migrations(self):
        for applied in (
            [{"name": "core.9999_unknown", "sha256": "0" * 64}],
            [
                {"name": "formula_editor.0002_fixedindicatorstate", "sha256": APPROVED_HASH},
                {"name": "formula_editor.0002_fixedindicatorstate", "sha256": APPROVED_HASH},
            ],
        ):
            with self.subTest(applied=applied), self.assertRaisesRegex(
                ValueError, "unapproved Django migration plan"
            ):
                self.guard().validate_probe_state({"pending": [], "applied": applied})

    def test_probe_state_rejects_same_migration_as_pending_and_applied(self):
        migration = {
            "name": "formula_editor.0002_fixedindicatorstate",
            "backwards": False,
            "sha256": APPROVED_HASH,
        }
        with self.assertRaisesRegex(ValueError, "unapproved Django migration plan"):
            self.guard().validate_probe_state(
                {
                    "pending": [migration],
                    "applied": [{"name": migration["name"], "sha256": APPROVED_HASH}],
                }
            )

    def test_exact_reviewed_additive_migration_is_approved(self):
        plan = {
            "pending": [
                {
                    "name": "formula_editor.0002_fixedindicatorstate",
                    "backwards": False,
                    "sha256": APPROVED_HASH,
                }
            ]
        }

        self.assertEqual(
            self.guard().validate_plan(plan),
            ["formula_editor.0002_fixedindicatorstate"],
        )

    def test_empty_migration_plan_is_a_noop(self):
        self.assertEqual(self.guard().validate_plan({"pending": []}), [])

    def test_unknown_migration_is_rejected(self):
        plan = {
            "pending": [
                {"name": "core.9999_unknown", "backwards": False, "sha256": "0" * 64}
            ]
        }

        with self.assertRaisesRegex(ValueError, "unapproved Django migration plan"):
            self.guard().validate_plan(plan)

    def test_changed_or_reversed_approved_migration_is_rejected(self):
        for migration in (
            {
                "name": "formula_editor.0002_fixedindicatorstate",
                "backwards": False,
                "sha256": "0" * 64,
            },
            {
                "name": "formula_editor.0002_fixedindicatorstate",
                "backwards": True,
                "sha256": APPROVED_HASH,
            },
        ):
            with self.subTest(migration=migration), self.assertRaisesRegex(
                ValueError, "unapproved Django migration plan"
            ):
                self.guard().validate_plan({"pending": [migration]})

    def test_multiple_pending_migrations_are_rejected(self):
        approved = {
            "name": "formula_editor.0002_fixedindicatorstate",
            "backwards": False,
            "sha256": APPROVED_HASH,
        }
        other = {"name": "core.9999_unknown", "backwards": False, "sha256": "0" * 64}

        with self.assertRaisesRegex(ValueError, "unapproved Django migration plan"):
            self.guard().validate_plan({"pending": [approved, other]})

    def test_approved_hash_matches_the_checked_in_task_012_migration(self):
        migration_path = ROOT / "formula_editor" / "migrations" / "0002_fixedindicatorstate.py"
        source = migration_path.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(source).hexdigest(), APPROVED_HASH)


class ProtectedDatabaseComparisonTests(MigrationGuardTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.before = Path(self.tempdir.name) / "before.sqlite3"
        self.after = Path(self.tempdir.name) / "after.sqlite3"
        for path in (self.before, self.after):
            self._create_fixture(path)

    @staticmethod
    def _create_fixture(path):
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                """
                CREATE TABLE fixture (id INTEGER PRIMARY KEY, value TEXT);
                INSERT INTO fixture VALUES (1, 'synthetic baseline');
                CREATE TABLE auth_user (id INTEGER PRIMARY KEY, username TEXT, password TEXT);
                CREATE TABLE core_accountprofile (id INTEGER PRIMARY KEY, user_id INTEGER, market TEXT);
                CREATE TABLE core_accountmembership (id INTEGER PRIMARY KEY, user_id INTEGER, tier TEXT);
                CREATE TABLE core_watchlistentry (id INTEGER PRIMARY KEY, user_id INTEGER, symbol_id INTEGER);
                CREATE TABLE formula_editor_formula (id INTEGER PRIMARY KEY, code TEXT, source TEXT);
                CREATE TABLE django_migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, app TEXT, name TEXT, applied TEXT
                );
                INSERT INTO auth_user VALUES (1, 'synthetic-user', 'synthetic-hash');
                INSERT INTO core_accountprofile VALUES (1, 1, 'us');
                INSERT INTO core_accountmembership VALUES (1, 1, 'pro');
                INSERT INTO core_watchlistentry VALUES (1, 1, 77);
                INSERT INTO formula_editor_formula VALUES (1, 'SYNTHETIC_ONLY', 'synthetic test content');
                INSERT INTO django_migrations VALUES (1, 'formula_editor', '0001_initial', '2026-01-01 00:00:00');
                """
            )
        finally:
            connection.close()

    @staticmethod
    def _apply_approved_migration(path):
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "CREATE TABLE formula_editor_fixedindicatorstate "
                "(code varchar(32) NOT NULL PRIMARY KEY, enabled bool NOT NULL)"
            )
            connection.execute(
                "INSERT INTO django_migrations (app, name, applied) VALUES (?, ?, ?)",
                ("formula_editor", "0002_fixedindicatorstate", "2026-01-01 00:01:00"),
            )
            connection.commit()
        finally:
            connection.close()

    def test_identical_protected_tables_compare_equal(self):
        self.guard().compare_protected_tables(self.before, self.after)

    def test_formula_change_fails_without_echoing_row_content(self):
        connection = sqlite3.connect(self.after)
        try:
            connection.execute(
                "UPDATE formula_editor_formula SET source = ? WHERE id = 1",
                ("changed synthetic test content",),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(ValueError, "protected table changed: formula_editor_formula") as error:
            self.guard().compare_protected_tables(self.before, self.after)

        self.assertNotIn("synthetic test content", str(error.exception))

    def test_missing_protected_table_fails(self):
        connection = sqlite3.connect(self.after)
        try:
            connection.execute("DROP TABLE core_accountmembership")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(ValueError, "protected table missing: core_accountmembership"):
            self.guard().compare_protected_tables(self.before, self.after)

    def test_approved_schema_addition_promotes_atomically_and_preserves_data(self):
        target = Path(self.tempdir.name) / "target.sqlite3"
        migrated = Path(self.tempdir.name) / "migrated.sqlite3"
        self.guard().copy_database(self.before, target)
        self.guard().copy_database(self.before, migrated)
        self._apply_approved_migration(migrated)

        self.guard().promote_migrated_database(self.before, migrated, target)
        self.guard().compare_protected_tables(self.before, target)
        self.assertEqual(
            self.guard()._integrity(target),
            None,
        )
        connection = sqlite3.connect(target)
        try:
            self.assertIsNotNone(
                connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='formula_editor_fixedindicatorstate'"
                ).fetchone()
            )
        finally:
            connection.close()

    def test_atomic_promotion_refuses_live_sqlite_sidecar(self):
        target = Path(self.tempdir.name) / "target.sqlite3"
        migrated = Path(self.tempdir.name) / "migrated.sqlite3"
        self.guard().copy_database(self.before, target)
        self.guard().copy_database(self.before, migrated)
        self._apply_approved_migration(migrated)
        sidecar = Path(f"{target}-wal")
        sidecar.touch()
        self.addCleanup(lambda: sidecar.unlink(missing_ok=True))

        with self.assertRaisesRegex(ValueError, "sidecar exists"):
            self.guard().promote_migrated_database(self.before, migrated, target)
        self.guard().compare_protected_tables(self.before, target)

    def test_promote_rejects_any_other_schema_or_data_change(self):
        for mutation in ("extra_table", "formula_row"):
            with self.subTest(mutation=mutation):
                migrated = Path(self.tempdir.name) / f"migrated-{mutation}.sqlite3"
                target = Path(self.tempdir.name) / f"target-{mutation}.sqlite3"
                self.guard().copy_database(self.before, target)
                self.guard().copy_database(self.before, migrated)
                self._apply_approved_migration(migrated)
                connection = sqlite3.connect(migrated)
                try:
                    if mutation == "extra_table":
                        connection.execute("CREATE TABLE unexpected_table (id INTEGER PRIMARY KEY)")
                    else:
                        connection.execute(
                            "UPDATE formula_editor_formula SET source = ? WHERE id = 1",
                            ("changed synthetic test content",),
                        )
                    connection.commit()
                finally:
                    connection.close()

                with self.assertRaises(ValueError):
                    self.guard().promote_migrated_database(self.before, migrated, target)
                self.guard().compare_database_contents(self.before, target)

    def test_promote_refuses_concurrent_database_change_without_overwriting_it(self):
        target = Path(self.tempdir.name) / "target-concurrent.sqlite3"
        migrated = Path(self.tempdir.name) / "migrated-concurrent.sqlite3"
        self.guard().copy_database(self.before, target)
        self.guard().copy_database(self.before, migrated)
        self._apply_approved_migration(migrated)
        connection = sqlite3.connect(target)
        try:
            connection.execute("UPDATE fixture SET value = 'concurrent synthetic update' WHERE id = 1")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(ValueError, "database changed after final backup"):
            self.guard().promote_migrated_database(self.before, migrated, target)
        connection = sqlite3.connect(target)
        try:
            self.assertEqual(
                connection.execute("SELECT value FROM fixture WHERE id = 1").fetchone()[0],
                "concurrent synthetic update",
            )
        finally:
            connection.close()

    def test_post_replacement_verification_failure_restores_original_atomically(self):
        target = Path(self.tempdir.name) / "target-revert.sqlite3"
        migrated = Path(self.tempdir.name) / "migrated-revert.sqlite3"
        self.guard().copy_database(self.before, target)
        self.guard().copy_database(self.before, migrated)
        self._apply_approved_migration(migrated)
        original_validator = self.guard().validate_approved_migration_result

        def fail_only_after_replacement(before, after):
            if Path(after).resolve() == target.resolve():
                raise ValueError("synthetic post-replacement failure")
            original_validator(before, after)

        with mock.patch.object(
            self.guard(), "validate_approved_migration_result", side_effect=fail_only_after_replacement
        ):
            with self.assertRaises(self.guard().PromotionReverted):
                self.guard().promote_migrated_database(self.before, migrated, target)
        self.guard().compare_database_contents(self.before, target)

    def test_restore_replaces_only_the_isolated_target(self):
        target = Path(self.tempdir.name) / "target.sqlite3"
        self.guard().copy_database(self.after, target)
        connection = sqlite3.connect(target)
        try:
            connection.execute(
                "UPDATE formula_editor_formula SET source = ? WHERE id = 1",
                ("changed synthetic test content",),
            )
            connection.commit()
        finally:
            connection.close()

        self.guard().restore_database(self.before, target)
        self.guard().compare_protected_tables(self.before, target)


class RealDjangoMigrationRehearsalTests(MigrationGuardTestCase):
    def _run_manage(self, database_path, *arguments):
        environment = os.environ.copy()
        environment.update(
            {
                "DJANGO_SECRET_KEY": "web-admin-synthetic-test-only",
                "HUNTALPHA_DATABASE_PATH": str(database_path),
                "HUNTALPHA_ALLOWED_HOSTS": "localhost",
            }
        )
        subprocess.run(
            [sys.executable, str(ROOT / "manage.py"), *arguments],
            cwd=ROOT,
            env=environment,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _probe(self, database_path):
        environment = os.environ.copy()
        environment.update(
            {
                "DJANGO_SECRET_KEY": "web-admin-synthetic-test-only",
                "HUNTALPHA_DATABASE_PATH": str(database_path),
                "HUNTALPHA_ALLOWED_HOSTS": "localhost",
            }
        )
        result = subprocess.run(
            [sys.executable, str(ROOT / "deployment" / "web-admin" / "lib" / "migration_probe.py")],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            exception_type = result.stderr.strip().splitlines()[-1].split(":", 1)[0]
            self.fail(f"Django migration probe failed ({exception_type})")
        return json.loads(result.stdout)

    def test_actual_django_migration_is_rehearsed_and_promoted_on_synthetic_copy(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            baseline = temporary / "baseline.sqlite3"
            backup = temporary / "backup.sqlite3"
            rehearsal = temporary / "rehearsal.sqlite3"
            target = temporary / "target.sqlite3"

            self._run_manage(baseline, "migrate", "--noinput")
            self._run_manage(
                baseline,
                "migrate",
                "formula_editor",
                "0001_initial",
                "--noinput",
            )
            approved_state = self.guard().validate_probe_state(self._probe(baseline))
            self.assertEqual(
                approved_state,
                {"pending": ["formula_editor.0002_fixedindicatorstate"], "applied": []},
            )

            self.guard().copy_database(baseline, backup)
            self.guard().copy_database(backup, rehearsal)
            self._run_manage(rehearsal, "migrate", "--noinput")
            self.guard().validate_approved_migration_result(backup, rehearsal)
            self.guard().compare_protected_tables(backup, rehearsal)
            self.guard()._integrity(rehearsal)
            self.assertEqual(
                self.guard().validate_probe_state(self._probe(rehearsal)),
                {"pending": [], "applied": ["formula_editor.0002_fixedindicatorstate"]},
            )

            self.guard().copy_database(backup, target)
            self.guard().promote_migrated_database(backup, rehearsal, target)
            self.guard().validate_approved_migration_result(backup, target)
            self.guard().restore_database(backup, target)
            self.guard().compare_database_contents(backup, target)


if __name__ == "__main__":
    unittest.main()
