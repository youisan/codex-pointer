"""Small stdlib-only executable entry point for the context MCP server.

Keep this separate from the GUI entry point so PyInstaller never discovers Qt
while building CodexPointerHost.exe. This process is started hidden by Codex.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex Pointer context MCP host")
    parser.add_argument("--mcp", action="store_true", help="Serve MCP over stdio (the default)")
    parser.add_argument("--diagnose", action="store_true", help="Check Codex availability without sending a task")
    args = parser.parse_args()
    if args.diagnose:
        from codex_pointer.bridge import CodexBridge
        print(CodexBridge().diagnostics())
        return
    from codex_pointer.mcp_server import serve
    serve()


if __name__ == "__main__":
    main()
