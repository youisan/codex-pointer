"""Embed the launcher's small catalog from the native source of truth."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from codex_pointer.i18n import catalog


def main():
    path = ROOT / "src/codex_pointer/assets/launcher.html"
    html = path.read_text(encoding="utf-8")
    script = html.split("  <script>", 1)[1]
    keys = {json.loads(match) for match in re.findall(r'tr\(("(?:[^"\\]|\\.)*")\)', script)}
    keys.update(re.findall(r'data-i18n(?:-title|-aria)?="([^"]+)"', html))
    keys.update(("正在连接", "正在读取悬浮按钮状态。"))
    english = catalog("en-US")
    missing = sorted(keys - english.keys())
    if missing:
        raise RuntimeError("Missing English launcher messages: " + repr(missing))
    payload = json.dumps({key: english[key] for key in sorted(keys)}, ensure_ascii=False, indent=2)
    # The generated JSON cannot close the surrounding inline script.
    payload = payload.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    generated = "// BEGIN GENERATED TRANSLATIONS\n      const english = " + payload.replace("\n", "\n      ") + ";\n      // END GENERATED TRANSLATIONS"
    updated, count = re.subn(r"// BEGIN GENERATED TRANSLATIONS.*?// END GENERATED TRANSLATIONS",
                             lambda _: generated, html, flags=re.S)
    if count != 1:
        raise RuntimeError("Expected exactly one launcher translation region")
    if updated != html:
        path.write_text(updated, encoding="utf-8", newline="\n")
    print(f"Launcher: {len(keys)} bilingual messages synchronized.")


if __name__ == "__main__":
    main()
