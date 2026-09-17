"""Cancellable urllib sockets without holding a database connection or starting retries."""

import http.client
import socket
import threading
import urllib.request
from typing import Any, Callable


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

    def __init__(self, *args: Any, register: Callable[[socket.socket], None], **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._register = register
        connect = self._create_connection

        def create_connection(*args: Any, **kwargs: Any) -> socket.socket:
            sock = connect(*args, **kwargs)
            register(sock)
            return sock

        # CPython's connection factory seam is covered by the supported Python CI matrix.
        self._create_connection = create_connection


class TrackedHTTPSConnection(TrackedHTTPConnection, http.client.HTTPSConnection):
    def connect(self) -> None:
        """TLS handshake retains the socket timeout; track the resulting wrapped socket."""
        super().connect()
        self._register(self.sock)


class CancellableHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, register: Callable[[socket.socket], None]):
        super().__init__()
        self.register = register

    def http_open(self, request: urllib.request.Request):
        return self.do_open(TrackedHTTPConnection, request, register=self.register)


class CancellableHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, register: Callable[[socket.socket], None]):
        super().__init__()
        self.register = register

    def https_open(self, request: urllib.request.Request):
        return self.do_open(
            TrackedHTTPSConnection, request, register=self.register, context=self._context
        )
