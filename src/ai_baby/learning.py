"""Conservative explicit learning. Free-form extraction can be added independently."""

import re
from dataclasses import dataclass, field

from .memory import MemoryStore


@dataclass
class LearningResult:
    acknowledgements: list[str] = field(default_factory=list)
    learned: int = 0


class Learner:
    """Learn supported assertions, never guesses extracted from a question."""

    def __init__(self, memory: MemoryStore):
        self.memory = memory

    def process(self, text: str) -> LearningResult:
        result = LearningResult()
        for sentence in re.split(r"[。！!；;\n]+", text):
            sentence = sentence.strip().rstrip(".")
            if not sentence or "?" in sentence or "？" in sentence:
                continue
            if any(q in sentence for q in ("什么", "吗", "是否", "为什么")):
                continue
            pref = re.fullmatch(r"我(不喜欢|讨厌|喜欢)(.+)", sentence)
            personal = re.fullmatch(r"我(住在|的生日是|的职业是)(.+)", sentence)
            taught = re.fullmatch(r"(?:记住|学习|知识)[：:]\s*(.+)", sentence)
            event = re.fullmatch(r"(?:重要事件|今天发生了)[：:]\s*(.+)", sentence)
            relation = re.fullmatch(r"关系[：:]\s*(.+?)是(.+?)的(.+)", sentence)
            candidate: tuple[str, str, str, str] | None = None
            if pref:
                candidate = (
                    "preference",
                    "用户",
                    "likes" if pref[1] == "喜欢" else "dislikes",
                    pref[2],
                )
            elif personal:
                candidate = (
                    "personal",
                    "用户",
                    {"住在": "居住地", "的生日是": "生日", "的职业是": "职业"}[personal[1]],
                    personal[2],
                )
            elif relation:
                candidate = ("relation", relation[2], relation[3], relation[1])
            elif taught:
                fact = re.fullmatch(r"(.+?)是(.+)", taught[1])
                candidate = (
                    ("world", fact[1], "是", fact[2])
                    if fact
                    else ("knowledge", "所学知识", "内容", taught[1])
                )
            elif event:
                # Explicit events are deduplicated as facts before becoming episodes.
                candidate = ("event", "用户", "经历", event[1])
            if candidate:
                candidate = tuple(v.strip() for v in candidate)
                if any(not v or len(v) > 500 for v in candidate):
                    result.acknowledgements.append("这条知识需要更简短一些（每项最多 500 字）。")
                    continue
                changed = self.memory.learn(*candidate)
                if changed:
                    result.learned += 1
                    self.memory.episode(
                        "important" if event else "learning", " · ".join(candidate[1:])
                    )
                result.acknowledgements.append(
                    ("我记住了：" if changed else "这条我已经记住了：") + " · ".join(candidate[1:])
                )
        return result
