"""End-to-end English profile/relation learning and routed memory questions."""

import pytest


@pytest.mark.parametrize(
    "statement,question,expected",
    [
        ("I live in Zhejiang.", "Where do I live?", "Zhejiang"),
        ("My birthday is June 1.", "When is my birthday?", "June 1"),
        ("I work as a programmer.", "What do I do for work?", "programmer"),
        ("My job is designer.", "What's my job?", "designer"),
    ],
)
def test_simple_english_profile_facts_can_be_learned_and_recalled(
    baby, statement, question, expected
):
    baby.chat(statement)

    reply = baby.chat(question).text

    assert expected in reply


@pytest.mark.parametrize(
    "statement,question,expected",
    [
        ("Alice is my friend.", "Who is my friend?", "Alice"),
        ("Bob is my classmate.", "Who are my classmates?", "Bob"),
        ("Dr Smith is my teacher.", "Who is my teacher?", "Dr Smith"),
        ("Casey is my coworker.", "Who are my coworkers?", "Casey"),
        ("Jordan is my colleague.", "Who are my colleagues?", "Jordan"),
        ("Mina is my family member.", "Who are my family members?", "Mina"),
    ],
)
def test_simple_english_relations_can_be_learned_and_recalled(baby, statement, question, expected):
    baby.chat(statement)

    reply = baby.chat(question).text

    assert expected in reply


def test_multiple_english_friends_remain_multi_value_relation_memory(baby):
    baby.chat("Alice is my friend.")
    baby.chat("Bob is my friend.")

    reply = baby.chat("Who are my friends?").text

    assert "Alice" in reply
    assert "Bob" in reply


def test_period_separated_english_profile_facts_are_learned_in_one_turn(baby):
    baby.chat("I live in Zhejiang. My birthday is June 1. My job is developer.")

    assert "Zhejiang" in baby.chat("Where do I live?").text
    assert "June 1" in baby.chat("When is my birthday?").text
    assert "developer" in baby.chat("What's my job?").text


def test_period_separated_english_relations_are_learned_in_one_turn(baby):
    baby.chat("Alice is my friend. Bob is my classmate.")

    assert "Alice" in baby.chat("Who are my friends?").text
    assert "Bob" in baby.chat("Who are my classmates?").text


def test_period_split_preserves_period_inside_relation_name(baby):
    baby.chat("Dr. Smith is my teacher. Alice is my friend.")

    assert "Dr. Smith" in baby.chat("Who is my teacher?").text
    assert "Alice" in baby.chat("Who are my friends?").text


@pytest.mark.parametrize(
    "statement,predicate,forbidden",
    [
        ("Maybe I live in Paris.", "居住地", "Paris"),
        ("I live in Paris, if my job moves.", "居住地", "Paris"),
        ("I live in Paris. if my job moves.", "居住地", "Paris"),
        ("My birthday is not June 1.", "生日", "June 1"),
        ("Bob said Alice is my friend.", "朋友", "Alice"),
        ("My job is designer because I changed teams.", "职业", "designer"),
    ],
)
def test_qualified_or_reported_english_facts_are_not_persisted(
    baby, statement, predicate, forbidden
):
    baby.chat(statement)

    values = [fact.value for fact in baby.memory.facts(predicate, limit=20)]

    assert forbidden not in values


def test_english_dislike_question_with_contraction_routes_to_saved_preferences(baby):
    baby.chat("I dislike broccoli.")

    reply = baby.chat("What don't I like?").text

    assert "broccoli" in reply
