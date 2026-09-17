"""Minimal Chat Completions transport with explicit consent and no redirects."""

import http.client
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
from .transport import CancellableHTTPHandler, CancellableHTTPSHandler, SocketControl


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
        self._transport = SocketControl()
        handlers = [
            NoRedirect(),
            CancellableHTTPHandler(lambda sock: self._transport.register(sock)),
            CancellableHTTPSHandler(lambda sock: self._transport.register(sock)),
        ]
        if config.is_loopback:
            # A local-model opt-in must not silently forward memory through a system proxy.
            handlers.append(urllib.request.ProxyHandler({}))
        self.opener = urllib.request.build_opener(*handlers)
        self._pending: threading.Thread | None = None
        self._admission = threading.Lock()

    def generate(self, context: Context) -> str:
        """Poll a bounded daemon transport so Ctrl+C interrupts the caller promptly."""
        output: queue.Queue = queue.Queue(maxsize=1)
        transport = SocketControl()

        def worker() -> None:
            try:
                output.put(self._with_retries(context, transport.cancelled))
            except Exception as exc:
                # Transport never touches the database. Unexpected details stay private.
                output.put(
                    exc
                    if isinstance(exc, ProviderError)
                    else ProviderError("服务异常。", category="transport")
                )

        # Admission includes Thread.start(): is_alive() alone has a check/start race.
        with self._admission:
            if self._pending is not None and self._pending.is_alive():
                raise ProviderError("上次请求仍在结束；本轮离线。", category="busy")
            self._transport = transport
            self._pending = threading.Thread(target=worker, daemon=True)
            deadline = time.monotonic() + self.config.timeout
            try:
                self._pending.start()
            except BaseException:
                transport.cancel()
                raise
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
            transport.cancel()  # Abort slow-drip sockets as well as cancelling future retries.

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
            self.config.base_url.rstrip("/") + "/chat/completions",
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
            code = exc.code
            exc.close()
            category = {401: "auth", 403: "auth", 429: "rate_limit"}.get(code, "http")
            if 300 <= code < 400:
                category = "redirect"
            elif 500 <= code < 600:
                category = "server"
            raise ProviderError(
                f"模型服务 HTTP {code}；本轮使用离线回复。",
                category=category,
                retryable=code == 429,
            ) from None
        except TimeoutError:
            raise ProviderError("模型请求超时。", category="timeout") from None
        except urllib.error.URLError as exc:
            category = "timeout" if isinstance(exc.reason, TimeoutError) else "transport"
            raise ProviderError("模型连接失败。", category=category) from None
        except (OSError, http.client.HTTPException):
            raise ProviderError("模型连接中断。", category="transport") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(
                "模型响应格式无效；本轮使用离线回复。", category="response"
            ) from None
