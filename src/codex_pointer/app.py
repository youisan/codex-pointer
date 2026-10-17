"""Compact native companion. UI and desktop capture remain separate."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict
import json
import os
from pathlib import Path, PureWindowsPath
import sys
import threading
import time
import uuid

from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QPushButton, QVBoxLayout
from shiboken6 import isValid

from .bridge import CodexBridge
from .i18n import language as current_language, set_language, tr
from .codex_language import CodexLanguageReader
from .captures import bundle_reference, save_capture
from .context import build_prompt, working_directory
from .control_events import ControlEvents
from .launcher import LauncherError, MUTEX_NAME, show_pointer
from .panel import TaskPanel
from .routing import binding_for, mode_for, recent_targets, remember_binding, remember_mode, remember_target, route_key
from .settings import data_directory, load_settings, save_settings
from .ui import FloatingButton, Popover, apply_theme, icon
from .ui import theme_for
from .target_preview import TargetPreview
from .windows import (TargetContext, cancel_capture_lookup, close_capture_helpers, enrich_target,
                      capture_screenshot, capture_target, capture_window, get_cursor_position, get_foreground_window,
                      target_from_path)


def system_theme():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return "light" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else "dark"
    except (ImportError, OSError):
        return "light"


def system_reduced_motion():
    if sys.platform != "win32":
        return False
    enabled = wintypes.BOOL(True)
    ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
    return not bool(enabled.value)


def translated(widget, key, method="setText", **kwargs):
    """Keep the source of auxiliary dialog labels for in-place translation."""
    bindings = getattr(widget, "_pointer_translations", {})
    bindings[method] = (key, kwargs)
    widget._pointer_translations = bindings
    getattr(widget, method)(tr(key, **kwargs))
    return widget


class WorkerSignals(QObject):
    finished = Signal(object, object)


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback, cancel=None):
        super().__init__()
        self.callback, self.cancel = callback, cancel

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32" and event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam == 0x5042:
                QTimer.singleShot(0, self.callback)
                return True, 0
            if msg.message == 0x0312 and msg.wParam == 0x5043 and self.cancel:
                self.cancel()
                return True, 0
        return False, 0


class PointerController(QObject):
    def __init__(self, application, *, preview=False, theme=None, reduced_motion=None, language=None):
        super().__init__()
        self.application, self.preview = application, preview
        if language is not None:
            set_language(language)
        self._language_reader = None if preview or language is not None else CodexLanguageReader()
        self._language_job_active = False
        self.settings = {} if preview else load_settings()
        # The former global binding must not follow an unrelated new target.
        self.settings.pop("thread_id", None)
        self.settings.pop("thread_title", None)
        selected = theme or self.settings.get("theme", "system")
        self.theme = theme_for(system_theme() if selected == "system" else selected)
        self.reduced_motion = self.settings.get("reduced_motion", system_reduced_motion()) if reduced_motion is None else reduced_motion
        self.mode = "new"
        self.draft, self.target = "", None
        self.image_path, self.cached_scope, self.image_scope = None, None, "window"
        self.busy, self.shared_ready, self.last_external = False, False, 0
        self.control_events, self.control_timer = None, None
        self.hide_pending, self.show_pending = False, False
        self.panel, self.picker = None, None
        self.selecting, self._closing = False, False
        self._selection_revision = 0
        self._jobs = {}
        self._drag_active, self._drag_restore_panel = False, False
        self._drag_revision, self._drag_point = 0, None
        self._drag_physical, self._drag_fast_point = None, None
        self._drag_context, self._drag_enriched_point = None, None
        self._drag_stable_since = 0.0
        self.target_preview = None
        self.bridge = CodexBridge()
        self.signals = WorkerSignals(self)
        self.signals.finished.connect(self.worker_finished)
        self.position_save_timer = QTimer(self)
        self.position_save_timer.setSingleShot(True)
        self.position_save_timer.timeout.connect(self.persist)
        self.drag_timer = QTimer(self)
        self.drag_timer.setInterval(90)
        self.drag_timer.timeout.connect(self.refresh_drag_preview)
        apply_theme(application, self.theme)
        self.button = FloatingButton(self.theme, self.reduced_motion)
        self.button.clicked.connect(self.capture_recent)
        self.button.dropped.connect(self.capture_drop)
        self.button.file_dropped.connect(self.capture_dropped_path)
        self.button.drag_started.connect(self.drag_started)
        self.button.drag_moved.connect(self.drag_moved)
        self.button.drag_cancelled.connect(self.drag_cancelled)
        self.button.moved.connect(self.save_position)
        self.button.menu_requested.connect(self.button_menu)
        x, y = int(self.settings.get("x", 72)), int(self.settings.get("y", 180))
        if not any(s.availableGeometry().contains(QPoint(x, y)) for s in application.screens()):
            x, y = 72, 180
        self.button.move(x, y)
        application.installEventFilter(self)
        self.language_timer = QTimer(self)
        self.language_timer.setInterval(1000)
        self.language_timer.timeout.connect(self.refresh_language)
        if not preview:
            self.language_timer.start()
            self.refresh_language()
            self.tracker = QTimer(self)
            self.tracker.timeout.connect(self.track_foreground)
            self.tracker.start(300)
            self.hotkey = HotkeyFilter(self.capture_hotkey, self.button.cancel_drag)
            application.installNativeEventFilter(self.hotkey)
            self.hotkey_registered = bool(ctypes.windll.user32.RegisterHotKey(None, 0x5042, 0x4003, 0x20))
            application.aboutToQuit.connect(self.cleanup)

    def refresh_language(self):
        # Config reads stay off the GUI thread, including redirected home paths.
        if self._closing or self._language_reader is None or self._language_job_active:
            return
        self._language_job_active = True
        def done(code):
            self._language_job_active = False
            self.apply_language(code)
        def failed(_error):
            self._language_job_active = False
        self.run_worker(self._language_reader.read, done, failed)

    def apply_language(self, code):
        if code == current_language():
            return
        set_language(code)
        self.button.retranslate_ui()
        if self.panel:
            self.panel.retranslate_ui()
        if self.target_preview:
            self.target_preview.retranslate_ui()
        for window in self.application.topLevelWidgets():
            if not isValid(window):
                continue
            for widget in [window, *window.findChildren(QObject)]:
                for method, (key, kwargs) in getattr(widget, "_pointer_translations", {}).items():
                    getattr(widget, method)(tr(key, **kwargs))

    def persist(self):
        if not self.preview:
            save_settings(self.settings)

    def save_position(self, x, y):
        self.settings.update(x=x, y=y)
        if not self.button.is_dragging:
            self.position_save_timer.start(300)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self._drag_active:
            self.button.cancel_drag()
            return True
        return False

    def submit_latest(self, channel, work, done, failed):
        """Bound each lookup lane to one active job and its latest replacement."""
        state = self._jobs.setdefault(channel, {"active": False, "pending": None})
        state["pending"] = (work, done, failed)
        self.drain_latest(channel)

    def drain_latest(self, channel):
        state = self._jobs[channel]
        if self._closing or state["active"] or not state["pending"]:
            return
        work, done, failed = state["pending"]
        state["pending"], state["active"] = None, True
        def finish(callback, value):
            state["active"] = False
            try:
                if not self._closing:
                    callback(value)
            finally:
                self.drain_latest(channel)
        self.run_worker(work, lambda value: finish(done, value), lambda error: finish(failed, error))

    def drag_started(self):
        if self.busy:
            self.button.cancel_drag()
            return
        self.cancel_selection()
        self._drag_active = True
        if sys.platform == "win32" and not self.preview:
            self.drag_escape_registered = bool(ctypes.windll.user32.RegisterHotKey(None, 0x5043, 0x4000, 0x1B))
        self._drag_revision += 1
        self._drag_physical, self._drag_fast_point = None, None
        self._drag_context, self._drag_enriched_point = None, None
        self._drag_restore_panel = bool(self.panel and self.panel.isVisible())
        if self._drag_restore_panel:
            self.draft = self.panel.editor.toPlainText()
            self.panel.hide()
        self.position_save_timer.stop()
        if self.target_preview is None:
            self.target_preview = TargetPreview(self.theme, self.reduced_motion)
        self.drag_timer.start()

    def drag_moved(self, x, y):
        if not self._drag_active:
            return
        self._drag_point = QPoint(x, y)
        physical = (x, y) if self.preview else get_cursor_position()
        if physical != self._drag_physical:
            first_point = self._drag_physical is None
            self._drag_physical = physical
            self._drag_stable_since = time.monotonic()
            self._drag_enriched_point = None
            if first_point:
                self.target_preview.show_context(None, cursor=self._drag_point, fallback_text="正在识别 · Esc 取消")
        self.target_preview.move_near(self._drag_point)

    def refresh_drag_preview(self):
        if not self._drag_active or self._drag_physical is None:
            return
        revision, point = self._drag_revision, self._drag_physical
        if point != self._drag_fast_point:
            self._drag_fast_point = point
            def done(target):
                if self._drag_active and revision == self._drag_revision and point == self._drag_physical:
                    self._drag_context = target
                    self.target_preview.show_context(target, cursor=self._drag_point,
                                                     resolving=bool(target.explorer))
            def failed(error):
                if self._drag_active and revision == self._drag_revision and point == self._drag_physical:
                    self._drag_context = None
                    self.target_preview.show_context(None, cursor=self._drag_point,
                                                     fallback_text="未识别到窗口 · Esc 取消")
            self.submit_latest("fast", lambda: demo_target() if self.preview else capture_target(*point, enrich=False),
                               done, failed)
        target = self._drag_context
        if (target and target.explorer and target.point == point and
                self._drag_enriched_point != point and time.monotonic() - self._drag_stable_since >= 0.25):
            self._drag_enriched_point = point
            def enriched(value):
                if self._drag_active and revision == self._drag_revision and point == self._drag_physical:
                    self._drag_context = value
                    self.target_preview.show_context(value, cursor=self._drag_point)
            self.submit_latest("enrich", lambda: enrich_target(target), enriched, lambda error: None)

    def finish_drag(self):
        if getattr(self, "drag_escape_registered", False):
            ctypes.windll.user32.UnregisterHotKey(None, 0x5043)
            self.drag_escape_registered = False
        self._drag_active = False
        self._drag_revision += 1
        self.clear_lookup_queue()
        cancel_capture_lookup()
        self.drag_timer.stop()
        if self.target_preview:
            self.target_preview.hide_preview()
        self.position_save_timer.start(300)

    def drag_cancelled(self):
        self.finish_drag()
        if self._drag_restore_panel:
            self.open_panel()

    def cancel_selection(self):
        self._selection_revision += 1
        self.clear_lookup_queue()
        picker, self.picker = self.picker, None
        if picker:
            picker.close()
        if self.selecting:
            self.selecting = False
            self.target = None
            cancel_capture_lookup()
            self.button.set_busy(False)
            if self.panel:
                self.panel.refresh_target()

    def clear_lookup_queue(self):
        for state in self._jobs.values():
            state["pending"] = None

    def track_foreground(self):
        hwnd = get_foreground_window()
        if hwnd:
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
            if pid.value != os.getpid():
                self.last_external = hwnd

    def capture_recent(self):
        if self.busy:
            return
        if self.panel:
            if self.panel.isVisible():
                self.panel.close()
            else:
                self.open_panel()
            return
        if self.preview:
            self.open_panel()
            return
        point, hwnd = get_cursor_position(), self.last_external
        self.capture(lambda: capture_window(hwnd, point, enrich=False) if hwnd else capture_target(*point, enrich=False))

    def capture_hotkey(self):
        if self.busy:
            return
        self.show_button()
        self.track_foreground()
        point, hwnd = get_cursor_position(), self.last_external
        self.capture(lambda: capture_window(hwnd, point, enrich=False) if hwnd else capture_target(*point, enrich=False))

    def capture_drop(self, *_):
        self.finish_drag()
        if self.busy:
            return
        point = (0, 0) if self.preview else get_cursor_position()
        self.capture(lambda: demo_target() if self.preview else capture_target(*point, enrich=False), show_panel=False)

    def capture_dropped_path(self, path):
        if self.busy:
            return
        self.capture(lambda: target_from_path(path), channel="enrich", show_panel=False)

    def capture(self, work, *, channel="fast", show_panel=True):
        if self.busy:
            return
        self.cancel_selection()
        cancel_capture_lookup()
        revision = self._selection_revision
        self.selecting, self.target = True, None
        self.settings.pop("thread_id", None)
        self.settings.pop("thread_title", None)
        self.invalidate_image()
        if self.picker:
            self.picker.close()
        self.button.set_busy(True)
        self.open_panel(reveal=show_panel)
        self.panel.show_notice("")
        def current():
            return not self._closing and revision == self._selection_revision
        def complete(target):
            if not current():
                return
            self.selecting = False
            self.button.set_busy(False)
            self.target = target
            self.apply_route(target)
            remember_target(self.settings, target)
            self.persist()
            self.panel.refresh_target()
            notice = "已选择资源管理器当前打开的目录。" if target.source == "explorer-current-folder" else ""
            if self.mode == "existing" and self.settings.get("thread_id"):
                notice = "已恢复这个对象上次选择的对话。" + notice
            self.panel.show_notice(notice)
        def done(target):
            if not current():
                return
            self.target = target
            self.panel.refresh_target()
            if target.explorer:
                self.submit_latest("enrich", lambda: enrich_target(target), complete, failed)
            else:
                complete(target)
        def failed(error):
            if not current():
                return
            self.selecting, self.target = False, None
            self.button.set_busy(False)
            self.panel.refresh_target()
            self.panel.show_notice("未能识别目标：{error}", error=error)
        self.submit_latest(channel, work, done, failed)

    def apply_route(self, target):
        self.settings.pop("thread_id", None)
        self.settings.pop("thread_title", None)
        binding = binding_for(self.settings, target)
        if binding:
            self.settings.update(thread_id=binding["thread_id"], thread_title=binding["thread_title"])
        self.mode = mode_for(self.settings, target)
        if self.panel:
            self.panel.set_mode(self.mode)

    def set_mode(self, mode):
        mode = "existing" if mode == "existing" else "new"
        remember_mode(self.settings, self.target, mode)
        self.persist()
        self.panel.set_mode(mode)

    def open_panel(self, *, reveal=True):
        if not self.panel:
            self.panel = TaskPanel(self)
        self.panel.refresh_target()
        if not reveal:
            if self.panel.isVisible():
                self.draft = self.panel.editor.toPlainText()
                self.panel.hide()
            return
        if not self.panel.isVisible():
            self.panel.editor.setPlainText(self.draft)
            self.panel.reveal(self.button.geometry())
        else:
            self.panel.raise_()
        self.panel.editor.setFocus()

    def choose_folder(self):
        if self.busy:
            return
        selected = QFileDialog.getExistingDirectory(self.panel or self.button, tr("选择要交给 Codex 的文件夹"))
        if selected:
            target = TargetContext(kind="folder", title=PureWindowsPath(selected).name or selected,
                path=selected, point=get_cursor_position() if not self.preview else (0, 0), source="folder-picker")
            self.capture(lambda: target)

    def toggle_theme(self):
        if self.busy:
            return
        self.draft = self.panel.editor.toPlainText() if self.panel else self.draft
        include_image = bool(self.panel and self.panel.include_image.isChecked())
        self.theme = theme_for("dark" if self.theme.name == "light" else "light")
        self.settings["theme"] = self.theme.name
        self.persist()
        apply_theme(self.application, self.theme)
        self.button.set_theme(self.theme)
        if self.target_preview:
            self.target_preview.set_theme(self.theme)
        if self.picker:
            self.picker.close()
        if self.panel:
            self.panel.hide()
            self.panel.deleteLater()
            self.panel = None
        self.open_panel()
        self.panel.include_image.blockSignals(True)
        self.panel.include_image.setChecked(include_image)
        self.panel.include_image.blockSignals(False)

    def invalidate_image(self, *_):
        self.image_path, self.cached_scope = None, None

    def primary_action(self):
        if self.busy or self.selecting or not self.panel or not self.panel.primary.isEnabled():
            return
        if self.mode == "existing" and not self.settings.get("thread_id"):
            self.pick_thread()
        else:
            self.execute("existing" if self.mode == "existing" else "draft")

    def set_busy(self, busy):
        self.busy = busy
        self.button.set_busy(busy)
        if self.panel:
            for widget in (self.panel.editor, self.panel.new_button, self.panel.existing_button,
                           self.panel.change_target, self.panel.more_button, self.panel.theme_button):
                widget.setEnabled(not busy)
            can_capture = not busy and bool(self.target and self.target.hwnd)
            self.panel.include_image.setEnabled(can_capture)
            self.panel.preview_button.setEnabled(can_capture)
            self.panel.refresh_primary()

    def execute(self, action):
        if self.busy or self.selecting or not self.panel:
            return
        target, instruction = self.target, self.panel.editor.toPlainText().strip()
        if not target or (not instruction and action != "image"):
            self.panel.show_notice("先选择目标，再写下你想完成的事。")
            return
        if self.preview:
            self.panel.show_notice("这是界面预览，未捕获屏幕，也未发送任务。")
            return
        image_requested = action == "image" or self.panel.include_image.isChecked()
        if image_requested and not target.hwnd:
            self.panel.show_notice("这个目标没有可截图的窗口，请重新选择软件窗口。")
            return
        scope = self.image_scope
        image = self.image_path if self.cached_scope == scope and self.image_path and self.image_path.exists() else None
        need_capture = image_requested and image is None
        hidden = []
        self.set_busy(True)
        self.panel.show_notice("正在准备截图…" if need_capture else "正在打开 Codex…" if action == "draft" else "正在提交任务…")
        if need_capture:
            hidden = [w for w in self.application.topLevelWidgets()
                      if isinstance(w, (FloatingButton, Popover, QDialog)) and w.isVisible()]
            for widget in hidden:
                widget.hide()
        thread_id = self.settings.get("thread_id")
        def work():
            output = image if image_requested else None
            if need_capture:
                folder = data_directory() / "captures"
                folder.mkdir(parents=True, exist_ok=True)
                for stale in folder.glob("*.png"):
                    try:
                        if stale.stat().st_mtime < time.time() - 86400:
                            stale.unlink()
                    except OSError:
                        pass
                output = folder / f"capture-{time.time_ns()}.png"
                crop = None
                if scope == "nearby":
                    x, y = target.point
                    crop = (x - 320, y - 240, x + 320, y + 240)
                capture_screenshot(target, output, crop_rect=crop)
            if action == "image":
                return {"image": output, "scope": scope, "result": None}
            identifier, bundle = save_capture(target, instruction, output)
            cwd = working_directory(target, data_directory() / "workspace")
            reference = bundle_reference(identifier, bundle)
            if action == "draft":
                result = self.bridge.open_new_draft(tr("用户请求：") + instruction + reference, cwd)
            else:
                prompt = build_prompt(target, instruction, str(output) if output else None) + reference
                result = self.bridge.send_existing(thread_id, prompt, cwd=cwd) if action == "existing" else self.bridge.send_new(prompt, cwd)
            return {"image": output, "scope": scope, "result": result}
        def restore():
            for widget in hidden:
                if isValid(widget):
                    widget.show()
            self.set_busy(False)
            self.panel.raise_()
        def done(value):
            restore()
            self.image_path, self.cached_scope = value["image"], value["scope"]
            if action == "image":
                self.panel.show_notice("")
                self.show_image(value["image"])
                return
            result = value["result"]
            self.button.set_success()
            if result.status == "draft_opened":
                self.panel.show_notice("已请求打开新对话并预填任务。请在 Codex 中确认后发送。")
            else:
                if action == "direct_new":
                    if route_key(target):
                        remember_binding(self.settings, target, result.thread_id, target.title)
                    self.settings.update(thread_id=result.thread_id, thread_title=target.title)
                    self.persist()
                    self.panel.set_mode("existing")
                self.panel.show_notice("任务已排队，请在 Codex 中查看执行进度。" if result.status == "queued" else "任务已提交，请在 Codex 中查看执行进度。")
        def failed(error):
            restore()
            self.panel.show_notice("未确认完成：{error}\n如已提交，请先检查对话再决定是否重发。", error=error)
        QTimer.singleShot(90 if need_capture else 0, lambda: self.run_worker(work, done, failed))

    def preview_image(self):
        self.execute("image")

    def show_image(self, path):
        view = QDialog(self.panel)
        translated(view, "截图预览 · 发送时使用这张图片", "setWindowTitle")
        layout = QVBoxLayout(view)
        label = QLabel()
        label.setPixmap(QPixmap(str(path)).scaled(QSize(880, 580), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(label)
        note = translated(QLabel(), "发送时使用这张预览截图；修改截图范围后会重新生成。")
        note.setObjectName("caption")
        layout.addWidget(note)
        self.panel.include_image.blockSignals(True)
        self.panel.include_image.setChecked(True)
        self.panel.include_image.blockSignals(False)
        view.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        view.show()

    def pick_thread(self):
        if self.busy or self.selecting:
            return
        if self.picker:
            self.picker.raise_()
            return
        picker = self.picker = Popover(self.theme, self.reduced_motion)
        translated(picker, "选择 Codex 对话", "setWindowTitle")
        head = QHBoxLayout()
        head.addWidget(translated(QLabel(), "选择要继续的对话"), 1)
        close = QPushButton()
        close.setObjectName("ghost")
        close.setIcon(icon("x", self.theme.muted))
        close.setFixedSize(32, 32)
        translated(close, "关闭", "setAccessibleName")
        close.clicked.connect(picker.close)
        head.addWidget(close)
        picker.body.addLayout(head)
        search = QLineEdit()
        translated(search, "搜索对话", "setPlaceholderText")
        picker.body.addWidget(search)
        listing = QListWidget()
        listing.setFixedHeight(250)
        picker.body.addWidget(listing)
        manual = QLineEdit()
        translated(manual, "或粘贴完整对话 UUID", "setPlaceholderText")
        picker.body.addWidget(manual)
        info = translated(QLabel(), "正在读取本地对话…")
        info.setObjectName("caption")
        info.setWordWrap(True)
        picker.body.addWidget(info)
        bind = translated(QPushButton(), "使用这条对话")
        bind.setObjectName("primary")
        bind.setIcon(icon("check", self.theme.primary_text))
        picker.body.addWidget(bind)
        rows_cache = []
        target, revision = self.target, self._selection_revision
        def load(rows):
            if self.picker is not picker or not picker.isVisible():
                return
            rows_cache[:] = rows
            listing.clear()
            for thread in rows:
                item = QListWidgetItem((thread.title or thread.preview or tr("未命名对话")).replace("\n", " ")[:80] + "\n" + thread.cwd)
                item.setData(Qt.ItemDataRole.UserRole, thread)
                item.setSizeHint(QSize(390, 56))
                item.setToolTip(thread.id)
                item.setIcon(icon("chat", self.theme.muted, 20))
                listing.addItem(item)
            translated(info, "选择你要继续的对话；不会自动猜测当前打开的是哪条。")
        def load_error(error):
            if self.picker is picker and picker.isVisible():
                translated(info, "列表暂不可用，可粘贴对话 UUID。{error}", error=error)
        def filter_rows(text):
            for i in range(listing.count()):
                listing.item(i).setHidden(text.casefold() not in listing.item(i).text().casefold())
        search.textChanged.connect(filter_rows)
        def selected():
            item = listing.currentItem()
            if item:
                manual.setText(item.data(Qt.ItemDataRole.UserRole).id)
        listing.itemSelectionChanged.connect(selected)
        def bind_selected():
            if self.busy or self.selecting or revision != self._selection_revision:
                return
            try:
                identifier = str(uuid.UUID(manual.text().strip()))
            except ValueError:
                translated(info, "请选择对话，或填写完整的会话 UUID。")
                return
            row = next((r for r in rows_cache if r.id == identifier), None)
            title = (row.title or row.preview) if row else identifier
            if route_key(target):
                remember_binding(self.settings, target, identifier, title)
            self.settings.update(thread_id=identifier, thread_title=title)
            self.persist()
            self.panel.set_mode("existing")
            self.panel.show_notice("已记住这个对象对应的对话。" if route_key(target) else "已选择对话；这个目标暂不支持记忆。")
            picker.close()
        bind.clicked.connect(bind_selected)
        listing.itemDoubleClicked.connect(lambda _: bind_selected())
        picker.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        picker.destroyed.connect(lambda: setattr(self, "picker", None) if self.picker is picker else None)
        picker.reveal(self.panel.geometry() if self.panel else self.button.geometry())
        self.run_worker(lambda: [] if self.preview else self.bridge.list_threads(), load, load_error)

    def show_details_menu(self):
        menu = QMenu(self.panel)
        self.add_recent_menu(menu)
        scope = menu.addMenu(tr("截图范围"))
        scope.setIcon(icon("scan", self.theme.muted))
        for label, value in [(tr("目标窗口"), "window"), (tr("鼠标周边 640 × 480"), "nearby")]:
            action = scope.addAction(icon("window" if value == "window" else "scan", self.theme.muted), label)
            action.setCheckable(True)
            action.setChecked(self.image_scope == value)
            action.triggered.connect(lambda _, value=value: self.set_scope(value))
        menu.addAction(icon("info", self.theme.muted), tr("查看目标与任务"), self.show_context)
        menu.addSeparator()
        menu.addAction(icon("activity", self.theme.muted), tr("检查 Codex 连接"), self.diagnose)
        direct = menu.addAction(icon("arrow-up-right", self.theme.muted), tr("直接创建并发送（实验）"), lambda: self.execute("direct_new"))
        direct.setEnabled(self.shared_ready and self.mode == "new")
        motion = menu.addAction(icon("motion", self.theme.muted), tr("减少动态效果"))
        motion.setCheckable(True)
        motion.setChecked(self.reduced_motion)
        motion.triggered.connect(self.set_reduced_motion)
        menu.exec(self.panel.more_button.mapToGlobal(QPoint(0, self.panel.more_button.height())))

    def set_scope(self, value):
        self.image_scope = value
        self.invalidate_image()

    def set_reduced_motion(self, enabled):
        self.reduced_motion = bool(enabled)
        self.settings["reduced_motion"] = self.reduced_motion
        self.persist()
        self.button.reduced_motion = self.reduced_motion
        self.panel.reduced_motion = self.reduced_motion
        if self.target_preview:
            self.target_preview.reduced_motion = self.reduced_motion

    def show_context(self):
        view = QDialog(self.panel)
        translated(view, "目标与任务", "setWindowTitle")
        view.resize(610, 460)
        layout = QVBoxLayout(view)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        if self.target:
            text.setPlainText(tr("用户任务：\n") + self.panel.editor.toPlainText() + tr("\n\n目标：\n") + json.dumps(asdict(self.target), ensure_ascii=False, indent=2))
        else:
            text.setPlainText(tr("尚未选择目标"))
        layout.addWidget(text)
        view.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        view.show()

    def diagnose(self):
        self.panel.show_notice("正在检查连接，任务内容不会发送…")
        def done(result):
            self.shared_ready = result.get("shared_available", False)
            self.panel.show_notice("共享服务已连接，可在菜单中直接创建并发送。" if self.shared_ready else "直接发送服务暂未连接。新对话可使用桌面预填入口。")
        self.run_worker(self.bridge.diagnostics, done, lambda e: self.panel.show_notice("连接检查未完成：{error}", error=e))

    def button_menu(self, point):
        menu = QMenu()
        menu.addAction(icon("folder-open", self.theme.muted), tr("选择文件夹…"), self.choose_folder)
        self.add_recent_menu(menu)
        menu.addAction(icon("panel", self.theme.muted), tr("打开任务面板"), self.open_panel)
        menu.addAction(icon("eye-off", self.theme.muted), tr("隐藏按钮"), self.hide_button)
        menu.addSeparator()
        menu.addAction(icon("logout", self.theme.muted), tr("退出 Codex Pointer"), self.quit)
        menu.exec(point)

    def add_recent_menu(self, menu):
        rows = [row for row in recent_targets(self.settings) if row["kind"] in ("folder", "file") and row.get("path")]
        recent = menu.addMenu(tr("最近对象"))
        recent.setIcon(icon("history", self.theme.muted))
        recent.setEnabled(bool(rows) and not self.busy)
        for row in rows:
            action = recent.addAction(icon("folder" if row["kind"] == "folder" else "file", self.theme.muted),
                                      row["title"] or PureWindowsPath(row["path"]).name)
            action.setToolTip(row["path"])
            action.triggered.connect(lambda _, row=row: self.capture(lambda: TargetContext(
                kind=row["kind"], title=row["title"], path=row["path"], source="recent")))

    def enable_controls(self):
        self.control_events = ControlEvents()
        self.control_timer = QTimer(self)
        self.control_timer.timeout.connect(self.poll_controls)
        self.control_timer.start(200)

    def poll_controls(self):
        try:
            show, hide = self.control_events.poll()
        except OSError:
            self.control_events.close()
            self.control_timer.stop()
            return
        if show:
            self.show_button()
        elif hide:
            self.hide_pending = True
            self.show_pending = False
        if self.show_pending and not self.busy:
            self.show_button()
        if self.hide_pending and not self.busy:
            self.hide_button()

    def show_button(self):
        self.hide_pending = False
        if self.busy:
            self.show_pending = True
            return
        self.show_pending = False
        self.button.show()
        self.button.raise_()

    def hide_button(self):
        self.show_pending = False
        if self.busy:
            self.hide_pending = True
            return
        self.hide_pending = False
        self.cancel_selection()
        if self._drag_active:
            self.button.cancel_drag()
        if self.panel:
            self.draft = self.panel.editor.toPlainText()
        for widget in self.application.topLevelWidgets():
            if isValid(widget):
                widget.hide()

    def run_worker(self, work, done, failed):
        def run():
            try:
                value, callback = work(), done
            except Exception as exc:
                value, callback = exc, failed
            if not self._closing:
                try:
                    self.signals.finished.emit(callback, value)
                except RuntimeError:
                    pass  # Qt may have been destroyed during shutdown.
        threading.Thread(target=run, daemon=True).start()

    def worker_finished(self, callback, value):
        if self._closing:
            return
        try:
            callback(value)
        except Exception as exc:
            self.set_busy(False)
            if self.panel:
                self.panel.show_notice("界面更新未完成：{error}", error=exc)

    def quit(self):
        if not self.busy:
            self.persist()
            self.application.quit()

    def cleanup(self):
        if self._closing:
            return
        self._closing = True
        self.clear_lookup_queue()
        self.drag_timer.stop()
        self.language_timer.stop()
        self.position_save_timer.stop()
        self.application.removeEventFilter(self)
        if hasattr(self, "tracker"):
            self.tracker.stop()
        if hasattr(self, "hotkey"):
            self.application.removeNativeEventFilter(self.hotkey)
        if getattr(self, "drag_escape_registered", False):
            ctypes.windll.user32.UnregisterHotKey(None, 0x5043)
            self.drag_escape_registered = False
        close_capture_helpers()
        if self.target_preview:
            self.target_preview.hide_preview()
        if getattr(self, "hotkey_registered", False):
            ctypes.windll.user32.UnregisterHotKey(None, 0x5042)
            self.hotkey_registered = False
        if self.control_timer:
            self.control_timer.stop()
        if self.control_events:
            self.control_events.close()


def demo_target():
    return TargetContext(kind="folder", title=tr("项目资料"), path=tr("D:/Projects/项目资料"), source="preview", point=(0, 0))


def run(smoke_test=False, *, preview=False, theme=None, render_path=None, language=None):
    mutex = None
    kernel = None
    live = sys.platform == "win32" and not (smoke_test or render_path or preview)
    if live:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        mutex = kernel.CreateMutexW(None, False, MUTEX_NAME)
        if not mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:
            kernel.CloseHandle(mutex)
            try:
                show_pointer()
            except LauncherError:
                pass  # An older instance needs to be quit by the user.
            return
    try:
        _run_gui(smoke_test, preview=preview, theme=theme, render_path=render_path, live=live, language=language)
    finally:
        if mutex:
            kernel.CloseHandle(mutex)


def _run_gui(smoke_test=False, *, preview=False, theme=None, render_path=None, live=False, language=None):
    if smoke_test or render_path:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName("Codex Pointer")
    application.setQuitOnLastWindowClosed(False)
    # Offscreen Qt has no platform font discovery; load installed system fonts
    # for our own widget renders. No font files are distributed with the app.
    if application.platformName() == "offscreen" and sys.platform == "win32":
        for name in ["segoeui.ttf", "seguisb.ttf", "msyh.ttc"]:
            QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
    controller = PointerController(application, preview=preview or smoke_test or bool(render_path),
                                   theme=theme, language=language)
    application.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "pointer.ico")))
    controller.button.show()
    if live:
        controller.enable_controls()
    if preview or smoke_test or render_path:
        controller.target = demo_target()
        controller.open_panel()
    if render_path:
        controller.panel.show()
        for _ in range(4):
            application.processEvents()
        path = Path(render_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not controller.panel.grab().save(str(path)):
            raise RuntimeError(tr("无法保存界面预览。"))
        controller.panel.close()
        controller.button.close()
        return
    if smoke_test:
        QTimer.singleShot(280, application.quit)
    try:
        application.exec()
    finally:
        controller.cleanup()
