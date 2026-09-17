"""Honest offline baseline using retrieved evidence and composable response policies."""

from ..conversation import Context
from .base import BaseLLMProvider
from .replies import answer


class MockProvider(BaseLLMProvider):
    """No generative model: useful memory Q&A, teaching, roleplay and basic conversation."""

    def generate(self, context: Context) -> str:
        return answer(context)
