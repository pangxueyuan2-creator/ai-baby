"""Temporary stores only: tests never touch the user's baby or API credentials."""

import pytest

from ai_baby.baby import Baby
from ai_baby.memory import MemoryStore


@pytest.fixture
def store(tmp_path):
    memory = MemoryStore(tmp_path / "baby.sqlite3")
    yield memory
    memory.close()


@pytest.fixture
def baby(store):
    result = Baby(store)
    result.born("Alice", "female")
    return result
