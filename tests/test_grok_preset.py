"""The Grok preset is explicit, endpoint-locked, and reuses hardened transport."""

import os

import pytest

from ai_baby.config import Config
from ai_baby.providers.openai_compatible import OpenAICompatibleProvider


def clear_ai_baby_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("AI_BABY_"):
            monkeypatch.delenv(key)


def test_grok_preset_requires_external_opt_in_key_and_model(monkeypatch, tmp_path):
    clear_ai_baby_env(monkeypatch)
    monkeypatch.setenv("AI_BABY_PROVIDER", "grok")
    monkeypatch.setenv("AI_BABY_ALLOW_EXTERNAL", "true")
    monkeypatch.setenv("AI_BABY_API_KEY", "fixture-key")
    monkeypatch.setenv("AI_BABY_MODEL", "fixture-grok-model")

    config = Config.load(tmp_path, tmp_path / "absent.env")

    assert config.provider == "grok"
    assert config.base_url == "https://api.x.ai/v1"
    assert config.allow_external is True
    assert config.model == "fixture-grok-model"
    assert "fixture-key" not in repr(config)
    OpenAICompatibleProvider(config)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"allow_external": False, "api_key": "fixture-key", "model": "fixture-model"},
        {"allow_external": True, "api_key": "", "model": "fixture-model"},
        {"allow_external": True, "api_key": "fixture-key", "model": ""},
    ],
)
def test_grok_preset_rejects_missing_consent_or_credentials(tmp_path, kwargs):
    with pytest.raises(ValueError):
        Config(tmp_path, provider="grok", base_url="https://api.x.ai/v1", **kwargs).validate()


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1",
        "https://api.x.ai.evil.example/v1",
        "https://api.x.ai:8443/v1",
        "https://api.x.ai/v2",
    ],
)
def test_grok_preset_cannot_be_repointed_to_an_unrelated_endpoint(tmp_path, url):
    with pytest.raises(ValueError, match="grok"):
        Config(
            tmp_path,
            provider="grok",
            api_key="fixture-key",
            base_url=url,
            model="fixture-model",
            allow_external=True,
        ).validate()
