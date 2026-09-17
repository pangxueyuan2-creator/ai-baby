"""Explicit provider opt-in and a deliberately small .env reader."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def read_env(path: Path) -> dict[str, str]:
    """Read KEY=value without executing/interpolating text or changing os.environ."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip().replace("_", "").isalnum():
            raise ValueError(".env 格式错误：需要 KEY=value。")
        values[key.strip()] = value.strip().strip("\"'")
    return values


@dataclass(frozen=True)
class Config:
    data_dir: Path
    provider: str = "mock"
    api_key: str = field(default="", repr=False)
    base_url: str = "https://api.openai.com/v1"
    model: str = ""
    timeout: float = 30.0
    allow_external: bool = False
    max_retries: int = 0
    retry_backoff: float = 0.25

    def validate(self) -> "Config":
        """Validate before any data is sent to an external provider."""
        if self.provider not in {"mock", "openai-compatible"}:
            raise ValueError("未知 provider；请选择 mock 或 openai-compatible。")
        if not 1 <= self.timeout <= 120:
            raise ValueError("超时时间必须在 1–120 秒之间。")
        if self.max_retries not in {0, 1, 2} or not 0 <= self.retry_backoff <= 2:
            raise ValueError("重试次数必须在 0–2，退避时间必须在 0–2 秒。")
        if self.provider == "openai-compatible":
            if not self.allow_external:
                raise ValueError("外部模式需显式设置 AI_BABY_ALLOW_EXTERNAL=true。")
            url = urlsplit(self.base_url)
            local = url.hostname in {"localhost", "127.0.0.1", "::1"}
            if not url.hostname or (url.scheme != "https" and not (local and url.scheme == "http")):
                raise ValueError("API 地址需要 HTTPS；仅回环本地服务允许 HTTP。")
            if url.username or url.password or url.query or url.fragment:
                raise ValueError("API 地址不能包含凭据、查询串或片段。")
            if not self.model.strip() or (not local and not self.api_key.strip()):
                raise ValueError("外部模式需要 AI_BABY_MODEL 和 AI_BABY_API_KEY。")
            if any(ord(c) < 32 or ord(c) == 127 for c in self.api_key):
                raise ValueError("API key 格式无效。")
        return self

    @classmethod
    def load(cls, data_dir: Path | None = None, env_file: Path | None = None) -> "Config":
        """Environment overrides the chosen .env file. Mock remains the default."""
        values = read_env(env_file or Path.cwd() / ".env") | dict(os.environ)
        return cls(
            data_dir=data_dir
            or Path(values.get("AI_BABY_DATA_DIR", str(Path.home() / ".ai-baby"))).expanduser(),
            provider=values.get("AI_BABY_PROVIDER", "mock"),
            api_key=values.get("AI_BABY_API_KEY", ""),
            base_url=values.get("AI_BABY_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            model=values.get("AI_BABY_MODEL", ""),
            timeout=float(values.get("AI_BABY_TIMEOUT", "30")),
            allow_external=values.get("AI_BABY_ALLOW_EXTERNAL", "false").lower() == "true",
            max_retries=int(values.get("AI_BABY_MAX_RETRIES", "0")),
            retry_backoff=float(values.get("AI_BABY_RETRY_BACKOFF", "0.25")),
        ).validate()
