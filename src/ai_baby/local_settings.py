"""Explicit, key-free local provider files; never edit .env or the baby database."""

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config


def read_local_settings(path: Path) -> dict[str, str]:
    """Read a bounded strict allowlist. A saved local choice cannot enable a remote provider."""
    try:
        with path.open("rb") as source:
            raw = source.read(8193)
        if len(raw) > 8192:
            raise ValueError("too large")
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {"version", "provider", "base_url", "model"}:
            raise ValueError("invalid fields")
        if type(data["version"]) is not int or data["version"] != 1:
            raise ValueError("invalid version")
        if any(not isinstance(data[key], str) for key in ("provider", "base_url", "model")):
            raise ValueError("invalid types")
        if data["provider"] not in {"ollama", "local-openai"}:
            raise ValueError("invalid provider")
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise ValueError("本地模型配置格式无效；请选择设置向导保存的 JSON 文件。") from None
    return {"AI_BABY_" + key.upper(): data[key] for key in ("provider", "base_url", "model")}


def save_local_settings(config: "Config", destination: Path) -> None:
    """Exclusively create a private connection file after explicit user confirmation."""
    config.validate()
    if config.provider not in {"ollama", "local-openai"}:
        raise ValueError("这里只能保存本机模型设置。")
    payload = {
        "version": 1,
        "provider": config.provider,
        "base_url": config.base_url,
        "model": config.model,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        output = os.fdopen(descriptor, "w", encoding="utf-8")
    except BaseException:
        try:
            os.close(descriptor)
        finally:
            destination.unlink(missing_ok=True)
        raise
    try:
        with output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
