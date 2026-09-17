"""Metadata-only discovery against loopback fixtures, never an installed model service."""

import json
import socket
import threading
import time
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ai_baby.providers import ProviderError
from ai_baby.providers.discovery import LocalModel, discover_models


@contextmanager
def catalog_server(*, ipv6=False):
    """Serve synthetic catalogs or chat responses and observe every accepted connection."""
    seen = []
    response = {
        "status": 200,
        "body": {"models": []},
        "drip": False,
        "delay_headers": False,
        "connections": 0,
    }
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            item = {"method": self.command, "path": self.path, "headers": dict(self.headers)}
            if self.command == "POST":
                item["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(item)
            if response["delay_headers"] and stop.wait(2):
                return
            try:
                self.send_response(response["status"])
                if response["status"] in {301, 302, 303, 307, 308}:
                    self.send_header("Location", response.get("location", "/redirect-target"))
                if response["drip"]:
                    self.send_header("Content-Length", "999999")
                self.end_headers()
                if response["drip"]:
                    while not stop.wait(0.02):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                else:
                    body = response["body"]
                    self.wfile.write(body if isinstance(body, bytes) else json.dumps(body).encode())
            except OSError:
                pass

        do_POST = do_GET
        do_CONNECT = do_GET

        def log_message(self, *args):
            pass

    class Server(ThreadingHTTPServer):
        address_family = socket.AF_INET6 if ipv6 else socket.AF_INET

        def get_request(self):
            result = super().get_request()
            response["connections"] += 1
            return result

    try:
        server = Server(("::1" if ipv6 else "127.0.0.1", 0), Handler)
    except OSError:
        if ipv6:
            pytest.skip("IPv6 loopback is unavailable on this host")
        raise
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    try:
        host = "[::1]" if ipv6 else "127.0.0.1"
        yield f"http://{host}:{server.server_port}", seen, response
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


def set_proxy_environment(monkeypatch, proxy_url):
    """Exercise actual urllib environment loading without a bypass for localhost."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, proxy_url)
        monkeypatch.setenv(name.lower(), proxy_url)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "")
    proxies = urllib.request.getproxies()
    assert all(proxies[name] == proxy_url for name in ("http", "https", "all"))
    assert not urllib.request.proxy_bypass("localhost")


def test_ollama_discovery_only_gets_bounded_metadata_without_auth(monkeypatch):
    monkeypatch.setenv("AI_BABY_API_KEY", "must-not-be-sent")
    with catalog_server() as (url, seen, response):
        response["body"] = {
            "models": [
                {"name": "fixture:latest", "size": 123, "modified_at": "2026-01-01T00:00:00Z"},
                {"name": "named-cloud-but-local", "size": 456},
                {"name": "cloud-proxy", "remote_model": "upstream", "remote_host": "cloud.invalid"},
            ]
        }
        models = discover_models(url + "/v1/")
    assert models == [
        LocalModel("fixture:latest", 123, "2026-01-01T00:00:00Z"),
        LocalModel("named-cloud-but-local", 456, None),
        LocalModel("cloud-proxy", None, None, remote=True),
    ]
    assert len(seen) == 1
    assert seen[0]["method"] == "GET" and seen[0]["path"] == "/api/tags"
    assert "Authorization" not in seen[0]["headers"]
    assert "Content-Length" not in seen[0]["headers"]


def test_local_openai_discovery_preserves_prefix_and_lists_ids():
    with catalog_server() as (url, seen, response):
        response["body"] = {"data": [{"id": "loaded-gguf"}, {"id": "second-model"}]}
        models = discover_models(url + "/custom/v1/", provider="local-openai")
    assert [model.name for model in models] == ["loaded-gguf", "second-model"]
    assert seen[0]["path"] == "/custom/v1/models"
    assert "Authorization" not in seen[0]["headers"]


@pytest.mark.parametrize("provider", ["ollama", "local-openai"])
def test_empty_catalog_is_valid(provider):
    with catalog_server() as (url, _, response):
        response["body"] = {"models" if provider == "ollama" else "data": []}
        assert discover_models(url, provider=provider) == []


@pytest.mark.parametrize(
    "url,provider",
    [
        ("https://example.com/v1", "ollama"),
        ("http://localhost.evil/v1", "local-openai"),
        ("http://192.168.1.2/v1", "local-openai"),
        ("http://[2001:db8::1]/v1", "local-openai"),
        ("http://user:password@localhost/v1", "ollama"),
        ("http://localhost/v1?private=secret", "ollama"),
        ("http://localhost/v1#fragment", "ollama"),
        ("http://localhost:0/v1", "ollama"),
        ("http://localhost:99999/v1", "ollama"),
        ("http://localhost:bad/v1", "ollama"),
        ("http://localhost/private/v1", "ollama"),
        ("http://localhost/v1\n", "ollama"),
        ("file:///private/config", "ollama"),
        ("http://localhost/v1", "grok"),
    ],
)
def test_unsafe_discovery_url_is_rejected_before_connect(monkeypatch, url, provider):
    def blocked(*args, **kwargs):
        raise AssertionError("invalid discovery configuration attempted network access")

    monkeypatch.setattr(socket, "socket", blocked)
    with pytest.raises(ValueError):
        discover_models(url, provider=provider)


@pytest.mark.parametrize(
    "payload",
    [
        b"invalid json",
        {},
        {"models": {}},
        {"models": ["fixture"]},
        {"models": [{"name": ""}]},
        {"models": [{"name": "unsafe\x1b[31m"}]},
        {"models": [{"name": "x" * 201}]},
        {"models": [{"name": "fixture", "size": True}]},
        {"models": [{"name": "fixture", "size": -1}]},
        {"models": [{"name": "fixture", "modified_at": {}}]},
        {"models": [{"name": "fixture", "remote_host": []}]},
        {"models": [{"name": "fixture", "remote_model": True}]},
        {"models": [{"name": "duplicate"}, {"name": "duplicate"}]},
        {"models": [{"name": f"fixture-{i}"} for i in range(101)]},
        b"x" * 1_048_577,
    ],
    ids=[
        "invalid-json",
        "missing-list",
        "wrong-list-type",
        "wrong-entry-type",
        "empty-name",
        "control-name",
        "long-name",
        "boolean-size",
        "negative-size",
        "bad-modification-time",
        "bad-remote-host",
        "bad-remote-model",
        "duplicate-name",
        "too-many-models",
        "oversized-body",
    ],
)
def test_malformed_or_excessive_catalog_is_rejected_without_echo(payload):
    with catalog_server() as (url, _, response):
        response["body"] = payload
        with pytest.raises(ProviderError) as error:
            discover_models(url)
    assert error.value.category == "response"
    assert "unsafe" not in str(error.value)


@pytest.mark.parametrize(
    "status,category", [(302, "redirect"), (404, "http"), (429, "rate_limit"), (500, "server")]
)
def test_discovery_does_not_redirect_or_retry(status, category):
    with catalog_server() as (url, seen, response):
        response["status"] = status
        with pytest.raises(ProviderError) as error:
            discover_models(url)
        assert error.value.category == category
        assert len(seen) == 1


def test_discovery_ignores_proxy_and_dns_even_for_localhost(monkeypatch):
    with catalog_server() as (url, seen, _):
        monkeypatch.setattr(
            urllib.request, "getproxies", lambda: {"http": "http://unrelated.invalid"}
        )
        monkeypatch.setattr(urllib.request, "proxy_bypass", lambda host: False)
        monkeypatch.setattr(socket, "getaddrinfo", lambda *args: pytest.fail("DNS must not run"))
        assert discover_models(url.replace("127.0.0.1", "localhost")) == []
        assert seen[0]["headers"]["Host"].startswith("localhost:")


@pytest.mark.parametrize("host", ["[::1]", "localhost"])
def test_ipv6_loopback_and_localhost_ipv6_fallback(host, monkeypatch):
    with catalog_server(ipv6=True) as (url, seen, _):
        monkeypatch.setattr(socket, "getaddrinfo", lambda *args: pytest.fail("DNS must not run"))
        assert discover_models(url.replace("[::1]", host)) == []
        assert seen[0]["headers"]["Host"].startswith(host + ":")


def test_slow_discovery_has_total_deadline():
    with catalog_server() as (url, _, response):
        response["drip"] = True
        started = time.monotonic()
        with pytest.raises(ProviderError) as error:
            discover_models(url, timeout=0.2)
        assert error.value.category == "timeout"
        assert time.monotonic() - started < 1


@pytest.mark.parametrize("provider", ["ollama", "local-openai"])
def test_actual_proxy_environment_never_receives_local_discovery(monkeypatch, provider):
    with (
        catalog_server() as (url, seen, response),
        catalog_server() as (
            proxy_url,
            proxy_seen,
            proxy_response,
        ),
    ):
        set_proxy_environment(monkeypatch, proxy_url)
        response["body"] = {"models" if provider == "ollama" else "data": []}
        assert discover_models(url.replace("127.0.0.1", "localhost"), provider=provider) == []
        assert len(seen) == 1 and seen[0]["method"] == "GET"
        assert proxy_seen == []
        assert proxy_response["connections"] == 0


@pytest.mark.parametrize("status", [302, 307])
def test_discovery_redirect_never_connects_to_another_listener(status):
    with (
        catalog_server() as (url, seen, response),
        catalog_server() as (
            destination,
            destination_seen,
            destination_response,
        ),
    ):
        response.update(status=status, location=destination + "/redirected-models")
        with pytest.raises(ProviderError) as error:
            discover_models(url)
        assert error.value.category == "redirect"
        assert len(seen) == 1
        assert destination_seen == []
        assert destination_response["connections"] == 0


def test_unavailable_loopback_port_fails_with_a_bounded_safe_error():
    # A reserved non-listening port is unavailable, but the kernel may drop rather than
    # reject its connect attempts. A total deadline is valid in that case (seen on macOS).
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
        reserved.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{reserved.getsockname()[1]}"
        started = time.monotonic()
        with pytest.raises(ProviderError) as error:
            discover_models(url, timeout=3)
        assert error.value.category in {"transport", "timeout"}
        assert time.monotonic() - started < 4
        assert url not in str(error.value)


def test_explicit_connection_refusal_has_transport_category(monkeypatch):
    """Test classification independently of the host's TCP rejection timing."""
    attempts = []

    def refuse(sock, address):
        attempts.append(address)
        raise ConnectionRefusedError("synthetic connection refusal")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    with pytest.raises(ProviderError) as error:
        discover_models("http://127.0.0.1:11434", timeout=3)
    assert error.value.category == "transport"
    assert attempts == [("127.0.0.1", 11434)]
    assert "synthetic" not in str(error.value)


def test_discovery_stalled_headers_has_timeout_category():
    with catalog_server() as (url, seen, response):
        response["delay_headers"] = True
        started = time.monotonic()
        with pytest.raises(ProviderError) as error:
            discover_models(url, timeout=0.2)
        assert error.value.category == "timeout"
        assert time.monotonic() - started < 1
        assert len(seen) == 1
