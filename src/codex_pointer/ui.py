"""Small, native Qt building blocks for the Pointer desktop interface.

All artwork is painted locally.  These widgets deliberately contain no context
capture or Codex transport logic, so the same surface can be previewed offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Property,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QMouseEvent,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QProxyStyle,
    QStyle,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    surface: str
    hover: str
    text: str
    muted: str
    subtle: str
    border: str
    primary: str
    primary_text: str


def theme_for(name: str) -> Theme:
    """Return one of the two intentionally restrained desktop palettes."""
    if name == "dark":
        return Theme(
            "dark", "#181818", "#212121", "#303030", "#ededed",
            "#afafaf", "#8f8f8f", "#303030", "#ededed", "#181818",
        )
    return Theme(
        "light", "#ffffff", "#f9f9f9", "#ededed", "#181818",
        "#5d5d5d", "#8f8f8f", "#ededed", "#181818", "#ffffff",
    )


class _PointerStyle(QProxyStyle):
    """Give checkboxes a real vector check, including on high DPI displays."""

    def __init__(self, theme: Theme) -> None:
        super().__init__("Fusion")
        self.theme = theme

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (QStyle.PixelMetric.PM_IndicatorWidth, QStyle.PixelMetric.PM_IndicatorHeight):
            return 18
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        if element != QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            return super().drawPrimitive(element, option, painter, widget)
        theme = self.theme
        checked = bool(option.state & QStyle.StateFlag.State_On)
        partial = bool(option.state & QStyle.StateFlag.State_NoChange)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not enabled:
            painter.setOpacity(0.45)
        bounds = QRectF(option.rect).adjusted(0.7, 0.7, -0.7, -0.7)
        painter.setPen(QPen(QColor(theme.primary if checked or partial else
                                   theme.text if hovered else theme.subtle), 1.15))
        painter.setBrush(QColor(theme.primary if checked or partial else theme.bg))
        painter.drawRoundedRect(bounds, 4, 4)
        if checked or partial:
            painter.setPen(QPen(QColor(theme.primary_text), 1.65,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            if partial:
                painter.drawLine(bounds.center() + QPointF(-3.5, 0),
                                 bounds.center() + QPointF(3.5, 0))
            else:
                from .iconography import paint_icon
                painter.translate(bounds.left(), bounds.top())
                painter.scale(bounds.width() / 24, bounds.height() / 24)
                paint_icon(painter, "check", theme.primary_text)
        painter.restore()


def apply_theme(app: QApplication, theme: Theme) -> None:
    """Style ordinary Qt controls as a quiet, consistent native companion."""
    font = QFont()
    font.setFamilies(["Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei"])
    font.setPixelSize(14)
    app.setFont(font)
    pointer_style = getattr(app, "_pointer_style", None)
    if pointer_style is None:
        pointer_style = _PointerStyle(theme)
        app._pointer_style = pointer_style
        app.setStyle(pointer_style)
    else:
        pointer_style.theme = theme
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, theme.bg),
        (QPalette.ColorRole.WindowText, theme.text),
        (QPalette.ColorRole.Base, theme.bg),
        (QPalette.ColorRole.AlternateBase, theme.surface),
        (QPalette.ColorRole.Text, theme.text),
        (QPalette.ColorRole.Button, theme.surface),
        (QPalette.ColorRole.ButtonText, theme.text),
        (QPalette.ColorRole.PlaceholderText, theme.subtle),
        (QPalette.ColorRole.Highlight, theme.hover),
        (QPalette.ColorRole.HighlightedText, theme.text),
    ):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(f"""
        QWidget {{ color: {theme.text}; font-size: 14px; }}
        QWidget#panel {{ background: {theme.bg}; border: 1px solid {theme.border};
                         border-radius: 20px; }}
        QLabel {{ background: transparent; border: none; }}
        QLabel#muted {{ color: {theme.muted}; font-size: 12px; }}
        QLabel#caption {{ color: {theme.subtle}; font-size: 12px; }}
        QWidget#targetCard {{ background: {theme.surface};
            border: 1px solid {theme.border}; border-radius: 13px; }}
        QWidget#targetCard QLabel {{ background: transparent; border: none; }}
        QWidget#segmented {{ background: {theme.surface};
            border: 1px solid {theme.border}; border-radius: 12px; }}
        QPushButton, QToolButton {{ background: transparent; border: none;
            border-radius: 9px; padding: 8px 12px; font-size: 14px; }}
        QPushButton:hover, QToolButton:hover {{ background: {theme.hover}; }}
        QPushButton:pressed, QToolButton:pressed {{ background: {theme.border}; }}
        QPushButton:disabled, QToolButton:disabled {{ color: {theme.subtle}; }}
        QPushButton#segment {{ color: {theme.muted}; padding: 9px 12px;
            border: 1px solid transparent; border-radius: 9px; }}
        QPushButton#segment:checked {{ background: {theme.hover if theme.name == 'dark' else theme.bg};
            color: {theme.text}; border-color: {theme.border}; font-weight: 600; }}
        QPushButton#primary {{ background: {theme.primary}; color: {theme.primary_text};
            border-radius: 20px; padding: 10px 18px; min-height: 20px; font-weight: 600; }}
        QPushButton#primary:hover {{ background: {'#ffffff' if theme.name == 'dark' else '#353535'}; }}
        QPushButton#primary:pressed {{ background: {'#d5d5d5' if theme.name == 'dark' else '#090909'}; }}
        QPushButton#primary:disabled {{ background: {theme.hover}; color: {theme.subtle}; }}
        QPushButton#ghost, QToolButton#ghost {{ background: transparent;
            border-radius: 8px; padding: 6px; color: {theme.muted}; }}
        QPushButton#ghost:hover, QToolButton#ghost:hover {{ background: {theme.hover}; }}
        QPlainTextEdit#taskEditor, QTextEdit#taskEditor {{ background: {theme.bg};
            color: {theme.text}; border: 1px solid {theme.border}; border-radius: 13px;
            padding: 13px; selection-background-color: {theme.hover}; }}
        QPlainTextEdit#taskEditor:focus, QTextEdit#taskEditor:focus {{
            border-color: {theme.subtle}; }}
        QLineEdit, QComboBox {{ background: {theme.surface}; color: {theme.text};
            border: 1px solid {theme.border}; border-radius: 8px; padding: 8px 10px;
            selection-background-color: {theme.hover}; }}
        QLineEdit:focus, QComboBox:focus {{ border-color: {theme.subtle}; }}
        QComboBox::drop-down {{ border: none; width: 24px; }}
        QComboBox QAbstractItemView {{ background: {theme.bg}; color: {theme.text};
            border: 1px solid {theme.border}; selection-background-color: {theme.hover};
            outline: none; padding: 4px; }}
        QCheckBox {{ background: transparent; spacing: 8px; color: {theme.muted}; }}
        QWidget#notice {{ background: {theme.surface}; border: 1px solid {theme.border};
            border-radius: 10px; padding: 8px; color: {theme.muted}; font-size: 12px; }}
        QWidget#boundRow {{ background: {theme.surface}; border: 1px solid {theme.border};
            border-radius: 10px; }}
        QWidget#boundRow QLabel {{ background: transparent; border: none; }}
        QMenu {{ background: {theme.bg}; color: {theme.text};
            border: 1px solid {theme.border}; border-radius: 10px; padding: 5px; }}
        QMenu::item {{ padding: 8px 24px 8px 12px; border-radius: 6px; }}
        QMenu::item:selected {{ background: {theme.hover}; }}
        QMenu::item:disabled {{ color: {theme.subtle}; }}
        QMenu::separator {{ height: 1px; background: {theme.border}; margin: 5px 6px; }}
        QToolTip {{ background: {theme.text}; color: {theme.bg}; border: none;
            border-radius: 6px; padding: 6px 9px; font-size: 12px; }}
        QScrollBar:vertical {{ background: transparent; width: 7px; margin: 3px 1px; }}
        QScrollBar::handle:vertical {{ background: {theme.border}; border-radius: 3px;
            min-height: 24px; }}
        QScrollBar::handle:vertical:hover {{ background: {theme.subtle}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    """)


@lru_cache(maxsize=192)
def icon(name: str, color: str, size: int = 18) -> QIcon:
    """Render the shared vector family at native and high-DPI resolutions."""
    from .iconography import paint_icon

    result = QIcon()
    for density in (1, 2, 3):
        pixmap = QPixmap(size * density, size * density)
        pixmap.setDevicePixelRatio(density)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 24.0, size / 24.0)
        paint_icon(painter, name, color)
        painter.end()
        result.addPixmap(pixmap)
    return result


class FloatingButton(QWidget):
    """A draggable context handle with motion only in response to activity."""

    clicked = Signal()
    file_dropped = Signal(str)
    dropped = Signal(int, int)
    moved = Signal(int, int)
    drag_started = Signal()
    drag_moved = Signal(int, int)
    drag_cancelled = Signal()
    menu_requested = Signal(QPoint)

    def __init__(self, theme: Theme, reduced_motion: bool = False) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(72, 72)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Codex Pointer")
        self._default_tooltip_key = "单击打开或收起；拖动选择窗口，或把文件拖到圆圈上"
        self._default_tooltip = tr(self._default_tooltip_key)
        self._drop_note_key = None
        self._drop_note_point = None
        self.setToolTip(self._default_tooltip)
        self._theme = theme
        self._reduced_motion = reduced_motion
        self._scale = 1.0
        self._hovered = False
        self._pressed = False
        self._dragging = False
        self._press_global = QPoint()
        self._press_offset = QPoint()
        self._press_position = QPoint()
        self._busy = False
        self._file_drag = False
        self._angle = 0
        self._success = False
        self._scale_animation = QPropertyAnimation(self, b"visualScale", self)
        self._scale_animation.setDuration(140)
        self._scale_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(24)
        self._busy_timer.timeout.connect(self._advance_busy)
        self._success_timer = QTimer(self)
        self._success_timer.setSingleShot(True)
        self._success_timer.timeout.connect(self._clear_success)
        self._drop_note_timer = QTimer(self)
        self._drop_note_timer.setSingleShot(True)
        self._drop_note_timer.timeout.connect(self._restore_drop_tooltip)

    def retranslate_ui(self) -> None:
        """Refresh chrome without changing drag, busy or target state."""
        self.setAccessibleName("Codex Pointer")
        self.setWindowTitle("Codex Pointer")
        self._default_tooltip = tr(self._default_tooltip_key)
        note = tr(self._drop_note_key) if self._drop_note_key else self._default_tooltip
        self.setToolTip(note)
        if self._drop_note_key and QToolTip.isVisible() and self._drop_note_point is not None:
            QToolTip.showText(self._drop_note_point, note, self, self.rect(),
                              max(100, self._drop_note_timer.remainingTime()))
        self.update()

    def get_visual_scale(self) -> float:
        return self._scale

    def set_visual_scale(self, value: float) -> None:
        self._scale = value
        self.update()

    visualScale = Property(float, get_visual_scale, set_visual_scale)

    @property
    def reduced_motion(self) -> bool:
        return self._reduced_motion

    @reduced_motion.setter
    def reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = bool(enabled)
        if self._reduced_motion:
            self._scale_animation.stop()
            self._busy_timer.stop()
            scale = (1.06 if self._file_drag else 1.04 if self._dragging else 0.94 if self._pressed else
                     1.06 if self._hovered else 1.0)
            self.set_visual_scale(scale)
        elif self._busy:
            self._busy_timer.start()
        self.update()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy and self._file_drag:
            self._set_file_drag(False)
            self._drop_note("正在处理任务，请稍后再拖入。")
        if busy and not self._reduced_motion:
            self._busy_timer.start()
        else:
            self._busy_timer.stop()
        self.update()

    def set_success(self) -> None:
        self.set_busy(False)
        self._success = True
        self._success_timer.start(1200)
        self.update()

    def _clear_success(self) -> None:
        self._success = False
        self.update()

    def _advance_busy(self) -> None:
        self._angle = (self._angle + 7) % 360
        self.update()

    def _animate_scale(self, value: float) -> None:
        # Mouse moves can arrive far more often than animation frames. Keeping
        # the same destination lets the running animation actually finish.
        if self._scale_animation.endValue() == value:
            if self._scale_animation.state() == QPropertyAnimation.State.Running:
                return
            if abs(self._scale - value) < 0.001:
                return
        self._scale_animation.stop()
        if self._reduced_motion:
            self.set_visual_scale(value)
            return
        self._scale_animation.setStartValue(self._scale)
        self._scale_animation.setEndValue(value)
        self._scale_animation.start()

    def enterEvent(self, event: QEvent) -> None:
        self._hovered = True
        if not self._pressed:
            self._animate_scale(1.06)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hovered = False
        if not self._pressed:
            self._animate_scale(1.0)
        super().leaveEvent(event)

    def _restore_drop_tooltip(self) -> None:
        self._drop_note_key = None
        self.setToolTip(self._default_tooltip)

    def _drop_note(self, text: str, event=None) -> None:
        self._drop_note_key = text
        translated = tr(text)
        self.setToolTip(translated)
        point = (self.mapToGlobal(event.position().toPoint()) if event is not None
                 else self.mapToGlobal(self.rect().center()))
        self._drop_note_point = point
        QToolTip.showText(point, translated, self, self.rect(), 1800)
        self._drop_note_timer.start(1800)

    def _set_file_drag(self, active: bool) -> None:
        if self._file_drag == active:
            return
        self._file_drag = active
        self._animate_scale(1.06 if active or self._hovered else 1.0)
        self.update()

    def _file_drop_path(self, event) -> str:
        from .drop_targets import DropTargetError, parse_local_file_urls

        if self._busy:
            raise DropTargetError("正在处理任务，请稍后再拖入。")
        if self._pressed:
            raise DropTargetError("请先松开圆圈，再拖入文件。")
        mime = event.mimeData()
        if not mime.hasUrls():
            raise DropTargetError("请拖入文件或文件夹，不支持纯文本。")
        return parse_local_file_urls([url.toString(url.ComponentFormattingOption.FullyEncoded)
                                      for url in mime.urls()])

    def dragEnterEvent(self, event) -> None:
        from .drop_targets import DropTargetError

        try:
            self._file_drop_path(event)
        except DropTargetError as error:
            self._set_file_drag(False)
            self._drop_note(str(error), event)
            event.ignore()
            return
        self._set_file_drag(True)
        self._drop_note("松开选择这个文件或文件夹。", event)
        # Selecting an object never means moving the source file. Explicit copy
        # feedback is also safe when Explorer's proposed action is MoveAction.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dragMoveEvent(self, event) -> None:
        from .drop_targets import DropTargetError

        try:
            self._file_drop_path(event)
        except DropTargetError as error:
            self._set_file_drag(False)
            self._drop_note(str(error), event)
            event.ignore()
            return
        self._set_file_drag(True)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dragLeaveEvent(self, event) -> None:
        self._set_file_drag(False)
        self._drop_note_timer.stop()
        self._restore_drop_tooltip()
        QToolTip.hideText()
        event.accept()

    def dropEvent(self, event) -> None:
        from .drop_targets import DropTargetError

        self._set_file_drag(False)
        self._drop_note_timer.stop()
        QToolTip.hideText()
        try:
            path = self._file_drop_path(event)
        except DropTargetError as error:
            self._drop_note(str(error), event)
            event.ignore()
            return
        self._restore_drop_tooltip()
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.file_dropped.emit(path)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(event.globalPosition().toPoint())
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._dragging = False
            self._press_global = event.globalPosition().toPoint()
            self._press_offset = self._press_global - self.pos()
            self._press_position = self.pos()
            self._animate_scale(0.94)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._pressed:
            return super().mouseMoveEvent(event)
        cursor = event.globalPosition().toPoint()
        if (not self._dragging and
                (cursor - self._press_global).manhattanLength() >= QApplication.startDragDistance()):
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._animate_scale(1.04)
            self.drag_started.emit()
        if self._dragging:
            position = cursor - self._press_offset
            self.move(position)
            self.moved.emit(position.x(), position.y())
            # Like dropped, these are Qt global logical coordinates. Native
            # screen pixel capture must convert them at the controller boundary.
            self.drag_moved.emit(cursor.x(), cursor.y())
            self.update()
        event.accept()

    @property
    def is_dragging(self) -> bool:
        return self._dragging

    def cancel_drag(self) -> None:
        """Restore the handle without dispatching a click or a target drop."""
        if not self._pressed:
            return
        was_dragging = self._dragging
        self._pressed = False
        self._dragging = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if was_dragging:
            self.move(self._press_position)
            self.moved.emit(self.x(), self.y())
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self._animate_scale(1.06 if self._hovered else 1.0)
        self.update()
        if was_dragging:
            self.drag_cancelled.emit()

    def keyPressEvent(self, event: QEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self._pressed:
            self.cancel_drag()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._pressed:
            return super().mouseReleaseEvent(event)
        was_dragging = self._dragging
        self._pressed = False
        self._dragging = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._animate_scale(1.06 if self._hovered else 1.0)
        self.update()
        if was_dragging:
            cursor = event.globalPosition().toPoint()
            self.dropped.emit(cursor.x(), cursor.y())
        else:
            self.clicked.emit()
        event.accept()

    def paintEvent(self, event: QEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(36, 36)
        radius = 24 * self._scale
        dark = self._theme.name == "dark"
        painter.setPen(Qt.PenStyle.NoPen)
        for spread in range(8, 0, -1):
            shadow = QColor(0, 0, 0, (3 if dark else 2) + (8 - spread))
            painter.setBrush(shadow)
            painter.drawEllipse(center + QPointF(0, 2), radius + spread, radius + spread)
        fill = QColor(self._theme.primary if self._file_drag else self._theme.bg)
        if not self._file_drag and self._hovered and not self._pressed:
            fill = QColor(self._theme.surface)
        painter.setBrush(fill)
        painter.setPen(QPen(QColor(self._theme.border), 1.0))
        painter.drawEllipse(center, radius, radius)
        if self._dragging or self._file_drag:
            ring = QColor(self._theme.text)
            ring.setAlpha(105)
            painter.setPen(QPen(ring, 1.25))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius + 3.5, radius + 3.5)
        if self._busy:
            painter.setPen(QPen(QColor(self._theme.text), 1.6,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            arc = QRectF(36 - radius - 2.5, 36 - radius - 2.5,
                         (radius + 2.5) * 2, (radius + 2.5) * 2)
            painter.drawArc(arc, -self._angle * 16, 92 * 16)
        extent = round(27 * self._scale)
        glyph = icon("check" if self._success else "target",
                     self._theme.primary_text if self._file_drag else self._theme.text, extent)
        glyph.paint(painter, QRect(round(36 - extent / 2), round(36 - extent / 2), extent, extent))


class Popover(QWidget):
    """A compact, shadowed task surface anchored to the floating handle."""

    def __init__(self, theme: Theme, reduced_motion: bool = False) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(488)
        self.setWindowTitle("Codex Pointer")
        self._theme = theme
        self._reduced_motion = reduced_motion
        self._reveal_destination: QPoint | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(0)
        self.panel = QFrame(self)
        self.panel.setObjectName("panel")
        self.panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        outer.addWidget(self.panel)
        self.body = QVBoxLayout(self.panel)
        self.body.setContentsMargins(22, 20, 22, 20)
        self.body.setSpacing(14)
        self._shadow = QGraphicsDropShadowEffect(self.panel)
        self._shadow.setBlurRadius(25)
        self._shadow.setOffset(0, 5)
        self.panel.setGraphicsEffect(self._shadow)
        self._animation = QParallelAnimationGroup(self)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self._animation)
        self._slide = QPropertyAnimation(self, b"pos", self._animation)
        for animation in (self._fade, self._slide):
            animation.setDuration(160)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._animation.addAnimation(animation)
        self.set_theme(theme)

    def retranslate_ui(self) -> None:
        self.setWindowTitle("Codex Pointer")

    @property
    def reduced_motion(self) -> bool:
        return self._reduced_motion

    @reduced_motion.setter
    def reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = bool(enabled)
        if self._reduced_motion:
            self._animation.stop()
            if self._reveal_destination is not None:
                self.move(self._reveal_destination)
            self.setWindowOpacity(1.0)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._shadow.setColor(QColor(0, 0, 0, 95 if theme.name == "dark" else 38))
        self.panel.update()

    def reveal(self, anchor: QRect) -> None:
        """Show above the handle where possible, within the current display."""
        self._animation.stop()
        self.adjustSize()
        screen = QApplication.screenAt(anchor.center()) or self.screen()
        available = screen.availableGeometry().adjusted(8, 8, -8, -8)
        x = anchor.center().x() - self.width() // 2
        y = anchor.top() - self.height() - 2
        if y < available.top():
            y = anchor.bottom() + 2
        x = max(available.left(), min(x, available.right() - self.width() + 1))
        y = max(available.top(), min(y, available.bottom() - self.height() + 1))
        destination = QPoint(x, y)
        self._reveal_destination = destination
        if self._reduced_motion or self.isVisible():
            self.setWindowOpacity(1)
            self.move(destination)
            self.show()
        else:
            self.move(destination + QPoint(0, 6))
            self.setWindowOpacity(0)
            self.show()
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._slide.setStartValue(destination + QPoint(0, 6))
            self._slide.setEndValue(destination)
            self._animation.start()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event: QEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QEvent) -> None:
        self._animation.stop()
        self.setWindowOpacity(1.0)
        super().closeEvent(event)
