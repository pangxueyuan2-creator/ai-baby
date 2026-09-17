"""Regression coverage for sustained interaction, without network generation."""

import pytest

from ai_baby import journal
from ai_baby.models import Growth, PersonalityState, Relationship, record
from ai_baby.relationship import classify, update


@pytest.mark.parametrize(
    "text",
    [
        "不要说我恨你",
        "她对我说你去死",
        "你说我恨你吗？",
        "如果我恨你怎么办",
        "台词是‘我恨你’",
        "我不喜欢你",
        "我并不是喜欢你",
    ],
)
def test_negation_quotation_and_questions_do_not_create_affection_or_hostility(text):
    assert classify(text, Relationship()) == "neutral"


def test_reported_harsh_words_do_not_override_users_distress():
    assert classify("我很难过，因为她对我说你真恶心", Relationship()) == "distress"
    assert classify("我恨你，但我很难过", Relationship()) == "hostile"


def test_relationship_has_diminishing_returns_and_can_recover():
    state = Relationship()
    for _ in range(1000):
        next_state = update(state, "gentle")
        assert all(abs(record(next_state)[k] - v) <= 0.35 for k, v in record(state).items())
        state = next_state
    assert all(0 < value < 100 for value in record(state).values())
    assert 70 < state.trust < 98
    trusted = state.trust
    for _ in range(200):
        state = update(state, "hostile")
    assert 0 < state.trust < trusted
    hurt = state.trust
    for _ in range(200):
        state = update(state, "gentle")
    assert hurt < state.trust < 100


def test_journal_bounds_each_event_without_losing_personality(baby):
    memory = baby.memory
    with memory.transaction():
        for i in range(6):
            memory.episode("important", f"事件{i}：" + "很长的测试经历" * 90)
        memory.save_state("personality", PersonalityState(confidence=51))
        summary = journal.consolidate(memory, force=True)
    assert summary is not None and len(summary) <= 1200
    assert all(f"事件{i}" in summary for i in range(6))
    assert "confidence 提高 1.00" in summary


def test_empty_unchanged_journals_do_not_repeat(baby):
    memory = baby.memory
    for turn in (20, 40, 60, 80):
        with memory.transaction():
            memory.save_state("growth", Growth(interactions=turn))
            journal.consolidate(memory)
    rows = memory.db.execute("SELECT summary FROM journals").fetchall()
    assert len(rows) == 1  # Birth is real evidence; later intervals add no new evidence.
    assert memory.setting("journal_turn") == "80"


def test_mature_curiosity_does_not_invent_previous_lessons(baby):
    baby.memory.save_state("growth", Growth(interactions=10, stage="mature"))
    reply = baby.chat("学习：海豚是哺乳动物")
    assert "以前学过" not in reply.text
    assert "你的看法" in reply.text


def test_mature_curiosity_connects_only_to_available_previous_evidence(baby):
    baby.chat("学习：鲸鱼是哺乳动物")
    baby.memory.save_state("growth", Growth(interactions=10, stage="mature"))
    reply = baby.chat("学习：海豚是哺乳动物")
    assert "以前学过" in reply.text and "鲸鱼" in reply.text
