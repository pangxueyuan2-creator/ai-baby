import pytest

from ai_baby.baby import Baby
from ai_baby.learning import Learner
from ai_baby.memory import MemoryStore


def test_preference_and_teaching_survive_restart(tmp_path):
    path = tmp_path / "baby.sqlite3"
    memory = MemoryStore(path)
    baby = Baby(memory)
    baby.born("Alice", "female")
    baby.chat("我喜欢草莓。")
    baby.chat("学习：海豚是一种哺乳动物。")
    memory.close()
    memory = MemoryStore(path)
    try:
        baby = Baby(memory)
        assert "你喜欢草莓" in baby.chat("我喜欢什么？").text
        assert "海豚是一种哺乳动物" in baby.chat("海豚是什么？").text
    finally:
        memory.close()


def test_exact_duplicates_do_not_increase_knowledge(baby):
    baby.chat("记住：猫是一种哺乳动物。")
    first = baby.memory.counts()
    answer = baby.chat("学习：猫是一种哺乳动物！")
    assert "已经" in answer.text
    assert baby.memory.counts() == first


def test_preferences_correct_and_reactivate(baby):
    baby.chat("我喜欢草莓")
    baby.chat("我不喜欢草莓")
    assert baby.memory.facts("likes") == []
    assert "你不喜欢草莓" in baby.chat("我不喜欢什么？").text
    baby.chat("我喜欢草莓")
    assert baby.memory.facts("dislikes") == []
    assert len(baby.memory.facts("likes")) == 1


def test_world_knowledge_correction(baby):
    baby.chat("学习：海豚是一种鱼")
    baby.chat("学习：海豚是一种哺乳动物")
    assert "一种鱼" not in baby.chat("海豚是什么？").text
    assert len(baby.memory.facts()) == 1


@pytest.mark.parametrize(
    "text", ["我喜欢什么？", "我不喜欢草莓吗", "我喜欢什么", "学习：猫是什么？"]
)
def test_questions_are_not_assertions(baby, text):
    baby.chat(text)
    assert baby.memory.counts()["knowledge"] == 0


def test_personal_and_simple_relationship(baby):
    baby.chat("我住在杭州。我的生日是六月一日。关系：小明是我的朋友")
    assert "杭州" in baby.chat("我的居住地是哪里？").text
    assert "小明" in baby.chat("我的朋友是谁？").text
    assert {f.kind for f in baby.memory.facts()} == {"personal", "relation"}


def test_event_is_deduplicated(store):
    learner = Learner(store)
    learner.process("重要事件：今天一起看星星")
    learner.process("重要事件：今天一起看星星")
    assert store.counts()["events"] == 1


@pytest.mark.parametrize("text", ["", "a" * 2001, "hello\x1b[31m"])
def test_invalid_input_never_mutates(baby, text):
    before = baby.memory.counts()
    with pytest.raises(ValueError):
        baby.chat(text)
    assert baby.memory.counts() == before
