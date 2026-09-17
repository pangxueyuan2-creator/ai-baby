"""Honest offline baseline using retrieved evidence and composable response policies."""

from ..conversation import Context, fact_query_route, is_experience_query, is_recall_query
from ..models import Fact
from .base import BaseLLMProvider


def _fact_sentence(fact: Fact) -> str:
    """Render stored triples as normal Chinese instead of exposing internal predicates."""
    if fact.kind == "preference":
        return f"你{' 喜欢' if False else ('喜欢' if fact.predicate == 'likes' else '不喜欢')}{fact.value}" if False else (
            f"你{' 喜欢'.strip()}"
        )
