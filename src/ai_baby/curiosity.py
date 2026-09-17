"""Sparse optional questions; ignoring one never reduces trust."""

import hashlib

from .conversation import Context
from .memory import MemoryStore


def advance(memory: MemoryStore, context: Context) -> str | None:
    """Keep at most three pending questions; durable hashes prevent re-asking."""
    pending = memory.db.execute(
        "SELECT topic FROM curiosity WHERE status='pending' ORDER BY asked_turn DESC LIMIT 1"
    ).fetchone()
    if pending and context.user_text.startswith(("因为", "回答：", "回答:")):
        memory.db.execute(
            "UPDATE curiosity SET status='answered',question='' WHERE topic=?", (pending[0],)
        )
    if pending and any(w in context.user_text for w in ("不想回答", "跳过问题")):
        memory.db.execute(
            "UPDATE curiosity SET status='ignored',question='' WHERE topic=?", (pending[0],)
        )
    turn = context.growth.interactions
    last = int(memory.setting("curiosity_turn", "-2"))
    if (
        turn < 6
        or turn - last < 8
        or context.learning.pending
        or context.personality.curiosity < 55
        or context.tone in {"hostile", "distress", "reserved"}
    ):
        return None
    for fact_id in context.learning.fact_ids:
        fact = memory.db.execute(
            "SELECT kind,subject,predicate,value FROM facts WHERE id=? AND active=1", (fact_id,)
        ).fetchone()
        if fact is None or fact["kind"] not in {"world", "preference"}:
            continue
        topic = hashlib.sha256(
            (fact["subject"] + fact["predicate"] + memory.normalize(fact["value"])).encode()
        ).hexdigest()
        if memory.db.execute("SELECT 1 FROM curiosity WHERE topic=?", (topic,)).fetchone():
            continue
        if context.growth.stage in {"newborn", "baby"}:
            question = (
                f"为什么你{'不喜欢' if fact['predicate'] == 'dislikes' else '喜欢'}{fact['value'][:60]}呀？"
                if fact["kind"] == "preference"
                else f"可以再举一个关于{fact['subject'][:60]}的小例子吗？"
            )
        else:
            question = f"关于{fact['value'][:60] if fact['kind'] == 'preference' else fact['subject'][:60]}，这和我们以前学过的事情有什么联系？你的看法有变化吗？"
        memory.db.execute(
            "INSERT INTO curiosity VALUES(?,?,?,?,'pending')", (topic, fact_id, question, turn)
        )
        memory.db.execute(
            "UPDATE curiosity SET status='ignored',question='' WHERE status='pending' AND topic NOT IN (SELECT topic FROM curiosity WHERE status='pending' ORDER BY asked_turn DESC LIMIT 3)"
        )
        memory.set_setting("curiosity_turn", str(turn))
        return question
    return None
