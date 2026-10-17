"""Exercise staged selection races through real Qt controls, without native I/O."""
from dataclasses import replace
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QListWidget, QMenu, QPushButton
from shiboken6 import isValid

from codex_pointer.app import PointerController
from codex_pointer.bridge import CodexBridge, ThreadSummary
from codex_pointer.routing import binding_for, recent_targets
from codex_pointer.windows import TargetContext


CHAT_A = "c053ab24-ef0b-4d9a-91de-1e68f6119f23"
FOLDER_A = TargetContext(kind="folder", title="A", path=r"C:\Projects\A", source="folder-picker")
FOLDER_B = TargetContext(kind="folder", title="B", path=r"C:\Projects\B", source="folder-picker")
EXPLORER_A = TargetContext(kind="window", title="Explorer", hwnd=41,
    process_name="explorer.exe", process_path=r"C:\Windows\explorer.exe",
    rect=(0, 0, 800, 600), point=(200, 200), explorer=True)
ENRICHED_A = replace(FOLDER_A, hwnd=41, explorer=True, source="explorer-hit-test")
_UNSET = object()


class TargetSwitchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.workers = []
        self.bridge = Mock(spec=CodexBridge)
        self.bridge.list_threads.return_value = [ThreadSummary(CHAT_A, "项目 A 对话", r"C:\Projects\A", "A")]
        replacements = {
            "CodexBridge": {"return_value": self.bridge},
            "save_settings": {},
            "cancel_capture_lookup": {},
            "close_capture_helpers": {},
            "enrich_target": {"return_value": ENRICHED_A},
            "get_cursor_position": {"return_value": (200, 200)},
            "capture_target": {"side_effect": AssertionError("Unexpected native target capture")},
            "capture_window": {"side_effect": AssertionError("Unexpected native window capture")},
            "capture_screenshot": {"side_effect": AssertionError("Unexpected screenshot")},
            "save_capture": {"side_effect": AssertionError("Unexpected submission")},
        }
        self.mocks = {}
        for name, options in replacements.items():
            patcher = patch(f"codex_pointer.app.{name}", **options)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)
        guard = patch("codex_pointer.app.threading.Thread", side_effect=AssertionError("Unexpected real worker"))
        guard.start()
        self.addCleanup(guard.stop)
        # Preview construction avoids global hotkeys and foreground polling.
        self.controller = PointerController(self.application, preview=True, theme="light", reduced_motion=True)
        self.controller.run_worker = lambda work, done, failed: self.workers.append((work, done, failed))
        self.controller.preview = False
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

    def finish_worker(self, index=0, *, value=_UNSET, error=None):
        """Deliver a queued result in the order a test chooses, with no sleep."""
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

    def select_folder(self, target):
        self.controller.capture(lambda: target)
        self.assertTrue(self.controller.selecting)
        self.finish_worker()
        self.assertEqual(self.controller.target, target)
        self.assertFalse(self.controller.selecting)

    def bind_a_with_picker(self):
        self.controller.panel.existing_button.click()
        self.controller.pick_thread()
        self.finish_worker()
        picker = self.controller.picker
        listing = picker.findChild(QListWidget)
        self.assertEqual(listing.count(), 1)
        listing.setCurrentRow(0)
        next(button for button in picker.findChildren(QPushButton)
             if button.text() == "使用这条对话").click()
        self.assertEqual(binding_for(self.controller.settings, FOLDER_A)["thread_id"], CHAT_A)

    def assert_no_dispatch(self):
        self.bridge.send_new.assert_not_called()
        self.bridge.send_existing.assert_not_called()
        self.bridge.open_new_draft.assert_not_called()
        self.mocks["save_capture"].assert_not_called()
        self.mocks["capture_screenshot"].assert_not_called()

    def test_fast_a_then_b_ignores_old_result_and_only_applies_b(self):
        self.controller.capture(lambda: FOLDER_A)
        panel = self.controller.panel
        self.controller.capture(lambda: FOLDER_B)
        # One active fast job, one replacement. A's callback cannot update B.
        self.assertEqual(len(self.workers), 1)
        self.finish_worker()
        self.assertIsNone(self.controller.target)
        self.assertTrue(self.controller.selecting)
        self.assertEqual(len(self.workers), 1)
        self.finish_worker()
        self.assertEqual(self.controller.target, FOLDER_B)
        self.assertEqual(panel.target_title.toolTip(), "B")
        self.assertFalse(self.controller.selecting)
        self.assertEqual([row["path"] for row in recent_targets(self.controller.settings)], [FOLDER_B.path])
        self.assert_no_dispatch()

    def test_repeated_changes_keep_only_latest_waiting_fast_lookup(self):
        discarded = Mock(return_value=FOLDER_A)
        final = replace(FOLDER_B, path=r"C:\Projects\C", title="C")
        self.controller.capture(lambda: FOLDER_A)
        self.controller.capture(discarded)
        self.controller.capture(lambda: final)
        self.finish_worker()
        self.assertEqual(len(self.workers), 1)
        self.finish_worker()
        discarded.assert_not_called()
        self.assertEqual(self.controller.target, final)
        self.assert_no_dispatch()

    def test_explorer_enrichment_keeps_editor_editable_and_new_target_selectable(self):
        self.controller.capture(lambda: EXPLORER_A)
        self.finish_worker()
        panel = self.controller.panel
        self.assertEqual(self.controller.target, EXPLORER_A)
        self.assertTrue(self.controller.selecting)
        self.assertFalse(panel.editor.isReadOnly())
        panel.editor.insertPlainText("识别时继续输入任务")
        self.assertFalse(panel.primary.isEnabled())
        self.assertTrue(panel.change_target.isEnabled())
        self.assertTrue(panel.close_button.isEnabled())
        panel.primary.click()
        self.assert_no_dispatch()
        self.mocks["cancel_capture_lookup"].reset_mock()
        with patch("codex_pointer.app.QFileDialog.getExistingDirectory", return_value=FOLDER_B.path):
            panel.change_target.click()
        self.mocks["cancel_capture_lookup"].assert_called()
        self.assertEqual(len(self.workers), 2)
        # Finish B's fast job before the older Explorer A enrichment.
        self.finish_worker(1)
        self.assertEqual(self.controller.target.path, FOLDER_B.path)
        self.assertEqual(panel.editor.toPlainText(), "识别时继续输入任务")
        self.assertTrue(panel.primary.isEnabled())
        self.finish_worker(0)
        self.assertEqual(self.controller.target.path, FOLDER_B.path)
        self.assertEqual(panel.target_title.toolTip(), "B")
        self.assertTrue(panel.primary.isEnabled())
        self.assert_no_dispatch()

    def test_old_enrichment_failure_cannot_clear_the_new_target(self):
        self.controller.capture(lambda: EXPLORER_A)
        self.finish_worker()
        self.controller.capture(lambda: FOLDER_B)
        self.finish_worker(1)
        self.finish_worker(0, error=RuntimeError("stale Explorer failure"))
        self.assertEqual(self.controller.target, FOLDER_B)
        self.assertNotIn("stale Explorer failure", self.controller.panel.notice.text())
        self.assertFalse(self.controller.selecting)
        self.assert_no_dispatch()

    def test_closing_during_fast_lookup_prevents_late_reopen(self):
        self.controller.capture(lambda: FOLDER_A)
        panel = self.controller.panel
        panel.editor.setPlainText("未发送任务")
        panel.close()
        self.assertFalse(panel.isVisible())
        with patch.object(self.controller, "open_panel", wraps=self.controller.open_panel) as reopen:
            self.finish_worker()
            reopen.assert_not_called()
        self.assertFalse(panel.isVisible())
        self.assertIsNone(self.controller.target)
        self.assertFalse(self.controller.selecting)
        self.assertEqual(self.controller.draft, "未发送任务")
        self.assertEqual(recent_targets(self.controller.settings), [])
        self.assert_no_dispatch()

    def test_closing_discards_waiting_replacement_work(self):
        waiting = Mock(return_value=FOLDER_B)
        self.controller.capture(lambda: FOLDER_A)
        self.controller.capture(waiting)
        self.controller.panel.close()
        self.finish_worker()
        self.assertEqual(self.workers, [])
        waiting.assert_not_called()
        self.assertFalse(self.controller.panel.isVisible())
        self.assert_no_dispatch()

    def test_closing_during_enrichment_ignores_the_late_result(self):
        self.controller.capture(lambda: EXPLORER_A)
        self.finish_worker()
        panel = self.controller.panel
        panel.editor.setPlainText("保留输入")
        panel.close()
        with patch.object(self.controller, "open_panel", wraps=self.controller.open_panel) as reopen:
            self.finish_worker()
            reopen.assert_not_called()
        self.assertFalse(panel.isVisible())
        self.assertIsNone(self.controller.target)
        self.assertFalse(self.controller.selecting)
        self.assertEqual(self.controller.draft, "保留输入")
        self.assertEqual(recent_targets(self.controller.settings), [])
        self.controller.open_panel()
        self.assertTrue(panel.isVisible())
        self.assertEqual(panel.editor.toPlainText(), "保留输入")
        self.assertFalse(panel.primary.isEnabled())
        panel.primary.click()
        self.assert_no_dispatch()

    def test_explicit_folder_binding_is_restored_only_when_returning_to_a(self):
        self.select_folder(FOLDER_A)
        self.bind_a_with_picker()
        self.assertEqual(self.controller.mode, "existing")
        self.select_folder(FOLDER_B)
        self.assertNotIn("thread_id", self.controller.settings)
        self.assertNotIn("thread_title", self.controller.settings)
        self.assertEqual(self.controller.mode, "new")
        self.select_folder(FOLDER_A)
        self.assertEqual(self.controller.settings["thread_id"], CHAT_A)
        self.assertEqual(self.controller.settings["thread_title"], "项目 A 对话")
        self.assertEqual(self.controller.mode, "existing")
        self.assertTrue(self.controller.panel.existing_button.isChecked())
        self.assertIn("恢复", self.controller.panel.notice.text())
        self.assert_no_dispatch()

    def test_new_mode_remembers_the_choice_but_keeps_a_binding_for_later(self):
        self.select_folder(FOLDER_A)
        self.bind_a_with_picker()
        self.controller.panel.new_button.click()
        self.assertEqual(self.controller.mode, "new")
        self.assertEqual(binding_for(self.controller.settings, FOLDER_A)["thread_id"], CHAT_A)
        self.select_folder(FOLDER_B)
        self.select_folder(FOLDER_A)
        self.assertEqual(self.controller.mode, "new")
        self.assertTrue(self.controller.panel.new_button.isChecked())
        self.assertEqual(self.controller.settings["thread_id"], CHAT_A)
        self.controller.panel.existing_button.click()
        self.assertEqual(self.controller.mode, "existing")
        self.assertEqual(self.controller.settings["thread_id"], CHAT_A)
        self.assert_no_dispatch()

    def test_canceled_drag_closes_stale_picker_and_a_reopened_picker_can_bind(self):
        self.select_folder(FOLDER_A)
        self.controller.panel.existing_button.click()
        self.controller.pick_thread()
        self.finish_worker()
        old_picker = self.controller.picker
        old_picker.findChild(QListWidget).setCurrentRow(0)
        self.controller.preview = True  # No real global Esc hotkey registration.
        self.controller.drag_started()
        self.controller.drag_cancelled()
        self.controller.preview = False
        self.assertFalse(old_picker.isVisible())
        self.assertIsNone(self.controller.picker)
        self.assertTrue(self.controller.panel.isVisible())
        self.controller.pick_thread()
        self.finish_worker()
        reopened = self.controller.picker
        self.assertIsNot(reopened, old_picker)
        reopened.findChild(QListWidget).setCurrentRow(0)
        next(button for button in reopened.findChildren(QPushButton)
             if button.text() == "使用这条对话").click()
        self.assertEqual(binding_for(self.controller.settings, FOLDER_A)["thread_id"], CHAT_A)
        self.assertEqual(self.controller.mode, "existing")
        self.assert_no_dispatch()

    def test_recent_target_reselection_has_no_stale_window_handle_or_screenshot(self):
        selected = replace(FOLDER_A, hwnd=987, rect=(10, 20, 100, 200), point=(50, 50))
        self.select_folder(selected)
        rows = recent_targets(self.controller.settings)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("hwnd", rows[0])
        self.assertNotIn("rect", rows[0])
        self.assertNotIn("point", rows[0])
        menu = QMenu(self.controller.panel)
        self.controller.add_recent_menu(menu)
        actions = menu.actions()  # Keep QAction wrappers alive with PySide 6.7.
        recent = actions[0].menu()
        entries = recent.actions()
        entries[0].trigger()
        self.finish_worker()
        self.assertEqual(self.controller.target.path, FOLDER_A.path)
        self.assertEqual(self.controller.target.hwnd, 0)
        self.assertEqual(self.controller.target.source, "recent")
        self.assertFalse(self.controller.panel.include_image.isEnabled())
        self.assert_no_dispatch()


if __name__ == "__main__":
    unittest.main()
