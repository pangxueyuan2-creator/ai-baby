"""Validated, serializable domain objects."""

from dataclasses import asdict, dataclass
from typing import Any


def clean_text(value: str, maximum: int = 2000) -> str:
    """Reject blank, oversized and terminal-control-bearing user text."""
    value = value.strip()
    if not value or len(value) > maximum:
        raise ValueError(f"内容需要 1–{maximum} 个字符。")
    if any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
        raise ValueError("内容不能包含控制字符。")
    return value


def safe_output(value: str) -> str:
    """Prevent model responses from injecting terminal escape sequences."""
    return "".join(c for c in value if c == "\n" or (ord(c) >= 32 and not 127 <= ord(c) <= 159))


@dataclass(frozen=True)
class Profile:
    name: str
    gender: str
    address: str

    @classmethod
    def create(cls, name: str, gender: str, address: str | None = None) -> "Profile":
        """Create a profile without inferring gender from a name."""
        name = clean_text(name, 80)
        if gender not in {"male", "female", "other"}:
            raise ValueError("性别必须是 male、female 或 other。")
        return cls(
            name,
            gender,
            clean_text(address or {"male": "爸爸", "female": "妈妈"}.get(gender, name), 80),
        )


@dataclass
class Relationship:
    trust: float = 20.0
    attachment: float = 10.0
    familiarity: float = 0.0
    closeness: float = 10.0
    playfulness: float = 15.0


@dataclass
class Emotion:
    label: str = "curious"
    intensity: float = 0.3


@dataclass
class Growth:
    interactions: int = 0
    active_seconds: float = 0.0
    knowledge: int = 0
    memories: int = 0
    events: int = 0
    score: float = 0.0
    stage: str = "newborn"


@dataclass(frozen=True)
class Fact:
    id: int
    kind: str
    subject: str
    predicate: str
    value: str

    def text(self) -> str:
        """Human-readable evidence; no assertion of independent truth verification."""
        return f"{self.subject} · {self.predicate} · {self.value}"


def record(value: Any) -> dict[str, Any]:
    """Convert a dataclass state to JSON-compatible fields."""
    return asdict(value)
