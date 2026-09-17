"""Offline long-run character and 10k-memory acceptance checks on temporary data."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_baby.baby import Baby  # noqa: E402
from ai_baby.conversation import Context  # noqa: E402
from ai_baby.journal import consolidate  # noqa: E402
from ai_baby.management import export_data, forget  # noqa: E402
from ai_baby.memory import MemoryStore  # noqa: E402
from ai_baby.models import (  # noqa: E402
    Growth,
    GrowthMetrics,
    PersonalityState,
    Relationship,
    record,
)
from ai_baby.providers import MockProvider  # noqa: E402


class RecordingMock(MockProvider):
    """Capture bounded context for assertions; never make external requests."""

    last_context: Context | None = None

    def generate(self, context: Context) -> str:
        self.last_context = context
        return super().generate(context)


def label(index: int) -> str:
    """Distinct alphabetic synthetic labels survive the numeric-spam filter."""
    return chr(97 + index // (26 * 26) % 26) + chr(97 + index // 26 % 26) + chr(97 + index % 26)


def utterance(style: str, turn: int) -> str:
    """Fixed, reproducible experience sequences, without real personal information."""
    item = label(turn // 5)
    examples = {
        "warm": (
            "谢谢你，真棒，我们一起探索",
            f"学习：探索概念{item}是观察样本{item}。做得好",
            f"重要事件：我们一起观察星星{item}，耐心尝试。谢谢你",
            "我喜欢橘猫。慢慢来",
            "海豚和鲸鱼为什么有相似的特点",
        ),
        "reserved": (
            "谨慎一点，先观察，保持距离",
            "先别急，先观察",
            "谨慎一点",
            "我喜欢安静。先观察",
            "保持距离",
        ),
        "playful": (
            "哈哈，一起玩，开玩笑",
            f"学习：游戏概念{item}是滑稽样本{item}。哈哈",
            f"重要事件：我们一起讲月亮笑话{item}。哈哈",
            "我喜欢猜谜。一起玩",
            "你个笨蛋，哈哈开玩笑",
        ),
    }
    return examples[style][turn % 5]


def simulate_baby(directory: Path, style: str, turns: int) -> dict:
    """Exercise full preview/generate/commit turns and assert storage/state bounds."""
    path = directory / f"{style}.sqlite3"
    memory = MemoryStore(path)
    clock = [0.0]
    provider = RecordingMock()
    baby = Baby(memory, provider=provider, clock=lambda: clock[0])
    maximum_change = 0.0
    latencies: list[float] = []
    try:
        baby.born("模拟照顾者", "other", "照顾者")
        initial = record(memory.load_state("personality", PersonalityState))
        initial_relationship = record(memory.load_state("relationship", Relationship))
        for turn in range(turns):
            clock[0] += 60
            before = record(memory.load_state("personality", PersonalityState))
            relation_before = record(memory.load_state("relationship", Relationship))
            started = time.perf_counter()
            baby.chat(utterance(style, turn))
            latencies.append((time.perf_counter() - started) * 1000)
            after = record(memory.load_state("personality", PersonalityState))
            relation_after = record(memory.load_state("relationship", Relationship))
            maximum_change = max(maximum_change, *(abs(after[k] - before[k]) for k in after))
            assert maximum_change <= 0.20001
            assert all(0 <= value <= 100 for value in after.values())
            assert all(0 <= value <= 100 for value in relation_after.values())
            assert all(
                abs(relation_after[k] - relation_before[k]) <= 0.35001 for k in relation_after
            )
        context = provider.last_context
        assert context is not None
        individual = record(memory.load_state("personality", PersonalityState))
        relation = record(memory.load_state("relationship", Relationship))
        growth = record(memory.load_state("growth", Growth))
        metrics = record(memory.load_state("growth_metrics", GrowthMetrics))
        assert context.personality == memory.load_state("personality", PersonalityState)
        assert context.relationship == memory.load_state("relationship", Relationship)
        assert growth["interactions"] == turns
        assert growth["active_seconds"] == 60 * turns
        assert all(0 < value < 100 for value in individual.values())
        assert all(0 < value < 100 for value in relation.values())
        journals = memory.db.execute("SELECT summary FROM journals ORDER BY id").fetchall()
        assert len(journals) <= math.ceil(turns / 20)
        assert len({row[0] for row in journals}) == len(journals)
        assert all(len(row[0]) <= 1200 for row in journals)
        questions = memory.db.execute("SELECT topic,asked_turn,status FROM curiosity").fetchall()
        assert len(questions) <= math.ceil(turns / 8)
        assert sum(row["status"] == "pending" for row in questions) <= 3
        asked_turns = sorted(row["asked_turn"] for row in questions)
        assert all(right - left >= 8 for left, right in zip(asked_turns, asked_turns[1:]))
        assert memory.db.execute("SELECT count(*) FROM messages").fetchone()[0] <= 100
        assert memory.db.execute("SELECT count(*) FROM turn_receipts").fetchone()[0] <= 256
        assert memory.db.execute("SELECT count(*) FROM candidates").fetchone()[0] <= 3
        assert memory.db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert len(context.messages()) <= 15
        assert len(json.dumps(context.messages(), ensure_ascii=False)) < 30_000
        # Loose smoke bounds catch runaway growth without benchmarking CI hardware.
        assert path.stat().st_size < 20_000_000
        window = min(100, max(1, turns // 4))
        early = statistics.median(latencies[:window])
        late = statistics.median(latencies[-window:])
        assert late < max(100, early * 10)
        result = {
            "turns": turns,
            "initial_personality": initial,
            "initial_relationship": initial_relationship,
            "personality": individual,
            "relationship": relation,
            "growth": growth,
            "growth_metrics": metrics,
            "max_single_trait_change": round(maximum_change, 5),
            "journal_count": len(journals),
            "duplicate_journals": len(journals) - len({row[0] for row in journals}),
            "latest_journal": journals[-1][0] if journals else None,
            "curiosity_questions": len(questions),
            "context_fact_ids": [fact.id for fact in context.facts],
            "context_episodes": [episode["summary"] for episode in context.episodes],
            "context_personality": record(context.personality),
            "relevant_memories": [fact.text() for fact in memory.retrieve("我喜欢什么", 8)],
            "database_bytes": path.stat().st_size,
            "first_window_median_ms": round(early, 3),
            "last_window_median_ms": round(late, 3),
            "total_seconds": round(sum(latencies) / 1000, 3),
        }
    finally:
        memory.close()
    reopened = MemoryStore(path)
    try:
        assert record(reopened.load_state("personality", PersonalityState)) == result["personality"]
        assert record(reopened.load_state("relationship", Relationship)) == result["relationship"]
        assert record(reopened.load_state("growth", Growth)) == result["growth"]
    finally:
        reopened.close()
    return result


def compare_simulations(results: dict) -> None:
    """Assert explainable differences in multiple states and actual provider context."""
    warm, reserved, playful = (results[name] for name in ("warm", "reserved", "playful"))
    assert (
        warm["initial_personality"]
        == reserved["initial_personality"]
        == playful["initial_personality"]
    )
    assert (
        warm["initial_relationship"]
        == reserved["initial_relationship"]
        == playful["initial_relationship"]
    )
    assert warm["personality"]["confidence"] > reserved["personality"]["confidence"] + 3
    assert warm["personality"]["curiosity"] > reserved["personality"]["curiosity"] + 2
    assert reserved["personality"]["caution"] > warm["personality"]["caution"] + 3
    assert playful["personality"]["playfulness"] > warm["personality"]["playfulness"] + 5
    assert warm["relationship"]["trust"] > reserved["relationship"]["trust"] + 5
    assert playful["relationship"]["playfulness"] > warm["relationship"]["playfulness"] + 5
    assert warm["growth_metrics"]["world_knowledge"] > reserved["growth_metrics"]["world_knowledge"]
    assert (
        playful["growth_metrics"]["world_knowledge"] > reserved["growth_metrics"]["world_knowledge"]
    )
    assert warm["growth"]["score"] > reserved["growth"]["score"]
    for field in ("latest_journal", "relevant_memories", "context_personality", "context_episodes"):
        assert (
            len(
                {
                    json.dumps(item[field], ensure_ascii=False, sort_keys=True)
                    for item in results.values()
                }
            )
            == 3
        )


def stress_memory(directory: Path, records: int) -> dict:
    """Check indexed retrieval, privacy controls and bounded chat at 1k–10k scale."""
    path = directory / "memory-stress.sqlite3"
    memory = MemoryStore(path)
    try:
        baby = Baby(memory)
        baby.born("压力测试照顾者", "other")
        started = time.perf_counter()
        with memory.transaction():
            memory.learn("world", "星星", "是", "遥远的恒星")
            star = memory.facts()[0].id
            memory.episode("important", "最早的经历：第一次教我辨认星星", 0.99, fact_id=star)
            star_episode = memory.db.execute("SELECT max(id) FROM episodes").fetchone()[0]
            memory.db.execute(
                "UPDATE episodes SET created_at=datetime('now','-90 days') WHERE id=?",
                (star_episode,),
            )
            for i in range(records):
                code = label(i)
                kind = ("world", "preference", "relation", "personal")[i % 4]
                subject = "用户" if kind in {"preference", "relation"} else f"测试主体{code}"
                predicate = {
                    "world": "是",
                    "preference": "likes",
                    "relation": "朋友",
                    "personal": "职业",
                }[kind]
                memory.learn(kind, subject, predicate, f"测试记录{code}")
                memory.episode(
                    "important" if i % 50 == 0 else "learning",
                    f"练习经历{code}",
                    0.8 if i % 50 == 0 else 0.3,
                )
                memory.message("user", f"合成聊天{code}")
        insertion_seconds = time.perf_counter() - started
        timings: dict[str, list[float]] = {"facts": [], "episodes": [], "common_tokens": []}
        for _ in range(25):
            started = time.perf_counter()
            facts = memory.retrieve("星星", 8)
            timings["facts"].append((time.perf_counter() - started) * 1000)
            assert facts[0].id == star
            started = time.perf_counter()
            episodes = memory.retrieve_episodes("第一次教我辨认星星", 4)
            timings["episodes"].append((time.perf_counter() - started) * 1000)
            assert episodes[0]["id"] == star_episode
            started = time.perf_counter()
            assert len(memory.retrieve("测试记录", 8)) <= 8
            assert len(memory.retrieve_episodes("练习经历", 4)) <= 4
            timings["common_tokens"].append((time.perf_counter() - started) * 1000)
        assert max(max(values) for values in timings.values()) < 2000
        plan = [
            row[3]
            for row in memory.db.execute(
                "EXPLAIN QUERY PLAN SELECT fact_id FROM fact_tokens WHERE token=?", ("星星",)
            )
        ]
        assert any("INDEX" in step.upper() for step in plan)
        with memory.transaction():
            summary = consolidate(memory, force=True)
        assert summary is not None and len(summary) <= 1200
        baby.chat("我喜欢橘猫")
        orange = memory.facts("likes")[0].id
        assert forget(memory, orange)
        assert not any(fact.value == "橘猫" for fact in memory.retrieve("橘猫"))
        assert not any("橘猫" in episode["summary"] for episode in memory.retrieve_episodes("橘猫"))
        destination = directory / "memory-stress-export.json"
        export_data(memory, destination)
        exported = destination.read_text(encoding="utf-8")
        assert "橘猫" not in exported
        assert "api_key" not in exported
        assert memory.db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert memory.db.execute("SELECT count(*) FROM messages").fetchone()[0] <= 100
        return {
            "inserted_facts": records + 1,
            "inserted_episodes": records + 1,
            "inserted_messages": records,
            "active_facts": len(json.loads(exported)["facts"]),
            "database_bytes": path.stat().st_size,
            "export_bytes": destination.stat().st_size,
            "insertion_seconds": round(insertion_seconds, 3),
            "retrieval_median_ms": {
                name: round(statistics.median(values), 3) for name, values in timings.items()
            },
            "retrieval_max_ms": {name: round(max(values), 3) for name, values in timings.items()},
            "old_important_episode_rank": 1,
            "fact_lookup_query_plan": plan,
            "forget_export_integrity": "passed",
        }
    finally:
        memory.close()


def run(turns: int = 1000, records: int = 10_000) -> dict:
    """Run acceptance assertions and delete all synthetic databases on completion."""
    with tempfile.TemporaryDirectory(prefix="ai-baby-stress-") as directory:
        root = Path(directory)
        simulations = {
            style: simulate_baby(root, style, turns) for style in ("warm", "reserved", "playful")
        }
        compare_simulations(simulations)
        return {
            "paid_api_calls": 0,
            "simulations": simulations,
            "memory_stress": stress_memory(root, records),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=1000)
    parser.add_argument("--records", type=int, default=10_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.turns < 120 or not 1000 <= args.records <= 10_000:
        parser.error("--turns must be >=120; --records must be between 1000 and 10000")
    payload = json.dumps(run(args.turns, args.records), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
