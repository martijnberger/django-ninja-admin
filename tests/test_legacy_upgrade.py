import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from django.db import connection

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def upgrade_database(tmp_path, transactional_db):
    if connection.vendor == "postgresql":
        schema = f"admin_upgrade_{uuid4().hex}"
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA {connection.ops.quote_name(schema)}")
        database = {**connection.settings_dict, "OPTIONS": {"options": f"-csearch_path={schema}"}}
        try:
            yield database
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP SCHEMA {connection.ops.quote_name(schema)} CASCADE")
    else:
        yield {"ENGINE": "django.db.backends.sqlite3", "NAME": str(tmp_path / "legacy.sqlite3")}


def run_phase(phase, database):
    result = subprocess.run(
        [sys.executable, "-m", "tests.legacy_upgrade_runner", phase],
        cwd=ROOT,
        env={**os.environ, "ADMIN_UPGRADE_TEST_DATABASE": json.dumps(database)},
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


@pytest.mark.parametrize("seed_phase", ["seed", "seed_initial"])
def test_upgrade_preserves_audit_history_content_type_ids_and_permission_assignments(upgrade_database, seed_phase):
    before = json.loads(run_phase(seed_phase, upgrade_database).splitlines()[-1])
    assert "Dry run only" in run_phase("preview", upgrade_database)
    after = json.loads(run_phase("upgrade", upgrade_database).splitlines()[-1])
    assert before == after


@pytest.mark.parametrize("phase", ["collision", "rollback", "both_tables"])
def test_unsafe_or_failed_upgrade_preserves_original_database_state(upgrade_database, phase):
    run_phase("seed", upgrade_database)
    run_phase(phase, upgrade_database)
