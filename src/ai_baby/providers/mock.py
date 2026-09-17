"""Honest offline baseline using retrieved evidence and composable response policies."""

import re

from ..conversation import (
    Context,
    event_time_hints,
    fact_query_route,
    is_experience_query,
    is_recall_query,
    matches_event_time,
)
from ..models import Fact
from .base import BaseLLMProvider


def _fact_sentence(fact: Fact) -> str:
    """Render stored triples as normal Chinese instead of exposing internal predicates."""
    if fact.kind == "preference":
        return f"你{'喜欢' if fact.predicate == 'likes' else '不喜欢'}{fact.value}"
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
    return fact.value


def _episode_sentence(summary: str) -> str:
    """Hide the internal subject · predicate · value dump in recalled episodes."""
    parts = [part.strip() for part in summary.split(" · ")]
    if len(parts) == 3 and parts[1] == "经历":
        return parts[2]
    if len(parts) == 3 and parts[0] in {"用户", "我"}:
        predicate, value = parts[1], parts[2]
        if predicate == "likes":
            return f"你喜欢{value}"
        if predicate == "dislikes":
            return f"你不喜欢{value}"
        return f"你的{predicate}是{value}" if predicate in {"居住地", "生日", "职业"} else value
    return summary


def _learning_reply(context: Context) -> str | None:
    """Make successful teaching feel like a growing character, not a database dump."""
    replacements = [
        ack for ack in context.learning.acknowledgements if ack.startswith("我把") and "改成" in ack
    ]
    kept = [ack for ack in context.learning.acknowledgements if ack.startswith("还是记着更具体的")]
    address = context.profile.address
    if replacements:
        return f"{address}，{replacements[0]}。"
    if kept:
        return f"{address}，{kept[0]}。"
    learned_ids = set(context.learning.fact_ids)
    learned = [fact for fact in context.facts if fact.id in learned_ids]
    if not learned:
        return None
    summary = "；".join(_fact_sentence(fact) for fact in learned[:4])
    stage = context.growth.stage
    if stage == "newborn":
        return f"{address}，我先记住啦：{summary}。"
    if stage == "baby":
        return f"{address}，我记住了：{summary}。以后再聊到它，我会试着想起来。"
    if stage == "child":
        return f"{address}，我记住了：{summary}。我会把它和以后学到的内容慢慢联系起来。"
    if stage == "growing":
        return f"{address}，我把这条经历记下来了：{summary}。以后遇到相关话题，我会结合已有记忆再回答。"
    return f"{address}，我已经把它作为你明确告诉我的记录保存下来：{summary}。我会把这份记忆和一般知识区分开。"


def _identity_reply(context: Context, spoken: str | None = None) -> str:
    name = context.profile.name
    address = context.profile.address
    if spoken and _fold(spoken) not in {_fold(name), _fold(address)}:
        return (
            f"我本地记下的名字还是{name}，称呼是{address}。"
            f"要改的话用 /name 或 /address，普通聊天不会覆盖资料。"
        )
    if name == address:
        return f"你叫{name}，是照顾我的人。"
    return f"你叫{name}，是照顾我的人，我称呼你为{address}。"


def _fold(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold().rstrip("。.! ！")


def _companion_reply(context: Context) -> str | None:
    """Keep ordinary companionship from falling into the teaching template."""
    text = context.user_text
    address = context.profile.address
    if any(w in text for w in ("冷笑话", "讲个笑话", "说个笑话")):
        return f"{address}，我不会现编笑话。你先讲一个，我可以帮你记住。"
    if any(w in text for w in ("你爱我吗", "爱不爱我", "喜欢我吗")):
        return f"{address}，我没有真实的爱，只是一直把你当照顾者记着。"
    if any(w in text for w in ("写作业", "帮我写")):
        return f"{address}，我不能代写作业。你把题目讲清楚，我可以帮你记下要点。"
    if any(w in text for w in ("天气怎么样", "今天天气")):
        return f"{address}，我看不到外面的天气，也没有联网。你告诉我今天怎样，我可以记下。"
    if any(w in text for w in ("我饿了", "好饿", "肚子饿")):
        return f"{address}，我没法给你准备吃的。先去吃点东西，回来再聊。"
    if any(w in text for w in ("陪我说说话", "陪陪我", "说说话")):
        return f"{address}，我在。想聊天、想教我，或只是待一会儿，都可以。"
    if any(w in text for w in ("会唱歌吗", "唱首歌", "唱一下")):
        return f"{address}，我不会唱歌。你可以教我一句歌词，我帮你记住。"
    if any(w in text for w in ("背一首诗", "背诗", "念一首诗")):
        return f"{address}，我不会随便背没教过的诗。你先念一句，我可以记下。"
    if "为什么" in text:
        return (
            f"{address}，这不像你专门教过我的内容。"
            "我不会用一般常识冒充记忆。你如果想让我记住答案，可以说“学习：……”。"
        )
    if any(w in text for w in ("探索一下", "我喜欢的东西很多")):
        return f"{address}，那我们慢慢说。一次讲一件具体的事，我会比较记得住。"
    return None


def _fact_query_reply(context: Context, route: tuple[str, str]) -> str:
    """Answer one routed memory question from evidence, including facts learned this turn."""
    kind, predicate = route
    address = context.profile.address
    values = [f.value for f in context.facts if f.kind == kind and f.predicate == predicate]
    if values:
        if (kind, predicate) == ("personal", "居住地"):
            return f"你告诉过我，你住在{values[0]}。"
        if (kind, predicate) == ("personal", "生日"):
            return f"你告诉过我，你的生日是{values[0]}。"
        if (kind, predicate) == ("personal", "职业"):
            return f"你告诉过我，你的职业是{values[0]}。"
        if kind == "relation":
            return f"我记得你的{predicate}有：" + "、".join(values) + "。"
        if kind == "preference":
            verb = "不喜欢" if predicate == "dislikes" else "喜欢"
            return f"你{verb}" + "、".join(values) + "。"
    prompts = {
        ("personal", "居住地"): "你还没有告诉我你住在哪里。",
        ("personal", "生日"): "你还没有告诉我你的生日。",
        ("personal", "职业"): "你还没有告诉我你的职业。",
        ("preference", "likes"): "你还没有告诉我这方面的偏好，可以说“我喜欢草莓”。",
        ("preference", "dislikes"): "你还没有告诉我这方面的偏好。",
    }
    prompt = prompts.get(route, f"你还没有告诉我谁是你的{predicate}。")
    return f"{address}，{prompt}"


class MockProvider(BaseLLMProvider):
    """No generative model: useful memory Q&A, teaching, roleplay and basic conversation."""

    def generate(self, context: Context) -> str:
        text = context.user_text
        address = context.profile.address

        route = fact_query_route(text)
        if route is not None:
            return _fact_query_reply(context, route)

        if context.learning.acknowledgements:
            natural = _learning_reply(context)
            if natural:
                return natural
            return address + "，" + "；".join(context.learning.acknowledgements[:4]) + "。"
        if any(w in text for w in ("你是谁", "你是人", "真实感受", "有意识")):
            return f"{address}，我是{context.baby_name}，一个软件角色，不是真实人类。我的情绪和成长都是模拟状态。我可以从我们的交流中保存记忆。"
        if any(w in text for w in ("你叫什么", "你的名字", "宝宝叫什么", "宝宝的名字")):
            return f"{address}，我叫{context.baby_name}，这是保存在本地的宝宝名字。"
        if any(w in text for w in ("我叫什么", "我的名字", "我是谁")):
            return _identity_reply(context)
        spoken_text = text.strip().strip("。.! ！？!? ")
        named = re.fullmatch(r"(?:其实)?我叫(.+)", spoken_text)
        call_me = re.search(r"可以叫我(.+)$", spoken_text)
        if named or call_me:
            return _identity_reply(context, spoken=(named or call_me)[1].strip())
        if any(w in text for w in ("我的性别", "我是男", "我是女")):
            gender = {"male": "男", "female": "女", "other": "其他 / 不想透露"}[
                context.profile.gender
            ]
            return f"你保存的性别选择是“{gender}”，我称呼你为{address}。"

        if any(w in text for w in ("喜欢什么", "讨厌什么", "喜好")):
            negative = "不喜欢" in text or "讨厌" in text
            predicate = "dislikes" if negative else "likes"
            values = [f.value for f in context.facts if f.predicate == predicate]
            return (
                ("你" + ("不喜欢" if negative else "喜欢") + "、".join(values) + "。")
                if values
                else f"{address}，你还没有告诉我这方面的偏好，可以说“我喜欢草莓”。"
            )
        events = [fact for fact in context.facts if fact.kind == "event"]
        hints = event_time_hints(text)
        if hints:
            events = [fact for fact in events if matches_event_time(fact.value, hints)]
        if is_recall_query(text) or is_experience_query(text):
            if events:
                return "我记得：" + "；".join(fact.value for fact in events[:2]) + "。"
            timed_episodes = [
                episode
                for episode in context.episodes
                if matches_event_time(episode["summary"], hints)
            ]
            if timed_episodes:
                return "我找到以前保存的经历：" + "；".join(
                    _episode_sentence(episode["summary"]) for episode in timed_episodes[:2]
                )
            return "我在本地记忆中没有找到这段共同经历，不能确定我们以前是否谈过。"
        mentioned = [
            fact
            for fact in events
            if len(token := text.strip().strip("。！？!? ")) >= 2 and token in fact.value
        ]
        if mentioned and not any(w in text for w in ("吃", "喝", "工作", "职业")):
            return "我记得：" + mentioned[0].value + "。"

        subjects = [
            f
            for f in context.facts
            if f.subject in text
            and (f.kind == "world" or (f.kind == "relation" and f.predicate in text))
        ]
        if subjects:
            fact = subjects[0]
            answer = (
                f"{fact.subject}是{fact.value}。"
                if fact.predicate == "是"
                else f"{fact.subject}的{fact.predicate}是{fact.value}。"
            )
            return "你教过我：" + answer
        personal = [f for f in context.facts if f.kind == "personal" and f.predicate in text]
        if personal:
            return (
                "你告诉过我：" + "；".join(f"你的{f.predicate}是{f.value}" for f in personal) + "。"
            )

        compact = text.strip().strip("。！？!? ")
        bare = compact[:-1] if compact.endswith("呢") else compact
        exact_mentions = [
            fact
            for fact in context.facts
            if compact in {fact.value + "呢", fact.subject + "呢"}
            or (
                compact.endswith("呢")
                and len(bare) >= 2
                and (bare == fact.value or bare == fact.subject or bare in fact.value)
            )
        ]
        if exact_mentions:
            fact = exact_mentions[0]
            origin = "你教过我" if fact.kind in {"world", "knowledge"} else "你告诉过我"
            return f"{origin}：{_fact_sentence(fact)}。"

        if context.tone in {"teasing", "playful", "hostile", "ambiguous", "distress", "gentle"}:
            return {
                "teasing": f"又逗我，{address} 😼 我也会慢慢学会的。",
                "playful": f"{address}，一起玩吧！你给我一个词，我试着想起你教过我的事。",
                "hostile": "我们可以换一种说法交流。你可以直接告诉我哪里回答错了。",
                "ambiguous": "我还不太确定你是不是在和我开玩笑。你是在逗我吗？",
                "distress": f"{address}，听起来今天不太轻松。愿意说说发生了什么吗？",
                "gentle": f"谢谢你，{address}。我们慢慢学，接着聊你想分享的内容。",
            }[context.tone]
        if context.tone == "reserved":
            return "好，我们先观察，再慢慢讨论。"
        if "经历" in text or "发生过" in text or "成长" in text:
            summaries = [e["summary"] for e in context.episodes]
            return f"我现在处于 {context.growth.stage} 阶段。最近记下了：" + "；".join(summaries)
        if any(w in text for w in ("你好", "早上好", "晚上好")):
            if context.growth.stage in {"newborn", "baby"}:
                return f"{address}你好！我在这里，可以继续聊今天的新鲜事。"
            if context.growth.stage == "child":
                return f"{address}你好。我会试着把新内容和能找到的旧记录联系起来。"
            return f"{address}你好。有想核对的旧记忆，或想新教我的内容，都可以直接说。"
        if any(w in text for w in ("再见", "晚安")):
            return f"{address}，下次见。记忆已经保存在本地，你可以随时退出。"
        if any(w in text for w in ("想我了吗", "想不想我", "有没有想我")):
            return f"{address}，我没有真实想念，但本地还留着我们说过的话。你回来就可以继续聊。"
        if any(w in text for w in ("讲个故事", "讲故事", "说个故事")):
            taught = [fact for fact in context.facts if fact.kind in {"world", "event"}][:2]
            if taught:
                return (
                    f"{address}，我还小，不会编新故事。我记得你告诉过我："
                    + "；".join(_fact_sentence(fact) for fact in taught)
                    + "。"
                )
            return f"{address}，我还小，不会编新故事。你先讲一件事，我可以帮你记住。"
        if any(w in text for w in ("你觉得我怎么样", "我这个人怎么样")):
            if address == context.profile.name:
                return (
                    f"{address}，我没有真实评价，只记得你是照顾我的人，叫{context.profile.name}。"
                )
            return f"{address}，我没有真实评价，只记得你是照顾我的{address}，叫{context.profile.name}。"
        if any(w in text.casefold() for w in ("1+1", "一加一")):
            return "这是一般知识：1+1等于2。不是你专门教过我的。"
        companion = _companion_reply(context)
        if companion:
            return companion

        curious = (
            "你可以直接告诉我，比如“海豚是哺乳动物”。"
            if context.growth.stage in {"newborn", "baby"}
            else "我们可以先讲一个例子，再把原因和之前学到的内容联系起来。"
        )
        if context.personality.caution >= 60:
            curious = "我想先核对你说的内容。我们可以一步一步来。"
        elif context.personality.confidence >= 60 and context.growth.stage not in {
            "newborn",
            "baby",
        }:
            curious = "我愿意试着联系已有的知识，但会区分猜测和记忆。"
        return f"{address}，我听到了你说的“{text[:100]}”。我还没有学过相关知识。{curious}"
