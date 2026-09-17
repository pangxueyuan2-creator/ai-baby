"""Minimal Chat Completions transport with explicit consent and no redirects."""

import json
import queue
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from ..config import Config
from ..conversation import Context
from ..models import safe_output
from .base import BaseLLMProvider, ProviderError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        """Do not forward private context or authorization to redirect targets."""
        return None


class OpenAICompatibleProvider(BaseLLMProvider):
    """Works with services implementing POST /chat/completions; no SDK dependency."""

    def __init__(self, config: Config):
        self.config = config.validate()
        if config.provider != "openai-compatible":
            raise ValueError("此 provider 需要显式启用外部模式。")
        self.opener = urllib.request.build_opener(NoRedirect())
        self._pending: threading.Thread | None = None

    def generate(self, context: Context) -> str:
        """Poll a bounded daemon transport so Ctrl+C interrupts the caller promptly."""
        if self._pending is not None and self._pending.is_alive():
            raise ProviderError("上次请求仍在结束；本轮离线。", category="busy")
        output: queue.Queue = queue.Queue(maxsize=1)
        cancelled = threading.Event()

        def worker() -> None:
            try:
                output.put(self._with_retries(context, cancelled))
            except Exception as exc:
                # Transport never touches the database. Unexpected details stay private.
                output.put(
                    exc
                    if isinstance(exc, ProviderError)
                    else ProviderError("服务异常。", category="transport")
                )

        self._pending = threading.Thread(target=worker, daemon=True)
        self._pending.start()
        deadline = time.monotonic() + self.config.timeout
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderError("模型请求超时。", category="timeout")
                try:
                    result = output.get(timeout=min(0.05, remaining))
                    if isinstance(result, ProviderError):
                        raise result
                    return result
                except queue.Empty:
                    continue
        finally:
            cancelled.set()  # Never schedule another request after caller cancellation/deadline.

    def _with_retries(self, context: Context, cancelled: threading.Event) -> str:
        """Retry only explicit rate-limit rejection, never ambiguous timeout/network errors."""
        for attempt in range(self.config.max_retries + 1):
            if cancelled.is_set():
                raise ProviderError("请求已取消。", category="cancelled")
            try:
                return self._request(context)
            except ProviderError as exc:
                if not exc.retryable or attempt >= self.config.max_retries:
                    raise
                if cancelled.wait(min(2, self.config.retry_backoff * (2**attempt))):
                    raise ProviderError("请求已取消。", category="cancelled") from None
        raise AssertionError("unreachable")

    def _request(self, context: Context) -> str:
        payload = {"model": self.config.model, "messages": context.messages(), "store": False}
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = "Bearer " + self.config.api_key
        request = urllib.request.Request(
            self.config.base_url + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=self.config.timeout) as response:
                raw = response.read(1_048_577)
                if len(raw) > 1_048_576:
                    raise ProviderError("模型响应过大；本轮使用离线回复。", category="response")
            data = json.loads(raw)
            answer = data["choices"][0]["message"]["content"]
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("empty response")
            answer = safe_output(answer).strip()
            if not answer:
                raise ValueError("invalid response")
            return answer[:4000]
        except urllib.error.HTTPError as exc:
            # Never include exception bodies: they can echo user messages or credentials.
            category = {401: "auth", 403: "auth", 429: "rate_limit"}.get(exc.code, "http")
            raise ProviderError(
                f"模型服务 HTTP {exc.code}；本轮使用离线回复。",
                category=category,
                retryable=exc.code == 429,
            ) from None
        except TimeoutError:
            raise ProviderError("模型请求超时。", category="timeout") from None
        except (
            urllib.error.URLError,
            OSError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
        ):
            raise ProviderError(
                "模型服务不可用或响应格式无效；本轮使用离线回复。", category="transport_or_response"
            ) from None
