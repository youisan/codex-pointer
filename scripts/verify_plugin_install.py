"""Install a release ZIP in an isolated Codex home and discover its real MCP tools.

This catches plugin manifest/relative-command errors that a direct host handshake
cannot. It never opens the GUI, creates a chat, reads account auth, or sends a task.
Requires a native Codex CLI with portable plugin manifest support.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from codex_pointer import __version__
from codex_pointer.bridge import _RpcConnection, discover_codex


EXPECTED_TOOLS = {
    "read_capture", "pointer_launcher", "pointer_status", "show_pointer", "hide_pointer",
}
LAUNCHER_URI = "ui://codex-pointer/launcher.html"


def extract_release(archive_path: Path, destination: Path) -> Path:
    """Validate every archive member before extracting anything."""
    destination = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        seen: set[str] = set()
        marketplace_paths: list[Path] = []
        for item in archive.infolist():
            # Backslashes also separate paths on the platform running the release.
            name = item.filename.replace("\\", "/")
            relative = PurePosixPath(name)
            if (not name or "\x00" in name or ":" in name or relative.is_absolute()
                    or ".." in relative.parts):
                raise RuntimeError(f"Unsafe ZIP entry: {item.filename!r}")
            if stat.S_ISLNK(item.external_attr >> 16):
                raise RuntimeError(f"ZIP symlinks are not supported: {item.filename!r}")
            target = destination.joinpath(*relative.parts).resolve()
            if not target.is_relative_to(destination) or target == destination:
                raise RuntimeError(f"ZIP entry escapes extraction directory: {item.filename!r}")
            identity = str(target).casefold()
            if identity in seen:
                raise RuntimeError(f"Duplicate ZIP destination: {item.filename!r}")
            seen.add(identity)
            if relative.parts[-3:] == (".agents", "plugins", "marketplace.json"):
                marketplace_paths.append(target)
        if len(marketplace_paths) != 1:
            raise RuntimeError("Release ZIP must contain exactly one local marketplace")
        # Use the validated platform-normalized paths, including on ZIPs produced
        # by Windows tooling. No archive member is used as a shell command.
        for item in archive.infolist():
            target = destination.joinpath(*PurePosixPath(item.filename.replace("\\", "/")).parts)
            if item.is_dir() or item.filename.endswith(("/", "\\")):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    return marketplace_paths[0].parents[2]


@contextmanager
def isolated_codex_home(home: Path):
    # _RpcConnection inherits its process's environment. This change is scoped
    # to this verification process and restored before leaving the context.
    previous = os.environ.get("CODEX_HOME")
    os.environ["CODEX_HOME"] = str(home)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = previous


def run_cli(codex: str, arguments: list[str], home: Path) -> None:
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    result = subprocess.run(
        [codex, *arguments], env=dict(os.environ, CODEX_HOME=str(home)),
        shell=False, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=60, **options,
    )
    if result.returncode:
        message = (result.stderr or result.stdout).strip()[-2000:]
        raise RuntimeError(f"Isolated Codex plugin command failed: {message}")


def verify(archive_path: Path, codex: str) -> None:
    if not archive_path.is_file():
        raise RuntimeError(f"Release ZIP is missing: {archive_path}")
    # Spaces deliberately exercise relative command handling after installation.
    with tempfile.TemporaryDirectory(prefix="codex pointer install ") as temporary:
        root = Path(temporary)
        home = root / "isolated codex home"
        home.mkdir()
        marketplace = extract_release(archive_path, root / "release with spaces")
        manifest = json.loads((marketplace / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
        marketplace_name = manifest["name"]
        if not isinstance(marketplace_name, str) or not marketplace_name:
            raise RuntimeError("Marketplace name is missing")
        run_cli(codex, ["plugin", "marketplace", "add", str(marketplace), "--json"], home)
        run_cli(codex, ["plugin", "add", f"codex-pointer@{marketplace_name}", "--json"], home)
        with isolated_codex_home(home):
            with _RpcConnection([codex, "app-server"], timeout=30) as connection:
                catalog = connection.request("mcpServerStatus/list", {
                    "serverName": "codex-pointer", "detail": "toolsAndAuthOnly", "limit": 100,
                })
                servers = [server for server in catalog.get("data", [])
                           if server.get("name") == "codex-pointer"]
                if len(servers) != 1:
                    raise RuntimeError("Installed Pointer MCP server was not discovered")
                server = servers[0]
                if server.get("toolsError"):
                    raise RuntimeError(f"Installed Pointer MCP failed: {server['toolsError']}")
                tools = server.get("tools", {})
                if not isinstance(tools, dict) or set(tools) != EXPECTED_TOOLS:
                    raise RuntimeError(f"Expected five installed Pointer tools; found {list(tools)}")
                launcher = tools["pointer_launcher"]
                metadata = launcher.get("_meta", {})
                if metadata.get("ui", {}).get("resourceUri") != LAUNCHER_URI:
                    raise RuntimeError("Installed launcher UI resource URI is missing")
                if metadata.get("openai/ui", {}).get("entrypoints") != [{"type": "global"}]:
                    raise RuntimeError("Installed launcher global entrypoint is missing")
                for tool in ("pointer_launcher", "pointer_status"):
                    if tools[tool].get("annotations", {}).get("readOnlyHint") is not True:
                        raise RuntimeError(f"Installed {tool} must remain read-only")
        print("Installed plugin: isolated ZIP install, five MCP tools and global launcher metadata passed.")
        print("No GUI launch, screen capture, account login or Codex task was performed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=(
        PROJECT_ROOT / f"dist/v{__version__}/codex-pointer-{__version__}-windows-x64.zip"))
    parser.add_argument("--codex", help="Path to a compatible native codex.exe (not a shell wrapper)")
    arguments = parser.parse_args()
    try:
        verify(arguments.archive.resolve(), discover_codex(arguments.codex))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Plugin install verification failed: {error}\n")


if __name__ == "__main__":
    main()
