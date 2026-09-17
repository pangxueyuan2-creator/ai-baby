"""Ordered, transactional schema upgrades; migration backups never overwrite data."""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from ..storage_files import reserve_private_file
from .v2 import upgrade as upgrade_v2
from .v3 import upgrade as upgrade_v3

SCHEMA_VERSION = 3
MIGRATIONS = {1: upgrade_v2, 2: upgrade_v3}


def validate_schema(db: sqlite3.Connection) -> None:
    """Refuse damaged concurrency metadata rather than pretending the store is safe."""
    for table, columns in {
        "profile": "id,name,gender,address,created_at",
        "facts": "id,kind,subject,predicate,value,active,novelty",
        "episodes": "id,kind,summary,importance,active,fact_id",
        "turn_receipts": "id,digest,answer,warning,revoked",
        "fact_tokens": "token,fact_id",
        "episode_tokens": "token,episode_id",
        "candidates": "id,kind,subject,predicate,value",
        "journals": "id,through_episode,through_turn,summary,created_at",
        "curiosity": "topic,fact_id,question,asked_turn,status",
        "experience": "category,signature",
        "messages": "id,role,content,created_at",
        "state": "key,value",
        "settings": "key,value",
    }.items():
        db.execute(f"SELECT {columns} FROM {table} LIMIT 0")
    revision = db.execute("SELECT value FROM revision WHERE id=1").fetchone()
    if revision is None or type(revision[0]) is not int or revision[0] < 0:
        raise ValueError("数据库 revision 无效。")
    triggers = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    required = {
        f"revision_{table}_{action}"
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
        )
        for action in ("insert", "update", "delete")
    }
    if not required <= triggers:
        raise ValueError("数据库并发保护不完整。")


def initialize(db: sqlite3.Connection, path: Path, base_schema: str) -> None:
    """Lock only during migration, back up committed v1 via a separate reader."""
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if version not in {0, *MIGRATIONS}:
        raise ValueError("数据库版本不受支持；请升级程序，原数据未重置。")
    db.execute("BEGIN IMMEDIATE")
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:  # Another process already migrated.
            db.execute("COMMIT")
            return
        if version == 0:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                raise ValueError("无版本的非空数据库不能自动升级。")
            for statement in base_schema.split(";"):
                if statement.strip():
                    db.execute(statement)
            version = 1
        else:
            directory = path.parent / "backups"
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            destination = directory / f"pre-v{version}-to-v{SCHEMA_VERSION}-{stamp}.sqlite3"
            reserve_private_file(destination)
            try:
                with (
                    closing(
                        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
                    ) as reader,
                    closing(sqlite3.connect(destination)) as target,
                ):
                    reader.backup(target)
            except BaseException:
                destination.unlink(missing_ok=True)
                raise
        while version < SCHEMA_VERSION:
            MIGRATIONS[version](db)
            version += 1
            db.execute(f"PRAGMA user_version={version}")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("迁移后的引用完整性检查失败。")
        validate_schema(db)
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
