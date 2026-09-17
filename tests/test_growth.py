from ai_baby.growth import STAGES, TRAITS, update
from ai_baby.models import Growth, GrowthMetrics, Relationship


def test_one_turn_cannot_produce_maturity():
    result = update(
        Growth(),
        GrowthMetrics(
            world_knowledge=1000,
            knowledge_diversity=1000,
            episodic_memories=1000,
            important_events=1000,
            interaction_diversity=5,
        ),
        Relationship(),
        1e9,
    )
    assert result.stage == "newborn"
    assert result.active_seconds == 300


def test_repeated_chat_without_learning_cannot_mature():
    state = Growth()
    for _ in range(1000):
        state = update(
            state,
            GrowthMetrics(episodic_memories=1, interaction_diversity=1),
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
            GrowthMetrics(
                world_knowledge=i // 3,
                knowledge_diversity=i // 3,
                episodic_memories=i // 3,
                important_events=i // 20,
                interaction_diversity=5,
            ),
            Relationship(*([min(100, 20 + i / 10)] * 5)),
            120,
        )
        seen.add(state.stage)
    assert seen == set(STAGES)
    assert state.stage == "mature"
    assert TRAITS["newborn"]["reflection"] < TRAITS["mature"]["reflection"]


def test_no_regression_after_corrections():
    state = Growth(interactions=1000, stage="mature")
    assert update(state, GrowthMetrics(), Relationship(), 0).stage == "mature"


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
