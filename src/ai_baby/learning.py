"""Conservative explicit learning. Free-form extraction can be added independently."""

import re
from dataclasses import dataclass, field

from .candidates import MemoryCandidate, assertion_clauses, extract_candidates
from .memory import MemoryStore
from .models import parse_memory_id


@dataclass
class LearningResult:
    acknowledgements: list[str] = field(default_factory=list)
    learned: int = 0
    pending: list[dict] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    fact_ids: list[int] = field(default_factory=list)


_PLACE_CHILDREN = {
    "浙江": (
        "杭州",
        "宁波",
        "温州",
        "嘉兴",
        "绍兴",
        "金华",
        "台州",
        "丽水",
        "衢州",
        "舟山",
        "湖州",
        "余杭",
        "西湖",
        "萧山",
        "滨江",
        "临平",
    ),
    "杭州": ("余杭", "西湖", "萧山", "滨江", "拱墅", "上城", "临平"),
}


def _place_tokens(value: str) -> set[str]:
    text = MemoryStore.normalize(value)
    found = {text} if text else set()
    for parent, children in _PLACE_CHILDREN.items():
        if parent in text:
            found.add(parent)
        found.update(child for child in children if child in text)
    return found


def is_coarser_place(new: str, old: str) -> bool:
    """True when the new residence only names a broader region already implied by old."""
    incoming = MemoryStore.normalize(new)
    previous = MemoryStore.normalize(old)
    if not incoming or incoming == previous:
        return False
    if previous.startswith(incoming) and len(incoming) < len(previous):
        return True
    new_tokens = _place_tokens(new)
    old_tokens = _place_tokens(old)
    ancestors = set(_PLACE_CHILDREN)
    return bool(old_tokens - ancestors) and new_tokens <= ancestors


class Learner:
    """Learn supported assertions, never guesses extracted from a question."""

    def __init__(self, memory: MemoryStore):
        self.memory = memory

    def process(self, text: str) -> LearningResult:
        if not self.memory.db.in_transaction:
            with self.memory.transaction():
                return self.process(text)
        result = LearningResult()
        confirmation = re.fullmatch(r"确认记忆\s+(\d+)", text.strip())
        if confirmation:
            candidate_id = parse_memory_id(confirmation[1])
            row = self.memory.db.execute(
                "SELECT kind,subject,predicate,value FROM candidates WHERE id=?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                result.acknowledgements.append("这条候选不存在或已经处理")
            else:
                candidate = MemoryCandidate(**dict(row)).validated()
                self._save(candidate, result)
                self.memory.db.execute("DELETE FROM candidates WHERE id=?", (candidate_id,))
            return result
        for sentence in assertion_clauses(text):
            extracted = extract_candidates(sentence)
            if extracted:
                for extended in extracted:
                    if extended.ambiguous:
                        existing = self.memory.db.execute(
                            "SELECT id FROM candidates WHERE kind=? AND subject=? AND predicate=? AND value=?",
                            (extended.kind, extended.subject, extended.predicate, extended.value),
                        ).fetchone()
                        candidate_id = existing[0] if existing else self._propose(extended)
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
                fact = None if "不是" in taught[1] else re.fullmatch(r"(.+?)是(.+)", taught[1])
                candidate = (
                    ("world", fact[1], "是", fact[2])
                    if fact
                    else ("knowledge", "所学知识", "内容", taught[1])
                )
            elif event:
                candidate = ("event", "用户", "经历", event[1])
            if candidate:
                candidate = tuple(v.strip() for v in candidate)
                if any(not v or len(v) > 500 for v in candidate):
                    result.acknowledgements.append("这条知识需要更简短一些（每项最多 500 字）。")
                    continue
                self._save(MemoryCandidate(*candidate).validated(), result)
        if result.pending:
            current_ids = {row[0] for row in self.memory.db.execute("SELECT id FROM candidates")}
            result.pending = [
                proposal for proposal in result.pending if proposal["id"] in current_ids
            ]
        return result

    def _propose(self, candidate: MemoryCandidate) -> int:
        highest = self.memory.db.execute("SELECT coalesce(max(id),0) FROM candidates").fetchone()[0]
        candidate_id = max(highest, int(self.memory.setting("candidate_sequence", "0"))) + 1
        self.memory.set_setting("candidate_sequence", str(candidate_id))
        self.memory.db.execute(
            "INSERT INTO candidates(id,kind,subject,predicate,value) VALUES(?,?,?,?,?)",
            (candidate_id, candidate.kind, candidate.subject, candidate.predicate, candidate.value),
        )
        return candidate_id

    def _save(self, candidate: MemoryCandidate, result: LearningResult) -> None:
        candidate = candidate.validated()
        fields = (candidate.kind, candidate.subject, candidate.predicate, candidate.value)
        if candidate.kind == "preference":
            for row in self.memory.db.execute(
                "SELECT id,value FROM candidates WHERE kind='preference' AND subject=?",
                (candidate.subject,),
            ).fetchall():
                if self.memory.normalize(row["value"]) == self.memory.normalize(candidate.value):
                    self.memory.db.execute("DELETE FROM candidates WHERE id=?", (row["id"],))
        previous = None
        if candidate.kind == "personal":
            row = self.memory.db.execute(
                "SELECT id,value FROM facts WHERE kind=? AND subject=? AND predicate=? AND active=1",
                fields[:3],
            ).fetchone()
            if row and self.memory.normalize(row["value"]) != self.memory.normalize(candidate.value):
                previous = row["value"]
                if candidate.predicate == "居住地" and is_coarser_place(candidate.value, previous):
                    result.acknowledgements.append(
                        f"还是记着更具体的{previous}（{candidate.value}范围更大）"
                    )
                    result.fact_ids.append(row["id"])
                    return
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
                candidate.value if candidate.kind == "event" else " · ".join(fields[1:]),
                fact_id=fact_id,
            )
        if previous and changed:
            result.acknowledgements.append(
                f"我把{candidate.predicate}改成{candidate.value}了（之前是{previous}）"
            )
        else:
            result.acknowledgements.append(
                ("我记住了：" if changed else "这条我已经记住了：") + " · ".join(fields[1:])
            )
