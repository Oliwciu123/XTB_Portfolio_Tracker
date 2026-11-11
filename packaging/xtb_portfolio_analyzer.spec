# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build specification for the Windows and macOS desktop app.
# Windows:  build_windows.bat -> dist\XTBPortfolioAnalyzer\
# macOS:    python packaging/build_release.py -> dist/XTBPortfolioAnalyzer.app

import sys
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
        "XTB_USD_cs.xlsx",
        "XTB_EUR_cs.xlsx",
        "prices.csv",
        "fx.csv",
        "benchmarks.csv",
        "instruments.csv",
        "benchmark_metadata.csv",
        "demo.json",
    )
]
binaries = []
if sys.platform == "win32":
    platform_hidden = ["webview.platforms.edgechromium", "clr", "pythonnet", "clr_loader"]
    collect_packages = (
        "webview",
        "pythonnet",
        "clr_loader",
        "tkinterdnd2",
        "plotly",
        "yfinance",
        "certifi",
        "tzdata",
    )
elif sys.platform == "darwin":
    platform_hidden = [
        "webview.platforms.cocoa",
        "objc",
        "Foundation",
        "AppKit",
        "Cocoa",
        "WebKit",
        "Quartz",
        "Security",
        "UniformTypeIdentifiers",
    ]
    collect_packages = ("webview", "tkinterdnd2", "plotly", "yfinance", "certifi", "tzdata")
else:
    platform_hidden = []
    collect_packages = ("webview", "tkinterdnd2", "plotly", "yfinance", "certifi", "tzdata")

hiddenimports = [
    "webview",
    *platform_hidden,
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

for package in collect_packages:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        datas += collect_data_files(package)

if sys.platform == "win32":
    import webview as _webview_mod

    _webview_lib = Path(_webview_mod.__file__).resolve().parent / "lib"
    if _webview_lib.is_dir():
        datas.append((str(_webview_lib), "webview/lib"))

a = Analysis(
    [str(ROOT / "run_desktop.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "notebook",
        "ipykernel",
        "ipywidgets",
        "matplotlib",
        "pytest",
        "IPython",
        "scipy",
        "sympy",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if sys.platform == "win32":
    app_icon = str(ASSETS / "app.ico") if (ASSETS / "app.ico").is_file() else None
elif sys.platform == "darwin":
    icns_file = ROOT / "build" / "app.icns"
    app_icon = str(icns_file) if icns_file.is_file() else None
else:
    app_icon = None

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
    icon=app_icon,
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

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="XTBPortfolioAnalyzer.app",
        icon=app_icon,
        bundle_identifier="io.github.oliwciu123.xtbportfolioanalyzer",
    )
