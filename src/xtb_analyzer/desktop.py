"""Desktop window: choose an XTB history zip and show the HTML report.

Windows: double-click ``xtb-analyzer.bat`` or run ``pythonw -m xtb_analyzer.desktop``.
The same calculations as ``python -m xtb_analyzer`` run locally. The report opens
in the application window (WebView2 on Windows, WebKit on Linux), not in a browser.
"""

from __future__ import annotations

import argparse
import re
import sys
import threading
import uuid
from pathlib import Path

from xtb_analyzer.parser import find_project_root
from xtb_analyzer.session import report_from_zip_path
from xtb_analyzer.zip_import import ZipImportError

BG = "#0f1419"
CARD = "#1a2332"
FG = "#e7ecf1"
MUTED = "#b7c3d1"
ACCENT = "#2f6fed"
_BRACED_PATH = re.compile(r"\{([^{}]+)\}")
_QUOTED_OR_TOKEN = re.compile(r'"[^"]+"|\S+')


def parse_dropped_paths(data: str) -> list[str]:
    """File paths from a Windows or Linux drag-and-drop payload."""
    text = str(data or "").strip()
    if not text:
        return []
    braced = [match.strip().strip('"') for match in _BRACED_PATH.findall(text)]
    if braced:
        candidates = braced
    else:
        candidates = [match.strip().strip('"') for match in _QUOTED_OR_TOKEN.findall(text)]
    return [path for path in candidates if path.lower().endswith(".zip")]


def _asset_dir() -> Path:
    return Path(__file__).resolve().parent / "assets"


def apply_window_icon(root) -> None:
    """Title-bar icon. Windows uses the .ico; other systems use the PNG."""
    ico = _asset_dir() / "app.ico"
    png = _asset_dir() / "app.png"
    if sys.platform == "win32" and ico.is_file():
        try:
            root.iconbitmap(default=str(ico))
            return
        except Exception:
            pass
    if not png.is_file():
        return
    try:
        import tkinter as tk

        image = tk.PhotoImage(file=str(png))
        root.iconphoto(True, image)
        root._xtb_icon = image  # keep a reference; Tk drops the image otherwise
    except Exception:
        return


def _prepare_webview():
    """Import pywebview, and on Linux find the apt-installed WebKit bindings."""
    system_site = Path("/usr/lib/python3/dist-packages")
    if system_site.is_dir() and str(system_site) not in sys.path:
        sys.path.append(str(system_site))
    import webview

    gui = None
    if sys.platform.startswith("linux"):
        try:
            import gi  # noqa: F401

            gui = "gtk"
        except Exception:
            gui = None
    return webview, gui


def open_report_window(html_path: Path) -> None:
    """Show ``html_path`` in a native window."""
    webview, gui = _prepare_webview()
    webview.create_window(
        "Raport portfela XTB",
        url=html_path.resolve().as_uri(),
        width=1280,
        height=860,
        min_size=(900, 640),
        background_color=BG,
    )
    if gui:
        webview.start(gui=gui)
    else:
        webview.start()


class AnalyzerApp:
    """Zip picker. ``load_zip(..., present=False)`` is for tests."""

    def __init__(self, root=None):
        import tkinter as tk
        from tkinter import ttk

        self._tk = tk
        self._ttk = ttk
        if root is None:
            root = self._make_root()
        self.root = root
        self.root.title("Analizator portfela XTB")
        self.root.configure(bg=BG)
        self.root.geometry("680x460")
        self.root.minsize(560, 400)
        self.currency = tk.StringVar(value="pln")
        self.zip_path = tk.StringVar(value="")
        self.status = tk.StringVar(value="Wybierz albo upuść archiwum ZIP z historią kont.")
        self.report_path: Path | None = None
        self._busy = False
        self.progress = None
        apply_window_icon(self.root)
        self._build()

    def _make_root(self):
        try:
            from tkinterdnd2 import TkinterDnD

            return TkinterDnD.Tk()
        except Exception:
            import tkinter as tk

            return tk.Tk()

    def _build(self) -> None:
        tk = self._tk
        outer = tk.Frame(self.root, bg=BG, padx=28, pady=24)
        outer.pack(fill="both", expand=True)
        tk.Label(
            outer,
            text="Raport portfela XTB",
            bg=BG,
            fg=FG,
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w")
        tk.Label(
            outer,
            text="Upuść ZIP z historią kont.\n"
            "Po przeliczeniu zobaczysz pełny raport w tym programie.",
            bg=BG,
            fg=MUTED,
            justify="left",
            font=("Segoe UI", 11),
        ).pack(anchor="w", pady=(6, 16))

        drop = tk.Label(
            outer,
            text="Upuść plik ZIP tutaj",
            bg=CARD,
            fg=FG,
            font=("Segoe UI", 13),
            relief="groove",
            bd=1,
            padx=16,
            pady=28,
        )
        drop.pack(fill="x")
        self._drop_label = drop
        self._enable_drop(drop)

        field = tk.Entry(
            outer,
            textvariable=self.zip_path,
            readonlybackground=CARD,
            fg=FG,
            bg=CARD,
            insertbackground=FG,
            relief="flat",
            font=("Segoe UI", 10),
        )
        field.configure(state="readonly")
        field.pack(fill="x", pady=(10, 0), ipady=6)
        self._enable_drop(field)
        self._enable_drop(outer)
        self._enable_drop(self.root)

        tk.Button(
            outer,
            text="Wybierz archiwum ZIP",
            command=self._browse,
            bg=ACCENT,
            fg="white",
            activebackground="#2459c4",
            activeforeground="white",
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            padx=14,
            pady=8,
            cursor="hand2",
        ).pack(anchor="w", pady=(16, 8))

        row = tk.Frame(outer, bg=BG)
        row.pack(anchor="w", pady=(4, 0))
        tk.Label(row, text="Waluta raportu", bg=BG, fg=FG, font=("Segoe UI", 10)).pack(side="left")
        menu = tk.OptionMenu(row, self.currency, "pln", "usd", "eur")
        menu.configure(bg=CARD, fg=FG, highlightthickness=0, font=("Segoe UI", 10))
        menu.pack(side="left", padx=(8, 16))

        style = self._ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "Xtb.Horizontal.TProgressbar",
            troughcolor=CARD,
            background=ACCENT,
            bordercolor=CARD,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
        )
        self.progress = self._ttk.Progressbar(
            outer,
            style="Xtb.Horizontal.TProgressbar",
            mode="determinate",
            maximum=100,
        )
        self.progress.pack(fill="x", pady=(16, 0))

        tk.Label(
            outer,
            textvariable=self.status,
            bg=BG,
            fg=MUTED,
            wraplength=600,
            justify="left",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(18, 0))

    def _enable_drop(self, widget) -> None:
        try:
            from tkinterdnd2 import DND_FILES
        except Exception:
            return
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            return

    def _on_drop(self, event) -> None:
        raw = getattr(event, "data", "")
        try:
            listed = [str(path) for path in self.root.tk.splitlist(raw)]
        except Exception:
            listed = []
        files = parse_dropped_paths(raw)
        for path in listed:
            files.extend(parse_dropped_paths(path))
        # Preserve order, drop duplicates.
        seen: list[str] = []
        for path in files:
            if path not in seen:
                seen.append(path)
        if not seen:
            self.status.set("Upuść plik .zip z historią kont XTB.")
            return
        self._choose(seen[0])

    def _browse(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="Historia kont XTB",
            filetypes=[("Archiwum ZIP", "*.zip"), ("Wszystkie pliki", "*.*")],
        )
        if path:
            self._choose(path)

    def _choose(self, path: str) -> None:
        self.zip_path.set(str(path))
        self._drop_label.configure(text=Path(path).name)
        self._start(path)

    def _set_progress(self, fraction: float, message: str) -> None:
        if self.progress is not None:
            self.progress["value"] = max(0, min(100, int(fraction * 100)))
        self.status.set(message)

    def _start(self, path: str) -> None:
        if self._busy:
            return
        self._busy = True
        currency = self.currency.get()
        self._set_progress(0.02, "Liczenie statystyk, porównań i benchmarków…")

        def on_progress(fraction: float, message: str) -> None:
            self.root.after(0, lambda: self._set_progress(fraction, message))

        def work() -> None:
            try:
                report = self.load_zip(
                    path,
                    currency=currency,
                    refresh_latest=True,
                    present=False,
                    on_progress=on_progress,
                )
            except Exception as exc:  # noqa: BLE001 — show the message in the window
                self.root.after(0, lambda: self._fail(exc))
                return
            self.root.after(0, lambda: self._present(report))

        threading.Thread(target=work, daemon=True).start()

    def load_zip(
        self,
        path: str | Path,
        *,
        currency: str = "pln",
        use_cache: bool = True,
        refresh_latest: bool = True,
        present: bool = False,
        upload_root: Path | None = None,
        on_progress=None,
    ) -> Path:
        path = Path(path)
        if path.suffix.lower() != ".zip":
            raise ZipImportError("Wybierz archiwum .zip z historią kont XTB.")
        root = upload_root or (find_project_root() / "data" / "uploads")
        work = root / uuid.uuid4().hex
        report = report_from_zip_path(
            path,
            work,
            currency=currency,
            use_cache=use_cache,
            refresh_latest=refresh_latest,
            on_progress=on_progress,
        )
        self.report_path = report
        if present:
            self._present(report)
        return report

    def _present(self, report: Path) -> None:
        self._busy = False
        self.report_path = report
        self.status.set("Otwieram raport…")
        self.root.update_idletasks()
        try:
            self.root.withdraw()
            open_report_window(report)
        except Exception as exc:  # noqa: BLE001
            self.root.deiconify()
            self._fail(exc)
            return
        self.root.destroy()

    def _fail(self, exc: BaseException) -> None:
        self._busy = False
        if self.progress is not None:
            self.progress["value"] = 0
        message = str(exc).strip() or exc.__class__.__name__
        self.status.set(message)
        try:
            from tkinter import messagebox

            messagebox.showerror("Nie udało się policzyć raportu", message)
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xtb_analyzer.desktop",
        description="Okno aplikacji: wgraj ZIP z historią XTB i zobacz raport.",
    )
    parser.add_argument("--currency", default="pln", choices=["pln", "usd", "eur"])
    parser.add_argument("--zip", dest="zip_path", default=None, help="od razu otwórz ten plik ZIP")
    args = parser.parse_args(argv)

    app = AnalyzerApp()
    app.currency.set(args.currency)
    if args.zip_path:
        app.root.after(200, lambda: app._start(args.zip_path))
    app.root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
