"""Language refresh is local and must not replace any in-progress task."""
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QLineEdit

from codex_pointer.app import PointerController
from codex_pointer.i18n import language, set_language
from codex_pointer import mcp_server
from codex_pointer.windows import TargetContext


class ControllerLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self):
        previous = language()
        self.addCleanup(set_language, previous)
        with patch("codex_pointer.app.CodexBridge") as bridge:
            self.controller = PointerController(self.application, preview=True, language="zh-CN", reduced_motion=True)
        self.bridge = bridge.return_value
        self.controller.target = TargetContext(kind="folder", path="C:/Example", title="用户目录")
        self.controller.open_panel()

    def tearDown(self):
        self.controller.cleanup()
        for window in self.application.topLevelWidgets():
            window.close()
            window.deleteLater()
        self.application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.application.processEvents()

    def test_background_refresh_is_single_flight_and_preserves_draft_and_target(self):
        controller = self.controller
        controller.panel.editor.setPlainText("Keep this 用户草稿")
        target = controller.target
        controller.settings.update(thread_id="linked-chat", thread_title="用户对话")
        reader = controller._language_reader = Mock()
        reader.read.return_value = "en-US"
        callbacks = []
        controller.run_worker = Mock(side_effect=lambda work, done, failed: callbacks.append((work, done)))
        controller.refresh_language()
        controller.refresh_language()
        controller.run_worker.assert_called_once()
        reader.read.assert_not_called()  # No config IO was performed on the GUI thread.
        work, done = callbacks.pop()
        done(work())
        self.assertFalse(controller._language_job_active)
        self.assertEqual(language(), "en-US")
        self.assertEqual(controller.panel.new_button.text(), "New chat")
        self.assertEqual(controller.panel.editor.toPlainText(), "Keep this 用户草稿")
        self.assertIs(controller.target, target)
        self.assertEqual(controller.settings["thread_id"], "linked-chat")
        self.bridge.send_existing.assert_not_called()
        self.bridge.open_new_draft.assert_not_called()

    def test_open_chat_picker_retranslates_without_losing_search_or_uuid(self):
        controller = self.controller
        controller.run_worker = lambda work, done, failed: done([])
        controller.pick_thread()
        picker = controller.picker
        search, manual = picker.findChildren(QLineEdit)
        search.setText("My query")
        manual.setText("01a1471e-0dbd-7bc1-8af3-487b6823c35f")
        controller.apply_language("en-US")
        self.assertIs(controller.picker, picker)
        self.assertEqual(picker.windowTitle(), "Choose a Codex chat")
        self.assertEqual(search.placeholderText(), "Search chats")
        self.assertEqual(search.text(), "My query")
        self.assertEqual(manual.text(), "01a1471e-0dbd-7bc1-8af3-487b6823c35f")


class McpLocaleTests(unittest.TestCase):
    def test_host_metadata_translates_tools_without_performing_an_action(self):
        previous = language()
        self.addCleanup(set_language, previous)
        with patch.object(mcp_server, "show_pointer") as show, patch.object(mcp_server, "hide_pointer") as hide:
            for metadata, expected in (({"openai/locale": "en-GB"}, "Show Pointer button"),
                                       ({"webplus/i18n": "zh-TW"}, "显示 Pointer 按钮")):
                mcp_server.handle({"id": 1, "method": "initialize", "params": {"_meta": metadata}})
                result = mcp_server.handle({"id": 2, "method": "tools/list"})["result"]
                tool = next(item for item in result["tools"] if item["name"] == "show_pointer")
                self.assertEqual(tool["title"], expected)
            show.assert_not_called()
            hide.assert_not_called()
