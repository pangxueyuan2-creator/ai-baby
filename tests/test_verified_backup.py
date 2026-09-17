import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ai_baby.backup import (
    backup_database,
    checksum_manifest_path,
    verify_backup,
    write_checksum_manifest,
)
from ai_baby.memory import MemoryError, MemoryStore
from ai_baby.models import Profile
from ai_baby.restore import restore_backup

ROOT = Path(__file__).resolve().parents[1]


def make_database(tmp_path: Path) -> Path:
    database = tmp_path / "source" / "baby.sqlite3"
    memory = MemoryStore(database)
    try:
        with memory.transaction():
            memory.save_profile(Profile.create("Alice", "female", "妈妈"))
            memory.set_setting("baby_name", "星星")
            memory.learn("personal", "user", "lives_in", "Hangzhou")
    finally:
        memory.close()
    return database


def test_verified_backup_round_trip_and_source_is_unchanged(tmp_path):
    source = make_database(tmp_path)
    before = source.read_bytes()
    backup = tmp_path / "backups" / "baby.sqlite3"

    manifest, digest, report = backup_database(source, backup)

    assert source.read_bytes() == before
    assert manifest == checksum_manifest_path(backup)
    assert manifest.read_text(encoding="ascii") == f"{digest}  {backup.name}\n"
    assert report["status"] == "ok"
    verified = verify_backup(backup, require_checksum=True)
    assert verified["checksum"] == digest

    restored_path = restore_backup(backup, tmp_path / "restored")
    restored = MemoryStore(restored_path)
    try:
        assert restored.profile() == Profile.create("Alice", "female", "妈妈")
        assert restored.setting("baby_name") == "星星"
        assert [(fact.predicate, fact.value) for fact in restored.facts()] == [
            ("lives_in", "Hangzhou")
        ]
    finally:
        restored.close()


def test_restore_rejects_tampered_backup_before_creating_destination(tmp_path):
    source = make_database(tmp_path)
    backup = tmp_path / "backup.sqlite3"
    backup_database(source, backup)
    with backup.open("ab") as output:
        output.write(b"tampered")

    data_dir = tmp_path / "restored"
    with pytest.raises(MemoryError, match="SHA-256"):
        restore_backup(backup, data_dir)

    assert not (data_dir / "baby.sqlite3").exists()


def test_restore_rejects_malformed_checksum_manifest(tmp_path):
    source = make_database(tmp_path)
    memory = MemoryStore(source)
    try:
        backup = tmp_path / "legacy.sqlite3"
        memory.backup(backup)
    finally:
        memory.close()
    checksum_manifest_path(backup).write_text("not-a-checksum\n", encoding="ascii")

    with pytest.raises(MemoryError, match="格式无效"):
        restore_backup(backup, tmp_path / "restored")


def test_restore_keeps_compatibility_with_legacy_backup_without_manifest(tmp_path):
    source = make_database(tmp_path)
    memory = MemoryStore(source)
    try:
        backup = tmp_path / "legacy.sqlite3"
        memory.backup(backup)
    finally:
        memory.close()

    restored = restore_backup(backup, tmp_path / "restored")

    assert restored.is_file()
    assert not checksum_manifest_path(backup).exists()
    assert verify_backup(backup)["checksum"] is None
    with pytest.raises(MemoryError, match="缺少 SHA-256"):
        verify_backup(backup, require_checksum=True)


def test_manifest_creation_never_overwrites_existing_sidecar(tmp_path):
    source = make_database(tmp_path)
    manifest = checksum_manifest_path(source)
    manifest.write_text("keep-me", encoding="ascii")

    with pytest.raises(FileExistsError):
        write_checksum_manifest(source)

    assert manifest.read_text(encoding="ascii") == "keep-me"


def test_backup_cli_create_and_verify_do_not_load_provider_config(tmp_path):
    source = make_database(tmp_path)
    data_dir = source.parent
    backup = tmp_path / "cli-backup.sqlite3"
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        PYTHONIOENCODING="utf-8",
        AI_BABY_PROVIDER="openai-compatible",
        AI_BABY_BASE_URL="http://unsafe.example.invalid/v1",
    )

    create = subprocess.run(
        [
            sys.executable,
            "-m",
            "ai_baby.backup",
            "--data-dir",
            str(data_dir),
            "--output",
            str(backup),
            "--json",
        ],
        encoding="utf-8",
        capture_output=True,
        env=env,
        timeout=20,
        cwd=tmp_path,
    )

    assert create.returncode == 0, create.stderr
    payload = json.loads(create.stdout)
    assert payload["status"] == "ok"
    assert payload["backup"] == str(backup)
    assert checksum_manifest_path(backup).is_file()

    verify = subprocess.run(
        [
            sys.executable,
            "-m",
            "ai_baby.backup",
            "--verify",
            str(backup),
            "--require-checksum",
            "--json",
        ],
        encoding="utf-8",
        capture_output=True,
        env=env,
        timeout=20,
        cwd=tmp_path,
    )

    assert verify.returncode == 0, verify.stderr
    verified = json.loads(verify.stdout)
    assert verified["status"] == "ok"
    assert verified["checksum"] == payload["checksum"]


def test_backup_cli_reports_checksum_failure(tmp_path):
    source = make_database(tmp_path)
    backup = tmp_path / "backup.sqlite3"
    backup_database(source, backup)
    with backup.open("ab") as output:
        output.write(b"changed")
    env = os.environ.copy()
    env.update(PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "ai_baby.backup", "--verify", str(backup), "--json"],
        encoding="utf-8",
        capture_output=True,
        env=env,
        timeout=20,
        cwd=tmp_path,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert "SHA-256" in payload["message"]
