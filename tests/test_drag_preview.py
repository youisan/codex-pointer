"""Drag lifecycle and target feedback verified without reading the desktop."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from codex_pointer.target_preview import ScreenMapping, TargetPreview, physical_rect_segments
from codex_pointer.ui import FloatingButton, theme_for
from codex_pointer.windows import TargetContext


class DragPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.button = FloatingButton(theme_for("light"), reduced_motion=True)
        self.button.move(100, 100)
        self.button.show()
        self.application.processEvents()
        self.starts = QSignalSpy(self.button.drag_started)
        self.moves = QSignalSpy(self.button.drag_moved)
        self.cancels = QSignalSpy(self.button.drag_cancelled)
        self.drops = QSignalSpy(self.button.dropped)
        self.clicks = QSignalSpy(self.button.clicked)
        self.preview = TargetPreview(theme_for("light"), reduced_motion=True)

    def tearDown(self):
        self.button.close()
        self.preview.hide_preview()
        self.preview.close()
        self.button.deleteLater()
        self.preview.deleteLater()
        self.application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.application.processEvents()

    def move_drag(self, point):
        event = QMouseEvent(QEvent.Type.MouseMove,
                            QPointF(self.button.mapFromGlobal(point)), QPointF(point),
                            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
        self.application.sendEvent(self.button, event)

    def test_drag_emits_start_once_and_reports_logical_cursor_each_move(self):
        origin = self.button.pos()
        QTest.mousePress(self.button, Qt.MouseButton.LeftButton, pos=QPoint(36, 36))
        self.move_drag(origin + QPoint(70, 70))
        self.move_drag(origin + QPoint(80, 80))
        self.move_drag(origin + QPoint(90, 90))
        self.assertEqual(self.starts.count(), 1)
        self.assertEqual(self.moves.count(), 3)
        self.assertEqual(self.moves.at(2), [origin.x() + 90, origin.y() + 90])
        self.assertTrue(self.button.is_dragging)
        QTest.mouseRelease(self.button, Qt.MouseButton.LeftButton, pos=QPoint(36, 36))
        self.assertEqual(self.drops.count(), 1)
        self.assertEqual(self.clicks.count(), 0)
        self.assertFalse(self.button.is_dragging)

    def test_escape_restores_position_and_release_does_not_drop_or_click(self):
        origin = self.button.pos()
        QTest.mousePress(self.button, Qt.MouseButton.LeftButton, pos=QPoint(36, 36))
        self.move_drag(origin + QPoint(95, 95))
        self.assertNotEqual(self.button.pos(), origin)
        QTest.keyClick(self.button, Qt.Key.Key_Escape)
        QTest.mouseRelease(self.button, Qt.MouseButton.LeftButton, pos=QPoint(36, 36))
        self.assertEqual(self.button.pos(), origin)
        self.assertEqual(self.cancels.count(), 1)
        self.assertEqual(self.drops.count(), 0)
        self.assertEqual(self.clicks.count(), 0)
        self.assertFalse(self.button.is_dragging)

    def test_programmatic_cancel_is_idempotent(self):
        QTest.mousePress(self.button, Qt.MouseButton.LeftButton, pos=QPoint(36, 36))
        self.move_drag(self.button.pos() + QPoint(90, 90))
        self.button.cancel_drag()
        self.button.cancel_drag()
        self.assertEqual(self.cancels.count(), 1)
        self.assertEqual(self.drops.count(), 0)

    def test_below_drag_threshold_remains_a_click(self):
        QTest.mousePress(self.button, Qt.MouseButton.LeftButton, pos=QPoint(36, 36))
        self.move_drag(self.button.pos() + QPoint(37, 37))
        QTest.mouseRelease(self.button, Qt.MouseButton.LeftButton, pos=QPoint(36, 36))
        self.assertEqual(self.starts.count(), 0)
        self.assertEqual(self.drops.count(), 0)
        self.assertEqual(self.clicks.count(), 1)

    def test_repeated_same_scale_does_not_restart_running_animation(self):
        self.button.reduced_motion = False
        self.button._animate_scale(1.04)
        with patch.object(self.button._scale_animation, "start") as start:
            self.button._animate_scale(1.04)
            self.button._animate_scale(1.04)
        start.assert_not_called()

    def test_preview_never_labels_an_unresolved_explorer_window_as_folder(self):
        target = TargetContext(title="Projects", process_name="explorer.exe", rect=(20, 20, 300, 220))
        self.preview.show_context(target, QPoint(400, 400), resolving=True)
        self.assertEqual(self.preview._tag, "窗口")
        self.assertEqual(self.preview._glyph, "window")
        self.assertIn("确认", self.preview._detail)
        self.assertFalse(self.preview.grab().isNull())

    def test_preview_names_verified_folder_and_explicit_current_folder_fallback(self):
        target = TargetContext(kind="folder", title="Explorer", path="D:\\Projects\\Demo",
                               source="explorer-current-folder", rect=(20, 20, 300, 220))
        self.preview.show_context(target, QPoint(400, 400))
        self.assertEqual(self.preview._tag, "当前文件夹")
        self.assertEqual(self.preview._title, "Demo")
        self.assertEqual(self.preview._glyph, "folder")

    def test_preview_is_click_through_does_not_accept_focus_and_hides_outlines(self):
        self.preview.show_context(TargetContext(title="Editor", rect=(20, 20, 300, 220)),
                                  QPoint(400, 400))
        self.assertTrue(self.preview.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        self.assertTrue(self.preview.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
        self.assertEqual(self.preview.focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertTrue(self.preview._outlines)
        self.preview.hide_preview()
        self.assertFalse(self.preview.isVisible())
        self.assertTrue(all(not outline.isVisible() for outline in self.preview._outlines))

    def test_preview_clamps_to_screen_edges(self):
        area = self.preview.screen().availableGeometry()
        self.preview.show_context(None, area.bottomRight(), resolving=True)
        self.assertTrue(area.contains(self.preview.geometry()))

    def test_mixed_dpi_native_rectangle_splits_without_a_false_monitor_seam(self):
        mappings = [
            ScreenMapping("left", QRect(-1920, 0, 1920, 1080), QRect(-1920, 0, 1920, 1080), 1),
            ScreenMapping("right", QRect(0, 0, 2560, 1440), QRect(0, 0, 1280, 720), 2),
        ]
        pieces = physical_rect_segments((-200, 200, 400, 800), mappings)
        self.assertEqual(pieces, [
            (QRect(-200, 200, 200, 600), (True, True, False, True)),
            (QRect(0, 100, 200, 300), (False, True, True, True)),
        ])

    def test_mixed_dpi_native_origin_is_not_scaled(self):
        mappings = [ScreenMapping("right", QRect(1920, -100, 3840, 2160),
                                  QRect(1920, -100, 1920, 1080), 2)]
        self.assertEqual(physical_rect_segments((2120, 100, 2520, 500), mappings)[0][0],
                         QRect(2020, 0, 200, 200))
        self.assertEqual(physical_rect_segments((0, 0, 0, 100), mappings), [])


if __name__ == "__main__":
    unittest.main()
