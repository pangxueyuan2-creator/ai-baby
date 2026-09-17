"""Orchestration: durable local state owns identity; providers only supply language."""

import logging
import time
from dataclasses import dataclass
from typing import Callable

from . import emotions, growth, relationship
from .conversation import build_context
from .learning import Learner
from .memory import MemoryStore
from .models import Emotion, Growth, Profile, Relationship, clean_text, safe_output
from .providers import BaseLLMProvider, MockProvider, ProviderError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reply:
    text: str
    warning: str | None = None


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
        # Validate persisted state at startup instead of crashing mid-conversation.
        self.memory.load_state("growth", Growth)
        self.memory.load_state("relationship", Relationship)
        self.memory.load_state("emotion", Emotion)

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
        return f"{profile.address}，你回来啦。我记得你叫{profile.name}。"

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

    def chat(self, text: str) -> Reply:
        text = clean_text(text)
        now = self.clock()
        warning = None
        with self.memory.transaction():
            profile = self.memory.profile()
            if profile is None:
                raise ValueError("请先完成出生流程。")
            previous = self.memory.load_state("growth", Growth)
            relation = self.memory.load_state("relationship", Relationship)
            emotion = self.memory.load_state("emotion", Emotion)
            tone = relationship.classify(text, relation)
            learning = Learner(self.memory).process(text)
            relation = relationship.update(relation, tone)
            new_emotion = emotions.update(emotion, tone, learning.learned > 0)
            if tone in {"hostile", "distress", "gentle"} and new_emotion.label != emotion.label:
                self.memory.episode(
                    "emotion",
                    f"互动情境：{tone}；模拟状态变为 {new_emotion.label}。用户说：{text[:180]}",
                )
            state = growth.update(previous, self.memory.counts(), relation, now - self.last_tick)
            if state.stage != previous.stage:
                self.memory.episode(
                    "milestone", f"成长阶段从 {previous.stage} 进入 {state.stage}。"
                )
            context = build_context(
                self.memory, profile, state, new_emotion, relation, text, tone, learning
            )
            try:
                answer = safe_output(self.provider.generate(context)).strip()
                if not answer:
                    raise ProviderError("模型回复为空；本轮使用离线回复。")
            except ProviderError as exc:
                warning = str(exc)
                logger.warning("provider_fallback")
                answer = MockProvider().generate(context)
            self.memory.message("user", text)
            self.memory.message("assistant", answer[:4000])
            self.memory.save_state("growth", state)
            self.memory.save_state("relationship", relation)
            self.memory.save_state("emotion", new_emotion)
        self.last_tick = self.clock()
        return Reply(answer[:4000], warning)
