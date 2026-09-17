import os
import subprocess
import sys
from pathlib import Path

import pytest

from ai_baby.config import Config, read_env

ROOT = Path(__file__).resolve().parents[1]


def test_mock_is_default_even_with_key(monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.startswith("AI_BABY_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("AI_BABY_API_KEY", "fixture-key")
    config = Config.load(tmp_path, tmp_path / "absent.env")
    assert config.provider == "mock"
    assert "fixture-key" not in repr(config)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/v1",
        "https://user:pass@example.com/v1",
        "https://example.com/v1?key=x",
        "file:///tmp/api",
    ],
)
def test_unsafe_provider_url_rejected(tmp_path, url):
    with pytest.raises(ValueError):
        Config(
            tmp_path, "openai-compatible", "fixture-key", url, "fixture-model", 2, True
        ).validate()


def test_external_requires_opt_in_and_model(tmp_path):
    with pytest.raises(ValueError):
        Config(
            tmp_path, provider="openai-compatible", api_key="fixture-key", model="model"
        ).validate()
    with pytest.raises(ValueError):
        Config(
            tmp_path, provider="openai-compatible", api_key="fixture-key", allow_external=True
        ).validate()


def test_env_file_and_precedence(tmp_path, monkeypatch):
    path = tmp_path / "config.env"
    path.write_text('# comment\nAI_BABY_MODEL="file-model"\n', encoding="utf-8")
    assert read_env(path)["AI_BABY_MODEL"] == "file-model"
    monkeypatch.setenv("AI_BABY_MODEL", "env-model")
    monkeypatch.setenv("AI_BABY_PROVIDER", "mock")
    assert Config.load(tmp_path, path).model == "env-model"


def cli(tmp_path, text):
    env = {k: v for k, v in os.environ.items() if not k.startswith("AI_BABY_")}
    env.update(PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8", AI_BABY_PROVIDER="mock")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ai_baby",
            "--data-dir",
            str(tmp_path / "memory"),
            "--env-file",
            str(tmp_path / "absent.env"),
        ],
        input=text,
        encoding="utf-8",
        capture_output=True,
        env=env,
        timeout=20,
        cwd=tmp_path,
    )


def test_cli_birth_restart_and_all_acceptance_questions(tmp_path):
    first = cli(tmp_path, "Alice\n2\n可以\n我喜欢草莓。\n学习：海豚是一种哺乳动物。\n/quit\n")
    assert first.returncode == 0, first.stderr
    assert "妈妈你好" in first.stdout
    second = cli(tmp_path, "我叫什么名字？\n我喜欢什么？\n海豚是什么？\n/status\n/backup\n/quit\n")
    assert second.returncode == 0, second.stderr
    assert "妈妈，你回来啦" in second.stdout
    assert "Alice" in second.stdout
    assert "你喜欢草莓" in second.stdout
    assert "海豚是一种哺乳动物" in second.stdout
    assert "备份完成" in second.stdout
    assert "Traceback" not in second.stdout + second.stderr


def test_onboarding_eof_does_not_create_profile(tmp_path):
    from ai_baby.memory import MemoryStore

    assert cli(tmp_path, "Alice\n").returncode == 0
    memory = MemoryStore(tmp_path / "memory" / "baby.sqlite3")
    try:
        assert memory.profile() is None
    finally:
        memory.close()


def test_other_gender_and_declined_parent_address(tmp_path):
    result = cli(tmp_path, "Alex\n3\n\n/profile\n/quit\n")
    assert "Alex你好" in result.stdout
    assert '"address": "Alex"' in result.stdout
    different = tmp_path / "declined"
    different.mkdir()
    result = cli(different, "Alice\n2\n不可以\n/profile\n/quit\n")
    assert '"address": "Alice"' in result.stdout


def test_corrupt_store_cli_has_actionable_error(tmp_path):
    path = tmp_path / "memory"
    path.mkdir()
    (path / "baby.sqlite3").write_bytes(b"broken")
    result = cli(tmp_path, "")
    assert result.returncode == 1
    assert "保留原文件" in result.stdout
    assert "Traceback" not in result.stderr
