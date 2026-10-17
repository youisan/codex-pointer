"""Keep the launcher's inline SVGs identical to the native vector icon family."""
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from codex_pointer.iconography import icon_svg


def sync():
    path = ROOT / "src/codex_pointer/assets/launcher.html"
    source = path.read_text(encoding="utf-8")
    count = 0

    def replace(match):
        nonlocal count
        tag = match.group()
        name = re.search(r'data-pointer-icon="([a-z-]+)"', tag).group(1)
        size = int(re.search(r'width="(\d+)"', tag).group(1))
        count += 1
        return icon_svg(name, size=size).replace("<svg", f'<svg data-pointer-icon="{name}" aria-hidden="true"', 1)

    result = re.sub(r'<svg\b(?=[^>]*\bdata-pointer-icon=")[\s\S]*?</svg>', replace, source)
    if count != 5:
        raise RuntimeError(f"Expected five launcher SVGs, found {count}")
    if result != source:
        path.write_text(result, encoding="utf-8")
    print("Launcher SVGs synchronized with the native icon family.")


if __name__ == "__main__":
    sync()
