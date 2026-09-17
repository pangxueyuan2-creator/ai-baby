"""Conservative explicit learning. Free-form extraction can be added independently."""

import re
from dataclasses import dataclass, field

from .candidates import MemoryCandidate, extract_extended
from .memory import MemoryStore


@dataclass
class LearningResult:
    acknowledgements: list[str] = field(default_factory=list)
    learned: int = 0
    pending: list[dict] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    fact_ids: list[int] = field(default_factory=list)


class Learner:
    """Learn supported assertions, never guesses extracted from a question."""

    def __init__(self, memory: MemoryStore):
        self.memory = memory

    def process(self, text: str) -> LearningResult:
        result = LearningResult()
        confirmation = re.fullmatch(r"确认记忆\s+(\d+)", text.strip())
        if confirmation:
            row = self.memory.db.execute(
                "SELECT kind,subject,predicate,value FROM candidates WHERE id=?",
                (int(confirmation[1]),),
            ).fetchone()
            if row is None:
                result.acknowledgements.append("这条候选不存在或已经处理")
            else:
                candidate = MemoryCandidate(**dict(row)).validated()
                self._save(candidate, result)
                self.memory.db.execute("DELETE FROM candidates WHERE id=?", (int(confirmation[1]),))
            return result
        for sentence in re.split(r"[。！!；;\n]+", text):
            sentence = sentence.strip().rstrip(".")
            if not sentence or "?" in sentence or "？" in sentence:
                continue
            if any(q in sentence for q in ("什么", "吗", "是否", "为什么", "哪里", "哪儿", "谁")):
                continue
            if sentence.startswith("我喜欢的") or "住院" in sentence:
                continue
            # Quoted, hypothetical, negated or uncertain personal claims are not assertions.
            if any(
                w in sentence
                for w in ("“", "”", '"', "如果", "假如", "据说", "别人说", "不是说", "不确定")
            ):
                continue
            extended = extract_extended(sentence)
            if extended is not None:
                if extended.ambiguous:
                    existing = self.memory.db.execute(
                        "SELECT id FROM candidates WHERE kind=? AND subject=? AND predicate=? AND value=?",
                        (extended.kind, extended.subject, extended.predicate, extended.value),
                    ).fetchone()
                    candidate_id = (
                        existing[0]
                        if existing
                        else self.memory.db.execute(
                            "INSERT INTO candidates(kind,subject,predicate,value) VALUES(?,?,?,?)",
                            (extended.kind, extended.subject, extended.predicate, extended.value),
                        ).lastrowid
                    )
                    self.memory.db.execute(
                        "DELETE FROM candidates WHERE id NOT IN (SELECT id FROM candidates ORDER BY id DESC LIMIT 3)"
                    )
                    result.pending.append({"id": candidate_id, "value": extended.value})
                else:
                    self._save(extended, result)
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
                self._save(MemoryCandidate(*candidate).validated(), result)
        return result

    def _save(self, candidate: MemoryCandidate, result: LearningResult) -> None:
        candidate.validated()
        fields = (candidate.kind, candidate.subject, candidate.predicate, candidate.value)
        changed = self.memory.learn(*fields)
        if changed:
            result.learned += 1
            result.categories.append(candidate.kind)
            fact_id = self.memory.db.execute(
                "SELECT id FROM facts WHERE kind=? AND subject=? AND predicate=? AND normalized=?",
                (*fields[:3], self.memory.normalize(candidate.value)),
            ).fetchone()[0]
            result.fact_ids.append(fact_id)
            self.memory.episode(
                "important" if candidate.kind == "event" else "learning",
                " · ".join(fields[1:]),
                fact_id=fact_id,
            )
        result.acknowledgements.append(
            ("我记住了：" if changed else "这条我已经记住了：") + " · ".join(fields[1:])
        )
