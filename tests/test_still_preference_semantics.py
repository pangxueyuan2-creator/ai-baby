import pytest


@pytest.mark.parametrize(
    "text,value,predicate",
    [
        ("我还是喜欢草莓。", "草莓", "likes"),
        ("我现在还是很喜欢橘猫。", "橘猫", "likes"),
        ("我还是不喜欢菠菜。", "菠菜", "dislikes"),
        ("我还是讨厌榴莲。", "榴莲", "dislikes"),
    ],
)
def test_still_preferences_are_saved_as_explicit_assertions(baby, text, value, predicate):
    baby.chat(text)

    matches = [
        fact
        for fact in baby.memory.facts()
        if fact.kind == "preference" and fact.value == value
    ]

    assert len(matches) == 1
    assert matches[0].predicate == predicate


@pytest.mark.parametrize(
    "text",
    [
        "我喜欢苹果还是香蕉",
        "我还是喜欢苹果还是香蕉",
        "我喜欢苹果还是香蕉？",
    ],
)
def test_alternative_questions_do_not_become_preferences(baby, text):
    baby.chat(text)

    assert not [fact for fact in baby.memory.facts() if fact.kind == "preference"]


def test_still_preference_replaces_previous_opposite_value(baby):
    baby.chat("我不喜欢草莓。")
    baby.chat("我还是喜欢草莓。")

    active = [
        fact
        for fact in baby.memory.facts()
        if fact.kind == "preference" and fact.value == "草莓"
    ]

    assert len(active) == 1
    assert active[0].predicate == "likes"
