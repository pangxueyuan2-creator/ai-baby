"""Temporary stores only: tests never touch the user's baby or API credentials."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ai_baby.baby import Baby
from ai_baby.memory import MemoryStore


@pytest.fixture
def store(tmp_path):
    memory = MemoryStore(tmp_path / "baby.sqlite3")
    yield memory
    memory.close()


@pytest.fixture
def baby(store):
    result = Baby(store)
    result.born("Alice", "female")
    return result


@pytest.fixture
def api_server():
    seen = []
    response = {
        "status": 200,
        "body": {"choices": [{"message": {"content": "妈妈，我记得草莓。"}}]},
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(
                {"path": self.path, "body": body, "authorization": self.headers["Authorization"]}
            )
            self.send_response(response["status"])
            if response["status"] == 302:
                self.send_header("Location", "/redirect-target")
            self.end_headers()
            payload = response["body"]
            self.wfile.write(
                payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            )

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", seen, response
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
