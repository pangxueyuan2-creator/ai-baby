import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from ai_baby import importer
from ai_baby.export import build_privacy_export, write_privacy_export
from ai_baby.importer import EXIT_INVALID, EXIT_OK, import_privacy_export, preflight_privacy_export
from ai_baby.memory import MemoryStore
from ai_baby.models import Profile, Relationship
from ai_baby.privacy_checksum import checksum_manifest_path

ROOT = Path(__file__).resolve().parents[1]


def make_export(tmp_path: Path, *, history: bool = False, inactive: bool = False) -> Path:
    database = tmp_path / "source" / "baby.sqlite3"
    memory = MemoryStore(database)
    try:
        with memory.transaction():
            memory.save_profile(Profile.create("Alice", "female", "Hangzhou"))
            memory.set_setting("baby_name", "Mochi")
            memory.save_state(
                "relationship",
                Relationship(
                    trust=42.0,
                    attachment=21.0,
                    familiarity=8.0,
                    closeness=18.0,
                    playfulness=24.0,
                ),
            )
            memory.learn("personal", "user", "lives_in", "Hangzhou")
            memory.learn("preference", "user", "likes", "cats")
            cat_id = memory.db.execute(
                "SELECT id FROM facts WHERE predicate='likes' AND value='cats' AND active=1"
            ).fetchone()[0]
            memory.episode("important", "we learned about portable memories", 0.9, cat_id)
            memory.message("user", "private transcript")
            memory.message("assistant", "private response")
            if inactive:
                memory.learn("preference", "user", "dislikes", "cats")
    finally:
        memory.close()

    output = tmp_path / "portable" / "baby.json"
    write_privacy_export(
        database,
        output,
        include_history=history,
        include_inactive=inactive,
        pretty=True,
    )
    return output


def visible_rows(payload: dict, key: str, fields: tuple[str, ...]) -> list[tuple]:
    return [tuple(item[field] for field in fields) for item in payload[key]]


def test_default_privacy_export_round_trips_into_new_database(tmp_path):
    source = make_export(tmp_path)
    source_before = source.read_bytes()
    target_dir = tmp_path / "imported"

    result = import_privacy_export(source, target_dir)

    assert result["status"] == "ok"
    assert result["profile_imported"] is True
    target = target_dir / "baby.sqlite3"
    assert target.is_file()
    assert source.read_bytes() == source_before
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    original = json.loads(source.read_text(encoding="utf-8"))
    imported = build_privacy_export(target)
    assert imported["profile"]["name"] == original["profile"]["name"]
    assert imported["profile"]["gender"] == original["profile"]["gender"]
    assert imported["profile"]["address"] == original["profile"]["address"]
    assert imported["baby"] == original["baby"]
    assert visible_rows(
        imported, "facts", ("kind", "subject", "predicate", "value", "active")
    ) == visible_rows(original, "facts", ("kind", "subject", "predicate", "value", "active"))
    assert visible_rows(
        imported, "episodes", ("kind", "summary", "importance", "active")
    ) == visible_rows(original, "episodes", ("kind", "summary", "importance", "active"))
    assert "history" not in imported


@pytest.mark.parametrize("history,inactive", [(True, False), (False, True)])
def test_import_rejects_opt_in_sensitive_or_inactive_exports_before_creating_database(
    tmp_path, history, inactive
):
    source = make_export(tmp_path, history=history, inactive=inactive)
    target_dir = tmp_path / "target"

    with pytest.raises(ValueError, match="默认隐私导出"):
        import_privacy_export(source, target_dir)

    assert not (target_dir / "baby.sqlite3").exists()


def test_import_never_overwrites_existing_baby(tmp_path):
    source = make_export(tmp_path)
    target = tmp_path / "existing" / "baby.sqlite3"
    memory = MemoryStore(target)
    memory.close()
    before = target.read_bytes()

    with pytest.raises(ValueError, match="已经包含 baby.sqlite3"):
        import_privacy_export(source, target.parent)

    assert target.read_bytes() == before


def test_import_race_never_deletes_a_destination_created_by_someone_else(tmp_path, monkeypatch):
    source = make_export(tmp_path)
    target = tmp_path / "raced" / "baby.sqlite3"
    sentinel = b"created by another process"

    def lose_reservation_race(path: Path) -> None:
        path.write_bytes(sentinel)
        raise FileExistsError(path)

    monkeypatch.setattr(importer, "reserve_private_file", lose_reservation_race)

    with pytest.raises(ValueError, match="已经包含 baby.sqlite3"):
        import_privacy_export(source, target.parent)

    assert target.read_bytes() == sentinel


def test_tampered_export_is_rejected_before_destination_creation(tmp_path):
    source = make_export(tmp_path)
    source.write_bytes(source.read_bytes() + b" \n")
    target_dir = tmp_path / "tampered-target"

    with pytest.raises(ValueError, match="SHA-256 校验失败"):
        import_privacy_export(source, target_dir)

    assert not target_dir.exists()


def test_old_export_without_checksum_is_compatible_unless_checksum_is_required(tmp_path):
    source = make_export(tmp_path)
    checksum_manifest_path(source).unlink()

    assert preflight_privacy_export(source)["status"] == "ok"
    with pytest.raises(ValueError, match="缺少 SHA-256 校验文件"):
        preflight_privacy_export(source, require_checksum=True)


def test_malformed_checksum_is_rejected_before_json_validation(tmp_path):
    source = make_export(tmp_path)
    checksum_manifest_path(source).write_text("not-a-checksum\n", encoding="ascii")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["episodes"][0]["fact_id"] = 999999
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="校验文件格式无效"):
        preflight_privacy_export(source)


def test_broken_episode_fact_reference_is_rejected_before_destination_creation(tmp_path):
    source = make_export(tmp_path)
    checksum_manifest_path(source).unlink()
    payload = json.loads(source.read_text(encoding="utf-8"))
    assert payload["episodes"][0]["fact_id"] is not None
    payload["episodes"][0]["fact_id"] = 999999
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    target_dir = tmp_path / "broken-target"

    with pytest.raises(ValueError, match="episode 引用了"):
        import_privacy_export(source, target_dir)

    assert not target_dir.exists()


def test_preflight_reports_portable_counts_and_rejects_broken_references(tmp_path):
    source = make_export(tmp_path)

    result = preflight_privacy_export(source)

    assert result == {
        "status": "ok",
        "mode": "check",
        "format": "ai-baby-privacy-export",
        "format_version": 1,
        "facts": 2,
        "episodes": 1,
        "profile_imported": True,
    }

    checksum_manifest_path(source).unlink()
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["episodes"][0]["fact_id"] = 999999
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="episode 引用了"):
        preflight_privacy_export(source)


def test_import_check_cli_is_read_only_and_ignores_provider_configuration(tmp_path):
    source = make_export(tmp_path)
    untouched_data_dir = tmp_path / "must-not-be-created"
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        PYTHONIOENCODING="utf-8",
        AI_BABY_DATA_DIR=str(untouched_data_dir),
        AI_BABY_PROVIDER="openai-compatible",
        AI_BABY_BASE_URL="http://unsafe.example.invalid/v1",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ai_baby.importer",
            str(source),
            "--check",
            "--require-checksum",
            "--json",
        ],
        encoding="utf-8",
        capture_output=True,
        env=env,
        timeout=20,
        cwd=tmp_path,
    )

    assert result.returncode == EXIT_OK, result.stderr
    status_payload = json.loads(result.stdout)
    assert status_payload["status"] == "ok"
    assert status_payload["mode"] == "check"
    assert status_payload["facts"] == 2
    assert status_payload["episodes"] == 1
    assert not untouched_data_dir.exists()


def test_import_check_cli_rejects_broken_reference_without_creating_default_data_dir(tmp_path):
    source = make_export(tmp_path)
    checksum_manifest_path(source).unlink()
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["episodes"][0]["fact_id"] = 999999
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    untouched_data_dir = tmp_path / "must-not-be-created"
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        PYTHONIOENCODING="utf-8",
        AI_BABY_DATA_DIR=str(untouched_data_dir),
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ai_baby.importer",
            str(source),
            "--check",
            "--json",
        ],
        encoding="utf-8",
        capture_output=True,
        env=env,
        timeout=20,
        cwd=tmp_path,
    )

    assert result.returncode == EXIT_INVALID, result.stderr
    status_payload = json.loads(result.stdout)
    assert status_payload["status"] == "error"
    assert "episode 引用了" in status_payload["message"]
    assert not untouched_data_dir.exists()


def test_import_cli_ignores_unrelated_provider_configuration(tmp_path):
    source = make_export(tmp_path)
    target_dir = tmp_path / "cli-import"
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
            "ai_baby.importer",
            str(source),
            "--data-dir",
            str(target_dir),
            "--require-checksum",
            "--json",
        ],
        encoding="utf-8",
        capture_output=True,
        env=env,
        timeout=20,
        cwd=tmp_path,
    )

    assert result.returncode == EXIT_OK, result.stderr
    status_payload = json.loads(result.stdout)
    assert status_payload["status"] == "ok"
    assert status_payload["facts"] == 2
    assert status_payload["episodes"] == 1
    imported = build_privacy_export(target_dir / "baby.sqlite3")
    assert imported["baby"]["name"] == "Mochi"
    assert imported["profile"]["name"] == "Alice"
