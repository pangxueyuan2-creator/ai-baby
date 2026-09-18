"""Relation questions are not people; Unicode names are not grammar keywords."""

import pytest

from ai_baby.providers import BaseLLMProvider


class CaptureProvider(BaseLLMProvider):
    def generate(self, context):
        self.context = context
        return "已收到。"


def assert_no_learning(baby):
    assert not baby.memory.db.execute("SELECT 1 FROM facts").fetchone()
    assert not baby.memory.db.execute("SELECT 1 FROM candidates").fetchone()
    assert not baby.memory.db.execute("SELECT 1 FROM episodes WHERE kind='learning'").fetchone()


@pytest.mark.parametrize("question", ["Who", "WHAT", "Which person"])
@pytest.mark.parametrize(
    "relation", ["friend", "classmate", "teacher", "coworker", "colleague", "family member"]
)
def test_unpunctuated_relation_question_is_not_saved_or_used_as_evidence(baby, question, relation):
    provider = CaptureProvider()
    baby.provider = provider

    baby.chat(f"{question} is my {relation}")

    assert_no_learning(baby)
    assert provider.context.facts == []
    assert provider.context.learning.fact_ids == []
    assert provider.context.learning.pending == []
    assert not any(episode["kind"] == "learning" for episode in provider.context.episodes)


def test_unpunctuated_question_recalls_only_previously_saved_friend(baby):
    baby.chat("Alice is my friend.")

    reply = baby.chat("Who is my friend").text

    assert [fact.value for fact in baby.memory.facts("朋友")] == ["Alice"]
    assert "Alice" in reply
    assert "Who" not in reply


@pytest.mark.parametrize(
    "question", ["Who is my teacher", "What is my coworker", "Which person is my classmate"]
)
def test_period_split_keeps_assertion_without_learning_following_question(baby, question):
    baby.chat(f"Alice is my friend. {question}.")

    assert [(fact.predicate, fact.value) for fact in baby.memory.facts()] == [("朋友", "Alice")]
    learning_episodes = baby.memory.db.execute(
        "SELECT summary FROM episodes WHERE kind='learning'"
    ).fetchall()
    assert len(learning_episodes) == 1
    assert "Alice" in learning_episodes[0]["summary"]
    assert not baby.memory.db.execute("SELECT 1 FROM candidates").fetchone()


@pytest.mark.parametrize(
    "statement",
    [
        "Alice is my frİend.",
        "Alice is my frıend.",
        "Alice is my claſsmate.",
        "Alice is my coworKer.",
        "Alice is my famİly member.",
        "Alice iſ my friend.",
    ],
)
def test_non_ascii_relation_keywords_are_skipped_without_crashing(baby, statement):
    baby.chat(statement)
    assert_no_learning(baby)

    baby.chat("小明 is my friend.")
    assert [fact.value for fact in baby.memory.facts("朋友")] == ["小明"]


@pytest.mark.parametrize(
    "statement,name,predicate",
    [
        ("İpek Şahin IS MY FRIEND.", "İpek Şahin", "朋友"),
        ("小明 is my classmate.", "小明", "同学"),
        ("Zoë Is My FAMILY MEMBER.", "Zoë", "家人"),
        ("Whoopi is my colleague.", "Whoopi", "同事"),
    ],
)
def test_unicode_names_and_ascii_keyword_case_remain_supported(baby, statement, name, predicate):
    baby.chat(statement)

    assert [(fact.predicate, fact.value) for fact in baby.memory.facts()] == [(predicate, name)]
