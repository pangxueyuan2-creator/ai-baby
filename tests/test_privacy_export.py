import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from ai_baby.export import (
    EXIT_OK,
    FORMAT_NAME,
    FORMAT_VERSION,
    build_privacy_export,
    write_privacy_export,
)
from ai_baby.memory import MemoryError, MemoryStore
from ai_baby.models import Profile

ROOT = Path(__file__).resolve().parents[1]


def make_database(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "baby.sqlite3"
    memory = MemoryStore(path)
    try:
        with memory.transaction():
            memory.save_profile(Profile.create("Alice", "female", "Hangzhou"))
            memory.set_setting("baby_name", "Mochi")
            memory.learn("personal", "user", "lives_in", "Hangzhou")
            memory.learn("preference", "user", "likes", "cats")
            memory.learn("preference", "user", "dislikes", "cats")
            memory.episode("important", "learned how to make a privacy export")
            memory.message("user", "this transcript stays private by default")
            memory.message("assistant", "understood")
    finally:
        memory.close()
    return path


def test_default_export_is_read_only_and_omits_sensitive_history(tmp_path):
    path = make_database(tmp_path)
    before = path.read_bytes()

    payload = build_privacy_export(path)

    assert payload["format"] == FORMAT_NAME
    assert payload["format_version"] == FORMAT_VERSION
    assert payload["schema_version"] == 3
    assert payload["profile"] == {
        "name": "Alice",
        "gender": "female",
        "address": "Hangzhou",
        "created_at": payload["profile"]["created_at"],
    }
    assert payload["baby"]["name"] == "Mochi"
    assert "personality" in payload["baby"]["state"]
    assert "history" not in payload
    assert {fact["predicate"] for fact in payload["facts"]} == {"lives_in", "dislikes"}
    assert all(fact["active"] == 1 for fact in payload["facts"])
    assert len(payload["episodes"]) == 1
    assert "turn_receipts" in payload["omitted_internal_tables"]
    assert path.read_bytes() == before


def test_include_history_and_inactive_are_explicit_opt_ins(tmp_path):
    path = make_database(tmp_path)

    payload = build_privacy_export(path, include_history=True, include_inactive=True)

    assert [item["role"] for item in payload["history"]["messages"]] == ["user", "assistant"]
    assert (
        payload["history"]["messages"][0]["content"] == "this transcript stays private by default"
    )
    cat_facts = [fact for fact in payload["facts"] if fact["value"] == "cats"]
    assert len(cat_facts) == 2
    assert {fact["active"] for fact in cat_facts} == {0, 1}


def test_write_export_uses_private_exclusive_file_and_never_overwrites(tmp_path):
    path = make_database(tmp_path)
    output = tmp_path / "exports" / "baby.json"

    write_privacy_export(path, output, pretty=True)
    original = output.read_bytes()

    parsed = json.loads(output.read_text(encoding="utf-8"))
    assert parsed["format"] == FORMAT_NAME
    assert parsed["options"]["include_history"] is False
    if os.name != "nt":
        assert stat.S_IMODE(output.stat().st_mode) == 0o600

    with pytest.raises(ValueError, match="不会改写"):
        write_privacy_export(path, output)
    assert output.read_bytes() == original


def test_export_rejects_database_as_destination_without_modifying_it(tmp_path):
    path = make_database(tmp_path)
    before = path.read_bytes()

    with pytest.raises(ValueError, match="不能与 AI Baby 数据库相同"):
        write_privacy_export(path, path)

    assert path.read_bytes() == before


def test_export_rejects_corrupt_database_before_creating_output(tmp_path):
    path = tmp_path / "broken.sqlite3"
    output = tmp_path / "export.json"
    path.write_bytes(b"not sqlite")

    with pytest.raises(MemoryError):
        write_privacy_export(path, output)

    assert not output.exists()


def test_export_cli_ignores_unrelated_provider_configuration(tmp_path):
    path = make_database(tmp_path)
    output = tmp_path / "portable" / "baby.json"
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
            "ai_baby.export",
            "--database",
            str(path),
            "--output",
            str(output),
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
    assert status_payload["history_included"] is False
    export_payload = json.loads(output.read_text(encoding="utf-8"))
    assert "history" not in export_payload
