"""Collect the raster widget app's Qt plugins before dependency analysis.

QtGui's default hook collects every installed image and input plugin. That can
pull Qt PDF, Quick and the GPL-only Virtual Keyboard into a simple QWidget app.
Use PyInstaller's normal Qt dependency collector with a temporary plugin policy
instead; all chosen plugins still receive its normal validity checks.
"""
from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info


_PLUGIN_NAMES = {
    "platforms": {"qwindows.dll", "qoffscreen.dll"},
    "imageformats": {"qico.dll", "qjpeg.dll"},
}
_original_collect_plugins = pyside6_library_info.collect_plugins


def _collect_widget_plugins(plugin_type):
    allowed = _PLUGIN_NAMES.get(plugin_type)
    if not allowed:
        return []
    return [
        item for item in _original_collect_plugins(plugin_type)
        if Path(item[0]).name.lower() in allowed
    ]


pyside6_library_info.collect_plugins = _collect_widget_plugins
try:
    hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
finally:
    pyside6_library_info.collect_plugins = _original_collect_plugins
