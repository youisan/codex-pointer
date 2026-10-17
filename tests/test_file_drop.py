"""Local file URL drag events stay explicit, reversible and filesystem-free."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from codex_pointer.drop_targets import DropTargetError, parse_local_file_urls
from codex_pointer.ui import FloatingButton, theme_for


class LocalFileUrlTests(unittest.TestCase):
    def test_drive_path_preserves_unicode_spaces_and_encoded_url_delimiters(self):
        self.assertEqual(parse_local_file_urls([
            "file:///C:/Project%20notes/%E6%96%87%E4%BB%B6%20%23%3F.txt"]),
            "C:/Project notes/文件 #?.txt")

    def test_unc_share_is_retained_without_network_access(self):
        self.assertEqual(parse_local_file_urls([
            "file://server/share/Folder%20one/%E8%B5%84%E6%96%99.pdf"]),
            "//server/share/Folder one/资料.pdf")

    def test_zero_or_multiple_urls_are_not_silently_reduced(self):
        for urls in ([], ["file:///C:/one", "file:///C:/two"]):
            with self.subTest(urls=urls), self.assertRaisesRegex(DropTargetError, "一个"):
                parse_local_file_urls(urls)

    def test_nonlocal_and_ambiguous_urls_are_rejected(self):
        for url in ("https://example.org/file.txt", "ftp://server/file", "C:/one.txt",
                    "file:C:/relative", "file://user@server/share/a", "file:///C:/a?query=1",
                    "file:///C:/a#fragment", "file:///C:/bad%00name", "file:///C:/bad%FF",
                    "file:///C:/bad%zz", "file://server/"):
            with self.subTest(url=url), self.assertRaises(DropTargetError):
                parse_local_file_urls([url])

    def test_localhost_file_uri_is_local_drive(self):
        self.assertEqual(parse_local_file_urls(["file://localhost/C:/Folder/one.txt"]),
                         "C:/Folder/one.txt")


class FileDropEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.button = FloatingButton(theme_for("light"), reduced_motion=True)
        self.button.move(120, 120)
        self.button.show()
        self.application.processEvents()
        self.files = QSignalSpy(self.button.file_dropped)
        self.targets = QSignalSpy(self.button.dropped)
        self.clicks = QSignalSpy(self.button.clicked)
        self.moves = QSignalSpy(self.button.moved)
        tooltip_patch = patch("codex_pointer.ui.QToolTip.showText")
        self.tooltip = tooltip_patch.start()
        self.addCleanup(tooltip_patch.stop)

    def tearDown(self):
        self.button.close()
        self.button.deleteLater()
        self.application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.application.processEvents()

    @staticmethod
    def mime_for(*urls):
        mime = QMimeData()
        mime.setUrls([QUrl(value) for value in urls])
        return mime

    def enter(self, mime):
        event = QDragEnterEvent(QPoint(36, 36), Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
                                mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.application.sendEvent(self.button, event)
        return event

    def drop(self, mime):
        event = QDropEvent(QPointF(36, 36), Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
                           mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.application.sendEvent(self.button, event)
        return event

    def test_single_local_file_drop_emits_only_file_signal_without_moving(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile("C:/Project notes/资料 one.txt")])
        origin = self.button.pos()
        entered = self.enter(mime)
        self.assertTrue(entered.isAccepted())
        self.assertTrue(self.button._file_drag)
        self.assertEqual(entered.dropAction(), Qt.DropAction.CopyAction)
        dropped = self.drop(mime)
        self.assertTrue(dropped.isAccepted())
        self.assertEqual(self.files.count(), 1)
        self.assertEqual(self.files.at(0), ["C:/Project notes/资料 one.txt"])
        self.assertEqual(self.targets.count(), 0)
        self.assertEqual(self.clicks.count(), 0)
        self.assertEqual(self.moves.count(), 0)
        self.assertEqual(self.button.pos(), origin)
        self.assertFalse(self.button._file_drag)
        self.assertEqual(self.button.toolTip(), self.button._default_tooltip)

    def test_single_folder_and_unc_path_are_accepted_without_filesystem_checks(self):
        for url, expected in [
            ("file:///D:/Never%20opened/%E9%A1%B9%E7%9B%AE", "D:/Never opened/项目"),
            ("file://offline-server/Unreachable%20Share/%E8%B5%84%E6%96%99", "//offline-server/Unreachable Share/资料"),
        ]:
            with self.subTest(url=url):
                self.files = QSignalSpy(self.button.file_dropped)
                mime = self.mime_for(url)
                with patch.object(Path, "exists", side_effect=AssertionError("UI filesystem access")), \
                        patch.object(Path, "stat", side_effect=AssertionError("UI filesystem access")), \
                        patch.object(Path, "resolve", side_effect=AssertionError("UI filesystem access")):
                    self.assertTrue(self.enter(mime).isAccepted())
                    self.assertTrue(self.drop(mime).isAccepted())
                self.assertEqual(self.files.at(0), [expected])

    def test_multiple_files_are_rejected_with_an_explanation(self):
        event = self.enter(self.mime_for("file:///C:/one", "file:///C:/two"))
        self.assertFalse(event.isAccepted())
        self.assertFalse(self.button._file_drag)
        self.assertIn("一个", self.button.toolTip())
        self.assertEqual(self.files.count(), 0)

    def test_plain_text_and_web_urls_are_rejected(self):
        text = QMimeData()
        text.setText("C:/path-is-not-a-file-drag")
        for mime in (text, self.mime_for("https://example.org/file.txt")):
            with self.subTest(formats=mime.formats()):
                self.assertFalse(self.enter(mime).isAccepted())
                self.assertFalse(self.button._file_drag)
        self.assertEqual(self.files.count(), 0)
        self.assertGreaterEqual(self.tooltip.call_count, 2)

    def test_drag_leave_clears_highlight_without_selecting(self):
        self.enter(self.mime_for("file:///C:/one.txt"))
        self.assertTrue(self.button._file_drag)
        leave = QDragLeaveEvent()
        self.application.sendEvent(self.button, leave)
        self.assertFalse(self.button._file_drag)
        self.assertEqual(self.button.get_visual_scale(), 1.0)
        self.assertEqual(self.files.count(), 0)

    def test_busy_rejects_entry_and_becoming_busy_clears_highlight(self):
        mime = self.mime_for("file:///C:/one.txt")
        self.button.set_busy(True)
        self.assertFalse(self.enter(mime).isAccepted())
        self.assertIn("稍后", self.button.toolTip())
        self.button.set_busy(False)
        self.assertTrue(self.enter(mime).isAccepted())
        self.button.set_busy(True)
        self.assertFalse(self.button._file_drag)
        self.assertFalse(self.drop(mime).isAccepted())
        self.assertEqual(self.files.count(), 0)

    def test_drag_move_revalidates_payload_and_keeps_copy_semantics(self):
        mime = self.mime_for("file:///C:/one.txt")
        self.enter(mime)
        event = QDragMoveEvent(QPoint(37, 36), Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
                               mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.application.sendEvent(self.button, event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(event.dropAction(), Qt.DropAction.CopyAction)
        self.assertTrue(self.button._file_drag)


if __name__ == "__main__":
    unittest.main()
