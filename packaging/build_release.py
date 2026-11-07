"""Build and package only application binaries, never uploaded histories or caches."""

import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Build the portable Windows archive on Windows.")
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
    app = ROOT / "dist" / "XTBPortfolioAnalyzer"
    shutil.copy2(ROOT / "docs" / "USER_GUIDE.md", app / "START.md")
    shutil.copy2(ROOT / "LICENSE", app / "LICENSE")
    archive = ROOT / "dist" / "XTBPortfolioAnalyzer-Windows.zip"
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
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"Built: {archive} ({archive.stat().st_size / 1024**2:.1f} MB)")


if __name__ == "__main__":
    main()
