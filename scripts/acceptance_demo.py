"""Repeatable A–H acceptance demo. Only temporary fake-user data, no external API."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_baby.baby import Baby, TurnConflict  # noqa: E402
from ai_baby.management import export_data, forget  # noqa: E402
from ai_baby.memory import MemoryStore  # noqa: E402
from ai_baby.models import Emotion, Growth, PersonalityState, Relationship, record  # noqa: E402
from ai_baby.providers import BaseLLMProvider  # noqa: E402


def run() -> dict:
    """Assert scenarios and report bounded evidence, deleting the temporary databases."""
    results: dict = {}
    with tempfile.TemporaryDirectory(prefix="ai-baby-acceptance-") as directory:
        root = Path(directory)
        path = root / "legacy.sqlite3"
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript((ROOT / "tests/fixtures/v1.sql").read_text(encoding="utf-8"))
            db.execute(
                "INSERT INTO profile(id,name,gender,address) VALUES(1,'Alice','female','妈妈')"
            )
            db.execute(
                "INSERT INTO facts(kind,subject,predicate,value,normalized) VALUES('preference','用户','likes','草莓','草莓')"
            )
            for key, value in (
                ("growth", Growth()),
                ("relationship", Relationship()),
                ("emotion", Emotion()),
            ):
                db.execute("INSERT INTO state VALUES(?,?)", (key, json.dumps(record(value))))
            db.execute("INSERT INTO episodes(kind,summary) VALUES('birth','AI 角色首次运行')")
            db.execute("PRAGMA user_version=1")
        memory = MemoryStore(path)
        try:
            baby = Baby(memory)
            assert memory.profile().address == "妈妈"
            assert "草莓" in baby.chat("我喜欢什么？").text
            results["A"] = {
                "schema": memory.db.execute("PRAGMA user_version").fetchone()[0],
                "profile": record(memory.profile()),
                "pre_migration_backups": len(list((root / "backups").glob("pre-v1*.sqlite3"))),
            }

            class Slow(BaseLLMProvider):
                def generate(self, context):
                    assert not memory.db.in_transaction
                    other = MemoryStore(path)
                    try:
                        started = time.perf_counter()
                        with other.transaction():
                            other.set_setting("concurrent_demo", "changed")
                        results["B"] = {
                            "second_writer_ms": round((time.perf_counter() - started) * 1000, 2),
                            "provider_delay_seconds": 2,
                        }
                    finally:
                        other.close()
                    time.sleep(2)
                    return "stale answer"

            before = memory.load_state("growth", Growth).interactions
            try:
                Baby(memory, Slow()).chat("我喜欢香蕉")
                raise AssertionError("Expected conflict")
            except TurnConflict:
                results["B"]["stale_turn_rejected"] = True
            assert memory.load_state("growth", Growth).interactions == before
            assert not memory.facts("likes")[0].value == "香蕉"

            personalities = []
            maximum_change = 0.0
            for i, phrase in enumerate(
                ("谢谢你，真棒，我们一起探索", "谨慎一点，先观察，保持距离")
            ):
                store = MemoryStore(root / f"personality-{i}.sqlite3")
                try:
                    character = Baby(store)
                    character.born("Alice", "female")
                    for _ in range(200):
                        previous = record(store.load_state("personality", PersonalityState))
                        character.chat(phrase)
                        current = record(store.load_state("personality", PersonalityState))
                        maximum_change = max(
                            maximum_change, *(abs(current[k] - previous[k]) for k in current)
                        )
                    personalities.append(current)
                finally:
                    store.close()
            assert maximum_change <= 0.2
            assert personalities[0]["confidence"] - personalities[1]["confidence"] > 10
            results["C"] = {
                "turns_each": 200,
                "max_single_trait_change": round(maximum_change, 5),
                "encouraged": personalities[0],
                "reserved": personalities[1],
            }

            with memory.transaction():
                memory.episode("important", "爸爸第一次教我什么叫星星", 0.99)
                old_id = memory.db.execute("SELECT max(id) FROM episodes").fetchone()[0]
                memory.db.execute(
                    "UPDATE episodes SET created_at=datetime('now','-90 days') WHERE id=?",
                    (old_id,),
                )
                for i in range(1200):
                    memory.episode("learning", f"普通生活记录{i}", 0.3)
                    memory.learn("world", f"编号{i}", "是", f"练习{i}")
            started = time.perf_counter()
            found = memory.retrieve_episodes("你还记得第一次教你星星吗？")
            assert found[0]["id"] == old_id
            results["D"] = {
                "later_episodes": 1200,
                "old_episode_rank": 1,
                "query_ms": round((time.perf_counter() - started) * 1000, 2),
                "summary": found[0]["summary"],
            }

            baby.chat("其实我从小特别喜欢橘猫")
            baby.chat("我可能喜欢苹果")
            assert not any(f.value == "苹果" for f in memory.facts("likes"))
            pending = memory.db.execute("SELECT id FROM candidates WHERE value='苹果'").fetchone()[
                0
            ]
            baby.chat(f"确认记忆 {pending}")
            assert any(f.value == "苹果" for f in memory.facts("likes"))
            results["E"] = {
                "explicit_preference_saved": True,
                "ambiguous_waited_for_confirmation": True,
            }

            orange_id = next(f.id for f in memory.facts("likes") if f.value == "橘猫")
            assert forget(memory, orange_id)
            destination = root / "export.json"
            export_data(memory, destination)
            exported = destination.read_text(encoding="utf-8")
            assert "橘猫" not in exported and "api_key" not in exported
            reopened = MemoryStore(path)
            try:
                assert all(f.value != "橘猫" for f in reopened.facts("likes"))
            finally:
                reopened.close()
            results["F"] = {
                "forgotten_after_reopen": True,
                "export_sections": list(json.loads(exported)),
            }
            results["G"] = {"offline_reply": baby.chat("你好").text, "api_key_used": False}

            class Down(BaseLLMProvider):
                def generate(self, context):
                    raise TimeoutError()

            response = Baby(memory, Down()).chat("我喜欢西瓜")
            assert response.warning and "西瓜" in response.text
            assert memory.db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            results["H"] = {"fallback": response.warning, "database_integrity": "ok"}
        finally:
            memory.close()
    return results


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
