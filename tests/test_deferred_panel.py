"""A drop selects quietly; only an explicit click opens the task composer."""
from dataclasses import replace
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from codex_pointer.app import PointerController
from codex_pointer.bridge import CodexBridge
from codex_pointer.i18n import language, set_language
from codex_pointer.windows import TargetContext


WINDOW_A = TargetContext(title="Window A", hwnd=41, process_path="C:/Apps/A.exe", point=(200, 200))
WINDOW_B = TargetContext(title="Window B", hwnd=42, process_path="C:/Apps/B.exe", point=(200, 200))
FOLDER_A = TargetContext(kind="folder", path="C:/Projects/A", source="file-drop")
EXPLORER = replace(WINDOW_A, explorer=True, process_name="explorer.exe")
ENRICHED = replace(FOLDER_A, explorer=True, hwnd=41, source="explorer-hit-test")
_UNSET = object()


class DeferredPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.previous_language = language()
        self.addCleanup(lambda: set_language(self.previous_language))
        self.workers = []
        self.bridge = Mock(spec=CodexBridge)
        self.mocks = {}
        replacements = {
            "CodexBridge": {"return_value": self.bridge},
            "save_settings": {}, "cancel_capture_lookup": {}, "close_capture_helpers": {},
            "get_cursor_position": {"return_value": (200, 200)},
            "capture_target": {"return_value": WINDOW_A},
            "capture_window": {"side_effect": AssertionError("Unexpected recapture")},
            "target_from_path": {"return_value": FOLDER_A},
            "enrich_target": {"return_value": ENRICHED},
            "capture_screenshot": {"side_effect": AssertionError("Unexpected screenshot")},
            "save_capture": {"side_effect": AssertionError("Unexpected submission")},
        }
        for name, options in replacements.items():
            replacement = patch(f"codex_pointer.app.{name}", **options)
            self.mocks[name] = replacement.start()
            self.addCleanup(replacement.stop)
        guard = patch("codex_pointer.app.threading.Thread", side_effect=AssertionError("Unexpected real worker"))
        guard.start()
        self.addCleanup(guard.stop)
        # Construction avoids global hotkeys, foreground polling and config
        # reads. Native capture functions remain mocked after preview is off.
        self.controller = PointerController(self.application, preview=True, theme="light",
                                            reduced_motion=True, language="en-US")
        self.controller.run_worker = lambda work, done, failed: self.workers.append((work, done, failed))
        self.controller.preview = False
        self.addCleanup(self.dispose)

    def dispose(self):
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

    def finish(self, index=0, *, value=_UNSET, error=None):
        work, done, failed = self.workers.pop(index)
        if error is not None:
            failed(error)
            return
        try:
            result = work() if value is _UNSET else value
        except Exception as exception:
            failed(exception)
        else:
            done(result)

    def assert_hidden(self):
        self.assertFalse(self.controller.panel and self.controller.panel.isVisible())

    def assert_no_submission(self):
        self.bridge.open_new_draft.assert_not_called()
        self.bridge.send_new.assert_not_called()
        self.bridge.send_existing.assert_not_called()
        self.mocks["save_capture"].assert_not_called()
        self.mocks["capture_screenshot"].assert_not_called()

    def test_window_drop_finishes_hidden_then_click_opens_the_selected_window(self):
        self.controller.button.dropped.emit(200, 200)
        self.assert_hidden()
        self.finish()
        self.assert_hidden()
        self.assertEqual(self.controller.target, WINDOW_A)
        self.controller.button.clicked.emit()
        self.assertTrue(self.controller.panel.isVisible())
        self.assertEqual(self.controller.panel.target_title.toolTip(), "Window A")
        self.assertEqual(self.workers, [])
        self.mocks["capture_target"].assert_called_once()
        self.mocks["capture_window"].assert_not_called()
        self.assert_no_submission()

    def test_file_or_folder_drop_stays_hidden_and_opens_without_recapturing_a_window(self):
        self.controller.button.file_dropped.emit("C:/Projects/A")
        self.assert_hidden()
        self.finish()
        self.assert_hidden()
        self.assertEqual(self.controller.target, FOLDER_A)
        self.controller.button.clicked.emit()
        self.assertTrue(self.controller.panel.isVisible())
        self.assertEqual(self.controller.panel.target_path.toolTip(), "C:/Projects/A")
        self.assertEqual(self.workers, [])
        self.mocks["target_from_path"].assert_called_once_with("C:/Projects/A")
        self.mocks["capture_target"].assert_not_called()
        self.mocks["capture_window"].assert_not_called()
        self.assert_no_submission()

    def test_background_drop_failure_does_not_open_the_panel(self):
        self.controller.button.file_dropped.emit("//offline/share/one")
        self.assert_hidden()
        self.finish(error=RuntimeError("Owned simulated offline share"))
        self.assert_hidden()
        self.assertFalse(self.controller.selecting)
        self.assertIsNone(self.controller.target)
        self.controller.button.clicked.emit()
        self.assertTrue(self.controller.panel.isVisible())
        self.assertIn("Owned simulated offline share", self.controller.panel.notice.text())
        self.assertEqual(self.workers, [])
        self.mocks["capture_target"].assert_not_called()
        self.mocks["capture_window"].assert_not_called()
        self.assert_no_submission()

    def test_dropping_a_file_on_the_circle_collapses_an_open_panel_and_preserves_its_draft(self):
        self.controller.target = WINDOW_A
        self.controller.open_panel()
        self.controller.panel.editor.setPlainText("Already composing a task")
        file = TargetContext(kind="file", path="C:/Projects/notes.txt", source="file-drop")
        self.mocks["target_from_path"].return_value = file
        self.controller.button.file_dropped.emit(file.path)
        self.assert_hidden()
        self.finish()
        self.assert_hidden()
        self.assertEqual(self.controller.target, file)
        self.controller.button.clicked.emit()
        self.assertTrue(self.controller.panel.isVisible())
        self.assertEqual(self.controller.panel.editor.toPlainText(), "Already composing a task")
        self.assertEqual(self.controller.panel.target_path.toolTip(), file.path)
        self.assertEqual(self.workers, [])
        self.mocks["capture_target"].assert_not_called()
        self.assert_no_submission()

    def test_dragging_from_an_open_panel_collapses_it_and_preserves_the_draft(self):
        self.controller.target = WINDOW_A
        self.controller.open_panel()
        self.controller.panel.editor.setPlainText("Unsent draft 用户输入")
        # Only suppress native Esc registration for the synthetic drag start.
        self.controller.preview = True
        self.controller.drag_started()
        self.controller.preview = False
        self.assert_hidden()
        self.mocks["capture_target"].return_value = WINDOW_B
        self.controller.button.dropped.emit(200, 200)
        self.assert_hidden()
        self.finish()
        self.assert_hidden()
        self.assertEqual(self.controller.draft, "Unsent draft 用户输入")
        self.controller.button.clicked.emit()
        self.assertEqual(self.controller.panel.editor.toPlainText(), "Unsent draft 用户输入")
        self.assertEqual(self.controller.target, WINDOW_B)
        self.assertTrue(self.controller.panel.isVisible())
        self.controller.button.clicked.emit()
        self.assert_hidden()
        self.controller.button.clicked.emit()
        self.assertEqual(self.controller.panel.editor.toPlainText(), "Unsent draft 用户输入")
        self.assertEqual(self.controller.target, WINDOW_B)
        self.assertEqual(self.workers, [])
        self.mocks["capture_target"].assert_called_once()
        self.assert_no_submission()

    def test_click_during_pending_identification_opens_progress_without_starting_another_capture(self):
        self.controller.button.dropped.emit(200, 200)
        self.assertTrue(self.controller.selecting)
        self.assert_hidden()
        self.controller.button.clicked.emit()
        self.assertTrue(self.controller.panel.isVisible())
        self.assertFalse(self.controller.panel.primary.isEnabled())
        self.assertFalse(self.controller.panel.editor.isReadOnly())
        self.assertEqual(len(self.workers), 1)
        self.controller.panel.editor.setPlainText("Keep writing while resolving")
        self.finish()
        self.assertTrue(self.controller.panel.isVisible())
        self.assertEqual(self.controller.target, WINDOW_A)
        self.assertEqual(self.controller.panel.editor.toPlainText(), "Keep writing while resolving")
        self.assertEqual(self.workers, [])
        self.mocks["capture_target"].assert_called_once()
        self.assert_no_submission()

    def test_late_fast_result_cannot_show_or_replace_a_newer_hidden_drop(self):
        self.controller.button.dropped.emit(200, 200)
        self.controller.button.dropped.emit(200, 200)
        self.assert_hidden()
        self.finish(value=WINDOW_A)
        self.assert_hidden()
        self.finish(value=WINDOW_B)
        self.assert_hidden()
        self.assertEqual(self.controller.target, WINDOW_B)
        self.assertFalse(self.controller.selecting)
        self.assert_no_submission()

    def test_stale_enrichment_after_a_new_hidden_drop_cannot_reopen_or_replace_it(self):
        self.controller.button.dropped.emit(200, 200)
        self.finish(value=EXPLORER)
        self.assertTrue(self.controller.selecting)
        self.assert_hidden()
        self.controller.button.dropped.emit(200, 200)
        # New fast result arrives ahead of the previous Explorer enrichment.
        self.finish(1, value=WINDOW_B)
        self.assert_hidden()
        self.finish(value=ENRICHED)
        self.assert_hidden()
        self.assertEqual(self.controller.target, WINDOW_B)
        self.assertFalse(self.controller.selecting)
        self.assert_no_submission()

    def test_cancelled_drag_restores_the_original_open_panel_and_draft(self):
        self.controller.target = WINDOW_A
        self.controller.open_panel()
        self.controller.panel.editor.setPlainText("Restore this unsent draft")
        self.controller.preview = True
        self.controller.drag_started()
        self.assert_hidden()
        self.controller.drag_cancelled()
        self.assertTrue(self.controller.panel.isVisible())
        self.assertEqual(self.controller.panel.editor.toPlainText(), "Restore this unsent draft")
        self.assertEqual(self.controller.target, WINDOW_A)
        self.assertEqual(self.workers, [])
        self.mocks["capture_target"].assert_not_called()
        self.assert_no_submission()


if __name__ == "__main__":
    unittest.main()
