"""Shared decoding rules for persisted character states and read-only recovery checks."""

import json
import math
import sqlite3
from contextlib import closing
from dataclasses import fields
from typing import Any, TypeVar

from .models import Emotion, Growth, GrowthMetrics, PersonalityState, Relationship, record

T = TypeVar("T")

_STATE_TYPES: dict[str, type[Any]] = {
    "growth": Growth,
    "growth_metrics": GrowthMetrics,
    "relationship": Relationship,
    "emotion": Emotion,
    "personality": PersonalityState,
}


class StateValidationError(ValueError):
    """A stored character state is unreadable; the message never includes stored values."""


def decode_state(key: str, serialized: str | bytes | bytearray, cls: type[T]) -> T:
    """Decode one present state using the established chat types, fields and ranges."""
    try:
        data = json.loads(serialized)
        if not isinstance(data, dict) or set(data) != {f.name for f in fields(cls)}:
            raise ValueError("invalid state fields")
        defaults = record(cls())
        for name, value in data.items():
            expected = defaults[name]
            if isinstance(expected, (int, float)):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError("invalid numeric state")
            elif not isinstance(value, str):
                raise ValueError("invalid string state")
        if key in {"relationship", "personality"} and any(v > 100 for v in data.values()):
            raise ValueError("invalid relationship")
        if key == "emotion" and (
            data["label"]
            not in {"calm", "happy", "curious", "sad", "playful", "nervous", "annoyed"}
            or data["intensity"] > 1
        ):
            raise ValueError("invalid emotion")
        if key == "growth" and data["stage"] not in {
            "newborn",
            "baby",
            "child",
            "growing",
            "mature",
        }:
            raise ValueError("invalid stage")
        return cls(**data)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise StateValidationError("保存的角色状态格式损坏；请从备份恢复。原数据未重置。") from None


def validate_stored_states(connection: sqlite3.Connection) -> None:
    """Read only known state keys; absent states keep defaults and unknown keys are ignored."""
    placeholders = ",".join("?" for _ in _STATE_TYPES)
    # An error traceback must not retain an active cursor that pins the staged database file.
    with closing(
        connection.execute(
            f"SELECT key,value FROM state WHERE key IN ({placeholders})", tuple(_STATE_TYPES)
        )
    ) as rows:
        for key, serialized in rows:
            decode_state(key, serialized, _STATE_TYPES[key])
