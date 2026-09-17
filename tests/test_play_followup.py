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

    night = baby.chat("我们今晚看了什么").text
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


def test_residence_overwrite_says_what_changed(baby):
    first = baby.chat("我住在浙江杭州。").text
    assert "浙江杭州" in first
    changed = baby.chat("我家在余杭。").text
    assert "余杭" in changed
    assert "之前是浙江杭州" in changed
    assert "余杭" in baby.chat("我住在哪里？").text


def test_same_turn_question_still_beats_overwrite_acknowledgement(baby):
    baby.chat("我住在浙江杭州。")
    reply = baby.chat("我家在余杭。我住在哪里？").text
    assert "余杭" in reply
    assert "先记住啦" not in reply
    assert "还没有告诉我" not in reply


def test_offline_notice_is_only_in_the_startup_greeting(baby):
    first = baby.greeting()
    second = baby.greeting()
    chat = baby.chat("你好").text
    assert "离线模式" in first
    assert "离线模式" not in second
    assert "当前为基础离线模式" not in first + second + chat
    assert "离线模式" not in chat


def test_negative_preference_question_is_not_routed_as_likes():
    assert fact_query_route("我不喜欢什么？") == ("preference", "dislikes")
    assert fact_query_route("我喜欢什么？") == ("preference", "likes")
    assert fact_query_route("What do I like?") == ("preference", "likes")


def test_relation_prefix_does_not_stick_to_the_name(baby):
    baby.chat("关系：王老师是我的老师")
    assert [f.value for f in baby.memory.facts() if f.kind == "relation"] == ["王老师"]
    reply = baby.chat("王老师呢").text
    assert "王老师" in reply
    assert "关系：" not in reply


def test_intensifier_like_without_pronoun_is_learned(baby):
    baby.chat("超喜欢草莓。")
    assert [f.value for f in baby.memory.facts("likes")] == ["草莓"]


def test_also_like_after_comma_is_learned(baby):
    baby.chat("我喜欢奶茶，也喜欢漫画。")
    values = {f.value for f in baby.memory.facts("likes")}
    assert values == {"奶茶", "漫画"}


def test_coordinated_dislikes_split_and_do_not_duplicate(baby):
    baby.chat("我不喜欢辣椒。")
    baby.chat("我不喜欢辣椒和早起。")
    assert {f.value for f in baby.memory.facts("dislikes")} == {"辣椒", "早起"}
    reply = baby.chat("我不喜欢什么？").text
    assert "辣椒" in reply and "早起" in reply
    assert "辣椒和早起" not in reply


def test_preference_reversal_removes_the_old_like(baby):
    baby.chat("超喜欢草莓。")
    baby.chat("我以前喜欢草莓，但是我现在不喜欢了")
    assert not baby.memory.facts("likes")
    assert [f.value for f in baby.memory.facts("dislikes")] == ["草莓"]


def test_event_time_window_does_not_mix_nights(baby):
    baby.chat("重要事件：今晚我们一起看了星星")
    baby.chat("重要事件：昨天晚上我们一起吃了火锅")
    night = baby.chat("昨晚看了什么").text
    assert "火锅" in night
    assert "星星" not in night
    tonight = baby.chat("今晚看了什么").text
    assert "星星" in tonight
    assert "火锅" not in tonight


def test_coarser_residence_does_not_erase_a_more_specific_place(baby):
    baby.chat("我现在住杭州西湖。")
    reply = baby.chat("我住在浙江。").text
    assert "杭州西湖" in reply
    assert "更具体" in reply
    assert "杭州西湖" in baby.chat("我住在哪里？").text
    assert [f.value for f in baby.memory.facts("居住地")] == ["杭州西湖"]


def test_identity_statements_are_not_teaching_prompts(baby):
    named = baby.chat("我叫Alice。").text
    call = baby.chat("你可以叫我Alice。").text
    about = baby.chat("你觉得我怎么样").text
    assert "还没有学过相关知识" not in named + call + about
    assert "Alice" in named
    assert "称呼你为妈妈，叫Alice" not in about


def test_companion_small_talk_does_not_demand_dolphin_template(baby):
    lines = [
        baby.chat("讲个冷笑话").text,
        baby.chat("你爱我吗").text,
        baby.chat("我饿了").text,
        baby.chat("陪我说说话").text,
        baby.chat("你会唱歌吗").text,
        baby.chat("背一首诗").text,
        baby.chat("今天天气怎么样").text,
        baby.chat("为什么天空是蓝的").text,
    ]
    blob = "".join(lines)
    assert "海豚是哺乳动物" not in blob
    assert "还没有学过相关知识" not in blob
