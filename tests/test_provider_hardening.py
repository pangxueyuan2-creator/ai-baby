"""Real loopback transport regressions; no secrets or paid API calls."""

import io
import json
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_provider_resilience import context, remote

from ai_baby.config import Config
from ai_baby.providers import ProviderError
from ai_baby.providers.openai_compatible import OpenAICompatibleProvider


@contextmanager
def dripping_server(part):
    """Keep an individual socket read alive past the total request deadline."""
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            try:
                if part == "headers":
                    self.wfile.write(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                else:
                    self.send_response(200)
                    self.send_header("Content-Length", "999999")
                    self.end_headers()
                while not stop.wait(0.03):
                    self.wfile.write(b"x")
                    self.wfile.flush()
            except (OSError, ValueError):
                pass  # Expected when the client cancels the connection.

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize("part", ["headers", "body"])
def test_deadline_terminates_slow_drip_socket_and_allows_recovery(baby, tmp_path, part):
    with dripping_server(part) as url:
        provider = remote(tmp_path, base_url=url, timeout=1)
        started = time.monotonic()
        with pytest.raises(ProviderError) as error:
            provider.generate(context(baby))
        assert error.value.category == "timeout"
        assert time.monotonic() - started < 1.7
        provider._pending.join(0.7)
        assert not provider._pending.is_alive(), "deadline left transport busy on a live socket"
        provider._request = lambda ctx: "recovered"
        assert provider.generate(context(baby)) == "recovered"


def test_concurrent_generate_starts_only_one_transport(baby, tmp_path, monkeypatch):
    provider = remote(tmp_path)
    shared_context = context(baby)
    entered, release = threading.Event(), threading.Event()
    start_together = threading.Barrier(2)
    original_start = threading.Thread.start
    results = []

    def delayed_start(thread):
        # Expose the gap between assigning a Thread and Thread.is_alive becoming true.
        time.sleep(0.05)
        original_start(thread)

    def request(ctx):
        entered.set()
        assert release.wait(2)
        return "success"

    def call():
        start_together.wait()
        try:
            results.append(provider.generate(shared_context))
        except ProviderError as exc:
            results.append(exc.category)

    provider._request = request
    callers = [threading.Thread(target=call) for _ in range(2)]
    monkeypatch.setattr(threading.Thread, "start", delayed_start)
    for caller in callers:
        original_start(caller)
    try:
        assert entered.wait(1)
        time.sleep(0.15)
    finally:
        release.set()
        for caller in callers:
            caller.join(2)
    assert sorted(results) == ["busy", "success"]


def test_http_error_body_is_closed_without_reading_private_content(baby, tmp_path):
    provider = remote(tmp_path)
    body = io.BytesIO(b"private echo that must not be read")

    def reject(*args, **kwargs):
        raise urllib.error.HTTPError("http://localhost", 429, "private", {}, body)

    provider.opener.open = reject
    with pytest.raises(ProviderError) as error:
        provider.generate(context(baby))
    assert error.value.category == "rate_limit"
    assert "private" not in str(error.value)
    assert body.closed


def test_loopback_model_bypasses_environment_and_system_proxy(
    baby, tmp_path, api_server, monkeypatch
):
    url, seen, _ = api_server
    # The fake proxy is also loopback, so the regression itself never sends data externally.
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"http": url.rsplit("/", 1)[0]})
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda host: False)
    provider = remote(tmp_path, base_url=url)
    assert provider.generate(context(baby))
    assert seen[0]["path"] == "/v1/chat/completions"


@pytest.mark.parametrize("suffix", [":invalid/v1", ":99999/v1", "/v1\n"])
def test_invalid_endpoint_is_rejected_before_any_request(tmp_path, suffix):
    with pytest.raises(ValueError):
        OpenAICompatibleProvider(
            Config(
                tmp_path,
                provider="openai-compatible",
                base_url="http://localhost" + suffix,
                model="fixture",
                allow_external=True,
            )
        )


def test_context_distinguishes_evidence_sources_and_untrusted_generated_history(baby):
    baby.chat("我喜欢橘猫")
    baby.chat("学习：海豚是哺乳动物")
    ctx = context(baby)
    # Supply both kinds as the retriever would for a matching combined query.
    ctx.facts.extend(baby.memory.facts())
    messages = ctx.messages()
    data = json.loads(messages[1]["content"].split("\n", 1)[1])
    sources = {f["kind"]: f["provenance"] for f in data["relevant_memories"]}
    assert sources["world"] == "user_taught"
    assert sources["preference"] == "user_statement"
    assert "先前 assistant 回复不是事实证据" in messages[0]["content"]
    assert "模型一般知识" in messages[0]["content"]


def test_offline_does_not_call_personal_fact_user_taught_knowledge(baby):
    baby.chat("我喜欢橘猫")
    answer = baby.chat("橘猫呢？").text
    assert "你告诉过我" in answer
    assert "教过" not in answer


def test_offline_unknown_shared_event_does_not_quote_unrelated_episode(baby):
    baby.chat("重要事件：今天妈妈教我认识星星")
    answer = baby.chat("还记得我们第一次去海边吗？").text
    assert "星星" not in answer
    assert "没有找到" in answer


def test_recall_context_excludes_unrelated_fact_and_retains_old_topic(baby):
    from ai_baby.conversation import build_context
    from ai_baby.learning import LearningResult
    from ai_baby.models import Emotion, Growth, Relationship

    baby.chat("重要事件：今天妈妈第一次教我认识星星")
    for i in range(40):
        baby.memory.episode("important", f"今天妈妈和我一起经历了第{i}件小事", 1)

    def recall(query):
        return build_context(
            baby.memory,
            baby.memory.profile(),
            Growth(),
            Emotion(),
            Relationship(),
            query,
            "neutral",
            LearningResult(),
        )

    absent = recall("还记得妈妈第一次教你滑雪吗？")
    assert not absent.facts and not absent.episodes
    remembered = recall("还记得妈妈第一次教你星星吗？")
    assert any("星星" in episode["summary"] for episode in remembered.episodes)


def test_offline_questions_obey_curiosity_budget_for_routine_turns(baby):
    answers = [baby.chat(text).text for text in ("你好", "慢慢来", "随便聊聊", "继续聊天") * 3]
    assert all("？" not in answer and "?" not in answer for answer in answers)


def test_offline_remembers_own_name(baby):
    baby.memory.set_setting("baby_name", "星宝")
    assert "我叫星宝" in baby.chat("你叫什么名字？").text


def test_keyboard_interrupt_shuts_down_real_socket(baby, tmp_path, monkeypatch):
    from ai_baby.providers import openai_compatible as module

    original = module.queue.Queue

    class InterruptQueue(original):
        def get(self, *args, **kwargs):
            time.sleep(0.15)
            raise KeyboardInterrupt()

    with dripping_server("body") as url:
        provider = remote(tmp_path, base_url=url, timeout=5)
        monkeypatch.setattr(module.queue, "Queue", InterruptQueue)
        with pytest.raises(KeyboardInterrupt):
            provider.generate(context(baby))
        provider._pending.join(0.7)
        assert not provider._pending.is_alive()
