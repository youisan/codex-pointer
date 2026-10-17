"""Small, bounded Codex CLI/app-server adapter; never reads account secrets.

The shared app-server is experimental. Starting a turn here does not install
Desktop host tools or guarantee that the Desktop opens the resulting chat.
The explicit desktop draft method only fills the composer and never sends it.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlencode, quote

from . import __version__


class BridgeError(RuntimeError):
    """Codex did not confirm the requested operation."""


class BridgeUnavailable(BridgeError):
    """The native CLI, desktop handler, or shared app-server is unavailable."""


class BridgeTimeout(BridgeError):
    """A bounded operation timed out; a dispatch might have reached Codex."""


@dataclass(frozen=True)
class ThreadSummary:
    id: str
    title: str
    cwd: str
    preview: str


@dataclass(frozen=True)
class DispatchResult:
    thread_id: str
    backend: str
    status: str


def _native_executable(value: str | os.PathLike[str]) -> str:
    candidate = Path(value).expanduser()
    if candidate.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        raise BridgeUnavailable("请指定原生 codex.exe，不能使用 .cmd/.bat/PowerShell 包装脚本。")
    if not candidate.is_file():
        raise BridgeUnavailable(f"找不到 Codex 可执行文件：{candidate}")
    if os.name == "nt" and candidate.suffix.lower() != ".exe":
        raise BridgeUnavailable("Windows 上需要原生 codex.exe。")
    return str(candidate.resolve())


def discover_codex(executable: str | os.PathLike[str] | None = None) -> str:
    """Find a native binary, avoiding shell wrappers and shell interpolation."""
    if executable is not None:
        return _native_executable(executable)
    configured = os.environ.get("CODEX_POINTER_CODEX")
    if configured:
        return _native_executable(configured)
    candidates: list[str | Path] = []
    for name in ("codex.exe", "codex"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        desktop_bins = Path(local) / "OpenAI" / "Codex" / "bin"
        try:
            candidates.extend(sorted(desktop_bins.glob("*/codex.exe"),
                                     key=lambda path: path.stat().st_mtime, reverse=True))
        except OSError:
            pass
    for candidate in candidates:
        try:
            return _native_executable(candidate)
        except BridgeUnavailable:
            continue
    raise BridgeUnavailable("未找到原生 Codex CLI。请安装 Codex，或设置 CODEX_POINTER_CODEX 为 codex.exe 的完整路径。")


def _process_options() -> dict[str, Any]:
    options: dict[str, Any] = {"shell": False}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    return options


class _RpcConnection:
    """One initialized newline-JSON connection, with bounded reads and cleanup."""

    _MAX_LINE = 8 * 1024 * 1024

    def __init__(self, argv: list[str], timeout: float):
        self.argv = argv
        self.timeout = timeout
        self.process: subprocess.Popen[str] | None = None
        self.messages: queue.Queue[Any] = queue.Queue(maxsize=256)
        self.closed = threading.Event()
        self.reader: threading.Thread | None = None
        self.next_id = 1

    def __enter__(self) -> "_RpcConnection":
        try:
            self.process = subprocess.Popen(
                self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, encoding="utf-8", errors="strict",
                text=True, bufsize=1, **_process_options())
            self.reader = threading.Thread(target=self._read_stdout,
                                           name="codex-pointer-rpc", daemon=True)
            self.reader.start()
            self.request("initialize", {"clientInfo": {
                "name": "codex_pointer", "title": "Codex Pointer", "version": __version__}})
            # Wait for initialize's response before sending this notification.
            self._write({"method": "initialized", "params": {}})
            return self
        except BaseException:
            self.close()
            raise

    def _enqueue(self, value: Any) -> None:
        while not self.closed.is_set():
            try:
                self.messages.put(value, timeout=0.1)
                return
            except queue.Full:
                continue

    def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            while not self.closed.is_set():
                line = self.process.stdout.readline(self._MAX_LINE + 1)
                if not line:
                    self._enqueue(BridgeUnavailable("Codex app-server 已断开；没有确认操作成功。"))
                    return
                if len(line) > self._MAX_LINE:
                    self._enqueue(BridgeError("Codex app-server 响应超过大小限制。"))
                    return
                if line.strip():
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError("RPC response must be an object")
                    self._enqueue(message)
        except (OSError, ValueError, UnicodeError):
            self._enqueue(BridgeError("Codex app-server 返回了无效的 UTF-8 JSON 响应。"))

    def _write(self, message: dict[str, Any]) -> None:
        assert self.process is not None and self.process.stdin is not None
        try:
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise BridgeUnavailable("无法写入 Codex app-server；没有确认操作成功。") from exc

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self._write({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BridgeTimeout(f"Codex {method} 超时；若正在发送，请先检查 Codex，避免重复提交。")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise BridgeTimeout(f"Codex {method} 超时；若正在发送，请先检查 Codex，避免重复提交。") from exc
            if isinstance(message, Exception):
                raise message
            if "method" in message:
                if "id" in message:
                    # Never approve requests or impersonate a Desktop host tool.
                    self._write({"id": message["id"], "error": {
                        "code": -32601, "message": "Codex Pointer does not implement interactive host requests."}})
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                code = error.get("code", "unknown") if isinstance(error, dict) else "unknown"
                # Deliberately exclude server text: it may echo a private prompt.
                raise BridgeError(f"Codex {method} 被拒绝（错误码 {code}）；请在 Codex 查看详情。")
            result = message.get("result")
            if not isinstance(result, dict):
                raise BridgeError(f"Codex {method} 响应缺少有效 result。")
            return result

    def close(self) -> None:
        self.closed.set()
        if self.process is None:
            return
        process = self.process
        try:
            if process.stdin:
                process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            process.wait(timeout=0.3)
        except subprocess.TimeoutExpired:
            process.kill()  # Kill only the child proxy/isolated process, never the daemon.
            process.wait(timeout=2)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
        if self.reader is not None:
            self.reader.join(timeout=0.3)

    def __exit__(self, *_: Any) -> None:
        self.close()


def _prompt(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BridgeError("请输入要发送的任务。")
    if "\x00" in value:
        raise BridgeError("任务中包含无效的空字符。")
    return value


def _directory(value: str | os.PathLike[str]) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise BridgeError("工作目录必须是存在的文件夹的绝对路径。")
    return str(path.resolve())


def _thread_id(value: str) -> str:
    # CLI also accepts titles; reject those so a duplicate title cannot misroute work.
    if not isinstance(value, str) or not re.fullmatch(
            r"(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|thr_[A-Za-z0-9_-]+)", value):
        raise BridgeError("必须明确选择对话 ID，不能使用对话名称或自动猜测当前对话。")
    return value


def _image_input(image_path: str | os.PathLike[str] | None) -> list[dict[str, str]]:
    if image_path is None:
        return []
    path = Path(image_path)
    if not path.is_absolute() or not path.is_file():
        raise BridgeError("截图必须是存在的本地文件的绝对路径。")
    return [{"type": "localImage", "path": str(path.resolve())}]


class CodexBridge:
    """Thread listing and explicit dispatch; callers should run this off the UI thread."""

    def __init__(self, executable: str | os.PathLike[str] | None = None,
                 timeout: float = 15.0):
        if not 0.05 <= timeout <= 60:
            raise ValueError("timeout must be between 0.05 and 60 seconds")
        self._configured_executable = executable
        self.timeout = timeout
        self.last_list_backend: str | None = None
        self.last_shared_error: str | None = None
        self._queue_supported: bool | None = None

    @property
    def executable(self) -> str:
        return discover_codex(self._configured_executable)

    def _connection(self, shared: bool = True) -> _RpcConnection:
        args = [self.executable, "app-server"]
        args += ["proxy"] if shared else ["--stdio"]
        return _RpcConnection(args, self.timeout)

    def _has_queue(self) -> bool:
        if self._queue_supported is None:
            try:
                result = subprocess.run([self.executable, "queue", "--help"],
                                        capture_output=True, text=True, encoding="utf-8",
                                        errors="replace", timeout=min(self.timeout, 5),
                                        **_process_options())
                self._queue_supported = (result.returncode == 0 and
                                         "--thread" in result.stdout and "--message" in result.stdout)
            except (OSError, subprocess.TimeoutExpired):
                self._queue_supported = False
        return self._queue_supported

    def diagnostics(self) -> dict[str, Any]:
        """Read-only checks; no login, daemon startup, thread resume, or turn."""
        result: dict[str, Any] = {"executable": None, "shared_available": False,
                                  "queue_available": False, "list_backend": self.last_list_backend,
                                  "detail": ""}
        try:
            result["executable"] = self.executable
            result["queue_available"] = self._has_queue()
            with self._connection():
                result["shared_available"] = True
        except (BridgeError, OSError) as exc:
            result["detail"] = str(exc)
        return result

    def list_threads(self, limit: int = 100) -> list[ThreadSummary]:
        """List up to 500 local root chats, without resuming or repairing logs."""
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        self.last_shared_error = None
        for shared in (True, False):
            try:
                with self._connection(shared) as connection:
                    found: list[ThreadSummary] = []
                    seen_ids: set[str] = set()
                    seen_cursors: set[str] = set()
                    cursor: str | None = None
                    while len(found) < limit:
                        params: dict[str, Any] = {
                            "limit": min(100, limit - len(found)), "sortKey": "updated_at",
                            "sortDirection": "desc", "archived": False, "useStateDbOnly": True,
                            "sourceKinds": ["cli", "vscode", "appServer", "exec", "unknown"]}
                        if cursor is not None:
                            params["cursor"] = cursor
                        result = connection.request("thread/list", params)
                        data = result.get("data")
                        if not isinstance(data, list):
                            raise BridgeError("Codex thread/list 响应缺少 data 列表。")
                        for row in data:
                            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                                continue
                            if row["id"] in seen_ids:
                                continue
                            seen_ids.add(row["id"])
                            preview = row.get("preview") or ""
                            title = row.get("name") or preview or row["id"]
                            found.append(ThreadSummary(row["id"], str(title),
                                                       str(row.get("cwd") or ""), str(preview)))
                            if len(found) >= limit:
                                break
                        cursor = result.get("nextCursor")
                        if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                            break
                        seen_cursors.add(cursor)
                    self.last_list_backend = "shared-app-server" if shared else "isolated-app-server-read-only"
                    return found
            except (BridgeError, OSError) as exc:
                if shared:
                    self.last_shared_error = str(exc)
                    continue
                self.last_list_backend = None
                raise BridgeUnavailable("无法读取本地 Codex 对话。请检查 CLI 和 Codex 登录状态。") from exc
        return []  # Both attempts return or raise above.

    def send_new(self, prompt: str, cwd: str,
                 image_path: str | None = None) -> DispatchResult:
        """Submit to the shared daemon only; never dispatch via isolated fallback."""
        prompt = _prompt(prompt)
        cwd = _directory(cwd)
        inputs = [{"type": "text", "text": prompt}] + _image_input(image_path)
        thread_id = ""
        try:
            with self._connection() as connection:
                started = connection.request("thread/start", {"cwd": cwd})
                thread = started.get("thread", {})
                if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
                    raise BridgeError("Codex 没有返回新对话 ID，任务未发送。")
                thread_id = _thread_id(thread["id"])
                turn = connection.request("turn/start", {"threadId": thread_id, "input": inputs})
                self._confirmed_turn(turn)
                return DispatchResult(thread_id, "shared-app-server", "submitted")
        except (BridgeError, OSError) as exc:
            if thread_id:
                raise BridgeError(f"已创建对话 {thread_id}，但未确认任务开始。请在 Codex 检查后再重试。") from exc
            raise BridgeUnavailable("共享 Codex app-server 不可用，任务未确认发送。可使用“在 Codex 打开草稿”手动发送。") from exc

    @staticmethod
    def _confirmed_turn(result: dict[str, Any]) -> None:
        turn = result.get("turn")
        if not isinstance(turn, dict) or not isinstance(turn.get("id"), str) or not turn["id"]:
            raise BridgeError("Codex 未返回 turn ID，不能确认任务已开始。")
        if turn.get("status") in {"failed", "interrupted"}:
            raise BridgeError("Codex 未成功开始任务，请在 Codex 查看失败原因。")

    def send_existing(self, thread_id: str, prompt: str, cwd: str | None = None,
                      image_path: str | None = None) -> DispatchResult:
        """Queue to an explicit chat; cwd is context, never changes its workspace."""
        thread_id = _thread_id(thread_id)
        prompt = _prompt(prompt)
        if cwd is not None:
            _directory(cwd)
        if image_path is not None:
            raise BridgeError("Codex queue 不支持图片附件。请通过本地捕获 MCP 工具读取截图，或在 Codex 手动添加图片。")
        if self._has_queue():
            try:
                result = subprocess.run(
                    [self.executable, "queue", "--thread", thread_id, "--message", prompt],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=self.timeout, **_process_options())
            except subprocess.TimeoutExpired as exc:
                raise BridgeTimeout("发送超时，任务可能已排队。请先在 Codex 检查，避免重复发送。") from exc
            except OSError as exc:
                raise BridgeUnavailable("无法运行 Codex queue，任务未确认发送。") from exc
            if result.returncode != 0:
                raise BridgeError("Codex queue 没有确认任务排队成功。请在 Codex 检查登录、目标对话和共享服务。")
            return DispatchResult(thread_id, "codex-queue", "queued")
        # Older CLIs without queue still need the shared daemon. No mutation fallback.
        with self._connection() as connection:
            resumed = connection.request("thread/resume", {"threadId": thread_id, "excludeTurns": True})
            resumed_thread = resumed.get("thread")
            if not isinstance(resumed_thread, dict) or resumed_thread.get("id") != thread_id:
                raise BridgeError("Codex 返回的对话 ID 与所选对话不同，任务未发送。")
            result = connection.request("turn/start", {"threadId": thread_id,
                                                        "input": [{"type": "text", "text": prompt}]})
            self._confirmed_turn(result)
            return DispatchResult(thread_id, "shared-app-server", "submitted")

    def open_new_draft(self, prompt: str, cwd: str) -> DispatchResult:
        """Open the documented Desktop deep link. This does NOT send the prompt."""
        prompt = _prompt(prompt)
        cwd = _directory(cwd)
        url = "codex://new?" + urlencode({"path": cwd, "prompt": prompt}, quote_via=quote)
        self._open_desktop_link(url)
        return DispatchResult("", "desktop-deep-link", "draft_opened")

    def open_thread(self, thread_id: str) -> None:
        self._open_desktop_link("codex://threads/" + quote(_thread_id(thread_id), safe=""))

    @staticmethod
    def _open_desktop_link(url: str) -> None:
        if not url.startswith("codex://"):
            raise BridgeError("无效的 Codex 链接。")
        startfile = getattr(os, "startfile", None)
        if startfile is None:
            raise BridgeUnavailable("此桌面集成需要 Windows 和已注册 codex:// 协议的 Codex 应用。")
        try:
            # ShellExecute resolves the registered protocol; no command shell is used.
            startfile(url)
        except OSError as exc:
            raise BridgeUnavailable("无法打开 Codex。请安装桌面应用并注册 codex:// 协议。") from exc
