"""Keep normal PySide runtime support without optional software OpenGL.

Pointer uses raster QWidget painting and QPixmap screenshots. It does not
create OpenGL contexts, so Mesa's optional opengl32sw.dll is unnecessary.
"""
from pathlib import Path

from PyInstaller.utils.hooks.qt import (
    ensure_single_qt_bindings_package,
    pyside6_library_info,
)


ensure_single_qt_bindings_package("PySide6")
# PySide6 6.7's package initializer contains an optional QtNetwork import to
# pre-load SSL only when its separate ``openssl`` directory exists. ModuleGraph
# sees that guarded import even though this widget app ships no such directory.
# Exclude this package-local optional edge; a real application import elsewhere
# would still collect QtNetwork normally (unlike a global --exclude-module).
excludedimports = ["PySide6.QtNetwork"]
hiddenimports = []
binaries = []
if pyside6_library_info.version is not None:
    hiddenimports = ["shiboken6", "inspect", "PySide6.support.deprecated"]
    binaries = [
        item for item in pyside6_library_info.collect_extra_binaries()
        if Path(item[0]).name.lower() != "opengl32sw.dll"
    ]
