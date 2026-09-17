"""Real CLI subprocesses with a fake model service; no Ollama or weights are installed."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def local_service():
    seen = []
    state = {
        "models": [{"name": "model-a", "size": 123}, {"name": "中文模型", "size": 456}],
        "failures": 0,
    }

    class Handler(BaseHTTPRequestHandler):
        def reply(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            seen.append(("GET", self.path, self.headers.get("Authorization"), None))
            if self.path == "/api/tags":
                self.reply({"models": state["models"]})
            elif self.path == "/v1/models":
                self.reply({"data": [{"id": model["name"]} for model in state["models"]]})
            else:
                self.reply({}, 404)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(("POST", self.path, self.headers.get("Authorization"), payload))
            if self.path != "/v1/chat/completions":
                self.reply({}, 404)
            elif state["failures"]:
                state["failures"] -= 1
                self.reply({"error": "private-server-detail"}, 503)
            else:
                self.reply({"choices": [{"message": {"content": "收到本轮输入。"}}]})

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", seen, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def run_cli(tmp_path, args, text="", extra_env=None):
    env = {key: value for key, value in os.environ.items() if not key.startswith("AI_BABY_")}
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        PYTHONIOENCODING="utf-8",
        OPENAI_API_KEY="ignored-global-fixture",
    )
    env.update(extra_env or {})
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ai_baby",
            "--data-dir",
            str(tmp_path / "baby"),
            "--env-file",
            str(tmp_path / "test.env"),
            *args,
        ],
        input=text,
        encoding="utf-8",
        capture_output=True,
        timeout=20,
        cwd=tmp_path,
        env=env,
    )


@pytest.mark.parametrize("provider,path", [("ollama", "/api/tags"), ("local-openai", "/v1/models")])
def test_listing_is_one_explicit_get_without_birth_or_configuration(
    tmp_path, local_service, provider, path
):
    url, seen, _ = local_service
    result = run_cli(tmp_path, ["--local-models", "--local-provider", provider, "--local-url", url])
    assert result.returncode == 0, result.stderr
    assert "model-a" in result.stdout and "中文模型" in result.stdout
    assert seen == [("GET", path, None, None)]
    assert not (tmp_path / "baby").exists()


def test_wizard_requires_choice_then_uses_selected_model(tmp_path, local_service):
    url, seen, _ = local_service
    result = run_cli(
        tmp_path, ["--setup-local", "--local-url", url], "oops\n9\n2\n\nAlice\n2\n\n你好\n/quit\n"
    )
    assert result.returncode == 0, result.stderr
    assert "请输入列表中的编号" in result.stdout
    assert "本次使用：中文模型" in result.stdout
    assert [(row[0], row[1]) for row in seen] == [
        ("GET", "/api/tags"),
        ("POST", "/v1/chat/completions"),
    ]
    assert seen[-1][2] is None and seen[-1][3]["model"] == "中文模型"
    assert not list((tmp_path / "baby").glob("local-model-*.json"))


@pytest.mark.parametrize("trailing_slash", ["", "/"])
def test_ollama_root_url_is_normalized_for_generation_and_saved_restart(
    tmp_path, local_service, trailing_slash
):
    url, seen, _ = local_service
    root_url = url.removesuffix("/v1") + trailing_slash
    first = run_cli(
        tmp_path,
        ["--setup-local", "--local-url", root_url],
        "1\ny\nAlice\n2\n\n你好\n/quit\n",
    )
    assert first.returncode == 0, first.stderr
    assert [(row[0], row[1]) for row in seen] == [
        ("GET", "/api/tags"),
        ("POST", "/v1/chat/completions"),
    ]
    assert "模型服务不可用" not in first.stdout
    (settings,) = (tmp_path / "baby").glob("local-model-*.json")
    assert json.loads(settings.read_text(encoding="utf-8"))["base_url"] == url
    second = run_cli(tmp_path, ["--local-config", str(settings)], "你好\n/quit\n")
    assert second.returncode == 0, second.stderr
    assert seen[-1][:2] == ("POST", "/v1/chat/completions")
    assert sum(row[0] == "GET" for row in seen) == 1


def test_save_and_restart_never_edit_env_or_repeat_discovery(tmp_path, local_service):
    url, seen, _ = local_service
    env_file = tmp_path / "test.env"
    env_file.write_text("# keep me\nOTHER=unchanged\nAI_BABY_PROVIDER=mock\n", encoding="utf-8")
    original = env_file.read_bytes()
    first = run_cli(
        tmp_path,
        ["--setup-local", "--local-url", url],
        "1\ny\nAlice\n2\n\n/baby-name 星芽\n/quit\n",
    )
    assert first.returncode == 0, first.stderr
    (settings,) = (tmp_path / "baby").glob("local-model-*.json")
    assert set(json.loads(settings.read_text(encoding="utf-8"))) == {
        "version",
        "provider",
        "base_url",
        "model",
    }
    assert env_file.read_bytes() == original
    second = run_cli(
        tmp_path,
        ["--local-config", str(settings)],
        "/profile\n你好\n/quit\n",
        {
            "AI_BABY_PROVIDER": "grok",
            "AI_BABY_BASE_URL": "https://remote.example/v1",
            "AI_BABY_MODEL": "wrong",
            "AI_BABY_API_KEY": "fixture-env-key",
        },
    )
    assert second.returncode == 0, second.stderr
    assert "Alice" in second.stdout and "星芽" in second.stdout
    assert [row[0] for row in seen] == ["GET", "POST"]
    assert seen[-1][2] is None and seen[-1][3]["model"] == "model-a"
    assert "fixture-env-key" not in second.stdout + second.stderr + settings.read_text(
        encoding="utf-8"
    )
    source_launcher = ".\\start.cmd" if os.name == "nt" else "sh start.sh"
    assert "已安装命令行" in first.stdout and source_launcher in first.stdout


def test_tilde_data_directory_keeps_wizard_and_saved_restart_on_same_baby(tmp_path, local_service):
    url, _, _ = local_service
    synthetic_home = tmp_path / "synthetic-home"
    home_env = {"HOME": str(synthetic_home), "USERPROFILE": str(synthetic_home)}
    first = run_cli(
        tmp_path,
        ["--data-dir", "~/same-baby", "--setup-local", "--local-url", url],
        "1\ny\nAlice\n2\n\n/quit\n",
        home_env,
    )
    assert first.returncode == 0, first.stderr
    actual_data = synthetic_home / "same-baby"
    assert (actual_data / "baby.sqlite3").exists()
    assert not (tmp_path / "~").exists()
    (settings,) = actual_data.glob("local-model-*.json")
    second = run_cli(
        tmp_path,
        ["--data-dir", str(actual_data), "--local-config", str(settings)],
        "/profile\n/quit\n",
        home_env,
    )
    assert second.returncode == 0, second.stderr
    assert "Alice" in second.stdout and "即将出生" not in second.stdout


def test_empty_model_list_does_not_download_or_create_baby(tmp_path, local_service):
    url, seen, state = local_service
    state["models"] = []
    result = run_cli(tmp_path, ["--setup-local", "--local-url", url])
    assert result.returncode == 0, result.stderr
    assert "没有发现已经安装的模型" in result.stdout
    assert [row[0] for row in seen] == ["GET"]
    assert not (tmp_path / "baby").exists()


@pytest.mark.parametrize("text", ["q\n", ""])
def test_cancel_or_eof_in_selection_leaves_no_character_or_settings(tmp_path, local_service, text):
    url, _, _ = local_service
    result = run_cli(tmp_path, ["--setup-local", "--local-url", url], text)
    assert result.returncode == 0 and "Traceback" not in result.stderr
    assert not (tmp_path / "baby").exists()


def test_remote_model_metadata_cannot_be_selected_as_local(tmp_path, local_service):
    url, seen, state = local_service
    state["models"] = [{"name": "arbitrary-name", "remote_host": "https://remote.example"}]
    result = run_cli(tmp_path, ["--setup-local", "--local-url", url])
    assert result.returncode == 0, result.stderr
    assert "仅发现远程模型" in result.stdout
    assert seen == [("GET", "/api/tags", None, None)]
    assert not (tmp_path / "baby").exists()


def test_repeated_outage_is_coalesced_and_recovery_reported(tmp_path, local_service):
    url, seen, state = local_service
    state["failures"] = 2
    result = run_cli(
        tmp_path,
        ["--setup-local", "--local-url", url],
        "1\n\nAlice\n2\n\n你好\n今天好吗\n再试一次\n/quit\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("模型服务不可用") == 1
    assert result.stdout.count("模型服务已恢复") == 1
    assert "private-server-detail" not in result.stdout + result.stderr
    assert "provider_fallback" not in result.stderr
    assert len([row for row in seen if row[0] == "POST"]) == 3
