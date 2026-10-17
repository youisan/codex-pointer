"""Parse one explicit file URL without touching the filesystem.

Existence, type and access checks belong to the controller's background worker.
UNC shares are retained as UNC paths; parsing never connects to the share.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from .i18n import tr


class DropTargetError(ValueError):
    """The drag payload cannot represent one unambiguous local object."""


def parse_local_file_urls(urls: list[str] | tuple[str, ...]) -> str:
    if len(urls) != 1:
        raise DropTargetError(tr("请一次拖入一个文件或文件夹。"))
    url = urls[0]
    if not isinstance(url, str) or not url.lower().startswith("file://"):
        raise DropTargetError(tr("请拖入本地文件或文件夹，不支持网页链接。"))
    if re.search(r"%(?![0-9a-fA-F]{2})", url):
        raise DropTargetError(tr("这个文件地址无效，请重新拖入。"))
    try:
        parts = urlsplit(url)
        path = unquote(parts.path, encoding="utf-8", errors="strict")
        host = unquote(parts.netloc, encoding="utf-8", errors="strict")
    except (ValueError, UnicodeError):
        raise DropTargetError(tr("这个文件地址无效，请重新拖入。")) from None
    if (parts.scheme.lower() != "file" or parts.query or parts.fragment or not path.startswith("/")
            or "\x00" in path or "\x00" in host or any(mark in host for mark in ("@", ":", "/", "\\"))):
        raise DropTargetError(tr("这个文件地址无效，请重新拖入。"))
    if host and host.casefold() != "localhost":
        if path == "/":
            raise DropTargetError(tr("请拖入共享目录中的文件或文件夹。"))
        return "//" + host + path
    if re.match(r"^/[a-zA-Z]:/", path):
        path = path[1:]
    if not path or path == "/":
        raise DropTargetError(tr("请拖入一个文件或文件夹。"))
    return path
