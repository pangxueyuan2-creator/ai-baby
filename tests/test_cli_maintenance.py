"""Actual terminal subprocess flows with temporary fictional profiles only."""

import json
import sqlite3

import pytest
from test_config_cli import cli


def test_cli_complete_lifecycle_name_and_memory_controls(tmp_path):
    first = cli(
        tmp_path,
        "Alice\n2\n可以\n/baby-name 星星\n我喜欢橘猫\n学习：海豚是哺乳动物\n"
        "谢谢你，真棒\n哈哈，一起玩\n/personality\n/journal\n/quit\n",
    )
    assert first.returncode == 0, first.stderr
    assert "星星：" in first.stdout and "妈妈你好" in first.stdout
    path = tmp_path / "memory" / "baby.sqlite3"
    with sqlite3.connect(path) as db:
        fact_id = db.execute("SELECT id FROM facts WHERE value='橘猫'").fetchone()[0]
    second = cli(
        tmp_path,
        "我喜欢什么？\n/name Alex\n/address 家长\n/profile\n"
        f"/forget {fact_id}\n/export\n/backup\n/quit\n",
    )
    assert second.returncode == 0, second.stderr
    assert "星星：妈妈，你回来啦" in second.stdout
    assert "你喜欢橘猫" in second.stdout
    assert "记忆已失效" in second.stdout
    assert "备份完成" in second.stdout
    (exported,) = (path.parent / "exports").glob("*.json")
    payload = json.loads(exported.read_text(encoding="utf-8"))
    assert payload["baby_name"] == "星星"
    assert payload["profile"]["name"] == "Alex"
    assert payload["profile"]["address"] == "家长"
    assert "橘猫" not in exported.read_text(encoding="utf-8")
    third = cli(tmp_path, "我喜欢什么？\n/quit\n")
    assert third.returncode == 0
    assert "星星：家长，你回来啦" in third.stdout
    assert "橘猫" not in third.stdout
    assert "Traceback" not in first.stderr + second.stderr + third.stderr


@pytest.mark.parametrize("argument", ["", "private-input", "0", "-1", "9999999999999999999999"])
def test_invalid_memory_id_has_safe_actionable_error(tmp_path, argument):
    result = cli(tmp_path, f"Alice\n1\n\n/forget {argument}\n/quit\n")
    assert result.returncode == 0
    assert "正整数记忆 ID" in result.stdout
    assert "private-input" not in result.stdout
