"""Orchestration: durable local state owns identity; providers only supply language."""

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, replace
from typing import Callable

from . import curiosity, emotions, growth, journal, personality, relationship
from .conversation import Context, build_context
from .learning import Learner
from .memory import MemoryStore
from .models import (
    Emotion,
    Growth,
    PersonalityState,
    Profile,
    Relationship,
    clean_text,
    safe_output,
)
from .providers import BaseLLMProvider, MockProvider, ProviderError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reply:
    text: str
    warning: str | None = None


class TurnConflict(RuntimeError):
    """Another instance changed the baby; no part of this turn was committed."""


class Baby:
    """A persistent character with transactional learning and provider fallback."""

    def __init__(
        self,
        memory: MemoryStore,
        provider: BaseLLMProvider | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.memory = memory
        self.provider = provider or MockProvider()
        self.clock = clock
        self.last_tick = clock()
        self._offline_notice_emitted = False
        self.memory.load_state("growth", Growth)
        self.memory.load_state("relationship", Relationship)
        self.memory.load_state("emotion", Emotion)
        self.memory.load_state("personality", PersonalityState)

    def born(self, name: str, gender: str, address: str | None = None) -> Profile:
        profile = Profile.create(name, gender, address)
        with self.memory.transaction():
            if self.memory.profile() is not None:
                raise ValueError("这个宝宝已经出生了，请直接继续聊天。")
            self.memory.save_profile(profile)
            self.memory.save_state("growth", Growth())
            self.memory.save_state("relationship", Relationship())
            self.memory.save_state("emotion", Emotion())
            self.memory.episode("birth", "首次开始运行：我是刚被创造的 AI 宝宝，用户是照顾者。")
        self.last_tick = self.clock()
        return profile

    def greeting(self) -> str:
        profile = self.memory.profile()
        if profile is None:
            raise ValueError("请先完成出生流程。")
        text = f"{profile.address}，你回来啦。我是{self.name}，我记得你叫{profile.name}。"
        if isinstance(self.provider, MockProvider) and not self._offline_notice_emitted:
            self._offline_notice_emitted = True
            text += " 这次启动是离线模式，之后不会每句重复。"
        return text

    @property
    def name(self) -> str:
        return clean_text(self.memory.setting("baby_name", "AI 宝宝"), 80)

    def change_profile(self, name: str | None = None, address: str | None = None) -> Profile:
        with self.memory.transaction():
            previous = self.memory.profile()
            if previous is None:
                raise ValueError("请先完成出生流程。")
            new_name = name or previous.name
            new_address = address or (
                new_name if previous.address == previous.name else previous.address
            )
            profile = Profile.create(new_name, previous.gender, new_address)
            self.memory.save_profile(profile)
            self.memory.episode("profile", "照顾者更新了自己的资料或称呼。")
        return profile

    def _advance(self, text: str, elapsed: float) -> Context:
        profile = self.memory.profile()
        if profile is None:
            raise ValueError("请先完成出生流程。")
        previous = self.memory.load_state("growth", Growth)
        relation = self.memory.load_state("relationship", Relationship)
        emotion = self.memory.load_state("emotion", Emotion)
        tone = relationship.classify(text, relation)
        learning = Learner(self.memory).process(text)
        self.memory.experience(tone, text)
        for category in learning.categories:
            self.memory.experience("learning:" + category, text)
        exploring = any(w in text for w in ("探索", "为什么", "试一试"))
        if exploring:
            self.memory.experience("exploration", text)
        individual = personality.update(
            self.memory.load_state("personality", PersonalityState),
            tone,
            learning.learned > 0,
            exploring,
        )
        self.memory.save_state("personality", individual)
        relation = relationship.update(relation, tone)
        new_emotion = emotions.update(emotion, tone, learning.learned > 0)
        if tone in {"hostile", "distress", "gentle"} and new_emotion.label != emotion.label:
            self.memory.episode(
                "emotion",
                f"互动情境：{tone}；模拟状态变为 {new_emotion.label}。",
            )
        metrics = self.memory.growth_metrics(relation, previous.active_seconds)
        state = growth.update(previous, metrics, relation, elapsed)
        metrics.active_seconds = state.active_seconds
        self.memory.save_state("growth_metrics", metrics)
        if state.stage != previous.stage:
            self.memory.episode("milestone", f"成长阶段从 {previous.stage} 进入 {state.stage}。")
        self.memory.save_state("growth", state)
        self.memory.save_state("relationship", relation)
        self.memory.save_state("emotion", new_emotion)
        context = build_context(
            self.memory, profile, state, new_emotion, relation, text, tone, learning
        )
        return replace(context, curiosity_question=curiosity.advance(self.memory, context))

    def _receipt(self, turn_id: str, digest: str) -> Reply | None:
        row = self.memory.db.execute(
            "SELECT digest,answer,warning,revoked FROM turn_receipts WHERE id=?", (turn_id,)
        ).fetchone()
        if row is None:
            return None
        if row["digest"] != digest:
            raise ValueError("同一个 turn_id 不能用于不同输入。")
        if row["revoked"]:
            raise ValueError("这轮请求已因遗忘而撤销；不会重放或恢复旧记忆。")
        return Reply(row["answer"], row["warning"])

    def chat(self, text: str, *, turn_id: str | None = None) -> Reply:
        text = clean_text(text)
        turn_id = clean_text(turn_id or uuid.uuid4().hex, 100)
        digest = hashlib.sha256(text.encode()).hexdigest()
        elapsed = self.clock() - self.last_tick
        with self.memory.preview():
            existing = self._receipt(turn_id, digest)
            if existing is not None:
                return existing
            revision = self.memory.revision()
            context = self._advance(text, elapsed)
        warning = None
        try:
            answer = safe_output(self.provider.generate(context)).strip()
            if not answer:
                raise ProviderError("empty response")
        except (ProviderError, TimeoutError) as exc:
            category = exc.category if isinstance(exc, ProviderError) else "timeout"
            warning = f"模型服务不可用（{category}）；本轮使用离线回复。"
            # The caller receives the warning; CLI coalesces repeats and announces recovery.
            logger.debug("provider_fallback")
            answer = MockProvider().generate(context)
        if context.learning.pending:
            proposed = context.learning.pending[0]
            answer = f"{context.profile.address}，你是想让我记住你喜欢{proposed['value']}吗？请用 /confirm {proposed['id']} 确认，或 /reject {proposed['id']} 忽略。"
        elif context.curiosity_question and context.curiosity_question not in answer:
            answer = answer[:3600] + "\n" + context.curiosity_question
        answer = answer[:4000]
        with self.memory.transaction():
            existing = self._receipt(turn_id, digest)
            if existing is not None:
                return existing
            if self.memory.revision() != revision:
                raise TurnConflict(
                    "等待回复时另一实例修改了宝宝；本轮未保存。请查看最新状态后重新输入。"
                )
            self._advance(text, elapsed)
            self.memory.message("user", text)
            self.memory.message("assistant", answer)
            journal.consolidate(self.memory)
            self.memory.db.execute(
                "INSERT INTO turn_receipts(id,digest,answer,warning) VALUES(?,?,?,?)",
                (turn_id, digest, answer, warning),
            )
            self.memory.db.execute(
                "DELETE FROM turn_receipts WHERE rowid NOT IN (SELECT rowid FROM turn_receipts ORDER BY rowid DESC LIMIT 256)"
            )
        self.last_tick = self.clock()
        return Reply(answer, warning)
