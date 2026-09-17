"""Slow relationship updates with context-sensitive, conservative tone classification."""

from dataclasses import replace

from .models import Relationship


def classify(text: str, state: Relationship) -> str:
    """Negative situations are distinct from hostility directed at the character."""
    if any(w in text for w in ("你去死", "我恨你", "你真恶心", "我要伤害你")):
        return "hostile"
    if any(w in text for w in ("今天很难过", "我很难过", "我很伤心", "我很累", "心情不好")):
        return "distress"
    if any(w in text for w in ("你个笨蛋", "你真笨", "小笨蛋")):
        friendly = state.familiarity >= 20 and state.trust >= 25
        return (
            "teasing"
            if friendly or any(w in text for w in ("哈哈", "开玩笑", "😼"))
            else "ambiguous"
        )
    if any(w in text for w in ("开玩笑", "哈哈", "一起玩")):
        return "playful"
    if any(w in text for w in ("谢谢", "做得好", "真棒", "别怕", "慢慢来", "喜欢你")):
        return "gentle"
    return "neutral"


def update(state: Relationship, tone: str) -> Relationship:
    """Per-turn changes stay at or below 0.35 on each 0–100 scale."""
    changes = {
        "gentle": (0.30, 0.16, 0.20, 0.18, 0.08),
        "playful": (0.12, 0.10, 0.20, 0.12, 0.25),
        "teasing": (0.05, 0.08, 0.20, 0.10, 0.20),
        "hostile": (-0.35, -0.10, 0.10, -0.20, -0.15),
        "ambiguous": (0.0, 0.0, 0.15, 0.0, 0.0),
        "distress": (0.04, 0.05, 0.15, 0.05, 0.0),
        "neutral": (0.05, 0.04, 0.20, 0.04, 0.01),
    }
    result = replace(state)
    for name, delta in zip(
        ("trust", "attachment", "familiarity", "closeness", "playfulness"), changes[tone]
    ):
        setattr(result, name, round(max(0.0, min(100.0, getattr(state, name) + delta)), 4))
    return result
