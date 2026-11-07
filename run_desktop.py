"""Entry point for the portable Windows desktop build (PyInstaller)."""

from __future__ import annotations

from xtb_analyzer.desktop import main
from xtb_analyzer.paths import ensure_app_cwd

if __name__ == "__main__":
    ensure_app_cwd()
    raise SystemExit(main())
