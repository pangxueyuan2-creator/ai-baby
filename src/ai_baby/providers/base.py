"""Provider boundary: a context in, a reply out."""

from abc import ABC, abstractmethod

from ..conversation import Context


class ProviderError(RuntimeError):
    """A redacted provider error that is safe to show to the user."""


class BaseLLMProvider(ABC):
    @abstractmethod
    def generate(self, context: Context) -> str:
        """Generate text or raise ProviderError; never mutate durable state."""
