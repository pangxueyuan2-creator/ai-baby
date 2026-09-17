import sqlite3

import pytest

from ai_baby.baby import Baby
from ai_baby.memory import MemoryError, MemoryStore
from ai_baby.models import Growth


@pytest.mark.parametrize(
    "gender,address", [("male", "爸爸"), ("female", "妈妈"), ("other", "Alice")]
)
def test_identity_survives_restart(tmp_path, gender, address):
    path = tmp_path / "nested" / "baby.sqlite3"
    memory = MemoryStore(path)
    baby = Baby(memory)
    baby.born("Alice", gender)
    baby.chat("你好")
    memory.close()
    memory = MemoryStore(path)
    try:
        baby = Baby(memory)
        assert memory.profile().name == "Alice"
        assert memory.profile().gender == gender
        assert memory.profile().address == address
        assert address in baby.greeting()
        assert memory.load_state("growth", Growth).interactions == 1
        assert "不是真实人类" in baby.chat("你是谁").text
    finally:
        memory.close()


def test_corrupt_database_preserved(tmp_path):
    path = tmp_path / "bad.sqlite3"
    original = b"not a database, preserve me"
    path.write_bytes(original)
    with pytest.raises(MemoryError):
        MemoryStore(path)
    assert path.read_bytes() == original


def test_corrupt_state_fails_without_reset(store):
    store.db.execute("INSERT INTO state VALUES('growth','{broken')")
    with pytest.raises(MemoryError):
        Baby(store)
    assert store.db.execute("SELECT value FROM state WHERE key='growth'").fetchone()[0] == "{broken"


def test_transaction_rolls_back(store):
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.learn("world", "海豚", "是", "哺乳动物")
            raise RuntimeError("interrupted")
    assert not store.facts()


def test_retrieval_ranks_exact_subject_and_is_bounded(store):
    for i in range(100):
        store.learn("world", f"动物{i}", "是", "某种动物")
    store.learn("world", "海豚", "是", "一种哺乳动物")
    assert store.retrieve("海豚是什么？", 3)[0].subject == "海豚"
    assert len(store.retrieve("动物", 3)) == 3


def test_history_is_separate_bounded_layer(store):
    for i in range(140):
        store.message("user", str(i))
    assert store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 100
    assert [m["content"] for m in store.history(2)] == ["138", "139"]


def test_consistent_backup_and_no_overwrite(baby, tmp_path):
    baby.chat("我喜欢草莓。")
    target = tmp_path / "backups" / "saved.sqlite3"
    baby.memory.backup(target)
    with pytest.raises(FileExistsError):
        baby.memory.backup(target)
    restored = MemoryStore(target)
    try:
        assert "草莓" in Baby(restored).chat("我喜欢什么？").text
    finally:
        restored.close()


def test_newer_schema_rejected(tmp_path):
    path = tmp_path / "new.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=999")
    with pytest.raises(MemoryError):
        MemoryStore(path)


def test_profile_changes_persist(baby):
    baby.change_profile(name="Alex", address="家长")
    assert baby.memory.profile().name == "Alex"
    assert "家长" in baby.greeting()


def test_concurrent_turn_is_rejected_without_partial_memory(baby):
    second = MemoryStore(baby.memory.path)
    second.db.execute("PRAGMA busy_timeout=1")
    other = Baby(second)
    try:
        with baby.memory.transaction():
            with pytest.raises(sqlite3.OperationalError):
                other.chat("我喜欢橘猫")
        assert not second.facts()
    finally:
        second.close()
