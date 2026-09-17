"""Validated, explicit memory proposals. No model inference of personal attributes."""

import re
from dataclasses import dataclass

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
        for value in (self.subject, self.predicate, self.value):
            clean_text(value, 500)
        if self.kind == "preference" and (
            self.subject != "用户" or self.predicate not in {"likes", "dislikes"}
        ):
            raise ValueError("偏好候选格式无效。")
        if self.kind == "personal" and (
            self.subject != "用户" or self.predicate not in {"居住地", "生日", "职业"}
        ):
            raise ValueError("个人资料候选格式无效。")
        return self


def extract_extended(sentence: str) -> MemoryCandidate | None:
    """Anchored first-person assertions only. Ambiguous preference requires confirmation."""
    uncertain = re.fullmatch(r"(?:其实)?我(?:可能|也许|好像)(?:有点)?喜欢(.+)", sentence)
    if uncertain:
        return MemoryCandidate("preference", "用户", "likes", uncertain[1], True).validated()
    preference = re.fullmatch(r"(?:其实)?我(?:从小)?(?:就)?(?:一直)?(?:特别|很)?喜欢(.+)", sentence)
    favorite = re.fullmatch(r"(?:其实)?(.+?)是我最喜欢的(?:水果|动物|食物|颜色)", sentence)
    address = re.fullmatch(r"我(?:现在住(?:在)?|住在)(.+)", sentence)
    friend = re.fullmatch(r"我的朋友叫(.+)", sentence)
    if preference:
        return MemoryCandidate("preference", "用户", "likes", preference[1]).validated()
    if favorite:
        return MemoryCandidate("preference", "用户", "likes", favorite[1]).validated()
    if address and "住院" not in sentence:
        return MemoryCandidate("personal", "用户", "居住地", address[1]).validated()
    if friend:
        return MemoryCandidate("relation", "我", "朋友", friend[1]).validated()
    return None
