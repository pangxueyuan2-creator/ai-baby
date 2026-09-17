"""Offline reply helpers shared by MockProvider."""

from ..conversation import Context, fact_query_route, is_experience_query, is_recall_query
from ..models import Fact


def fact_sentence(fact: Fact) -> str:
    """Render stored triples as normal Chinese instead of exposing internal predicates."""
    if fact.kind == "preference":
        liked = fact.predicate == "likes"
        return ("你喜欢" if liked else "你不喜欢") + fact.value
    if fact.kind == "personal":
        return {
            "居住地": "你住在" + fact.value,
            "生日": "你的生日是" + fact.value,
            "职业": "你的职业是" + fact.value,
        }.get(fact.predicate, "你的" + fact.predicate + "是" + fact.value)
    if fact.kind == "world" and fact.predicate == "是":
        return fact.subject + "是" + fact.value
    if fact.kind == "relation":
        owner = "你" if fact.subject in {"我", "用户"} else fact.subject
        return owner + "的" + fact.predicate + "是" + fact.value
    return fact.value


def episode_sentence(summary: str) -> str:
    """Hide the internal subject / predicate / value dump in recalled episodes."""
    parts = [part.strip() for part in summary.split(" · ")]
    if len(parts) == 3 and parts[1] == "经历":
        return parts[2]
    if len(parts) == 3 and parts[0] in {"用户", "我"}:
        predicate, value = parts[1], parts[2]
        if predicate == "likes":
            return "你喜欢" + value
        if predicate == "dislikes":
            return "你不喜欢" + value
        if predicate in {"居住地", "生日", "职业"}:
            return "你的" + predicate + "是" + value
        return value
    return summary


def learning_reply(context: Context) -> str | None:
    """Make successful teaching feel like a growing character, not a database dump."""
    learned_ids = set(context.learning.fact_ids)
    learned = [fact for fact in context.facts if fact.id in learned_ids]
    if not learned:
        return None
    summary = "；".join(fact_sentence(fact) for fact in learned[:4])
    address = context.profile.address
    stage = context.growth.stage
    if stage == "newborn":
        return address + "，我先记住啦：" + summary + "。"
    if stage == "baby":
        return address + "，我记住了：" + summary + "。以后再聊到它，我会试着想起来。"
    if stage == "child":
        return address + "，我记住了：" + summary + "。我会把它和以后学到的内容慢慢联系起来。"
    if stage == "growing":
        return address + "，我把这条经历记下来了：" + summary + "。以后遇到相关话题，我会结合已有记忆再回答。"
    return address + "，我已经把它作为你明确告诉我的记录保存下来：" + summary + "。我会把这份记忆和一般知识区分开。"


def fallback_curious(context: Context) -> str:
    if context.growth.stage in {"newborn", "baby"}:
        return "你可以直接告诉我，比如“海豚是卜乳动物”。"
    if context.personality.caution >= 60:
        return "我想先核对你说的内容。我们可以一步一步来。"
    if context.personality.confidence >= 60:
        return "我愿意试着联系已有的知识，但会区分猜测和记忆。"
    return "我们可以先讲一个例子，再把原因和之前学到的内容联系起来。"


def answer(context: Context) -> str:
    """Composable offline policies. No generative model."""
    text = context.user_text
    address = context.profile.address
    if context.learning.acknowledgements:
        natural = learning_reply(context)
        if natural:
            return natural
        return address + "，" + "；".join(context.learning.acknowledgements[:4]) + "。"
    if any(w in text for w in ("你是谁", "你是人", "真实感受", "有意识")):
        return address + "，我是" + context.baby_name + "，一个软件角色，不是真实人类。我的情绪和成长都是模拟状态。我可以从我们的交流中保存记忆。"
    if any(w in text for w in ("你叫什么", "你的名字", "宝宝叫什么", "宝宝的名字")):
        return address + "，我叫" + context.baby_name + "，这是保存在本地的宝宝名字。"
    if any(w in text for w in ("我叫什么", "我的名字", "我是谁")):
        return "你叫" + context.profile.name + "，是照顾我的人，我称呼你为" + address + "。"
    if any(w in text for w in ("我的性别", "我是男", "我是女")):
        gender = {"male": "男", "female": "女", "other": "其他 / 不想透露"}[context.profile.gender]
        return "你保存的性别选择是“" + gender + "”，我称呼你为" + address + "。"
    route = fact_query_route(text)
    if route is not None:
        kind, predicate = route
        values = [f.value for f in context.facts if f.kind == kind and f.predicate == predicate]
        if values:
            if (kind, predicate) == ("personal", "居住地"):
                return "你告诉过我，你住在" + values[0] + "。"
            if (kind, predicate) == ("personal", "生日"):
                return "你告诉过我，你的生日是" + values[0] + "。"
            if (kind, predicate) == ("personal", "职业"):
                return "你告诉过我，你的职业是" + values[0] + "。"
            if kind == "relation":
                return "我记得你的" + predicate + "有：" + "、".join(values) + "。"
            if kind == "preference":
                verb = "不喜欢" if predicate == "dislikes" else "喜欢"
                return "你" + verb + "、".join(values) + "。"
        prompts = {
            ("personal", "居住地"): "你还没有告诉我你住在哪里。",
            ("personal", "生日"): "你还没有告诉我你的生日。",
            ("personal", "职业"): "你还没有告诉我你的职业。",
            ("preference", "likes"): "你还没有告诉我这方面的偏好，可以说“我喜欢草莓”。",
            ("preference", "dislikes"): "你还没有告诉我这方面的偏好。",
        }
        return address + "，" + prompts.get(route, "你还没有告诉我谁是你的" + predicate + "。")
    if any(w in text for w in ("喜欢什么", "讨厌什么", "喜好")):
        negative = "不喜欢" in text or "讨厌" in text
        predicate = "dislikes" if negative else "likes"
        values = [f.value for f in context.facts if f.predicate == predicate]
        if values:
            return "你" + ("不喜欢" if negative else "喜欢") + "、".join(values) + "。"
        return address + "，你还没有告诉我这方面的偏好，可以说“我喜欢草莓”。"
    events = [fact for fact in context.facts if fact.kind == "event"]
    if is_recall_query(text) or is_experience_query(text):
        if events:
            return "我记得：" + "；".join(fact.value for fact in events[:2]) + "。"
        if context.episodes:
            return "我找到以前保存的经历：" + "；".join(episode_sentence(episode["summary"]) for episode in context.episodes[:2])
        return "我在本地记忆中没有找到这段共同经历，不能确定我们以前是否谈过。"
    mentioned = [fact for fact in events if len(text.strip().strip("。！？!? ")) >= 2 and text.strip().strip("。！？!? ") in fact.value]
    if mentioned and not any(w in text for w in ("吃", "喝", "工作", "职业")):
        return "我记得：" + mentioned[0].value + "。"
    subjects = [fact for fact in context.facts if fact.subject in text and (fact.kind == "world" or (fact.kind == "relation" and fact.predicate in text))]
    if subjects:
        fact = subjects[0]
        taught = fact.subject + "是" + fact.value + "。" if fact.predicate == "是" else fact.subject + "的" + fact.predicate + "是" + fact.value + "。"
        return "你教过我：" + taught
    personal = [fact for fact in context.facts if fact.kind == "personal" and fact.predicate in text]
    if personal:
        return "你告诉过我：" + "；".join("你的" + f.predicate + "是" + f.value for f in personal) + "。"
    compact = text.strip().strip("。！？!? ")
    exact = [fact for fact in context.facts if compact in {fact.value + "呢", fact.subject + "呢"}]
    if exact:
        fact = exact[0]
        origin = "你教过我" if fact.kind in {"world", "knowledge"} else "你告诉过我"
        return origin + "：" + fact_sentence(fact) + "。"
    tones = {
        "teasing": "又逗我，" + address + " 😼 我也会慢慢学会的。",
        "playful": address + "，一起玩吧！你给我一个词，我试着想起你教过我的事。",
        "hostile": "我们可以换一种说法交流。你可以直接告诉我哪里回答错了。",
        "ambiguous": "我还不太确定你是不是在和我开玩笑。你是在逗我吗？",
        "distress": address + "，听起来今天不太轻松。愿意说说发生了什么吗？",
        "gentle": "谢谢你，" + address + "。我们慢慢学，接着聊你想分享的内容。",
        "reserved": "好，我们先观察，再慢慢讨论。",
    }
    if context.tone in tones:
        return tones[context.tone]
    if "经历" in text or "发生过" in text or "成长" in text:
        return "我现在处于 " + context.growth.stage + " 阶段。最近记下了：" + "；".join(episode["summary"] for episode in context.episodes)
    if any(w in text for w in ("你好", "早上好", "晚上好")):
        return address + "你好！我在这里，可以继续聊今天的新鲜事。"
    if any(w in text for w in ("再见", "晚安")):
        return address + "，下次见。记忆已经保存在本地，你可以随时退出。"
    if any(w in text for w in ("想我了吗", "想不想我", "有没有想我")):
        return address + "，我没有真实想念，但本地还留着我们说过的话。你回来就可以继续聊。"
    if any(w in text for w in ("讲个故事", "讲故事", "说个故事")):
        taught_facts = [fact for fact in context.facts if fact.kind in {"world", "event"}][:2]
        if taught_facts:
            return address + "，我还小，不会编新故事。我记得你告诉过我：" + "；".join(fact_sentence(fact) for fact in taught_facts) + "。"
        return address + "，我还小，不会编新故事。你先讲一件事，我可以帮你记住。"
    if any(w in text for w in ("你觉得我怎么样", "我这个人怎么样")):
        return address + "，我没有真实评价，只记得你是照顾我的" + address + "，叫" + context.profile.name + "。"
    if any(w in text.casefold() for w in ("1+1", "一加一")):
        return "这是一般知识：1+1等于2。不是你专门教过我的。"
    return address + "，我听到了你说的“" + text[:100] + "”。我还没有学过相关知识。" + fallback_curious(context)
