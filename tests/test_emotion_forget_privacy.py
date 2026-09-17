"""Legacy truncated emotion excerpts must not bypass explicit logical forgetting."""

import json
import sqlite3

import pytest
from test_forget_privacy import CaptureProvider

from ai_baby import journal, management
from ai_baby.baby import Baby
from ai_baby.memory import MemoryStore


@pytest.mark.parametrize(
    ("cue", "tone", "label"),
    [
        ("谢谢你", "gentle", "happy"),
        ("我很难过", "distress", "sad"),
        ("我恨你", "hostile", "annoyed"),
    ],
)
def test_new_emotion_episodes_record_state_without_raw_input(baby, cue, tone, label):
    baby.chat(cue + "。我住在PRIVATE-FIXTURE-" + "X" * 240)
    events = [event for event in baby.memory.episodes() if event["kind"] == "emotion"]
    assert len(events) == 1
    assert tone in events[0]["summary"] and label in events[0]["summary"]
    assert "PRIVATE-FIXTURE" not in events[0]["summary"]
    assert "用户说：" not in events[0]["summary"]


def seed_legacy_excerpt(baby):
    """Reproduce the shipped format using only a synthetic, longer-than-excerpt fact."""
    value = "PRIVATE-FIXTURE-" + "X" * 240
    text = "我住在" + value
    baby.chat(text, turn_id="legacy-private-turn")
    fact_id = baby.memory.facts()[0].id
    summary = "互动情境：gentle；模拟状态变为 happy。用户说：" + text[:180]
    assert value not in summary
    baby.memory.episode("emotion", summary)
    return fact_id


@pytest.mark.parametrize("superseded", [False, True])
def test_forget_truncated_legacy_excerpt_across_restart_and_recall(baby, tmp_path, superseded):
    fact_id = seed_legacy_excerpt(baby)
    if superseded:
        baby.chat("我住在测试新城市")
    baby.memory.episode("important", "一起认识星星", importance=0.9)
    baby.memory.episode("emotion", "互动情境：gentle；模拟状态变为 happy。")
    with baby.memory.transaction():
        journal.consolidate(baby.memory, force=True)
    assert "PRIVATE-FIXTURE" in json.dumps(journal.recent(baby.memory), ensure_ascii=False)

    assert management.forget(baby.memory, fact_id)
    assert not baby.memory.retrieve("PRIVATE-FIXTURE")
    assert not baby.memory.retrieve_episodes("PRIVATE-FIXTURE")
    assert not baby.memory.history()
    with pytest.raises(ValueError, match="撤销"):
        baby.chat("我住在PRIVATE-FIXTURE-" + "X" * 240, turn_id="legacy-private-turn")

    reopened = MemoryStore(baby.memory.path)
    try:
        with reopened.transaction():
            journal.consolidate(reopened, force=True)
        remaining = reopened.episodes(50)
        assert any(event["summary"] == "一起认识星星" for event in remaining)
        assert any(event["kind"] == "emotion" for event in remaining)
        assert "PRIVATE-FIXTURE" not in json.dumps(remaining, ensure_ascii=False)
        assert "PRIVATE-FIXTURE" not in json.dumps(journal.recent(reopened), ensure_ascii=False)
        target = tmp_path / "export.json"
        management.export_data(reopened, target)
        exported = target.read_text(encoding="utf-8")
        assert "PRIVATE-FIXTURE" not in exported
        if superseded:
            assert "测试新城市" in exported
        else:
            assert not reopened.facts()
        provider = CaptureProvider()
        Baby(reopened, provider).chat("我们经历过什么")
        assert "PRIVATE-FIXTURE" not in json.dumps(provider.messages, ensure_ascii=False)
        assert reopened.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        reopened.close()


def test_forget_conservatively_retires_unattributed_excerpts_only(baby):
    baby.chat("我喜欢草莓")
    fact_id = baby.memory.facts()[0].id
    baby.memory.episode("emotion", "互动情境：gentle；模拟状态变为 happy。用户说：别的话题")
    baby.memory.episode("important", "文本标记用户说：的含义", importance=0.9)
    assert management.forget(baby.memory, fact_id)
    remaining = baby.memory.episodes(50)
    assert all(event["kind"] != "emotion" for event in remaining)
    assert any(event["summary"] == "文本标记用户说：的含义" for event in remaining)


def test_unknown_forget_preserves_legacy_excerpt(baby):
    seed_legacy_excerpt(baby)
    before = list(baby.memory.db.iterdump())
    assert not management.forget(baby.memory, 2**63 - 1)
    assert list(baby.memory.db.iterdump()) == before


def test_failed_forget_rolls_back_legacy_cleanup_and_all_state(baby):
    fact_id = seed_legacy_excerpt(baby)
    with baby.memory.transaction():
        journal.consolidate(baby.memory, force=True)
    baby.memory.db.execute(
        "CREATE TEMP TRIGGER fail_forget BEFORE DELETE ON journals "
        "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
    )
    before = list(baby.memory.db.iterdump())
    with pytest.raises(sqlite3.IntegrityError, match="synthetic failure"):
        management.forget(baby.memory, fact_id)
    assert not baby.memory.db.in_transaction
    assert list(baby.memory.db.iterdump()) == before
