"""No secrets, no external requests: exercise cancellation, deadlines and retry bounds."""

import threading
import time
from dataclasses import replace

import pytest

from ai_baby.config import Config
from ai_baby.conversation import build_context
from ai_baby.learning import LearningResult
from ai_baby.models import Emotion, Growth, Relationship
from ai_baby.providers import ProviderError
from ai_baby.providers.openai_compatible import OpenAICompatibleProvider


def context(baby):
    return build_context(
        baby.memory,
        baby.memory.profile(),
        Growth(),
        Emotion(),
        Relationship(),
        "你好",
        "neutral",
        LearningResult(),
    )


def remote(tmp_path, **options):
    return OpenAICompatibleProvider(
        replace(
            Config(
                tmp_path,
                provider="openai-compatible",
                base_url="http://127.0.0.1:12345/v1",
                model="fixture",
                allow_external=True,
            ),
            **options,
        )
    )


def test_local_no_key_omits_authorization(baby, tmp_path, api_server):
    url, seen, _ = api_server
    baby.provider = remote(tmp_path, base_url=url)
    assert baby.chat("你好").warning is None
    assert seen[0]["authorization"] is None


@pytest.mark.parametrize("code,expected", [(429, 3), (401, 1), (500, 1)])
def test_retry_bounded_to_explicit_rate_limit(baby, tmp_path, api_server, code, expected):
    url, seen, response = api_server
    response["status"] = code
    baby.provider = remote(tmp_path, base_url=url, max_retries=2, retry_backoff=0)
    reply = baby.chat("我喜欢草莓")
    assert reply.warning
    assert len(seen) == expected
    assert baby.memory.facts()[0].value == "草莓"


def test_rate_limit_then_success(baby, tmp_path):
    provider = remote(tmp_path, max_retries=2, retry_backoff=0.01)
    attempts = []

    def request(ctx):
        attempts.append(1)
        if len(attempts) == 1:
            raise ProviderError("rate limit", category="rate_limit", retryable=True)
        return "success"

    provider._request = request
    assert provider.generate(context(baby)) == "success"
    assert len(attempts) == 2


def test_whole_request_deadline_and_busy_worker_bound(baby, tmp_path):
    provider = remote(tmp_path, timeout=1)
    release = threading.Event()

    def request(ctx):
        release.wait(3)
        return "late response"

    provider._request = request
    baby.provider = provider
    start = time.monotonic()
    try:
        assert "timeout" in baby.chat("你好").warning
        assert time.monotonic() - start < 1.7
        assert not baby.memory.db.in_transaction
        assert "busy" in baby.chat("我喜欢草莓").warning
        assert len(baby.memory.history()) == 4
    finally:
        release.set()
        provider._pending.join(2)


def test_cancellation_prevents_retries_and_leaves_database_untouched(baby, tmp_path, monkeypatch):
    from ai_baby.providers import openai_compatible as module

    provider = remote(tmp_path, max_retries=2)
    entered, release = threading.Event(), threading.Event()
    attempts = []
    original = module.queue.Queue

    class InterruptQueue(original):
        def get(self, *args, **kwargs):
            assert entered.wait(2)
            raise KeyboardInterrupt()

    def request(ctx):
        attempts.append(1)
        entered.set()
        release.wait(3)
        raise ProviderError("rejected", category="rate_limit", retryable=True)

    monkeypatch.setattr(module.queue, "Queue", InterruptQueue)
    provider._request = request
    baby.provider = provider
    try:
        start = time.monotonic()
        with pytest.raises(KeyboardInterrupt):
            baby.chat("我喜欢草莓")
        assert time.monotonic() - start < 1
        assert baby.memory.history() == []
        assert baby.memory.facts() == []
    finally:
        release.set()
        provider._pending.join(2)
    assert len(attempts) == 1
