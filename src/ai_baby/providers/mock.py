"""Honest offline baseline using retrieved evidence and composable response policies."""

from ..conversation import Context, fact_query_route, is_experience_query, is_recall_query
from ..models import Fact
from .base import BaseLLMProvider


def _fact_sentence(fact: Fact) -> str:
    """Render stored triples as normal Chinese instead of exposing internal predicates."""
    if fact.kind == "preference":
        return f"你{' 喜欢' if fact.predicate == 'likes' else '不喜欢'}{fact.value}".replace('你 喜欢', '你喜欢') if fact.predicate == 'likes' else f"你不喜欢{fact.value}"
    if fact.kind == "personal":
        return {
            "居住地": f"你住在{fact.value}",
            "生日": f"你的生日是{fact.value}",
            "职业": f"你的职业是{fact.value}",
        }.get(fact.predicate, f"你的{fact.predicate}是{fact.value}")
    if fact.kind == "world" and fact.predicate == "是":
        return f"{fact.subject}是{fact.value}"
    if fact.kind == "relation":
        owner = "你" if fact.subject in {"我", "用户"} else fact.subject
        return f"{owner}的{fact.predicate}是{fact.value}"
    if fact.kind == "event":
        return fact.value
    return fact.value
