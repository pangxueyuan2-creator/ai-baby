"""Deterministic bounded consolidation, triggered by turns or explicit commands."""

import json
import math
from datetime import datetime, timezone

from .memory import MemoryError, MemoryStore
from .models import Growth, PersonalityState, record


def consolidate(memory: MemoryStore, *, force: bool = False) -> str | None:
    """Caller holds a short transaction. Journals never count as new growth evidence."""
    state = memory.load_state("growth", Growth)
    last_turn = int(memory.setting("journal_turn", "0"))
    if not force and state.interactions - last_turn < 20:
        return None
    cursor = int(memory.setting("journal_cursor", "0"))
    maximum = memory.db.execute("SELECT coalesce(max(id),0) FROM episodes").fetchone()[0]
    if maximum <= cursor and state.interactions <= last_turn:
        return None
    rows = memory.db.execute(
        "SELECT summary FROM episodes WHERE active=1 AND id>? ORDER BY importance DESC,id DESC LIMIT 6",
        (cursor,),
    ).fetchall()
    profile = memory.db.execute("SELECT created_at FROM profile WHERE id=1").fetchone()
    if profile is None:
        return None
    born = datetime.fromisoformat(profile[0]).replace(tzinfo=timezone.utc)
    day = max(1, (datetime.now(timezone.utc) - born).days + 1)
    current = record(memory.load_state("personality", PersonalityState))
    previous = json.loads(
        memory.setting("journal_personality", json.dumps(record(PersonalityState())))
    )
    if (
        not isinstance(previous, dict)
        or set(previous) != set(current)
        or any(
            not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 100
            for v in previous.values()
        )
    ):
        raise MemoryError("日记人格快照损坏，请从备份恢复。")
    changes = [
        f"{key} {'提高' if current[key] > previous[key] else '降低'} {abs(current[key] - previous[key]):.2f}"
        for key in current
        if abs(current[key] - previous[key]) >= 0.05
    ]
    summary = (
        f"出生第 {day} 天（软件角色状态记录，非真实感受）。阶段：{state.stage}。"
        + "记录："
        + ("；".join(row[0] for row in rows) or "本段没有新增重要经历")
        + "。人格变化："
        + ("、".join(changes) or "暂无明显变化")
        + "。"
    )[:1200]
    memory.db.execute(
        "INSERT INTO journals(through_episode,through_turn,summary) VALUES(?,?,?)",
        (maximum, state.interactions, summary),
    )
    memory.set_setting("journal_cursor", str(maximum))
    memory.set_setting("journal_turn", str(state.interactions))
    memory.set_setting("journal_personality", json.dumps(current))
    return summary


def recent(memory: MemoryStore, limit: int = 5) -> list[dict]:
    return [
        dict(row)
        for row in memory.db.execute(
            "SELECT id,summary,created_at FROM journals ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 10)),),
        )
    ]
