"""Real competing connections and delayed generation, without paid API access."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from ai_baby.baby import Baby, TurnConflict
from ai_baby.memory import MemoryStore
from ai_baby.models import Growth
from ai_baby.providers import BaseLLMProvider


def test_slow_provider_releases_write_lock_and_conflict_is_atomic(baby):
    entered, release = threading.Event(), threading.Event()

    class Slow(BaseLLMProvider):
        def generate(self, context):
            entered.set()
            assert release.wait(5)
            return "a stale answer"

    def run():
        memory = MemoryStore(baby.memory.path)
        try:
            return Baby(memory, Slow()).chat("我喜欢橘猫", turn_id="slow")
        finally:
            memory.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run)
        assert entered.wait(5)
        start = time.monotonic()
        baby.chat("我喜欢草莓", turn_id="winner")
        assert time.monotonic() - start < 1.5
        assert all(f.value != "橘猫" for f in baby.memory.facts())
        release.set()
        with pytest.raises(TurnConflict):
            future.result(timeout=5)
    assert baby.memory.load_state("growth", Growth).interactions == 1
    assert len(baby.memory.history()) == 2
    assert baby.memory.db.execute("SELECT count(*) FROM turn_receipts").fetchone()[0] == 1


def test_slow_provider_waits_seconds_without_any_transaction(baby):
    class Slow(BaseLLMProvider):
        def generate(self, context):
            assert not baby.memory.db.in_transaction
            other = MemoryStore(baby.memory.path)
            try:
                with other.transaction():  # The second store can acquire a write lock now.
                    time.sleep(0.05)
                time.sleep(2)
            finally:
                other.close()
            return "done"

    baby.provider = Slow()
    assert baby.chat("你好").text == "done"
    assert len(baby.memory.history()) == 2


def test_timeout_fallback_commits_once(baby):
    class Timeout(BaseLLMProvider):
        def generate(self, context):
            assert not baby.memory.db.in_transaction
            raise TimeoutError()

    baby.provider = Timeout()
    first = baby.chat("我喜欢橘猫", turn_id="retryable-id")
    assert first.warning and "橘猫" in first.text
    assert baby.chat("我喜欢橘猫", turn_id="retryable-id") == first
    assert baby.memory.load_state("growth", Growth).interactions == 1
    assert len(baby.memory.history()) == 2
    with pytest.raises(ValueError):
        baby.chat("different", turn_id="retryable-id")


def test_keyboard_interrupt_leaves_no_partial_state(baby):
    class Cancel(BaseLLMProvider):
        def generate(self, context):
            raise KeyboardInterrupt()

    baby.provider = Cancel()
    before = baby.memory.revision()
    with pytest.raises(KeyboardInterrupt):
        baby.chat("学习：海豚是哺乳动物")
    assert baby.memory.revision() == before
    assert not baby.memory.facts()
    assert not baby.memory.db.in_transaction


def test_finalize_write_failure_rolls_back_every_layer(baby, monkeypatch):
    import sqlite3

    original = baby.memory.message
    before = baby.memory.revision()

    def fail(role, content):
        original(role, content)
        if role == "assistant":
            raise sqlite3.OperationalError("simulated full disk")

    monkeypatch.setattr(baby.memory, "message", fail)
    with pytest.raises(sqlite3.OperationalError):
        baby.chat("我喜欢橘猫")
    assert baby.memory.revision() == before
    assert not baby.memory.history()
    assert not baby.memory.facts()
    assert baby.memory.load_state("growth", Growth).interactions == 0


def test_concurrent_same_request_commits_only_one_turn(baby):
    rendezvous = threading.Barrier(2)

    class Simultaneous(BaseLLMProvider):
        def generate(self, context):
            rendezvous.wait(timeout=5)
            return "shared answer"

    def run():
        memory = MemoryStore(baby.memory.path)
        try:
            return Baby(memory, Simultaneous()).chat("我喜欢橘猫", turn_id="shared-id")
        finally:
            memory.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        replies = list(executor.map(lambda _: run(), range(2)))
    assert replies[0] == replies[1]
    assert baby.memory.load_state("growth", Growth).interactions == 1
    assert len(baby.memory.history()) == 2
    assert len(baby.memory.facts()) == 1


def test_process_exit_during_generation_has_no_durable_preview(baby):
    import os
    import subprocess
    import sys
    from pathlib import Path

    revision = baby.memory.revision()
    script = """
import os, sys
from pathlib import Path
from ai_baby.baby import Baby
from ai_baby.memory import MemoryStore
from ai_baby.providers import BaseLLMProvider
class Crash(BaseLLMProvider):
    def generate(self, context):
        os._exit(24)
Baby(MemoryStore(Path(sys.argv[1])), Crash()).chat('我喜欢橘猫', turn_id='crashed')
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    result = subprocess.run(
        [sys.executable, "-c", script, str(baby.memory.path)], env=env, timeout=15
    )
    assert result.returncode == 24
    assert baby.memory.revision() == revision
    assert not baby.memory.history()
    assert not baby.memory.facts()
    assert baby.memory.load_state("growth", Growth).interactions == 0
    assert baby.memory.db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
