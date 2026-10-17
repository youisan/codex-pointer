"""Only preferences and explicitly bound thread IDs are persisted."""
from __future__ import annotations

import json
import os
from pathlib import Path


def data_directory() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
    return base / "CodexPointer"


def load_settings() -> dict:
    try:
        value = json.loads((data_directory() / "settings.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(value: dict) -> None:
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    temp = directory / "settings.tmp"
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(directory / "settings.json")
