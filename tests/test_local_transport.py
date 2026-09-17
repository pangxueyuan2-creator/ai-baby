"""Loopback means a numeric socket destination, not trust in DNS or inherited keys."""

import socket
import socketserver
import ssl
import threading
import urllib.request
from dataclasses import replace

import pytest
from test_local_discovery import catalog_server, set_proxy_environment
from test_provider_resilience import context

from ai_baby.config import Config
from ai_baby.providers import ProviderError
from ai_baby.providers.openai_compatible import OpenAICompatibleProvider
from ai_baby.providers.transport import CancellableJSONClient, TrackedHTTPSConnection


@pytest.mark.parametrize("host", ["localhost", "LOCALHOST", "127.0.0.1"])
def test_local_chat_never_resolves_a_hostname(baby, tmp_path, api_server, monkeypatch, host):
    url, seen, _ = api_server
    baby.provider = OpenAICompatibleProvider(
        Config(
            tmp_path, provider="ollama", model="fixture", base_url=url.replace("127.0.0.1", host)
        )
    )

    def poison_dns(*args, **kwargs):
        raise AssertionError("local connection unexpectedly delegated destination to DNS")

    monkeypatch.setattr(socket, "getaddrinfo", poison_dns)
    assert baby.chat("你好").warning is None
    assert len(seen) == 1


def test_local_preset_does_not_send_an_inherited_key(baby, tmp_path, api_server):
    url, seen, _ = api_server
    baby.provider = OpenAICompatibleProvider(
        Config(
            tmp_path,
            provider="ollama",
            model="fixture",
            base_url=url,
            api_key="unrelated-fixture-key",
        )
    )
    assert baby.chat("你好").warning is None
    assert seen[0]["authorization"] is None


@pytest.mark.parametrize("provider", ["ollama", "local-openai"])
def test_local_auth_requires_a_separate_opt_in(baby, tmp_path, api_server, provider):
    url, seen, _ = api_server
    config = Config(
        tmp_path,
        provider=provider,
        model="fixture",
        base_url=url,
        api_key="explicit-local-fixture-key",
        allow_local_auth=True,
    )
    baby.provider = OpenAICompatibleProvider(config)
    assert baby.chat("你好").warning is None
    assert seen[0]["authorization"] == "Bearer explicit-local-fixture-key"
    baby.provider = OpenAICompatibleProvider(replace(config, allow_local_auth=False))
    assert baby.chat("你好").warning is None
    assert seen[1]["authorization"] is None


def test_numeric_loopback_does_not_change_tls_server_hostname(monkeypatch):
    class DummySocket:
        def setsockopt(self, *args):
            pass

        def close(self):
            pass

        def do_handshake(self):
            seen.append("handshake")

    sock = DummySocket()
    seen = []
    context = ssl.create_default_context()

    def wrap_socket(raw, *, server_hostname, do_handshake_on_connect):
        assert do_handshake_on_connect is False
        seen.append(server_hostname)
        return raw

    connection = TrackedHTTPSConnection(
        "localhost", context=context, register=lambda sock: None, loopback_only=True
    )
    # Exercise HTTPConnection/TLS handoff with no live server or certificate fixture.
    monkeypatch.setattr(connection, "_create_connection", lambda *args: sock)
    monkeypatch.setattr(context, "wrap_socket", wrap_socket)
    connection.connect()
    assert seen == ["localhost", "handshake"]
    connection.close()


def test_slow_tls_handshake_is_cancelled_without_leaving_a_worker():
    release = threading.Event()

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.recv(4096)  # Receive ClientHello, then deliberately send no TLS reply.
            release.wait(2)

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = CancellableJSONClient(0.2, loopback_only=True)
        request = urllib.request.Request(f"https://127.0.0.1:{server.server_address[1]}/models")
        try:
            with pytest.raises(ProviderError) as error:
                client.run(lambda cancelled: client.read_json(request))
            assert error.value.category == "timeout"
            client._pending.join(0.7)
            assert not client._pending.is_alive()
        finally:
            release.set()
            server.shutdown()
            thread.join(2)


@pytest.mark.parametrize("url", ["file:///private/config", "https://example.com/models"])
def test_local_json_client_rejects_nonlocal_and_nonhttp_requests(url, monkeypatch):
    client = CancellableJSONClient(1, loopback_only=True)

    def blocked(*args, **kwargs):
        raise AssertionError("unsafe URL reached the opener")

    monkeypatch.setattr(client.opener, "open", blocked)
    with pytest.raises(ProviderError) as error:
        client.run(lambda cancelled: client.read_json(urllib.request.Request(url)))
    assert error.value.category == "configuration"


@pytest.mark.parametrize("provider", ["ollama", "local-openai"])
def test_actual_proxy_environment_never_receives_local_chat(baby, tmp_path, monkeypatch, provider):
    with (
        catalog_server() as (url, seen, response),
        catalog_server() as (
            proxy_url,
            proxy_seen,
            proxy_response,
        ),
    ):
        set_proxy_environment(monkeypatch, proxy_url)
        response["body"] = {"choices": [{"message": {"content": "fixture local reply"}}]}
        baby.provider = OpenAICompatibleProvider(
            Config(
                tmp_path,
                provider=provider,
                base_url=url.replace("127.0.0.1", "localhost") + "/v1",
                model="fixture",
            )
        )
        reply = baby.chat("你好")
        assert reply.warning is None
        assert len(seen) == 1 and seen[0]["method"] == "POST"
        assert seen[0]["path"] == "/v1/chat/completions"
        assert proxy_seen == []
        assert proxy_response["connections"] == 0


@pytest.mark.parametrize("host", ["[::1]", "localhost"])
def test_local_openai_chat_uses_ipv6_without_dns(baby, tmp_path, monkeypatch, host):
    with catalog_server(ipv6=True) as (url, seen, response):
        response["body"] = {"choices": [{"message": {"content": "IPv6 fixture reply"}}]}
        monkeypatch.setattr(socket, "getaddrinfo", lambda *args: pytest.fail("DNS must not run"))
        baby.provider = OpenAICompatibleProvider(
            Config(
                tmp_path,
                provider="local-openai",
                base_url=url.replace("[::1]", host) + "/v1",
                model="fixture-ipv6",
            )
        )
        reply = baby.chat("你好")
        assert reply.warning is None
        assert len(seen) == 1 and seen[0]["method"] == "POST"
        assert seen[0]["body"]["model"] == "fixture-ipv6"
        assert seen[0]["headers"]["Host"].startswith(host + ":")
        assert "Authorization" not in seen[0]["headers"]


@pytest.mark.parametrize("status", [302, 307])
def test_chat_redirect_never_sends_context_or_auth_to_another_listener(baby, tmp_path, status):
    with (
        catalog_server() as (url, seen, response),
        catalog_server() as (
            destination,
            destination_seen,
            destination_response,
        ),
    ):
        response.update(status=status, location=destination + "/redirected-chat")
        provider = OpenAICompatibleProvider(
            Config(
                tmp_path,
                provider="local-openai",
                base_url=url + "/v1",
                model="fixture",
                api_key="explicit-fixture-auth",
                allow_local_auth=True,
            )
        )
        with pytest.raises(ProviderError) as error:
            provider.generate(context(baby))
        assert error.value.category == "redirect"
        assert len(seen) == 1
        assert seen[0]["headers"]["Authorization"] == "Bearer explicit-fixture-auth"
        assert destination_seen == []
        assert destination_response["connections"] == 0
