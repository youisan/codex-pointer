"""Generate Pointer's app identity and a Windows ICO from shared vectors."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from codex_pointer.iconography import ICONS, app_badge_svg, paint_icon


def badge_image(size: int, theme: str = "light") -> QImage:
    """Draw the app badge from the same paths used in native controls."""
    background, foreground = (("#ededed", "#181818") if theme == "dark"
                              else ("#212121", "#ffffff"))
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 64, size / 64)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(background))
    painter.drawRoundedRect(QRectF(2, 2, 60, 60), 17, 17)
    painter.translate(13, 13)
    painter.scale(38 / 24, 38 / 24)
    paint_icon(painter, "target", foreground)
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("PNG encoding failed")
    return bytes(buffer.data())


def contact_sheet(destination: Path) -> None:
    """Render a review sheet; the distributable contains only app assets."""
    names = list(ICONS)
    columns, cell_width, cell_height = 6, 150, 104
    rows = (len(names) + columns - 1) // columns
    sheet = QImage(columns * cell_width, rows * cell_height * 2,
                   QImage.Format.Format_ARGB32)
    sheet.fill(QColor("#ffffff"))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont("Segoe UI")
    font.setPixelSize(12)
    painter.setFont(font)
    for mode, bg, fg in ((0, "#ffffff", "#181818"), (1, "#181818", "#ededed")):
        base_y = mode * rows * cell_height
        painter.fillRect(0, base_y, sheet.width(), rows * cell_height, QColor(bg))
        for index, name in enumerate(names):
            x, y = (index % columns) * cell_width, base_y + (index // columns) * cell_height
            painter.save()
            painter.translate(x + 57, y + 18)
            painter.scale(1.5, 1.5)
            paint_icon(painter, name, fg)
            painter.restore()
            painter.setPen(QColor(fg))
            painter.drawText(QRectF(x, y + 64, cell_width, 22),
                             Qt.AlignmentFlag.AlignCenter, name)
    painter.end()
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(str(destination))


def main() -> None:
    application = QApplication.instance() or QApplication([])
    # Offscreen Qt does not discover the host's fonts automatically. These
    # installed fonts improve only the review sheet; no font is distributed.
    if application.platformName() == "offscreen" and sys.platform == "win32":
        for name in ("segoeui.ttf", "seguisb.ttf", "msyh.ttc"):
            QFontDatabase.addApplicationFont(
                str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
    destination = ROOT / "src/codex_pointer/assets"
    plugin_assets = ROOT / "plugins/codex-pointer/assets"
    destination.mkdir(parents=True, exist_ok=True)
    plugin_assets.mkdir(parents=True, exist_ok=True)
    for theme in ("light", "dark"):
        (destination / f"pointer-{theme}.svg").write_text(app_badge_svg(theme), encoding="utf-8")
        (destination / f"pointer-{theme}.png").write_bytes(png_bytes(badge_image(256, theme)))
    sizes = [16, 20, 24, 32, 48, 64, 128, 256]
    images = [png_bytes(badge_image(size)) for size in sizes]
    offset = 6 + 16 * len(sizes)
    entries = []
    for size, data in zip(sizes, images):
        entries.append(struct.pack("<4B2H2I", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    (destination / "pointer.ico").write_bytes(
        struct.pack("<3H", 0, 1, len(sizes)) + b"".join(entries) + b"".join(images))
    for name in ("pointer-light.svg", "pointer-dark.svg", "pointer-light.png",
                 "pointer-dark.png", "pointer.ico"):
        shutil.copyfile(destination / name, plugin_assets / name)
    contact_sheet(ROOT / ".dev/icons-review.png")
    print(f"Generated five app assets in {destination} and {plugin_assets}")


if __name__ == "__main__":
    main()
