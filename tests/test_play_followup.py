"""Regression cases from the offline playthrough: recall, extra likes, companion chat."""

from ai_baby.conversation import fact_query_route
from ai_baby.models import Relationship
from ai_baby.relationship import classify


def test_remember_where_i_live_does_not_erase_the_stored_place(baby):
    baby.chat("我住在浙江杭州。")
    baby.chat("我家在余杭。")

    assert "余杭" in baby.chat("我住在哪里？").text
    remembered = baby.chat("还记得我住哪吗").text
    assert "余杭" in remembered
    assert "还没有告诉我" not in remembered
    assert "余杭" in baby.chat("我回来了，还记得我住哪吗").text


def test_also_like_is_learned_without_the_teaching_prefix(baby):
    baby.chat("我喜欢橘猫。")
    baby.chat("我也喜欢下雨天。")

    reply = baby.chat("我喜欢什么？").text
    assert "橘猫" in reply
    assert "下雨天" in reply


def test_english_preference_question_uses_saved_likes(baby):
    baby.chat("I like coffee.")

    reply = baby.chat("What do I like?").text
    assert "coffee" in reply
    assert "还没有学过相关知识" not in reply


def test_tired_small_talk_is_distress_not_a_teaching_form(baby):
    assert classify("今天有点累", Relationship()) == "distress"
    reply = baby.chat("今天有点累").text
    assert "不太轻松" in reply
    assert "学习：" not in reply


def test_recorded_evening_can_be_asked_without_the_remember_prefix(baby):
    baby.chat("重要事件：今晚我们一起看了星星")

    night = baby.chat("我们昨晚看了什么").text
    assert "星星" in night
    assert "用户 ·" not in night
    assert "星星" in baby.chat("星星").text
    assert "没有找到" in baby.chat("还记得我们第一次去海边吗").text


def test_companion_questions_do_not_demand_the_teaching_syntax(baby):
    miss = baby.chat("想我了吗").text
    story = baby.chat("给我讲个故事").text
    about = baby.chat("你觉得我怎么样").text

    assert "学习：" not in miss + story + about
    assert "没有真实想念" in miss
    assert "故事" in story
    assert "照顾" in about


def test_negative_preference_question_is_not_routed_as_likes():
    assert fact_query_route("我不喜欢什么？") == ("preference", "dislikes")
    assert fact_query_route("我喜欢什么？") == ("preference", "likes")
    assert fact_query_route("What do I like?") == ("preference", "likes")
