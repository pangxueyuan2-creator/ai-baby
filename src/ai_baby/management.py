"""User-directed memory controls, separate from language generation."""

import json
from pathlib import Path

from .memory import MemoryStore
from .migrations import SCHEMA_VERSION
from .models import Emotion, Growth, GrowthMetrics, PersonalityState, Relationship, record


def forget(memory: MemoryStore, fact_id: int) -> bool:
    """Deactivate a fact and derived recall; not forensic secure erasure."""
    with memory.transaction():
        fact = memory.db.execute(
            "SELECT value FROM facts WHERE id=? AND active=1", (fact_id,)
        ).fetchone()
        cursor = memory.db.execute("UPDATE facts SET active=0 WHERE id=? AND active=1", (fact_id,))
        if cursor.rowcount == 0:
            return False
        memory.db.execute(
            "UPDATE episodes SET active=0 WHERE fact_id=? OR instr(summary,?)>0", (fact_id, fact[0])
        )
        memory.db.execute(
            "UPDATE curiosity SET status='ignored',question='' WHERE fact_id=?", (fact_id,)
        )
        # Conservative privacy: old dialogue/summaries must not resurrect forgotten content.
        memory.db.execute("DELETE FROM messages")
        memory.db.execute("DELETE FROM turn_receipts")
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
    with destination.open("x", encoding="utf-8") as output:
        try:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
        except BaseException:
            output.close()
            destination.unlink(missing_ok=True)
            raise
