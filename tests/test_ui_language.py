"""Switch the visible UI language without modifying user-authored state."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QTextCursor
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from codex_pointer.i18n import language, set_language
from codex_pointer.panel import TaskPanel
from codex_pointer.target_preview import TargetPreview
from codex_pointer.ui import FloatingButton, apply_theme, theme_for
from codex_pointer.windows import TargetContext


class NativeLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.original_language = language()
        set_language("zh-CN")
        self.theme = theme_for("light")
        apply_theme(self.application, self.theme)
        self.controller = SimpleNamespace(
            theme=self.theme, reduced_motion=True, busy=False, selecting=False,
            mode="existing", draft="", settings={"thread_id": "bound-id", "thread_title": "用户对话名称"},
            target=TargetContext(title="用户窗口名称", hwnd=42, process_path="C:/Editor.exe"),
        )
        for method in ("toggle_theme", "choose_folder", "set_mode", "pick_thread", "invalidate_image",
                       "preview_image", "show_details_menu", "primary_action", "cancel_selection"):
            setattr(self.controller, method, Mock())
        self.panel = TaskPanel(self.controller)
        self.button = FloatingButton(self.theme, reduced_motion=True)
        self.preview = TargetPreview(self.theme, reduced_motion=True)

    def tearDown(self):
        set_language(self.original_language)
        self.controller.busy = False
        self.preview.hide_preview()
        for widget in (self.panel, self.button, self.preview):
            widget.close()
            widget.deleteLater()
        self.application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.application.processEvents()

    def test_panel_retranslation_preserves_draft_selection_target_binding_and_screenshot(self):
        panel = self.panel
        panel.editor.setPlainText("Keep my draft\n用户写的原文")
        cursor = panel.editor.textCursor()
        cursor.setPosition(2)
        cursor.setPosition(10, QTextCursor.MoveMode.KeepAnchor)
        panel.editor.setTextCursor(cursor)
        panel.include_image.setChecked(True)
        panel.show_notice("未能识别目标：{error}", error="Example {literal braces}")
        self.controller.invalidate_image.reset_mock()
        target = self.controller.target
        original = panel.editor.toPlainText()
        selection = (cursor.position(), cursor.anchor(), cursor.selectedText())
        set_language("en-US")
        panel.retranslate_ui()
        self.assertEqual(panel.existing_button.text(), "Continue chat")
        self.assertIn("Switch", panel.theme_button.toolTip())
        self.assertIn("Could not identify", panel.notice.text())
        self.assertIn("Example {literal braces}", panel.notice.text())
        self.assertEqual(panel.editor.toPlainText(), original)
        current = panel.editor.textCursor()
        self.assertEqual((current.position(), current.anchor(), current.selectedText()), selection)
        self.assertIs(self.controller.target, target)
        self.assertEqual(panel.target_title.toolTip(), "用户窗口名称")
        self.assertEqual(panel.bound_title.toolTip(), "用户对话名称")
        self.assertTrue(panel.include_image.isChecked())
        self.assertTrue(panel.existing_button.isChecked())
        self.assertEqual(self.controller.settings["thread_id"], "bound-id")
        self.controller.invalidate_image.assert_not_called()
        self.controller.primary_action.assert_not_called()
        set_language("zh-CN")
        panel.retranslate_ui()
        self.assertIn("未能识别目标", panel.notice.text())
        self.assertEqual(panel.editor.toPlainText(), original)

    def test_retranslation_keeps_pending_selection_editable_and_submission_disabled(self):
        self.controller.selecting = True
        self.controller.target = None
        self.panel.refresh_target()
        self.panel.editor.setPlainText("Still writing while a target resolves")
        set_language("en-US")
        self.panel.retranslate_ui()
        self.assertIn("Identifying", self.panel.target_title.toolTip())
        self.assertFalse(self.panel.editor.isReadOnly())
        self.assertFalse(self.panel.primary.isEnabled())
        self.assertTrue(self.controller.selecting)
        self.assertEqual(self.panel.editor.toPlainText(), "Still writing while a target resolves")

    def test_button_retranslation_keeps_external_drop_highlight_without_selecting(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile("C:/Example/用户文件.txt")])
        event = QDragEnterEvent(QPoint(36, 36), Qt.DropAction.CopyAction, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        files = QSignalSpy(self.button.file_dropped)
        with patch("codex_pointer.ui.QToolTip.showText"):
            self.button.dragEnterEvent(event)
            position = self.button.pos()
            self.assertTrue(event.isAccepted())
            set_language("en-US")
            self.button.retranslate_ui()
        self.assertIn("Release", self.button.toolTip())
        self.assertTrue(self.button._file_drag)
        self.assertEqual(self.button.pos(), position)
        self.assertEqual(files.count(), 0)

    def test_hidden_target_preview_stays_hidden_and_keeps_user_target_name(self):
        target = TargetContext(kind="folder", path="D:/Projects/用户目录", source="explorer-hit-test")
        self.preview.show_context(target, QPoint(300, 300))
        self.preview.hide_preview()
        set_language("en-US")
        with patch.object(self.preview, "_show_outline") as outline:
            self.preview.retranslate_ui()
        outline.assert_not_called()
        self.assertFalse(self.preview.isVisible())
        self.assertEqual(self.preview._tag, "Folder")
        self.assertEqual(self.preview._title, "用户目录")
        self.assertIs(self.preview._context, target)
        self.assertTrue(all(not window.isVisible() for window in self.preview._outlines))


if __name__ == "__main__":
    unittest.main()
