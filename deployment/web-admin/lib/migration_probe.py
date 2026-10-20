#!/usr/bin/env python3
"""Emit only pending Django migration identities and source SHA-256 values."""

import hashlib
import importlib
import json
import os
from pathlib import Path
import sys


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quant_site.settings")
sys.path.insert(0, str(Path.cwd()))

import django

django.setup()

from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


executor = MigrationExecutor(connection)
targets = executor.loader.graph.leaf_nodes()
pending = executor.migration_plan(targets)
migrations = []
for migration, backwards in pending:
    # Migration labels are not always Python package names (e.g.
    # contenttypes lives under django.contrib.contenttypes).
    module = importlib.import_module(
        f"{apps.get_app_config(migration.app_label).name}.migrations.{migration.name}"
    )
    source_path = Path(module.__file__).resolve(strict=True)
    source_bytes = source_path.read_bytes().replace(b"\r\n", b"\n")
    migrations.append(
        {
            "name": f"{migration.app_label}.{migration.name}",
            "backwards": bool(backwards),
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
        }
    )

approved_applied = []
for approved_key in (
    ("formula_editor", "0002_fixedindicatorstate"),
    ("core", "0012_auth_verification"),
    ("core", "0013_chartworkspace"),
    ("core", "0014_accountmembership_expires_at"),
    ("core", "0015_marketdatasourcesetting"),
):
    if approved_key in executor.loader.applied_migrations:
        module = importlib.import_module(
            f"{apps.get_app_config(approved_key[0]).name}.migrations.{approved_key[1]}"
        )
        source_path = Path(module.__file__).resolve(strict=True)
        source_bytes = source_path.read_bytes().replace(b"\r\n", b"\n")
        approved_applied.append(
            {
                "name": f"{approved_key[0]}.{approved_key[1]}",
                "sha256": hashlib.sha256(source_bytes).hexdigest(),
            }
        )

print(
    json.dumps(
        {"pending": migrations, "applied": approved_applied}, separators=(",", ":")
    )
)
