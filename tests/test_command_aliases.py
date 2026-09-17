"""Chinese slash-command aliases preserve the same validated local command paths."""

import pytest

from ai_baby.main import command


def test_chinese_status_alias_prints_growth(capsys, baby):
    assert command(baby, "/状态") is True
    output = capsys.readouterr().out
    assert "growth" in output
    assert "relationship" in output


def test_chinese_profile_and_name_aliases(capsys, baby):
    assert command(baby, "/名字 小渊") is True
    assert command(baby, "/称呼 家长") is True
    assert command(baby, "/资料") is True
    output = capsys.readouterr().out
    assert "小渊" in output
    assert "家长" in output


def test_chinese_memory_alias_preserves_all_pagination_argument(capsys, baby):
    baby.chat("我喜欢草莓。")
    assert command(baby, "/记忆 --all") is True
    assert "草莓" in capsys.readouterr().out


def test_chinese_id_alias_uses_same_signed_64_bit_validation(baby):
    with pytest.raises(ValueError):
        command(baby, "/遗忘 9223372036854775808")
