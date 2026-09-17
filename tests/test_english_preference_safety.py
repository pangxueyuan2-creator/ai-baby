"""English aliases must not turn unrelated negations or scoped claims into preferences."""

import pytest

from ai_baby.baby import Baby
from ai_baby.memory import MemoryStore


@pytest.mark.parametrize(
    "statement",
    ["I don't own a car.", "I do not know my birthday.", "I do not remember."],
)
def test_non_preference_negation_is_not_learned(baby, statement):
    baby.chat(statement)
    assert not baby.memory.facts()
    assert not baby.memory.db.execute("SELECT 1 FROM candidates").fetchone()


@pytest.mark.parametrize(
    "correction",
    ["I don't like cats.", "I do not like cats.", "I REALLY DON'T LIKE cats.", "I dislike cats."],
)
def test_explicit_english_dislike_retires_same_object_preference(baby, correction):
    baby.chat("I like cats.")
    baby.chat(correction)
    assert not baby.memory.facts("likes")
    assert [fact.value for fact in baby.memory.facts("dislikes")] == ["cats"]
    reopened = MemoryStore(baby.memory.path)
    try:
        assert not reopened.facts("likes")
        assert [fact.value for fact in reopened.facts("dislikes")] == ["cats"]
        Baby(reopened).chat("I like cats.")
        assert not reopened.facts("dislikes")
        assert [fact.value for fact in reopened.facts("likes")] == ["cats"]
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "statement",
    [
        "I like cats maybe.",
        "I like cats, but I am not sure.",
        "I like cats if they are quiet.",
        "If I like cats, I like dogs.",
        "I like cats, unless they scratch.",
        "Someone said I like cats, I like dogs.",
        "I like cats, perhaps.",
        "I like cats, I might like dogs.",
        "I like cats, I used to like dogs.",
        "For example, I like cats.",
        "I like cats, don't I.",
        "I like cats. I don't like dogs.",
        "I like cats not dogs.",
        "I like cats or dogs.",
    ],
)
def test_uncertain_conditional_or_reported_sentence_does_not_save_fragments(baby, statement):
    baby.chat(statement)
    assert not baby.memory.facts()
    assert not baby.memory.db.execute("SELECT 1 FROM candidates").fetchone()
    assert not baby.memory.db.execute("SELECT 1 FROM episodes WHERE kind='learning'").fetchone()


def test_guards_preserve_separate_explicit_teaching_and_current_preference(baby):
    baby.chat("我喜欢橘猫。I like dogs, but I am not sure.。学习：if 是英语中的条件词")
    facts = baby.memory.facts()
    assert [(fact.predicate, fact.value) for fact in facts if fact.kind == "preference"] == [
        ("likes", "橘猫")
    ]
    assert any(fact.kind == "world" and fact.subject == "if" for fact in facts)
    baby.chat("I really like cats.")
    assert {fact.value for fact in baby.memory.facts("likes")} == {"cats", "橘猫"}


def test_complete_english_clauses_and_word_boundaries_remain_supported(baby):
    baby.chat("I like gift wrapping, I really dislike dogs.")
    assert {(fact.predicate, fact.value) for fact in baby.memory.facts()} == {
        ("likes", "gift wrapping"),
        ("dislikes", "dogs"),
    }


@pytest.mark.parametrize("verb", ["LİKE", "lıke"])
def test_unicode_case_matching_cannot_reverse_an_affirmative_preference(baby, verb):
    baby.chat("I like cats.")
    baby.chat(f"I {verb} cats.")
    assert not baby.memory.facts("dislikes")
    assert [fact.value for fact in baby.memory.facts("likes")] == ["cats"]
