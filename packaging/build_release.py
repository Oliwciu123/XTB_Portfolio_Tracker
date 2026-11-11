"""Build and package only application binaries, never uploaded histories or caches."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _build_macos_icns() -> None:
    """Create build/app.icns from app.png on macOS if sips and iconutil are available."""
    png = ROOT / "src" / "xtb_analyzer" / "assets" / "app.png"
    if not png.is_file():
        return
    iconset = ROOT / "build" / "app.iconset"
    icns = ROOT / "build" / "app.icns"
    try:
        if iconset.exists():
            shutil.rmtree(iconset)
        iconset.mkdir(parents=True, exist_ok=True)
        for size in (16, 32, 128, 256, 512):
            subprocess.run(
                [
                    "sips",
                    "-z",
                    str(size),
                    str(size),
                    str(png),
                    "--out",
                    str(iconset / f"icon_{size}x{size}.png"),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                [
                    "sips",
                    "-z",
                    str(size * 2),
                    str(size * 2),
                    str(png),
                    "--out",
                    str(iconset / f"icon_{size}x{size}@2x.png"),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], check=True)
    except Exception:
        icns.unlink(missing_ok=True)


def _write_sha256(archive: Path) -> None:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"Built: {archive} ({archive.stat().st_size / 1024**2:.1f} MB)")


def _package_windows() -> Path:
    app = ROOT / "dist" / "XTBPortfolioAnalyzer"
    shutil.copy2(ROOT / "docs" / "USER_GUIDE.md", app / "START.md")
    shutil.copy2(ROOT / "LICENSE", app / "LICENSE")
    ico = ROOT / "src" / "xtb_analyzer" / "assets" / "app.ico"
    if ico.is_file():
        shutil.copy2(ico, app / "app.ico")
    archive = ROOT / "dist" / "XTBPortfolioAnalyzer-Windows.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(app.rglob("*")):
            if path.is_file():
                relative = path.relative_to(app)
                if relative.parts[0] == "_internal" or relative.as_posix() in (
                    "XTBPortfolioAnalyzer.exe",
                    "START.md",
                    "LICENSE",
                    "app.ico",
                ):
                    z.write(path, Path(app.name) / relative)
    _write_sha256(archive)
    return archive


def _package_macos() -> Path:
    app_bundle = ROOT / "dist" / "XTBPortfolioAnalyzer.app"
    if not app_bundle.is_dir():
        raise RuntimeError(f"Expected macOS app bundle at {app_bundle}")

    stage_root = ROOT / "build" / "macos_stage"
    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_dir = stage_root / "XTBPortfolioAnalyzer"
    stage_dir.mkdir(parents=True, exist_ok=True)

    # Copy strictly the .app bundle and documentation files, preserving framework symlinks.
    shutil.copytree(app_bundle, stage_dir / "XTBPortfolioAnalyzer.app", symlinks=True)
    shutil.copy2(ROOT / "docs" / "USER_GUIDE.md", stage_dir / "START.md")
    shutil.copy2(ROOT / "LICENSE", stage_dir / "LICENSE")

    archive = ROOT / "dist" / "XTBPortfolioAnalyzer-macOS.zip"
    archive.unlink(missing_ok=True)
    subprocess.run(
        [
            "/usr/bin/ditto",
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            str(stage_dir),
            str(archive),
        ],
        check=True,
    )
    shutil.rmtree(stage_root, ignore_errors=True)
    _write_sha256(archive)
    return archive


def main() -> None:
    if sys.platform not in ("win32", "darwin"):
        raise SystemExit("Build portable desktop archives on Windows (win32) or macOS (darwin).")

    if sys.platform == "darwin":
        _build_macos_icns()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            str(ROOT / "packaging" / "xtb_portfolio_analyzer.spec"),
        ],
        cwd=ROOT,
        check=True,
    )

    if sys.platform == "win32":
        _package_windows()
    else:
        _package_macos()


if __name__ == "__main__":
    main()
