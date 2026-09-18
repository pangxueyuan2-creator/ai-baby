import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from ai_baby.backup import write_checksum_manifest
from ai_baby.memory import MemoryError, MemoryStore
from ai_baby.models import Profile
from ai_baby.restore import check_restore_backup, restore_backup

ROOT = Path(__file__).resolve().parents[1]


def make_backup(tmp_path: Path) -> Path:
    source = MemoryStore(tmp_path / "source" / "baby.sqlite3")
    try:
        with source.transaction():
            source.save_profile(Profile.create("Alice", "female", "妈妈"))
            source.set_setting("baby_name", "星星")
            source.learn("personal", "user", "lives_in", "Hangzhou")
        backup = tmp_path / "backup.sqlite3"
        source.backup(backup)
        return backup
    finally:
        source.close()


def test_restore_backup_round_trip_preserves_profile_settings_and_facts(tmp_path):
    backup = make_backup(tmp_path)
    target = restore_backup(backup, tmp_path / "restored")

    assert target == tmp_path / "restored" / "baby.sqlite3"
    restored = MemoryStore(target)
    try:
        assert restored.profile() == Profile.create("Alice", "female", "妈妈")
        assert restored.setting("baby_name") == "星星"
        assert [(fact.predicate, fact.value) for fact in restored.facts()] == [
            ("lives_in", "Hangzhou")
        ]
        assert restored.db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert restored.db.execute("PRAGMA foreign_key_check").fetchone() is None
    finally:
        restored.close()


def test_restore_refuses_to_overwrite_existing_baby(tmp_path):
    backup = make_backup(tmp_path)
    data_dir = tmp_path / "restored"
    target = restore_backup(backup, data_dir)
    before = target.read_bytes()

    with pytest.raises(ValueError, match="避免覆盖"):
        restore_backup(backup, data_dir)

    assert target.read_bytes() == before


def test_corrupt_backup_never_creates_destination(tmp_path):
    backup = tmp_path / "broken.sqlite3"
    backup.write_text("this is not sqlite", encoding="utf-8")
    data_dir = tmp_path / "restored"

    with pytest.raises(MemoryError, match="目标未修改"):
        restore_backup(backup, data_dir)

    assert not data_dir.exists()


def test_empty_sqlite_file_is_not_accepted_as_an_ai_baby_backup(tmp_path):
    backup = tmp_path / "empty.sqlite3"
    with sqlite3.connect(backup):
        pass
    data_dir = tmp_path / "restored"

    with pytest.raises(MemoryError, match="版本不受支持"):
        restore_backup(backup, data_dir)

    assert not data_dir.exists()


def test_unsupported_future_schema_never_creates_destination(tmp_path):
    backup = tmp_path / "future.sqlite3"
    with sqlite3.connect(backup) as db:
        db.execute("CREATE TABLE marker(value TEXT)")
        db.execute("PRAGMA user_version=999")
    data_dir = tmp_path / "restored"

    with pytest.raises(MemoryError, match="版本不受支持"):
        restore_backup(backup, data_dir)

    assert not data_dir.exists()


def test_restore_preflight_reports_current_schema_without_mutating_source(tmp_path):
    backup = make_backup(tmp_path)
    before = backup.read_bytes()

    report = check_restore_backup(backup)

    assert report["status"] == "ok"
    assert report["source_schema_version"] == 3
    assert report["target_schema_version"] == 3
    assert report["migration_required"] is False
    assert report["checksum"] is None
    assert backup.read_bytes() == before


def test_restore_preflight_proves_v2_can_migrate_without_touching_source(tmp_path):
    backup = tmp_path / "v2.sqlite3"
    with sqlite3.connect(backup) as db:
        db.executescript((ROOT / "tests/fixtures/v2.sql").read_text(encoding="utf-8"))
    before = backup.read_bytes()

    report = check_restore_backup(backup)

    assert report["source_schema_version"] == 2
    assert report["target_schema_version"] == 3
    assert report["migration_required"] is True
    assert backup.read_bytes() == before
    assert not (tmp_path / "backups").exists()
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_restore_can_require_verified_checksum_before_creating_target(tmp_path):
    backup = make_backup(tmp_path)
    data_dir = tmp_path / "restored"

    with pytest.raises(MemoryError, match="缺少 SHA-256"):
        restore_backup(backup, data_dir, require_checksum=True)
    assert not data_dir.exists()

    _, digest = write_checksum_manifest(backup)
    report = check_restore_backup(backup, require_checksum=True)
    assert report["checksum"] == digest
    assert report["checksum_manifest"] == str(backup.with_name(backup.name + ".sha256"))

    target = restore_backup(backup, data_dir, require_checksum=True)
    assert target.is_file()


def test_restore_check_cli_is_json_scriptable_and_ignores_provider_config(tmp_path):
    backup = make_backup(tmp_path)
    default_data_dir = tmp_path / "must-not-be-created"
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        PYTHONIOENCODING="utf-8",
        AI_BABY_DATA_DIR=str(default_data_dir),
        AI_BABY_PROVIDER="openai-compatible",
        AI_BABY_BASE_URL="http://unsafe.example.invalid/v1",
    )

    result = subprocess.run(
        [sys.executable, "-m", "ai_baby.restore", str(backup), "--check", "--json"],
        encoding="utf-8",
        capture_output=True,
        env=env,
        timeout=20,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "ok"
    assert report["source_schema_version"] == 3
    assert report["target_schema_version"] == 3
    assert not default_data_dir.exists()


def test_restore_cli_is_noninteractive_and_does_not_load_provider_config(tmp_path):
    backup = make_backup(tmp_path)
    data_dir = tmp_path / "cli-restored"
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        PYTHONIOENCODING="utf-8",
        AI_BABY_PROVIDER="openai-compatible",
        AI_BABY_BASE_URL="http://unsafe.example.invalid/v1",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ai_baby.restore",
            str(backup),
            "--data-dir",
            str(data_dir),
        ],
        encoding="utf-8",
        capture_output=True,
        env=env,
        timeout=20,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "恢复完成" in result.stdout
    assert (data_dir / "baby.sqlite3").exists()
