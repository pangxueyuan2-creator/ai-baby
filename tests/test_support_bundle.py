import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ai_baby.memory import MemoryStore
from ai_baby.support import EXIT_OK, build_support_bundle, write_support_bundle

ROOT = Path(__file__).resolve().parents[1]
SECRET = "private-memory-value-7c3d"


def make_database(tmp_path: Path) -> Path:
    path = tmp_path / "private-user-dir" / "baby.sqlite3"
    memory = MemoryStore(path)
    try:
        with memory.transaction():
            memory.learn("personal", "user", "lives_in", SECRET)
            memory.episode("important", f"secret episode {SECRET}")
            memory.message("user", f"secret chat {SECRET}")
    finally:
        memory.close()
    return path


def test_support_bundle_is_read_only_and_excludes_private_content_and_paths(tmp_path):
    database = make_database(tmp_path)
    before = database.read_bytes()

    payload = build_support_bundle(database)
    encoded = json.dumps(payload, ensure_ascii=False)

    assert payload["database"]["status"] == "ok"
    assert payload["database"]["counts"] == {
        "profile": 0,
        "active_facts": 1,
        "active_episodes": 1,
        "messages": 1,
    }
    assert payload["privacy"] == {
        "content_included": False,
        "paths_included": False,
        "provider_configuration_included": False,
    }
    assert SECRET not in encoded
    assert str(database) not in encoded
    assert "private-user-dir" not in encoded
    assert database.read_bytes() == before


def test_write_support_bundle_creates_private_checksum_sidecar(tmp_path):
    database = make_database(tmp_path)
    output = tmp_path / "support.json"

    payload = write_support_bundle(database, output)
    manifest = output.with_name(output.name + ".sha256")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()

    assert output.is_file()
    assert manifest.is_file()
    assert payload["artifact"]["sha256"] == digest
    assert manifest.read_text(encoding="ascii") == f"{digest}  {output.name}\n"
    if os.name == "posix":
        assert output.stat().st_mode & 0o777 == 0o600
        assert manifest.stat().st_mode & 0o777 == 0o600


def test_support_bundle_refuses_to_overwrite_existing_output(tmp_path):
    database = make_database(tmp_path)
    output = tmp_path / "support.json"
    output.write_text("keep me", encoding="utf-8")

    with pytest.raises(ValueError, match="已存在"):
        write_support_bundle(database, output)

    assert output.read_text(encoding="utf-8") == "keep me"


def test_support_bundle_keeps_existing_manifest_when_sidecar_conflicts(tmp_path):
    database = make_database(tmp_path)
    output = tmp_path / "support.json"
    manifest = output.with_name(output.name + ".sha256")
    manifest.write_text("existing manifest", encoding="ascii")

    with pytest.raises(ValueError, match="校验文件已存在"):
        write_support_bundle(database, output)

    assert not output.exists()
    assert manifest.read_text(encoding="ascii") == "existing manifest"


def test_support_bundle_can_report_corrupt_database_without_reading_content(tmp_path):
    database = tmp_path / "broken.sqlite3"
    database.write_bytes(b"not sqlite and not private content")
    before = database.read_bytes()

    payload = build_support_bundle(database, full=True)

    assert payload["database"]["status"] == "error"
    assert payload["database"]["code"] == "not_sqlite"
    assert payload["database"]["integrity_check"] == "integrity_check"
    assert database.read_bytes() == before


def test_support_cli_ignores_provider_configuration_and_emits_machine_readable_status(tmp_path):
    database = make_database(tmp_path)
    output = tmp_path / "bundle.json"
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        PYTHONIOENCODING="utf-8",
        AI_BABY_PROVIDER="openai-compatible",
        AI_BABY_API_KEY="must-not-appear",
        AI_BABY_BASE_URL="http://unsafe.example.invalid/v1",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ai_baby.support",
            "--database",
            str(database),
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
    status = json.loads(result.stdout)
    assert status["status"] == "ok"
    bundle_text = output.read_text(encoding="utf-8")
    assert SECRET not in bundle_text
    assert "must-not-appear" not in bundle_text
    assert "unsafe.example.invalid" not in bundle_text
