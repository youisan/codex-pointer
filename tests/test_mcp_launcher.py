"""MCP discovery and rendering must never launch the native companion."""
import unittest
from unittest.mock import patch

from codex_pointer import mcp_server as server
from codex_pointer.launcher import LauncherError


class McpLauncherTests(unittest.TestCase):
    def call(self, name, arguments=None):
        return server.handle({"id": 1, "method": "tools/call", "params": {
            "name": name, "arguments": {} if arguments is None else arguments}})

    def test_discovery_and_resource_reads_have_no_side_effects(self):
        with patch.object(server, "show_pointer") as show, patch.object(server, "hide_pointer") as hide, \
                patch.object(server, "pointer_status") as status:
            tools = server.handle({"id": 1, "method": "tools/list"})["result"]["tools"]
            launcher = next(tool for tool in tools if tool["name"] == "pointer_launcher")
            self.assertEqual(launcher["_meta"]["openai/ui"]["entrypoints"], [{"type": "global"}])
            self.assertTrue(launcher["annotations"]["readOnlyHint"])
            self.assertEqual(launcher["_meta"]["ui"]["resourceUri"], server.LAUNCHER_URI)
            listing = server.handle({"id": 2, "method": "resources/list"})["result"]
            self.assertEqual(listing["resources"][0]["uri"], server.LAUNCHER_URI)
            resource = server.handle({"id": 3, "method": "resources/read", "params": {
                "uri": server.LAUNCHER_URI}})["result"]["contents"][0]
            self.assertEqual(resource["mimeType"], "text/html;profile=mcp-app")
            self.assertIn("<!doctype html>", resource["text"].lower())
            self.assertIn("show_pointer", resource["text"])
        show.assert_not_called()
        hide.assert_not_called()
        status.assert_not_called()

    def test_resource_cannot_read_arbitrary_files(self):
        for uri in ["file:///C:/secret", "ui://codex-pointer/../../config", "", None]:
            result = server.handle({"id": 2, "method": "resources/read", "params": {"uri": uri}})
            self.assertEqual(result["error"]["code"], -32002)

    def test_launcher_returns_structured_readonly_status(self):
        data = {"running": True, "control_available": False, "gui_available": True, "platform": "win32"}
        with patch.object(server, "pointer_status", return_value=data) as status, \
                patch.object(server, "show_pointer") as show:
            for name in ("pointer_launcher", "pointer_status"):
                result = self.call(name)["result"]
                self.assertEqual(result["structuredContent"], data)
                self.assertFalse(result["isError"])
        self.assertEqual(status.call_count, 2)
        show.assert_not_called()

    def test_actions_only_reach_the_requested_fixed_operation(self):
        with patch.object(server, "show_pointer", return_value={"status": "launch_requested"}) as show, \
                patch.object(server, "hide_pointer", return_value={"status": "hide_requested"}) as hide:
            self.assertEqual(self.call("show_pointer")["result"]["structuredContent"]["status"], "launch_requested")
            show.assert_called_once_with()
            hide.assert_not_called()
            self.assertEqual(self.call("hide_pointer")["result"]["structuredContent"]["status"], "hide_requested")
            hide.assert_called_once_with()

    def test_launch_errors_stay_errors_and_do_not_kill_server(self):
        with patch.object(server, "show_pointer", side_effect=LauncherError("退出旧版后重试")):
            result = self.call("show_pointer")["result"]
            self.assertTrue(result["isError"])
            self.assertIn("退出旧版", result["content"][0]["text"])
        self.assertEqual(server.handle({"id": 3, "method": "ping"})["result"], {})

    def test_invalid_arguments_cannot_launch_any_program(self):
        with patch.object(server, "show_pointer") as show:
            for arguments in ({"path": "cmd.exe"}, "command", [1], 1):
                self.assertTrue(self.call("show_pointer", arguments)["result"]["isError"])
            for name in ({"bad": "name"}, ["show_pointer"], None):
                self.assertEqual(self.call(name)["error"]["code"], -32602)
        show.assert_not_called()
