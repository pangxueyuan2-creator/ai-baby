"""A smoothed character mood, not a claim of subjective feeling."""

from .models import Emotion


def update(previous: Emotion, tone: str, learned: bool) -> Emotion:
    """Move intensity gradually; neutral interactions let the state settle."""
    target, intensity = {
        "gentle": ("happy", 0.55),
        "playful": ("playful", 0.55),
        "teasing": ("playful", 0.50),
        "hostile": ("annoyed", 0.45),
        "ambiguous": ("nervous", 0.35),
        "distress": ("sad", 0.40),
        "neutral": ("curious", 0.40) if learned else ("calm", 0.20),
    }[tone]
    return Emotion(target, round(previous.intensity * 0.75 + intensity * 0.25, 4))
