"""Capture regression checks that never read real desktop pixels."""

from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
import zlib

from codex_pointer import windows


def decode_fixture_png(data):
    """Read our unfiltered RGB PNG fixtures and validate every chunk CRC."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("Invalid PNG signature")
    offset = 8
    compressed = bytearray()
    dimensions = None
    while offset < len(data):
        size = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + size]
        checksum = struct.unpack(">I", data[offset + 8 + size:offset + 12 + size])[0]
        if checksum != zlib.crc32(kind + payload) & 0xFFFFFFFF:
            raise AssertionError("PNG chunk CRC mismatch")
        if kind == b"IHDR":
            width, height, bits, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if (bits, color, compression, filtering, interlace) != (8, 2, 0, 0, 0):
                raise AssertionError("Unexpected PNG encoding")
            dimensions = width, height
        elif kind == b"IDAT":
            compressed.extend(payload)
        offset += size + 12
    return dimensions, zlib.decompress(compressed)


class FakeNativeApi:
    """Supply empty in-memory pixels; never load a DLL or access the screen."""

    SetThreadDpiAwarenessContext = None

    def __init__(self):
        self.blits = []
        self.dc_requests = 0
        self.valid = True
        self.minimized = False
        self.metrics = {76: 0, 77: 0, 78: 1000, 79: 800}

    def IsWindow(self, hwnd):
        return self.valid

    def IsIconic(self, hwnd):
        return self.minimized

    def GetSystemMetrics(self, index):
        return self.metrics[index]

    def GetDC(self, hwnd):
        self.dc_requests += 1
        return 1

    def CreateCompatibleDC(self, dc):
        return 2

    def CreateCompatibleBitmap(self, dc, width, height):
        return 3

    def SelectObject(self, dc, obj):
        return 4

    def BitBlt(self, *args):
        self.blits.append(args)
        return True

    def GetDIBits(self, dc, bitmap, start, height, buffer, info, mode):
        # ctypes initializes the caller's fixture buffer to zero.
        return height

    def DeleteObject(self, obj):
        return True

    def DeleteDC(self, dc):
        return True

    def ReleaseDC(self, hwnd, dc):
        return 1


class ScreenshotTests(unittest.TestCase):
    def test_png_preserves_rgb_colors_top_down_rows_and_dimensions(self):
        # Two BGR pixels per row, with two padding bytes on each DIB row.
        bgr = bytes([0, 0, 255, 0, 255, 0, 99, 99,
                     255, 0, 0, 255, 255, 255, 88, 88])
        dimensions, rows = decode_fixture_png(windows._encode_png(2, 2, bgr, 8))
        self.assertEqual(dimensions, (2, 2))
        self.assertEqual(rows, bytes([0, 255, 0, 0, 0, 255, 0,
                                      0, 0, 0, 255, 255, 255, 255]))

    def test_explicit_crop_limits_captured_pixels_instead_of_expanding_to_window(self):
        native = FakeNativeApi()
        target = windows.TargetContext(hwnd=123, rect=(1, 2, 3, 4))
        with TemporaryDirectory() as folder, patch.object(windows, "_api", return_value=native), \
                patch.object(windows, "_window_rect", return_value=(100, 110, 900, 710)) as window_rect:
            output = windows.capture_screenshot(target, Path(folder) / "crop.png", crop_rect=(250, 260, 270, 290))
            dimensions, _ = decode_fixture_png(output.read_bytes())
        self.assertEqual(dimensions, (20, 30))
        self.assertEqual(native.blits[-1][3:5], (20, 30))
        self.assertEqual(native.blits[-1][6:8], (250, 260))
        window_rect.assert_not_called()

    def test_default_capture_refreshes_window_bounds_instead_of_using_stale_context(self):
        native = FakeNativeApi()
        target = windows.TargetContext(hwnd=123, rect=(1, 2, 3, 4))
        with TemporaryDirectory() as folder, patch.object(windows, "_api", return_value=native), \
                patch.object(windows, "_window_rect", return_value=(100, 110, 400, 410)) as window_rect:
            output = windows.capture_screenshot(target, Path(folder) / "window.png")
            dimensions, _ = decode_fixture_png(output.read_bytes())
        self.assertEqual(dimensions, (300, 300))
        self.assertEqual(native.blits[-1][6:8], (100, 110))
        window_rect.assert_called_once_with(native, 123)

    def test_crop_clips_to_virtual_desktop_with_negative_monitor_coordinates(self):
        native = FakeNativeApi()
        native.metrics = {76: -20, 77: -10, 78: 1020, 79: 810}
        with TemporaryDirectory() as folder, patch.object(windows, "_api", return_value=native):
            output = windows.capture_screenshot(windows.TargetContext(hwnd=123), Path(folder) / "clipped.png",
                                                crop_rect=(-50, -30, 20, 30))
            dimensions, _ = decode_fixture_png(output.read_bytes())
        self.assertEqual(dimensions, (40, 40))
        self.assertEqual(native.blits[-1][6:8], (-20, -10))

    def test_offscreen_crop_is_rejected_before_accessing_desktop_pixels(self):
        native = FakeNativeApi()
        with TemporaryDirectory() as folder, patch.object(windows, "_api", return_value=native):
            output = Path(folder) / "not-created.png"
            with self.assertRaisesRegex(windows.WindowsCaptureError, "outside"):
                windows.capture_screenshot(windows.TargetContext(hwnd=123), output,
                                           crop_rect=(2000, 2000, 2100, 2100))
            self.assertFalse(output.exists())
        self.assertEqual(native.dc_requests, 0)

    def test_minimized_target_is_rejected_before_accessing_desktop_pixels(self):
        native = FakeNativeApi()
        native.minimized = True
        with patch.object(windows, "_api", return_value=native):
            with self.assertRaisesRegex(windows.WindowsCaptureError, "Restore"):
                windows.capture_screenshot(windows.TargetContext(hwnd=123), "unused.png")
        self.assertEqual(native.dc_requests, 0)


class ExplorerMetadataTests(unittest.TestCase):
    def test_current_folder_fallback_keeps_its_explicit_source_and_note(self):
        with TemporaryDirectory() as folder:
            response = {"path": folder, "kind": "folder", "source": "explorer-current-folder", "notes": ["fallback"]}
            with patch.object(windows, "_explorer_query", return_value=response), \
                    patch.object(windows.Path, "exists", side_effect=AssertionError("No filesystem stat")), \
                    patch.object(windows.Path, "is_dir", side_effect=AssertionError("No filesystem stat")):
                target = windows._explorer_context(windows.TargetContext(hwnd=123), False)
            self.assertEqual(target.path, folder)
            self.assertEqual(target.kind, "folder")
            self.assertEqual(target.source, "explorer-current-folder")
            self.assertEqual(target.notes, ("fallback",))

    def test_slow_accessibility_provider_returns_window_metadata(self):
        original = windows.TargetContext(hwnd=123, title="Fixture")
        with patch.object(windows, "_explorer_query", side_effect=windows.ExplorerWorkerTimeout("helper")):
            target = windows._explorer_context(original, False)
        self.assertEqual(target.hwnd, original.hwnd)
        self.assertEqual(target.title, original.title)
        self.assertIsNone(target.path)
        self.assertIn("timed out", target.notes[-1])

    def test_enrichment_uses_original_point_and_never_reuses_old_path(self):
        original = windows.TargetContext(hwnd=123, point=(400, 500), explorer=True)
        responses = [
            {"path": r"C:\one", "kind": "folder", "source": "explorer-hit-test", "notes": []},
            {"path": r"C:\two.txt", "kind": "file", "source": "explorer-hit-test", "notes": []},
        ]
        with patch.object(windows, "_explorer_query", side_effect=responses) as query:
            first = windows.enrich_target(original)
            second = windows.enrich_target(original)
        self.assertEqual(first.path, r"C:\one")
        self.assertEqual(second.path, r"C:\two.txt")
        self.assertEqual(second.kind, "file")
        self.assertEqual(query.call_count, 2)
        query.assert_called_with(original, False)

    def test_non_explorer_enrichment_returns_immediately(self):
        original = windows.TargetContext(hwnd=123)
        with patch.object(windows, "_explorer_query") as query:
            self.assertIs(windows.enrich_target(original), original)
        query.assert_not_called()

    def test_switch_cancellation_preserves_idle_helper(self):
        from unittest.mock import Mock
        worker = Mock()
        with patch.object(windows, "_explorer_worker", worker):
            windows.cancel_capture_lookup()
        worker.cancel_active.assert_called_once_with()
        worker.cancel.assert_not_called()

    def test_unknown_type_is_rejected_without_guessing(self):
        original = windows.TargetContext(hwnd=123, explorer=True)
        response = {"path": r"C:\item", "source": "explorer-hit-test", "notes": []}
        with patch.object(windows, "_explorer_query", return_value=response):
            target = windows.enrich_target(original)
        self.assertIsNone(target.path)
        self.assertIn("unavailable", target.notes[-1])

    def test_fast_capture_returns_explorer_flags_without_loading_helper(self):
        class MetadataApi:
            SetThreadDpiAwarenessContext = None

            def IsWindow(self, hwnd): return True
            def GetAncestor(self, hwnd, mode): return hwnd
            def GetWindowTextLengthW(self, hwnd): return 7
            def GetWindowTextW(self, hwnd, buffer, size): buffer.value = "Fixture"
            def GetClassNameW(self, hwnd, buffer, size): buffer.value = "CabinetWClass"
            def OpenProcess(self, *args): return None

        with patch.object(windows, "_api", return_value=MetadataApi()), \
                patch.object(windows, "_process_id", return_value=999_999), \
                patch.object(windows, "_window_rect", return_value=(10, 20, 110, 120)), \
                patch.object(windows, "_explorer_query") as query:
            target = windows.capture_window(123, (40, 50), enrich=False)
        self.assertEqual(target.title, "Fixture")
        self.assertEqual(target.point, (40, 50))
        self.assertTrue(target.explorer)
        self.assertFalse(target.desktop)
        self.assertIsNone(target.path)
        query.assert_not_called()


@unittest.skipUnless(sys.platform == "win32", "PowerShell coordinate fixture requires Windows")
class UiaPointLookupTests(unittest.TestCase):
    def test_occluded_point_uses_only_unique_visible_target_rows_within_budgets(self):
        # Fake UIA nodes exercise the production tree algorithm without reading
        # real desktop elements. A foreign floating window covers FromPoint.
        fixture = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
function New-FixtureNode {
    param($Name, $Type = 'ControlType.Pane', [long]$Hwnd = 0,
          [int]$Left = 0, [int]$Top = 0, [int]$Right = 1000, [int]$Bottom = 1000)
    return [pscustomobject]@{
        Current = [pscustomobject]@{
            Name = $Name; ControlType = [pscustomobject]@{ ProgrammaticName = $Type };
            NativeWindowHandle = $Hwnd; IsOffscreen = $false;
            BoundingRectangle = [pscustomobject]@{ Left=$Left;Top=$Top;Right=$Right;Bottom=$Bottom }
        }; FirstChild = $null; NextSibling = $null; Parent = $null
    }
}
function Add-FixtureChild {
    param($Parent, $Child)
    $Child.Parent = $Parent
    if ($null -eq $Parent.FirstChild) { $Parent.FirstChild = $Child; return }
    $sibling = $Parent.FirstChild
    while ($null -ne $sibling.NextSibling) { $sibling = $sibling.NextSibling }
    $sibling.NextSibling = $Child
}
$walker = New-Object PSObject
$walker | Add-Member ScriptMethod GetFirstChild { param($node) return $node.FirstChild }
$walker | Add-Member ScriptMethod GetNextSibling { param($node) return $node.NextSibling }
$walker | Add-Member ScriptMethod GetParent { param($node) return $node.Parent }
while ($null -ne ($line = [Console]::ReadLine())) {
    $request = ConvertFrom-Json $line
    $case = [int]$request.hwnd
    $root = New-FixtureNode 'target window' 'ControlType.Window' $case
    $container = New-FixtureNode 'items view'
    $row = New-FixtureNode '目标文件夹' 'ControlType.ListItem' 0 20 20 70 70
    $selectedElsewhere = New-FixtureNode 'wrong selected item' 'ControlType.ListItem' 0 200 20 270 70
    Add-FixtureChild $root $container
    Add-FixtureChild $container $row
    Add-FixtureChild $container $selectedElsewhere
    $foreignRoot = New-FixtureNode 'floating pointer' 'ControlType.Window' 99999
    $foreignRow = New-FixtureNode 'wrong overlay row' 'ControlType.ListItem'
    Add-FixtureChild $foreignRoot $foreignRow
    $pointElement = $foreignRow
    $options = @{ Root=$root;Walker=$walker;TargetHwnd=$case;X=30;Y=30;MaxMilliseconds=2000 }
    switch ($case) {
        2 { Add-FixtureChild $container (New-FixtureNode 'overlap' 'ControlType.ListItem' 0 20 20 70 70) }
        3 { $options.MaxNodes = 2 }
        4 { $options.MaxDepth = 1 }
        5 { $row.Current.IsOffscreen = $true }
        6 { $root.Current.NativeWindowHandle = 55555 }
        7 { Add-FixtureChild $row (New-FixtureNode 'nested overlap' 'ControlType.ListItem' 0 20 20 70 70) }
        8 { $options.X = 70 }
        9 { $pointElement = $row }
        10 { $options.MaxMilliseconds = 0 }
    }
    $direct = Get-PointerAncestorHit -Element $pointElement -Walker $walker -TargetHwnd $case
    $hit = Find-PointerTargetRow @options
    $result = @{name=$hit.Name;ambiguous=$hit.Ambiguous;limited=$hit.Limited;visited=$hit.Visited;
                directBelongs=$direct.Belongs;directName=$direct.Name}
    @{id=$request.id;result=$result} | ConvertTo-Json -Depth 5 -Compress
}
'''
        with windows.ExplorerWorker(windows._UIA_POINT_LOOKUP_SCRIPT + fixture) as worker:
            unique = worker.query(1)
            self.assertEqual(unique["name"], "目标文件夹")
            self.assertFalse(unique["directBelongs"])
            self.assertEqual(unique["directName"], "wrong overlay row")
            for case in (2, 7):
                with self.subTest(ambiguous_case=case):
                    result = worker.query(case)
                    self.assertIsNone(result["name"])
                    self.assertTrue(result["ambiguous"])
            for case in (3, 4, 10):
                with self.subTest(budget_case=case):
                    result = worker.query(case)
                    self.assertIsNone(result["name"])
                    self.assertTrue(result["limited"])
            for case in (5, 6, 8):
                with self.subTest(outside_scope_case=case):
                    result = worker.query(case)
                    self.assertIsNone(result["name"])
                    self.assertFalse(result["ambiguous"])
            direct = worker.query(9)
            self.assertTrue(direct["directBelongs"])
            self.assertEqual(direct["directName"], "目标文件夹")


@unittest.skipUnless(sys.platform == "win32", "Owned native-window fixture requires Windows")
class NativeMetadataTests(unittest.TestCase):
    def test_metadata_from_owned_hidden_window_without_screen_capture(self):
        # The child owns an invisible STATIC window. It never receives
        # WS_VISIBLE, so the test does not show or control another application.
        helper = r'''
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.CreateWindowExW.restype = ctypes.c_void_p
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
user32.DestroyWindow.argtypes = [ctypes.c_void_p]
hwnd = user32.CreateWindowExW(0, "STATIC", "Codex Pointer hidden capture fixture",
    0, 10, 20, 200, 120, None, None, None, None)
if not hwnd:
    raise ctypes.WinError(ctypes.get_last_error())
try:
    ready = Path(sys.argv[1])
    pending = ready.with_suffix(".tmp")
    pending.write_text(str(hwnd), encoding="ascii")
    pending.replace(ready)
    sys.stdin.readline()
finally:
    user32.DestroyWindow(hwnd)
'''
        with TemporaryDirectory() as folder:
            ready = Path(folder) / "fixture-hwnd.txt"
            child = subprocess.Popen([sys.executable, "-u", "-c", helper, str(ready)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(ready.exists(), "Hidden native fixture did not become ready")
                hwnd = int(ready.read_text(encoding="ascii"))
                target = windows.capture_window(hwnd, point=(15, 25))
                self.assertEqual(target.title, "Codex Pointer hidden capture fixture")
                self.assertEqual(target.hwnd, hwnd)
                self.assertEqual(target.process_name.lower(), Path(sys.executable).name.lower())
                self.assertGreater(target.rect[2], target.rect[0])
                self.assertGreater(target.rect[3], target.rect[1])
                self.assertEqual(target.point, (15, 25))
                with self.assertRaises(windows.WindowsCaptureError):
                    windows.capture_window(0)
            finally:
                try:
                    child.communicate(input="\n", timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.communicate(timeout=5)
            self.assertEqual(child.returncode, 0)


if __name__ == "__main__":
    unittest.main()
