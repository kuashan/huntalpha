#!/usr/bin/env python3
"""Fail-closed migration approval and SQLite copy/promotion helpers.

This file is installed root-owned and is called only by the fixed web-admin
dispatcher. It never prints database rows, row hashes, or Formula contents.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import json
import os
import re
import sqlite3
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any


APPROVED_MIGRATIONS = {
    "formula_editor.0002_fixedindicatorstate": "72514513ca8f6b801b2b68fef42f7b35e998c78d7cdcd9cd236e0dbffefa977a",
    "core.0012_auth_verification": "2e02a54d4869e10dcb4da50a66a9656a63c2d120cd33ab8ec9cd757187effdc9",
    "core.0013_chartworkspace": "e398a835684bbf3fd216fc57a6539f2f990d92b9862f0f9f96a17974c4ff2cea",
    "core.0014_accountmembership_expires_at": "8e3ce97ca723bceb21a62e59fa9e9f4055180e9304f88a7daf84c9f5f923669e",
}
PROTECTED_TABLES = (
    "auth_user",
    "core_accountprofile",
    "core_accountmembership",
    "core_watchlistentry",
    "formula_editor_formula",
)
APPROVED_TASK012_TABLE_SQL = (
    'CREATE TABLE "formula_editor_fixedindicatorstate" '
    '("code" varchar(32) NOT NULL PRIMARY KEY, "enabled" bool NOT NULL)'
)


class AtomicInstallFailure(ValueError):
    def __init__(self, replaced: bool):
        super().__init__("atomic SQLite replacement failed")
        self.replaced = replaced


class PromotionReverted(ValueError):
    pass


class PromotionRecoveryFailure(ValueError):
    pass


def _reject() -> ValueError:
    return ValueError("unapproved Django migration plan")


def _normalize_sql(sql: str) -> str:
    return re.sub(r'[\s"`\[\]]+', "", sql).casefold()


def validate_plan(payload: Any) -> list[str]:
    """Return the reviewed pending migration names or reject the whole plan."""
    if not isinstance(payload, dict) or set(payload) != {"pending"}:
        raise _reject()
    pending = payload["pending"]
    if not isinstance(pending, list):
        raise _reject()
    if not pending:
        return []
    if len(pending) != 1:
        raise _reject()
    migration = pending[0]
    if not isinstance(migration, dict) or set(migration) != {"name", "backwards", "sha256"}:
        raise _reject()
    name = migration["name"]
    if (
        not isinstance(name, str)
        or migration["backwards"] is not False
        or not isinstance(migration["sha256"], str)
        or APPROVED_MIGRATIONS.get(name) != migration["sha256"]
    ):
        raise _reject()
    return [name]


def validate_probe_state(payload: Any) -> dict[str, list[str]]:
    """Validate both pending work and the approved migration already in DB."""
    if not isinstance(payload, dict) or set(payload) != {"pending", "applied"}:
        raise _reject()
    pending = validate_plan({"pending": payload["pending"]})
    applied_payload = payload["applied"]
    if not isinstance(applied_payload, list) or len(applied_payload) > len(APPROVED_MIGRATIONS):
        raise _reject()
    applied: list[str] = []
    for item in applied_payload:
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "sha256"}
            or not isinstance(item["name"], str)
            or not isinstance(item["sha256"], str)
            or APPROVED_MIGRATIONS.get(item["name"]) != item["sha256"]
        ):
            raise _reject()
        applied.append(item["name"])
    if set(pending) & set(applied) or len(set(applied)) != len(applied):
        raise _reject()
    # Account tables may only follow the already-reviewed Task 012 migration.
    if "core.0012_auth_verification" in pending and "formula_editor.0002_fixedindicatorstate" not in applied:
        raise _reject()
    if "core.0013_chartworkspace" in pending and "core.0012_auth_verification" not in applied:
        raise _reject()
    if "core.0013_chartworkspace" in applied and "core.0012_auth_verification" not in applied:
        raise _reject()
    if "core.0014_accountmembership_expires_at" in pending + applied and "core.0013_chartworkspace" not in applied:
        raise _reject()
    return {"pending": pending, "applied": applied}


def _connect_readonly(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).resolve(strict=True)
    return sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)


def _integrity(path: str | Path) -> None:
    try:
        with closing(_connect_readonly(path)) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise ValueError("SQLite integrity check failed")
    except (OSError, sqlite3.Error) as error:
        raise ValueError("SQLite integrity check failed") from error


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _rows_equal(before: sqlite3.Connection, after: sqlite3.Connection, table: str) -> bool:
    before_columns = [row[1] for row in before.execute(f"PRAGMA table_info({_quote_identifier(table)})")]
    after_columns = [row[1] for row in after.execute(f"PRAGMA table_info({_quote_identifier(table)})")]
    if not before_columns or before_columns != after_columns:
        return False
    projection = ", ".join(_quote_identifier(column) for column in before_columns)
    query = f"SELECT {projection} FROM {_quote_identifier(table)} ORDER BY {projection}"
    left = before.execute(query)
    right = after.execute(query)
    while True:
        left_rows = left.fetchmany(256)
        right_rows = right.fetchmany(256)
        if left_rows != right_rows:
            return False
        if not left_rows:
            return True


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _schema_rows(connection: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return list(
        connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "ORDER BY type, name, tbl_name, sql"
        )
    )


def compare_database_contents(before_path: str | Path, after_path: str | Path) -> None:
    """Refuse to replace a live DB that changed after its final backup."""
    try:
        with closing(_connect_readonly(before_path)) as before, closing(
            _connect_readonly(after_path)
        ) as after:
            tables = _table_names(before)
            if tables != _table_names(after) or _schema_rows(before) != _schema_rows(after):
                raise ValueError("database changed after final backup")
            for table in sorted(tables):
                if not _rows_equal(before, after, table):
                    raise ValueError("database changed after final backup")
    except ValueError:
        raise
    except (OSError, sqlite3.Error) as error:
        raise ValueError("database snapshot comparison failed") from error


def _validate_task012_permission_metadata(
    before: sqlite3.Connection, after: sqlite3.Connection
) -> tuple[int, list[int]]:
    required_tables = {"django_content_type", "auth_permission"}
    if not required_tables.issubset(_table_names(before)) or not required_tables.issubset(
        _table_names(after)
    ):
        raise ValueError("Django permission metadata tables are unavailable")
    for table in required_tables:
        if not _rows_equal_schema(before, after, table):
            raise ValueError("Django permission metadata schema changed")

    content_type_columns = [
        row[1] for row in before.execute('PRAGMA table_info("django_content_type")')
    ]
    permission_columns = [
        row[1] for row in before.execute('PRAGMA table_info("auth_permission")')
    ]
    if set(content_type_columns) != {"id", "app_label", "model"} or set(
        permission_columns
    ) != {"id", "name", "content_type_id", "codename"}:
        raise ValueError("Django permission metadata schema is unexpected")

    before_content_types = Counter(before.execute('SELECT * FROM "django_content_type"'))
    after_content_types = Counter(after.execute('SELECT * FROM "django_content_type"'))
    removed_content_types = list((before_content_types - after_content_types).elements())
    added_content_types = list((after_content_types - before_content_types).elements())
    if removed_content_types or len(added_content_types) != 1:
        raise ValueError("Task 012 content type metadata change is unexpected")
    content_type = added_content_types[0]
    content_type_indexes = {
        name: content_type_columns.index(name) for name in ("id", "app_label", "model")
    }
    if (
        content_type[content_type_indexes["app_label"]] != "formula_editor"
        or content_type[content_type_indexes["model"]] != "fixedindicatorstate"
    ):
        raise ValueError("Task 012 content type metadata is unexpected")
    content_type_id = content_type[content_type_indexes["id"]]
    if not isinstance(content_type_id, int) or content_type_id <= 0:
        raise ValueError("Task 012 content type identifier is invalid")

    before_permissions = Counter(before.execute('SELECT * FROM "auth_permission"'))
    after_permissions = Counter(after.execute('SELECT * FROM "auth_permission"'))
    removed_permissions = list((before_permissions - after_permissions).elements())
    added_permissions = list((after_permissions - before_permissions).elements())
    expected_permissions = {
        "add_fixedindicatorstate": "Can add 固定公式（服务器已安装）",
        "change_fixedindicatorstate": "Can change 固定公式（服务器已安装）",
        "delete_fixedindicatorstate": "Can delete 固定公式（服务器已安装）",
        "view_fixedindicatorstate": "Can view 固定公式（服务器已安装）",
    }
    if removed_permissions or len(added_permissions) != len(expected_permissions):
        raise ValueError("Task 012 permission metadata change is unexpected")
    permission_indexes = {
        name: permission_columns.index(name)
        for name in ("id", "name", "content_type_id", "codename")
    }
    seen_codenames: set[str] = set()
    permission_ids: list[int] = []
    for permission in added_permissions:
        codename = permission[permission_indexes["codename"]]
        if (
            codename not in expected_permissions
            or codename in seen_codenames
            or permission[permission_indexes["name"]] != expected_permissions[codename]
            or permission[permission_indexes["content_type_id"]] != content_type_id
        ):
            raise ValueError("Task 012 permission metadata is unexpected")
        permission_id = permission[permission_indexes["id"]]
        if not isinstance(permission_id, int) or permission_id <= 0:
            raise ValueError("Task 012 permission identifier is invalid")
        seen_codenames.add(codename)
        permission_ids.append(permission_id)
    if seen_codenames != set(expected_permissions):
        raise ValueError("Task 012 permission metadata is incomplete")
    return content_type_id, permission_ids


def validate_approved_migration_result(before_path: str | Path, after_path: str | Path) -> None:
    """Allow only reviewed Task 012 or account schema and metadata additions."""
    with closing(_connect_readonly(before_path)) as baseline, closing(_connect_readonly(after_path)) as candidate:
        added = _table_names(candidate) - _table_names(baseline)
    if added == {"core_authratelimit", "core_pendingemailregistration"}:
        return _validate_core_0012_result(before_path, after_path)
    if added == {"core_chartworkspace"}:
        return _validate_core_0013_result(before_path, after_path)
    if not added:
        return _validate_core_0014_result(before_path, after_path)
    migration_name = "0002_fixedindicatorstate"
    new_table = "formula_editor_fixedindicatorstate"
    try:
        with closing(_connect_readonly(before_path)) as before, closing(
            _connect_readonly(after_path)
        ) as after:
            before_tables = _table_names(before)
            after_tables = _table_names(after)
            if after_tables - before_tables != {new_table} or before_tables - after_tables:
                raise ValueError("unexpected database migration table change")
            new_columns = [
                (row[1], row[2].lower(), row[3], row[4], row[5], row[6])
                for row in after.execute(f'PRAGMA table_xinfo("{new_table}")')
            ]
            if new_columns != [
                ("code", "varchar(32)", 1, None, 1, 0),
                ("enabled", "bool", 1, None, 0, 0),
            ]:
                raise ValueError("new Task 012 state table schema is unexpected")
            table_sql_row = after.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (new_table,),
            ).fetchone()
            if (
                table_sql_row is None
                or not isinstance(table_sql_row[0], str)
                or _normalize_sql(table_sql_row[0])
                != _normalize_sql(APPROVED_TASK012_TABLE_SQL)
            ):
                raise ValueError("new Task 012 state table schema is unexpected")
            state_indexes = list(after.execute(f'PRAGMA index_list("{new_table}")'))
            if len(state_indexes) != 1 or state_indexes[0][2] != 1 or state_indexes[0][3] != "pk":
                raise ValueError("new Task 012 state table indexes are unexpected")
            attached_objects = list(
                after.execute(
                    "SELECT type FROM sqlite_master "
                    "WHERE tbl_name=? AND type NOT IN ('table', 'index')",
                    (new_table,),
                )
            )
            if attached_objects:
                raise ValueError("unexpected schema object attached to Task 012 state table")
            indexed_columns = [
                row[2]
                for row in after.execute(
                    f'PRAGMA index_info("{state_indexes[0][1]}")'
                )
            ]
            if indexed_columns != ["code"]:
                raise ValueError("new Task 012 state table primary key is unexpected")

            before_schema = [row for row in _schema_rows(before) if row[2] != new_table]
            after_schema = [row for row in _schema_rows(after) if row[2] != new_table]
            if before_schema != after_schema:
                raise ValueError("unexpected database migration schema change")

            content_type_id, permission_ids = _validate_task012_permission_metadata(
                before, after
            )
            for table in sorted(
                before_tables
                - {
                    "auth_permission",
                    "django_content_type",
                    "django_migrations",
                    "sqlite_sequence",
                }
            ):
                if not _rows_equal(before, after, table):
                    raise ValueError("unexpected database migration data change")

            if "django_migrations" not in before_tables or not _rows_equal_schema(
                before, after, "django_migrations"
            ):
                raise ValueError("Django migration history table changed unexpectedly")
            migration_columns = [
                row[1] for row in before.execute('PRAGMA table_info("django_migrations")')
            ]
            column_indexes = {name: migration_columns.index(name) for name in ("id", "app", "name", "applied")}
            before_rows = list(before.execute('SELECT * FROM "django_migrations"'))
            after_rows = list(after.execute('SELECT * FROM "django_migrations"'))
            before_counts = Counter(before_rows)
            after_counts = Counter(after_rows)
            added_rows = list((after_counts - before_counts).elements())
            if len(added_rows) != 1:
                raise ValueError("Django migration history row count is unexpected")
            added = added_rows[0]
            if (
                added[column_indexes["app"]] != "formula_editor"
                or added[column_indexes["name"]] != migration_name
                or not added[column_indexes["applied"]]
                or sum(before_counts.values()) + 1 != sum(after_counts.values())
            ):
                raise ValueError("Django migration history does not match the reviewed migration")

            state_count = after.execute(f'SELECT COUNT(*) FROM "{new_table}"').fetchone()[0]
            if state_count != 0:
                raise ValueError("new Task 012 state table is unexpectedly populated")

            if "sqlite_sequence" in before_tables or "sqlite_sequence" in after_tables:
                if "sqlite_sequence" not in before_tables or "sqlite_sequence" not in after_tables:
                    raise ValueError("SQLite sequence metadata changed unexpectedly")
                sequence_columns = [
                    row[1] for row in before.execute('PRAGMA table_info("sqlite_sequence")')
                ]
                name_index = sequence_columns.index("name")
                seq_index = sequence_columns.index("seq")
                before_sequences = list(before.execute('SELECT * FROM "sqlite_sequence"'))
                after_sequences = list(after.execute('SELECT * FROM "sqlite_sequence"'))
                before_by_name = {row[name_index]: row[seq_index] for row in before_sequences}
                after_by_name = {row[name_index]: row[seq_index] for row in after_sequences}
                sequence_minimums = {
                    "django_migrations": added[column_indexes["id"]],
                    "django_content_type": content_type_id,
                    "auth_permission": max(permission_ids),
                }
                expected_names = set(before_by_name) | set(sequence_minimums)
                if set(after_by_name) != expected_names:
                    raise ValueError("SQLite sequence metadata changed unexpectedly")
                for name, value in before_by_name.items():
                    if name in sequence_minimums:
                        if after_by_name.get(name) != sequence_minimums[name] or sequence_minimums[name] < value:
                            raise ValueError("SQLite sequence metadata changed unexpectedly")
                    elif after_by_name.get(name) != value:
                        raise ValueError("SQLite sequence metadata changed unexpectedly")
                for name, minimum in sequence_minimums.items():
                    if after_by_name.get(name) != minimum:
                        raise ValueError("SQLite sequence metadata is invalid")
    except ValueError:
        raise
    except (OSError, sqlite3.Error, IndexError, KeyError) as error:
        raise ValueError("approved migration result validation failed") from error



# Exact reviewed SQL created by core.0012_auth_verification on SQLite.
ACCOUNT_SCHEMA = {
    "core_pendingemailregistration": (
        'CREATE TABLE "core_pendingemailregistration" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, '
        '"email" varchar(150) NOT NULL UNIQUE, "display_name" varchar(150) NOT NULL, '
        '"password_hash" varchar(128) NOT NULL, "code_hash" varchar(128) NOT NULL, '
        '"expires_at" datetime NOT NULL, "sent_at" datetime NOT NULL, '
        '"failed_attempts" smallint unsigned NOT NULL CHECK ("failed_attempts" >= 0))'
    ),
    "core_authratelimit": (
        'CREATE TABLE "core_authratelimit" ("key" varchar(64) NOT NULL PRIMARY KEY, '
        '"count" integer unsigned NOT NULL CHECK ("count" >= 0), '
        '"window_ends_at" datetime NOT NULL)'
    ),
}


def _validate_core_0012_result(before_path: str | Path, after_path: str | Path) -> None:
    """Fail closed if account migration alters anything beyond its two empty tables and Django metadata."""
    with closing(_connect_readonly(before_path)) as before, closing(_connect_readonly(after_path)) as after:
        new_tables = set(ACCOUNT_SCHEMA)
        old_tables = _table_names(before)
        if _table_names(after) - old_tables != new_tables or old_tables - _table_names(after):
            raise ValueError("unapproved account migration tables")
        for table, sql in ACCOUNT_SCHEMA.items():
            actual = after.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not actual or _normalize_sql(actual[0]) != _normalize_sql(sql):
                raise ValueError("unapproved account table schema")
            if after.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]:
                raise ValueError("account table is not initially empty")
            objects = list(after.execute(
                "SELECT type FROM sqlite_master WHERE tbl_name=? AND type NOT IN ('table', 'index')",
                (table,),
            ))
            if objects:
                raise ValueError("unapproved schema object attached to account table")
            indexes = list(after.execute(f'PRAGMA index_list("{table}")'))
            if len(indexes) != 1 or indexes[0][2] != 1 or indexes[0][3] not in ("u", "pk"):
                raise ValueError("unapproved account index")
            indexed = [r[2] for r in after.execute(f'PRAGMA index_info("{indexes[0][1]}")')]
            if indexed != (["email"] if table == "core_pendingemailregistration" else ["key"]):
                raise ValueError("unapproved account index columns")
        if [row for row in _schema_rows(before) if row[2] not in new_tables] != [
            row for row in _schema_rows(after) if row[2] not in new_tables
        ]:
            raise ValueError("account migration changed existing schema")
        meta_tables = {"django_content_type", "auth_permission", "django_migrations", "sqlite_sequence"}
        if not meta_tables.issubset(old_tables):
            raise ValueError("Django metadata missing")
        for table in meta_tables - {"sqlite_sequence"}:
            if not _rows_equal_schema(before, after, table):
                raise ValueError("Django metadata schema changed")
        for table in old_tables - meta_tables:
            if not _rows_equal(before, after, table):
                raise ValueError("account migration modified pre-existing data")

        ct_columns = [r[1] for r in before.execute('PRAGMA table_info("django_content_type")')]
        ct_idx = {k: ct_columns.index(k) for k in ("id", "app_label", "model")}
        old_ct, new_ct = (
            Counter(db.execute("SELECT * FROM django_content_type")) for db in (before, after)
        )
        added_ct = list((new_ct - old_ct).elements())
        if old_ct - new_ct or len(added_ct) != 2 or {
            (r[ct_idx["app_label"]], r[ct_idx["model"]]) for r in added_ct
        } != {("core", "pendingemailregistration"), ("core", "authratelimit")}:
            raise ValueError("unapproved Django content types")
        ct_ids = {r[ct_idx["model"]]: r[ct_idx["id"]] for r in added_ct}
        if any(not isinstance(n, int) or n <= 0 for n in ct_ids.values()):
            raise ValueError("invalid content type IDs")

        perm_columns = [r[1] for r in before.execute('PRAGMA table_info("auth_permission")')]
        perm_idx = {k: perm_columns.index(k) for k in ("id", "name", "content_type_id", "codename")}
        old_perm, new_perm = (
            Counter(db.execute("SELECT * FROM auth_permission")) for db in (before, after)
        )
        added_perm = list((new_perm - old_perm).elements())
        expected = {
            (ct_ids[model], f"{action}_{model}", f"Can {action} {friendly}")
            for model, friendly in (
                ("pendingemailregistration", "pending email registration"),
                ("authratelimit", "auth rate limit"),
            )
            for action in ("add", "change", "delete", "view")
        }
        if old_perm - new_perm or len(added_perm) != 8 or {
            (r[perm_idx["content_type_id"]], r[perm_idx["codename"]], r[perm_idx["name"]])
            for r in added_perm
        } != expected:
            raise ValueError("unapproved Django permission changes")
        permission_ids = [r[perm_idx["id"]] for r in added_perm]
        if any(not isinstance(n, int) or n <= 0 for n in permission_ids):
            raise ValueError("invalid permission IDs")

        history_columns = [r[1] for r in before.execute('PRAGMA table_info("django_migrations")')]
        h_idx = {k: history_columns.index(k) for k in ("id", "app", "name", "applied")}
        old_history, new_history = (
            Counter(db.execute("SELECT * FROM django_migrations")) for db in (before, after)
        )
        added_history = list((new_history - old_history).elements())
        if old_history - new_history or len(added_history) != 1:
            raise ValueError("unapproved migration history changes")
        history = added_history[0]
        if (history[h_idx["app"]], history[h_idx["name"]]) != ("core", "0012_auth_verification") or not history[h_idx["applied"]]:
            raise ValueError("unapproved migration history entry")

        old_seq = dict(before.execute("SELECT name,seq FROM sqlite_sequence"))
        new_seq = dict(after.execute("SELECT name,seq FROM sqlite_sequence"))
        expected_seq = {
            "django_migrations": history[h_idx["id"]],
            "django_content_type": max(ct_ids.values()),
            "auth_permission": max(permission_ids),
        }
        if set(new_seq) != set(old_seq) | set(expected_seq):
            raise ValueError("unapproved SQLite sequence changes")
        for name in set(old_seq) | set(expected_seq):
            if name in expected_seq:
                if new_seq[name] != expected_seq[name] or expected_seq[name] < old_seq.get(name, 0):
                    raise ValueError("invalid SQLite metadata sequence")
            elif new_seq[name] != old_seq[name]:
                raise ValueError("existing SQLite sequence changed")



# Exact reviewed Django/SQLite schema of the single Task 005.2 table.
WORKSPACE_TABLE_SQL = (
    'CREATE TABLE "core_chartworkspace" '
    '("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, '
    '"main" text NOT NULL CHECK ((JSON_VALID("main") OR "main" IS NULL)), '
    '"sub" text NOT NULL CHECK ((JSON_VALID("sub") OR "sub" IS NULL)), '
    '"pane_heights" text NOT NULL CHECK ((JSON_VALID("pane_heights") OR "pane_heights" IS NULL)), '
    '"updated_at" datetime NOT NULL, '
    '"user_id" integer NOT NULL UNIQUE REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED)'
)


def _validate_core_0013_result(before_path: str | Path, after_path: str | Path) -> None:
    """Only the empty workspace table, its Django metadata and migration history may be added."""
    new_table = "core_chartworkspace"
    with closing(_connect_readonly(before_path)) as before, closing(_connect_readonly(after_path)) as after:
        before_tables = _table_names(before)
        after_tables = _table_names(after)
        if after_tables - before_tables != {new_table} or before_tables - after_tables:
            raise ValueError("unapproved workspace migration tables")
        row = after.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (new_table,)).fetchone()
        if row is None or _normalize_sql(row[0]) != _normalize_sql(WORKSPACE_TABLE_SQL):
            raise ValueError("unapproved workspace table schema")
        fields = [(r[1], r[2].lower(), r[3], r[4], r[5], r[6]) for r in after.execute(
            'PRAGMA table_xinfo("core_chartworkspace")'
        )]
        if fields != [
            ("id", "integer", 1, None, 1, 0),
            ("main", "text", 1, None, 0, 0),
            ("sub", "text", 1, None, 0, 0),
            ("pane_heights", "text", 1, None, 0, 0),
            ("updated_at", "datetime", 1, None, 0, 0),
            ("user_id", "integer", 1, None, 0, 0),
        ]:
            raise ValueError("unapproved workspace table columns")
        indexes = list(after.execute('PRAGMA index_list("core_chartworkspace")'))
        if len(indexes) != 1 or indexes[0][2:4] != (1, "u") or [
            r[2] for r in after.execute(f'PRAGMA index_info("{indexes[0][1]}")')
        ] != ["user_id"]:
            raise ValueError("unapproved workspace unique index")
        if list(after.execute('PRAGMA foreign_key_list("core_chartworkspace")')) != [
            (0, 0, "auth_user", "user_id", "id", "NO ACTION", "NO ACTION", "NONE")
        ]:
            raise ValueError("unapproved workspace foreign key")
        # The comparison excludes the new table; reject attached triggers and views.
        attached = list(after.execute(
            "SELECT type FROM sqlite_master WHERE tbl_name=? AND type NOT IN ('table', 'index')",
            (new_table,),
        ))
        if attached:
            raise ValueError("unapproved workspace schema object")
        if after.execute('SELECT COUNT(*) FROM "core_chartworkspace"').fetchone()[0] != 0:
            raise ValueError("workspace table is not initially empty")
        if [r for r in _schema_rows(before) if r[2] != new_table] != [
            r for r in _schema_rows(after) if r[2] != new_table
        ]:
            raise ValueError("workspace migration changed existing schema")
        if not {"django_content_type", "auth_permission", "django_migrations", "sqlite_sequence"} <= before_tables:
            raise ValueError("workspace Django metadata missing")
        for table in ("django_content_type", "auth_permission", "django_migrations"):
            if not _rows_equal_schema(before, after, table):
                raise ValueError("workspace Django metadata schema changed")
        for table in before_tables - {
            "django_content_type", "auth_permission", "django_migrations", "sqlite_sequence"
        }:
            if not _rows_equal(before, after, table):
                raise ValueError("workspace migration modified existing data")

        ct_columns = [r[1] for r in before.execute('PRAGMA table_info("django_content_type")')]
        ct_idx = {k: ct_columns.index(k) for k in ("id", "app_label", "model")}
        old_ct, new_ct = (Counter(db.execute("SELECT * FROM django_content_type")) for db in (before, after))
        added_ct = list((new_ct - old_ct).elements())
        if old_ct - new_ct or len(added_ct) != 1 or (
            added_ct[0][ct_idx["app_label"]], added_ct[0][ct_idx["model"]]
        ) != ("core", "chartworkspace"):
            raise ValueError("unapproved workspace content type")
        ct_id = added_ct[0][ct_idx["id"]]
        if type(ct_id) is not int or ct_id < 1:
            raise ValueError("invalid workspace content type ID")

        perm_columns = [r[1] for r in before.execute('PRAGMA table_info("auth_permission")')]
        perm_idx = {k: perm_columns.index(k) for k in ("id", "name", "content_type_id", "codename")}
        old_perm, new_perm = (Counter(db.execute("SELECT * FROM auth_permission")) for db in (before, after))
        added_perm = list((new_perm - old_perm).elements())
        expected = {
            (ct_id, f"{action}_chartworkspace", f"Can {action} 图表工作区")
            for action in ("add", "change", "delete", "view")
        }
        if old_perm - new_perm or len(added_perm) != 4 or {
            (r[perm_idx["content_type_id"]], r[perm_idx["codename"]], r[perm_idx["name"]])
            for r in added_perm
        } != expected:
            raise ValueError("unapproved workspace permissions")

        history_columns = [r[1] for r in before.execute('PRAGMA table_info("django_migrations")')]
        h_idx = {k: history_columns.index(k) for k in ("id", "app", "name", "applied")}
        old_hist, new_hist = (Counter(db.execute("SELECT * FROM django_migrations")) for db in (before, after))
        added_history = list((new_hist - old_hist).elements())
        if old_hist - new_hist or len(added_history) != 1 or (
            added_history[0][h_idx["app"]], added_history[0][h_idx["name"]]
        ) != ("core", "0013_chartworkspace") or not added_history[0][h_idx["applied"]]:
            raise ValueError("unapproved workspace migration history")

        old_seq = dict(before.execute("SELECT name,seq FROM sqlite_sequence"))
        new_seq = dict(after.execute("SELECT name,seq FROM sqlite_sequence"))
        expected_seq = {
            "django_migrations": added_history[0][h_idx["id"]],
            "django_content_type": ct_id,
            "auth_permission": max(r[perm_idx["id"]] for r in added_perm),
        }
        if set(new_seq) != set(old_seq) | set(expected_seq):
            raise ValueError("unapproved workspace sequence changes")
        for name in set(old_seq) | set(expected_seq):
            if name in expected_seq:
                if new_seq[name] != expected_seq[name] or new_seq[name] < old_seq.get(name, 0):
                    raise ValueError("unapproved workspace metadata sequence")
            elif new_seq[name] != old_seq[name]:
                raise ValueError("existing SQLite sequence changed")



def _member_legacy_rows_unchanged(before: sqlite3.Connection, after: sqlite3.Connection) -> bool:
    """Preserve every existing membership column; all new expirations must be NULL."""
    old_cols = [r[1] for r in before.execute('PRAGMA table_info("core_accountmembership")')]
    new_cols = [r[1] for r in after.execute('PRAGMA table_info("core_accountmembership")')]
    if not old_cols or new_cols != old_cols + ["expires_at"]:
        return False
    if after.execute('SELECT COUNT(*) FROM "core_accountmembership" WHERE "expires_at" IS NOT NULL').fetchone()[0]:
        return False
    columns = ", ".join(_quote_identifier(c) for c in old_cols)
    sql = f'SELECT {columns} FROM "core_accountmembership" ORDER BY {columns}'
    lhs, rhs = before.execute(sql), after.execute(sql)
    while True:
        x, y = lhs.fetchmany(256), rhs.fetchmany(256)
        if x != y:
            return False
        if not x:
            return True


def _validate_core_0014_result(before_path: str | Path, after_path: str | Path) -> None:
    """Permit only the exact reviewed nullable column and Django migration marker."""
    table = "core_accountmembership"
    with closing(_connect_readonly(before_path)) as before, closing(_connect_readonly(after_path)) as after:
        tables = _table_names(before)
        if tables != _table_names(after) or table not in tables:
            raise ValueError("unapproved membership schema change")
        old_schema, new_schema = _schema_rows(before), _schema_rows(after)
        old_sql = next((r[3] for r in old_schema if r[0] == "table" and r[1] == table), None)
        new_sql = next((r[3] for r in new_schema if r[0] == "table" and r[1] == table), None)
        if not old_sql or not old_sql.rstrip().endswith(")") or not new_sql:
            raise ValueError("invalid membership table SQL")
        expected_sql = old_sql.rstrip()[:-1] + ', "expires_at" datetime NULL)'
        if _normalize_sql(new_sql) != _normalize_sql(expected_sql):
            raise ValueError("unapproved membership column SQL")
        def without_membership_table(rows):
            return [r for r in rows if not (r[0] == "table" and r[1] == table)]
        if without_membership_table(old_schema) != without_membership_table(new_schema):
            raise ValueError("migration changed unrelated schema")
        original = list(before.execute('PRAGMA table_info("core_accountmembership")'))
        actual = list(after.execute('PRAGMA table_info("core_accountmembership")'))
        if actual[:-1] != original or not actual or tuple(actual[-1][1:6]) != ("expires_at", "datetime", 0, None, 0):
            raise ValueError("unapproved membership field specification")
        if not _member_legacy_rows_unchanged(before, after):
            raise ValueError("existing membership records changed")
        for other in tables - {table, "django_migrations", "sqlite_sequence"}:
            if not _rows_equal(before, after, other):
                raise ValueError("migration changed existing user/application data")
        old_history, new_history = (
            Counter(db.execute('SELECT * FROM "django_migrations"')) for db in (before, after)
        )
        added = list((new_history - old_history).elements())
        if old_history - new_history or len(added) != 1:
            raise ValueError("unapproved migration history change")
        cols = [r[1] for r in before.execute('PRAGMA table_info("django_migrations")')]
        indexes = {key: cols.index(key) for key in ("id", "app", "name", "applied")}
        marker = added[0]
        if (marker[indexes["app"]], marker[indexes["name"]]) != ("core", "0014_accountmembership_expires_at") or not marker[indexes["applied"]]:
            raise ValueError("unexpected migration record")
        old_seq = dict(before.execute('SELECT name,seq FROM sqlite_sequence'))
        new_seq = dict(after.execute('SELECT name,seq FROM sqlite_sequence'))
        if old_seq.keys() != new_seq.keys() or new_seq.get("django_migrations") != marker[indexes["id"]]:
            raise ValueError("unapproved migration sequence update")
        if any(new_seq[key] != value for key, value in old_seq.items() if key != "django_migrations"):
            raise ValueError("existing SQLite sequence changed")


def _rows_equal_schema(before: sqlite3.Connection, after: sqlite3.Connection, table: str) -> bool:
    before_columns = list(before.execute(f"PRAGMA table_info({_quote_identifier(table)})"))
    after_columns = list(after.execute(f"PRAGMA table_info({_quote_identifier(table)})"))
    return before_columns == after_columns


def compare_protected_tables(before_path: str | Path, after_path: str | Path) -> None:
    """Compare protected tables exactly without disclosing their contents."""
    try:
        with closing(_connect_readonly(before_path)) as before, closing(
            _connect_readonly(after_path)
        ) as after:
            before_names = {
                row[0]
                for row in before.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            after_names = {
                row[0]
                for row in after.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            for table in PROTECTED_TABLES:
                if table not in before_names or table not in after_names:
                    raise ValueError(f"protected table missing: {table}")
                if table == "core_accountmembership" and [
                    r[1] for r in after.execute('PRAGMA table_info("core_accountmembership")')
                ] == [
                    r[1] for r in before.execute('PRAGMA table_info("core_accountmembership")')
                ] + ["expires_at"]:
                    unchanged = _member_legacy_rows_unchanged(before, after)
                else:
                    unchanged = _rows_equal(before, after, table)
                if not unchanged:
                    raise ValueError(f"protected table changed: {table}")
    except ValueError:
        raise
    except (OSError, sqlite3.Error) as error:
        raise ValueError("protected database comparison failed") from error


def copy_database(source_path: str | Path, destination_path: str | Path) -> None:
    destination = Path(destination_path)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size != 0:
        raise ValueError("database copy destination already exists")
    source = None
    target = None
    try:
        source = _connect_readonly(source_path)
        target = sqlite3.connect(destination)
        source.backup(target)
        target.close()
        target = None
        source.close()
        source = None
        os.chmod(destination, 0o600)
        _integrity(destination)
    except (OSError, sqlite3.Error, ValueError) as error:
        destination.unlink(missing_ok=True)
        if isinstance(error, ValueError):
            raise
        raise ValueError("SQLite database copy failed") from error
    finally:
        if target is not None:
            target.close()
        if source is not None:
            source.close()


def _atomic_install(source_path: str | Path, target_path: str | Path) -> None:
    source = Path(source_path).resolve(strict=True)
    target = Path(target_path).resolve(strict=True)
    if source == target:
        raise ValueError("database source and target must differ")
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{target}{suffix}")
        if sidecar.exists():
            raise ValueError("SQLite database sidecar exists; refusing atomic replacement")

    original_mode = stat.S_IMODE(target.stat().st_mode)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.web-admin-", suffix=".tmp", dir=target.parent
    )
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    replaced = False
    try:
        copy_database(source, temporary)
        os.chmod(temporary, original_mode)
        with temporary.open("r+b") as database_file:
            os.fsync(database_file.fileno())
        os.replace(temporary, target)
        replaced = True
        if os.name == "posix":
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except Exception as error:
        raise AtomicInstallFailure(replaced) from error
    finally:
        temporary.unlink(missing_ok=True)


def promote_migrated_database(
    before_path: str | Path, migrated_path: str | Path, target_path: str | Path
) -> None:
    _integrity(before_path)
    _integrity(migrated_path)
    compare_database_contents(before_path, target_path)
    validate_approved_migration_result(before_path, migrated_path)
    try:
        _atomic_install(migrated_path, target_path)
    except AtomicInstallFailure as error:
        if not error.replaced:
            raise
        try:
            restore_database(before_path, target_path)
            compare_database_contents(before_path, target_path)
        except Exception as restore_error:
            raise PromotionRecoveryFailure(
                "migration verification failed and the original database could not be restored"
            ) from restore_error
        raise PromotionReverted(
            "migration verification failed; the original database was restored"
        ) from error
    try:
        _integrity(target_path)
        validate_approved_migration_result(before_path, target_path)
    except Exception as error:
        try:
            restore_database(before_path, target_path)
            compare_database_contents(before_path, target_path)
        except Exception as restore_error:
            raise PromotionRecoveryFailure(
                "migration verification failed and the original database could not be restored"
            ) from restore_error
        raise PromotionReverted(
            "migration verification failed; the original database was restored"
        ) from error


def restore_database(backup_path: str | Path, target_path: str | Path) -> None:
    _integrity(backup_path)
    _atomic_install(backup_path, target_path)
    _integrity(target_path)


def _main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "command",
        choices=(
            "validate-plan",
            "validate-state",
            "validate-result",
            "check-integrity",
            "compare",
            "copy",
            "promote",
            "restore",
        ),
    )
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    try:
        if args.command == "validate-plan":
            if args.paths:
                raise ValueError("invalid migration validator arguments")
            plan = validate_plan(json.load(sys.stdin))
            print(json.dumps(plan, separators=(",", ":")))
        elif args.command == "validate-state":
            if args.paths:
                raise ValueError("invalid migration validator arguments")
            state = validate_probe_state(json.load(sys.stdin))
            print(json.dumps(state, separators=(",", ":")))
        elif args.command == "validate-result" and len(args.paths) == 2:
            validate_approved_migration_result(*args.paths)
            print("migration result: ok")
        elif args.command == "check-integrity" and len(args.paths) == 1:
            _integrity(args.paths[0])
            print("integrity_check: ok")
        elif args.command == "compare" and len(args.paths) == 2:
            compare_protected_tables(*args.paths)
            print("protected tables: unchanged")
        elif args.command == "copy" and len(args.paths) == 2:
            copy_database(*args.paths)
            print("database copy: ok")
        elif args.command == "promote" and len(args.paths) == 3:
            promote_migrated_database(*args.paths)
            print("database promotion: ok")
        elif args.command == "restore" and len(args.paths) == 2:
            restore_database(*args.paths)
            print("database restore: ok")
        else:
            raise ValueError("invalid migration validator arguments")
    except PromotionRecoveryFailure:
        print("siftalpha-web-admin: database migration failed; recovery requires operator review", file=sys.stderr)
        return 3
    except PromotionReverted:
        print("siftalpha-web-admin: database migration failed; the original database was restored", file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error, ValueError, json.JSONDecodeError):
        print("siftalpha-web-admin: database migration guard failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
