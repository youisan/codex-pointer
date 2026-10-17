"""Local target preferences, with no filesystem probes or chat inference.

Only an explicit selection creates a binding. In particular the old global
``thread_id`` preference never supplies a route for an unrelated target.
Windows paths are normalized lexically, so an unavailable network share cannot
stall target switching. Application routes deliberately require a full executable
path; window titles and process basenames are not stable identities.
"""
from __future__ import annotations

from collections.abc import Mapping
import ntpath
from typing import Any
from uuid import UUID


MAX_ROUTES = 100
MAX_RECENT_TARGETS = 8
_MAX_PATH = 32768
_MAX_TITLE = 240


def _field(target: Any, name: str, default: Any = "") -> Any:
    return target.get(name, default) if isinstance(target, Mapping) else getattr(target, name, default)


def _text(value: Any, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _absolute_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > _MAX_PATH or "\0" in value:
        return None
    path = value.replace("/", "\\")
    # Extended filesystem paths and ordinary paths identify the same target.
    if path.casefold().startswith("\\\\?\\unc\\"):
        path = "\\\\" + path[8:]
    elif path.startswith("\\\\?\\"):
        path = path[4:]
    if path.startswith("\\\\.\\"):
        return None  # Device names are not routable filesystem targets.
    drive, tail = ntpath.splitdrive(path)
    if drive.startswith("\\\\"):
        if len([part for part in drive[2:].split("\\") if part]) != 2:
            return None
        # A bare UNC share and the same share with a trailing slash are equal.
        path = drive + (tail or "\\")
    elif len(drive) == 2 and drive[0].isalpha() and drive[1] == ":" and tail.startswith("\\"):
        pass
    else:
        return None  # Drive-relative and current-drive-rooted paths are ambiguous.
    return ntpath.normpath(path)


def route_key(target: Any) -> str | None:
    """Return an exact folder or application key without touching disk.

    Files share their containing folder's route. Sibling folders and child
    folders remain separate; routes never inherit from a parent directory.
    """
    kind = _field(target, "kind")
    if kind in ("folder", "file"):
        path = _absolute_path(_field(target, "path"))
        if not path:
            return None
        if kind == "file":
            path = ntpath.dirname(path)
        return "folder:" + path.casefold()
    if kind == "window":
        path = _absolute_path(_field(target, "process_path"))
        return "application:" + path.casefold() if path else None
    return None


def _thread_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        return None


def _route(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    identifier = _thread_id(value.get("thread_id"))
    mode = value.get("mode", "existing" if identifier else "new")
    if mode not in ("new", "existing"):
        mode = "new"
    if not identifier:
        return {"mode": "new"} if mode == "new" else None
    return {"thread_id": identifier,
            "thread_title": _text(value.get("thread_title"), _MAX_TITLE) or identifier,
            "mode": mode}


def _routes(settings: dict) -> dict:
    raw = settings.get("target_routes")
    if not isinstance(raw, dict):
        return {}
    # Preserve insertion order as recency, while dropping malformed entries.
    cleaned = {}
    for key, value in raw.items():
        if not isinstance(key, str) or len(key) > _MAX_PATH + 12:
            continue
        prefix, separator, path = key.partition(":")
        normalized = _absolute_path(path) if separator else None
        if prefix not in ("folder", "application") or not normalized or normalized.casefold() != path:
            continue
        route = _route(value)
        if route:
            cleaned[key] = route
    return dict(list(cleaned.items())[-MAX_ROUTES:])


def binding_for(settings: dict, target: Any) -> dict | None:
    """Copy an explicitly saved binding for this exact target, if valid."""
    key = route_key(target)
    raw = settings.get("target_routes")
    value = _route(raw.get(key)) if key and isinstance(raw, dict) else None
    return value if value and value.get("thread_id") else None


def mode_for(settings: dict, target: Any) -> str:
    """New is the safe default unless this target has a valid saved binding."""
    binding = binding_for(settings, target)
    return binding["mode"] if binding else "new"


def _save_route(settings: dict, key: str, value: dict) -> None:
    routes = _routes(settings)
    routes.pop(key, None)
    routes[key] = value
    settings["target_routes"] = dict(list(routes.items())[-MAX_ROUTES:])


def remember_binding(settings: dict, target: Any, thread_id: str, title: str = "") -> dict:
    """Save the user's explicit target/chat selection; return the saved copy.

    Invalid chat IDs or ambiguous targets raise ValueError without mutation.
    The caller owns persistence, so ordinary UI refreshes perform no disk I/O.
    """
    key, identifier = route_key(target), _thread_id(thread_id)
    if not key:
        raise ValueError("这个目标没有可稳定记住的文件夹或软件路径。")
    if not identifier:
        raise ValueError("对话 ID 必须是有效的 UUID。")
    value = {"thread_id": identifier, "thread_title": _text(title, _MAX_TITLE) or identifier,
             "mode": "existing"}
    _save_route(settings, key, value)
    return dict(value)


def remember_mode(settings: dict, target: Any, mode: str) -> None:
    """Remember a mode without fabricating a chat binding."""
    if mode not in ("new", "existing"):
        raise ValueError("对话模式必须是 new 或 existing。")
    key = route_key(target)
    if not key:
        return
    value = binding_for(settings, target) or {"mode": "new"}
    value["mode"] = mode if mode == "new" or value.get("thread_id") else "new"
    _save_route(settings, key, value)


def _recent_record(target: Any) -> dict | None:
    key = route_key(target)
    if not key:
        return None
    kind = _field(target, "kind")
    record = {"key": key, "kind": kind, "title": _text(_field(target, "title"), _MAX_TITLE)}
    if kind in ("folder", "file"):
        record["path"] = _absolute_path(_field(target, "path"))
    else:
        record["process_path"] = _absolute_path(_field(target, "process_path"))
        record["process_name"] = _text(_field(target, "process_name"), 260)
    return record


def recent_targets(settings: dict) -> list[dict]:
    """Newest first, metadata only, sanitized on every read."""
    raw = settings.get("recent_targets")
    if not isinstance(raw, list):
        return []
    result, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        record = _recent_record(item)
        if not record or record["key"] in seen:
            continue
        seen.add(record["key"])
        result.append(record)
        if len(result) == MAX_RECENT_TARGETS:
            break
    return result


def remember_target(settings: dict, target: Any) -> list[dict]:
    """Remember selected metadata; never save pixels, prompts or window handles."""
    record = _recent_record(target)
    records = recent_targets(settings)
    if record:
        records = [record] + [item for item in records if item["key"] != record["key"]]
    settings["recent_targets"] = records[:MAX_RECENT_TARGETS]
    return [dict(item) for item in settings["recent_targets"]]
