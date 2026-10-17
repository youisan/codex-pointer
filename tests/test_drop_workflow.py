"""Native Qt file drops compose a task; only an explicit submit reaches Codex."""
from pathlib import Path
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from codex_pointer.app import PointerController
from codex_pointer.bridge import CodexBridge, DispatchResult
from codex_pointer.quick_tasks import tasks_for
from codex_pointer.windows import TargetContext, WindowsCaptureError


CAPTURE_ID = "c053ab24-ef0b-4d9a-91de-1e68f6119f23"
FILE_PATH = "C:/Projects/资料 one.txt"
FOLDER_PATH = "C:/Projects/项目资料"
FILE_TARGET = TargetContext(kind="file", title="资料 one.txt", path=FILE_PATH, source="file-drop")
FOLDER_TARGET = TargetContext(kind="folder", title="项目资料", path=FOLDER_PATH, source="file-drop")


class FileDropWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.workers = []
        self.bridge = Mock(spec=CodexBridge)
        self.bridge.open_new_draft.return_value = DispatchResult("", "desktop-deep-link", "draft_opened")
        replacements = {
            "CodexBridge": {"return_value": self.bridge},
            "target_from_path": {"return_value": FILE_TARGET},
            "save_settings": {}, "cancel_capture_lookup": {}, "close_capture_helpers": {},
            "data_directory": {"return_value": Path("C:/MockPointer")},
            "working_directory": {"return_value": "C:/Projects"},
            "save_capture": {"return_value": (CAPTURE_ID, Path("C:/MockPointer/context.json"))},
            "capture_target": {"side_effect": AssertionError("Unexpected native target capture")},
            "capture_window": {"side_effect": AssertionError("Unexpected native window capture")},
            "capture_screenshot": {"side_effect": AssertionError("Unexpected screenshot")},
        }
        self.mocks = {}
        for name, options in replacements.items():
            patcher = patch(f"codex_pointer.app.{name}", **options)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)
        for destination, options in [
            ("codex_pointer.app.threading.Thread", {"side_effect": AssertionError("Unexpected real thread")}),
            ("codex_pointer.app.QTimer.singleShot", {"side_effect": lambda delay, callback: callback()}),
            ("codex_pointer.ui.QToolTip.showText", {}),
        ]:
            patcher = patch(destination, **options)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.controller = PointerController(self.application, preview=True, theme="light", reduced_motion=True)
        self.controller.run_worker = lambda work, done, failed: self.workers.append((work, done, failed))
        self.controller.preview = False
        self.controller.button.show()
        self.addCleanup(self._dispose)

    def _dispose(self):
        self.controller.busy = False
        self.controller.cleanup()
        self.workers.clear()
        for widget in (self.controller.picker, self.controller.panel, self.controller.button,
                       self.controller.target_preview):
            if widget is not None and isValid(widget):
                widget.close()
                widget.deleteLater()
        self.controller.deleteLater()
        self.application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.application.processEvents()

    def finish_worker(self):
        work, done, failed = self.workers.pop(0)
        try:
            value = work()
        except Exception as error:
            failed(error)
        else:
            done(value)

    def drop_path(self, path):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path)])
        actions = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
        enter = QDragEnterEvent(QPoint(36, 36), actions, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.application.sendEvent(self.controller.button, enter)
        drop = QDropEvent(QPointF(36, 36), actions, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.application.sendEvent(self.controller.button, drop)
        return enter, drop

    def assert_no_dispatch(self):
        self.bridge.open_new_draft.assert_not_called()
        self.bridge.send_new.assert_not_called()
        self.bridge.send_existing.assert_not_called()
        self.mocks["save_capture"].assert_not_called()
        self.mocks["capture_screenshot"].assert_not_called()

    def test_file_drop_then_quick_task_preserves_draft_and_waits_for_explicit_submit(self):
        self.controller.open_panel()
        panel = self.controller.panel
        panel.editor.setPlainText("保留我的原稿")
        entered, dropped = self.drop_path(FILE_PATH)
        self.assertTrue(entered.isAccepted())
        self.assertTrue(dropped.isAccepted())
        self.assertEqual(dropped.dropAction(), Qt.DropAction.CopyAction)
        self.assertTrue(self.controller.selecting)
        self.assertFalse(panel.primary.isEnabled())
        # Parsing/drag events do not resolve paths on the GUI thread.
        self.mocks["target_from_path"].assert_not_called()
        self.finish_worker()
        self.mocks["target_from_path"].assert_called_once_with(FILE_PATH)
        self.assertEqual(self.controller.target, FILE_TARGET)
        self.assertEqual(self.controller.target.source, "file-drop")
        self.assertEqual(self.controller.target.hwnd, 0)
        self.assertFalse(self.controller.target.explorer)
        self.assertFalse(panel.include_image.isEnabled())
        panel.quick_task_buttons[0].click()
        expected = "保留我的原稿\n\n" + tasks_for(FILE_TARGET)[0].prompt
        self.assertEqual(panel.editor.toPlainText(), expected)
        self.assertTrue(panel.primary.isEnabled())
        self.assertEqual(self.workers, [])
        self.assert_no_dispatch()
        panel.primary.click()
        self.assertEqual(len(self.workers), 1)
        self.bridge.open_new_draft.assert_not_called()
        self.finish_worker()
        self.bridge.open_new_draft.assert_called_once()
        self.assertIn(expected, self.bridge.open_new_draft.call_args.args[0])
        self.bridge.send_new.assert_not_called()
        self.bridge.send_existing.assert_not_called()
        self.assertIn("确认后发送", panel.notice.text())

    def test_folder_drop_chooses_folder_starters_without_a_window_or_screenshot(self):
        self.mocks["target_from_path"].return_value = FOLDER_TARGET
        entered, dropped = self.drop_path(FOLDER_PATH)
        self.assertTrue(entered.isAccepted() and dropped.isAccepted())
        self.finish_worker()
        panel = self.controller.panel
        self.assertEqual(self.controller.target.kind, "folder")
        self.assertEqual(self.controller.target.source, "file-drop")
        self.assertEqual(self.controller.target.hwnd, 0)
        self.assertFalse(self.controller.target.explorer)
        self.assertEqual([button.text() for button in panel.quick_task_buttons],
                         [task.label for task in tasks_for(FOLDER_TARGET)])
        panel.quick_task_buttons[2].click()
        self.assertEqual(panel.editor.toPlainText(), tasks_for(FOLDER_TARGET)[2].prompt)
        self.assertTrue(panel.primary.isEnabled())
        self.assert_no_dispatch()

    def test_invalid_path_shows_a_clear_error_and_never_reaches_codex(self):
        self.mocks["target_from_path"].side_effect = WindowsCaptureError("文件已移动或无法访问，请重新拖入。")
        self.drop_path("C:/missing.txt")
        self.finish_worker()
        self.assertIsNone(self.controller.target)
        self.assertFalse(self.controller.selecting)
        self.assertFalse(self.controller.panel.primary.isEnabled())
        self.assertIn("文件已移动或无法访问", self.controller.panel.notice.text())
        self.assert_no_dispatch()

    def test_close_during_path_lookup_ignores_late_result_and_does_not_reopen(self):
        self.drop_path(FILE_PATH)
        panel = self.controller.panel
        panel.editor.setPlainText("未发送的草稿")
        panel.close()
        with patch.object(self.controller, "open_panel", wraps=self.controller.open_panel) as reopen:
            self.finish_worker()
            reopen.assert_not_called()
        self.assertFalse(panel.isVisible())
        self.assertIsNone(self.controller.target)
        self.assertFalse(self.controller.selecting)
        self.controller.open_panel()
        self.assertEqual(panel.editor.toPlainText(), "未发送的草稿")
        self.assertFalse(panel.primary.isEnabled())
        self.assert_no_dispatch()

    def test_cancel_during_path_lookup_leaves_no_sendable_target(self):
        self.drop_path(FOLDER_PATH)
        self.controller.panel.editor.setPlainText("我的任务")
        self.controller.cancel_selection()
        self.finish_worker()
        self.assertIsNone(self.controller.target)
        self.assertFalse(self.controller.selecting)
        self.assertFalse(self.controller.panel.primary.isEnabled())
        self.assert_no_dispatch()

    def test_busy_drop_is_rejected_without_starting_a_lookup_or_changing_target(self):
        self.controller.target = FOLDER_TARGET
        self.controller.open_panel()
        self.controller.set_busy(True)
        entered, dropped = self.drop_path(FILE_PATH)
        self.assertFalse(entered.isAccepted())
        self.assertFalse(dropped.isAccepted())
        self.assertEqual(self.workers, [])
        self.assertEqual(self.controller.target, FOLDER_TARGET)
        self.mocks["target_from_path"].assert_not_called()
        self.assert_no_dispatch()


if __name__ == "__main__":
    unittest.main()
