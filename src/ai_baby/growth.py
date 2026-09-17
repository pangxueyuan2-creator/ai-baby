"""Multiple saturating experience dimensions drive an irreversible growth stage."""

import math
from dataclasses import replace

from .models import Growth, GrowthMetrics, Relationship

STAGES = ("newborn", "baby", "child", "growing", "mature")
THRESHOLDS = (0, 12, 30, 52, 75)
TRAITS = {
    "newborn": {
        "language": "简单、好奇、短句；能够正常交流",
        "complexity": 1,
        "curiosity": 0.95,
        "independence": 0.10,
        "reflection": 0.10,
        "worldview": "经验很少，区分知道和不知道",
    },
    "baby": {
        "language": "活泼，能举简单例子",
        "complexity": 2,
        "curiosity": 0.90,
        "independence": 0.25,
        "reflection": 0.25,
        "worldview": "开始连接学过的概念",
    },
    "child": {
        "language": "完整句子，说明简单原因",
        "complexity": 3,
        "curiosity": 0.80,
        "independence": 0.45,
        "reflection": 0.45,
        "worldview": "比较观点，承认经验的局限",
    },
    "growing": {
        "language": "有条理，主动提出可能性",
        "complexity": 4,
        "curiosity": 0.70,
        "independence": 0.65,
        "reflection": 0.70,
        "worldview": "理解情境和多个解释",
    },
    "mature": {
        "language": "温和清晰，能反思且承认不确定性",
        "complexity": 5,
        "curiosity": 0.65,
        "independence": 0.85,
        "reflection": 0.90,
        "worldview": "综合经历，审视自己的假设",
    },
}


def update(state: Growth, counts: GrowthMetrics, relation: Relationship, elapsed: float) -> Growth:
    """Time is active session time, capped per turn; wall-clock absence adds nothing."""
    result = replace(state)
    result.interactions += 1
    # A completed turn is a short exchange even when the test clock barely moves.
    # Wall-clock gaps are still capped at 300s; absence between processes is not added here.
    presence = max(0.0, min(300.0, elapsed)) if math.isfinite(elapsed) else 0.0
    result.active_seconds += max(presence, 8.0)
    result.knowledge = counts.world_knowledge
    result.memories = counts.episodic_memories
    result.events = counts.important_events

    def saturate(value: float, scale: float) -> float:
        return 1.0 - math.exp(-value / scale)

    depth = (relation.trust + relation.closeness + relation.familiarity) / 300
    score = (
        20 * saturate(result.interactions, 400)
        + 15 * saturate(result.active_seconds, 36000)
        + 25 * saturate(counts.knowledge_diversity, 100)
        + 10 * saturate(result.memories, 100)
        + 15 * depth
        + 5 * saturate(result.events, 30)
        + 10 * min(1.0, counts.interaction_diversity / 5)
    )
    result.score = round(score, 3)
    # Require breadth: repeated empty chatter alone cannot reach mature.
    gates = ((0, 0), (10, 1), (60, 8), (200, 25), (500, 60))
    eligible = [
        i
        for i, (threshold, (turns, facts)) in enumerate(zip(THRESHOLDS, gates))
        if score >= threshold
        and result.interactions >= turns
        and counts.knowledge_diversity >= facts
        and counts.interaction_diversity >= min(i, 4)
    ]
    result.stage = STAGES[max(STAGES.index(state.stage), max(eligible))]
    return result
