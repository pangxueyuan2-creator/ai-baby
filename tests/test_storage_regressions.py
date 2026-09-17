"""Reproductions of atomicity, stale requests and corrected-evidence bugs."""

import sqlite3

import pytest

from ai_baby.management import forget
from ai_baby.memory import MemoryError, MemoryStore


def test_forgotten_turn_cannot_be_replayed_to_restore_fact(baby):
    baby.chat("我喜欢橘猫", turn_id="original-request")
    fact_id = baby.memory.facts()[0].id
    assert forget(baby.memory, fact_id)
    before = baby.memory.revision()
    with pytest.raises(ValueError, match="遗忘"):
        baby.chat("我喜欢橘猫", turn_id="original-request")
    assert not baby.memory.facts()
    assert baby.memory.revision() == before


def test_standalone_learning_is_atomic_if_index_write_fails(store):
    store.db.execute(
        "CREATE TRIGGER fail_index BEFORE INSERT ON fact_tokens "
        "BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END"
    )
    before = store.revision()
    with pytest.raises(sqlite3.IntegrityError):
        store.learn("world", "海豚", "是", "哺乳动物")
    assert not store.facts()
    assert store.revision() == before
    assert not store.db.in_transaction


def test_standalone_episode_is_atomic_if_index_write_fails(store):
    store.db.execute(
        "CREATE TRIGGER fail_index BEFORE INSERT ON episode_tokens "
        "BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END"
    )
    before = store.revision()
    with pytest.raises(sqlite3.IntegrityError):
        store.episode("important", "第一次认识星星")
    assert not store.episodes()
    assert store.revision() == before


def test_catching_nested_transaction_error_preserves_outer_work(store):
    with store.transaction():
        store.set_setting("outer", "preserved")
        with pytest.raises((ValueError, sqlite3.OperationalError)):
            with store.transaction():
                pytest.fail("Nested turn transactions must be rejected")
        assert store.db.in_transaction
    assert store.setting("outer") == "preserved"


def test_backup_rejects_active_transaction_before_copy(store, tmp_path, monkeypatch):
    class Connection:
        in_transaction = True

        def backup(self, target):
            pytest.fail("Backing up own active transaction may block forever")

    with store.transaction():
        original = store.connection
        monkeypatch.setattr(store, "connection", Connection())
        try:
            with pytest.raises(ValueError, match="事务"):
                store.backup(tmp_path / "backup.sqlite3")
        finally:
            store.connection = original
    assert not (tmp_path / "backup.sqlite3").exists()


def test_changed_fact_cannot_reappear_through_derived_episodes(baby):
    baby.chat("学习：海豚是鱼类")
    old_id = baby.memory.facts()[0].id
    baby.chat("学习：海豚是哺乳动物")
    assert all("鱼类" not in e["summary"] for e in baby.memory.retrieve_episodes("海豚"))
    assert all(f.value != "鱼类" for f in baby.memory.facts())
    assert not baby.memory.db.execute(
        "SELECT 1 FROM episodes WHERE fact_id=? AND active=1", (old_id,)
    ).fetchone()


def test_more_than_one_friend_is_preserved(baby):
    baby.chat("我的朋友叫小明")
    baby.chat("我的朋友叫小红")
    assert {f.value for f in baby.memory.facts() if f.kind == "relation"} == {"小明", "小红"}


@pytest.mark.parametrize(
    "damage",
    [
        "DELETE FROM revision",
        "UPDATE revision SET value=-1",
        "DROP TRIGGER revision_facts_update",
        "DROP TABLE fact_tokens",
        "DROP TABLE episode_tokens",
    ],
)
def test_damaged_revision_protection_rejected_without_reset(baby, damage):
    path = baby.memory.path
    baby.chat("我喜欢草莓")
    baby.memory.db.execute(damage)
    baby.memory.close()
    with pytest.raises(MemoryError, match="保留原文件"):
        MemoryStore(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM facts WHERE active=1").fetchone()[0] == "草莓"
