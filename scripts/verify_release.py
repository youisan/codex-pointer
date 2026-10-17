"""Verify frozen release behavior with synthetic context and offscreen widgets."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from codex_pointer import __version__


def png_fixture():
    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x18\x18\x18")) + chunk(b"IEND", b""))


def verify(dist):
    host = dist / "CodexPointerHost.exe"
    gui = dist / "CodexPointer.exe"
    portable = dist / "portable/CodexPointer/CodexPointer.exe"
    for path in (host, gui, portable):
        if not path.is_file():
            raise RuntimeError(f"Missing release executable: {path.name}")
    with tempfile.TemporaryDirectory(prefix="codex-pointer-release-") as tmp:
        root = Path(tmp)
        cache = root / "CodexPointer/captures"
        cache.mkdir(parents=True)
        identifier = str(uuid.uuid4())
        image = cache / "synthetic.png"
        image.write_bytes(png_fixture())
        (cache / f"{identifier}.json").write_text(json.dumps({
            "id": identifier, "created_at": time.time(),
            "target": {"title": "合成检查对象"}, "image": str(image),
        }, ensure_ascii=False), encoding="utf-8")
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "read_capture", "arguments": None}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "read_capture", "arguments": {"capture_id": identifier}}},
            {"jsonrpc": "2.0", "id": 5, "method": "resources/list"},
            {"jsonrpc": "2.0", "id": 6, "method": "resources/read", "params": {"uri": "ui://codex-pointer/launcher.html"}},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "pointer_status", "arguments": {}}},
        ]
        result = subprocess.run([str(host), "--mcp"], input="".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requests),
            capture_output=True, encoding="utf-8", env=dict(os.environ, LOCALAPPDATA=tmp), timeout=30, check=True)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        assert len(replies) == 7
        assert replies[0]["result"]["serverInfo"]["version"] == __version__
        assert replies[1]["result"]["tools"][0]["name"] == "read_capture"
        assert replies[2]["result"]["isError"]
        assert not replies[3]["result"]["isError"]
        assert replies[3]["result"]["content"][1]["type"] == "image"
        launcher = next(tool for tool in replies[1]["result"]["tools"] if tool["name"] == "pointer_launcher")
        assert launcher["_meta"]["openai/ui"]["entrypoints"] == [{"type": "global"}]
        for tool in replies[1]["result"]["tools"]:
            assert {item["theme"] for item in tool["icons"]} == {"light", "dark"}
            assert all(item["src"].startswith("data:image/svg+xml;") for item in tool["icons"])
        assert replies[4]["result"]["resources"][0]["uri"] == "ui://codex-pointer/launcher.html"
        resource = replies[5]["result"]["contents"][0]
        assert resource["mimeType"] == "text/html;profile=mcp-app"
        assert "ui/initialize" in resource["text"] and "show_pointer" in resource["text"]
        assert not replies[6]["result"]["isError"]
        assert isinstance(replies[6]["result"]["structuredContent"]["running"], bool)
        print("Frozen MCP: version, handshake, recovery, UTF-8, image, global launcher and readonly status passed.")
        for executable in (gui, portable):
            output = root / ("standalone.png" if executable == gui else "portable.png")
            subprocess.run([str(executable), "--render-preview", str(output), "--theme", "light"],
                env=dict(os.environ, QT_QPA_PLATFORM="offscreen"), timeout=40, check=True)
            data = output.read_bytes()
            assert data.startswith(b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", data[16:24])
            assert width == 488 and 420 <= height <= 540, (width, height)
        print("Frozen GUI: standalone and portable offscreen rendering passed.")
    archives = sorted(dist.glob("codex-pointer-*-windows-x64.zip"))
    if len(archives) != 1:
        raise RuntimeError("Expected exactly one versioned plugin ZIP")
    with zipfile.ZipFile(archives[0]) as archive:
        assert archive.testzip() is None
        paths = archive.namelist()
        for suffix in [".agents/plugins/marketplace.json", "plugins/codex-pointer/plugin.json",
                       "plugins/codex-pointer/mcp.json", "plugins/codex-pointer/bin/CodexPointer.exe",
                       "plugins/codex-pointer/bin/CodexPointerHost.exe", "THIRD_PARTY_NOTICES.txt",
                       "THIRD_PARTY_LICENSES/LGPL-3.0.txt", "docs/preview-light.png", "docs/preview-dark.png"]:
            assert any(p.endswith(suffix) for p in paths), suffix
        manifest_path = next(p for p in paths if p.endswith("plugins/codex-pointer/plugin.json"))
        manifest = json.loads(archive.read(manifest_path))
        assert manifest["version"] == __version__
        interface = manifest["extensions"]["com.openai"]["interface"]
        plugin_root = manifest_path.rsplit("/", 1)[0]
        for name in ("composerIcon", "composerIconDark", "logo", "logoDark"):
            data = archive.read(plugin_root + "/" + interface[name].removeprefix("./"))
            assert data.startswith(b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", data[16:24])
            assert width == height and width >= 48
        config_path = next(p for p in paths if p.endswith("plugins/codex-pointer/mcp.json"))
        assert json.loads(archive.read(config_path))["mcpServers"]["codex-pointer"]["command"] == "./bin/CodexPointerHost.exe"
        assert any("_internal/PySide6/Qt6Core.dll" in p for p in paths)
        for unwanted in ["qtvirtualkeyboard", "qt6virtualkeyboard", "qt6pdf", "imageformats/qpdf"]:
            assert not any(unwanted in p.lower() for p in paths), unwanted
    print("Release ZIP: CRC, marketplace, portable Qt runtime, previews and notices passed.")
    print("No real screen capture or Codex task was performed.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=Path(__file__).resolve().parents[1] / f"dist/v{__version__}")
    args = parser.parse_args()
    verify(args.dist.resolve())


if __name__ == "__main__":
    main()
