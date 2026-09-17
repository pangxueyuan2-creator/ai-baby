"""Natural-language Q&A over already stored facts."""

import pytest

from ai_baby.models import Growth


@pytest.mark.parametrize(
    "question,expected",
    [
        ("我住在哪里？", "浙江"),
        ("我住哪儿？", "浙江"),
        ("我家在哪？", "浙江"),
        ("我的居住地是什么？", "浙江"),
        ("我的生日是哪天？", "六月一日"),
        ("我生日哪天？", "六月一日"),
        ("我什么时候生日？", "六月一日"),
        ("我做什么工作？", "程序员"),
        ("我是做什么工作的？", "程序员"),
        ("我的职业是什么？", "程序员"),
    ],
)
def test_natural_profile_questions_route_to_stored_predicates(baby, question, expected):
    baby.chat("我住在浙江。")
    baby.chat("我的生日是六月一日。")
    baby.chat("我的职业是程序员。")

    reply = baby.chat(question).text

    assert expected in reply
    assert "朋友" not in reply


def test_multi_value_friend_question_is_answered_from_relation_memory(baby):
    baby.chat("我的朋友叫小明。")
    baby.chat("我的朋友叫小红。")

    reply = baby.chat("我的朋友是谁？").text

    assert "小明" in reply
    assert "小红" in reply


def test_memory_question_beats_gentle_tone_template(baby):
    baby.chat("我住在浙江。")

    reply = baby.chat("谢谢，我住在哪里？").text

    assert "浙江" in reply
    assert "慢慢学" not in reply


def test_mock_does_not_present_arbitrary_retrieval_as_related_answer(baby):
    baby.chat("我的朋友叫小明。")

    reply = baby.chat("小明今天吃什么？").text

    assert (
        "小明" in reply
    )  # It may quote the user's question, but not the stored friend fact as an answer.
    assert "相关记录" not in reply
    assert "还没有学过相关知识" in reply


def test_learning_reply_is_human_readable_and_stage_aware(baby):
    newborn = baby.chat("我喜欢草莓。 ").text
    assert "草莓" in newborn
    assert "likes" not in newborn
    assert "用户 ·" not in newborn
    assert "先记住" in newborn

    with baby.memory.transaction():
        baby.memory.save_state("growth", Growth(interactions=500, stage="mature"))

    mature = baby.chat("我喜欢橘猫。 ").text
    assert "橘猫" in mature
    assert "likes" not in mature
    assert "明确告诉我的记录" in mature
    assert mature != newborn
