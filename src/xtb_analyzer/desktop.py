"""Desktop window: choose an XTB history zip and show the HTML report.

Windows: double-click ``xtb-analyzer.bat`` or run ``pythonw -m xtb_analyzer.desktop``.
The same calculations as ``python -m xtb_analyzer`` run locally. The report opens
in the application window (WebView2 on Windows, WebKit on Linux), not in a browser.
"""

from __future__ import annotations

import argparse
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
        self.no_live = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Wybierz albo upuść archiwum ZIP z historią kont.")
        self.report_path: Path | None = None
        self._busy = False
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
            text="Upuść ZIP z historią kont (USD, EUR, a w przyszłości także PLN).\n"
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
            pady=36,
        )
        drop.pack(fill="x")
        self._enable_drop(drop)

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
        tk.Checkbutton(
            row,
            text="bez pobierania bieżących notowań",
            variable=self.no_live,
            bg=BG,
            fg=MUTED,
            selectcolor=CARD,
            activebackground=BG,
            activeforeground=FG,
            font=("Segoe UI", 10),
        ).pack(side="left")

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
        try:
            paths = self.root.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]
        files = [path for path in paths if str(path).lower().endswith(".zip")]
        if not files:
            self.status.set("Upuść plik .zip z historią kont XTB.")
            return
        self._start(files[0])

    def _browse(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="Historia kont XTB",
            filetypes=[("Archiwum ZIP", "*.zip"), ("Wszystkie pliki", "*.*")],
        )
        if path:
            self._start(path)

    def _start(self, path: str) -> None:
        if self._busy:
            return
        self._busy = True
        currency = self.currency.get()
        refresh_latest = not bool(self.no_live.get())
        self.status.set("Liczenie statystyk, porównań i benchmarków…")

        def work() -> None:
            try:
                report = self.load_zip(path, currency=currency, refresh_latest=refresh_latest, present=False)
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
    parser.add_argument("--no-live", action="store_true", help="nie pobieraj bieżących notowań")
    parser.add_argument("--zip", dest="zip_path", default=None, help="od razu otwórz ten plik ZIP")
    args = parser.parse_args(argv)

    app = AnalyzerApp()
    app.currency.set(args.currency)
    app.no_live.set(args.no_live)
    if args.zip_path:
        app.root.after(200, lambda: app._start(args.zip_path))
    app.root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
