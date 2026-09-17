"""Build actual v1 files from frozen SQL, never from the current schema."""

import json
import sqlite3
from pathlib import Path

import pytest

from ai_baby import migrations
from ai_baby.baby import Baby
from ai_baby.memory import MemoryStore
from ai_baby.models import Emotion, Growth, PersonalityState, Relationship, record


def create_v1(path):
    db = sqlite3.connect(path)
    db.executescript((Path(__file__).parent / "fixtures" / "v1.sql").read_text(encoding="utf-8"))
    db.execute("INSERT INTO profile(id,name,gender,address) VALUES(1,'Alice','female','妈妈')")
    db.execute(
        "INSERT INTO facts(kind,subject,predicate,value,normalized) VALUES('preference','用户','likes','草莓','草莓')"
    )
    db.execute("INSERT INTO episodes(kind,summary) VALUES('important','妈妈第一次教我星星')")
    for key, state in (
        ("growth", Growth(interactions=80, stage="child")),
        ("relationship", Relationship(trust=65)),
        ("emotion", Emotion("happy", 0.5)),
    ):
        db.execute("INSERT INTO state VALUES(?,?)", (key, json.dumps(record(state))))
    db.execute("PRAGMA user_version=1")
    db.commit()
    db.close()


def test_v1_migration_preserves_every_existing_layer(tmp_path):
    path = tmp_path / "baby.sqlite3"
    create_v1(path)
    memory = MemoryStore(path)
    try:
        assert memory.db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert memory.profile().name == "Alice"
        assert memory.profile().gender == "female"
        assert memory.profile().address == "妈妈"
        assert memory.facts()[0].value == "草莓"
        assert "星星" in memory.episodes()[0]["summary"]
        assert memory.load_state("growth", Growth).stage == "child"
        assert memory.load_state("growth", Growth).interactions == 80
        assert memory.load_state("relationship", Relationship).trust == 65
        assert memory.load_state("emotion", Emotion) == Emotion("happy", 0.5)
        assert memory.load_state("personality", PersonalityState).curiosity == 70
        assert "草莓" in Baby(memory).chat("我喜欢什么？").text
    finally:
        memory.close()
    backups = list((tmp_path / "backups").glob("pre-v1*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
    MemoryStore(path).close()
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


def test_migration_failure_rolls_back_ddl_and_data(tmp_path, monkeypatch):
    path = tmp_path / "baby.sqlite3"
    create_v1(path)

    def fail(db):
        migrations.upgrade_v2(db)
        db.execute("UPDATE profile SET name='broken'")
        raise ValueError("simulated migration failure")

    monkeypatch.setitem(migrations.MIGRATIONS, 1, fail)
    with pytest.raises(Exception, match="无法打开记忆"):
        MemoryStore(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT name FROM profile").fetchone()[0] == "Alice"
        assert "importance" not in {r[1] for r in db.execute("PRAGMA table_info(episodes)")}
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


def test_backup_failure_does_not_start_migration(tmp_path, monkeypatch):
    path = tmp_path / "baby.sqlite3"
    create_v1(path)
    original = Path.open

    def fail(self, *args, **kwargs):
        if self.name.startswith("pre-v1-"):
            raise PermissionError("backup blocked")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(Exception, match="无法打开记忆"):
        MemoryStore(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT name FROM profile").fetchone()[0] == "Alice"


def test_two_simultaneous_migration_openers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "baby.sqlite3"
    create_v1(path)

    def open_one():
        memory = MemoryStore(path)
        try:
            return memory.db.execute("PRAGMA user_version").fetchone()[0]
        finally:
            memory.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(lambda _: open_one(), range(2))) == [2, 2]
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


def test_failed_backup_copy_is_closed_and_not_kept_as_valid_backup(tmp_path, monkeypatch):
    path = tmp_path / "baby.sqlite3"
    create_v1(path)
    original = sqlite3.connect
    closed = []

    class FailingReader:
        def backup(self, target):
            raise OSError("simulated full disk during backup")

        def close(self):
            closed.append(True)

    def connect(target, *args, **kwargs):
        if "?mode=ro" in str(target):
            return FailingReader()
        return original(target, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(Exception, match="无法打开记忆"):
        MemoryStore(path)
    assert closed
    assert list((tmp_path / "backups").glob("*.sqlite3")) == []
    with original(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
