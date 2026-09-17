import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from ai_baby.doctor import (
    EXIT_OK,
    EXIT_UPGRADE_REQUIRED,
    diagnose_database,
)
from ai_baby.memory import MemoryStore

ROOT = Path(__file__).resolve().parents[1]


def make_current_database(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "baby.sqlite3"
    memory = MemoryStore(path)
    try:
        with memory.transaction():
            memory.learn("personal", "user", "lives_in", "Hangzhou")
            memory.episode("important", "learned a safe diagnostic command")
            memory.message("user", "hello")
    finally:
        memory.close()
    return path


def make_v2_database(tmp_path: Path) -> Path:
    path = tmp_path / "v2.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript((ROOT / "tests/fixtures/v2.sql").read_text(encoding="utf-8"))
    return path


def test_doctor_reports_current_database_health_without_writing(tmp_path):
    path = make_current_database(tmp_path)
    before = path.read_bytes()

    report = diagnose_database(path)

    assert report["status"] == "ok"
    assert report["code"] == "ok"
    assert report["schema_version"] == 3
    assert report["integrity_check"] == "quick_check"
    assert report["counts"] == {
        "profile": 0,
        "active_facts": 1,
        "active_episodes": 1,
        "messages": 1,
    }
    assert path.read_bytes() == before


def test_doctor_full_mode_uses_integrity_check_and_stays_read_only(tmp_path):
    path = make_current_database(tmp_path)
    before = path.read_bytes()

    report = diagnose_database(path, full=True)

    assert report["status"] == "ok"
    assert report["integrity_check"] == "integrity_check"
    assert path.read_bytes() == before


def test_doctor_reports_supported_old_schema_without_migrating(tmp_path):
    path = make_v2_database(tmp_path)
    before = path.read_bytes()

    report = diagnose_database(path)

    assert report["status"] == "upgrade_required"
    assert report["code"] == "upgrade_required"
    assert report["schema_version"] == 2
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert "revoked" not in {row[1] for row in db.execute("PRAGMA table_info(turn_receipts)")}


def test_doctor_rejects_corrupt_input_without_modifying_it(tmp_path):
    path = tmp_path / "broken.sqlite3"
    path.write_bytes(b"not a sqlite database")
    before = path.read_bytes()

    report = diagnose_database(path)

    assert report["status"] == "error"
    assert report["code"] == "not_sqlite"
    assert path.read_bytes() == before


def test_doctor_detects_missing_current_schema_trigger(tmp_path):
    path = make_current_database(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("DROP TRIGGER revision_profile_insert")
    before = path.read_bytes()

    report = diagnose_database(path)

    assert report["status"] == "error"
    assert report["code"] == "schema_invalid"
    assert path.read_bytes() == before


def test_doctor_missing_database_does_not_create_parent_directory(tmp_path):
    data_dir = tmp_path / "missing" / "nested"

    report = diagnose_database(data_dir / "baby.sqlite3")

    assert report["code"] == "missing"
    assert not data_dir.exists()


def test_doctor_cli_ignores_unrelated_provider_configuration(tmp_path):
    path = make_current_database(tmp_path)
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        PYTHONIOENCODING="utf-8",
        AI_BABY_DATA_DIR=str(path.parent),
        AI_BABY_PROVIDER="openai-compatible",
        AI_BABY_BASE_URL="http://unsafe.example.invalid/v1",
    )

    result = subprocess.run(
        [sys.executable, "-m", "ai_baby.doctor", "--json"],
        encoding="utf-8",
        capture_output=True,
        env=env,
        timeout=20,
        cwd=tmp_path,
    )

    assert result.returncode == EXIT_OK, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["database"] == str(path)


def test_doctor_cli_uses_distinct_exit_code_when_upgrade_is_required(tmp_path):
    path = make_v2_database(tmp_path)
    before = path.read_bytes()
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "ai_baby.doctor", "--database", str(path), "--json"],
        encoding="utf-8",
        capture_output=True,
        env=env,
        timeout=20,
        cwd=tmp_path,
    )

    assert result.returncode == EXIT_UPGRADE_REQUIRED, result.stderr
    assert json.loads(result.stdout)["status"] == "upgrade_required"
    assert path.read_bytes() == before
