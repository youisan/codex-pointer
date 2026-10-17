"""The compact task surface shared by the light and dark desktop themes."""

from __future__ import annotations

from pathlib import PureWindowsPath

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .ui import Popover, Theme, icon
from .quick_tasks import insertion_for, tasks_for
from .i18n import tr


class _ElidingLabel(QLabel):
    """Keep untrusted window and conversation names to a single plain-text line."""

    def __init__(self, text: str = "", parent: QWidget | None = None,
                 mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight) -> None:
        super().__init__(parent)
        self._full_text = text
        self._elide_mode = mode
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._update_text()

    def _update_text(self) -> None:
        self.setText(self.fontMetrics().elidedText(
            self._full_text, self._elide_mode, max(0, self.contentsRect().width())))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_text()


class TaskPanel(Popover):
    """A task composer; its controller owns capture, state, and Codex transport."""

    def __init__(self, controller) -> None:
        self.controller = controller
        self._notice_key, self._notice_kwargs = "", {}
        super().__init__(controller.theme, controller.reduced_motion)
        self.setAccessibleName(tr("Codex Pointer 任务面板"))
        self.body.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(9)
        self.brand_icon = QLabel()
        self.brand_icon.setFixedSize(24, 24)
        header.addWidget(self.brand_icon)
        title = QLabel("Codex Pointer")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch()
        self.theme_button = self._icon_button("切换深浅色主题")
        self.theme_button.clicked.connect(controller.toggle_theme)
        header.addWidget(self.theme_button)
        self.close_button = self._icon_button("关闭")
        self.close_button.clicked.connect(self.close)
        header.addWidget(self.close_button)
        self.body.addLayout(header)

        self.target_card = QFrame()
        self.target_card.setObjectName("targetCard")
        self.target_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.target_card.setFixedHeight(62)
        target_layout = QHBoxLayout(self.target_card)
        target_layout.setContentsMargins(14, 9, 8, 9)
        target_layout.setSpacing(12)
        self.target_icon = QLabel()
        self.target_icon.setFixedSize(24, 24)
        target_layout.addWidget(self.target_icon)
        target_text = QVBoxLayout()
        target_text.setContentsMargins(0, 0, 0, 0)
        target_text.setSpacing(2)
        self.target_title = _ElidingLabel()
        self.target_title.setStyleSheet("font-weight: 600;")
        self.target_path = _ElidingLabel(mode=Qt.TextElideMode.ElideMiddle)
        self.target_path.setObjectName("muted")
        target_text.addWidget(self.target_title)
        target_text.addWidget(self.target_path)
        target_layout.addLayout(target_text, 1)
        self.change_target = self._icon_button("选择文件夹")
        self.change_target.clicked.connect(controller.choose_folder)
        target_layout.addWidget(self.change_target)
        self.body.addWidget(self.target_card)

        segmented = QFrame()
        segmented.setObjectName("segmented")
        segmented.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        segmented.setFixedHeight(44)
        modes = QHBoxLayout(segmented)
        modes.setContentsMargins(3, 3, 3, 3)
        modes.setSpacing(3)
        self.new_button = QPushButton("新对话")
        self.existing_button = QPushButton("继续对话")
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        for button in (self.new_button, self.existing_button):
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self._mode_group.addButton(button)
            modes.addWidget(button, 1)
        self.new_button.clicked.connect(lambda: controller.set_mode("new"))
        self.existing_button.clicked.connect(lambda: controller.set_mode("existing"))
        self.body.addWidget(segmented)

        self.bound_row = QFrame()
        self.bound_row.setObjectName("boundRow")
        self.bound_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.bound_row.setFixedHeight(42)
        bound_layout = QHBoxLayout(self.bound_row)
        bound_layout.setContentsMargins(12, 3, 5, 3)
        bound_layout.setSpacing(6)
        self.bound_title = _ElidingLabel()
        self.bound_title.setObjectName("muted")
        bound_layout.addWidget(self.bound_title, 1)
        self.bind_button = QPushButton("选择对话")
        self.bind_button.setObjectName("ghost")
        self.bind_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bind_button.clicked.connect(controller.pick_thread)
        bound_layout.addWidget(self.bind_button)
        self.body.addWidget(self.bound_row)

        self.quick_tasks_row = QWidget()
        quick_tasks_layout = QHBoxLayout(self.quick_tasks_row)
        quick_tasks_layout.setContentsMargins(0, 0, 0, 0)
        quick_tasks_layout.setSpacing(6)
        self.quick_task_buttons = []
        for index in range(3):
            button = QPushButton()
            button.setObjectName("quickTask")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(28)
            button.clicked.connect(lambda checked=False, index=index: self.insert_quick_task(index))
            self.quick_task_buttons.append(button)
            quick_tasks_layout.addWidget(button)
        quick_tasks_layout.addStretch()
        self.body.addWidget(self.quick_tasks_row)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("taskEditor")
        self.editor.setPlaceholderText("想让 Codex 做什么？")
        self.editor.setAccessibleName("任务内容")
        self.editor.setFixedHeight(118)
        self.editor.setTabChangesFocus(True)
        self.editor.setPlainText(controller.draft)
        self.editor.textChanged.connect(self._task_changed)
        self.body.addWidget(self.editor)

        attachments = QHBoxLayout()
        attachments.setSpacing(10)
        self.include_image = QCheckBox("附带截图")
        self.include_image.setToolTip("仅在勾选后截取目标窗口")
        self.include_image.setCursor(Qt.CursorShape.PointingHandCursor)
        self.include_image.toggled.connect(lambda _checked: controller.invalidate_image())
        attachments.addWidget(self.include_image)
        self.attachment_divider = QFrame()
        self.attachment_divider.setFrameShape(QFrame.Shape.VLine)
        self.attachment_divider.setFixedHeight(17)
        attachments.addWidget(self.attachment_divider)
        self.preview_button = QPushButton("预览")
        self.preview_button.setObjectName("ghost")
        self.preview_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_button.setToolTip("预览目标窗口截图")
        self.preview_button.clicked.connect(controller.preview_image)
        attachments.addWidget(self.preview_button)
        attachments.addStretch()
        self.more_button = self._icon_button("更多选项")
        self.more_button.clicked.connect(controller.show_details_menu)
        attachments.addWidget(self.more_button)
        self.body.addLayout(attachments)

        self.notice = QLabel()
        self.notice.setObjectName("notice")
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        self.notice.setWordWrap(True)
        self.notice.setAccessibleName("任务状态")
        self.notice.hide()
        self.body.addWidget(self.notice)

        footer = QHBoxLayout()
        footer.setSpacing(9)
        self.hint = QLabel()
        self.hint.setObjectName("caption")
        self.hint.setTextFormat(Qt.TextFormat.PlainText)
        self.hint.setWordWrap(True)
        footer.addWidget(self.hint, 1)
        self.primary = QPushButton()
        self.primary.setObjectName("primary")
        self.primary.setCursor(Qt.CursorShape.PointingHandCursor)
        self.primary.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.primary.setIconSize(QSize(18, 18))
        self.primary.setMinimumHeight(40)
        self.primary.clicked.connect(controller.primary_action)
        footer.addWidget(self.primary)
        self.body.addLayout(footer)

        self._submit_shortcuts = []
        for sequence in ("Ctrl+Return", "Ctrl+Enter"):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(self._trigger_primary)
            self._submit_shortcuts.append(shortcut)
        self._escape_shortcut = QShortcut(QKeySequence("Esc"), self)
        self._escape_shortcut.activated.connect(self.close)
        self.set_theme(controller.theme)
        self.refresh_target()
        self.set_mode(controller.mode)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """Translate chrome in place, leaving drafts, selection and state intact."""
        super().retranslate_ui()
        if not hasattr(self, "primary"):
            return
        self.setAccessibleName(tr("Codex Pointer 任务面板"))
        for button in (self.theme_button, self.close_button, self.change_target, self.more_button):
            text = tr(button.property("translation_key"))
            button.setAccessibleName(text)
            button.setToolTip(text)
        self.new_button.setText(tr("新对话"))
        self.existing_button.setText(tr("继续对话"))
        self.editor.setPlaceholderText(tr("想让 Codex 做什么？"))
        self.editor.setAccessibleName(tr("任务内容"))
        self.include_image.setText(tr("附带截图"))
        self.preview_button.setText(tr("预览"))
        self.preview_button.setToolTip(tr("预览目标窗口截图"))
        self.notice.setAccessibleName(tr("任务状态"))
        self.notice.setText(tr(self._notice_key, **self._notice_kwargs))
        self.refresh_target()
        self._fit_content()

    @staticmethod
    def _icon_button(description: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("ghost")
        button.setFixedSize(30, 30)
        button.setIconSize(QSize(18, 18))
        button.setProperty("translation_key", description)
        button.setAccessibleName(tr(description))
        button.setToolTip(tr(description))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def set_theme(self, theme: Theme) -> None:
        super().set_theme(theme)
        # Popover calls this hook before TaskPanel has created its children.
        if not hasattr(self, "theme_button"):
            return
        self.brand_icon.setPixmap(icon("target", theme.text, 23).pixmap(23, 23))
        self.theme_button.setIcon(icon("sun" if theme.name == "dark" else "moon", theme.muted))
        self.close_button.setIcon(icon("x", theme.muted))
        self.change_target.setIcon(icon("folder-open", theme.muted))
        self.more_button.setIcon(icon("more", theme.muted))
        self.preview_button.setIcon(icon("eye", theme.muted))
        self.include_image.setIcon(icon("camera", theme.muted, 16))
        self.bind_button.setIcon(icon("chevron-down", theme.muted, 16))
        self.attachment_divider.setStyleSheet(f"color: {theme.border};")
        self.quick_tasks_row.setStyleSheet(f"""
            QPushButton#quickTask {{ background: {theme.surface}; color: {theme.muted};
                border: 1px solid {theme.border}; border-radius: 14px;
                padding: 4px 10px; font-size: 12px; }}
            QPushButton#quickTask:hover {{ background: {theme.hover}; color: {theme.text}; }}
            QPushButton#quickTask:pressed {{ background: {theme.border}; }}
            QPushButton#quickTask:disabled {{ color: {theme.subtle}; }}
        """)
        self.refresh_target()
        self.refresh_primary()

    def insert_quick_task(self, index: int) -> None:
        """Append a task starter without replacing a draft or sending anything."""
        if self.controller.busy or self.controller.selecting:
            return
        tasks = tasks_for(self.controller.target)
        if not 0 <= index < len(tasks):
            return
        insertion = insertion_for(self.editor.toPlainText(), tasks[index])
        if insertion is not None:
            cursor = self.editor.textCursor()
            cursor.clearSelection()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.beginEditBlock()
            cursor.insertText(insertion)
            cursor.endEditBlock()
            self.editor.setTextCursor(cursor)
            self.editor.ensureCursorVisible()
        self.editor.setFocus()

    def _refresh_quick_tasks(self) -> None:
        tasks = tasks_for(self.controller.target)
        was_visible = not self.quick_tasks_row.isHidden()
        self.quick_tasks_row.setVisible(bool(tasks))
        for index, button in enumerate(self.quick_task_buttons):
            task = tasks[index] if index < len(tasks) else None
            button.setVisible(task is not None)
            button.setText(task.label if task else "")
            button.setAccessibleName(tr("快捷任务：{label}", label=task.label) if task else tr("快捷任务"))
            button.setToolTip(task.prompt + "\n" + tr("添加到任务末尾，不会自动发送") if task else "")
        if was_visible != bool(tasks):
            self._fit_content()

    def _task_changed(self) -> None:
        self.controller.draft = self.editor.toPlainText()
        self.refresh_primary()

    def set_mode(self, mode: str) -> None:
        self.controller.mode = "existing" if mode == "existing" else "new"
        self.new_button.setChecked(self.controller.mode == "new")
        self.existing_button.setChecked(self.controller.mode == "existing")
        self.bound_row.setVisible(self.controller.mode == "existing")
        self.refresh_primary()
        self._fit_content()

    def _fit_content(self) -> None:
        # Nested layouts otherwise retain the old height for one event-loop turn
        # when the bound conversation or status row is hidden.
        self.body.invalidate()
        self.body.activate()
        self.layout().invalidate()
        self.layout().activate()
        self.adjustSize()
        if self.isVisible():
            available = self.screen().availableGeometry().adjusted(8, 8, -8, -8)
            x = max(available.left(), min(self.x(), available.right() - self.width() + 1))
            y = max(available.top(), min(self.y(), available.bottom() - self.height() + 1))
            if QPoint(x, y) != self.pos():
                self._animation.stop()
                self.setWindowOpacity(1.0)
                self.move(x, y)

    def refresh_target(self) -> None:
        target = self.controller.target
        if target is None:
            name, detail = ((tr("正在识别目标…"), tr("可以继续输入任务，或选择其他对象")) if self.controller.selecting
                            else (tr("选择操作对象"), tr("拖动悬浮按钮，或选择文件夹")))
            glyph = "folder"
        else:
            path = str(target.path or "")
            name = str((PureWindowsPath(path).name if path and target.kind in ("folder", "file") else "")
                       or target.title or target.process_name or tr("目标窗口"))
            detail = path or str(target.process_path or target.process_name or tr("目标窗口"))
            glyph = "folder" if target.kind == "folder" else "file" if target.kind == "file" else "window"
        self.target_title.set_full_text(name)
        self.target_path.set_full_text(detail)
        self.target_card.setToolTip(f"{name}\n{detail}")
        self.target_icon.setPixmap(icon(glyph, self._theme.muted, 23).pixmap(23, 23))
        can_capture = bool(target and target.hwnd)
        if not can_capture and self.include_image.isChecked():
            self.include_image.setChecked(False)
        self.include_image.setEnabled(can_capture and not self.controller.busy)
        self.preview_button.setEnabled(can_capture and not self.controller.busy)
        self.include_image.setToolTip(tr("仅在勾选后截取目标窗口") if can_capture else tr("文件夹无需截图"))
        self._refresh_quick_tasks()
        self.refresh_primary()

    def refresh_primary(self) -> None:
        busy = self.controller.busy
        selecting = self.controller.selecting
        existing = self.controller.mode == "existing"
        thread_id = self.controller.settings.get("thread_id", "")
        missing_binding = existing and not thread_id
        title = self.controller.settings.get("thread_title") or thread_id or tr("尚未选择对话")
        self.bound_title.set_full_text(str(title))
        self.bind_button.setText(tr("更换") if thread_id else tr("选择对话"))
        if missing_binding:
            text = tr("选择对话")
            hint = tr("选择后将任务发送到该对话")
        elif existing:
            text = tr("发送到此对话")
            hint = tr("任务将排队发送到已绑定对话")
        else:
            text = tr("在 Codex 中继续")
            hint = tr("将在 Codex 中预填，确认后发送")
        ready = bool(self.controller.target and self.editor.toPlainText().strip())
        enabled = not busy and not selecting and (missing_binding or ready)
        self.primary.setText(tr("正在连接…") if busy else tr("正在识别…") if selecting else text)
        self.primary.setEnabled(enabled)
        self.primary.setIcon(icon("arrow-right", self._theme.primary_text if enabled else self._theme.subtle))
        self.primary.setToolTip("Ctrl + Enter")
        self.hint.setText(hint)
        for widget in (self.new_button, self.existing_button, self.change_target,
                       self.more_button, self.bind_button, self.theme_button):
            widget.setEnabled(not busy)
        self.new_button.setEnabled(not busy and not selecting)
        self.existing_button.setEnabled(not busy and not selecting)
        self.editor.setReadOnly(busy)
        self.bind_button.setEnabled(not busy and not selecting)
        can_capture = bool(self.controller.target and self.controller.target.hwnd)
        self.include_image.setEnabled(can_capture and not busy and not selecting)
        self.preview_button.setEnabled(can_capture and not busy and not selecting)
        self.close_button.setEnabled(not busy)
        for button in self.quick_task_buttons:
            button.setEnabled(bool(self.controller.target) and not busy and not selecting)

    def _trigger_primary(self) -> None:
        if self.primary.isEnabled():
            self.primary.click()

    def show_notice(self, text: str, **kwargs) -> None:
        self._notice_key, self._notice_kwargs = str(text), kwargs
        self.notice.setText(tr(self._notice_key, **self._notice_kwargs))
        self.notice.setVisible(bool(text))
        self._fit_content()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.controller.busy:
            event.ignore()
            return
        self.controller.draft = self.editor.toPlainText()
        self.controller.cancel_selection()
        super().closeEvent(event)
