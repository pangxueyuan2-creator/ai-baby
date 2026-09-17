"""Provider boundary: a context in, a reply out."""

from abc import ABC, abstractmethod

from ..conversation import Context


class ProviderError(RuntimeError):
    """A redacted provider error that is safe to show to the user."""

    def __init__(self, message: str, *, category: str = "unavailable", retryable: bool = False):
        super().__init__(message)
        self.category = category
        self.retryable = retryable


class BaseLLMProvider(ABC):
    @abstractmethod
    def generate(self, context: Context) -> str:
        """Generate text or raise ProviderError; never mutate durable state."""
