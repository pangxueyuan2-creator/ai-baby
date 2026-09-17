"""User-directed memory controls, separate from language generation."""

import json
import os
from pathlib import Path

from .memory import MemoryStore
from .migrations import SCHEMA_VERSION
from .models import (
    Emotion,
    Growth,
    GrowthMetrics,
    PersonalityState,
    Relationship,
    parse_memory_id,
    record,
)


def forget(memory: MemoryStore, fact_id: int) -> bool:
    """Forget active or superseded facts and derived recall; not secure erasure."""
    fact_id = parse_memory_id(fact_id)
    with memory.transaction():
        fact = memory.db.execute("SELECT value FROM facts WHERE id=?", (fact_id,)).fetchone()
        if fact is None:
            return False
        # Supersession only retired factual recall; history/journals may still contain it.
        memory.db.execute("UPDATE facts SET active=0 WHERE id=? AND active=1", (fact_id,))
        normalized = memory.normalize(fact[0])
        memory.db.execute("UPDATE episodes SET active=0 WHERE fact_id=?", (fact_id,))
        # Forget is an infrequent explicit operation. A normalized pass also finds
        # case/whitespace variants in unlinked v1 or emotional summaries.
        episode_ids = [
            (row["id"],)
            for row in memory.db.execute("SELECT id,summary FROM episodes WHERE active=1")
            if normalized and normalized in memory.normalize(row["summary"])
        ]
        memory.db.executemany("UPDATE episodes SET active=0 WHERE id=?", episode_ids)
        memory.db.execute(
            "UPDATE curiosity SET status='ignored',question='' WHERE fact_id=?", (fact_id,)
        )
        topics = [
            (row["topic"],)
            for row in memory.db.execute("SELECT topic,question FROM curiosity WHERE question!=''")
            if normalized and normalized in memory.normalize(row["question"])
        ]
        memory.db.executemany(
            "UPDATE curiosity SET status='ignored',question='' WHERE topic=?", topics
        )
        # Conservative privacy: old dialogue/summaries must not resurrect forgotten content.
        memory.db.execute("DELETE FROM messages")
        memory.db.execute("UPDATE turn_receipts SET revoked=1,answer='',warning=NULL")
        memory.db.execute("DELETE FROM candidates")
        memory.db.execute("DELETE FROM journals")
        memory.set_setting("journal_cursor", "0")
        growth = memory.load_state("growth", Growth)
        metrics = memory.growth_metrics(
            memory.load_state("relationship", Relationship), growth.active_seconds
        )
        growth.knowledge = metrics.world_knowledge
        growth.memories = metrics.episodic_memories
        growth.events = metrics.important_events
        memory.save_state("growth", growth)
        memory.save_state("growth_metrics", metrics)
    return True


def memory_page(memory: MemoryStore, before_id: str | int | None = None) -> list[dict]:
    """Explicit local inspection of 20 facts, including retired versions, by stable ID."""
    columns = "id,kind,subject,predicate,value,active"
    if before_id is None:
        rows = memory.db.execute(f"SELECT {columns} FROM facts ORDER BY id DESC LIMIT 20")
    else:
        rows = memory.db.execute(
            f"SELECT {columns} FROM facts WHERE id<? ORDER BY id DESC LIMIT 20",
            (parse_memory_id(before_id),),
        )
    return [dict(row) for row in rows]


def export_data(memory: MemoryStore, destination: Path) -> None:
    """Consistent readable export, with a strict allowlist; no config or credentials."""
    memory.db.execute("BEGIN")
    try:
        profile = memory.profile()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "baby_name": memory.setting("baby_name", "AI 宝宝"),
            "profile": record(profile) if profile else None,
            "facts": [
                dict(row)
                for row in memory.db.execute(
                    "SELECT id,kind,subject,predicate,value,source,created_at FROM facts WHERE active=1 ORDER BY id"
                )
            ],
            "important_episodes": [
                dict(row)
                for row in memory.db.execute(
                    "SELECT id,kind,summary,importance,created_at FROM episodes WHERE active=1 AND importance>=0.7 ORDER BY id"
                )
            ],
            "growth": record(memory.load_state("growth", Growth)),
            "growth_metrics": record(memory.load_state("growth_metrics", GrowthMetrics)),
            "relationship": record(memory.load_state("relationship", Relationship)),
            "emotion": record(memory.load_state("emotion", Emotion)),
            "personality": record(memory.load_state("personality", PersonalityState)),
            "journals": [
                dict(row)
                for row in memory.db.execute(
                    "SELECT id,summary,created_at FROM journals ORDER BY id"
                )
            ],
        }
    finally:
        memory.db.execute("ROLLBACK")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental overwrite. A failed write removes only our file.
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        output = os.fdopen(descriptor, "w", encoding="utf-8")
    except BaseException:
        # fdopen did not take ownership; do not leak a descriptor on setup failure.
        try:
            os.close(descriptor)
        finally:
            destination.unlink(missing_ok=True)
        raise
    try:
        with output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
    except BaseException:
        # Buffered writes can fail during __exit__/close, not only during json.dump.
        destination.unlink(missing_ok=True)
        raise
