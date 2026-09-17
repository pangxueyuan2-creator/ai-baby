"""User-triggered local model discovery and selection; never install or launch software."""

import os
import shlex
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .config import Config
from .local_settings import save_local_settings
from .models import safe_output
from .providers import ProviderError
from .providers.discovery import discover_models

DEFAULT_URLS = {
    "ollama": "http://127.0.0.1:11434/v1",
    "local-openai": "http://127.0.0.1:8080/v1",
}


def _quote_argument(value: str) -> str:
    """Quote a displayed restart argument for PowerShell on Windows, POSIX sh elsewhere."""
    return "'" + value.replace("'", "''") + "'" if os.name == "nt" else shlex.quote(value)


def setup_local(
    current: Config,
    *,
    provider: str = "ollama",
    base_url: str | None = None,
    choose: bool = True,
) -> Config | None:
    """List once, require a choice, optionally save a new key-free file, then return config."""
    config = replace(
        current,
        provider=provider,
        base_url=base_url or DEFAULT_URLS[provider],
        model="discovery-only",
        api_key="",
        allow_external=False,
        allow_local_auth=False,
    ).validate()
    service = "Ollama" if provider == "ollama" else "OpenAI-compatible 本地服务"
    print(f"仅查询本机模型列表：{config.base_url}；不发送聊天或记忆。")
    try:
        models = discover_models(config.base_url, provider=provider, timeout=3.0)
    except ProviderError as exc:
        if exc.category == "transport":
            message = f"检测不到本地 {service}，请确认服务已启动、地址和端口正确。"
        elif exc.category == "timeout":
            message = f"本地 {service} 查询超时，请检查服务后重试。"
        else:
            message = f"本地 {service} 未返回可用模型列表（{exc.category}）。请检查服务协议和地址。"
        raise ValueError(message + " 本程序不会安装服务或下载模型。") from None
    print(f"检测到 {service}。")
    if not models:
        print("没有发现已经安装的模型。请在本机服务中自行安装模型；AI Baby 不会自动下载。")
        return None
    for index, model in enumerate(models, 1):
        details = []
        if model.size is not None:
            details.append(f"大小 {model.size:,} bytes")
        if model.modified_at:
            details.append("修改于 " + model.modified_at)
        if model.remote:
            details.append("服务标记为远程模型，不可在本向导启用")
        suffix = "（" + "；".join(details) + "）" if details else ""
        print(safe_output(f"{index}. {model.name}{suffix}"))
    print("模型元数据由本机服务提供；本机服务仍可能转发到云端。离线使用需在服务端禁用云功能。")
    if not choose:
        return None
    if all(model.remote for model in models):
        print("仅发现远程模型条目；本向导只能启用本地模型。")
        return None
    while True:
        choice = input("选择模型编号（q 取消）：\n> ").strip()
        if choice.lower() in {"q", "quit", "取消"}:
            print("已取消，没有更改模型或宝宝数据。")
            return None
        if not choice.isdecimal() or len(choice) > 3 or not 1 <= int(choice) <= len(models):
            print("请输入列表中的编号，或 q 取消。")
            continue
        selected = models[int(choice) - 1]
        if selected.remote:
            print("该条目被服务标记为远程模型，请选择本地模型。")
            continue
        selected_url = config.base_url.rstrip("/")
        if provider == "ollama" and not urlsplit(selected_url).path:
            # Discovery accepts the native root; generation uses the compatible API.
            selected_url += "/v1"
        config = replace(config, model=selected.name, base_url=selected_url).validate()
        break
    print(safe_output(f"本次使用：{config.model}（{config.base_url}）。宝宝仍使用原数据目录。"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = config.data_dir.expanduser().resolve() / f"local-model-{stamp}.json"
    print(safe_output(f"可保存一份新的本机连接配置：{destination}\n不包含 API key，不修改 .env。"))
    if input("保存配置？输入 y 保存，回车仅用于本次：\n> ").strip().lower() in {"y", "yes", "是"}:
        try:
            save_local_settings(config, destination)
        except OSError:
            print("本地配置未能保存；原文件未覆盖，本次仍使用所选模型。")
        else:
            shell = "PowerShell" if os.name == "nt" else "终端"
            arguments = (
                "--local-config "
                + _quote_argument(str(destination))
                + " --data-dir "
                + _quote_argument(str(config.data_dir.expanduser().resolve()))
            )
            source_launcher = ".\\start.cmd" if os.name == "nt" else "sh start.sh"
            print(
                safe_output(
                    f"已保存。下次在 {shell} 中继续使用原启动方式，并保留以下参数：\n"
                    f"已安装命令行：ai-baby {arguments}\n"
                    f"源码用户在项目目录运行：{source_launcher} {arguments}"
                )
            )
    else:
        print("未保存连接配置；现有配置文件保持原样。")
    return config
