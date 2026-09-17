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
_QUESTIONS = ("?", "？", "什么", "吗", "是否", "哪里", "哪儿", "谁", "是不是", "对不对")
_NON_ASSERTIONS = (
    "\u201c",
    "\u201d",
    '"',
    "\u2018",
    "\u2019",
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
_ENGLISH_PREFERENCE_CUE = re.compile(
    r"\bi\s+(?:really\s+)?(?:like|dislike|do\s+not|don't)\b", re.IGNORECASE
)
_ENGLISH_PREFERENCE = re.compile(
    r"i\s+(?:really\s+)?(?:(?P<positive>like)|dislike|(?:do\s+not|don't)\s+like)\s+(?P<value>.+)",
    re.IGNORECASE,
)
_ENGLISH_QUALIFIER = re.compile(
    r"\b(?:if|unless|when|maybe|perhaps|possibly|probably|might|would|could|should|but|"
    r"although|because|whether|unsure|uncertain|used\s+to|not|or|"
    r"i|you|he|she|they|we)\b",
    re.IGNORECASE,
)


def _english_preference(sentence: str) -> MemoryCandidate | None:
    """Recognize a complete simple preference; decline complex or qualified objects."""
    match = _ENGLISH_PREFERENCE.fullmatch(sentence)
    if not match:
        return None
    value = match["value"]
    if _ENGLISH_QUALIFIER.search(value) or re.search(r"[.;?!]", value):
        return None
    # Follow the matched grammar branch; Unicode IGNORECASE is not str.lower().
    predicate = "likes" if match["positive"] is not None else "dislikes"
    return MemoryCandidate("preference", "用户", predicate, value).validated()


def _unsupported_still(sentence: str) -> bool:
    """Treat 还是 as 'still' only in an explicit first-person assertion prefix.

    The same token commonly means an alternative question (苹果还是香蕉). If it is
    not the supported 我[现在]还是... prefix, or appears again in the object, abstain.
    """
    if "还是" not in sentence:
        return False
    remainder = re.sub(r"^(?:其实)?我(?:现在)?还是", "", sentence, count=1)
    return remainder == sentence or "还是" in remainder


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
        if (
            not sentence
            or _unsupported_still(sentence)
            or any(cue in sentence for cue in (*questions, *_NON_ASSERTIONS))
        ):
            continue
        if sentence.startswith("我喜欢的") or "住院" in sentence:
            continue
        if _REVERSAL.fullmatch(sentence):
            clauses.append(sentence)
            continue
        if re.match(r"(?:记住|学习|知识|重要事件|今天发生了|关系)[：:]", sentence):
            clauses.append(sentence)
            continue
        if _ENGLISH_PREFERENCE_CUE.search(sentence):
            # Do not discard a qualifier/report/tag question when splitting commas.
            # Every part must be a complete supported assertion; otherwise abstain.
            if not all(_english_preference(part.strip()) for part in re.split(r"[，,]+", sentence)):
                continue
        for clause in re.split(r"[，,]+", sentence):
            clause = re.sub(r"^(?:但是|但|而且|其实)", "", clause.strip())
            continued = sentence.startswith("我") and (
                clause.startswith(("现在", "已经", "不再"))
                or re.match(
                    r"(?:也|还|又|还是)?(?:特别|很|超|好|挺)?(?:不)?(?:喜欢|讨厌)",
                    clause,
                )
            )
            if continued and not clause.startswith("我"):
                clause = "我" + clause
            if any(cue in clause for cue in ("但是", "但", "不过", "虽然", "因为", "然后")):
                continue
            if re.search(r"(?:喜欢|讨厌).+(?:喜欢|讨厌)", clause):
                continue
            clauses.append(clause)
    return clauses


def split_preference_objects(value: str) -> list[str]:
    """Split short coordinated likes/dislikes, but keep phrases that contain 的."""
    parts = [part.strip().rstrip("。.") for part in re.split(r"(?:、|以及|还有|(?<!的)和)", value)]
    parts = [part for part in parts if part]
    if len(parts) >= 2 and all(1 <= len(part) <= 12 and "的" not in part for part in parts):
        return parts
    return [value.strip()]


def extract_candidates(sentence: str) -> list[MemoryCandidate]:
    """One clause may yield several preference objects after conservative splitting."""
    extracted = extract_extended(sentence)
    if extracted is None:
        return []
    if extracted.kind != "preference":
        return [extracted]
    return [
        replace(extracted, value=part).validated()
        for part in split_preference_objects(extracted.value)
    ]


def extract_extended(sentence: str) -> MemoryCandidate | None:
    """Anchored first-person assertions only. Ambiguous preference requires confirmation."""
    sentence = re.sub(r"^(?:关系)[：:]\s*", "", sentence.strip())
    uncertain = re.fullmatch(
        r"(?:其实)?我(?:可能|也许|好像)(?:有点)?喜欢(.+)", sentence
    ) or re.fullmatch(r"我喜欢(.+?)吧", sentence)
    if uncertain:
        return MemoryCandidate("preference", "用户", "likes", uncertain[1], True).validated()
    reversal = _REVERSAL.fullmatch(sentence)
    if reversal:
        return MemoryCandidate("preference", "用户", "dislikes", reversal[1]).validated()
    negative = re.fullmatch(
        r"我(?:(?:现在|已经)?不喜欢|还是(?:不喜欢|讨厌)|不再喜欢|讨厌)(.+?)(?:了)?",
        sentence,
    )
    if negative:
        return MemoryCandidate("preference", "用户", "dislikes", negative[1]).validated()
    preference = re.fullmatch(
        r"(?:其实)?我(?:现在)?(?:也|还|又|还是)?(?:从小)?(?:就)?(?:一直)?(?:特别|很|超|好|挺)?喜欢(.+)",
        sentence,
    )
    intense = re.fullmatch(
        r"(?:其实)?(?:也|还|又|还是)?(?:特别|很|超|好|挺)喜欢(.+)", sentence
    )
    favorite = re.fullmatch(r"(?:其实)?(.+?)是我最喜欢的(?:水果|动物|食物|颜色)", sentence)
    address = re.fullmatch(r"我(?:现在住(?:在)?|住在)(.+)", sentence)
    home_address = re.fullmatch(r"我家在(.+)", sentence)
    friend = re.fullmatch(r"我的朋友叫(.+)", sentence)
    named_relation = re.fullmatch(r"我的(朋友|同学|老师|同事|家人)叫(.+)", sentence)
    reverse_relation = re.fullmatch(r"(.+?)是我(?:的)?(朋友|同学|老师|同事|家人)", sentence)
    english_preference = _english_preference(sentence)
    if preference:
        return MemoryCandidate("preference", "用户", "likes", preference[1]).validated()
    if intense:
        return MemoryCandidate("preference", "用户", "likes", intense[1]).validated()
    if favorite:
        return MemoryCandidate("preference", "用户", "likes", favorite[1]).validated()
    if english_preference:
        return english_preference
    if address and "住院" not in sentence:
        return MemoryCandidate("personal", "用户", "居住地", address[1]).validated()
    if home_address and "住院" not in sentence:
        return MemoryCandidate("personal", "用户", "居住地", home_address[1]).validated()
    if friend:
        return MemoryCandidate("relation", "我", "朋友", friend[1]).validated()
    if named_relation:
        return MemoryCandidate("relation", "我", named_relation[1], named_relation[2]).validated()
    if reverse_relation:
        return MemoryCandidate(
            "relation", "我", reverse_relation[2], reverse_relation[1]
        ).validated()
    return None
