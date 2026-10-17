"""One bounded, reusable helper for Explorer metadata, with no Qt dependency.

The helper accepts data-only JSON requests. A stalled accessibility provider is
contained in this process; a timeout closes only the helper we created. Results
are never cached, so a changed folder, tab or pointer position is looked up anew.
"""
from __future__ import annotations

import base64
import json
import ntpath
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import re
from threading import Lock, Thread
import time
from typing import Callable


class ExplorerWorkerError(RuntimeError):
    """The helper could not return trustworthy metadata."""


class ExplorerWorkerTimeout(ExplorerWorkerError):
    """A helper request exceeded its wall-clock budget."""


def validate_windows_path(path: str) -> str:
    """Validate only path syntax, without resolving or opening any object."""
    if (not isinstance(path, str) or not path or len(path) > 32767
            or any(ord(character) < 32 for character in path)
            or any(character in path for character in '<>"|?*')):
        raise ValueError("Expected an absolute Windows file or folder path.")
    candidate = path.replace("/", "\\")
    if candidate.startswith(("\\\\?\\", "\\\\.\\")):
        raise ValueError("Windows device paths are not supported.")
    drive, tail = ntpath.splitdrive(candidate)
    if drive.startswith("\\\\"):
        parts = drive[2:].split("\\")
        valid = (len(parts) == 2 and all(part and part not in (".", "..") for part in parts)
                 and ":" not in drive and (not tail or tail.startswith("\\")))
    else:
        valid = bool(re.fullmatch(r"[A-Za-z]:", drive) and tail.startswith("\\"))
    if not valid or ":" in tail:
        raise ValueError("Expected an absolute Windows drive or UNC path.")
    return path


class ExplorerWorker:
    """Serialize requests to a single lazy helper and restart after failure."""

    def __init__(self, script: str, *, timeout: float = 3.0,
                 command_factory: Callable[[], list[str]] | None = None) -> None:
        self._script = script
        self.timeout = timeout
        self._command_factory = command_factory
        self._lock = Lock()
        self._state_lock = Lock()
        self._cancel_revision = 0
        self._active = False
        self._process: subprocess.Popen | None = None
        self._responses: Queue | None = None
        self._reader: Thread | None = None
        self._next_id = 0

    def _command(self) -> list[str]:
        if self._command_factory is not None:
            return self._command_factory()
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        powershell = Path(system_root) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        encoded = base64.b64encode(self._script.encode("utf-16-le")).decode("ascii")
        return [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Sta",
                "-EncodedCommand", encoded]

    @staticmethod
    def _read_responses(process: subprocess.Popen, responses: Queue) -> None:
        try:
            while True:
                line = process.stdout.readline(65_537)
                if not line:
                    responses.put(ExplorerWorkerError("Explorer helper closed its output."))
                    return
                if len(line) > 65_536 or not line.endswith("\n"):
                    responses.put(ExplorerWorkerError("Explorer helper returned oversized metadata."))
                    return
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("Expected an object.")
                responses.put(value)
        except (OSError, UnicodeError, ValueError) as error:
            responses.put(ExplorerWorkerError(f"Explorer helper returned invalid metadata: {error}"))

    def _start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        self._stop()
        try:
            process = subprocess.Popen(
                self._command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="strict",
                bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            raise ExplorerWorkerError("Explorer helper could not start.") from error
        responses: Queue = Queue()
        with self._state_lock:
            self._process, self._responses = process, responses
        self._reader = Thread(target=self._read_responses, args=(process, responses),
                              name="Explorer metadata output", daemon=True)
        self._reader.start()

    def query(self, hwnd: int, point: tuple[int, int] | None = None,
              *, desktop: bool = False) -> dict:
        if isinstance(hwnd, bool) or not isinstance(hwnd, int) or not 0 < hwnd < 2 ** 63:
            raise ValueError("Explorer target must have a valid HWND.")
        if point is not None and (len(point) != 2 or any(
                isinstance(value, bool) or not isinstance(value, int) or not -(2 ** 31) <= value < 2 ** 31
                for value in point)):
            raise ValueError("Explorer point must contain two physical pixel coordinates.")
        return self._request_payload({"hwnd": hwnd, "desktop": bool(desktop),
                                      "point": list(point) if point is not None else None})

    def query_path(self, path: str) -> dict:
        """Inspect only the selected path, within the same cancellation budget."""
        return self._request_payload({"path": validate_windows_path(path)})

    @staticmethod
    def _write_request(process, responses, request) -> None:
        # A long UNC path can fill a pipe while a stalled helper is not reading.
        # Bound the caller's wait even in that case; killing this owned helper
        # on timeout also releases the writer. No shell interpolation is used.
        try:
            process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (OSError, UnicodeError, ValueError) as error:
            responses.put(ExplorerWorkerError(f"Explorer helper could not receive metadata: {error}"))

    def _request_payload(self, payload: dict) -> dict:
        deadline = time.monotonic() + self.timeout
        if not self._lock.acquire(timeout=self.timeout):
            raise ExplorerWorkerTimeout("Explorer helper remained busy beyond the lookup budget.")
        try:
            with self._state_lock:
                self._active = True
                revision = self._cancel_revision
            self._start()
            with self._state_lock:
                cancelled = revision != self._cancel_revision
            if cancelled:
                self._stop()
                raise ExplorerWorkerError("Explorer lookup was cancelled.")
            self._next_id += 1
            request_id = self._next_id
            request = {"id": request_id, **payload}
            try:
                process, responses = self._process, self._responses
                Thread(target=self._write_request, args=(process, responses, request),
                       name="Explorer metadata input", daemon=True).start()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Empty
                response = responses.get(timeout=remaining)
                if isinstance(response, Exception):
                    raise response
                if response.get("id") != request_id:
                    raise ExplorerWorkerError("Explorer helper returned a mismatched request.")
                data = response.get("result")
                if not isinstance(data, dict):
                    raise ExplorerWorkerError("Explorer helper returned invalid metadata.")
                with self._state_lock:
                    if revision != self._cancel_revision:
                        raise ExplorerWorkerError("Explorer lookup was cancelled.")
                return data
            except Empty as error:
                self._stop()
                raise ExplorerWorkerTimeout("Explorer path lookup timed out.") from error
            except (OSError, UnicodeError, ExplorerWorkerError) as error:
                self._stop()
                if isinstance(error, ExplorerWorkerError):
                    raise
                raise ExplorerWorkerError("Explorer helper communication failed.") from error
        finally:
            with self._state_lock:
                self._active = False
            self._lock.release()

    def _stop(self) -> None:
        with self._state_lock:
            process, self._process = self._process, None
        reader, self._reader = self._reader, None
        self._responses = None
        if process is None:
            return
        # Never enumerate or terminate any process other than this Popen child.
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass  # It may have exited between poll() and kill().
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
        if reader is not None:
            reader.join(timeout=0.5)
        for pipe in (process.stdin, process.stdout):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass

    def _cancel(self, *, active_only: bool) -> bool:
        with self._state_lock:
            if active_only and not self._active:
                return False
            self._cancel_revision += 1
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        return True

    def cancel_active(self) -> bool:
        """Interrupt a stale request while preserving an idle, warmed helper."""
        return self._cancel(active_only=True)

    def cancel(self) -> None:
        """Stop the owned process, including an idle helper, without waiting."""
        self._cancel(active_only=False)

    def close(self) -> None:
        self.cancel()
        with self._lock:
            self._stop()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
