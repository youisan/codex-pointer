"""Read-only, explicit Windows target capture with no third-party dependencies.

Coordinates and rectangles are physical screen pixels. Captures never read the
clipboard, activate applications, or send input to the target. Screenshots use
the visible desktop region: another window in front of a target will appear in
its screenshot. Importing this module does not load Windows DLLs or capture data.
"""

from __future__ import annotations

from contextlib import contextmanager
import atexit
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, replace
import os
from pathlib import Path, PureWindowsPath
import struct
from threading import Lock, Thread
import zlib

from .explorer_worker import ExplorerWorker, ExplorerWorkerError, ExplorerWorkerTimeout, validate_windows_path
from .i18n import tr


class WindowsCaptureError(RuntimeError):
    """A requested native capture could not be completed."""


@dataclass(frozen=True)
class TargetContext:
    kind: str = "window"
    title: str = ""
    process_name: str = ""
    process_path: str = ""
    hwnd: int = 0
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)
    point: tuple[int, int] | None = None
    path: str | None = None
    source: str = "window"
    notes: tuple[str, ...] = ()
    explorer: bool = False
    desktop: bool = False


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD), ("width", wintypes.LONG),
        ("height", wintypes.LONG), ("planes", wintypes.WORD),
        ("bit_count", wintypes.WORD), ("compression", wintypes.DWORD),
        ("size_image", wintypes.DWORD), ("x_pixels_per_meter", wintypes.LONG),
        ("y_pixels_per_meter", wintypes.LONG), ("colors_used", wintypes.DWORD),
        ("colors_important", wintypes.DWORD),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("header", _BitmapInfoHeader), ("colors", wintypes.DWORD * 1)]


class _Win32:
    def __init__(self) -> None:
        if os.name != "nt":
            raise WindowsCaptureError("Window capture is available only on Windows.")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

        def bind(dll, name, result, args):
            function = getattr(dll, name)
            function.restype = result
            function.argtypes = args
            setattr(self, name, function)

        handle = ctypes.c_void_p
        uint = wintypes.UINT
        integer = ctypes.c_int
        boolean = wintypes.BOOL
        bind(self.user32, "GetCursorPos", boolean, [ctypes.POINTER(wintypes.POINT)])
        bind(self.user32, "GetForegroundWindow", handle, [])
        bind(self.user32, "WindowFromPoint", handle, [wintypes.POINT])
        bind(self.user32, "GetAncestor", handle, [handle, uint])
        bind(self.user32, "GetTopWindow", handle, [handle])
        bind(self.user32, "GetWindow", handle, [handle, uint])
        bind(self.user32, "IsWindow", boolean, [handle])
        bind(self.user32, "IsWindowVisible", boolean, [handle])
        bind(self.user32, "IsIconic", boolean, [handle])
        bind(self.user32, "GetWindowRect", boolean, [handle, ctypes.POINTER(wintypes.RECT)])
        bind(self.user32, "GetWindowThreadProcessId", wintypes.DWORD,
             [handle, ctypes.POINTER(wintypes.DWORD)])
        bind(self.user32, "GetWindowTextLengthW", integer, [handle])
        bind(self.user32, "GetWindowTextW", integer, [handle, wintypes.LPWSTR, integer])
        bind(self.user32, "GetClassNameW", integer, [handle, wintypes.LPWSTR, integer])
        bind(self.user32, "GetSystemMetrics", integer, [integer])
        bind(self.user32, "GetDC", handle, [handle])
        bind(self.user32, "ReleaseDC", integer, [handle, handle])
        bind(self.kernel32, "OpenProcess", handle,
             [wintypes.DWORD, boolean, wintypes.DWORD])
        bind(self.kernel32, "QueryFullProcessImageNameW", boolean,
             [handle, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)])
        bind(self.kernel32, "CloseHandle", boolean, [handle])
        bind(self.dwmapi, "DwmGetWindowAttribute", ctypes.c_long,
             [handle, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD])
        bind(self.gdi32, "CreateCompatibleDC", handle, [handle])
        bind(self.gdi32, "CreateCompatibleBitmap", handle, [handle, integer, integer])
        bind(self.gdi32, "SelectObject", handle, [handle, handle])
        bind(self.gdi32, "DeleteObject", boolean, [handle])
        bind(self.gdi32, "DeleteDC", boolean, [handle])
        bind(self.gdi32, "BitBlt", boolean,
             [handle, integer, integer, integer, integer, handle, integer, integer, wintypes.DWORD])
        bind(self.gdi32, "GetDIBits", integer,
             [handle, handle, uint, uint, ctypes.c_void_p, ctypes.POINTER(_BitmapInfo), uint])
        self.SetThreadDpiAwarenessContext = None
        if hasattr(self.user32, "SetThreadDpiAwarenessContext"):
            bind(self.user32, "SetThreadDpiAwarenessContext", handle, [handle])


_native: _Win32 | None = None


def _api() -> _Win32:
    global _native
    if _native is None:
        _native = _Win32()
    return _native


def _failure(action: str) -> WindowsCaptureError:
    code = ctypes.get_last_error()
    detail = ctypes.FormatError(code).strip() if code else "Windows did not provide an error code."
    return WindowsCaptureError(f"{action}: {detail}" + (f" (Win32 {code})" if code else ""))


@contextmanager
def _physical_pixels(api: _Win32):
    # Thread-local awareness avoids changing a Tk application's DPI mode after
    # its windows have already been created. Restore the caller's mode exactly.
    previous = None
    if api.SetThreadDpiAwarenessContext:
        previous = api.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    try:
        yield
    finally:
        if previous:
            api.SetThreadDpiAwarenessContext(previous)


def get_cursor_position() -> tuple[int, int]:
    api = _api()
    with _physical_pixels(api):
        point = wintypes.POINT()
        if not api.GetCursorPos(ctypes.byref(point)):
            raise _failure("Could not read the cursor position")
        return point.x, point.y


def get_foreground_window() -> int:
    """Return the current foreground HWND, or zero if Windows has none."""
    return int(_api().GetForegroundWindow() or 0)


def _process_id(api: _Win32, hwnd: int) -> int:
    pid = wintypes.DWORD()
    api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _window_rect(api: _Win32, hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    # DWM's frame bounds omit invisible resize borders and use physical pixels.
    result = api.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
    if result != 0 or rect.right <= rect.left or rect.bottom <= rect.top:
        if not api.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise _failure("Could not read the target window rectangle")
    return rect.left, rect.top, rect.right, rect.bottom


def _is_cloaked(api: _Win32, hwnd: int) -> bool:
    cloaked = wintypes.DWORD()
    return (api.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0
            and bool(cloaked.value))


def _underlying_window(api: _Win32, x: int, y: int) -> int:
    hit = int(api.WindowFromPoint(wintypes.POINT(x, y)) or 0)
    root = int(api.GetAncestor(hit, 2) or hit) if hit else 0
    if root and _process_id(api, root) != os.getpid():
        return root

    # When the floating button is still present, walk top-level windows in Z
    # order and exclude all windows owned by this process. The UI should hide
    # its overlay before requesting capture so UIA and screenshots agree too.
    hwnd = int(api.GetTopWindow(None) or 0)
    seen: set[int] = set()
    while hwnd and hwnd not in seen:
        seen.add(hwnd)
        if (api.IsWindowVisible(hwnd) and not api.IsIconic(hwnd)
                and _process_id(api, hwnd) != os.getpid() and not _is_cloaked(api, hwnd)):
            try:
                left, top, right, bottom = _window_rect(api, hwnd)
                if left <= x < right and top <= y < bottom:
                    return hwnd
            except WindowsCaptureError:
                pass  # A window can disappear while walking the Z order.
        hwnd = int(api.GetWindow(hwnd, 2) or 0)  # GW_HWNDNEXT
    raise WindowsCaptureError("No application window was found at this screen position.")


def capture_target(x: int, y: int, *, enrich: bool = True) -> TargetContext:
    """Capture metadata for the underlying application at a physical point."""
    api = _api()
    with _physical_pixels(api):
        hwnd = _underlying_window(api, int(x), int(y))
        return capture_window(hwnd, (int(x), int(y)), enrich=enrich)


def capture_window(hwnd: int, point: tuple[int, int] | None = None, *, enrich: bool = True) -> TargetContext:
    """Read one window's metadata and, when possible, its Explorer path.

    With no point supplied, Explorer reports its current folder only. A selected
    item is never substituted for the item beneath the supplied point.
    """
    api = _api()
    hwnd = int(hwnd)
    if not hwnd or not api.IsWindow(hwnd):
        raise WindowsCaptureError("The target window no longer exists.")
    if _process_id(api, hwnd) == os.getpid():
        raise WindowsCaptureError("The floating button cannot be its own target.")
    with _physical_pixels(api):
        root = int(api.GetAncestor(hwnd, 2) or hwnd)
        title_buffer = ctypes.create_unicode_buffer(max(1, min(32768, api.GetWindowTextLengthW(root) + 1)))
        api.GetWindowTextW(root, title_buffer, len(title_buffer))
        class_buffer = ctypes.create_unicode_buffer(256)
        api.GetClassNameW(root, class_buffer, len(class_buffer))
        notes: list[str] = []
        process_path = ""
        pid = _process_id(api, root)
        process = api.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if process:
            try:
                image_buffer = ctypes.create_unicode_buffer(32768)
                length = wintypes.DWORD(len(image_buffer))
                if api.QueryFullProcessImageNameW(process, 0, image_buffer, ctypes.byref(length)):
                    process_path = image_buffer.value
                else:
                    notes.append("The target process executable path is unavailable.")
            finally:
                api.CloseHandle(process)
        else:
            notes.append("Windows denied access to the target process executable path.")
        desktop = class_buffer.value in ("Progman", "WorkerW")
        explorer = (Path(process_path).name.lower() == "explorer.exe" or
                    class_buffer.value in ("CabinetWClass", "ExploreWClass") or desktop)
        context = TargetContext(
            title=title_buffer.value, process_name=Path(process_path).name if process_path else "",
            process_path=process_path, hwnd=root, rect=_window_rect(api, root),
            point=point, notes=tuple(notes), explorer=explorer, desktop=desktop,
        )
        if explorer and enrich:
            context = _explorer_context(context, desktop)
        return context


def enrich_target(context: TargetContext) -> TargetContext:
    """Resolve a staged Explorer target off the UI thread, without screenshots.

    This always queries the original point and HWND anew. It does not reuse a
    previous path, selected item or another window's accessibility information.
    """
    if not context.explorer:
        return context
    return _explorer_context(context, context.desktop)


_explorer_worker: ExplorerWorker | None = None
_explorer_worker_lock = Lock()


def _explorer_query(context: TargetContext, desktop: bool) -> dict:
    global _explorer_worker
    with _explorer_worker_lock:
        if _explorer_worker is None:
            _explorer_worker = ExplorerWorker(_EXPLORER_WORKER_SCRIPT)
        worker = _explorer_worker
    return worker.query(context.hwnd, context.point, desktop=desktop)


def target_from_path(path: str) -> TargetContext:
    """Validate one explicit dropped path in the bounded, owned helper.

    The calling Qt thread must dispatch this function to its metadata worker.
    Neither file contents nor application windows are read by this operation.
    """
    global _explorer_worker
    try:
        with _explorer_worker_lock:
            if _explorer_worker is None:
                _explorer_worker = ExplorerWorker(_EXPLORER_WORKER_SCRIPT)
            worker = _explorer_worker
        data = worker.query_path(path)
        if not isinstance(data, dict):
            raise ValueError("Invalid path metadata.")
        if data.get("error"):
            raise WindowsCaptureError(tr("未能选择这个文件或文件夹：它可能已移动、无法访问，或不是普通文件。"))
        resolved, kind = data.get("path"), data.get("kind")
        if (not isinstance(resolved, str) or not resolved or kind not in ("folder", "file")
                or data.get("source") != "file-drop"):
            raise ValueError("Invalid path metadata.")
        validate_windows_path(resolved)
        return TargetContext(kind=kind, title=PureWindowsPath(resolved).name or resolved,
                             path=resolved, source="file-drop")
    except ExplorerWorkerTimeout as error:
        raise WindowsCaptureError(tr("文件或文件夹检查超时，共享目录可能暂时无法连接。请稍后重试。")) from error
    except (ExplorerWorkerError, OSError) as error:
        raise WindowsCaptureError(tr("未能检查这个文件或文件夹，请重新拖入或稍后重试。")) from error
    except (TypeError, ValueError) as error:
        raise WindowsCaptureError(tr("这个文件地址无效，请拖入本地文件或文件夹。")) from error


def close_capture_helpers() -> None:
    """Stop the owned helper without waiting on the caller's UI thread."""
    global _explorer_worker
    with _explorer_worker_lock:
        worker, _explorer_worker = _explorer_worker, None
    if worker is not None:
        worker.cancel()
        Thread(target=worker.close, name="Explorer helper cleanup", daemon=True).start()


def cancel_capture_lookup() -> None:
    """Cancel a stale lookup when the user explicitly switches targets."""
    with _explorer_worker_lock:
        worker = _explorer_worker
    if worker is not None:
        worker.cancel_active()


atexit.register(close_capture_helpers)


def _explorer_context(context: TargetContext, desktop: bool) -> TargetContext:
    try:
        data = _explorer_query(context, desktop)
        if not isinstance(data, dict):
            raise ValueError("Explorer accessibility helper returned invalid metadata.")
        raw_notes = data.get("notes", [])
        notes = tuple(note for note in raw_notes if isinstance(note, str)) if isinstance(raw_notes, list) else ()
        path = data.get("path")
        if not isinstance(path, str) or not path:
            return replace(context, notes=context.notes + notes)
        kind = data.get("kind")
        if kind not in ("folder", "file"):
            raise ValueError("Explorer accessibility helper returned an unknown path type.")
        source = data.get("source")
        if source not in ("explorer-hit-test", "explorer-current-folder", "desktop-hit-test"):
            raise ValueError("Explorer accessibility helper returned an unknown source.")
        return replace(context, kind=kind, path=path, source=source, notes=context.notes + notes)
    except ExplorerWorkerTimeout:
        note = "Explorer path lookup timed out; window metadata is still available."
    except (ExplorerWorkerError, OSError, ValueError):
        note = "Explorer path lookup was unavailable; window metadata is still available."
    return replace(context, notes=context.notes + (note,))


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _encode_png(width: int, height: int, bgr: bytes, stride: int) -> bytes:
    """Encode a top-down, padded, 24-bit BGR DIB as an RGB PNG."""
    compressor = zlib.compressobj(6)
    chunks: list[bytes] = []
    for row_index in range(height):
        row = bgr[row_index * stride:row_index * stride + width * 3]
        rgb = bytearray(width * 3 + 1)  # PNG filter type 0, followed by RGB.
        rgb[1::3], rgb[2::3], rgb[3::3] = row[2::3], row[1::3], row[0::3]
        chunks.append(compressor.compress(rgb))
    chunks.append(compressor.flush())
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header)
            + _png_chunk(b"IDAT", b"".join(chunks)) + _png_chunk(b"IEND", b""))


def capture_screenshot(
    context: TargetContext,
    output_path: str | Path,
    *,
    crop_rect: tuple[int, int, int, int] | None = None,
) -> Path:
    """Save visible pixels inside the target rectangle as a PNG, on request.

    By default, the window's current rectangle is read again. ``crop_rect``
    explicitly requests a physical screen region for nearby context instead.
    The rectangle is clipped to the virtual desktop. Minimized, closed, and
    entirely off-screen windows are rejected. This does not activate the target
    or bypass Windows display-capture protection.
    """
    api = _api()
    if not context.hwnd or not api.IsWindow(context.hwnd):
        raise WindowsCaptureError("The target window no longer exists.")
    if api.IsIconic(context.hwnd):
        raise WindowsCaptureError("Restore the target window before taking its screenshot.")
    with _physical_pixels(api):
        screen_left, screen_top = api.GetSystemMetrics(76), api.GetSystemMetrics(77)
        screen_right = screen_left + api.GetSystemMetrics(78)
        screen_bottom = screen_top + api.GetSystemMetrics(79)
        if crop_rect is None:
            left, top, right, bottom = _window_rect(api, context.hwnd)
        else:
            if len(crop_rect) != 4:
                raise WindowsCaptureError("The requested screenshot crop must have four coordinates.")
            left, top, right, bottom = (int(value) for value in crop_rect)
        left, top = max(left, screen_left), max(top, screen_top)
        right, bottom = min(right, screen_right), min(bottom, screen_bottom)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            raise WindowsCaptureError("The target window is outside the visible desktop.")
        if width * height > 50_000_000:
            raise WindowsCaptureError("The target screenshot is too large; resize the target window first.")
        screen_dc = api.GetDC(None)
        if not screen_dc:
            raise _failure("Could not access visible desktop pixels")
        memory_dc = bitmap = original = None
        selected = False
        try:
            memory_dc = api.CreateCompatibleDC(screen_dc)
            if not memory_dc:
                raise _failure("Could not create the screenshot device context")
            bitmap = api.CreateCompatibleBitmap(screen_dc, width, height)
            if not bitmap:
                raise _failure("Could not allocate the screenshot bitmap")
            original = api.SelectObject(memory_dc, bitmap)
            if not original or original == ctypes.c_void_p(-1).value:
                raise _failure("Could not prepare the screenshot bitmap")
            selected = True
            if not api.BitBlt(memory_dc, 0, 0, width, height, screen_dc, left, top, 0x40CC0020):
                raise _failure("Could not capture the target's visible pixels")
            api.SelectObject(memory_dc, original)
            selected = False  # GetDIBits requires an unselected bitmap.
            stride = (width * 3 + 3) & ~3
            buffer = ctypes.create_string_buffer(stride * height)
            info = _BitmapInfo()
            info.header.size = ctypes.sizeof(_BitmapInfoHeader)
            info.header.width, info.header.height = width, -height
            info.header.planes, info.header.bit_count = 1, 24
            if api.GetDIBits(screen_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0) != height:
                raise _failure("Could not read the screenshot bitmap")
            png = _encode_png(width, height, buffer.raw, stride)
        finally:
            if selected and memory_dc and original:
                api.SelectObject(memory_dc, original)
            if bitmap:
                api.DeleteObject(bitmap)
            if memory_dc:
                api.DeleteDC(memory_dc)
            api.ReleaseDC(None, screen_dc)
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(png)
    return output


_UIA_POINT_LOOKUP_SCRIPT = r"""
function Get-PointerAncestorHit {
    param($Element, $Walker, [long]$TargetHwnd)
    $name = $null; $type = $null; $belongs = $false
    $node = $Element
    for ($depth = 0; $null -ne $node -and $depth -lt 64; $depth++) {
        $current = $node.Current
        $control = $current.ControlType.ProgrammaticName
        if ($null -eq $name -and $control -in @('ControlType.ListItem','ControlType.TreeItem')) {
            $name = $current.Name; $type = $control
        }
        if ([long]$current.NativeWindowHandle -eq $TargetHwnd) { $belongs = $true; break }
        $node = $Walker.GetParent($node)
    }
    return @{ Name = $name; Type = $type; Belongs = $belongs }
}

function Find-PointerTargetRow {
    param($Root, $Walker, [long]$TargetHwnd, [int]$X, [int]$Y,
          [int]$MaxNodes = 512, [int]$MaxDepth = 24, [int]$MaxMilliseconds = 250)
    $result = @{ Name = $null; Ambiguous = $false; Limited = $false; Visited = 0 }
    if ($null -eq $Root -or [long]$Root.Current.NativeWindowHandle -ne $TargetHwnd) { return $result }
    $pending = New-Object 'System.Collections.Generic.Queue[object]'
    $pending.Enqueue(@{ Node = $Root; Depth = 0 })
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $names = New-Object 'System.Collections.Generic.List[string]'
    try {
        while ($pending.Count -gt 0) {
            $parent = $pending.Dequeue()
            if ($parent.Depth -ge $MaxDepth) { $result.Limited = $true; break }
            $child = $Walker.GetFirstChild($parent.Node)
            while ($null -ne $child) {
                if ($result.Visited -ge $MaxNodes -or $clock.ElapsedMilliseconds -ge $MaxMilliseconds) {
                    $result.Limited = $true; break
                }
                $result.Visited++
                $current = $child.Current
                $bounds = $current.BoundingRectangle
                # Only the target's visible coordinate branch is descended.
                # Bounding rectangles use physical pixels, as does the picker.
                if (-not $current.IsOffscreen -and $bounds.Right -gt $bounds.Left -and
                    $bounds.Bottom -gt $bounds.Top -and $X -ge $bounds.Left -and
                    $X -lt $bounds.Right -and $Y -ge $bounds.Top -and $Y -lt $bounds.Bottom) {
                    if ($current.ControlType.ProgrammaticName -eq 'ControlType.ListItem') {
                        $names.Add([string]$current.Name)
                        if ($names.Count -gt 1) { $result.Ambiguous = $true; break }
                    }
                    $pending.Enqueue(@{ Node = $child; Depth = $parent.Depth + 1 })
                }
                $child = $Walker.GetNextSibling($child)
            }
            if ($result.Ambiguous -or $result.Limited) { break }
        }
    } catch { $result.Limited = $true }
    if (-not $result.Ambiguous -and -not $result.Limited -and $names.Count -eq 1) {
        $result.Name = $names[0]
    }
    return $result
}
"""


_EXPLORER_SCRIPT = r"""
param([long]$TargetHwnd, [int]$X = 0, [int]$Y = 0,
      [switch]$HasPoint, [switch]$Desktop)
$answer = @{ path = $null; source = $null; kind = $null; notes = @() }
try {
    $shell = $script:ExplorerShell
    $folder = $null
    $currentPath = $null
    if ($Desktop) {
        $folder = $shell.NameSpace(0)
    } else {
        $views = @()
        foreach ($window in $shell.Windows()) {
            try {
                if ([long]$window.HWND -eq $TargetHwnd) {
                    $views += [pscustomobject]@{
                        Folder = $window.Document.Folder
                        Identity = [string]$window.Document.Folder.Self.Path
                    }
                }
            } catch { }
        }
        $identities = @($views | Select-Object -ExpandProperty Identity -Unique)
        if ($identities.Count -eq 1) {
            $folder = $views[0].Folder
            $candidate = [string]$folder.Self.Path
            if ($folder.Self.IsFileSystem -and $folder.Self.IsFolder) {
                $currentPath = $candidate
            }
        } elseif ($identities.Count -gt 1) {
            $answer.notes += 'Multiple Explorer tab paths were exposed; the active path could not be verified.'
        }
    }

    if ($HasPoint -and $null -ne $folder) {
        $walker = [System.Windows.Automation.TreeWalker]::RawViewWalker
        $hit = @{ Name = $null; Type = $null; Belongs = $false }
        try {
            $element = [System.Windows.Automation.AutomationElement]::FromPoint((New-Object System.Windows.Point($X, $Y)))
            $hit = Get-PointerAncestorHit -Element $element -Walker $walker -TargetHwnd $TargetHwnd
        } catch { }
        $itemName = $hit.Name
        $itemType = $hit.Type
        $belongsToWindow = $hit.Belongs
        if (-not $belongsToWindow) {
            # The floating button can cover this point. Query only the chosen
            # HWND's coordinate branch rather than hiding the picker or using
            # an unrelated globally hit-tested/selected row.
            $targetRoot = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$TargetHwnd)
            $row = Find-PointerTargetRow -Root $targetRoot -Walker $walker -TargetHwnd $TargetHwnd -X $X -Y $Y
            if ($row.Name) {
                $itemName = $row.Name; $itemType = 'ControlType.ListItem'; $belongsToWindow = $true
            } elseif ($row.Ambiguous) {
                $answer.notes += 'Multiple target rows covered this point; the exact item could not be verified.'
            } elseif ($row.Limited) {
                $answer.notes += 'The bounded target-tree lookup could not verify the exact item beneath the pointer.'
            }
        }
        if ($belongsToWindow -and $itemName -and $itemType -eq 'ControlType.ListItem') {
            $matches = @()
            foreach ($item in $folder.Items()) {
                # Resolve only an exact display-name match from the actual
                # hit-tested row. Never infer the target from SelectedItems.
                if ([string]$item.Name -eq $itemName) {
                    $itemPath = [string]$item.Path
                    if ($item.IsFileSystem) {
                        $matches += [pscustomobject]@{ Path = $itemPath; IsFolder = [bool]$item.IsFolder }
                    }
                }
                # Once ambiguous, additional enumeration cannot make the
                # match safe. Avoid walking the remainder of a large folder.
                if ($matches.Count -gt 1) { break }
            }
            if ($matches.Count -eq 1) {
                $answer.path = $matches[0].Path
                $answer.kind = if ($matches[0].IsFolder) { 'folder' } else { 'file' }
                $answer.source = if ($Desktop) { 'desktop-hit-test' } else { 'explorer-hit-test' }
            } elseif ($matches.Count -gt 1) {
                $answer.notes += 'The item beneath the pointer had an ambiguous display name.'
            }
        }
    }
    if (-not $answer.path -and $currentPath) {
        $answer.path = $currentPath
        $answer.kind = 'folder'
        $answer.source = 'explorer-current-folder'
        if ($HasPoint) {
            $answer.notes += 'The exact item beneath the pointer could not be resolved; this is the Explorer current folder.'
        }
    }
    if (-not $answer.path -and $answer.notes.Count -eq 0) {
        $answer.notes += 'No verified filesystem path was available for this Explorer target.'
    }
} catch {
    $answer.notes += 'Explorer accessibility lookup was unavailable.'
    if ($currentPath) {
        $answer.path = $currentPath
        $answer.kind = 'folder'
        $answer.source = 'explorer-current-folder'
        $answer.notes += 'The current folder is a fallback; the item beneath the pointer was not verified.'
    }
}
return $answer
"""


_EXPLORER_WORKER_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$script:ExplorerInitialized = $false
function Initialize-PointerExplorer {
    if ($script:ExplorerInitialized) { return }
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    Add-Type -AssemblyName WindowsBase
    $script:ExplorerShell = New-Object -ComObject Shell.Application
    $script:ExplorerInitialized = $true
}
""" + _UIA_POINT_LOOKUP_SCRIPT + r"""
function Get-ExplorerTarget {
""" + _EXPLORER_SCRIPT + r"""
}
while ($null -ne ($line = [Console]::ReadLine())) {
    $request = $null
    try {
        $request = ConvertFrom-Json -InputObject $line
        if ($request.PSObject.Properties.Name -contains 'path') {
            $item = Get-Item -LiteralPath ([string]$request.path) -Force -ErrorAction Stop
            if ($item.PSProvider.Name -ne 'FileSystem') { throw 'Unsupported provider.' }
            $kind = if ($item -is [System.IO.DirectoryInfo]) { 'folder' }
                    elseif ($item -is [System.IO.FileInfo]) { 'file' }
                    else { throw 'Unsupported object.' }
            $result = @{path=[string]$item.FullName;kind=$kind;source='file-drop';notes=@()}
        } else {
            Initialize-PointerExplorer
            $arguments = @{ TargetHwnd = [long]$request.hwnd; Desktop = [bool]$request.desktop }
            if ($null -ne $request.point) {
                $arguments.HasPoint = $true
                $arguments.X = [int]$request.point[0]
                $arguments.Y = [int]$request.point[1]
            }
            $result = Get-ExplorerTarget @arguments
        }
        @{ id = $request.id; result = $result } | ConvertTo-Json -Depth 6 -Compress
    } catch {
        $result = if ($null -ne $request -and $request.PSObject.Properties.Name -contains 'path') {
            @{path=$null;kind=$null;source='file-drop';error='path-unavailable';notes=@()}
        } else {
            @{path=$null;source=$null;kind=$null;notes=@('Explorer accessibility lookup was unavailable.')}
        }
        @{id=$request.id;result=$result} | ConvertTo-Json -Depth 6 -Compress
    }
}
"""
