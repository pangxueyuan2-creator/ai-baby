"""Honest offline baseline using retrieved evidence and composable response policies."""

from ..conversation import Context
from .base import BaseLLMProvider


class MockProvider(BaseLLMProvider):
    """No generative model: useful memory Q&A, teaching, roleplay and basic conversation."""

    def generate(self, context: Context) -> str:
        text = context.user_text
        address = context.profile.address
        if context.learning.acknowledgements:
            return address + "，" + "；".join(context.learning.acknowledgements[:4]) + "。"
        if any(w in text for w in ("你是谁", "你是人", "真实感受", "有意识")):
            return f"{address}，我是{context.baby_name}，一个软件角色，不是真实人类。我的情绪和成长都是模拟状态。我可以从我们的交流中保存记忆。"
        if any(w in text for w in ("我叫什么", "我的名字", "我是谁")):
            return f"你叫{context.profile.name}，是照顾我的人，我称呼你为{address}。"
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
        if context.tone in {"teasing", "playful", "hostile", "ambiguous", "distress", "gentle"}:
            return {
                "teasing": f"又逗我，{address} 😼 我也会慢慢学会的。",
                "playful": f"{address}，一起玩吧！你给我一个词，我试着想起你教过我的事。",
                "hostile": "我们可以换一种说法交流。你可以直接告诉我哪里回答错了。",
                "ambiguous": "我还不太确定你是不是在和我开玩笑。你是在逗我吗？",
                "distress": f"{address}，听起来今天不太轻松。愿意说说发生了什么吗？",
                "gentle": f"谢谢你，{address}。我们慢慢学，你今天想教我什么？",
            }[context.tone]
        if context.tone == "reserved":
            return "好，我们先观察，再慢慢讨论。"
        if any(w in text for w in ("还记得", "第一次", "很久以前")) and context.episodes:
            return "我找到以前保存的经历：" + "；".join(e["summary"] for e in context.episodes[:2])
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
        if "经历" in text or "发生过" in text or "成长" in text:
            summaries = [e["summary"] for e in context.episodes]
            return f"我现在处于 {context.growth.stage} 阶段。最近记下了：" + "；".join(summaries)
        if any(w in text for w in ("你好", "早上好", "晚上好")):
            return f"{address}你好！我在这里。今天有什么新鲜事？"
        if any(w in text for w in ("再见", "晚安")):
            return f"{address}，下次见。记忆已经保存在本地，你可以随时退出。"
        if context.facts:
            return (
                "我想起你教过的一条相关内容：" + context.facts[0].text() + "。你想聊它的哪一部分？"
            )
        curious = (
            "这是什么呢？可以用“学习：事物是……”教我。"
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
        return f"{address}，我听到了你说的“{text[:100]}”。我还没有学过相关知识。{curious}（当前为基础离线模式。）"
