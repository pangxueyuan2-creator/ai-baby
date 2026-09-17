from ai_baby.emotions import update as emotion_update
from ai_baby.models import Emotion, Relationship, record
from ai_baby.relationship import classify, update


def test_familiar_teasing_and_stranger_uncertainty(baby):
    assert "不太确定" in baby.chat("你个笨蛋").text
    for _ in range(120):
        baby.chat("谢谢你，真棒")
    assert "😼" in baby.chat("你个笨蛋").text


def test_distress_and_jokes_are_not_hostility():
    state = Relationship()
    assert classify("我今天很难过", state) == "distress"
    assert classify("这个游戏真糟糕", state) == "neutral"
    assert classify("哈哈你个笨蛋，开玩笑", state) == "teasing"
    assert classify("我恨你", state) == "hostile"


def test_bounded_slow_changes():
    state = Relationship()
    for tone in ("gentle", "hostile", "teasing", "ambiguous", "distress", "neutral", "playful"):
        changed = update(state, tone)
        assert all(abs(record(changed)[k] - v) <= 0.351 for k, v in record(state).items())
    for _ in range(2000):
        state = update(state, "hostile")
    assert all(0 <= v <= 100 for v in record(state).values())


def test_emotion_moves_gradually():
    result = emotion_update(Emotion("calm", 0.2), "hostile", False)
    assert result.label == "annoyed"
    assert 0.2 < result.intensity < 0.45
