"""Frozen v2 upgrade, real interrupted process, and preservation of every v2 layer."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from ai_baby import migrations
from ai_baby.memory import MemoryError, MemoryStore

ROOT = Path(__file__).resolve().parents[1]


def create_v2(path):
    db = sqlite3.connect(path)
    try:
        db.executescript((ROOT / "tests/fixtures/v2.sql").read_text(encoding="utf-8"))
        db.execute("INSERT INTO profile VALUES(1,'Alice','female','妈妈','2026-01-01')")
        db.execute(
            "INSERT INTO facts(id,kind,subject,predicate,value,normalized,novelty) "
            "VALUES(1,'preference','用户','likes','橘猫','橘猫','用户橘猫')"
        )
        db.execute("INSERT INTO fact_tokens VALUES('橘猫',1)")
        db.execute(
            "INSERT INTO episodes(id,kind,summary,importance,fact_id) "
            "VALUES(1,'learning','用户喜欢橘猫',0.7,1)"
        )
        db.execute("INSERT INTO episode_tokens VALUES('橘猫',1)")
        db.execute("INSERT INTO messages(role,content) VALUES('user','我喜欢橘猫')")
        db.execute(
            "INSERT INTO candidates(kind,subject,predicate,value) VALUES('preference','用户','likes','草莓')"
        )
        db.execute("INSERT INTO curiosity VALUES('topic',1,'为什么喜欢橘猫',1,'pending')")
        db.execute(
            "INSERT INTO journals(through_episode,through_turn,summary) VALUES(1,1,'模拟成长记录')"
        )
        db.execute("INSERT INTO experience VALUES('gentle','synthetic-signature')")
        db.execute("INSERT INTO turn_receipts(id,digest,answer) VALUES('old','digest','旧回答')")
        db.execute("UPDATE settings SET value='星星' WHERE key='baby_name'")
        for key, value in (
            (
                "growth",
                {
                    "interactions": 40,
                    "active_seconds": 120,
                    "knowledge": 1,
                    "memories": 1,
                    "events": 0,
                    "score": 12,
                    "stage": "baby",
                },
            ),
            (
                "relationship",
                {
                    "trust": 42,
                    "attachment": 25,
                    "familiarity": 9,
                    "closeness": 21,
                    "playfulness": 30,
                },
            ),
            ("emotion", {"label": "happy", "intensity": 0.5}),
        ):
            db.execute("INSERT INTO state VALUES(?,?)", (key, json.dumps(value)))
        db.commit()
    finally:
        db.close()


def snapshot(path):
    with sqlite3.connect(path) as db:
        tables = (
            "profile",
            "facts",
            "episodes",
            "state",
            "settings",
            "candidates",
            "messages",
            "journals",
            "curiosity",
            "experience",
            "fact_tokens",
            "episode_tokens",
        )
        result = {
            table: db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in tables
        }
        result["settings"] = [row for row in result["settings"] if row[0] != "candidate_sequence"]
        return result


def test_frozen_v2_preserves_all_layers_and_backup(tmp_path):
    path = tmp_path / "baby.sqlite3"
    create_v2(path)
    before = snapshot(path)
    memory = MemoryStore(path)
    try:
        assert memory.db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert memory.db.execute("SELECT revoked FROM turn_receipts").fetchone()[0] == 0
        assert memory.db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert memory.setting("candidate_sequence") == "1"
    finally:
        memory.close()
    assert snapshot(path) == before
    (backup,) = (tmp_path / "backups").glob("pre-v2-to-v3-*.sqlite3")
    assert snapshot(backup) == before
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_v2_upgrade_failure_preserves_schema_and_data(tmp_path, monkeypatch):
    path = tmp_path / "baby.sqlite3"
    create_v2(path)
    before = snapshot(path)

    def fail(db):
        migrations.upgrade_v3(db)
        db.execute("UPDATE profile SET name='broken'")
        raise OSError("simulated migration disk failure")

    monkeypatch.setitem(migrations.MIGRATIONS, 2, fail)
    with pytest.raises(MemoryError):
        MemoryStore(path)
    assert snapshot(path) == before
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert "revoked" not in {r[1] for r in db.execute("PRAGMA table_info(turn_receipts)")}


def test_process_dies_during_migration_and_next_open_recovers(tmp_path):
    path = tmp_path / "baby.sqlite3"
    create_v2(path)
    before = snapshot(path)
    script = """
import os, sys
from pathlib import Path
from ai_baby import migrations
from ai_baby.memory import MemoryStore
def interrupted(db):
    migrations.upgrade_v3(db)
    db.execute("UPDATE profile SET name='broken'")
    os._exit(23)
migrations.MIGRATIONS[2] = interrupted
MemoryStore(Path(sys.argv[1]))
"""
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    result = subprocess.run([sys.executable, "-c", script, str(path)], env=env, timeout=15)
    assert result.returncode == 23
    assert snapshot(path) == before
    MemoryStore(path).close()
    assert snapshot(path) == before


def test_migration_retires_already_superseded_derived_evidence(tmp_path):
    path = tmp_path / "baby.sqlite3"
    create_v2(path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE facts SET active=0")
    memory = MemoryStore(path)
    try:
        assert not memory.retrieve_episodes("橘猫")
        assert memory.db.execute("SELECT status,question FROM curiosity").fetchone()[:] == (
            "ignored",
            "",
        )
    finally:
        memory.close()


def test_schema_invariant_failure_also_rolls_back_upgrade(tmp_path):
    path = tmp_path / "baby.sqlite3"
    create_v2(path)
    with sqlite3.connect(path) as db:
        db.execute("DROP TRIGGER revision_facts_update")
    before = snapshot(path)
    with pytest.raises(MemoryError):
        MemoryStore(path)
    assert snapshot(path) == before
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_upgrade_preserves_candidate_sequence_before_first_command_deletes_it(tmp_path):
    from ai_baby.baby import Baby
    from ai_baby.main import command

    path = tmp_path / "baby.sqlite3"
    create_v2(path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE candidates SET id=80")
    memory = MemoryStore(path)
    try:
        baby = Baby(memory)
        command(baby, "/reject 80")
        baby.chat("我可能喜欢梨")
        assert memory.db.execute("SELECT id FROM candidates").fetchone()[0] == 81
    finally:
        memory.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permission contract")
def test_new_databases_and_both_backup_paths_are_owner_only(tmp_path):
    path = tmp_path / "new.sqlite3"
    memory = MemoryStore(path)
    target = tmp_path / "manual.sqlite3"
    try:
        memory.backup(target)
    finally:
        memory.close()
    legacy = tmp_path / "legacy.sqlite3"
    create_v2(legacy)
    MemoryStore(legacy).close()
    (backup,) = (tmp_path / "backups").glob("pre-v2-to-v3-*.sqlite3")
    for item in (path, target, backup):
        assert item.stat().st_mode & 0o777 == 0o600
