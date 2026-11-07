# -*- mode: python ; coding: utf-8 -*-
# PyInstaller one-folder build for the Windows desktop app.
# Build on Windows:  build_windows.bat
# Output:            dist\XTBPortfolioAnalyzer\

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None
ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
ASSETS = SRC / "xtb_analyzer" / "assets"

datas = [
    (str(ASSETS / "app.ico"), "xtb_analyzer/assets"),
    (str(ASSETS / "app.png"), "xtb_analyzer/assets"),
]
# Explicitly bundle only the fictional demo, never the private data/ directory.
datas += [
    (str(ROOT / "examples" / name), "examples")
    for name in (
        "XTB_USD_cs.xlsx", "XTB_EUR_cs.xlsx", "prices.csv", "fx.csv", "benchmarks.csv",
        "instruments.csv", "benchmark_metadata.csv", "demo.json",
    )
]
binaries = []
hiddenimports = [
    "webview",
    "webview.platforms.edgechromium",
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinterdnd2",
    "openpyxl",
    "pyarrow",
    "yfinance",
    "plotly",
    "pandas",
    "numpy",
    "requests",
]

for package in ("webview", "tkinterdnd2", "plotly", "yfinance", "certifi"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        datas += collect_data_files(package)

a = Analysis(
    [str(ROOT / "run_desktop.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["notebook", "ipykernel", "ipywidgets", "matplotlib", "pytest", "IPython", "scipy", "sympy"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="XTBPortfolioAnalyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ASSETS / "app.ico") if (ASSETS / "app.ico").is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="XTBPortfolioAnalyzer",
)
