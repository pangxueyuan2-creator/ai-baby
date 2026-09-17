"""CLI-only outage notices: retain provider errors without repeating long warnings."""

from dataclasses import dataclass


@dataclass
class ProviderNotices:
    provider: str
    previous: str | None = None
    repeats: int = 0

    def observe(self, warning: str | None) -> str | None:
        """Show new failures, every tenth repeat, and recovery; do not alter requests."""
        if warning is None:
            recovered = self.previous is not None
            self.previous, self.repeats = None, 0
            return "模型服务已恢复，本轮已使用所选模型。" if recovered else None
        if warning == self.previous:
            self.repeats += 1
            return "模型仍不可用，继续使用基础离线回复。" if self.repeats % 10 == 0 else None
        self.previous, self.repeats = warning, 0
        if self.provider in {"ollama", "local-openai"}:
            service = "Ollama" if self.provider == "ollama" else "推理"
            return (
                warning
                + f" 请确认本地 {service} 服务已启动，端口和模型正确；"
                + "可另开终端执行 --local-models 检查。相同故障提示会合并，恢复时会通知。"
            )
        return warning
