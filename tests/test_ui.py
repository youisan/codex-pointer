"""Exercise dispatch and consent through the real Qt controls, entirely offline."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QRect
from PySide6.QtWidgets import QApplication, QDialog, QListWidget, QPushButton

from codex_pointer.app import PointerController
from codex_pointer.bridge import CodexBridge, DispatchResult, ThreadSummary
from codex_pointer.windows import TargetContext


THREAD_ID = "01a1471e-0dbd-7bc1-8af3-487b6823c35f"


class PointerUiTests(unittest.TestCase):
    def test_folder_hit_shows_the_item_name_instead_of_explorer_window_title(self):
        self.controller.target = TargetContext(kind="folder", title="Explorer parent window",
                                               path="D:/Projects/selected-folder")
        self.controller.panel.refresh_target()
        self.assertEqual(self.controller.panel.target_title.toolTip(), "selected-folder")

    def test_expanding_conversation_row_keeps_the_primary_action_on_screen(self):
        panel = self.controller.panel
        available = panel.screen().availableGeometry()
        panel.move(available.left(), available.bottom() - panel.height() + 1)
        panel.set_mode("existing")
        self.application.processEvents()
        self.assertTrue(available.contains(panel.geometry()))
        self.assertTrue(panel.primary.isVisible())

    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bridge = Mock(spec=CodexBridge)
        self.bridge.open_new_draft.return_value = DispatchResult("", "desktop-deep-link", "draft_opened")
        self.bridge.send_existing.return_value = DispatchResult(THREAD_ID, "shared-app-server", "queued")
        self.bridge.list_threads.return_value = [
            ThreadSummary(THREAD_ID, "Selected conversation", self.temp.name, "Preview")
        ]
        self.mocks = {}
        replacements = {
            "CodexBridge": {"return_value": self.bridge},
            "data_directory": {"return_value": self.directory},
            "save_capture": {"return_value": (THREAD_ID, self.directory / "context.json")},
            "working_directory": {"return_value": self.temp.name},
            "capture_screenshot": {},
            "capture_target": {},
            "capture_window": {},
            "save_settings": {},
        }
        for name, options in replacements.items():
            patcher = patch(f"codex_pointer.app.{name}", **options)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)
        # Accidentally reaching the production worker must fail instead of
        # creating a background thread or contacting a real Codex process.
        thread_guard = patch("codex_pointer.app.threading.Thread", side_effect=AssertionError("Unexpected thread"))
        thread_guard.start()
        self.addCleanup(thread_guard.stop)
        timers = patch("codex_pointer.app.QTimer.singleShot", side_effect=lambda delay, callback: callback())
        timers.start()
        self.addCleanup(timers.stop)
        self.controller = PointerController(self.application, preview=True, theme="light", reduced_motion=True)
        self.controller.run_worker = self._run_synchronously
        self.controller.target = TargetContext(kind="folder", title="Project", path=self.temp.name)
        self.controller.open_panel()
        # Construction stays in preview mode to avoid registering global
        # hotkeys or tracking the real foreground window. Dispatch is mocked.
        self.controller.preview = False
        self.addCleanup(self._dispose_controller)

    @staticmethod
    def _run_synchronously(work, done, failed):
        try:
            value = work()
        except Exception as error:
            failed(error)
        else:
            done(value)

    def _dispose_controller(self):
        self.controller.busy = False
        self.controller.cleanup()
        self.controller.position_save_timer.stop()
        for widget in self.application.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        self.application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.application.processEvents()

    def _window_target(self):
        self.controller.target = TargetContext(kind="window", title="Editor", hwnd=42,
            process_name="editor.exe", rect=(100, 100, 1200, 800), point=(700, 500))
        self.controller.panel.refresh_target()

    def test_default_new_action_opens_draft_without_sending(self):
        panel = self.controller.panel
        panel.editor.setPlainText("Summarize this folder")
        panel.primary.click()
        self.bridge.open_new_draft.assert_called_once()
        prompt, directory = self.bridge.open_new_draft.call_args.args
        self.assertIn("Summarize this folder", prompt)
        self.assertEqual(directory, self.temp.name)
        self.bridge.send_new.assert_not_called()
        self.bridge.send_existing.assert_not_called()
        self.mocks["capture_screenshot"].assert_not_called()
        self.assertIn("确认后发送", panel.notice.text())

    def test_unbound_existing_action_selects_conversation_even_without_task(self):
        panel = self.controller.panel
        self.controller.target = None
        panel.refresh_target()
        panel.set_mode("existing")
        self.assertTrue(panel.primary.isEnabled())
        with patch.object(self.controller, "pick_thread") as select:
            panel.primary.click()
        select.assert_called_once_with()
        self.bridge.send_existing.assert_not_called()
        self.bridge.list_threads.assert_not_called()
        self.assertNotIn("thread_id", self.controller.settings)

    def test_thread_list_does_not_implicitly_bind_first_or_latest_conversation(self):
        self.controller.panel.set_mode("existing")
        self.controller.pick_thread()
        picker = self.controller.picker
        listing = picker.findChild(QListWidget)
        self.assertEqual(listing.count(), 1)
        self.assertIsNone(listing.currentItem())
        bind = next(button for button in picker.findChildren(QPushButton)
                    if button.text() == "使用这条对话")
        bind.click()
        self.assertNotIn("thread_id", self.controller.settings)
        self.bridge.send_existing.assert_not_called()
        self.assertTrue(picker.isVisible())

    def test_existing_action_uses_only_explicit_bound_identifier(self):
        self.controller.settings.update(thread_id=THREAD_ID, thread_title="Bound conversation")
        panel = self.controller.panel
        panel.set_mode("existing")
        panel.editor.setPlainText("Inspect this folder")
        panel.primary.click()
        self.bridge.send_existing.assert_called_once()
        self.assertEqual(self.bridge.send_existing.call_args.args[0], THREAD_ID)
        self.bridge.list_threads.assert_not_called()
        self.bridge.open_new_draft.assert_not_called()
        self.assertIn("已排队", panel.notice.text())

    def test_empty_task_cannot_dispatch(self):
        panel = self.controller.panel
        panel.editor.setPlainText("  \n ")
        self.assertFalse(panel.primary.isEnabled())
        self.controller.primary_action()
        self.mocks["save_capture"].assert_not_called()
        self.bridge.open_new_draft.assert_not_called()
        self.bridge.send_existing.assert_not_called()

    def test_nearby_screenshot_is_explicitly_cropped_and_hides_own_windows(self):
        self._window_target()
        panel = self.controller.panel
        panel.editor.setPlainText("Explain the selected window")
        panel.include_image.setChecked(True)
        self.controller.set_scope("nearby")
        self.controller.button.show()
        preview = QDialog(panel)
        preview.show()
        seen = []

        def capture(target, output, *, crop_rect):
            seen.append((panel.isVisible(), self.controller.button.isVisible(), preview.isVisible()))
            self.assertEqual(target, self.controller.target)
            self.assertEqual(crop_rect, (380, 260, 1020, 740))
            output.write_bytes(b"\x89PNG\r\n\x1a\nmock")
            return output

        self.mocks["capture_screenshot"].side_effect = capture
        panel.primary.click()
        self.assertEqual(seen, [(False, False, False)])
        self.assertTrue(panel.isVisible())
        self.assertTrue(self.controller.button.isVisible())
        self.assertTrue(preview.isVisible())
        self.assertIsNotNone(self.mocks["save_capture"].call_args.args[2])
        self.assertFalse(self.controller.busy)

    def test_unchecked_screenshot_omits_a_cached_preview(self):
        self._window_target()
        image = self.directory / "old-preview.png"
        image.write_bytes(b"cached preview")
        self.controller.image_path, self.controller.cached_scope = image, "window"
        panel = self.controller.panel
        panel.editor.setPlainText("Read the window title")
        panel.include_image.setChecked(False)
        panel.primary.click()
        self.mocks["capture_screenshot"].assert_not_called()
        self.assertIsNone(self.mocks["save_capture"].call_args.args[2])

    def test_theme_change_preserves_task_target_mode_and_screenshot_selection(self):
        self._window_target()
        self.controller.settings.update(thread_id=THREAD_ID, thread_title="Bound")
        panel = self.controller.panel
        panel.set_mode("existing")
        panel.editor.setPlainText("Keep this draft\nwith another line")
        panel.include_image.setChecked(True)
        target = self.controller.target
        self.controller.toggle_theme()
        replacement = self.controller.panel
        self.assertIsNot(replacement, panel)
        self.assertEqual(self.controller.theme.name, "dark")
        self.assertEqual(replacement.editor.toPlainText(), "Keep this draft\nwith another line")
        self.assertEqual(self.controller.target, target)
        self.assertEqual(self.controller.mode, "existing")
        self.assertTrue(replacement.existing_button.isChecked())
        self.assertTrue(replacement.include_image.isChecked())
        self.assertEqual(self.controller.settings["thread_id"], THREAD_ID)
        self.bridge.open_new_draft.assert_not_called()

    def test_close_and_reopen_preserves_unsubmitted_task(self):
        panel = self.controller.panel
        panel.editor.setPlainText("Unsubmitted draft")
        panel.close()
        self.assertFalse(panel.isVisible())
        self.controller.open_panel()
        self.assertIs(self.controller.panel, panel)
        self.assertEqual(panel.editor.toPlainText(), "Unsubmitted draft")
        self.assertTrue(panel.isVisible())
        self.bridge.open_new_draft.assert_not_called()

    def test_show_button_only_reveals_pointer_without_capture_or_dispatch(self):
        panel = self.controller.panel
        panel.editor.setPlainText("Keep this draft")
        panel.hide()
        self.controller.button.hide()
        self.controller.show_button()
        self.assertTrue(self.controller.button.isVisible())
        self.assertFalse(panel.isVisible())
        self.assertEqual(panel.editor.toPlainText(), "Keep this draft")
        for name in ("capture_target", "capture_window", "capture_screenshot", "save_capture"):
            self.mocks[name].assert_not_called()
        self.bridge.open_new_draft.assert_not_called()
        self.bridge.send_new.assert_not_called()
        self.bridge.send_existing.assert_not_called()

    def test_hide_preserves_draft_target_and_options_for_reopen(self):
        self._window_target()
        panel = self.controller.panel
        panel.set_mode("existing")
        panel.editor.setPlainText("Unsubmitted task\nwith details")
        panel.include_image.setChecked(True)
        target = self.controller.target
        self.controller.button.show()
        self.controller.hide_button()
        self.assertFalse(panel.isVisible())
        self.assertFalse(self.controller.button.isVisible())
        self.assertEqual(self.controller.draft, "Unsubmitted task\nwith details")
        self.assertEqual(self.controller.target, target)
        self.controller.show_button()
        self.controller.open_panel()
        self.assertIs(self.controller.panel, panel)
        self.assertEqual(panel.editor.toPlainText(), "Unsubmitted task\nwith details")
        self.assertTrue(panel.include_image.isChecked())
        self.assertEqual(self.controller.mode, "existing")
        self.mocks["save_capture"].assert_not_called()
        self.bridge.open_new_draft.assert_not_called()
        self.bridge.send_existing.assert_not_called()

    def test_hide_event_waits_for_busy_work_then_preserves_draft(self):
        panel = self.controller.panel
        panel.editor.setPlainText("Waiting task")
        self.controller.button.show()
        events = self.controller.control_events = Mock()
        events.poll.return_value = (False, True)
        self.controller.busy = True
        self.controller.poll_controls()
        self.assertTrue(self.controller.hide_pending)
        self.assertTrue(panel.isVisible())
        self.assertTrue(self.controller.button.isVisible())
        self.controller.busy = False
        events.poll.return_value = (False, False)
        self.controller.poll_controls()
        self.assertFalse(self.controller.hide_pending)
        self.assertFalse(panel.isVisible())
        self.assertFalse(self.controller.button.isVisible())
        self.assertEqual(self.controller.draft, "Waiting task")
        self.bridge.send_existing.assert_not_called()
        self.mocks["capture_screenshot"].assert_not_called()

    def test_later_show_cancels_hide_pending_during_busy_work(self):
        self.controller.button.show()
        events = self.controller.control_events = Mock()
        events.poll.return_value = (False, True)
        self.controller.busy = True
        self.controller.poll_controls()
        self.assertTrue(self.controller.hide_pending)
        events.poll.return_value = (True, False)
        self.controller.poll_controls()
        self.assertFalse(self.controller.hide_pending)
        self.controller.busy = False
        events.poll.return_value = (False, False)
        self.controller.poll_controls()
        self.assertTrue(self.controller.button.isVisible())
        self.assertTrue(self.controller.panel.isVisible())

    def test_show_while_busy_waits_to_reveal_until_idle(self):
        self.controller.button.hide()
        self.controller.panel.hide()
        self.controller.busy = True
        events = self.controller.control_events = Mock()
        events.poll.return_value = (True, False)
        self.controller.poll_controls()
        self.assertFalse(self.controller.button.isVisible())
        self.assertFalse(self.controller.panel.isVisible())
        self.assertTrue(self.controller.show_pending)
        self.controller.busy = False
        events.poll.return_value = (False, False)
        self.controller.poll_controls()
        self.assertTrue(self.controller.button.isVisible())
        self.assertFalse(self.controller.panel.isVisible())
        self.assertFalse(self.controller.show_pending)

    def test_broken_control_channel_stops_polling_and_releases_handles(self):
        events = self.controller.control_events = Mock()
        events.poll.side_effect = OSError("Invalid handle")
        timer = self.controller.control_timer = Mock()
        self.controller.poll_controls()
        timer.stop.assert_called_once()
        events.close.assert_called_once()

    def test_show_wins_when_both_event_requests_arrive_together(self):
        self.controller.hide_button()
        events = self.controller.control_events = Mock()
        events.poll.return_value = (True, True)
        self.controller.poll_controls()
        self.assertTrue(self.controller.button.isVisible())
        self.assertFalse(self.controller.hide_pending)

    def test_control_timer_setup_and_cleanup_use_mocked_native_events(self):
        events = Mock()
        events.poll.return_value = (False, False)
        with patch("codex_pointer.app.ControlEvents", return_value=events):
            self.controller.enable_controls()
        timer = self.controller.control_timer
        self.assertTrue(timer.isActive())
        self.assertEqual(timer.interval(), 200)
        self.controller.cleanup()
        self.assertFalse(timer.isActive())
        events.close.assert_called_once()

    def test_reduced_motion_stops_running_effects_and_reveal_stays_onscreen(self):
        self.controller.set_reduced_motion(False)
        self.controller.button.set_busy(True)
        self.assertTrue(self.controller.button._busy_timer.isActive())
        self.controller.panel.hide()
        self.controller.panel.reveal(QRect(790, 790, 72, 72))
        self.controller.set_reduced_motion(True)
        self.assertTrue(self.controller.button.reduced_motion)
        self.assertTrue(self.controller.panel.reduced_motion)
        self.assertFalse(self.controller.button._busy_timer.isActive())
        self.assertEqual(self.controller.panel.windowOpacity(), 1.0)
        available = self.controller.panel.screen().availableGeometry()
        self.assertTrue(available.contains(self.controller.panel.geometry()))
        self.assertTrue(self.controller.settings["reduced_motion"])


if __name__ == "__main__":
    unittest.main()
