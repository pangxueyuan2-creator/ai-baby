from ai_baby.growth import STAGES, TRAITS, update
from ai_baby.models import Growth, Relationship


def test_one_turn_cannot_produce_maturity():
    result = update(
        Growth(), {"knowledge": 1000, "memories": 1000, "events": 1000}, Relationship(), 1e9
    )
    assert result.stage == "newborn"
    assert result.active_seconds == 300


def test_repeated_chat_without_learning_cannot_mature():
    state = Growth()
    for _ in range(1000):
        state = update(
            state,
            {"knowledge": 0, "memories": 1, "events": 0},
            Relationship(100, 100, 100, 100, 100),
            300,
        )
    assert state.stage == "newborn"


def test_multidimensional_growth_reaches_all_stages():
    state = Growth()
    seen = {state.stage}
    for i in range(1, 1001):
        state = update(
            state,
            {"knowledge": i // 3, "memories": i // 3, "events": i // 20},
            Relationship(*([min(100, 20 + i / 10)] * 5)),
            120,
        )
        seen.add(state.stage)
    assert seen == set(STAGES)
    assert state.stage == "mature"
    assert TRAITS["newborn"]["reflection"] < TRAITS["mature"]["reflection"]


def test_no_regression_after_corrections():
    state = Growth(interactions=1000, stage="mature")
    assert (
        update(state, {"knowledge": 0, "memories": 0, "events": 0}, Relationship(), 0).stage
        == "mature"
    )


def test_restart_does_not_credit_offline_time(store):
    from ai_baby.baby import Baby

    ticks = [0.0]
    baby = Baby(store, clock=lambda: ticks[0])
    baby.born("Alice", "female")
    ticks[0] = 60
    baby.chat("你好")
    ticks[0] = 100000
    restarted = Baby(store, clock=lambda: ticks[0])
    restarted.chat("你好")
    assert store.load_state("growth", Growth).active_seconds == 60
