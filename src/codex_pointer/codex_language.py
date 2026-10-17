"""Read Codex's desktop locale without changing Codex or Windows settings.

Python 3.11 uses tomllib. The Python 3.10 fallback recognizes Codex-generated
tables, dotted keys and ordinary TOML values, while lexically skipping comments
and multiline strings. Ambiguous or unsupported constructs retain the last
working language rather than guessing from text that resembles a setting.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import datetime
import json
import os
from pathlib import Path
import re
from typing import Callable

try:
    import tomllib as _tomllib
except ModuleNotFoundError:  # Python 3.10 ships without tomllib.
    _tomllib = None


_MAX_CONFIG_BYTES = 1024 * 1024


def _supported_language(code: str) -> str:
    family = str(code).strip().replace("_", "-").casefold().split("-", 1)[0]
    return "zh-CN" if family == "zh" else "en-US"


def preferred_ui_language() -> str:
    """Prefer Windows UI language order, independently of regional formatting."""
    if os.name != "nt":
        return "en-US"
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        try:
            preferred = kernel.GetUserPreferredUILanguages
            preferred.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.ULONG),
                                  wintypes.LPWSTR, ctypes.POINTER(wintypes.ULONG)]
            preferred.restype = wintypes.BOOL
            count, size = wintypes.ULONG(), wintypes.ULONG()
            preferred(0x8, ctypes.byref(count), None, ctypes.byref(size))  # MUI_LANGUAGE_NAME
            if 0 < size.value <= 16384:
                names = ctypes.create_unicode_buffer(size.value)
                if preferred(0x8, ctypes.byref(count), names, ctypes.byref(size)) and names.value:
                    return names.value
        except (OSError, AttributeError, ValueError):
            pass
        default = kernel.GetUserDefaultUILanguage
        default.argtypes, default.restype = [], wintypes.WORD
        primary = int(default()) & 0x3FF
        return "zh-CN" if primary == 0x04 else "en-US"
    except (OSError, AttributeError, ValueError):
        return "en-US"


def _quoted_end(text: str, start: int) -> int:
    quote = text[start]
    delimiter = quote * (3 if text.startswith(quote * 3, start) else 1)
    index = start + len(delimiter)
    while index < len(text):
        if text.startswith(delimiter, index):
            return index + len(delimiter)
        if text[index] == "\n" and len(delimiter) == 1:
            raise ValueError("Unfinished single-line TOML string.")
        if quote == '"' and text[index] == "\\":
            index += 2
        else:
            index += 1
    raise ValueError("Unfinished TOML string.")


def _statements(text: str) -> list[str]:
    statements, current, nesting = [], [], []
    index = 0
    while index < len(text):
        character = text[index]
        if character in "\"'":
            end = _quoted_end(text, index)
            current.append(text[index:end])
            index = end
            continue
        if character == "#":
            end = text.find("\n", index)
            index = len(text) if end < 0 else end
            continue
        if character in "[{":
            nesting.append(character)
        elif character in "]}":
            expected = "[" if character == "]" else "{"
            if not nesting or nesting.pop() != expected:
                raise ValueError("Unbalanced TOML value.")
        if character == "\n" and not nesting:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(character)
        index += 1
    if nesting:
        raise ValueError("Unfinished TOML value.")
    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


def _string(text: str) -> str:
    if text.startswith(('"""', "'''")) or _quoted_end(text, 0) != len(text):
        raise ValueError("Expected a single-line setting.")
    if text.startswith("'"):
        return text[1:-1]
    # JSON shares the escapes used by Codex's generated basic TOML strings.
    if re.search(r"\\(?:/|U)", text):
        raise ValueError("Unsupported TOML string escape.")
    return json.loads(text)


def _key(text: str) -> tuple[str, ...]:
    parts, index = [], 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text):
            raise ValueError("Empty dotted key.")
        if text[index] in "\"'":
            end = _quoted_end(text, index)
            part = _string(text[index:end])
            index = end
        else:
            match = re.match(r"[A-Za-z0-9_-]+", text[index:])
            if not match:
                raise ValueError("Unsupported TOML key.")
            part = match.group()
            index += len(part)
        parts.append(part)
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text):
            return tuple(parts)
        if text[index] != ".":
            raise ValueError("Invalid dotted key.")
        index += 1
    raise ValueError("Empty TOML key.")


def _split(text: str, separator: str) -> list[str]:
    parts, start, index, depth = [], 0, 0, 0
    while index < len(text):
        character = text[index]
        if character in "\"'":
            index = _quoted_end(text, index)
            continue
        if character in "[{":
            depth += 1
        elif character in "]}":
            depth -= 1
        elif character == separator and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
        index += 1
    parts.append(text[start:].strip())
    return parts


def _value(text: str):
    if not text:
        raise ValueError("Missing TOML value.")
    if text[0] in "\"'":
        if text.startswith(('"""', "'''")):
            if _quoted_end(text, 0) != len(text):
                raise ValueError("Invalid multiline string.")
            if text.startswith('"""'):
                # Reject unrecognized escapes instead of accepting an invalid
                # partially rewritten document as a new language setting.
                body = text[3:-3]
                body = re.sub(r"\\[ \t\r]*\n[ \t\r\n]*", "", body)
                body = re.sub(r"\\(?:[btnfr\"\\]|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})", "", body)
                if "\\" in body:
                    raise ValueError("Invalid multiline string escape.")
            return None  # Never use multiline text as the desktop locale.
        return _string(text)
    if text.startswith("[") and text.endswith("]"):
        parts = _split(text[1:-1], ",")
        for value in parts[:-1] if not parts[-1] else parts:
            _value(value)
        return None
    if text.startswith("{") and text.endswith("}"):
        if "\n" in text:
            raise ValueError("Unsupported multiline inline table.")
        keys = set()
        if text[1:-1].strip():
            for assignment in _split(text[1:-1], ","):
                pair = _split(assignment, "=")
                path = _key(pair[0]) if len(pair) == 2 else ()
                if len(pair) != 2 or any(path[:len(key)] == key or key[:len(path)] == path for key in keys):
                    raise ValueError("Invalid inline table.")
                keys.add(path)
                _value(pair[1])
        return None
    if text in ("true", "false", "inf", "+inf", "-inf", "nan", "+nan", "-nan"):
        return None
    digits = r"(?:0|[1-9](?:_?[0-9])*)"
    decimal = rf"[+-]?{digits}(?:\.[0-9](?:_?[0-9])*)?(?:[eE][+-]?[0-9](?:_?[0-9])*)?"
    if re.fullmatch(decimal, text) or re.fullmatch(r"0(?:x[0-9A-Fa-f](?:_?[0-9A-Fa-f])*|o[0-7](?:_?[0-7])*|b[01](?:_?[01])*)", text):
        return None
    try:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
            datetime.date.fromisoformat(text)
        elif re.fullmatch(r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?", text):
            datetime.time.fromisoformat(text)
        else:
            datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Unsupported or invalid TOML value.") from None
    return None


def _fallback_override(text: str) -> str | None:
    table, tables, keys, dotted_tables, override = (), set(), set(), set(), None
    arrays, array_entries = set(), {}

    def scope(path):
        encoded = ()
        for depth, name in enumerate(path, 1):
            encoded += (name,)
            if path[:depth] in array_entries:
                encoded = array_entries[path[:depth]]
        return encoded

    for statement in _statements(text):
        if statement.startswith("[["):
            if not statement.endswith("]]"):
                raise ValueError("Invalid TOML array table.")
            raw = _key(statement[2:-2].strip())
            if raw == ("desktop",) or raw[:2] == ("desktop", "localeOverride"):
                raise ValueError("Invalid desktop setting structure.")
            container = scope(raw[:-1]) + (raw[-1],)
            if (container in tables or container in dotted_tables or
                    any(container[:len(key)] == key for key in keys)):
                raise ValueError("Conflicting TOML array table.")
            arrays.add(container)
            # Every entry is an independent scope, including nested tables and
            # dotted keys. Markers cannot equal any untrusted string key.
            for previous in list(array_entries):
                if previous[:len(raw)] == raw:
                    del array_entries[previous]
            table = container + (object(),)
            array_entries[raw] = table
            continue
        if statement.startswith("["):
            if not statement.endswith("]"):
                raise ValueError("Invalid TOML table.")
            raw = _key(statement[1:-1].strip())
            table = scope(raw)
            if (table in tables or table in dotted_tables or raw in array_entries
                    or any(table[:len(key)] == key for key in keys)
                    or raw[:2] == ("desktop", "localeOverride")):
                raise ValueError("Duplicate TOML table.")
            tables.add(table)
            continue
        parts = _split(statement, "=")
        if len(parts) != 2:
            raise ValueError("Invalid TOML assignment.")
        relative = _key(parts[0])
        path = table + relative
        dotted_tables.update(table + relative[:depth] for depth in range(1, len(relative)))
        if path in arrays or path in tables or any(path[:len(key)] == key or key[:len(path)] == path for key in keys):
            raise ValueError("Duplicate TOML key.")
        keys.add(path)
        value = _value(parts[1])
        if path == ("desktop",) or (len(path) > 2 and path[:2] == ("desktop", "localeOverride")):
            raise ValueError("Unsupported desktop setting structure.")
        if path == ("desktop", "localeOverride"):
            if not isinstance(value, str):
                raise ValueError("Unsupported desktop locale setting.")
            override = value
    return override


def _override(text: str) -> str | None:
    if _tomllib is None:
        return _fallback_override(text)
    data = _tomllib.loads(text)
    desktop = data.get("desktop", {})
    if not isinstance(desktop, dict):
        raise ValueError("Invalid desktop settings.")
    value = desktop.get("localeOverride")
    if value is not None and not isinstance(value, str):
        raise ValueError("Invalid desktop locale.")
    return value


class CodexLanguageReader:
    def __init__(self, config_path: Path | str | None = None,
                 system_language: Callable[[], str] | None = None):
        root = Path(os.environ["CODEX_HOME"]) if os.environ.get("CODEX_HOME") else Path.home() / ".codex"
        self.config_path = Path(config_path) if config_path is not None else root / "config.toml"
        self._system_language = system_language or preferred_ui_language
        self._last_language = self._system()
        self._signature = None
        self._automatic = True

    def _system(self) -> str:
        try:
            return _supported_language(self._system_language())
        except (OSError, ValueError, TypeError):
            return "en-US"

    def read(self) -> str:
        try:
            info = self.config_path.stat()
            signature = (info.st_mtime_ns, info.st_size)
        except FileNotFoundError:
            self._signature = None
            if self._automatic:
                self._last_language = self._system()
            return self._last_language
        except OSError:
            self._signature = None
            return self._last_language
        if signature == self._signature:
            if self._automatic:
                self._last_language = self._system()
            return self._last_language
        self._signature = signature
        try:
            if info.st_size > _MAX_CONFIG_BYTES:
                raise ValueError("Configuration exceeds the locale reader limit.")
            with self.config_path.open("rb") as source:
                raw = source.read(_MAX_CONFIG_BYTES + 1)
            if len(raw) > _MAX_CONFIG_BYTES:
                raise ValueError("Configuration exceeds the locale reader limit.")
            after = self.config_path.stat()
            if (after.st_mtime_ns, after.st_size) != signature:
                return self._last_language
            value = _override(raw.decode("utf-8"))
            automatic = value is None or value.strip().casefold() in ("", "auto", "system")
            self._last_language = self._system() if automatic else _supported_language(value)
            self._automatic = automatic
        except OSError:
            # Locks and transient atomic replacement must be retried even if
            # the next stat has the same timestamp and size as this attempt.
            self._signature = None
        except (ValueError, TypeError, UnicodeError, RecursionError):
            self._automatic = False
        return self._last_language
