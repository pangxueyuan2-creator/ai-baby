"""Cancellable urllib sockets without holding a database connection or starting retries."""

import http.client
import json
import math
import queue
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, TypeVar
from urllib.parse import urlsplit

from .base import ProviderError

T = TypeVar("T")
MAX_RESPONSE_BYTES = 1_048_576


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        """Never forward metadata, context or authorization to a redirect target."""
        return None


class SocketControl:
    """Interrupt active socket I/O; OS name resolution remains outside Python's control."""

    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self._lock = threading.Lock()
        self._socket: socket.socket | None = None

    @staticmethod
    def _shutdown(sock: socket.socket | None) -> None:
        if sock is not None:
            try:
                # close() alone does not interrupt a read held by HTTPResponse.makefile().
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # The response may already have closed its socket.

    def register(self, sock: socket.socket) -> None:
        """Track a newly connected socket, including one finishing after cancellation."""
        with self._lock:
            self._socket = sock
            cancelled = self.cancelled.is_set()
        if cancelled:
            self._shutdown(sock)
            sock.close()
            raise OSError("request cancelled")

    def cancel(self) -> None:
        """Wake blocked header/body readers and prevent another retry."""
        with self._lock:
            self.cancelled.set()
            sock = self._socket
        self._shutdown(sock)


class TrackedHTTPConnection(http.client.HTTPConnection):
    """Register TCP before proxy CONNECT, so a stalled proxy can also be cancelled."""

    def __init__(
        self,
        *args: Any,
        register: Callable[[socket.socket], None],
        loopback_only: bool = False,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self._register = register
        connect = self._create_connection

        def create_connection(*args: Any, **kwargs: Any) -> socket.socket:
            sock = (
                _connect_loopback(*args, register=register, **kwargs)
                if loopback_only
                else connect(*args, **kwargs)
            )
            register(sock)
            return sock

        # CPython's connection factory seam is covered by the supported Python CI matrix.
        self._create_connection = create_connection


class TrackedHTTPSConnection(TrackedHTTPConnection, http.client.HTTPSConnection):
    def connect(self) -> None:
        """Keep hostname verification and make the TLS handshake itself cancellable."""
        http.client.HTTPConnection.connect(self)
        self.sock = self._context.wrap_socket(
            self.sock,
            server_hostname=self._tunnel_host or self.host,
            do_handshake_on_connect=False,
        )
        self._register(self.sock)
        self.sock.do_handshake()


def _connect_loopback(
    address: tuple[str, int],
    timeout: Any = socket._GLOBAL_DEFAULT_TIMEOUT,
    source_address: tuple[str, int] | None = None,
    *,
    register: Callable[[socket.socket], None],
) -> socket.socket:
    """Use numeric addresses directly: localhost never reaches a DNS resolver."""
    host, port = address
    host = host.casefold()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise OSError("non-loopback destination rejected")
    destinations = []
    if host in {"localhost", "127.0.0.1"}:
        destinations.append((socket.AF_INET, "127.0.0.1"))
    if host in {"localhost", "::1"}:
        destinations.append((socket.AF_INET6, "::1"))
    for family, numeric_host in destinations:
        sock = None
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            register(sock)
            sock.connect((numeric_host, port))
            # If cancellation happened while connecting, reject before sending any HTTP data.
            register(sock)
            return sock
        except OSError:
            if sock is not None:
                sock.close()
    raise OSError("loopback connection failed")


class CancellableHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, register: Callable[[socket.socket], None], *, loopback_only: bool = False):
        super().__init__()
        self.register = register
        self.loopback_only = loopback_only

    def http_open(self, request: urllib.request.Request):
        return self.do_open(
            TrackedHTTPConnection,
            request,
            register=self.register,
            loopback_only=self.loopback_only,
        )


class CancellableHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, register: Callable[[socket.socket], None], *, loopback_only: bool = False):
        super().__init__()
        self.register = register
        self.loopback_only = loopback_only

    def https_open(self, request: urllib.request.Request):
        return self.do_open(
            TrackedHTTPSConnection,
            request,
            register=self.register,
            context=self._context,
            loopback_only=self.loopback_only,
        )


class CancellableJSONClient:
    """Shared bounded HTTP I/O for generation and explicitly requested model metadata."""

    def __init__(self, timeout: float, *, loopback_only: bool = False):
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 120
        ):
            raise ValueError("请求超时必须大于 0 且不超过 120 秒。")
        self.timeout = timeout
        self.loopback_only = loopback_only
        self._transport = SocketControl()
        handlers = [
            NoRedirect(),
            CancellableHTTPHandler(
                lambda sock: self._transport.register(sock), loopback_only=loopback_only
            ),
            CancellableHTTPSHandler(
                lambda sock: self._transport.register(sock), loopback_only=loopback_only
            ),
        ]
        if loopback_only:
            handlers.append(urllib.request.ProxyHandler({}))
        self.opener = urllib.request.build_opener(*handlers)
        self._pending: threading.Thread | None = None
        self._admission = threading.Lock()

    def run(self, operation: Callable[[threading.Event], T]) -> T:
        """Run one operation with a total caller deadline and one admitted worker."""
        output: queue.Queue = queue.Queue(maxsize=1)
        transport = SocketControl()

        def worker() -> None:
            try:
                output.put(operation(transport.cancelled))
            except Exception as exc:
                output.put(
                    exc
                    if isinstance(exc, ProviderError)
                    else ProviderError("服务异常。", category="transport")
                )

        with self._admission:
            if self._pending is not None and self._pending.is_alive():
                raise ProviderError("上次请求仍在结束；请稍后重试。", category="busy")
            self._transport = transport
            self._pending = threading.Thread(target=worker, daemon=True)
            deadline = time.monotonic() + self.timeout
            try:
                self._pending.start()
            except BaseException:
                transport.cancel()
                raise
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderError("模型请求超时。", category="timeout")
                try:
                    result = output.get(timeout=min(0.05, remaining))
                    if isinstance(result, ProviderError):
                        raise result
                    return result
                except queue.Empty:
                    continue
        finally:
            transport.cancel()

    def read_json(self, request: urllib.request.Request) -> Any:
        """Read at most one MiB inside run(); redact network and response errors."""
        url = urlsplit(request.full_url)
        if url.scheme not in {"http", "https"} or (
            self.loopback_only and url.hostname not in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ProviderError("请求地址不符合连接限制。", category="configuration")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ProviderError("模型响应过大。", category="response")
            return json.loads(raw)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            category = {401: "auth", 403: "auth", 429: "rate_limit"}.get(code, "http")
            if 300 <= code < 400:
                category = "redirect"
            elif 500 <= code < 600:
                category = "server"
            raise ProviderError(
                f"模型服务 HTTP {code}。", category=category, retryable=code == 429
            ) from None
        except TimeoutError:
            raise ProviderError("模型请求超时。", category="timeout") from None
        except urllib.error.URLError as exc:
            category = "timeout" if isinstance(exc.reason, TimeoutError) else "transport"
            raise ProviderError("模型连接失败。", category=category) from None
        except (OSError, http.client.HTTPException):
            raise ProviderError("模型连接中断。", category="transport") from None
        except (ValueError, RecursionError):
            raise ProviderError("模型响应格式无效。", category="response") from None
