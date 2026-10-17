"""Pointer's original, shared 24 px vector artwork.

This module deliberately imports only the standard library until ``paint_icon``
is called.  The MCP host, SVG launcher and native desktop widgets all consume
the same geometry; installing an icon must never load Qt into the MCP host.
"""

from __future__ import annotations

from base64 import b64encode
from html import escape
import re


STROKE_WIDTH = 1.65

# Small absolute paths keep the source reviewable and render identically through
# SVG and QPainter.  Every mark is drawn for this project, on a 24 x 24 grid.
# Primitive layout: ("path", d), ("circle", cx, cy, radius), or
# ("roundrect", x, y, width, height, corner_radius).
ICONS: dict[str, tuple[tuple, ...]] = {
    "target": (
        ("path", "M8 3.5 L5.5 3.5 Q3.5 3.5 3.5 5.5 L3.5 8 M16 3.5 L18.5 3.5 Q20.5 3.5 20.5 5.5 L20.5 8 M3.5 16 L3.5 18.5 Q3.5 20.5 5.5 20.5 L8 20.5 M20.5 16 L20.5 18.5 Q20.5 20.5 18.5 20.5 L16 20.5"),
        ("path", "M8.8 7.3 L17.7 14.4 L13.5 15 L11.6 19 Z"),
    ),
    "cursor": (("path", "M6 3.5 L18 13.3 L12.7 14 L10.2 20.3 Z"),),
    "folder": (("path", "M3.5 7.5 L3.5 6.2 Q3.5 4.5 5.2 4.5 L9 4.5 L11.2 7 L18.8 7 Q20.5 7 20.5 8.7 L20.5 17.8 Q20.5 19.5 18.8 19.5 L5.2 19.5 Q3.5 19.5 3.5 17.8 Z M3.5 9 L20.5 9"),),
    "folder-open": (("path", "M3.5 10 L3.5 6.2 Q3.5 4.5 5.2 4.5 L9 4.5 L11.2 7 L18.8 7 Q20.5 7 20.5 8.7 L20.5 10 M3.5 11 L20.3 11 Q21.5 11 21.1 12.2 L19.5 18.1 Q19.1 19.5 17.7 19.5 L5.8 19.5 Q4.6 19.5 4.4 18.3 L3.1 12.2 Q2.9 11 3.5 11 Z"),),
    "file": (("path", "M13.5 3.5 L6.7 3.5 Q5 3.5 5 5.2 L5 18.8 Q5 20.5 6.7 20.5 L17.3 20.5 Q19 20.5 19 18.8 L19 9 Z M13.5 3.5 L13.5 7.4 Q13.5 9 15.1 9 L19 9 M8.5 13 L15.5 13 M8.5 16.5 L13 16.5"),),
    "window": (("roundrect", 3.5, 4.5, 17, 15, 2), ("path", "M3.5 9 L20.5 9 M6.5 6.8 L6.6 6.8 M9.4 6.8 L9.5 6.8")),
    "chat": (("path", "M7.5 18.5 L4.5 20 L4.5 6.5 Q4.5 4.5 6.5 4.5 L17.5 4.5 Q19.5 4.5 19.5 6.5 L19.5 16.5 Q19.5 18.5 17.5 18.5 Z M8.3 9 L15.7 9 M8.3 13 L13.6 13"),),
    "chat-plus": (("path", "M7.5 18.5 L4.5 20 L4.5 6.5 Q4.5 4.5 6.5 4.5 L17.5 4.5 Q19.5 4.5 19.5 6.5 L19.5 16.5 Q19.5 18.5 17.5 18.5 Z M8.5 11.5 L15.5 11.5 M12 8 L12 15"),),
    "arrow-right": (("path", "M4.5 12 L19.5 12 M13.5 6 L19.5 12 L13.5 18"),),
    "arrow-up-right": (("path", "M6 18 L18 6 M6.5 6 L18 6 L18 17.5"),),
    "x": (("path", "M6.5 6.5 L17.5 17.5 M17.5 6.5 L6.5 17.5"),),
    "moon": (("path", "M19.9 14.6 C18.7 18.4 14.9 20.9 11 20 C6.8 19.1 4.2 15 5.1 10.8 C5.8 7.5 8.4 5 11.7 4.6 C9.9 6.7 9.5 9.7 11 12.1 C12.8 15 16.7 16.1 19.9 14.6 Z"),),
    "sun": (("circle", 12, 12, 4), ("path", "M12 2.8 L12 4.4 M12 19.6 L12 21.2 M2.8 12 L4.4 12 M19.6 12 L21.2 12 M5.5 5.5 L6.6 6.6 M17.4 17.4 L18.5 18.5 M18.5 5.5 L17.4 6.6 M6.6 17.4 L5.5 18.5")),
    "more": (("circle", 5, 12, 0.85), ("circle", 12, 12, 0.85), ("circle", 19, 12, 0.85)),
    "image": (("roundrect", 3.5, 4.5, 17, 15, 2), ("circle", 15.8, 8.8, 1.35), ("path", "M3.5 16 L8.6 10.9 L16.8 19.5 M13.7 16.4 L16.5 13.6 L20.5 17.6")),
    "camera": (("path", "M8 6.5 L9.5 4.5 L14.5 4.5 L16 6.5 L19 6.5 Q21 6.5 21 8.5 L21 17.5 Q21 19.5 19 19.5 L5 19.5 Q3 19.5 3 17.5 L3 8.5 Q3 6.5 5 6.5 Z"), ("circle", 12, 12.8, 3.5)),
    "chevron-down": (("path", "M6.5 9 L12 14.5 L17.5 9"),),
    "check": (("path", "M5 12.3 L9.6 16.8 L19 7.3"),),
    "settings": (("path", "M10 3.5 L14 3.5 L14.5 5.8 L16.5 7 L18.8 6.3 L20.8 9.7 L19 11.3 L19 13.7 L20.8 15.3 L18.8 18.7 L16.5 18 L14.5 19.2 L14 21.5 L10 21.5 L9.5 19.2 L7.5 18 L5.2 18.7 L3.2 15.3 L5 13.7 L5 11.3 L3.2 9.7 L5.2 6.3 L7.5 7 L9.5 5.8 Z"), ("circle", 12, 12.5, 3)),
    "refresh": (("path", "M19.2 9 C18 5.7 14.5 3.8 11 4.5 C7.5 5.2 5 8.3 5 11.8 M19.2 4.7 L19.2 9 L14.9 9 M4.8 15 C6 18.3 9.5 20.2 13 19.5 C16.5 18.8 19 15.7 19 12.2 M4.8 19.3 L4.8 15 L9.1 15"),),
    "history": (("path", "M4 9 C5.3 5.3 9.3 3.1 13.3 3.7 C17.9 4.4 21.1 8.8 20.4 13.4 C19.7 18 15.4 21.2 10.8 20.5 C8.2 20.1 6 18.6 4.7 16.5 M4 4.8 L4 9 L8.2 9 M12 7.4 L12 12.3 L15.2 14.2"),),
    "eye": (("path", "M2.8 12 C5.2 7.6 8.3 5.5 12 5.5 C15.7 5.5 18.8 7.6 21.2 12 C18.8 16.4 15.7 18.5 12 18.5 C8.3 18.5 5.2 16.4 2.8 12 Z"), ("circle", 12, 12, 3)),
    "eye-off": (("path", "M4 4 L20 20 M8.3 6.3 C9.5 5.8 10.7 5.5 12 5.5 C15.7 5.5 18.8 7.6 21.2 12 C20.4 13.4 19.5 14.6 18.5 15.6 M14.1 18.2 C13.4 18.4 12.7 18.5 12 18.5 C8.3 18.5 5.2 16.4 2.8 12 C3.7 10.4 4.7 9.1 5.8 8.1 M10 9.8 C8.9 10.8 8.8 12.7 10 14 C11.2 15.2 13.1 15.1 14.2 14"),),
    "pin": (("path", "M8 3.5 L16 3.5 M9 3.5 L9 9 L6 13 L6 14 L18 14 L18 13 L15 9 L15 3.5 M12 14 L12 21"),),
    "scan": (("path", "M8 3.5 L5.5 3.5 Q3.5 3.5 3.5 5.5 L3.5 8 M16 3.5 L18.5 3.5 Q20.5 3.5 20.5 5.5 L20.5 8 M3.5 16 L3.5 18.5 Q3.5 20.5 5.5 20.5 L8 20.5 M20.5 16 L20.5 18.5 Q20.5 20.5 18.5 20.5 L16 20.5 M7 12 L17 12"),),
    "info": (("circle", 12, 12, 8.5), ("path", "M12 10.5 L12 16 M12 7.6 L12 7.7")),
    "activity": (("path", "M3 12 L7 12 L10 5 L14 19 L17 12 L21 12"),),
    "keyboard": (("roundrect", 3, 5, 18, 14, 2), ("path", "M6.6 8.5 L6.7 8.5 M10.2 8.5 L10.3 8.5 M13.8 8.5 L13.9 8.5 M17.4 8.5 L17.5 8.5 M6.6 12 L6.7 12 M10.2 12 L10.3 12 M13.8 12 L13.9 12 M17.4 12 L17.5 12 M8 15.6 L16 15.6")),
    "logout": (("path", "M10 4.5 L6.5 4.5 Q4.5 4.5 4.5 6.5 L4.5 17.5 Q4.5 19.5 6.5 19.5 L10 19.5 M10 12 L20.5 12 M16 7.5 L20.5 12 L16 16.5"),),
    "motion": (("path", "M3.5 8 L7 8 M2.5 12 L6 12 M3.5 16 L7 16 M12 5.2 C15.8 3.9 19.9 6 21.1 9.8 C22.3 13.6 20.2 17.7 16.4 18.9 M11.8 8.5 L16.6 12 L11.8 15.5 Z"),),
    "panel": (("roundrect", 3.5, 4.5, 17, 15, 2), ("path", "M9.5 4.5 L9.5 19.5 M6.5 8 L6.6 8 M6.5 11.5 L6.6 11.5")),
}

def _primitives(name: str) -> tuple[tuple, ...]:
    return ICONS.get(name, ICONS["cursor"])


def icon_svg(name: str, color: str = "currentColor", size: int = 24) -> str:
    """Return a self-contained SVG with no scripts, fonts or external assets."""
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= 4096:
        raise ValueError("Icon size must be an integer between 1 and 4096.")
    elements = []
    for shape in _primitives(name):
        if shape[0] == "path":
            elements.append(f'<path d="{shape[1]}"/>')
        elif shape[0] == "circle":
            _, x, y, radius = shape
            elements.append(f'<circle cx="{x}" cy="{y}" r="{radius}"/>')
        elif shape[0] == "roundrect":
            _, x, y, width, height, radius = shape
            elements.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 24 24" fill="none" stroke="{escape(color, quote=True)}" '
            f'stroke-width="{STROKE_WIDTH}" stroke-linecap="round" stroke-linejoin="round">'
            + "".join(elements) + "</svg>")


def data_icon(name: str = "target", theme: str = "light") -> str:
    """Return a theme-appropriate SVG data URI without importing Qt."""
    color = "#ededed" if theme == "dark" else "#181818"
    return "data:image/svg+xml;base64," + b64encode(icon_svg(name, color).encode("utf-8")).decode("ascii")


def _painter_path(data: str):
    from PySide6.QtGui import QPainterPath

    tokens = re.findall(r"[MLQCZ]|-?\d+(?:\.\d+)?", data)
    path = QPainterPath()
    index = 0
    while index < len(tokens):
        command = tokens[index]
        index += 1
        count = {"M": 2, "L": 2, "Q": 4, "C": 6, "Z": 0}[command]
        points = tuple(float(value) for value in tokens[index:index + count])
        index += count
        if command == "M":
            path.moveTo(*points)
        elif command == "L":
            path.lineTo(*points)
        elif command == "Q":
            path.quadTo(*points)
        elif command == "C":
            path.cubicTo(*points)
        else:
            path.closeSubpath()
    return path


def paint_icon(painter, name: str, color) -> None:
    """Paint the same 24-unit geometry into an already transformed QPainter."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen

    painter.save()
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(color), STROKE_WIDTH, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for shape in _primitives(name):
            if shape[0] == "path":
                painter.drawPath(_painter_path(shape[1]))
            elif shape[0] == "circle":
                _, x, y, radius = shape
                painter.drawEllipse(QRectF(x - radius, y - radius, 2 * radius, 2 * radius))
            elif shape[0] == "roundrect":
                _, x, y, width, height, radius = shape
                painter.drawRoundedRect(QRectF(x, y, width, height), radius, radius)
    finally:
        painter.restore()


def app_badge_svg(theme: str = "light", size: int = 256) -> str:
    """Return the rounded square app identity, separate from small UI glyphs."""
    background, foreground = (("#ededed", "#181818") if theme == "dark"
                              else ("#212121", "#ffffff"))
    glyph = icon_svg("target", foreground).split(">", 1)[1].removesuffix("</svg>")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            'viewBox="0 0 64 64">'
            f'<rect x="2" y="2" width="60" height="60" rx="17" fill="{background}"/>'
            f'<g transform="translate(13 13) scale(1.5833333333)" fill="none" '
            f'stroke="{foreground}" stroke-width="{STROKE_WIDTH}" '
            'stroke-linecap="round" stroke-linejoin="round">' + glyph + "</g></svg>")
