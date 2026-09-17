"""Short CI version of the full offline stress demo's behavioral assertions."""

from scripts.stress_demo import compare_simulations, simulate_baby


def test_same_initial_baby_diverges_across_states_memories_and_context(tmp_path):
    results = {
        style: simulate_baby(tmp_path, style, 120) for style in ("warm", "reserved", "playful")
    }
    compare_simulations(results)
