"""Protocol and dispatch tests use fake servers; never create a real Codex turn."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from codex_pointer.bridge import (
    BridgeError, BridgeTimeout, BridgeUnavailable, CodexBridge,
    DispatchResult, ThreadSummary, _RpcConnection, discover_codex,
)


THREAD_ID = "01a1471e-0dbd-7bc1-8af3-487b6823c35f"


class FakeConnection:
    def __init__(self, responses=None, error=None):
        self.responses = responses or {}
        self.error = error
        self.calls = []

    def __enter__(self):
        if self.error:
            raise self.error
        return self

    def __exit__(self, *args):
        pass

    def request(self, method, params):
        self.calls.append((method, params))
        response = self.responses.get(method, {})
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response(params)
        return response


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = self.temp.name
        self.bridge = CodexBridge(timeout=1)

    def test_list_is_read_only_and_pages_root_chat_sources(self):
        pages = [
            {"data": [{"id": THREAD_ID, "name": "已有标题", "cwd": self.cwd,
                       "preview": "任务预览"}], "nextCursor": "page2"},
            {"data": [{"id": "thr_other", "name": None, "preview": "第二条"}],
             "nextCursor": None},
        ]
        connection = FakeConnection({"thread/list": lambda params: pages.pop(0)})
        with patch.object(self.bridge, "_connection", return_value=connection) as factory:
            threads = self.bridge.list_threads()
        factory.assert_called_once_with(True)
        self.assertEqual(threads[0], ThreadSummary(THREAD_ID, "已有标题", self.cwd, "任务预览"))
        self.assertEqual(threads[1].title, "第二条")
        self.assertEqual(self.bridge.last_list_backend, "shared-app-server")
        self.assertEqual([method for method, _ in connection.calls], ["thread/list", "thread/list"])
        self.assertEqual(connection.calls[1][1]["cursor"], "page2")
        for _, params in connection.calls:
            self.assertTrue(params["useStateDbOnly"])
            self.assertFalse(params["archived"])
            self.assertIn("appServer", params["sourceKinds"])
            self.assertNotIn("subAgent", params["sourceKinds"])

    def test_list_falls_back_to_isolated_read_only_only(self):
        unavailable = FakeConnection(error=BridgeUnavailable("proxy unavailable"))
        isolated = FakeConnection({"thread/list": {"data": [], "nextCursor": None}})
        with patch.object(self.bridge, "_connection", side_effect=[unavailable, isolated]) as factory:
            self.assertEqual(self.bridge.list_threads(), [])
        self.assertEqual(factory.call_args_list[0].args, (True,))
        self.assertEqual(factory.call_args_list[1].args, (False,))
        self.assertEqual(self.bridge.last_list_backend, "isolated-app-server-read-only")
        self.assertEqual(self.bridge.last_shared_error, "proxy unavailable")

    def test_new_preserves_permissions_and_requires_confirmed_turn(self):
        connection = FakeConnection({"thread/start": {"thread": {"id": THREAD_ID}},
                                     "turn/start": {"turn": {"id": "turn1", "status": "inProgress"}}})
        with patch.object(self.bridge, "_connection", return_value=connection):
            result = self.bridge.send_new("处理文件夹\n继续", self.cwd)
        self.assertEqual(result, DispatchResult(THREAD_ID, "shared-app-server", "submitted"))
        self.assertEqual(connection.calls[0], ("thread/start", {"cwd": str(Path(self.cwd).resolve())}))
        self.assertEqual(connection.calls[1][1]["input"], [{"type": "text", "text": "处理文件夹\n继续"}])
        for _, params in connection.calls:
            self.assertTrue({"sandbox", "sandboxPolicy", "approvalPolicy", "model"}.isdisjoint(params))

    def test_new_never_falls_back_to_isolated_dispatch(self):
        connection = FakeConnection(error=BridgeUnavailable("proxy unavailable"))
        with patch.object(self.bridge, "_connection", return_value=connection) as factory:
            with self.assertRaises(BridgeUnavailable):
                self.bridge.send_new("任务", self.cwd)
        factory.assert_called_once_with()
        self.assertEqual(connection.calls, [])

    def test_failed_new_turn_reports_created_thread_without_success(self):
        connection = FakeConnection({"thread/start": {"thread": {"id": THREAD_ID}},
                                     "turn/start": BridgeError("rejected")})
        with patch.object(self.bridge, "_connection", return_value=connection):
            with self.assertRaisesRegex(BridgeError, THREAD_ID):
                self.bridge.send_new("任务", self.cwd)
        self.assertEqual(len(connection.calls), 2)

    def test_new_local_image_uses_protocol_item(self):
        screenshot = Path(self.cwd) / "窗口.png"
        screenshot.write_bytes(b"test-placeholder")
        connection = FakeConnection({"thread/start": {"thread": {"id": THREAD_ID}},
                                     "turn/start": {"turn": {"id": "turn1"}}})
        with patch.object(self.bridge, "_connection", return_value=connection):
            self.bridge.send_new("解释截图", self.cwd, str(screenshot))
        self.assertEqual(connection.calls[1][1]["input"][1],
                         {"type": "localImage", "path": str(screenshot.resolve())})

    def test_queue_uses_explicit_id_and_safe_argv_without_cwd_override(self):
        prompt = '中文 & $(secret) `echo private`\n第二行 "quotes"'
        with patch.object(self.bridge, "_has_queue", return_value=True), \
             patch.object(CodexBridge, "executable", new_callable=lambda: property(lambda _: "native-codex.exe")), \
             patch("codex_pointer.bridge.subprocess.run", return_value=Mock(returncode=0)) as run:
            result = self.bridge.send_existing(THREAD_ID, prompt, self.cwd)
        self.assertEqual(result.status, "queued")
        self.assertEqual(result.backend, "codex-queue")
        self.assertEqual(run.call_args.args[0],
                         ["native-codex.exe", "queue", "--thread", THREAD_ID, "--message", prompt])
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")

    def test_queue_failure_is_not_success_and_is_not_retried(self):
        with patch.object(self.bridge, "_has_queue", return_value=True), \
             patch.object(CodexBridge, "executable", new_callable=lambda: property(lambda _: "native-codex.exe")), \
             patch("codex_pointer.bridge.subprocess.run", return_value=Mock(returncode=1)) as run, \
             patch.object(self.bridge, "_connection") as connection:
            with self.assertRaises(BridgeError):
                self.bridge.send_existing(THREAD_ID, "任务")
        run.assert_called_once()
        connection.assert_not_called()

    def test_queue_timeout_is_ambiguous_and_is_not_retried(self):
        with patch.object(self.bridge, "_has_queue", return_value=True), \
             patch.object(CodexBridge, "executable", new_callable=lambda: property(lambda _: "native-codex.exe")), \
             patch("codex_pointer.bridge.subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 1)) as run:
            with self.assertRaises(BridgeTimeout):
                self.bridge.send_existing(THREAD_ID, "任务")
        run.assert_called_once()

    def test_existing_does_not_guess_thread_or_send_unsupported_image(self):
        with patch.object(self.bridge, "_has_queue") as has_queue:
            for invalid in ("", "current", "my title", "--last"):
                with self.assertRaises(BridgeError):
                    self.bridge.send_existing(invalid, "任务")
            with self.assertRaises(BridgeError):
                self.bridge.send_existing(THREAD_ID, "任务", image_path="window.png")
        has_queue.assert_not_called()

    def test_existing_without_queue_resumes_only_explicit_thread(self):
        connection = FakeConnection({"thread/resume": {"thread": {"id": THREAD_ID}},
                                     "turn/start": {"turn": {"id": "turn1"}}})
        with patch.object(self.bridge, "_has_queue", return_value=False), \
             patch.object(self.bridge, "_connection", return_value=connection):
            result = self.bridge.send_existing(THREAD_ID, "任务", cwd=self.cwd)
        self.assertEqual(result.status, "submitted")
        self.assertEqual(connection.calls[0], ("thread/resume", {"threadId": THREAD_ID, "excludeTurns": True}))
        self.assertNotIn("cwd", connection.calls[1][1])

    def test_draft_deep_link_encodes_content_and_does_not_dispatch(self):
        prompt = "解释窗口 & 保留\n第二行 #部分"
        with patch("codex_pointer.bridge.os.startfile", create=True) as startfile, \
             patch.object(self.bridge, "_connection") as connection:
            result = self.bridge.open_new_draft(prompt, self.cwd)
        url = urlparse(startfile.call_args.args[0])
        self.assertEqual((url.scheme, url.netloc), ("codex", "new"))
        self.assertEqual(parse_qs(url.query), {"path": [str(Path(self.cwd).resolve())], "prompt": [prompt]})
        self.assertEqual(result, DispatchResult("", "desktop-deep-link", "draft_opened"))
        connection.assert_not_called()

    def test_missing_protocol_handler_is_failure(self):
        with patch("codex_pointer.bridge.os.startfile", create=True, side_effect=OSError("not registered")):
            with self.assertRaises(BridgeUnavailable):
                self.bridge.open_new_draft("任务", self.cwd)

    def test_discovery_rejects_wrappers_without_running_a_shell(self):
        wrapper = Path(self.cwd) / "codex.cmd"
        wrapper.write_text("@echo should never run", encoding="utf-8")
        with self.assertRaises(BridgeUnavailable):
            discover_codex(wrapper)


class RpcTransportTests(unittest.TestCase):
    # This miniature server is Python code under test, not the real Codex CLI.
    SERVER = r'''
import json, sys
history = []
for line in sys.stdin:
    message = json.loads(line)
    history.append(message.get("method"))
    if "id" not in message:
        continue
    if message["method"] == "initialize":
        result = {"userAgent": "fake-server"}
    elif message["method"] == "neverRespond":
        continue
    elif message["method"] == "fail":
        print(json.dumps({"id": message["id"], "error": {"code": -1, "message": "secret prompt"}}), flush=True)
        continue
    else:
        print(json.dumps({"method": "item/started", "params": {}}), flush=True)
        result = {"history": history, "params": message["params"]}
    print(json.dumps({"id": message["id"], "result": result}, ensure_ascii=False), flush=True)
'''

    def test_utf8_handshake_waits_before_initialized_and_ignores_notifications(self):
        connection = _RpcConnection([sys.executable, "-u", "-c", self.SERVER], timeout=2)
        with connection:
            result = connection.request("echo", {"text": "中文\n第二行"})
            self.assertEqual(result["history"], ["initialize", "initialized", "echo"])
            self.assertEqual(result["params"]["text"], "中文\n第二行")
        self.assertIsNotNone(connection.process.poll())

    def test_timeout_and_cleanup_are_bounded(self):
        connection = _RpcConnection([sys.executable, "-u", "-c", self.SERVER], timeout=0.2)
        with self.assertRaises(BridgeTimeout):
            with connection:
                connection.request("neverRespond", {})
        self.assertIsNotNone(connection.process.poll())

    def test_rpc_error_does_not_echo_private_server_text(self):
        with _RpcConnection([sys.executable, "-u", "-c", self.SERVER], timeout=2) as connection:
            with self.assertRaises(BridgeError) as raised:
                connection.request("fail", {})
        self.assertNotIn("secret prompt", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
