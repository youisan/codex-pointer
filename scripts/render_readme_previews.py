"""Render bilingual README images from real, owned Qt widgets.

Run ``python scripts/render_readme_previews.py`` on the Windows development
environment. Each language/theme is rendered in a fresh offscreen process.
Only synthetic context is used: no desktop capture, user settings, clipboard,
Codex connection or model request. Existing documentation images are replaced.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("en-US", "zh-CN")
THEMES = ("light", "dark")


def render_one(language: str, theme: str, output: Path) -> dict:
    # Set before importing Qt; never create a native desktop window.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.path.insert(0, str(ROOT / "src"))

    from unittest.mock import Mock, patch

    from PySide6.QtCore import QEvent, QPoint, QRect, Qt
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton

    from codex_pointer.app import PointerController
    from codex_pointer.bridge import CodexBridge
    from codex_pointer.i18n import set_language, tr
    from codex_pointer.quick_tasks import tasks_for
    from codex_pointer.windows import TargetContext

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_Use96Dpi)
    application = QApplication([])
    application.setApplicationName("Codex Pointer")
    application.setQuitOnLastWindowClosed(False)
    if sys.platform == "win32":
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("segoeui.ttf", "seguisb.ttf", "msyh.ttc"):
            QFontDatabase.addApplicationFont(str(fonts / name))

    set_language(language)
    bridge = Mock(spec=CodexBridge)
    fixture_name = "Research" if language == "en-US" else "研究资料"
    target = TargetContext(
        kind="folder", title=fixture_name,
        path=f"D:/Projects/{fixture_name}", source="preview", point=(0, 0),
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Documentation rendering must not access the desktop or settings.")

    with patch("codex_pointer.app.CodexBridge", return_value=bridge), \
            patch("codex_pointer.app.save_settings", side_effect=forbidden), \
            patch("codex_pointer.app.get_cursor_position", side_effect=forbidden), \
            patch("codex_pointer.app.get_foreground_window", side_effect=forbidden), \
            patch("codex_pointer.app.capture_screenshot", side_effect=forbidden):
        controller = PointerController(
            application, preview=True, theme=theme, reduced_motion=True,
        )
        try:
            controller.target = target
            controller.open_panel()
            panel = controller.panel
            panel.insert_quick_task(0)
            panel.editor.clearFocus()
            for _ in range(5):
                application.processEvents()

            # Do not silently publish a Chinese render under an English name.
            assert panel.new_button.text() == tr("新对话")
            assert panel.existing_button.text() == tr("继续对话")
            assert panel.primary.text() == tr("在 Codex 中继续")
            assert [button.text() for button in panel.quick_task_buttons] == [
                task.label for task in tasks_for(target)
            ]
            if language == "en-US":
                widgets = (
                    panel.findChildren(QLabel)
                    + panel.findChildren(QPushButton)
                    + panel.findChildren(QCheckBox)
                )
                visible_text = [widget.text() for widget in widgets if widget.isVisible()]
                visible_text.append(panel.editor.toPlainText())
                assert not any(re.search(r"[\u3400-\u9fff]", text) for text in visible_text), visible_text

            primary_bounds = QRect(panel.primary.mapTo(panel, QPoint(0, 0)), panel.primary.size())
            assert panel.rect().contains(primary_bounds), "The primary action is cropped."
            assert panel.primary.isEnabled(), "The example task must have a usable action."
            assert not bridge.mock_calls, "Preview unexpectedly called Codex."

            output.parent.mkdir(parents=True, exist_ok=True)
            pixmap = panel.grab()
            if pixmap.isNull() or not pixmap.save(str(output)):
                raise RuntimeError(f"Could not save {output}")
            return {
                "language": language, "theme": theme, "path": str(output),
                "pixels": [pixmap.width(), pixmap.height()],
                "primary": panel.primary.text(),
                "quick_tasks": [button.text() for button in panel.quick_task_buttons],
            }
        finally:
            controller.cleanup()
            for widget in application.topLevelWidgets():
                widget.close()
                widget.deleteLater()
            application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            application.processEvents()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs")
    parser.add_argument("--single", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--language", choices=LANGUAGES)
    parser.add_argument("--theme", choices=THEMES)
    parser.add_argument("--output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.single:
        if not (args.language and args.theme and args.output):
            parser.error("--single requires --language, --theme and --output")
        print(json.dumps(
            render_one(args.language, args.theme, args.output.resolve()), ensure_ascii=False,
        ))
        return

    output_dir = args.output_dir.resolve()
    for language in (args.language,) if args.language else LANGUAGES:
        suffix = "en" if language == "en-US" else "zh-CN"
        for theme in (args.theme,) if args.theme else THEMES:
            output = output_dir / f"preview-{theme}-{suffix}.png"
            result = subprocess.run(
                [sys.executable, "-X", "utf8", str(Path(__file__).resolve()),
                 "--single", "--language", language, "--theme", theme, "--output", str(output)],
                check=False, capture_output=True, text=True, encoding="utf-8", timeout=25,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode:
                raise RuntimeError(f"Could not render {language}/{theme}:\n{result.stdout}\n{result.stderr}")
            print(result.stdout.strip())
            if language == "zh-CN":
                # Keep existing release scripts and old documentation links valid.
                shutil.copyfile(output, output_dir / f"preview-{theme}.png")


if __name__ == "__main__":
    main()
