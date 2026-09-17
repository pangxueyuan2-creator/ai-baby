"""Chinese slash-command aliases stay local and do not change stored identity."""

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
