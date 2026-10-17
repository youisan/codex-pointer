"""Source-tree entry point, also used by PyInstaller."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from codex_pointer.__main__ import main

if __name__ == "__main__":
    main()
