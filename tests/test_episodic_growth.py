import time

from ai_baby.growth import update
from ai_baby.models import Growth, Relationship


def test_old_important_episode_retrieved_after_thousands_of_memories(baby):
    memory = baby.memory
    with memory.transaction():
        memory.episode("important", "爸爸第一次教我什么叫星星", importance=0.99)
        old_id = memory.db.execute("SELECT max(id) FROM episodes").fetchone()[0]
        memory.db.execute(
            "UPDATE episodes SET created_at=datetime('now','-90 days') WHERE id=?", (old_id,)
        )
        for i in range(1200):
            memory.episode("learning", f"普通生活记录，第{i}次练习", importance=0.3)
            memory.learn("world", f"词{i}", "是", f"编号{i}")
    started = time.perf_counter()
    for _ in range(10):
        found = memory.retrieve_episodes("你还记得我第一次教你星星吗？", 4)
        assert found[0]["id"] == old_id
        assert len(found) <= 4
        assert len(memory.retrieve("编号是什么", 8)) <= 8
    assert time.perf_counter() - started < 3.0
    assert "星星" in baby.chat("还记得第一次教你星星吗？").text


def test_importance_can_outweigh_mild_recency(store):
    with store.transaction():
        store.episode("important", "星星", 0.99)
        store.db.execute("UPDATE episodes SET created_at=datetime('now','-90 days')")
        store.episode("learning", "星星", 0.2)
    assert store.retrieve_episodes("星星", 1)[0]["importance"] == 0.99


def test_growth_distinguishes_personal_and_world_memories(baby):
    baby.chat("我喜欢橘猫。我的生日是六月一日。关系：小明是我的朋友。重要事件：一起赏月")
    assert baby.memory.counts()["knowledge"] == 0
    metrics = baby.memory.growth_metrics(Relationship(), 0)
    assert metrics.world_knowledge == 0
    assert metrics.personal_memories == 3
    assert metrics.important_events == 1
    baby.chat("学习：海豚是哺乳动物")
    assert baby.memory.growth_metrics(Relationship(), 0).world_knowledge == 1


def test_numbered_garbage_cannot_mature_baby(store):
    with store.transaction():
        for i in range(1500):
            store.learn("world", f"垃圾{i}", "是", f"值{i}")
        for category in ("gentle", "playful", "exploration", "neutral", "learning:world"):
            store.experience(category, category)
    relation = Relationship(100, 100, 100, 100, 100)
    metrics = store.growth_metrics(relation, 100000)
    assert metrics.world_knowledge == 1500
    assert metrics.knowledge_diversity == 1
    result = update(Growth(interactions=2000, active_seconds=100000), metrics, relation, 300)
    assert result.stage in {"newborn", "baby"}


def test_duplicate_experience_does_not_increase_diversity(store):
    with store.transaction():
        for _ in range(1000):
            store.experience("neutral", "你好")
    assert store.db.execute("SELECT count(*) FROM experience").fetchone()[0] == 1


def test_explicit_prose_teaching_counts_as_knowledge_without_counting_preferences(baby):
    baby.chat("知识：地球围绕太阳运行。学习：海豚不是鱼。")
    baby.chat("我喜欢草莓")
    metrics = baby.memory.growth_metrics(Relationship(), 0)
    assert metrics.world_knowledge == baby.memory.counts()["knowledge"] == 2
    assert metrics.knowledge_diversity == 2
    assert metrics.personal_memories == 1
