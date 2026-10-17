import json
import time
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from codex_pointer.captures import read_capture
from codex_pointer.mcp_server import handle


class CaptureTests(unittest.TestCase):
    def test_does_not_accept_path_instead_of_uuid(self):
        with self.assertRaises(ValueError):
            read_capture("../../secrets")

    def test_image_outside_cache_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "captures"
            folder.mkdir()
            identifier = str(uuid.uuid4())
            (folder / f"{identifier}.json").write_text(json.dumps({"id": identifier,
                "created_at": time.time(), "image": str(root / "private.png")}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "缓存目录"):
                read_capture(identifier, folder)

    def test_expired_target_does_not_silently_reappear(self):
        with TemporaryDirectory() as tmp:
            identifier = str(uuid.uuid4())
            (Path(tmp) / f"{identifier}.json").write_text(json.dumps({"id": identifier,
                "created_at": time.time() - 90000}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "24 小时"):
                read_capture(identifier, Path(tmp))

    def test_mcp_tool_failure_is_a_tool_error(self):
        response = handle({"id": 2, "method": "tools/call", "params": {"name": "read_capture", "arguments": {"capture_id": "invalid"}}})
        self.assertTrue(response["result"]["isError"])

    def test_mcp_notification_has_no_response(self):
        self.assertIsNone(handle({"method": "notifications/initialized"}))

    def test_malformed_mcp_parameters_do_not_crash_server(self):
        for method in ["initialize", "tools/call"]:
            self.assertEqual(handle({"id": 1, "method": method, "params": None})["error"]["code"], -32602)
        result = handle({"id": 2, "method": "tools/call", "params": {"name": "read_capture", "arguments": None}})
        self.assertTrue(result["result"]["isError"])
