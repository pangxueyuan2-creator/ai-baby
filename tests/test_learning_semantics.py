"""Regression cases for explicit assertions, correction and stable confirmations."""

import pytest

from ai_baby.baby import Baby
from ai_baby.learning import Learner
from ai_baby.main import command
from ai_baby.memory import MemoryStore


@pytest.mark.parametrize(
    "text",
    [
        "我喜欢橘猫对不对",
        "我喜欢橘猫还是草莓",
        "我现在住杭州是不是",
        "如果有一天，我喜欢橘猫",
        "他说，我喜欢橘猫",
        "例如，我喜欢橘猫",
        "我喜欢橘猫只是一个假设",
        "我喜欢橘猫但不确定",
        "我喜欢橘猫不喜欢狗",
    ],
)
def test_questions_and_scoped_hypotheticals_create_no_facts(baby, text):
    baby.chat(text)
    assert not baby.memory.facts()
    assert baby.memory.db.execute("SELECT count(*) FROM candidates").fetchone()[0] == 0


@pytest.mark.parametrize(
    "correction",
    [
        "我以前喜欢橘猫，现在不喜欢了",
        "我喜欢橘猫，但是现在不喜欢了",
        "我现在不喜欢橘猫了",
        "我不再喜欢橘猫了",
    ],
)
def test_explicit_preference_correction_never_saves_qualifier_as_object(baby, correction):
    baby.chat("我喜欢橘猫")
    baby.chat(correction)
    assert not baby.memory.facts("likes")
    assert [f.value for f in baby.memory.facts("dislikes")] == ["橘猫"]


def test_separate_first_person_clauses_are_distinct_facts(baby):
    baby.chat("我喜欢橘猫，我现在住杭州，我的朋友叫小明")
    assert {(f.kind, f.value) for f in baby.memory.facts()} == {
        ("preference", "橘猫"),
        ("personal", "杭州"),
        ("relation", "小明"),
    }


def test_supported_natural_aliases_remain_explicit_and_bounded(baby):
    baby.chat("我家在杭州。")
    baby.chat("I like cats.")
    baby.chat("小明是我同学。")

    facts = {(f.kind, f.predicate, f.value) for f in baby.memory.facts()}
    assert ("personal", "居住地", "杭州") in facts
    assert ("preference", "likes", "cats") in facts
    assert ("relation", "同学", "小明") in facts


def test_natural_relation_aliases_are_multi_value(baby):
    baby.chat("小明是我的朋友。")
    baby.chat("我的朋友叫小红。")

    assert {(f.predicate, f.value) for f in baby.memory.facts() if f.kind == "relation"} == {
        ("朋友", "小明"),
        ("朋友", "小红"),
    }


def test_english_question_is_not_learned(baby):
    baby.chat("Do I like cats?")
    assert not baby.memory.facts()


def test_unsupported_temporal_preference_does_not_invent_current_fact(baby):
    baby.chat("我以前喜欢橘猫")
    assert not baby.memory.facts()


def test_previous_residence_clause_does_not_hide_explicit_current_residence(baby):
    baby.chat("我以前住北京，现在住杭州")
    assert [(f.predicate, f.value) for f in baby.memory.facts()] == [("居住地", "杭州")]


def test_only_recognized_complete_clauses_are_learned(baby):
    baby.chat("我喜欢橘猫，因为它们很可爱")
    assert [f.value for f in baby.memory.facts()] == ["橘猫"]
    baby.chat("我喜欢草莓但以前不喜欢")
    assert all("但以前" not in f.value for f in baby.memory.facts())


def test_negated_teaching_never_invents_a_positive_subject(baby):
    baby.chat("学习：海豚不是鱼")
    assert not any(f.subject == "海豚不" for f in baby.memory.facts())
    # Explicit prose can remain verbatim knowledge; it is not converted to a false triple.
    assert any(f.kind == "knowledge" and f.value == "海豚不是鱼" for f in baby.memory.facts())


def test_explicit_event_about_a_question_is_still_an_event(baby):
    baby.chat("重要事件：今天爸爸第一次教我什么叫星星")
    assert any(f.kind == "event" and "星星" in f.value for f in baby.memory.facts())


def test_particle_uncertainty_is_a_candidate_without_the_particle(baby):
    baby.chat("我喜欢橘猫吧")
    assert not baby.memory.facts()
    row = baby.memory.db.execute("SELECT value FROM candidates").fetchone()
    assert row[0] == "橘猫"


def test_candidate_ids_are_not_reused_after_delete_and_restart(baby):
    baby.chat("我可能喜欢橘猫")
    old_id = baby.memory.db.execute("SELECT id FROM candidates").fetchone()[0]
    command(baby, f"/reject {old_id}")
    second = MemoryStore(baby.memory.path)
    try:
        other = Baby(second)
        other.chat("我可能喜欢草莓")
        new_id = second.db.execute("SELECT id FROM candidates").fetchone()[0]
        assert new_id > old_id
        other.chat(f"确认记忆 {old_id}")
        assert not second.facts()
        other.chat(f"确认记忆 {new_id}")
        assert [f.value for f in second.facts()] == ["草莓"]
    finally:
        second.close()


def test_explicit_preference_correction_retires_conflicting_candidate(baby):
    baby.chat("我可能喜欢橘猫")
    old_id = baby.memory.db.execute("SELECT id FROM candidates").fetchone()[0]
    baby.chat("我不喜欢橘猫")
    baby.chat(f"确认记忆 {old_id}")
    assert not baby.memory.facts("likes")
    assert [f.value for f in baby.memory.facts("dislikes")] == ["橘猫"]


def test_candidate_sequence_upgrades_existing_rows_without_reusing_id(store):
    store.db.execute(
        "INSERT INTO candidates(id,kind,subject,predicate,value) "
        "VALUES(80,'preference','用户','likes','梨')"
    )
    result = Learner(store).process("我可能喜欢苹果")
    assert result.pending[0]["id"] > 80


def test_one_turn_never_requests_confirmation_of_an_evicted_candidate(store):
    result = Learner(store).process("我可能喜欢橘猫。我可能喜欢草莓。我可能喜欢梨。我可能喜欢苹果")
    current_ids = {row[0] for row in store.db.execute("SELECT id FROM candidates")}
    assert len(current_ids) == 3
    assert {candidate["id"] for candidate in result.pending} == current_ids


def test_explicit_correction_in_same_turn_cancels_confirmation_prompt(baby):
    response = baby.chat("我可能喜欢橘猫。我不喜欢橘猫")
    assert "/confirm" not in response.text
    assert not baby.memory.facts("likes")
    assert [fact.value for fact in baby.memory.facts("dislikes")] == ["橘猫"]
