"""Writable paths for source runs and frozen (PyInstaller) Windows builds."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Bundled read-only resources (``sys._MEIPASS`` when frozen)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def app_writable_root() -> Path:
    """Per-user application storage when frozen, or the project root in source."""
    if is_frozen():
        from platformdirs import user_data_path

        root = user_data_path("XTBPortfolioAnalyzer", appauthor=False)
        root.mkdir(parents=True, exist_ok=True)
        return root
    from xtb_analyzer.parser import find_project_root

    return find_project_root()


def ensure_app_cwd() -> Path:
    """Resolve relative cache/output paths inside writable application storage."""
    root = app_writable_root()
    try:
        import os

        os.chdir(root)
    except OSError:
        pass
    return root


def asset_path(*parts: str) -> Path:
    base = resource_root()
    if is_frozen():
        candidate = base.joinpath(*parts)
        if candidate.is_file() or candidate.is_dir():
            return candidate
        nested = base.joinpath("xtb_analyzer", *parts)
        if nested.is_file() or nested.is_dir():
            return nested
        return candidate
    return Path(__file__).resolve().parent.joinpath(*parts)
