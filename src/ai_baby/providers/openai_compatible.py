"""Minimal Chat Completions transport with explicit consent and no redirects."""

import json
import threading
import urllib.request

from ..config import Config
from ..conversation import Context
from ..models import safe_output
from .base import BaseLLMProvider, ProviderError
from .transport import CancellableJSONClient
from .transport import NoRedirect as NoRedirect
from .transport import queue as queue  # Preserve the existing cancellation-test seam.


class OpenAICompatibleProvider(BaseLLMProvider):
    """Works with Chat Completions, including local and explicitly enabled remote presets."""

    def __init__(self, config: Config):
        self.config = config.validate()
        if config.provider not in {"openai-compatible", "ollama", "local-openai", "grok"}:
            raise ValueError(
                "此 provider 需要 openai-compatible、ollama、local-openai 或 grok 模式。"
            )
        self._client = CancellableJSONClient(config.timeout, loopback_only=config.is_loopback)

    @property
    def opener(self) -> urllib.request.OpenerDirector:
        """Expose the existing injectable HTTP opener for local transport tests."""
        return self._client.opener

    @property
    def _pending(self) -> threading.Thread | None:
        return self._client._pending

    def generate(self, context: Context) -> str:
        """Generate within a total deadline, with no database capability in the transport."""
        return self._client.run(lambda cancelled: self._with_retries(context, cancelled))

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
        local_preset = self.config.provider in {"ollama", "local-openai"}
        if self.config.api_key and (not local_preset or self.config.allow_local_auth):
            headers["Authorization"] = "Bearer " + self.config.api_key
        request = urllib.request.Request(
            self.config.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        data = self._client.read_json(request)
        try:
            answer = data["choices"][0]["message"]["content"]
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("empty response")
            answer = safe_output(answer).strip()
            if not answer:
                raise ValueError("invalid response")
            return answer[:4000]
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(
                "模型响应格式无效；本轮使用离线回复。", category="response"
            ) from None
