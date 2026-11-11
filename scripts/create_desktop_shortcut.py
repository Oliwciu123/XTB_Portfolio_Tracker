"""Create or refresh a Windows Desktop shortcut (.lnk) for the locally built app.

Usage on Windows (from the repository root):
    uv run python scripts/create_desktop_shortcut.py
    uv run python scripts/create_desktop_shortcut.py --build-if-missing
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXE = ROOT / "dist" / "XTBPortfolioAnalyzer" / "XTBPortfolioAnalyzer.exe"
SOURCE_ICON = ROOT / "src" / "xtb_analyzer" / "assets" / "app.ico"
SHORTCUT_NAME = "XTB Portfolio Analyzer.lnk"
DESCRIPTION = "XTB Portfolio Analyzer — Interactive Portfolio & PIT-38 Tracker"


def _ps_quote(text: str) -> str:
    """Single-quote escape a string literal for PowerShell."""
    return "'" + text.replace("'", "''") + "'"


def resolve_windows_desktop() -> Path:
    """Resolve the active Windows Desktop folder (handles OneDrive / localized Pulpit)."""
    if sys.platform != "win32":
        return Path.home() / "Desktop"
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "[Environment]::GetFolderPath('Desktop')",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    resolved = completed.stdout.strip()
    if not resolved:
        return Path.home() / "Desktop"
    return Path(resolved)


def build_powershell_shortcut_script(
    shortcut_path: Path,
    exe_path: Path,
    working_dir: Path,
    icon_path: Path,
    description: str = DESCRIPTION,
) -> str:
    return (
        "$ErrorActionPreference = 'Stop'; "
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$sc = $ws.CreateShortcut({_ps_quote(str(shortcut_path))}); "
        f"$sc.TargetPath = {_ps_quote(str(exe_path))}; "
        f"$sc.WorkingDirectory = {_ps_quote(str(working_dir))}; "
        f"$sc.IconLocation = {_ps_quote(f'{icon_path},0')}; "
        f"$sc.Description = {_ps_quote(description)}; "
        "$sc.Save()"
    )


def create_shortcut(
    *,
    exe_path: Path = DEFAULT_EXE,
    desktop_dir: Path | None = None,
    shortcut_name: str = SHORTCUT_NAME,
    build_if_missing: bool = False,
) -> Path:
    if sys.platform != "win32":
        raise SystemExit("Windows Desktop shortcuts (.lnk) can only be created on Windows (win32).")

    exe_path = exe_path.resolve()
    if not exe_path.is_file() and build_if_missing:
        print("Local executable not found; building dist\\XTBPortfolioAnalyzer first...")
        subprocess.run(
            [
                "uv",
                "run",
                "--locked",
                "--extra",
                "desktop",
                "--extra",
                "build",
                "python",
                str(ROOT / "packaging" / "build_release.py"),
            ],
            cwd=ROOT,
            check=True,
        )

    if not exe_path.is_file():
        raise FileNotFoundError(
            f"Executable not found at {exe_path}.\n"
            "Build it first with `build_windows.bat` or pass `--build-if-missing`."
        )

    app_dir = exe_path.parent
    bundled_icon = app_dir / "app.ico"
    if not bundled_icon.is_file() and SOURCE_ICON.is_file():
        shutil.copy2(SOURCE_ICON, bundled_icon)
    icon_target = bundled_icon if bundled_icon.is_file() else exe_path

    target_desktop = (desktop_dir or resolve_windows_desktop()).resolve()
    target_desktop.mkdir(parents=True, exist_ok=True)
    shortcut_path = target_desktop / shortcut_name

    ps_script = build_powershell_shortcut_script(
        shortcut_path=shortcut_path,
        exe_path=exe_path,
        working_dir=app_dir,
        icon_path=icon_target,
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        check=True,
    )
    return shortcut_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--exe",
        type=Path,
        default=DEFAULT_EXE,
        help="Path to XTBPortfolioAnalyzer.exe (default: dist/XTBPortfolioAnalyzer/XTBPortfolioAnalyzer.exe)",
    )
    parser.add_argument(
        "--desktop-dir",
        type=Path,
        default=None,
        help="Override destination folder (defaults to the active Windows Desktop)",
    )
    parser.add_argument(
        "--build-if-missing",
        action="store_true",
        help="Run the PyInstaller Windows build automatically if the local exe is missing",
    )
    args = parser.parse_args(argv)
    try:
        shortcut = create_shortcut(
            exe_path=args.exe,
            desktop_dir=args.desktop_dir,
            build_if_missing=args.build_if_missing,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Desktop shortcut ready: {shortcut}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
