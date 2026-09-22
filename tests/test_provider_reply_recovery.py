"""Malformed model text and confirmation commands share safe, visible fallback."""

import pytest

from ai_baby.baby import Baby
from ai_baby.config import Config
from ai_baby.main import command, main
from ai_baby.memory import MemoryStore
from ai_baby.models import Growth
from ai_baby.providers.openai_compatible import OpenAICompatibleProvider


def local_config(baby, url):
    return Config(
        baby.memory.path.parent,
        provider="ollama",
        base_url=url,
        model="fixture-model",
    )


@pytest.mark.parametrize("invalid", ["\ud800", "\udfff"], ids=["high-surrogate", "low-surrogate"])
def test_invalid_unicode_reply_falls_back_and_commits_learning_once(baby, api_server, invalid):
    url, seen, response = api_server
    response["body"] = {"choices": [{"message": {"content": "private-fixture-" + invalid}}]}
    baby.provider = OpenAICompatibleProvider(local_config(baby, url))
    before_turns = baby.memory.load_state("growth", Growth).interactions

    reply = baby.chat("我喜欢草莓", turn_id="invalid-unicode-turn")

    assert reply.warning and "response" in reply.warning
    assert "private-fixture" not in reply.text + reply.warning
    assert invalid not in reply.text
    assert [fact.value for fact in baby.memory.facts("likes")] == ["草莓"]
    assert baby.memory.load_state("growth", Growth).interactions == before_turns + 1
    assert baby.memory.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
    assert (
        baby.memory.db.execute("SELECT count(*) FROM episodes WHERE kind='learning'").fetchone()[0]
        == 1
    )
    assert baby.chat("我喜欢草莓", turn_id="invalid-unicode-turn") == reply
    assert len(seen) == 1

    response["body"] = {"choices": [{"message": {"content": "中文回复恢复了，😀"}}]}
    recovered = baby.chat("你好", turn_id="recovered-turn")
    assert recovered.warning is None and recovered.text == "中文回复恢复了，😀"
    assert len(seen) == 2
    assert baby.memory.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    with_restored = MemoryStore(baby.memory.path)
    try:
        restored = Baby(with_restored)
        assert [fact.value for fact in with_restored.facts("likes")] == ["草莓"]
        assert restored.chat("我喜欢草莓", turn_id="invalid-unicode-turn") == reply
    finally:
        with_restored.close()


@pytest.mark.parametrize("answer", ["普通中文回复", "你好，😀🍼！", " café，𠮷 "])
def test_valid_unicode_reply_is_preserved(baby, api_server, answer):
    url, seen, response = api_server
    response["body"] = {"choices": [{"message": {"content": answer}}]}
    baby.provider = OpenAICompatibleProvider(local_config(baby, url))

    reply = baby.chat("你好")

    assert reply.text == answer.strip()
    assert reply.warning is None
    assert len(seen) == 1


def test_two_argument_confirmation_command_displays_fallback(baby, api_server, capsys):
    baby.chat("我可能喜欢草莓")
    candidate_id = baby.memory.db.execute("SELECT id FROM candidates").fetchone()[0]
    url, seen, response = api_server
    response["status"] = 503
    baby.provider = OpenAICompatibleProvider(local_config(baby, url))

    assert command(baby, f"/confirm {candidate_id}") is True

    assert "模型服务不可用（server）；本轮使用离线回复。" in capsys.readouterr().out
    assert len(seen) == 1
    assert [fact.value for fact in baby.memory.facts("likes")] == ["草莓"]


@pytest.mark.parametrize("confirmation", ["/confirm", "/确认"])
def test_cli_confirmation_and_chat_share_outage_and_recovery_notices(
    baby, api_server, capsys, monkeypatch, confirmation
):
    baby.chat("我可能喜欢草莓")
    candidate_id = baby.memory.db.execute("SELECT id FROM candidates").fetchone()[0]
    url, seen, response = api_server
    config = local_config(baby, url)
    monkeypatch.setattr(Config, "load", lambda *args, **kwargs: config)
    steps = iter(
        [
            (f"{confirmation} {candidate_id}", 503),
            ("你好", 503),
            (f"{confirmation} {candidate_id}", 503),
            (f"{confirmation} {candidate_id}", 200),
            ("你好", 200),
            ("/quit", 200),
        ]
    )
    displayed = []

    def enter(prompt):
        displayed.append(capsys.readouterr().out)
        text, status = next(steps)
        response["status"] = status
        return text

    monkeypatch.setattr("builtins.input", enter)

    assert main([]) == 0

    assert "模型服务不可用" in displayed[1]
    assert "模型服务不可用" not in displayed[2] + displayed[3]
    assert "模型服务已恢复" in displayed[4]
    assert "模型服务已恢复" not in displayed[5]
    assert len(seen) == 5
    assert [fact.value for fact in baby.memory.facts("likes")] == ["草莓"]
    assert baby.memory.db.execute("SELECT count(*) FROM candidates").fetchone()[0] == 0
    assert (
        baby.memory.db.execute("SELECT count(*) FROM episodes WHERE kind='learning'").fetchone()[0]
        == 1
    )
