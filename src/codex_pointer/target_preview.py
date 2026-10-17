"""Non-interactive target feedback. This module never captures screen pixels.

Windows metadata uses physical pixels; Qt positions use per-monitor logical
coordinates. An outline is split at monitor boundaries so mixed DPI desktops
do not stretch or displace it onto the wrong monitor.
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import ntpath
import os

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from .ui import Theme, icon


@dataclass(frozen=True)
class ScreenMapping:
    name: str
    native: QRect
    logical: QRect
    density: float


def physical_rect_segments(rect: tuple[int, int, int, int], mappings: list[ScreenMapping]):
    """Yield visible Qt rectangles and their real target edges, with no I/O."""
    left, top, right, bottom = rect
    if right <= left or bottom <= top:
        return []
    target = QRect(left, top, right - left, bottom - top)
    result = []
    for mapping in mappings:
        visible = target.intersected(mapping.native)
        if visible.isEmpty():
            continue
        density = max(0.1, mapping.density)
        x = mapping.logical.x() + round((visible.x() - mapping.native.x()) / density)
        y = mapping.logical.y() + round((visible.y() - mapping.native.y()) / density)
        x2 = mapping.logical.x() + round((visible.x() + visible.width() - mapping.native.x()) / density)
        y2 = mapping.logical.y() + round((visible.y() + visible.height() - mapping.native.y()) / density)
        logical = QRect(x, y, max(1, x2 - x), max(1, y2 - y))
        edges = (visible.left() == target.left(), visible.top() == target.top(),
                 visible.right() == target.right(), visible.bottom() == target.bottom())
        result.append((logical, edges))
    return result


def _native_monitors() -> dict[str, QRect]:
    if os.name != "nt":
        return {}

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                    ("work", wintypes.RECT), ("flags", wintypes.DWORD),
                    ("device", wintypes.WCHAR * 32)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MonitorInfo)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p, callback_type, wintypes.LPARAM]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    result = {}

    @callback_type
    def collect(handle, dc, bounds, data):
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            box = info.monitor
            result[info.device.casefold()] = QRect(box.left, box.top,
                                                   box.right - box.left, box.bottom - box.top)
        return True

    if not user32.EnumDisplayMonitors(None, None, collect, 0):
        return {}
    return result


def screen_mappings() -> list[ScreenMapping]:
    try:
        native = _native_monitors()
    except (OSError, AttributeError):
        native = {}
    result = []
    for screen in QApplication.screens():
        logical = screen.geometry()
        density = screen.devicePixelRatio()
        # Qt on Windows preserves physical monitor origins while scaling each
        # monitor's dimensions. Matching by device name also covers negative X/Y.
        bounds = native.get(screen.name().casefold())
        if bounds is None:
            bounds = QRect(logical.x(), logical.y(), round(logical.width() * density),
                           round(logical.height() * density))
        result.append(ScreenMapping(screen.name(), bounds, logical, density))
    return result


_OVERLAY_FLAGS = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                  Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus |
                  Qt.WindowType.WindowTransparentForInput)


def _configure_overlay(widget: QWidget) -> None:
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class _TargetOutline(QWidget):
    def __init__(self, theme: Theme, owner: QWidget):
        super().__init__(owner, _OVERLAY_FLAGS)
        _configure_overlay(self)
        self.theme = theme
        self.edges = (True, True, True, True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        # A quiet light/dark double stroke stays readable against any target.
        for color, width in ((QColor(0, 0, 0, 82), 3.5), (QColor(255, 255, 255, 215), 1.4)):
            painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if all(self.edges):
                painter.drawRoundedRect(bounds, 7, 7)
            else:
                left, top, right, bottom = self.edges
                if left:
                    painter.drawLine(bounds.topLeft(), bounds.bottomLeft())
                if top:
                    painter.drawLine(bounds.topLeft(), bounds.topRight())
                if right:
                    painter.drawLine(bounds.topRight(), bounds.bottomRight())
                if bottom:
                    painter.drawLine(bounds.bottomLeft(), bounds.bottomRight())


class TargetPreview(QWidget):
    """Pointer-following target name plus non-activating window outlines.

    ``show_context`` takes native ``TargetContext.rect`` plus an optional Qt
    global cursor point. Folder labels require a resolved path; window metadata
    alone is never promoted to an Explorer folder selection.
    """

    def __init__(self, theme: Theme, reduced_motion: bool = False):
        super().__init__(None, _OVERLAY_FLAGS)
        _configure_overlay(self)
        self.setAccessibleName("Codex Pointer 目标预览")
        self.setFixedSize(316, 88)
        self._theme = theme
        self.reduced_motion = reduced_motion
        self._mappings: list[ScreenMapping] | None = None
        self._outlines: list[_TargetOutline] = []
        self._title = "正在识别目标…"
        self._tag = "选择对象"
        self._glyph = "target"
        self._detail = "松开选择 · Esc 取消"
        application = QApplication.instance()
        if application is not None:
            application.screenAdded.connect(self._invalidate_screens)
            application.screenRemoved.connect(self._invalidate_screens)
            for screen in application.screens():
                self._watch_screen(screen)

    def _watch_screen(self, screen):
        screen.geometryChanged.connect(self._invalidate_screens)
        screen.physicalDotsPerInchChanged.connect(self._invalidate_screens)

    def _invalidate_screens(self, *args):
        self._mappings = None
        if args and hasattr(args[0], "geometryChanged"):
            self._watch_screen(args[0])

    def set_theme(self, theme: Theme):
        self._theme = theme
        self.update()
        for outline in self._outlines:
            outline.theme = theme
            outline.update()

    def show_context(self, context, cursor: QPoint | None = None, resolving: bool = False,
                     fallback_text: str = "") -> None:
        cursor = cursor if cursor is not None else QCursor.pos()
        path = getattr(context, "path", None)
        kind = getattr(context, "kind", "window")
        verified_path = bool(path and kind in ("folder", "file"))
        if verified_path:
            self._glyph = kind
            self._tag = "当前文件夹" if getattr(context, "source", "") == "explorer-current-folder" else (
                "文件夹" if kind == "folder" else "文件")
            self._title = ntpath.basename(str(path).rstrip("/\\")) or str(path)
        else:
            self._glyph = "window" if context is not None else "scan"
            self._tag = "窗口" if context is not None else "选择对象"
            self._title = (getattr(context, "title", "") or getattr(context, "process_name", "") or
                           ("正在识别目标…" if resolving else "移到窗口或文件夹上"))
        if fallback_text:
            self._detail = fallback_text
        elif resolving:
            self._detail = "正在确认对象 · Esc 取消"
        elif verified_path:
            self._detail = "所在窗口已高亮 · 松开选择 · Esc 取消"
        else:
            self._detail = "松开选择 · Esc 取消"
        self.setToolTip(self._title)
        self._show_outline(getattr(context, "rect", (0, 0, 0, 0)))
        self.move_near(cursor)
        self.show()
        self.update()

    show_target = show_context

    def move_near(self, cursor: QPoint) -> None:
        """Move cheaply while a metadata request is in flight."""
        screen = QApplication.screenAt(cursor) or self.screen()
        area = screen.availableGeometry().adjusted(8, 8, -8, -8)
        x, y = cursor.x() + 26, cursor.y() + 24
        if x + self.width() > area.right() + 1:
            x = cursor.x() - self.width() - 26
        if y + self.height() > area.bottom() + 1:
            y = cursor.y() - self.height() - 24
        x = max(area.left(), min(x, area.right() - self.width() + 1))
        y = max(area.top(), min(y, area.bottom() - self.height() + 1))
        destination = QPoint(x, y)
        if destination != self.pos():
            self.move(destination)

    def _show_outline(self, rect):
        if self._mappings is None:
            self._mappings = screen_mappings()
        segments = physical_rect_segments(rect, self._mappings)
        for index, (bounds, edges) in enumerate(segments):
            if index == len(self._outlines):
                self._outlines.append(_TargetOutline(self._theme, self))
            outline = self._outlines[index]
            if outline.geometry() != bounds:
                outline.setGeometry(bounds)
            if outline.edges != edges:
                outline.edges = edges
                outline.update()
            if not outline.isVisible():
                outline.show()
        for outline in self._outlines[len(segments):]:
            outline.hide()

    def hide_preview(self) -> None:
        self.hide()
        for outline in self._outlines:
            outline.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        painter.setPen(QPen(QColor(self._theme.border), 1))
        painter.setBrush(QColor(self._theme.bg))
        painter.drawRoundedRect(bounds, 13, 13)
        icon(self._glyph, self._theme.text, 21).paint(painter, QRect(16, 19, 21, 21))
        font = QFont(self.font())
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor(self._theme.muted))
        painter.drawText(QRect(47, 13, self.width() - 65, 16), Qt.AlignmentFlag.AlignVCenter,
                         self._tag)
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(self._theme.text))
        title = painter.fontMetrics().elidedText(self._title, Qt.TextElideMode.ElideMiddle, self.width() - 66)
        painter.drawText(QRect(47, 31, self.width() - 65, 21), Qt.AlignmentFlag.AlignVCenter, title)
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(self._theme.muted))
        detail = painter.fontMetrics().elidedText(self._detail, Qt.TextElideMode.ElideRight, self.width() - 34)
        painter.drawText(QRect(17, 60, self.width() - 34, 16), Qt.AlignmentFlag.AlignVCenter, detail)
