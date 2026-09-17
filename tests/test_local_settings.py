"""Local connection preferences stay separate from credentials and character data."""

import json
import os
import stat
from pathlib import Path

import pytest

from ai_baby.config import Config
from ai_baby.local_settings import read_local_settings, save_local_settings
from ai_baby.provider_notices import ProviderNotices


def local(tmp_path, **options):
    return Config(
        tmp_path,
        provider="local-openai",
        base_url=options.pop("base_url", "http://127.0.0.1:8080/v1"),
        model="本机测试模型",
        **options,
    )


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_generic_local_mode_needs_no_key_or_external_permission(tmp_path, host):
    config = local(tmp_path, base_url=f"http://{host}:8080/v1").validate()
    assert config.is_loopback and not config.allow_external and not config.api_key


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/v1",
        "https://example.com/v1",
        "http://127.0.0.2:8080/v1",
        "http://localhost.example.com/v1",
        "http://127.1:8080/v1",
        "http://[::ffff:127.0.0.1]:8080/v1",
        "http://localhost@remote.example/v1",
    ],
)
def test_local_provider_rejects_non_allowlisted_hosts_even_with_external_opt_in(tmp_path, url):
    with pytest.raises(ValueError):
        local(tmp_path, base_url=url, allow_external=True).validate()


def test_saved_connection_uses_allowlist_and_explicit_flag_wins_over_remote_env(
    tmp_path, monkeypatch
):
    env_file = tmp_path / "private.env"
    env_file.write_text("UNRELATED=keep\nAI_BABY_PROVIDER=mock\n", encoding="utf-8")
    before = env_file.read_bytes()
    target = tmp_path / "local-model-test.json"
    save_local_settings(local(tmp_path, api_key="private-fixture-key"), target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert set(payload) == {"version", "provider", "base_url", "model"}
    assert "private-fixture-key" not in target.read_text(encoding="utf-8")
    monkeypatch.setenv("AI_BABY_PROVIDER", "grok")
    monkeypatch.setenv("AI_BABY_BASE_URL", "https://remote.example/v1")
    monkeypatch.setenv("AI_BABY_MODEL", "remote-model")
    monkeypatch.setenv("OPENAI_API_KEY", "ignored-global-key")
    config = Config.load(tmp_path, env_file, local_config=target)
    assert (config.provider, config.model, config.base_url) == (
        "local-openai",
        "本机测试模型",
        "http://127.0.0.1:8080/v1",
    )
    assert env_file.read_bytes() == before
    assert config.api_key != "ignored-global-key"
    assert not (tmp_path / "baby.sqlite3").exists()


@pytest.mark.parametrize(
    "update",
    [
        {"version": True},
        {"version": 2},
        {"provider": "grok"},
        {"api_key": "never-accepted"},
        {"model": []},
    ],
)
def test_local_file_rejects_untrusted_schema_without_echoing_content(tmp_path, update):
    target = tmp_path / "local.json"
    save_local_settings(local(tmp_path), target)
    data = json.loads(target.read_text(encoding="utf-8")) | update
    target.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="配置格式无效") as failure:
        Config.load(tmp_path, tmp_path / "absent.env", local_config=target)
    assert "never-accepted" not in str(failure.value)


def test_local_file_size_is_bounded(tmp_path):
    target = tmp_path / "huge.json"
    target.write_bytes(b"private" * 2000)
    with pytest.raises(ValueError, match="配置格式无效"):
        read_local_settings(target)


@pytest.mark.parametrize("body", [b"[" * 3000 + b"]" * 3000, b"\xff\xfeinvalid"])
def test_malformed_local_file_is_a_safe_configuration_error(tmp_path, body):
    target = tmp_path / "malformed.json"
    target.write_bytes(body)
    with pytest.raises(ValueError, match="配置格式无效"):
        read_local_settings(target)


def test_explicit_tilde_data_directory_is_expanded_consistently(tmp_path, monkeypatch):
    synthetic_home = tmp_path / "synthetic-home"
    monkeypatch.setenv("HOME", str(synthetic_home))
    monkeypatch.setenv("USERPROFILE", str(synthetic_home))
    config = Config.load(Path("~/same-baby"), tmp_path / "absent.env", provider_override="mock")
    assert config.data_dir == synthetic_home / "same-baby"
    assert config.data_dir.resolve() == config.data_dir.expanduser().resolve()
    assert not synthetic_home.exists()


def test_save_refuses_overwrite(tmp_path):
    target = tmp_path / "existing.json"
    target.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        save_local_settings(local(tmp_path), target)
    assert target.read_text(encoding="utf-8") == "keep"


def test_save_refuses_symlink(tmp_path):
    target = tmp_path / "original.json"
    target.write_text("keep", encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation unavailable")
    with pytest.raises(FileExistsError):
        save_local_settings(local(tmp_path), link)
    assert target.read_text(encoding="utf-8") == "keep"


@pytest.mark.skipif(os.name == "nt", reason="Windows uses directory ACLs")
def test_saved_local_config_is_owner_only(tmp_path):
    target = tmp_path / "private.json"
    old = os.umask(0)
    try:
        save_local_settings(local(tmp_path), target)
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    finally:
        os.umask(old)


def test_repeated_failure_notice_is_coalesced_and_recovery_is_visible():
    notices = ProviderNotices("ollama")
    failure = "模型服务不可用（transport）；本轮使用离线回复。"
    assert "Ollama" in notices.observe(failure)
    assert all(notices.observe(failure) is None for _ in range(9))
    assert "仍不可用" in notices.observe(failure)
    assert "已恢复" in notices.observe(None)
    assert notices.observe(None) is None
    assert "Ollama" in notices.observe(failure)


def test_changed_failure_category_is_not_hidden():
    notices = ProviderNotices("local-openai")
    assert notices.observe("timeout")
    assert notices.observe("auth")
    assert notices.observe("auth") is None
