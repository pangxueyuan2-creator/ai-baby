"""Forgetting must suppress every supported secondary recall surface."""

import json
import os
import stat

import pytest

from ai_baby import journal, management
from ai_baby.baby import Baby
from ai_baby.memory import MemoryStore
from ai_baby.providers import BaseLLMProvider


class CaptureProvider(BaseLLMProvider):
    def generate(self, context):
        self.messages = context.messages()
        return "收到。"


def test_forget_matches_case_and_spacing_in_secondary_memory(baby, tmp_path):
    baby.chat("我喜欢ICE CREAM")
    fact_id = baby.memory.facts()[0].id
    baby.memory.episode("important", "今天我们一起聊了 ice   cream", importance=0.9)
    baby.memory.db.execute(
        "INSERT INTO curiosity VALUES('synthetic-question',NULL,'喜欢 Ice Cream 的原因？',1,'pending')"
    )
    baby.chat("我可能喜欢ice cream")
    with baby.memory.transaction():
        journal.consolidate(baby.memory, force=True)
    assert management.forget(baby.memory, fact_id)
    assert not baby.memory.retrieve("ice cream")
    assert not baby.memory.retrieve_episodes("ice cream")
    assert not baby.memory.history()
    assert not baby.memory.db.execute("SELECT 1 FROM candidates").fetchall()
    assert not baby.memory.db.execute("SELECT 1 FROM curiosity WHERE question!=''").fetchall()
    with baby.memory.transaction():
        journal.consolidate(baby.memory, force=True)
    target = tmp_path / "private-export.json"
    management.export_data(baby.memory, target)
    normalized = baby.memory.normalize(target.read_text(encoding="utf-8"))
    assert "icecream" not in normalized
    second = MemoryStore(baby.memory.path)
    try:
        provider = CaptureProvider()
        Baby(second, provider).chat("我们有什么共同经历")
        assert "icecream" not in second.normalize(json.dumps(provider.messages))
    finally:
        second.close()


def test_forgetting_revokes_receipt_instead_of_replaying_or_relearning(baby):
    baby.chat("我喜欢橘猫", turn_id="first-preference")
    assert management.forget(baby.memory, baby.memory.facts()[0].id)
    with pytest.raises(ValueError, match="遗忘|失效|撤销"):
        baby.chat("我喜欢橘猫", turn_id="first-preference")
    assert not baby.memory.facts()


def test_export_refuses_overwrite_and_symlink(baby, tmp_path):
    target = tmp_path / "protected.json"
    target.write_text("keep this file", encoding="utf-8")
    with pytest.raises(FileExistsError):
        management.export_data(baby.memory, target)
    assert target.read_text(encoding="utf-8") == "keep this file"
    link = tmp_path / "export-link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this platform")
    with pytest.raises(FileExistsError):
        management.export_data(baby.memory, link)
    assert target.read_text(encoding="utf-8") == "keep this file"


@pytest.mark.skipif(os.name == "nt", reason="Windows permissions are controlled by ACLs")
def test_export_is_private_to_owner_even_with_permissive_umask(baby, tmp_path):
    previous = os.umask(0)
    try:
        target = tmp_path / "private.json"
        management.export_data(baby.memory, target)
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    finally:
        os.umask(previous)
