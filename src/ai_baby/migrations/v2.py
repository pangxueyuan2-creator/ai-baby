"""Add personality, indexed episodes and small persistent interaction subsystems."""

import json
import re
import sqlite3

from ..models import PersonalityState, record


def index_tokens(text: str) -> set[str]:
    """Frozen v2 index tokenizer, independent of future retrieval implementations."""
    result = set(re.findall(r"[a-z0-9_]+", text.casefold()))
    for part in re.findall(r"[\u3400-\u9fff]+", text):
        result.update(part)
        result.update(part[i : i + 2] for i in range(len(part) - 1))
    return result


def novelty_key(text: str) -> str:
    """Collapse numeric/punctuation variants; not a semantic truth detector."""
    return re.sub(r"[\W\d_]+", "", text.casefold())[:500]


def upgrade(db: sqlite3.Connection) -> None:
    """DDL and backfill run inside the caller's transaction; never executescript."""
    statements = [
        "ALTER TABLE facts ADD COLUMN novelty TEXT NOT NULL DEFAULT ''",
        "CREATE INDEX facts_novelty ON facts(active,kind,novelty)",
        # Older SQLite builds falsely reject floating NOT NULL defaults on populated tables.
        # Keep both constraints: add an integer default, then materialize the intended values.
        "ALTER TABLE episodes ADD COLUMN importance REAL NOT NULL DEFAULT 0 CHECK(importance BETWEEN 0 AND 1)",
        "UPDATE episodes SET importance=0.4",
        "ALTER TABLE episodes ADD COLUMN active INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE episodes ADD COLUMN fact_id INTEGER REFERENCES facts(id)",
        "CREATE TABLE episode_tokens(token TEXT NOT NULL, episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE, PRIMARY KEY(token,episode_id))",
        "CREATE INDEX episodes_rank ON episodes(active,importance,id)",
        "CREATE TABLE revision(id INTEGER PRIMARY KEY CHECK(id=1), value INTEGER NOT NULL)",
        "INSERT INTO revision VALUES(1,0)",
        "CREATE TABLE turn_receipts(id TEXT PRIMARY KEY, digest TEXT NOT NULL, answer TEXT NOT NULL, warning TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE candidates(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, predicate TEXT NOT NULL, value TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE journals(id INTEGER PRIMARY KEY, through_episode INTEGER NOT NULL, through_turn INTEGER NOT NULL, summary TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(through_episode,through_turn))",
        "CREATE TABLE curiosity(topic TEXT PRIMARY KEY, fact_id INTEGER REFERENCES facts(id), question TEXT NOT NULL, asked_turn INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','answered','ignored')))",
        "CREATE TABLE experience(category TEXT NOT NULL, signature TEXT NOT NULL, PRIMARY KEY(category,signature))",
        "CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "INSERT INTO settings VALUES('baby_name','AI 宝宝')",
    ]
    for statement in statements:
        db.execute(statement)
    for row in db.execute("SELECT id,subject,value FROM facts").fetchall():
        db.execute("UPDATE facts SET novelty=? WHERE id=?", (novelty_key(row[1] + row[2]), row[0]))
    db.execute(
        "UPDATE episodes SET importance=0.95 WHERE kind IN ('birth','important','milestone')"
    )
    db.execute("UPDATE episodes SET importance=0.7 WHERE kind='emotion'")
    db.execute(
        "UPDATE episodes SET fact_id=(SELECT id FROM facts WHERE subject || ' · ' || predicate || ' · ' || value=episodes.summary ORDER BY id DESC LIMIT 1)"
    )
    for row in db.execute("SELECT id,summary FROM episodes").fetchall():
        db.executemany(
            "INSERT INTO episode_tokens VALUES(?,?)", [(t, row[0]) for t in index_tokens(row[1])]
        )
    db.execute(
        "INSERT OR IGNORE INTO state VALUES('personality',?)",
        (json.dumps(record(PersonalityState())),),
    )
    # All public mutation paths (including direct SQL) invalidate optimistic turns.
    for table in (
        "profile",
        "facts",
        "episodes",
        "messages",
        "state",
        "candidates",
        "journals",
        "curiosity",
        "experience",
        "settings",
    ):
        for action in ("INSERT", "UPDATE", "DELETE"):
            db.execute(
                f"CREATE TRIGGER revision_{table}_{action.lower()} AFTER {action} ON {table} BEGIN UPDATE revision SET value=value+1 WHERE id=1; END"
            )
