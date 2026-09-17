"""SQLite memory layers, atomic transactions, and bounded indexed retrieval."""

import json
import math
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from typing import Any, Iterator, TypeVar

from .migrations import SCHEMA_VERSION as SCHEMA_VERSION
from .migrations import initialize
from .migrations.v2 import novelty_key
from .models import Fact, Profile, record

T = TypeVar("T")


class MemoryError(RuntimeError):
    """A storage failure with a privacy-safe, actionable message."""


def tokens(text: str) -> set[str]:
    """Chinese character/bigram plus Latin token indexing; replaceable with vectors."""
    text = text.casefold()
    result = set(re.findall(r"[a-z0-9_]+", text))
    for part in re.findall(r"[\u3400-\u9fff]+", text):
        result.update(part)
        result.update(part[i : i + 2] for i in range(len(part) - 1))
    return result


SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL,
    gender TEXT NOT NULL CHECK(gender IN ('male','female','other')),
    address TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL,
    predicate TEXT NOT NULL, value TEXT NOT NULL, normalized TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user', active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kind, subject, predicate, normalized)
);
CREATE TABLE IF NOT EXISTS fact_tokens (
    token TEXT NOT NULL, fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    PRIMARY KEY(token, fact_id)
);
CREATE INDEX IF NOT EXISTS facts_active ON facts(active, kind, predicate, id);
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, summary TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class MemoryStore:
    """A single baby per database. Corruption never triggers a silent reset."""

    def __init__(self, path: Path):
        self.path = path
        self.connection: sqlite3.Connection | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(path, timeout=2, isolation_level=None)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys=ON")
            if self.connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise MemoryError("数据库完整性检查未通过。")
            initialize(self.connection, path, SCHEMA)
        except (sqlite3.Error, OSError, ValueError, RuntimeError) as exc:
            self.close()
            raise MemoryError(
                "无法打开记忆数据库。请检查权限、磁盘或备份；保留原文件，"
                "不要直接删除。可用 --data-dir 指向新目录创建另一个宝宝。"
            ) from exc

    @property
    def db(self) -> sqlite3.Connection:
        if self.connection is None:
            raise MemoryError("记忆数据库已关闭。")
        return self.connection

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Serialize state updates and roll back the entire turn on failure."""
        try:
            self.db.execute("BEGIN IMMEDIATE")
            yield
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    @contextmanager
    def preview(self) -> Iterator[None]:
        """Evaluate local effects under a short lock, always rolling them back."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        finally:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")

    def revision(self) -> int:
        return self.db.execute("SELECT value FROM revision WHERE id=1").fetchone()[0]

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def profile(self) -> Profile | None:
        row = self.db.execute("SELECT name,gender,address FROM profile WHERE id=1").fetchone()
        return Profile.create(**dict(row)) if row else None

    def save_profile(self, profile: Profile) -> None:
        """Store the authoritative profile outside learned, untrusted facts."""
        profile = Profile.create(profile.name, profile.gender, profile.address)
        self.db.execute(
            "INSERT INTO profile(id,name,gender,address) VALUES(1,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name,gender=excluded.gender,address=excluded.address",
            (profile.name, profile.gender, profile.address),
        )

    def load_state(self, key: str, cls: type[T]) -> T:
        row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        if row is None:
            return cls()
        try:
            data = json.loads(row[0])
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
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            raise MemoryError("保存的角色状态格式损坏；请从备份恢复。原数据未重置。") from exc

    def save_state(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO state VALUES(?,?)",
            (key, json.dumps(record(value), ensure_ascii=False)),
        )

    @staticmethod
    def normalize(value: str) -> str:
        return re.sub(r"\s+", "", value).casefold().rstrip("。.!！")

    def learn(self, kind: str, subject: str, predicate: str, value: str) -> bool:
        """Deduplicate; opposing preferences and changed single-valued facts supersede."""
        normalized = self.normalize(value)
        old = self.db.execute(
            "SELECT id,active FROM facts WHERE kind=? AND subject=? AND predicate=? AND normalized=?",
            (kind, subject, predicate, normalized),
        ).fetchone()
        if old and old["active"]:
            return False
        if kind == "preference":
            opposite = "dislikes" if predicate == "likes" else "likes"
            self.db.execute(
                "UPDATE facts SET active=0 WHERE kind=? AND subject=? AND predicate=? AND normalized=?",
                (kind, subject, opposite, normalized),
            )
        elif kind in {"personal", "world", "relation"}:
            self.db.execute(
                "UPDATE facts SET active=0 WHERE kind=? AND subject=? AND predicate=?",
                (kind, subject, predicate),
            )
        if old:
            fact_id = old["id"]
            self.db.execute("UPDATE facts SET active=1 WHERE id=?", (fact_id,))
        else:
            cursor = self.db.execute(
                "INSERT INTO facts(kind,subject,predicate,value,normalized,novelty) VALUES(?,?,?,?,?,?)",
                (kind, subject, predicate, value, normalized, novelty_key(subject + value)),
            )
            fact_id = cursor.lastrowid
            self.db.executemany(
                "INSERT OR IGNORE INTO fact_tokens VALUES(?,?)",
                [(t, fact_id) for t in tokens(subject + predicate + value)],
            )
        return True

    def retrieve_episodes(self, query: str, limit: int = 4) -> list[dict[str, Any]]:
        """Indexed relevance + importance + gently bounded recency, not latest-only."""
        query_tokens = sorted(tokens(query), key=lambda t: (-len(t), t))[:80]
        limit = max(1, min(limit, 10))
        if not query_tokens:
            return self.episodes(limit)
        marks = ",".join("?" for _ in query_tokens)
        # The 0..1 recency bonus cannot overwhelm multiple meaningful matching tokens.
        rows = self.db.execute(
            "SELECT e.id,e.kind,e.summary,e.importance,e.created_at, "
            "SUM(length(t.token)*length(t.token)) + 6*e.importance + "
            "1.0/(1.0+max(0,julianday('now')-julianday(e.created_at))/30) AS score "
            "FROM episode_tokens t JOIN episodes e ON e.id=t.episode_id "
            f"WHERE e.active=1 AND t.token IN ({marks}) GROUP BY e.id "
            "ORDER BY score DESC,e.id DESC LIMIT ?",
            (*query_tokens, limit),
        ).fetchall()
        return [
            {k: row[k] for k in ("id", "kind", "summary", "importance", "created_at")}
            for row in rows
        ]

    def setting(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, value))

    def experience(self, category: str, text: str) -> bool:
        """Novel experience signatures are local data; no per-repetition rewards."""
        import hashlib

        signature = hashlib.sha256(novelty_key(text).encode()).hexdigest()
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO experience VALUES(?,?)", (category, signature)
        )
        return cursor.rowcount > 0

    def growth_metrics(self, relation: Any, active_seconds: float):
        from .models import GrowthMetrics

        counts = self.counts()
        return GrowthMetrics(
            world_knowledge=self.db.execute(
                "SELECT count(*) FROM facts WHERE active=1 AND kind='world'"
            ).fetchone()[0],
            personal_memories=self.db.execute(
                "SELECT count(*) FROM facts WHERE active=1 AND kind IN ('preference','personal','relation')"
            ).fetchone()[0],
            episodic_memories=counts["memories"],
            relationship_depth=(relation.trust + relation.closeness + relation.familiarity) / 300,
            interaction_diversity=self.db.execute(
                "SELECT count(DISTINCT category) FROM experience"
            ).fetchone()[0],
            active_seconds=active_seconds,
            important_events=counts["events"],
            knowledge_diversity=self.db.execute(
                "SELECT count(DISTINCT novelty) FROM facts WHERE active=1 AND kind='world' AND length(novelty)>=3"
            ).fetchone()[0],
        )

    def retrieve(self, query: str, limit: int = 8) -> list[Fact]:
        """Bound candidates in SQL; prefer exact subject and longer token overlap."""
        limit = max(1, min(limit, 20))
        query_tokens = sorted(tokens(query), key=lambda t: (-len(t), t))[:80]
        if not query_tokens:
            return []
        marks = ",".join("?" for _ in query_tokens)
        rows = self.db.execute(
            f"SELECT f.id,f.kind,f.subject,f.predicate,f.value, "
            f"SUM(length(t.token)) + CASE WHEN instr(?,f.subject)>0 THEN 20 ELSE 0 END AS score "
            f"FROM fact_tokens t JOIN facts f ON f.id=t.fact_id "
            f"WHERE f.active=1 AND t.token IN ({marks}) "
            "GROUP BY f.id ORDER BY score DESC,f.id DESC LIMIT ?",
            [query, *query_tokens, limit],
        ).fetchall()
        return [
            Fact(**{k: r[k] for k in ("id", "kind", "subject", "predicate", "value")}) for r in rows
        ]

    def facts(self, predicate: str | None = None, limit: int = 20) -> list[Fact]:
        sql = "SELECT id,kind,subject,predicate,value FROM facts WHERE active=1"
        args: list[Any] = []
        if predicate is not None:
            sql += " AND predicate=?"
            args.append(predicate)
        rows = self.db.execute(
            sql + " ORDER BY id DESC LIMIT ?", (*args, max(1, min(limit, 100)))
        ).fetchall()
        return [Fact(**dict(r)) for r in rows]

    def episode(
        self, kind: str, summary: str, importance: float | None = None, fact_id: int | None = None
    ) -> None:
        if importance is None:
            importance = {"birth": 0.95, "important": 0.95, "milestone": 0.9, "emotion": 0.7}.get(
                kind, 0.4
            )
        if not math.isfinite(importance) or not 0 <= importance <= 1:
            raise ValueError("importance 必须是 0–1。")
        summary = summary[:500]
        cursor = self.db.execute(
            "INSERT INTO episodes(kind,summary,importance,fact_id) VALUES(?,?,?,?)",
            (kind, summary, importance, fact_id),
        )
        self.db.executemany(
            "INSERT INTO episode_tokens VALUES(?,?)",
            [(t, cursor.lastrowid) for t in tokens(summary)],
        )

    def episodes(self, limit: int = 4) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT id,kind,summary,importance,created_at FROM episodes WHERE active=1 ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 50)),),
            )
        ]

    def history(self, limit: int = 12) -> list[dict[str, str]]:
        rows = self.db.execute(
            "SELECT role,content FROM messages ORDER BY id DESC LIMIT ?", (max(1, min(limit, 100)),)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def message(self, role: str, content: str) -> None:
        self.db.execute("INSERT INTO messages(role,content) VALUES(?,?)", (role, content))
        self.db.execute(
            "DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY id DESC LIMIT 100)"
        )

    def counts(self) -> dict[str, int]:
        return {
            "knowledge": self.db.execute(
                "SELECT count(*) FROM facts WHERE active=1 AND kind IN ('world','knowledge')"
            ).fetchone()[0],
            "events": self.db.execute(
                "SELECT count(*) FROM episodes WHERE active=1 AND kind IN ('important','emotion','milestone')"
            ).fetchone()[0],
            "memories": self.db.execute("SELECT count(*) FROM episodes WHERE active=1").fetchone()[
                0
            ],
        }

    def backup(self, destination: Path) -> None:
        """Use SQLite's consistent backup API; never overwrite an existing file."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb"):
            pass
        try:
            target = sqlite3.connect(destination)
            try:
                self.db.backup(target)
            finally:
                target.close()
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
