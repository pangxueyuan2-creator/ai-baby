"""Slow relationship updates with context-sensitive, conservative tone classification."""

import re
from dataclasses import replace

from .models import Relationship


def _direct_clauses(text: str) -> list[str]:
    """Conservatively exclude quotations, hypotheticals and reported utterances."""
    text = re.sub(r'[“”‘’「」\"]+', " ", text)
    clauses = re.findall(r"[^，,。！？!?；;\n]+[，,。！？!?；;\n]?", text)
    return [
        clause
        for clause in clauses
        if not any(marker in clause for marker in ("?", "？", "吗", "如果", "假如", "假设", "是否"))
        and not re.search(
            r"(?:他|她|别人|有人)(?:对我)?说|(?:不要|别|没有|没|不曾|不是|不许|并非|从没)(?:再)?说|台词|例句",
            clause,
        )
    ]


def _affirmed(clauses: list[str], words: tuple[str, ...]) -> bool:
    """A negated cue is neither praise nor a reason to punish the relationship."""
    return any(
        not re.search(
            r"(?:不|没|并非|不是|从未|未必|不算)(?:是|太|很|再|真的?|怎么)?$",
            clause[: match.start()],
        )
        for clause in clauses
        for word in words
        for match in re.finditer(re.escape(word), clause)
    )


def classify(text: str, state: Relationship) -> str:
    """Conservative lexical hints, not a general sarcasm or intent classifier."""
    clauses = _direct_clauses(text)
    if _affirmed(clauses, ("你去死", "我恨你", "你真恶心", "我要伤害你")):
        return "hostile"
    if _affirmed(
        clauses,
        (
            "今天很难过",
            "我很难过",
            "我很伤心",
            "我很累",
            "心情不好",
            "今天有点累",
            "有点累",
            "好累",
            "有点难过",
            "不太舒服",
        ),
    ):
        return "distress"
    if _affirmed(clauses, ("你个笨蛋", "你真笨", "小笨蛋")):
        friendly = state.familiarity >= 20 and state.trust >= 25
        return (
            "teasing" if friendly or _affirmed(clauses, ("哈哈", "开玩笑", "😼")) else "ambiguous"
        )
    if _affirmed(clauses, ("开玩笑", "哈哈", "一起玩")):
        return "playful"
    if _affirmed(clauses, ("谢谢", "做得好", "真棒", "别怕", "慢慢来", "喜欢你")):
        return "gentle"
    if _affirmed(clauses, ("谨慎一点", "先别急", "先观察", "保持距离")):
        return "reserved"
    return "neutral"


def update(state: Relationship, tone: str) -> Relationship:
    """Bounded, diminishing changes; passive chatter cannot farm trust or closeness."""
    changes = {
        "gentle": (0.30, 0.16, 0.20, 0.18, 0.08),
        "playful": (0.12, 0.10, 0.20, 0.12, 0.25),
        "teasing": (0.05, 0.08, 0.20, 0.10, 0.20),
        "hostile": (-0.35, -0.10, 0.10, -0.20, -0.15),
        "ambiguous": (0.0, 0.0, 0.08, 0.0, 0.0),
        "distress": (0.04, 0.05, 0.10, 0.05, 0.0),
        "neutral": (0.0, 0.0, 0.02, 0.0, 0.0),
        "reserved": (0.0, 0.01, 0.08, 0.01, 0.0),
    }
    result = replace(state)
    for name, delta in zip(
        ("trust", "attachment", "familiarity", "closeness", "playfulness"), changes[tone]
    ):
        current = getattr(state, name)
        remaining = (100.0 - current) / 100 if delta > 0 else current / 100
        setattr(result, name, round(max(0.0, min(100.0, current + delta * remaining)), 5))
    return result
