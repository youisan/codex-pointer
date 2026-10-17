"""Dropped path validation uses only owned fixtures, not desktop state."""
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from codex_pointer import windows
from codex_pointer.explorer_worker import ExplorerWorker, ExplorerWorkerError, ExplorerWorkerTimeout


class DroppedPathTests(unittest.TestCase):
    def test_verified_file_returns_context_without_a_window_or_screenshot_scope(self):
        worker = Mock(spec=ExplorerWorker)
        worker.query_path.return_value = {
            "path": "C:/Projects/资料 one.txt", "kind": "file", "source": "file-drop"}
        with patch.object(windows, "_explorer_worker", worker), \
                patch.object(Path, "stat", side_effect=AssertionError("No host stat")), \
                patch.object(Path, "resolve", side_effect=AssertionError("No host resolution")), \
                patch.object(windows, "_api", side_effect=AssertionError("No desktop access")):
            target = windows.target_from_path("C:/Projects/资料 one.txt")
        worker.query_path.assert_called_once_with("C:/Projects/资料 one.txt")
        self.assertEqual(target.path, "C:/Projects/资料 one.txt")
        self.assertEqual(target.title, "资料 one.txt")
        self.assertEqual(target.kind, "file")
        self.assertEqual(target.source, "file-drop")
        self.assertEqual(target.hwnd, 0)
        self.assertFalse(target.explorer)
        self.assertIsNone(target.point)

    def test_unc_folder_metadata_keeps_the_selected_share_path(self):
        worker = Mock(spec=ExplorerWorker)
        worker.query_path.return_value = {
            "path": r"\\server\Share name\项目", "kind": "folder", "source": "file-drop"}
        with patch.object(windows, "_explorer_worker", worker):
            target = windows.target_from_path("//server/Share name/项目")
        self.assertEqual(target.title, "项目")
        self.assertEqual(target.kind, "folder")
        self.assertEqual(target.path, r"\\server\Share name\项目")

    def test_unavailable_path_is_a_clear_failure_instead_of_a_guessed_target(self):
        worker = Mock(spec=ExplorerWorker)
        worker.query_path.return_value = {"path": None, "error": "path-unavailable"}
        with patch.object(windows, "_explorer_worker", worker):
            with self.assertRaisesRegex(windows.WindowsCaptureError, "移动|访问"):
                windows.target_from_path("C:/missing")

    def test_timeouts_and_cancelled_queries_are_reported_in_chinese(self):
        for error, text in [(ExplorerWorkerTimeout("offline"), "超时"),
                            (ExplorerWorkerError("cancelled"), "重新拖入")]:
            worker = Mock(spec=ExplorerWorker)
            worker.query_path.side_effect = error
            with self.subTest(error=error), patch.object(windows, "_explorer_worker", worker):
                with self.assertRaisesRegex(windows.WindowsCaptureError, text):
                    windows.target_from_path("//offline-server/share/one")

    def test_invalid_metadata_type_source_and_relative_path_are_rejected(self):
        for data in [{"path": "C:/one", "kind": "device", "source": "file-drop"},
                     {"path": "C:/one", "kind": "file", "source": "window"},
                     {"path": "one.txt", "kind": "file", "source": "file-drop"},
                     {"path": None, "kind": "folder", "source": "file-drop"}, []]:
            worker = Mock(spec=ExplorerWorker)
            worker.query_path.return_value = data
            with self.subTest(data=data), patch.object(windows, "_explorer_worker", worker):
                with self.assertRaises(windows.WindowsCaptureError):
                    windows.target_from_path("C:/one")

    def test_production_encoded_command_stays_within_windows_launch_limit(self):
        command = ExplorerWorker(windows._EXPLORER_WORKER_SCRIPT)._command()
        self.assertLess(len(subprocess.list2cmdline(command)), 32767)


@unittest.skipUnless(sys.platform == "win32", "Production path helper requires Windows")
class OwnedPathIntegrationTests(unittest.TestCase):
    def test_literal_file_folder_missing_and_reuse_in_production_powershell(self):
        # Brackets, quote and $() are literal filename characters. This would
        # fail if a path were interpolated into executable PowerShell source.
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "目录 [one] O'Brien $()"
            folder.mkdir()
            file = folder / "资料 $(throw 1).txt"
            file.write_bytes(b"Owned fixture content; production must only inspect metadata.")
            with ExplorerWorker(windows._EXPLORER_WORKER_SCRIPT) as worker:
                first = worker.query_path(str(file))
                process = worker._process
                missing = worker.query_path(str(folder / "missing.txt"))
                second = worker.query_path(str(folder))
                self.assertIs(worker._process, process)
                self.assertIsNone(process.poll())
            self.assertEqual(first["kind"], "file")
            self.assertEqual(first["source"], "file-drop")
            self.assertEqual(first["path"], str(file))
            self.assertEqual(second["kind"], "folder")
            self.assertEqual(second["path"], str(folder))
            self.assertEqual(missing["error"], "path-unavailable")
            self.assertIsNone(missing["path"])

    def test_context_api_uses_real_owned_file_metadata_without_desktop_capture(self):
        with TemporaryDirectory() as directory:
            file = Path(directory) / "test context 文.txt"
            file.write_bytes(b"fixture")
            with ExplorerWorker(windows._EXPLORER_WORKER_SCRIPT) as worker, \
                    patch.object(windows, "_explorer_worker", worker), \
                    patch.object(windows, "_api", side_effect=AssertionError("No desktop access")):
                target = windows.target_from_path(str(file))
            self.assertEqual(target.kind, "file")
            self.assertEqual(target.title, file.name)
            self.assertEqual(target.path, str(file))
            self.assertEqual(target.source, "file-drop")


if __name__ == "__main__":
    unittest.main()
