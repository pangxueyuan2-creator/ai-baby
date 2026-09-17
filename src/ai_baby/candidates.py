"""Validated, explicit memory proposals. No model inference of personal attributes."""

import re
from dataclasses import dataclass, replace

from .models import clean_text


@dataclass(frozen=True)
class MemoryCandidate:
    kind: str
    subject: str
    predicate: str
    value: str
    ambiguous: bool = False

    def validated(self) -> "MemoryCandidate":
        """Only locally understood fact shapes can cross the persistence boundary."""
        allowed = {"preference", "personal", "world", "relation", "knowledge", "event"}
        if self.kind not in allowed:
            raise ValueError("未知记忆类型。")
        if any(not isinstance(value, str) for value in (self.subject, self.predicate, self.value)):
            raise ValueError("记忆内容必须是文本。")
        candidate = replace(
            self,
            subject=clean_text(self.subject, 500),
            predicate=clean_text(self.predicate, 500),
            value=clean_text(self.value, 500),
        )
        if self.kind == "preference" and (
            candidate.subject != "用户" or candidate.predicate not in {"likes", "dislikes"}
        ):
            raise ValueError("偏好候选格式无效。")
        if self.kind == "personal" and (
            candidate.subject != "用户" or candidate.predicate not in {"居住地", "生日", "职业"}
        ):
            raise ValueError("个人资料候选格式无效。")
        return candidate


_REVERSAL = re.compile(
    r"我(?:以前|曾经)?喜欢([^，,]+)[，,]\s*(?:但是|但)?(?:我)?(?:现在|已经)不喜欢(?:了)?"
)
_QUESTIONS = ("?", "？", "什么", "吗", "是否", "哪里", "哪儿", "谁", "是不是", "对不对", "还是")
_NON_ASSERTIONS = (
    "“",
    "”",
    '"',
    "‘",
    "’",
    "如果",
    "假如",
    "假设",
    "据说",
    "别人说",
    "他说",
    "她说",
    "你说",
    "不是说",
    "不确定",
    "未必",
    "不一定",
    "例如",
    "比如",
    "例句",
)


def assertion_clauses(text: str) -> list[str]:
    """Split explicit clauses without stripping the scope of questions or hypotheticals.

    This is a small supported grammar, not general Chinese language understanding.
    Unknown temporal qualifiers are rejected instead of becoming part of a fact value.
    """
    clauses = []
    for sentence in re.split(r"[。！!;；\n]+", text):
        sentence = sentence.strip().rstrip(".")
        event = re.match(r"(?:重要事件|今天发生了)[：:]", sentence)
        questions = (
            tuple(q for q in _QUESTIONS if q not in {"什么", "哪里", "哪儿", "谁"})
            if event
            else _QUESTIONS
        )
        if not sentence or any(cue in sentence for cue in (*questions, *_NON_ASSERTIONS)):
            continue
        if sentence.startswith("我喜欢的") or "住院" in sentence:
            continue
        # Resolve this exact, explicit anaphoric negation before splitting the comma.
        if _REVERSAL.fullmatch(sentence):
            clauses.append(sentence)
            continue
        # Explicit teaching/event syntax may legitimately contain descriptive commas.
        if re.match(r"(?:记住|学习|知识|重要事件|今天发生了|关系)[：:]", sentence):
            clauses.append(sentence)
            continue
        for clause in re.split(r"[，,]+", sentence):
            clause = re.sub(r"^(?:但是|但|而且|其实)", "", clause.strip())
            if sentence.startswith("我") and clause.startswith(("现在", "已经", "不再")):
                clause = "我" + clause
            # Do not swallow a second proposition into a personal fact's object.
            if any(cue in clause for cue in ("但是", "但", "不过", "虽然", "因为", "然后")):
                continue
            if re.search(r"(?:喜欢|讨厌).+(?:喜欢|讨厌)", clause):
                continue
            clauses.append(clause)
    return clauses


def extract_extended(sentence: str) -> MemoryCandidate | None:
    """Anchored first-person assertions only. Ambiguous preference requires confirmation."""
    uncertain = re.fullmatch(
        r"(?:其实)?我(?:可能|也许|好像)(?:有点)?喜欢(.+)", sentence
    ) or re.fullmatch(r"我喜欢(.+?)吧", sentence)
    if uncertain:
        return MemoryCandidate("preference", "用户", "likes", uncertain[1], True).validated()
    reversal = _REVERSAL.fullmatch(sentence)
    if reversal:
        return MemoryCandidate("preference", "用户", "dislikes", reversal[1]).validated()
    negative = re.fullmatch(r"我(?:(?:现在|已经)?不喜欢|不再喜欢|讨厌)(.+?)(?:了)?", sentence)
    if negative:
        return MemoryCandidate("preference", "用户", "dislikes", negative[1]).validated()
    preference = re.fullmatch(
        r"(?:其实)?我(?:现在)?(?:也|还|又)?(?:从小)?(?:就)?(?:一直)?(?:特别|很|超|好|挺)?喜欢(.+)",
        sentence,
    )
    favorite = re.fullmatch(r"(?:其实)?(.+?)是我最喜欢的(?:水果|动物|食物|颜色)", sentence)
    address = re.fullmatch(r"我(?:现在住(?:在)?|住在)(.+)", sentence)
    home_address = re.fullmatch(r"我家在(.+)", sentence)
    friend = re.fullmatch(r"我的朋友叫(.+)", sentence)
    named_relation = re.fullmatch(r"我的(朋友|同学|老师|同事|家人)叫(.+)", sentence)
    reverse_relation = re.fullmatch(r"(.+?)是我(?:的)?(朋友|同学|老师|同事|家人)", sentence)
    english_like = re.fullmatch(
        r"i\s+(?:really\s+)?like\s+(.+)", sentence, flags=re.IGNORECASE
    )
    english_dislike = re.fullmatch(
        r"i\s+(?:really\s+)?(?:do\s+not|don't|dislike)\s+(.+)",
        sentence,
        flags=re.IGNORECASE,
    )
    if preference:
        return MemoryCandidate("preference", "用户", "likes", preference[1]).validated()
    if favorite:
        return MemoryCandidate("preference", "用户", "likes", favorite[1]).validated()
    if english_like:
        return MemoryCandidate("preference", "用户", "likes", english_like[1]).validated()
    if english_dislike:
        return MemoryCandidate("preference", "用户", "dislikes", english_dislike[1]).validated()
    if address and "住院" not in sentence:
        return MemoryCandidate("personal", "用户", "居住地", address[1]).validated()
    if home_address and "住院" not in sentence:
        return MemoryCandidate("personal", "用户", "居住地", home_address[1]).validated()
    if friend:
        return MemoryCandidate("relation", "我", "朋友", friend[1]).validated()
    if named_relation:
        return MemoryCandidate("relation", "我", named_relation[1], named_relation[2]).validated()
    if reverse_relation:
        return MemoryCandidate("relation", "我", reverse_relation[2], reverse_relation[1]).validated()
    return None
