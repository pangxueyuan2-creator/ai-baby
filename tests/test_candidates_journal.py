import json

import pytest

from ai_baby.baby import Baby
from ai_baby.main import command
from ai_baby.memory import MemoryStore
from ai_baby.models import Growth, PersonalityState, Relationship


@pytest.mark.parametrize(
    "text,kind,value",
    [
        ("其实我从小特别喜欢橘猫。", "preference", "橘猫"),
        ("我从小就特别喜欢橘猫。", "preference", "橘猫"),
        ("其实草莓是我最喜欢的水果。", "preference", "草莓"),
        ("我现在住杭州。", "personal", "杭州"),
        ("我的朋友叫小明。", "relation", "小明"),
        ("我也喜欢下雨天。", "preference", "下雨天"),
        ("我还喜欢看书。", "preference", "看书"),
        ("我超喜欢火锅。", "preference", "火锅"),
    ],
)
def test_explicit_natural_statements(baby, text, kind, value):
    baby.chat(text)
    assert any(f.kind == kind and f.value == value for f in baby.memory.facts())


@pytest.mark.parametrize(
    "text",
    [
        "如果我喜欢橘猫就好了",
        "我喜欢橘猫吗",
        "小明说他住杭州",
        "我不确定住哪里",
        "今天去医院了",
        "我现在住院了",
        "我喜欢的不是橘猫",
        "我现在住哪里",
        "“我喜欢橘猫”这是一句例句",
    ],
)
def test_no_inferred_sensitive_facts(baby, text):
    baby.chat(text)
    assert not baby.memory.facts()


def test_ambiguous_preference_requires_confirmation_and_survives_restart(baby):
    reply = baby.chat("我可能喜欢橘猫")
    assert "/confirm" in reply.text
    assert not baby.memory.facts()
    candidate_id = baby.memory.db.execute("SELECT id FROM candidates").fetchone()[0]
    path = baby.memory.path
    second = MemoryStore(path)
    try:
        other = Baby(second)
        command(other, f"/confirm {candidate_id}")
        assert second.facts("likes")[0].value == "橘猫"
        assert second.db.execute("SELECT count(*) FROM candidates").fetchone()[0] == 0
    finally:
        second.close()


def test_reject_and_candidate_limit(baby):
    for value in ("橘猫", "草莓", "苹果", "梨", "西瓜"):
        baby.chat(f"我可能喜欢{value}")
    assert baby.memory.db.execute("SELECT count(*) FROM candidates").fetchone()[0] == 3
    candidate_id = baby.memory.db.execute("SELECT max(id) FROM candidates").fetchone()[0]
    command(baby, f"/reject {candidate_id}")
    assert not baby.memory.facts()


def test_candidate_injection_cannot_change_authoritative_profile(baby):
    baby.memory.db.execute(
        "INSERT INTO candidates(kind,subject,predicate,value) VALUES('personal','用户','gender','male')"
    )
    with pytest.raises(ValueError):
        baby.chat("确认记忆 1")
    assert baby.memory.profile().gender == "female"


def test_journal_is_deterministic_idempotent_and_does_not_boost_growth(baby):
    baby.chat("学习：猫是哺乳动物。学习：狗是哺乳动物。我喜欢橘猫。")
    before = baby.memory.counts()
    command(baby, "/journal")
    row = baby.memory.db.execute("SELECT summary FROM journals").fetchone()
    assert "软件角色状态记录" in row[0] and "猫" in row[0] and "狗" in row[0]
    command(baby, "/journal")
    assert baby.memory.db.execute("SELECT count(*) FROM journals").fetchone()[0] == 1
    assert baby.memory.counts() == before


def test_automatic_journal_after_twenty_turns(baby):
    for i in range(20):
        baby.chat(f"学习：动物{i}是某种动物")
    assert baby.memory.db.execute("SELECT count(*) FROM journals").fetchone()[0] == 1


def test_journal_records_personality_without_new_events(baby):
    for _ in range(40):
        baby.chat("谢谢你，真棒")
    rows = baby.memory.db.execute("SELECT summary FROM journals ORDER BY id").fetchall()
    assert len(rows) == 2
    assert "本段没有新增重要经历" in rows[-1][0]
    assert "confidence" in rows[-1][0]


def test_journal_after_profile_change_in_same_turn_is_valid(baby):
    command(baby, "/journal")
    command(baby, "/name Alex")
    command(baby, "/journal")
    command(baby, "/journal")
    assert baby.memory.db.execute("SELECT count(*) FROM journals").fetchone()[0] == 2


def test_forget_export_and_baby_name_survive_restart(baby, tmp_path, capsys):
    baby.chat("我喜欢橘猫。谢谢你")
    baby.chat("我喜欢草莓")
    fact_id = next(f.id for f in baby.memory.facts() if f.value == "橘猫")
    command(baby, "/baby-name 星芽")
    command(baby, "/journal")
    command(baby, f"/forget {fact_id}")
    command(baby, "/export")
    exported = next((baby.memory.path.parent / "exports").glob("*.json"))
    payload = json.loads(exported.read_text(encoding="utf-8"))
    assert payload["baby_name"] == "星芽"
    assert payload["profile"]["name"] == "Alice"
    assert "personality" in payload and "growth_metrics" in payload
    assert "橘猫" not in exported.read_text(encoding="utf-8")
    assert "api_key" not in payload and "env" not in payload
    assert baby.memory.history() == []
    second = MemoryStore(baby.memory.path)
    try:
        other = Baby(second)
        assert "星芽" in other.chat("你是谁").text
        assert "橘猫" not in other.chat("我喜欢什么").text
        assert "草莓" in other.chat("我喜欢什么").text
        assert not second.retrieve_episodes("橘猫")
    finally:
        second.close()


def test_curiosity_sparse_no_penalty_and_no_repeat(baby):
    for _ in range(5):
        baby.chat("你好")
    response = baby.chat("我喜欢橘猫")
    assert "为什么你喜欢橘猫" in response.text
    trust = baby.memory.load_state("relationship", Relationship).trust
    baby.chat("不想回答，跳过问题")
    assert baby.memory.load_state("relationship", Relationship).trust >= trust
    for _ in range(10):
        assert "为什么你喜欢" not in baby.chat("我喜欢橘猫").text
    assert (
        baby.memory.db.execute("SELECT count(*) FROM curiosity WHERE status='pending'").fetchone()[
            0
        ]
        == 0
    )


def test_curiosity_answered_and_mature_question(baby):
    baby.chat("学习：鲸鱼是哺乳动物")
    baby.memory.save_state("growth", Growth(interactions=10, stage="mature"))
    baby.memory.save_state("personality", PersonalityState(curiosity=80))
    reply = baby.chat("学习：海豚是哺乳动物")
    assert "以前学过" in reply.text
    baby.chat("因为它们有共同特点")
    assert baby.memory.db.execute("SELECT status FROM curiosity").fetchone()[0] == "answered"
