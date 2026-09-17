"""Minimal Chat Completions transport with explicit consent and no redirects."""

import json
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

    def generate(self, context: Context) -> str:
        payload = {"model": self.config.model, "messages": context.messages(), "store": False}
        request = urllib.request.Request(
            self.config.base_url + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self.config.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=self.config.timeout) as response:
                raw = response.read(1_048_577)
                if len(raw) > 1_048_576:
                    raise ProviderError("模型响应过大；本轮使用离线回复。")
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
            raise ProviderError(f"模型服务 HTTP {exc.code}；本轮使用离线回复。") from None
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
        ):
            raise ProviderError("模型服务不可用或响应格式无效；本轮使用离线回复。") from None
