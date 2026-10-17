"""Show and hide the native Pointer without importing Qt into the MCP host.

Only the shipped companion executable (or this checkout's source entry point)
can be launched. Named events request visibility changes in the GUI process;
this module never injects input, captures a screen, or terminates a process.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import importlib.util
from pathlib import Path
import subprocess
import sys
import time


MUTEX_NAME = r"Local\CodexPointer-v1"
SHOW_EVENT_NAME = r"Local\CodexPointer-show-v1"
HIDE_EVENT_NAME = r"Local\CodexPointer-hide-v1"
_READY_TIMEOUT_SECONDS = 3.0
_POLL_INTERVAL_SECONDS = 0.1


class LauncherError(RuntimeError):
    """The native Pointer could not accept the requested action."""


class _Win32Control:
    """Minimal handle-safe Windows visibility IPC; loaded only on demand."""

    SYNCHRONIZE = 0x00100000
    EVENT_MODIFY_STATE = 0x0002
    ERROR_FILE_NOT_FOUND = 2
    ERROR_INVALID_NAME = 123

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise LauncherError("Codex Pointer 的悬浮按钮目前仅支持 Windows。")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        for name, result, arguments in (
            ("OpenMutexW", wintypes.HANDLE,
             [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]),
            ("OpenEventW", wintypes.HANDLE,
             [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]),
            ("SetEvent", wintypes.BOOL, [wintypes.HANDLE]),
            ("CloseHandle", wintypes.BOOL, [wintypes.HANDLE]),
        ):
            function = getattr(self.kernel32, name)
            function.restype = result
            function.argtypes = arguments
            setattr(self, name, function)

    def _open(self, kind: str, name: str):
        access = self.SYNCHRONIZE
        if kind == "event":
            access |= self.EVENT_MODIFY_STATE
        opener = self.OpenEventW if kind == "event" else self.OpenMutexW
        handle = opener(access, False, name)
        if not handle:
            error = ctypes.get_last_error()
            if error in (self.ERROR_FILE_NOT_FOUND, self.ERROR_INVALID_NAME):
                return None
            raise LauncherError(
                f"无法访问 Codex Pointer 的本地控制通道（Windows 错误 {error}）。"
                "请确保悬浮按钮与 Codex 使用相同的 Windows 用户和权限运行。"
            )
        return handle

    def exists(self, kind: str, name: str) -> bool:
        handle = self._open(kind, name)
        if not handle:
            return False
        try:
            return True
        finally:
            self.CloseHandle(handle)

    def signal(self, name: str) -> bool:
        handle = self._open("event", name)
        if not handle:
            return False
        try:
            if not self.SetEvent(handle):
                error = ctypes.get_last_error()
                raise LauncherError(f"无法请求更改悬浮按钮的显示状态（Windows 错误 {error}）。")
            return True
        finally:
            self.CloseHandle(handle)


def _gui_command() -> tuple[list[str], Path] | None:
    """Resolve a fixed local companion; never accept a caller-supplied path."""
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve().parent / "CodexPointer.exe"
        return ([str(executable)], executable.parent) if executable.is_file() else None

    repository = Path(__file__).resolve().parents[2]
    executable = repository / "plugins" / "codex-pointer" / "bin" / "CodexPointer.exe"
    if executable.is_file():
        return [str(executable)], executable.parent

    # pythonw avoids an additional console; find_spec does not import PySide6.
    entrypoint = repository / "run.py"
    pythonw = Path(sys.executable).resolve().with_name("pythonw.exe")
    if entrypoint.is_file() and pythonw.is_file():
        try:
            qt_available = importlib.util.find_spec("PySide6") is not None
        except (ImportError, ValueError):
            qt_available = False
        if qt_available:
            return [str(pythonw), str(entrypoint)], repository
    return None


def pointer_status() -> dict:
    """Read availability without launching the GUI or changing visibility."""
    status = {
        "platform": sys.platform,
        "running": False,
        "control_available": False,
        "gui_available": _gui_command() is not None,
    }
    if sys.platform != "win32":
        return status
    native = _Win32Control()
    status["running"] = native.exists("mutex", MUTEX_NAME)
    if status["running"]:
        status["control_available"] = (
            native.exists("event", SHOW_EVENT_NAME)
            and native.exists("event", HIDE_EVENT_NAME)
        )
    return status


def _require_windows(status: dict) -> None:
    if status["platform"] != "win32":
        raise LauncherError("Codex Pointer 的悬浮按钮目前仅支持 Windows。")


def _legacy_instance_error() -> LauncherError:
    return LauncherError(
        "检测到正在运行的 Codex Pointer，但显示控制尚未就绪。"
        "如果是旧版悬浮按钮，请先在其右键菜单中退出旧版，再重新打开；"
        "如果刚刚启动，请稍后重试。"
    )


def _show_existing(status: dict) -> dict:
    if not _Win32Control().signal(SHOW_EVENT_NAME):
        raise LauncherError("悬浮按钮的控制通道已关闭，请重试打开。")
    return {
        **status,
        "status": "shown",
        "requested": True,
        "message": "已向正在运行的悬浮按钮发送显示请求。",
    }


def show_pointer() -> dict:
    """Show an existing GUI or launch the packaged companion and wait briefly."""
    status = pointer_status()
    _require_windows(status)
    if status["control_available"]:
        return _show_existing(status)
    if status["running"]:
        raise _legacy_instance_error()
    command = _gui_command()
    if command is None:
        raise LauncherError(
            "找不到 CodexPointer.exe。请安装完整 Windows 插件包，"
            "并保留 CodexPointerHost.exe 旁的 CodexPointer.exe 和 _internal 文件夹。"
        )
    argv, working_directory = command
    try:
        process = subprocess.Popen(
            argv,
            cwd=str(working_directory),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
    except OSError as error:
        raise LauncherError(f"无法启动 Codex Pointer：{error}") from error

    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    while True:
        return_code = process.poll()
        status = pointer_status()
        if status["control_available"]:
            return _show_existing(status)
        if return_code is not None:
            raise LauncherError(
                f"Codex Pointer 在控制通道就绪前退出（退出码 {return_code}）。"
                "请重新安装完整插件包后重试。"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {
                **status,
                "status": "launch_requested",
                "requested": True,
                "message": "已启动悬浮按钮进程，但尚未确认显示控制就绪，请稍后检查或重试。",
            }
        time.sleep(min(_POLL_INTERVAL_SECONDS, remaining))


def hide_pointer() -> dict:
    """Request hiding without exiting the GUI or losing its in-memory draft."""
    status = pointer_status()
    _require_windows(status)
    if not status["running"]:
        return {
            **status,
            "status": "already_hidden",
            "requested": False,
            "message": "悬浮按钮没有运行。",
        }
    if not status["control_available"]:
        raise _legacy_instance_error()
    if not _Win32Control().signal(HIDE_EVENT_NAME):
        raise LauncherError("悬浮按钮的控制通道已关闭，请重试隐藏。")
    return {
        **status,
        "status": "hide_requested",
        "requested": True,
        "message": "已发送隐藏请求；正在选择目标或发送任务时会延后处理。",
    }
