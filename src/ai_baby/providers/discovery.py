"""Explicit, metadata-only discovery of models exposed by a trusted loopback server."""

import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..models import clean_text
from .base import ProviderError
from .transport import CancellableJSONClient

MAX_MODELS = 100


@dataclass(frozen=True)
class LocalModel:
    """Reported metadata, not proof that a local server never forwards to another service."""

    name: str
    size: int | None
    modified_at: str | None
    remote: bool = False


def _discovery_url(base_url: str, provider: str) -> str:
    """Validate independently of model/key configuration and never resolve a hostname."""
    if provider not in {"ollama", "local-openai"}:
        raise ValueError("模型发现只支持 ollama 或 local-openai。")
    if (
        not isinstance(base_url, str)
        or not base_url
        or len(base_url) > 2048
        or any(ord(c) <= 32 or 127 <= ord(c) <= 159 for c in base_url)
    ):
        raise ValueError("本地模型地址格式无效。")
    try:
        url = urlsplit(base_url)
        port = url.port
    except ValueError:
        raise ValueError("本地模型地址或端口格式无效。") from None
    if (
        url.scheme not in {"http", "https"}
        or url.hostname not in {"localhost", "127.0.0.1", "::1"}
        or port == 0
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
    ):
        raise ValueError("模型发现仅支持无凭据、查询串或片段的本机回环 HTTP(S) 地址。")
    path = url.path.rstrip("/")
    if provider == "ollama":
        if path not in {"", "/v1"}:
            raise ValueError("Ollama 模型发现只支持根地址或 /v1 前缀；它读取 /api/tags。")
        path = "/api/tags"
    else:
        path += "/models"
    return urlunsplit((url.scheme, url.netloc, path, "", ""))


def _optional_text(value: Any, maximum: int, *, allow_empty: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("invalid model metadata")
    if allow_empty and value == "":
        return value
    return clean_text(value, maximum)


def _parse_models(data: Any, provider: str) -> list[LocalModel]:
    """Reject ambiguous, oversized or unsafe catalogs rather than silently select a model."""
    try:
        key = "models" if provider == "ollama" else "data"
        if not isinstance(data, dict) or not isinstance(data.get(key), list):
            raise ValueError("invalid model list")
        rows = data[key]
        if len(rows) > MAX_MODELS:
            raise ValueError("too many models")
        result = []
        names = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("invalid model entry")
            name = row.get("name" if provider == "ollama" else "id")
            if not isinstance(name, str):
                raise ValueError("invalid model name")
            name = clean_text(name, 200)
            if name in names:
                raise ValueError("duplicate model name")
            names.add(name)
            size = row.get("size")
            if size is not None and (
                isinstance(size, bool) or not isinstance(size, int) or not 0 <= size < 2**63
            ):
                raise ValueError("invalid model size")
            modified_at = _optional_text(row.get("modified_at"), 100)
            remote_model = _optional_text(row.get("remote_model"), 500, allow_empty=True)
            remote_host = _optional_text(row.get("remote_host"), 500, allow_empty=True)
            result.append(LocalModel(name, size, modified_at, bool(remote_model or remote_host)))
        return result
    except (ValueError, TypeError):
        raise ProviderError(
            "模型列表格式无效、存在重复标识或超过 100 条限制。", category="response"
        ) from None


def discover_models(
    base_url: str, *, provider: str = "ollama", timeout: float = 3.0
) -> list[LocalModel]:
    """GET metadata only when called; never infer, download, authenticate or read user memory."""
    url = _discovery_url(base_url, provider)
    client = CancellableJSONClient(timeout, loopback_only=True)
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    data = client.run(lambda cancelled: client.read_json(request))
    return _parse_models(data, provider)
