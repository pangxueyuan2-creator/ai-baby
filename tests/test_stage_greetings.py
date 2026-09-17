"""Offline greetings evolve without claiming unsupported shared memories."""

import pytest

from ai_baby.models import Growth


@pytest.mark.parametrize(
    "stage,expected",
    [
        ("newborn", "今天的新鲜事"),
        ("baby", "今天的新鲜事"),
        ("child", "能找到的旧记录"),
        ("growing", "核对的旧记忆"),
        ("mature", "核对的旧记忆"),
    ],
)
def test_offline_greeting_changes_with_growth_stage(baby, stage, expected):
    with baby.memory.transaction():
        baby.memory.save_state("growth", Growth(interactions=500, stage=stage))

    reply = baby.chat("你好").text

    assert expected in reply
    assert "还记得我们" not in reply
    assert "我记得你" not in reply
