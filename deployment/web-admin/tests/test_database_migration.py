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
from contextlib import closing
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
ACCOUNT_HASH = "2e02a54d4869e10dcb4da50a66a9656a63c2d120cd33ab8ec9cd757187effdc9"
WORKSPACE_HASH = "e398a835684bbf3fd216fc57a6539f2f990d92b9862f0f9f96a17974c4ff2cea"
EXPIRY_HASH = "8e3ce97ca723bceb21a62e59fa9e9f4055180e9304f88a7daf84c9f5f923669e"


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

    def test_exact_account_migration_hash_and_sequence(self):
        path = ROOT / "core" / "migrations" / "0012_auth_verification.py"
        self.assertEqual(hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest(), ACCOUNT_HASH)
        item = {"name": "core.0012_auth_verification", "backwards": False, "sha256": ACCOUNT_HASH}
        self.assertEqual(self.guard().validate_plan({"pending": [item]}), [item["name"]])
        self.assertEqual(
            self.guard().validate_probe_state({
                "pending": [item],
                "applied": [{"name": "formula_editor.0002_fixedindicatorstate", "sha256": APPROVED_HASH}],
            }),
            {"pending": [item["name"]], "applied": ["formula_editor.0002_fixedindicatorstate"]},
        )
        with self.assertRaises(ValueError):
            self.guard().validate_probe_state({"pending": [item], "applied": []})
        with self.assertRaises(ValueError):
            self.guard().validate_plan({"pending": [{**item, "sha256": "0" * 64}]})

    def test_only_exact_reviewed_workspace_hash_after_account_migration(self):
        source = ROOT / "core" / "migrations" / "0013_chartworkspace.py"
        self.assertEqual(
            hashlib.sha256(source.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
            WORKSPACE_HASH,
        )
        item = {"name": "core.0013_chartworkspace", "backwards": False, "sha256": WORKSPACE_HASH}
        previous = [
            {"name": "formula_editor.0002_fixedindicatorstate", "sha256": APPROVED_HASH},
            {"name": "core.0012_auth_verification", "sha256": ACCOUNT_HASH},
        ]
        self.assertEqual(self.guard().validate_plan({"pending": [item]}), [item["name"]])
        self.assertEqual(
            self.guard().validate_probe_state({"pending": [item], "applied": previous}),
            {"pending": [item["name"]], "applied": [x["name"] for x in previous]},
        )
        self.assertEqual(
            self.guard().validate_probe_state({
                "pending": [], "applied": [*previous, {"name": item["name"], "sha256": WORKSPACE_HASH}]
            }),
            {"pending": [], "applied": [*([x["name"] for x in previous]), item["name"]]},
        )
        for broken in (
            {**item, "sha256": "0" * 64}, {**item, "backwards": True},
        ):
            with self.assertRaisesRegex(ValueError, "unapproved Django migration plan"):
                self.guard().validate_plan({"pending": [broken]})
        with self.assertRaisesRegex(ValueError, "unapproved Django migration plan"):
            self.guard().validate_probe_state({"pending": [item], "applied": previous[:1]})
        with self.assertRaisesRegex(ValueError, "unapproved Django migration plan"):
            self.guard().validate_probe_state({
                "pending": [], "applied": [previous[0], {"name": item["name"], "sha256": WORKSPACE_HASH}]
            })

    def test_v114_expiry_migration_hash_and_prerequisite(self):
        path = ROOT / "core" / "migrations" / "0014_accountmembership_expires_at.py"
        self.assertEqual(hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest(), EXPIRY_HASH)
        item = {"name": "core.0014_accountmembership_expires_at", "backwards": False, "sha256": EXPIRY_HASH}
        previous = [
            {"name": "formula_editor.0002_fixedindicatorstate", "sha256": APPROVED_HASH},
            {"name": "core.0012_auth_verification", "sha256": ACCOUNT_HASH},
            {"name": "core.0013_chartworkspace", "sha256": WORKSPACE_HASH},
        ]
        self.assertEqual(self.guard().validate_probe_state({"pending": [item], "applied": previous}),
                         {"pending": [item["name"]], "applied": [r["name"] for r in previous]})
        self.assertEqual(self.guard().validate_probe_state({
            "pending": [], "applied": [*previous, {"name": item["name"], "sha256": EXPIRY_HASH}]
        }), {"pending": [], "applied": [r["name"] for r in previous] + [item["name"]]})
        with self.assertRaises(ValueError):
            self.guard().validate_probe_state({"pending": [item], "applied": previous[:-1]})
        with self.assertRaises(ValueError):
            self.guard().validate_plan({"pending": [{**item, "sha256": "0"*64}]})

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
                CREATE TABLE django_content_type (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_label TEXT NOT NULL,
                    model TEXT NOT NULL,
                    UNIQUE(app_label, model)
                );
                CREATE TABLE auth_permission (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    content_type_id INTEGER NOT NULL,
                    codename TEXT NOT NULL,
                    UNIQUE(content_type_id, codename)
                );
                CREATE TABLE django_migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, app TEXT, name TEXT, applied TEXT
                );
                INSERT INTO auth_user VALUES (1, 'synthetic-user', 'synthetic-hash');
                INSERT INTO core_accountprofile VALUES (1, 1, 'us');
                INSERT INTO core_accountmembership VALUES (1, 1, 'pro');
                INSERT INTO core_watchlistentry VALUES (1, 1, 77);
                INSERT INTO formula_editor_formula VALUES (1, 'SYNTHETIC_ONLY', 'synthetic test content');
                INSERT INTO django_content_type (id, app_label, model) VALUES (1, 'auth', 'user');
                INSERT INTO auth_permission (id, name, content_type_id, codename)
                    VALUES (1, 'Can view user', 1, 'view_user');
                INSERT INTO django_migrations VALUES (1, 'formula_editor', '0001_initial', '2026-01-01 00:00:00');
                """
            )
        finally:
            connection.close()

    @staticmethod
    def _apply_approved_migration(
        path,
        table_sql='CREATE TABLE formula_editor_fixedindicatorstate '
        '(code varchar(32) NOT NULL PRIMARY KEY, enabled bool NOT NULL)',
    ):
        connection = sqlite3.connect(path)
        try:
            connection.execute(table_sql)
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
                    "INSERT INTO auth_permission (name, content_type_id, codename) "
                    "VALUES (?, ?, ?)",
                    (name, content_type_id, codename),
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

    def test_sqlite_sequence_cannot_advance_beyond_approved_rows(self):
        migrated = Path(self.tempdir.name) / "migrated-sequence.sqlite3"
        self.guard().copy_database(self.before, migrated)
        self._apply_approved_migration(migrated)
        connection = sqlite3.connect(migrated)
        try:
            connection.execute(
                "UPDATE sqlite_sequence SET seq = 999 WHERE name = 'auth_permission'"
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(ValueError, "SQLite sequence metadata changed unexpectedly"):
            self.guard().validate_approved_migration_result(self.before, migrated)

    def test_approved_migration_rejects_trigger_attached_to_new_state_table(self):
        migrated = Path(self.tempdir.name) / "migrated-trigger.sqlite3"
        self.guard().copy_database(self.before, migrated)
        self._apply_approved_migration(migrated)
        connection = sqlite3.connect(migrated)
        try:
            connection.execute(
                "CREATE TRIGGER unexpected_state_trigger "
                "AFTER INSERT ON formula_editor_fixedindicatorstate "
                "BEGIN UPDATE formula_editor_formula SET source='changed' WHERE id=1; END"
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(ValueError, "unexpected schema object attached to Task 012 state table"):
            self.guard().validate_approved_migration_result(self.before, migrated)

    def test_approved_migration_rejects_unreviewed_table_defaults_and_constraints(self):
        definitions = (
            "CREATE TABLE formula_editor_fixedindicatorstate "
            "(code varchar(32) NOT NULL PRIMARY KEY, enabled bool NOT NULL DEFAULT 1)",
            "CREATE TABLE formula_editor_fixedindicatorstate "
            "(code varchar(32) NOT NULL PRIMARY KEY, enabled bool NOT NULL "
            "CHECK (enabled IN (0, 1)))",
        )
        for index, definition in enumerate(definitions):
            with self.subTest(index=index):
                migrated = Path(self.tempdir.name) / f"migrated-definition-{index}.sqlite3"
                self.guard().copy_database(self.before, migrated)
                self._apply_approved_migration(migrated, table_sql=definition)

                with self.assertRaisesRegex(ValueError, "new Task 012 state table schema is unexpected"):
                    self.guard().validate_approved_migration_result(self.before, migrated)

    def test_validate_result_cli_accepts_reviewed_migration(self):
        migrated = Path(self.tempdir.name) / "migrated-cli.sqlite3"
        self.guard().copy_database(self.before, migrated)
        self._apply_approved_migration(migrated)

        result = subprocess.run(
            [
                sys.executable,
                str(HELPER_PATH),
                "validate-result",
                str(self.before),
                str(migrated),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "migration result: ok")

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
    @staticmethod
    def _remove_task012_content_type_from_baseline(database_path):
        connection = sqlite3.connect(database_path)
        try:
            row = connection.execute(
                "SELECT id FROM django_content_type "
                "WHERE app_label=? AND model=?",
                ("formula_editor", "fixedindicatorstate"),
            ).fetchone()
            if row:
                connection.execute(
                    "DELETE FROM auth_permission WHERE content_type_id=?",
                    (row[0],),
                )
                connection.execute(
                    "DELETE FROM django_content_type WHERE id=?",
                    (row[0],),
                )
            connection.commit()
        finally:
            connection.close()

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
            # Keep the current core chain applied so only the Task 012 migration is pending.
            self._run_manage(
                baseline,
                "migrate",
                "formula_editor",
                "0001_initial",
                "--noinput",
            )
            self._remove_task012_content_type_from_baseline(baseline)
            approved_state = self.guard().validate_probe_state(self._probe(baseline))
            self.assertEqual(
                approved_state,
                {"pending": ["formula_editor.0002_fixedindicatorstate"], "applied": ["core.0012_auth_verification", "core.0013_chartworkspace", "core.0014_accountmembership_expires_at"]},
            )

            self.guard().copy_database(baseline, backup)
            self.guard().copy_database(backup, rehearsal)
            self._run_manage(rehearsal, "migrate", "--noinput")
            self.guard().validate_approved_migration_result(backup, rehearsal)
            self.guard().compare_protected_tables(backup, rehearsal)
            self.guard()._integrity(rehearsal)
            self.assertEqual(
                self.guard().validate_probe_state(self._probe(rehearsal)),
                {"pending": [], "applied": ["formula_editor.0002_fixedindicatorstate", "core.0012_auth_verification", "core.0013_chartworkspace", "core.0014_accountmembership_expires_at"]},
            )

            self.guard().copy_database(backup, target)
            self.guard().promote_migrated_database(backup, rehearsal, target)
            self.guard().validate_approved_migration_result(backup, target)
            self.guard().restore_database(backup, target)
            self.guard().compare_database_contents(backup, target)


class RealAccountMigrationRehearsalTests(RealDjangoMigrationRehearsalTests):
    def test_core_0012_rehearsal_has_only_two_new_empty_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline, migrated = root / "baseline.sqlite3", root / "migrated.sqlite3"
            self._run_manage(baseline, "migrate", "--noinput")
            self._run_manage(baseline, "migrate", "core", "0011_accountmembership", "--noinput")
            # Django does not automatically delete stale content types on migration rollback.
            connection = sqlite3.connect(baseline)
            try:
                for model in ("pendingemailregistration", "authratelimit"):
                    rows = connection.execute(
                        "SELECT id FROM django_content_type WHERE app_label='core' AND model=?",
                        (model,),
                    ).fetchall()
                    for row in rows:
                        connection.execute("DELETE FROM auth_permission WHERE content_type_id=?", (row[0],))
                        connection.execute("DELETE FROM django_content_type WHERE id=?", (row[0],))
                connection.commit()
            finally:
                connection.close()
            probe = self._probe(baseline)
            if any(item["name"] == "core.0013_chartworkspace" for item in probe["pending"]):
                # V1.0.0 production guard must reject the NEW unapproved schema.
                # Review/allowlist of 0013 belongs to a separately authorized release.
                with self.assertRaisesRegex(ValueError, "unapproved Django migration plan"):
                    self.guard().validate_probe_state(probe)
                return
            state = self.guard().validate_probe_state(probe)
            self.assertEqual(state, {
                "pending": ["core.0012_auth_verification"],
                "applied": ["formula_editor.0002_fixedindicatorstate"],
            })
            self.guard().copy_database(baseline, migrated)
            self._run_manage(migrated, "migrate", "--noinput")
            self.guard().validate_approved_migration_result(baseline, migrated)
            self.guard().compare_protected_tables(baseline, migrated)
            self.assertEqual(
                self.guard().validate_probe_state(self._probe(migrated)),
                {"pending": [], "applied": ["formula_editor.0002_fixedindicatorstate", "core.0012_auth_verification"]},
            )
            # A trigger on the new tables is never part of the approved migration.
            unsafe = root / "unsafe-trigger.sqlite3"
            self.guard().copy_database(migrated, unsafe)
            connection = sqlite3.connect(unsafe)
            try:
                connection.execute(
                    "CREATE TRIGGER hidden_update AFTER INSERT ON core_authratelimit "
                    "BEGIN SELECT 1; END"
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaises(ValueError):
                self.guard().validate_approved_migration_result(baseline, unsafe)
            # Any change to existing private Formula data must block promotion.
            connection = sqlite3.connect(migrated)
            try:
                connection.execute("UPDATE formula_editor_formula SET source='tampered' WHERE id=(SELECT id FROM formula_editor_formula LIMIT 1)")
                connection.execute("CREATE TABLE unapproved_extra (id INTEGER PRIMARY KEY)")
                connection.commit()
            finally:
                connection.close()
            with self.assertRaises(ValueError):
                self.guard().validate_approved_migration_result(baseline, migrated)



class RealWorkspaceMigrationGuardTests(RealDjangoMigrationRehearsalTests):
    def test_rehearses_only_workspace_addition_without_touching_original_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline, migrated = root / "baseline.sqlite3", root / "migrated.sqlite3"
            self._run_manage(baseline, "migrate", "--noinput")
            self._run_manage(baseline, "migrate", "core", "0012_auth_verification", "--noinput")
            # Django retains content types on model migration rollback; remove
            # synthetic residue before comparing a real V1.0.0-shaped baseline.
            with closing(sqlite3.connect(baseline)) as connection, connection:
                rows = connection.execute(
                    "SELECT id FROM django_content_type WHERE app_label='core' AND model='chartworkspace'"
                ).fetchall()
                for (identifier,) in rows:
                    connection.execute("DELETE FROM auth_permission WHERE content_type_id=?", (identifier,))
                    connection.execute("DELETE FROM django_content_type WHERE id=?", (identifier,))
                connection.commit()

            probe = self._probe(baseline)
            self.assertEqual(
                [item["name"] for item in probe["pending"]],
                ["core.0013_chartworkspace", "core.0014_accountmembership_expires_at"],
            )
            with self.assertRaisesRegex(ValueError, "unapproved Django migration plan"):
                self.guard().validate_probe_state(probe)
            self.guard().copy_database(baseline, migrated)
            self._run_manage(migrated, "migrate", "core", "0013_chartworkspace", "--noinput")
            self.guard().validate_approved_migration_result(baseline, migrated)
            self.guard().compare_protected_tables(baseline, migrated)
            self.assertEqual(
                self.guard().validate_probe_state(self._probe(migrated)),
                {
                    "pending": ["core.0014_accountmembership_expires_at"],
                    "applied": [
                        "formula_editor.0002_fixedindicatorstate",
                        "core.0012_auth_verification",
                        "core.0013_chartworkspace",
                    ],
                },
            )
            # A nonempty workspace table, a trigger, or an altered protected
            # Formula are each separately forbidden by the production verifier.
            mutations = (
                ("row", "INSERT INTO core_chartworkspace (main, sub, pane_heights, updated_at, user_id) "
                        "VALUES ('[]', '[]', '{}', CURRENT_TIMESTAMP, 1)"),
                ("trigger", "CREATE TRIGGER surprise AFTER INSERT ON core_chartworkspace BEGIN SELECT 1; END"),
                ("table", "CREATE TABLE unrelated (id integer PRIMARY KEY)"),
            )
            for name, sql in mutations:
                bad = root / f"bad-{name}.sqlite3"
                self.guard().copy_database(migrated, bad)
                with closing(sqlite3.connect(bad)) as connection, connection:
                    connection.execute(sql)
                    connection.commit()
                with self.subTest(name=name), self.assertRaises(ValueError):
                    self.guard().validate_approved_migration_result(baseline, bad)


class RealExpiryMigrationGuardTests(RealDjangoMigrationRehearsalTests):
    def test_adds_only_nullable_expiration_and_preserves_account_rows(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            baseline, upgraded = root / "before.sqlite3", root / "after.sqlite3"
            self._run_manage(baseline, "migrate", "--noinput")
            self._run_manage(baseline, "migrate", "core", "0013_chartworkspace", "--noinput")
            with closing(sqlite3.connect(baseline)) as connection, connection:
                connection.execute('INSERT INTO auth_user (password,last_login,is_superuser,username,first_name,last_name,email,is_staff,is_active,date_joined) '
                                   "VALUES ('test',NULL,0,'expiry-legacy','', '', 'legacy@example.com',0,1,CURRENT_TIMESTAMP)")
                user_id = connection.execute("SELECT id FROM auth_user WHERE username='expiry-legacy'").fetchone()[0]
                connection.execute('INSERT INTO core_accountmembership (user_id,tier) VALUES (?,?)', (user_id, "pro"))
                connection.commit()
            state = self.guard().validate_probe_state(self._probe(baseline))
            self.assertEqual(state["pending"], ["core.0014_accountmembership_expires_at"])
            self.assertEqual(state["applied"][-1], "core.0013_chartworkspace")
            self.guard().copy_database(baseline, upgraded)
            self._run_manage(upgraded, "migrate", "--noinput")
            self.guard().validate_approved_migration_result(baseline, upgraded)
            self.guard().compare_protected_tables(baseline, upgraded)
            with closing(sqlite3.connect(upgraded)) as connection, connection:
                self.assertEqual(connection.execute(
                    "SELECT tier, expires_at FROM core_accountmembership WHERE user_id=?", (user_id,)
                ).fetchone(), ("pro", None))
            for name, statement in (
                ("grant", "UPDATE core_accountmembership SET expires_at='2027-01-01' WHERE tier='pro'"),
                ("formula", "UPDATE auth_user SET username='tampered' WHERE username='expiry-legacy'"),
                ("table", "CREATE TABLE unexpected_table (id INTEGER PRIMARY KEY)"),
            ):
                damaged = root / f"damaged-{name}.sqlite3"
                self.guard().copy_database(upgraded, damaged)
                with closing(sqlite3.connect(damaged)) as connection, connection:
                    connection.execute(statement)
                with self.subTest(name=name), self.assertRaises(ValueError):
                    self.guard().validate_approved_migration_result(baseline, damaged)


if __name__ == "__main__":
    unittest.main()
