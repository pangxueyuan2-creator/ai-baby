import pytest

from ai_baby.baby import Baby
from ai_baby.learning import is_coarser_place
from ai_baby.memory import MemoryStore


@pytest.mark.parametrize(
    "previous,incoming,correction",
    [
        ("北京", "浙江", "我现在住浙江。"),
        ("宁波", "杭州", "我现在住杭州。"),
        ("浙江宁波", "杭州", "我现在住杭州。"),
        ("Paris", "浙江", "我现在住浙江。"),
        ("杭州", "浙江", "我不住杭州了。我现在住浙江。"),
        ("杭州", "浙江", "我现在不住在杭州了，我现在住浙江。"),
        ("杭州西湖", "杭州", "我已经不再住在杭州西湖了。我住在杭州。"),
        ("杭州", "浙江", "我以前住杭州，现在住浙江。"),
        ("杭州西湖", "杭州", "我曾经住在杭州西湖。我现在住杭州。"),
    ],
)
def test_residence_correction_survives_restart(baby, previous, incoming, correction):
    baby.chat(f"我住在{previous}。")
    old_fact = baby.memory.facts("居住地")[0]
    reply = baby.chat(correction).text

    assert f"改成{incoming}" in reply
    assert [fact.value for fact in baby.memory.facts("居住地")] == [incoming]
    assert (
        baby.memory.db.execute("SELECT active FROM facts WHERE id=?", (old_fact.id,)).fetchone()[0]
        == 0
    )
    assert not baby.memory.db.execute(
        "SELECT id FROM episodes WHERE fact_id=? AND active=1", (old_fact.id,)
    ).fetchall()

    path = baby.memory.path
    baby.memory.close()
    restored = MemoryStore(path)
    try:
        answer = Baby(restored).chat("我住在哪里？").text
        assert incoming in answer
        assert previous not in answer
        assert [fact.value for fact in restored.facts("居住地")] == [incoming]
    finally:
        restored.close()


@pytest.mark.parametrize(
    "previous,incoming",
    [
        ("杭州", "浙江"),
        ("杭州西湖", "浙江"),
        ("杭州西湖", "杭州"),
        ("西湖", "杭州"),
        ("宁波", "浙江"),
        ("浙江省杭州市", "浙江"),
    ],
)
def test_actual_broader_region_preserves_specific_residence(baby, previous, incoming):
    baby.chat(f"我住在{previous}。")
    old_fact = baby.memory.facts("居住地")[0]
    reply = baby.chat(f"我住在{incoming}。").text

    assert "更具体" in reply
    assert previous in reply
    assert baby.memory.facts("居住地") == [old_fact]
    assert previous in baby.chat("我住在哪里？").text


def test_same_or_empty_residence_is_not_a_broader_region():
    assert not is_coarser_place("杭州", " 杭州。")
    assert not is_coarser_place("", "杭州西湖")


@pytest.mark.parametrize(
    "statement",
    [
        "我不住杭州了吗？我住在浙江。",
        "“我不住杭州了”。我住在浙江。",
        "“这是引用。我不住杭州了。引用结束”。我住在浙江。",
        "'这是引用。我不住杭州了。引用结束'。我住在浙江。",
        "如果我不住杭州了。我住在浙江。",
        "假设一个场景。我不住杭州了。场景结束。我住在浙江。",
        "他说了几句话。我不住杭州了。讲完了。我住在浙江。",
        "“这是引用。我以前住杭州。引用结束”。我住在浙江。",
        "我可能不住杭州了。我住在浙江。",
        "不是说我不住杭州了。我住在浙江。",
        "我不住宁波了。我住在浙江。",
        "我不住杭州了。我现在住哪里？",
        "我不住杭州了。我可能住浙江。",
        "我不住杭州了。",
    ],
)
def test_only_explicit_matching_retraction_with_new_fact_can_replace_residence(baby, statement):
    baby.chat("我住在杭州。")
    old_fact = baby.memory.facts("居住地")[0]

    baby.chat(statement)

    assert baby.memory.facts("居住地") == [old_fact]
    assert baby.memory.db.execute(
        "SELECT id FROM episodes WHERE fact_id=? AND active=1", (old_fact.id,)
    ).fetchall()


def test_residence_retraction_is_not_carried_into_later_turns(baby):
    baby.chat("我住在杭州。")
    baby.chat("我不住杭州了。")
    reply = baby.chat("我住在浙江。").text

    assert "更具体" in reply
    assert [fact.value for fact in baby.memory.facts("居住地")] == ["杭州"]
