"""Pointer launch tests use fake processes and IPC; never open a real window."""

import ctypes
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from codex_pointer import launcher


def status(*, running=False, ready=False, gui=True, platform="win32"):
    return {
        "platform": platform,
        "running": running,
        "control_available": ready,
        "gui_available": gui,
    }


class LauncherTests(unittest.TestCase):
    def test_read_status_does_not_signal_or_launch(self):
        native = Mock()
        native.exists.return_value = True
        with patch.object(launcher.sys, "platform", "win32"), \
                patch.object(launcher, "_gui_command", return_value=(["fixed.exe"], Path("."))), \
                patch.object(launcher, "_Win32Control", return_value=native), \
                patch.object(launcher.subprocess, "Popen") as popen:
            self.assertEqual(launcher.pointer_status(), status(running=True, ready=True))
        native.signal.assert_not_called()
        popen.assert_not_called()
        self.assertEqual(native.exists.call_count, 3)

    def test_status_without_running_instance_does_not_check_events(self):
        native = Mock()
        native.exists.return_value = False
        with patch.object(launcher.sys, "platform", "win32"), \
                patch.object(launcher, "_gui_command", return_value=None), \
                patch.object(launcher, "_Win32Control", return_value=native):
            self.assertEqual(launcher.pointer_status(), status(gui=False))
        native.exists.assert_called_once_with("mutex", launcher.MUTEX_NAME)

    def test_unsupported_platform_never_loads_win32(self):
        with patch.object(launcher.sys, "platform", "linux"), \
                patch.object(launcher, "_gui_command", return_value=None), \
                patch.object(launcher, "_Win32Control") as factory:
            self.assertEqual(launcher.pointer_status(), status(platform="linux", gui=False))
            with self.assertRaises(launcher.LauncherError):
                launcher.show_pointer()
            with self.assertRaises(launcher.LauncherError):
                launcher.hide_pointer()
        factory.assert_not_called()

    def test_existing_gui_receives_show_event_even_if_companion_missing(self):
        native = Mock()
        native.signal.return_value = True
        with patch.object(launcher, "pointer_status", return_value=status(running=True, ready=True, gui=False)), \
                patch.object(launcher, "_Win32Control", return_value=native), \
                patch.object(launcher.subprocess, "Popen") as popen:
            result = launcher.show_pointer()
        self.assertEqual(result["status"], "shown")
        self.assertTrue(result["requested"])
        native.signal.assert_called_once_with(launcher.SHOW_EVENT_NAME)
        popen.assert_not_called()

    def test_legacy_instance_is_not_duplicated_or_killed(self):
        with patch.object(launcher, "pointer_status", return_value=status(running=True)), \
                patch.object(launcher.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(launcher.LauncherError, "退出旧版"):
                launcher.show_pointer()
            with self.assertRaisesRegex(launcher.LauncherError, "退出旧版"):
                launcher.hide_pointer()
        popen.assert_not_called()

    def test_launch_uses_fixed_argv_detached_stdio_and_no_shell(self):
        process = Mock()
        process.poll.return_value = None
        native = Mock()
        native.signal.return_value = True
        command = [r"C:\Plugin Folder\CodexPointer.exe"]
        directory = Path(r"C:\Plugin Folder")
        with patch.object(launcher, "pointer_status", side_effect=[status(), status(running=True, ready=True)]), \
                patch.object(launcher, "_gui_command", return_value=(command, directory)), \
                patch.object(launcher, "_Win32Control", return_value=native), \
                patch.object(launcher.subprocess, "Popen", return_value=process) as popen:
            self.assertEqual(launcher.show_pointer()["status"], "shown")
        self.assertEqual(popen.call_args.args, (command,))
        self.assertEqual(popen.call_args.kwargs, {
            "cwd": str(directory), "shell": False,
            "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL, "close_fds": True,
            "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        })

    def test_child_exit_does_not_report_success(self):
        process = Mock()
        process.poll.return_value = 2
        with patch.object(launcher, "pointer_status", return_value=status()), \
                patch.object(launcher, "_gui_command", return_value=(["fixed.exe"], Path("."))), \
                patch.object(launcher.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(launcher.LauncherError, "退出码 2"):
                launcher.show_pointer()

    def test_readiness_timeout_reports_only_launch_request(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(launcher, "pointer_status", return_value=status(running=False)), \
                patch.object(launcher, "_gui_command", return_value=(["fixed.exe"], Path("."))), \
                patch.object(launcher.subprocess, "Popen", return_value=process), \
                patch.object(launcher.time, "monotonic", side_effect=[10.0, 13.0]), \
                patch.object(launcher.time, "sleep") as sleep:
            result = launcher.show_pointer()
        self.assertEqual(result["status"], "launch_requested")
        self.assertIn("尚未确认", result["message"])
        process.terminate.assert_not_called()
        sleep.assert_not_called()

    def test_launch_failure_is_actionable(self):
        with patch.object(launcher, "pointer_status", return_value=status()), \
                patch.object(launcher, "_gui_command", return_value=(["fixed.exe"], Path("."))), \
                patch.object(launcher.subprocess, "Popen", side_effect=OSError("blocked")):
            with self.assertRaisesRegex(launcher.LauncherError, "无法启动"):
                launcher.show_pointer()

    def test_missing_companion_never_launches_host_itself(self):
        with patch.object(launcher, "pointer_status", return_value=status(gui=False)), \
                patch.object(launcher, "_gui_command", return_value=None), \
                patch.object(launcher.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(launcher.LauncherError, "完整 Windows 插件包"):
                launcher.show_pointer()
        popen.assert_not_called()

    def test_hide_only_signals_existing_instance(self):
        native = Mock()
        native.signal.return_value = True
        with patch.object(launcher, "pointer_status", return_value=status(running=True, ready=True)), \
                patch.object(launcher, "_Win32Control", return_value=native), \
                patch.object(launcher.subprocess, "Popen") as popen:
            self.assertEqual(launcher.hide_pointer()["status"], "hide_requested")
        native.signal.assert_called_once_with(launcher.HIDE_EVENT_NAME)
        popen.assert_not_called()

    def test_hiding_absent_instance_is_idempotent(self):
        with patch.object(launcher, "pointer_status", return_value=status()), \
                patch.object(launcher, "_Win32Control") as factory:
            self.assertEqual(launcher.hide_pointer()["status"], "already_hidden")
        factory.assert_not_called()

    def test_disappearing_control_channel_does_not_report_success(self):
        native = Mock()
        native.signal.return_value = False
        with patch.object(launcher, "pointer_status", return_value=status(running=True, ready=True)), \
                patch.object(launcher, "_Win32Control", return_value=native):
            with self.assertRaises(launcher.LauncherError):
                launcher.show_pointer()
            with self.assertRaises(launcher.LauncherError):
                launcher.hide_pointer()

    def test_frozen_resolver_uses_only_adjacent_gui(self):
        with patch.object(launcher.sys, "frozen", True, create=True), \
                patch.object(launcher.sys, "executable", str(Path("/plugin/CodexPointerHost.exe").resolve())), \
                patch.object(Path, "is_file", return_value=True):
            argv, directory = launcher._gui_command()
        self.assertEqual(Path(argv[0]).name, "CodexPointer.exe")
        self.assertEqual(Path(argv[0]).parent, directory)
        self.assertEqual(len(argv), 1)

    def test_source_resolver_prefers_packaged_gui(self):
        with patch.object(launcher.sys, "frozen", False, create=True), \
                patch.object(Path, "is_file", return_value=True), \
                patch.object(launcher.importlib.util, "find_spec") as find_spec:
            argv, _ = launcher._gui_command()
        self.assertEqual(Path(argv[0]).name, "CodexPointer.exe")
        find_spec.assert_not_called()

    def test_source_fallback_uses_pythonw_without_importing_qt(self):
        with patch.object(launcher.sys, "frozen", False, create=True), \
                patch.object(Path, "is_file", side_effect=[False, True, True]), \
                patch.object(launcher.importlib.util, "find_spec", return_value=object()):
            argv, directory = launcher._gui_command()
        self.assertEqual(Path(argv[0]).name, "pythonw.exe")
        self.assertEqual(Path(argv[1]), directory / "run.py")

    def test_handles_close_when_signaling_fails(self):
        native = object.__new__(launcher._Win32Control)
        native._open = Mock(return_value=0x100000001)
        native.SetEvent = Mock(return_value=False)
        native.CloseHandle = Mock()
        with patch.object(launcher.ctypes, "get_last_error", return_value=5, create=True):
            with self.assertRaises(launcher.LauncherError):
                native.signal(launcher.SHOW_EVENT_NAME)
        native.CloseHandle.assert_called_once_with(0x100000001)

    def test_native_api_binds_pointer_sized_handles(self):
        dll = Mock()
        with patch.object(launcher.sys, "platform", "win32"), \
                patch.object(launcher.ctypes, "WinDLL", return_value=dll, create=True):
            native = launcher._Win32Control()
        self.assertEqual(native.OpenMutexW.restype, ctypes.wintypes.HANDLE)
        self.assertEqual(native.OpenEventW.restype, ctypes.wintypes.HANDLE)
        self.assertEqual(native.SetEvent.argtypes, [ctypes.wintypes.HANDLE])
        self.assertEqual(native.CloseHandle.argtypes, [ctypes.wintypes.HANDLE])


if __name__ == "__main__":
    unittest.main()
