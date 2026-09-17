"""Small repeated experiences shape individual simulated traits."""

from dataclasses import replace

from .models import PersonalityState


def update(state: PersonalityState, tone: str, learned: bool, exploring: bool) -> PersonalityState:
    """At most 0.20 per trait per turn; approach boundaries with diminishing returns."""
    changes = {
        "gentle": {"confidence": 0.16, "openness": 0.12, "patience": 0.10, "sociability": 0.10},
        "playful": {"playfulness": 0.18, "sociability": 0.12, "openness": 0.08},
        "teasing": {"playfulness": 0.14, "confidence": 0.06},
        "hostile": {"caution": 0.18, "openness": -0.14, "confidence": -0.14, "sociability": -0.08},
        "reserved": {"caution": 0.12, "patience": 0.08, "sociability": -0.06},
        "distress": {"patience": 0.08, "caution": 0.04},
    }.get(tone, {}).copy()
    if learned or exploring:
        changes["curiosity"] = 0.16
        changes["independence"] = 0.12
        changes["openness"] = changes.get("openness", 0) + 0.04
    result = replace(state)
    for name, raw in changes.items():
        current = getattr(state, name)
        delta = max(-0.2, min(0.2, raw)) * ((100 - current) / 100 if raw > 0 else current / 100)
        setattr(result, name, round(max(0, min(100, current + delta)), 5))
    return result
