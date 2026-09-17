import pytest

from ai_baby.baby import Baby
from ai_baby.memory import MemoryStore
from ai_baby.models import PersonalityState, record
from ai_baby.personality import update


@pytest.mark.parametrize(
    "tone", ["gentle", "playful", "teasing", "hostile", "reserved", "distress", "neutral"]
)
def test_every_trait_change_is_bounded(tone):
    state = PersonalityState()
    for _ in range(1000):
        next_state = update(state, tone, True, True)
        for name, value in record(next_state).items():
            assert 0 <= value <= 100
            assert abs(value - getattr(state, name)) <= 0.20001
        state = next_state


def test_identical_babies_diverge_and_persist(tmp_path):
    memories = [MemoryStore(tmp_path / f"baby-{i}.sqlite3") for i in range(2)]
    try:
        babies = [Baby(m) for m in memories]
        for baby in babies:
            baby.born("Alice", "female")
        assert memories[0].load_state("personality", PersonalityState) == memories[1].load_state(
            "personality", PersonalityState
        )
        for _ in range(200):
            babies[0].chat("谢谢你，真棒，我们一起探索")
            babies[1].chat("谨慎一点，先观察，保持距离")
        encouraged = memories[0].load_state("personality", PersonalityState)
        reserved = memories[1].load_state("personality", PersonalityState)
        assert encouraged.confidence - reserved.confidence > 10
        assert encouraged.curiosity - reserved.curiosity > 7
        assert reserved.caution - encouraged.caution > 10
    finally:
        for memory in memories:
            memory.close()
    reopened = MemoryStore(tmp_path / "baby-0.sqlite3")
    try:
        assert reopened.load_state("personality", PersonalityState) == encouraged
    finally:
        reopened.close()


def test_invalid_saved_personality_does_not_silently_reset(store):
    import json

    from ai_baby.memory import MemoryError

    data = record(PersonalityState()) | {"openness": 1000}
    store.db.execute("UPDATE state SET value=? WHERE key='personality'", (json.dumps(data),))
    with pytest.raises(MemoryError):
        Baby(store)
