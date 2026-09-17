"""Regression tests for forgotten historical facts and failed export finalization."""

import json
import os

import pytest
from test_config_cli import cli
from test_forget_privacy import CaptureProvider

from ai_baby import journal, management
from ai_baby.baby import Baby
from ai_baby.memory import MemoryStore


def test_superseded_fact_can_be_forgotten_across_all_recall_surfaces(baby, tmp_path):
    baby.chat("我住在杭州", turn_id="old-address")
    old_id = baby.memory.facts()[0].id
    with baby.memory.transaction():
        journal.consolidate(baby.memory, force=True)
    baby.chat("我住在苏州")
    baby.memory.episode("important", "我们聊起了杭州的旧居", importance=0.9)
    old = baby.memory.db.execute("SELECT active FROM facts WHERE id=?", (old_id,)).fetchone()
    assert old[0] == 0
    assert "杭州" in json.dumps(baby.memory.history(), ensure_ascii=False)

    assert management.forget(baby.memory, old_id)
    assert [fact.value for fact in baby.memory.facts()] == ["苏州"]
    assert all("杭州" not in event["summary"] for event in baby.memory.retrieve_episodes("杭州"))
    assert not baby.memory.history()
    assert not journal.recent(baby.memory)
    with pytest.raises(ValueError, match="撤销"):
        baby.chat("我住在杭州", turn_id="old-address")

    target = tmp_path / "export.json"
    management.export_data(baby.memory, target)
    assert "杭州" not in target.read_text(encoding="utf-8")
    reopened = MemoryStore(baby.memory.path)
    try:
        provider = CaptureProvider()
        Baby(reopened, provider).chat("你还记得我的旧居吗")
        assert "杭州" not in json.dumps(provider.messages, ensure_ascii=False)
        assert [fact.value for fact in reopened.facts()] == ["苏州"]
    finally:
        reopened.close()


def test_empty_normalized_fact_does_not_match_every_episode(baby):
    baby.memory.learn("knowledge", "标点", "内容", ".")
    fact_id = baby.memory.facts()[0].id
    baby.memory.episode("learning", "标点内容", fact_id=fact_id)
    baby.memory.episode("important", "一起认识星星", importance=0.9)
    baby.memory.db.execute("INSERT INTO curiosity VALUES('stars',NULL,'星星是什么',1,'pending')")
    assert management.forget(baby.memory, fact_id)
    assert any("星星" in event["summary"] for event in baby.memory.episodes())
    question = baby.memory.db.execute(
        "SELECT question FROM curiosity WHERE topic='stars'"
    ).fetchone()
    assert question[0] == "星星是什么"
    assert not baby.memory.db.execute(
        "SELECT 1 FROM episodes WHERE fact_id=? AND active=1", (fact_id,)
    ).fetchone()


def test_failed_export_close_removes_our_partial_file(baby, tmp_path, monkeypatch):
    target = tmp_path / "failed-export.json"
    fdopen = os.fdopen

    class FailOnClose:
        def __init__(self, descriptor, *args, **kwargs):
            self.output = fdopen(descriptor, *args, **kwargs)

        def __enter__(self):
            return self.output

        def __exit__(self, *exc):
            self.output.close()
            raise OSError("simulated buffered close failure")

    monkeypatch.setattr(management.os, "fdopen", FailOnClose)
    with pytest.raises(OSError, match="buffered close"):
        management.export_data(baby.memory, target)
    assert not target.exists()
    assert baby.memory.profile().name == "Alice"
    assert not baby.memory.db.in_transaction


def test_failed_export_stream_creation_closes_descriptor(baby, tmp_path, monkeypatch):
    target = tmp_path / "failed-open.json"
    descriptors = []

    def fail_open(descriptor, *args, **kwargs):
        descriptors.append(descriptor)
        raise OSError("simulated fdopen failure")

    monkeypatch.setattr(management.os, "fdopen", fail_open)
    try:
        with pytest.raises(OSError, match="fdopen failure"):
            management.export_data(baby.memory, target)
        assert not target.exists()
        with pytest.raises(OSError):
            os.fstat(descriptors[0])
    finally:
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass


@pytest.mark.parametrize(
    "value",
    [str(2**63), "9" * 100, "9" * 1900],
    ids=["sqlite-overflow", "100-digits", "1900-digits"],
)
def test_natural_confirmation_rejects_oversized_id_without_mutation(baby, value):
    baby.chat("我可能喜欢橘猫")
    revision = baby.memory.revision()
    with pytest.raises(ValueError, match="记忆 ID"):
        baby.chat("确认记忆 " + value)
    assert baby.memory.revision() == revision
    assert not baby.memory.db.in_transaction
    assert not baby.memory.facts()
    assert baby.memory.db.execute("SELECT count(*) FROM candidates").fetchone()[0] == 1


@pytest.mark.parametrize("value", [True, 1.0, 0, -1, 2**63])
def test_forget_rejects_invalid_id_without_mutation(baby, value):
    baby.chat("我喜欢草莓")
    revision = baby.memory.revision()
    with pytest.raises(ValueError, match="记忆 ID"):
        management.forget(baby.memory, value)
    assert baby.memory.revision() == revision
    assert baby.memory.facts()[0].value == "草莓"


def test_unknown_forget_id_leaves_all_state_intact(baby):
    baby.chat("我喜欢草莓")
    revision = baby.memory.revision()
    assert management.forget(baby.memory, 2**63 - 1) is False
    assert baby.memory.revision() == revision
    assert baby.memory.history()


def test_cli_survives_oversized_natural_confirmation(tmp_path):
    result = cli(tmp_path, f"Alice\n2\n\n确认记忆 {2**63}\n你好\n/quit\n")
    assert result.returncode == 0, result.stderr
    assert "正整数记忆 ID" in result.stdout
    assert "妈妈你好" in result.stdout
    assert "Traceback" not in result.stderr


def test_archived_memory_pages_allow_discovering_superseded_ids(baby):
    for number in range(25):
        baby.memory.learn("personal", "用户", "居住地", f"测试城市{number}")
    first = management.memory_page(baby.memory)
    second = management.memory_page(baby.memory, first[-1]["id"])
    assert len(first) == 20 and len(second) == 5
    assert {row["id"] for row in first}.isdisjoint(row["id"] for row in second)
    assert sum(row["active"] for row in first + second) == 1
    assert second[-1]["value"] == "测试城市0"
    assert management.forget(baby.memory, second[-1]["id"])
    assert baby.memory.facts()[0].value == "测试城市24"


def test_cli_can_inspect_and_forget_a_superseded_fact(tmp_path):
    first = cli(tmp_path, "Alice\n2\n\n我住在杭州\n我住在苏州\n/quit\n")
    assert first.returncode == 0
    result = cli(tmp_path, "/memories --all\n/forget 1\n/export\n/quit\n")
    assert result.returncode == 0, result.stderr
    assert "#1 [已失效]" in result.stdout and "杭州" in result.stdout
    assert "记忆已失效" in result.stdout
    (target,) = (tmp_path / "memory" / "exports").glob("*.json")
    assert "杭州" not in target.read_text(encoding="utf-8")
    assert "苏州" in target.read_text(encoding="utf-8")


def test_positive_confirmation_still_works_with_leading_zeroes(baby):
    baby.chat("我可能喜欢橘猫")
    candidate_id = baby.memory.db.execute("SELECT id FROM candidates").fetchone()[0]
    baby.chat(f"确认记忆 000{candidate_id}")
    assert baby.memory.facts()[0].value == "橘猫"


def test_failed_export_body_removes_only_new_file(baby, tmp_path, monkeypatch):
    target = tmp_path / "failed-body.json"

    def fail_dump(payload, output, **kwargs):
        output.write("partial")
        raise OSError("simulated write failure")

    monkeypatch.setattr(management.json, "dump", fail_dump)
    with pytest.raises(OSError, match="write failure"):
        management.export_data(baby.memory, target)
    assert not target.exists()
    assert baby.memory.profile().name == "Alice"
