"""Desktop window: choose an XTB history zip and show the HTML report.

Windows (portable): build once with ``build_windows.bat``, then double-click
``XTBPortfolioAnalyzer.exe`` in the copied folder.
Development: ``python -m xtb_analyzer.desktop``.
The report opens in the application window, not in a browser. Live quotes
are always fetched.
"""

from __future__ import annotations

import argparse
import re
import sys
import threading
import uuid
from pathlib import Path

from xtb_analyzer.paths import (
    app_writable_root,
    asset_path,
    ensure_app_cwd,
    is_frozen,
    resource_root,
)
from xtb_analyzer.session import report_from_zip_path
from xtb_analyzer.zip_import import ZipImportError

# Modern dark slate palette matching the interactive inner report UI
BG = "#0b0f17"
SURFACE = "#111827"
CARD = "#151d2e"
CARD_HOVER = "#1b253b"
BORDER = "#1e293b"
FG = "#f1f5f9"
MUTED = "#94a3b8"
ACCENT = "#3b82f6"
ACCENT_SOFT = "#60a5fa"
ACCENT_ACTIVE = "#2563eb"
ACCENT_HOVER = "#6366f1"
DROP_BG = "#12233b"
DROP_BORDER = "#34547c"
DROP_HOVER_BG = "#1a3452"
DROP_HOVER_BORDER = "#22d3ee"

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


def apply_window_icon(root) -> None:
    """Title-bar icon. Windows uses the .ico; other systems use the PNG."""
    ico = asset_path("assets", "app.ico")
    png = asset_path("assets", "app.png")
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
    """Let pywebview select the native backend for the current platform."""
    import webview

    return webview, None


_DESKTOP_START_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>XTB Portfolio Analyzer</title>
<style>
  * { box-sizing: border-box; }
  html, body {
    margin: 0;
    padding: 0;
    width: 100%;
    height: 100%;
    background: #0B0F17;
    color: #F8FAFC;
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    -webkit-font-smoothing: antialiased;
    user-select: none;
  }
  .start-screen {
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 32px 24px;
  }
  .upload-card {
    width: 100%;
    max-width: 580px;
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  .upload-title {
    margin: 0 0 10px;
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #F8FAFC;
  }
  .upload-subtitle {
    margin: 0 0 28px;
    font-size: 14.5px;
    color: #94A3B8;
    line-height: 1.5;
  }
  .dropzone {
    width: 100%;
    background: #161F30;
    border: 2px dashed #334155;
    border-radius: 16px;
    padding: 40px 28px;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    transition: border-color 0.2s ease, background-color 0.2s ease, transform 0.2s ease;
  }
  .dropzone:hover,
  .dropzone.drag-active {
    border-color: #3B82F6;
    background: #1E293B;
  }
  .dropzone-icon {
    width: 50px;
    height: 50px;
    color: #3B82F6;
    margin-bottom: 14px;
    transition: transform 0.2s ease;
  }
  .dropzone:hover .dropzone-icon,
  .dropzone.drag-active .dropzone-icon {
    transform: translateY(-2px);
  }
  .dropzone-heading {
    margin: 0 0 6px;
    font-size: 18px;
    font-weight: 700;
    color: #F8FAFC;
  }
  .dropzone-hint {
    margin: 0 0 20px;
    font-size: 13.5px;
    color: #94A3B8;
  }
  .dropzone-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: #3B82F6;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 10px 24px;
    font-size: 13.5px;
    font-weight: 600;
    font-family: inherit;
    cursor: pointer;
    box-shadow: 0 4px 14px rgba(59, 130, 246, 0.35);
    transition: background-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
  }
  .dropzone-btn:hover {
    background: #2563EB;
    box-shadow: 0 6px 18px rgba(37, 99, 235, 0.45);
    transform: translateY(-1px);
  }
  .progress-wrap {
    width: 100%;
    margin-top: 24px;
    display: none;
    flex-direction: column;
    align-items: center;
    gap: 10px;
  }
  .progress-wrap.active {
    display: flex;
  }
  .progress-track {
    width: 100%;
    height: 8px;
    background: #0F172A;
    border: 1px solid #334155;
    border-radius: 999px;
    overflow: hidden;
  }
  .progress-bar {
    width: 12%;
    height: 100%;
    background: #3B82F6;
    border-radius: 999px;
    transition: width 0.25s ease;
  }
  .status-text {
    font-size: 13.5px;
    color: #94A3B8;
    margin: 0;
  }
  .status-text.error {
    color: #F87171;
  }
</style>
</head>
<body>
  <div class="start-screen">
    <div class="upload-card">
      <h1 class="upload-title">XTB Portfolio Analyzer</h1>
      <p class="upload-subtitle">Import your account history as a ZIP file to generate a report.</p>

      <input id="file-input" type="file" accept=".zip" style="display:none">
      <div id="dropzone" class="dropzone" role="button" tabindex="0">
        <svg class="dropzone-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/>
          <path d="M12 12v9"/>
          <path d="m16 16-4-4-4 4"/>
        </svg>
        <div id="dropzone-heading" class="dropzone-heading">Drop your history ZIP here</div>
        <div class="dropzone-hint">or click to select a file</div>
        <span class="dropzone-btn">Choose file</span>
      </div>

      <div id="progress-wrap" class="progress-wrap">
        <div class="progress-track">
          <div id="progress-bar" class="progress-bar"></div>
        </div>
        <p id="status-text" class="status-text"></p>
      </div>
    </div>
  </div>
<script>
(function() {
  const dropzone = document.getElementById('dropzone');
  const heading = document.getElementById('dropzone-heading');
  const fileInput = document.getElementById('file-input');
  const progressWrap = document.getElementById('progress-wrap');
  const progressBar = document.getElementById('progress-bar');
  const statusText = document.getElementById('status-text');
  let busy = false;
  let pollTimer = null;

  function showStatus(pct, message, isError) {
    progressWrap.classList.add('active');
    progressBar.style.width = Math.max(6, Math.min(100, pct)) + '%';
    statusText.textContent = message || '';
    statusText.classList.toggle('error', !!isError);
  }

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async function() {
      if (!window.pywebview || !window.pywebview.api || !window.pywebview.api.get_build_status) return;
      try {
        const st = await window.pywebview.api.get_build_status();
        if (!st) return;
        if (st.state === 'running') {
          showStatus(st.progress || 15, st.message || 'Generating report…', false);
        } else if (st.state === 'error') {
          clearInterval(pollTimer);
          pollTimer = null;
          busy = false;
          showStatus(0, st.message || 'Unable to generate the report.', true);
        } else if (st.state === 'done' && st.report_url) {
          clearInterval(pollTimer);
          pollTimer = null;
          showStatus(100, 'Opening report...', false);
          window.location.href = st.report_url;
        }
      } catch (e) {}
    }, 220);
  }

  function handleFileObject(file) {
    if (!file || busy) return;
    if (!file.name.toLowerCase().endsWith('.zip')) {
      showStatus(0, 'Select a .zip archive.', true);
      return;
    }
    busy = true;
    heading.textContent = file.name;
    showStatus(10, 'Loading ' + file.name + '…', false);
    const reader = new FileReader();
    reader.onload = async function(ev) {
      const result = String(ev.target.result || '');
      const b64 = result.includes(',') ? result.split(',')[1] : result;
      if (window.pywebview && window.pywebview.api && window.pywebview.api.start_zip_base64) {
        await window.pywebview.api.start_zip_base64(file.name, b64);
        startPolling();
      }
    };
    reader.readAsDataURL(file);
  }

  dropzone.addEventListener('click', async function() {
    if (busy) return;
    if (window.pywebview && window.pywebview.api && window.pywebview.api.browse_zip_dialog) {
      const res = await window.pywebview.api.browse_zip_dialog();
      if (res && res.started) {
        busy = true;
        if (res.filename) heading.textContent = res.filename;
        showStatus(8, 'Calculating metrics and benchmark comparisons...', false);
        startPolling();
        return;
      }
      if (res && res.cancelled) return;
    }
    fileInput.click();
  });

  fileInput.addEventListener('change', function() {
    if (fileInput.files && fileInput.files.length > 0) {
      handleFileObject(fileInput.files[0]);
    }
  });

  window.addEventListener('dragenter', function(e) {
    e.preventDefault();
    dropzone.classList.add('drag-active');
  });
  window.addEventListener('dragover', function(e) {
    e.preventDefault();
    dropzone.classList.add('drag-active');
  });
  window.addEventListener('dragleave', function(e) {
    if (e.relatedTarget === null) dropzone.classList.remove('drag-active');
  });
  window.addEventListener('drop', function(e) {
    e.preventDefault();
    dropzone.classList.remove('drag-active');
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileObject(e.dataTransfer.files[0]);
    }
  });
})();
</script>
</body>
</html>"""


class _LiveReportBridge:
    """Expose start-screen ZIP loading, live statistics refresh, benchmark simulation, and currency switch to pywebview."""

    def __init__(self, html_path: Path | None = None, currency: str = "pln"):
        self._html_path: Path | None = Path(html_path).resolve() if html_path else None
        self._currency = (currency or "pln").lower()
        self._window = None
        self._build_state = "idle"
        self._build_progress = 0
        self._build_message = ""
        self._report_url = ""
        self._custom_tickers: set[str] = set()
        self._last_data = None
        self._cached_accounts_key: tuple | None = None
        self._cached_accounts: list | None = None
        self._live_lock = threading.Lock()

    def set_window(self, window) -> None:
        self._window = window

    def _data_dir(self) -> Path:
        if self._html_path is not None:
            candidate = self._html_path.parent.parent / "extracted"
            if candidate.is_dir():
                return candidate
        return app_writable_root() / "data"

    def get_build_status(self) -> dict[str, object]:
        return {
            "state": self._build_state,
            "progress": self._build_progress,
            "message": self._build_message,
            "report_url": self._report_url,
        }

    def browse_zip_dialog(self) -> dict[str, object]:
        """Open native file dialog in PyWebView and start building the report in a background thread."""
        if self._build_state == "running":
            return {"started": False, "cancelled": True}
        selected_path: str | None = None
        if self._window is not None:
            try:
                import webview

                file_types = ("ZIP archive (*.zip)", "All files (*.*)")
                dialog_type = getattr(webview, "OPEN_DIALOG", 10)
                result = self._window.create_file_dialog(
                    dialog_type, allow_multiple=False, file_types=file_types
                )
                if result:
                    selected_path = (
                        str(result[0]) if isinstance(result, (list, tuple)) else str(result)
                    )
            except Exception:
                selected_path = None
        if not selected_path:
            return {"started": False, "cancelled": True}
        self.start_zip_path(selected_path)
        return {"started": True, "filename": Path(selected_path).name}

    def start_zip_path(self, zip_path: str | Path) -> dict[str, object]:
        path = Path(zip_path)
        self._build_state = "running"
        self._build_progress = 8
        self._build_message = "Calculating metrics and benchmark comparisons..."

        def on_progress(fraction: float, message: str) -> None:
            self._build_progress = max(5, min(98, int(fraction * 100)))
            self._build_message = message

        def work() -> None:
            try:
                work_dir = app_writable_root() / "data" / "uploads" / uuid.uuid4().hex
                report = report_from_zip_path(
                    path,
                    work_dir,
                    currency=self._currency,
                    use_cache=True,
                    refresh_latest=True,
                    on_progress=on_progress,
                )
                self._html_path = report.resolve()
                self._report_url = self._html_path.as_uri()
                self._build_progress = 100
                self._build_message = "Opening report..."
                self._build_state = "done"
            except Exception as exc:
                self._build_message = str(exc).strip() or exc.__class__.__name__
                self._build_state = "error"

        threading.Thread(target=work, daemon=True).start()
        return {"started": True, "filename": path.name}

    def start_zip_base64(self, filename: str, b64_payload: str) -> dict[str, object]:
        import base64

        from xtb_analyzer.session import report_from_zip_bytes

        self._build_state = "running"
        self._build_progress = 8
        self._build_message = "Calculating metrics and benchmark comparisons..."

        def on_progress(fraction: float, message: str) -> None:
            self._build_progress = max(5, min(98, int(fraction * 100)))
            self._build_message = message

        def work() -> None:
            try:
                raw_bytes = base64.b64decode(b64_payload)
                work_dir = app_writable_root() / "data" / "uploads" / uuid.uuid4().hex
                report = report_from_zip_bytes(
                    raw_bytes,
                    work_dir,
                    currency=self._currency,
                    use_cache=True,
                    refresh_latest=True,
                    on_progress=on_progress,
                )
                self._html_path = report.resolve()
                self._report_url = self._html_path.as_uri()
                self._build_progress = 100
                self._build_message = "Opening report..."
                self._build_state = "done"
            except Exception as exc:
                self._build_message = str(exc).strip() or exc.__class__.__name__
                self._build_state = "error"

        threading.Thread(target=work, daemon=True).start()
        return {"started": True, "filename": filename}

    def _load_cached_accounts(self) -> list:
        from xtb_analyzer.parser import discover_export_files, load_accounts

        data_dir = self._data_dir()
        csv_files = discover_export_files(data_dir)
        if not csv_files:
            return []
        key = (
            str(data_dir.resolve()),
            tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in csv_files),
        )
        if self._cached_accounts_key != key or self._cached_accounts is None:
            self._cached_accounts = load_accounts(csv_files)
            self._cached_accounts_key = key
        return self._cached_accounts

    def get_live_update(self, currency: str = "pln") -> dict[str, object] | None:
        from xtb_analyzer.report import build_live_payload, collect_report_data

        if not self._live_lock.acquire(blocking=False):
            return None
        try:
            accounts = self._load_cached_accounts()
            if not accounts:
                return None
            data = collect_report_data(
                accounts,
                currency=currency,
                use_cache=True,
                refresh_latest=True,
            )
            self._last_data = data
            return build_live_payload(data, sorted(self._custom_tickers))
        finally:
            self._live_lock.release()

    def switch_currency(self, currency: str = "pln") -> dict[str, object]:
        """Rebuild report in the selected currency (PLN/USD/EUR) and reload inside the desktop window."""
        from xtb_analyzer.report import collect_report_data, render_html_report

        currency = (currency or "pln").lower()
        if currency not in ("pln", "usd", "eur"):
            currency = "pln"
        self._currency = currency
        with self._live_lock:
            try:
                accounts = self._load_cached_accounts()
                if not accounts:
                    return {"ok": False, "error": "No XTB account exports have been loaded."}
                data = collect_report_data(
                    accounts,
                    currency=currency,
                    use_cache=True,
                    refresh_latest=False,
                )
                self._last_data = data
                if self._html_path is not None:
                    self._html_path.write_text(render_html_report(data), encoding="utf-8")
                return {"ok": True, "currency": currency}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

    def get_custom_benchmark(self, ticker: str, currency: str = "pln") -> dict[str, object]:
        from xtb_analyzer.flows import attach_deposits_to_nav
        from xtb_analyzer.portfolio import build_nav_series
        from xtb_analyzer.report import build_custom_benchmark_payload

        with self._live_lock:
            try:
                accounts = self._load_cached_accounts()
                if not accounts:
                    return {"error": "No XTB account exports have been loaded."}
                if self._last_data is not None and self._last_data.currency == currency:
                    nav = self._last_data.nav
                else:
                    nav, _, _ = build_nav_series(accounts, use_cache=True, live_prices=False)
                    nav = attach_deposits_to_nav(nav, accounts, use_cache=True)
                payload = build_custom_benchmark_payload(
                    accounts,
                    nav,
                    ticker,
                    currency=currency,
                    use_cache=True,
                    refresh_latest=True,
                )
                self._custom_tickers.add(ticker.strip().upper())
                return payload
            except Exception as exc:
                return {"error": str(exc)}


def _capture_readiness(window, ready_file: Path | None, report: bool) -> None:
    """Signal actual WebView rendering to the optional native screenshot driver."""
    if ready_file is None:
        return

    def loaded() -> None:
        import json
        import os
        import time

        expression = (
            "document.querySelectorAll('.js-plotly-plot').length === 8 && "
            "Array.from(document.querySelectorAll('.js-plotly-plot')).every(p => p._fullLayout)"
            if report
            else "document.getElementById('dropzone-heading') !== null"
        )
        for _ in range(150):
            if window.evaluate_js(expression):
                ready_file.parent.mkdir(parents=True, exist_ok=True)
                ready_file.write_text(
                    json.dumps({"pid": os.getpid(), "rendered": True, "report": report}),
                    encoding="utf-8",
                )
                return
            time.sleep(0.2)

    window.events.loaded += loaded


def open_report_window(
    html_path: Path,
    *,
    width: int = 1280,
    height: int = 860,
    capture_ready: Path | None = None,
) -> None:
    """Show ``html_path`` in a native window."""
    webview, gui = _prepare_webview()
    bridge = _LiveReportBridge(html_path)
    window = webview.create_window(
        "XTB Portfolio Report",
        url=html_path.resolve().as_uri(),
        width=width,
        height=height,
        min_size=(900, 640),
        background_color=BG,
        js_api=bridge,
    )
    bridge.set_window(window)
    _capture_readiness(window, capture_ready, report=True)
    if gui:
        webview.start(gui=gui)
    else:
        webview.start()


def open_desktop_app(
    currency: str = "pln",
    initial_zip: str | None = None,
    *,
    width: int = 1120,
    height: int = 760,
    capture_ready: Path | None = None,
) -> None:
    """Open the modern HTML/CSS Fintech Dark Mode start screen in PyWebView and transition to the report."""
    webview, gui = _prepare_webview()
    start_dir = app_writable_root() / "data"
    start_dir.mkdir(parents=True, exist_ok=True)
    start_file = start_dir / "start_screen.html"
    start_file.write_text(_DESKTOP_START_HTML, encoding="utf-8")

    bridge = _LiveReportBridge(None, currency=currency)
    window = webview.create_window(
        "XTB Portfolio Analyzer",
        url=start_file.resolve().as_uri(),
        width=width,
        height=height,
        min_size=(760, 560),
        background_color=BG,
        js_api=bridge,
    )
    bridge.set_window(window)
    _capture_readiness(window, capture_ready, report=False)
    if initial_zip:
        bridge.start_zip_path(initial_zip)
    if gui:
        webview.start(gui=gui)
    else:
        webview.start()


class AnalyzerApp:
    """Modern Fintech Dark Mode ZIP launcher window."""

    def __init__(self, root=None):
        import tkinter as tk
        from tkinter import ttk

        self._tk = tk
        self._ttk = ttk
        if root is None:
            root = self._make_root()
        self.root = root
        self.root.title("XTB Portfolio Analyzer")
        self.root.configure(bg=BG)
        self.root.geometry("680x460")
        self.root.minsize(560, 410)
        self.currency = tk.StringVar(value="pln")
        self.zip_path = tk.StringVar(value="")
        self.status = tk.StringVar(value="")
        self.report_path: Path | None = None
        self._busy = False
        self.progress = None
        self._progress_visible = False
        self._hovered = False
        apply_window_icon(self.root)
        self._build()

    def _make_root(self):
        try:
            from tkinterdnd2 import TkinterDnD

            return TkinterDnD.Tk()
        except Exception:
            import tkinter as tk

            return tk.Tk()

    @staticmethod
    def _draw_rounded_rect(canvas, x1: int, y1: int, x2: int, y2: int, r: int, **kwargs) -> int:
        points = [
            x1 + r,
            y1,
            x2 - r,
            y1,
            x2,
            y1,
            x2,
            y1 + r,
            x2,
            y2 - r,
            x2,
            y2,
            x2 - r,
            y2,
            x1 + r,
            y2,
            x1,
            y2,
            x1,
            y2 - r,
            x1,
            y1 + r,
            x1,
            y1,
        ]
        return canvas.create_polygon(points, smooth=True, **kwargs)

    def _build(self) -> None:
        tk = self._tk
        outer = tk.Frame(self.root, bg=BG, padx=40, pady=32)
        outer.pack(fill="both", expand=True)
        self._outer = outer

        tk.Label(
            outer,
            text="XTB Portfolio Analyzer",
            bg=BG,
            fg=FG,
            font=("Segoe UI", 22, "bold"),
        ).pack(anchor="center")

        tk.Label(
            outer,
            text="Import your account history as a ZIP file to generate a report.",
            bg=BG,
            fg=MUTED,
            justify="center",
            font=("Segoe UI", 10),
        ).pack(anchor="center", pady=(6, 24))

        drop_canvas = tk.Canvas(
            outer,
            bg=BG,
            highlightthickness=0,
            bd=0,
            height=230,
            cursor="hand2",
        )
        drop_canvas.pack(fill="x", anchor="center")
        self._drop_canvas = drop_canvas

        drop_card = tk.Frame(drop_canvas, bg=DROP_BG, padx=24, pady=20, cursor="hand2")
        self._drop_card = drop_card
        self._card_window = drop_canvas.create_window(0, 0, window=drop_card, anchor="center")

        icon_canvas = tk.Canvas(
            drop_card,
            width=52,
            height=44,
            bg=DROP_BG,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        icon_canvas.pack(anchor="center", pady=(0, 10))
        self._icon_canvas = icon_canvas
        self._draw_cloud_icon(icon_canvas)

        drop = tk.Label(
            drop_card,
            text="Drop your history ZIP here",
            bg=DROP_BG,
            fg=FG,
            font=("Segoe UI", 14, "bold"),
            cursor="hand2",
        )
        drop.pack(anchor="center")
        self._drop_label = drop

        drop_sub = tk.Label(
            drop_card,
            text="or click to select a file",
            bg=DROP_BG,
            fg=MUTED,
            font=("Segoe UI", 10),
            cursor="hand2",
        )
        drop_sub.pack(anchor="center", pady=(4, 16))
        self._drop_sub = drop_sub

        btn = tk.Button(
            drop_card,
            text="Choose file",
            command=self._browse,
            bg=ACCENT,
            fg="#FFFFFF",
            activebackground=ACCENT_HOVER,
            activeforeground="#FFFFFF",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            bd=0,
            padx=22,
            pady=9,
            cursor="hand2",
        )
        btn.pack(anchor="center")
        self._browse_btn = btn
        btn.bind("<Enter>", lambda _e: btn.configure(bg=ACCENT_HOVER))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=ACCENT))

        drop_canvas.bind("<Configure>", self._redraw_dropzone)

        for widget in (drop_canvas, drop_card, icon_canvas, drop, drop_sub):
            widget.bind("<Button-1>", lambda _e: self._browse())
            widget.bind("<Enter>", lambda _e: self._set_hover(True))
            widget.bind("<Leave>", lambda _e: self._set_hover(False))
            self._enable_drop(widget)
        self._enable_drop(outer)
        self._enable_drop(self.root)

        style = self._ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "Xtb.Horizontal.TProgressbar",
            troughcolor=SURFACE,
            background=ACCENT,
            bordercolor=DROP_BORDER,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=8,
        )
        self._progress_frame = tk.Frame(outer, bg=BG)
        self.progress = self._ttk.Progressbar(
            self._progress_frame,
            style="Xtb.Horizontal.TProgressbar",
            mode="determinate",
            maximum=100,
        )
        self.progress.pack(fill="x", pady=(18, 0))

        self._status_label = tk.Label(
            self._progress_frame,
            textvariable=self.status,
            bg=BG,
            fg=MUTED,
            wraplength=580,
            justify="center",
            font=("Segoe UI", 10),
        )
        self._status_label.pack(anchor="center", pady=(10, 0))

    @staticmethod
    def _draw_cloud_icon(canvas) -> None:
        canvas.delete("all")
        canvas.create_arc(
            10, 12, 32, 34, start=30, extent=170, style="arc", outline=ACCENT, width=2.4
        )
        canvas.create_arc(
            22, 8, 44, 30, start=0, extent=160, style="arc", outline=ACCENT, width=2.4
        )
        canvas.create_arc(
            6, 18, 22, 34, start=90, extent=180, style="arc", outline=ACCENT, width=2.4
        )
        canvas.create_arc(
            30, 16, 46, 34, start=-90, extent=180, style="arc", outline=ACCENT, width=2.4
        )
        canvas.create_line(14, 34, 21, 34, fill=ACCENT, width=2.4)
        canvas.create_line(31, 34, 38, 34, fill=ACCENT, width=2.4)
        canvas.create_line(26, 38, 26, 21, fill=ACCENT, width=2.6)
        canvas.create_line(20, 27, 26, 21, fill=ACCENT, width=2.6)
        canvas.create_line(32, 27, 26, 21, fill=ACCENT, width=2.6)

    def _redraw_dropzone(self, _event=None) -> None:
        if not hasattr(self, "_drop_canvas"):
            return
        c = self._drop_canvas
        w = max(c.winfo_width(), 420)
        h = max(c.winfo_height(), 220)
        c.delete("bg_rect")
        fill_color = DROP_HOVER_BG if self._hovered else DROP_BG
        border_color = DROP_HOVER_BORDER if self._hovered else DROP_BORDER
        rect_id = self._draw_rounded_rect(
            c,
            4,
            4,
            w - 4,
            h - 4,
            16,
            fill=fill_color,
            outline=border_color,
            width=2,
            dash=(7, 5),
        )
        c.itemconfig(rect_id, tags=("bg_rect",))
        c.tag_lower("bg_rect")
        c.coords(self._card_window, w // 2, h // 2)

    def _set_hover(self, hovered: bool) -> None:
        if self._hovered == hovered:
            return
        self._hovered = hovered
        bg_color = DROP_HOVER_BG if hovered else DROP_BG
        for w in (self._drop_card, self._icon_canvas, self._drop_label, self._drop_sub):
            try:
                w.configure(bg=bg_color)
            except Exception:
                pass
        self._redraw_dropzone()

    def _show_progress_area(self) -> None:
        if not self._progress_visible and hasattr(self, "_progress_frame"):
            self._progress_frame.pack(fill="x")
            self._progress_visible = True

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
        seen: list[str] = []
        for path in files:
            if path not in seen:
                seen.append(path)
        if not seen:
            self._show_progress_area()
            self.status.set("Drop a ZIP containing your account history.")
            return
        self._choose(seen[0])

    def _browse(self) -> None:
        if self._busy:
            return
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="XTB account history",
            filetypes=[("ZIP archive", "*.zip"), ("All files", "*.*")],
        )
        if path:
            self._choose(path)

    def _choose(self, path: str) -> None:
        self.zip_path.set(str(path))
        self._drop_label.configure(text=Path(path).name)
        self._start(path)

    def _set_progress(self, fraction: float, message: str) -> None:
        self._show_progress_area()
        if self.progress is not None:
            self.progress["value"] = max(0, min(100, int(fraction * 100)))
        self.status.set(message)

    def _start(self, path: str) -> None:
        if self._busy:
            return
        self._busy = True
        self._show_progress_area()
        currency = self.currency.get()
        self._set_progress(0.02, "Calculating metrics and benchmark comparisons...")
        if self.progress is not None:
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)

        def on_progress(fraction: float, message: str) -> None:
            def apply() -> None:
                if self.progress is not None and str(self.progress["mode"]) == "indeterminate":
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                self._set_progress(fraction, message)

            self.root.after(0, apply)

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
                self.root.after(0, lambda error=exc: self._fail(error))
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
            raise ZipImportError("Select your account-history ZIP.")
        root = upload_root or (app_writable_root() / "data" / "uploads")
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
        if self.progress is not None:
            try:
                self.progress.stop()
            except Exception:
                pass
            self.progress.configure(mode="determinate")
            self.progress["value"] = 100
        self.status.set("Opening report...")
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
            try:
                self.progress.stop()
            except Exception:
                pass
            self.progress.configure(mode="determinate")
            self.progress["value"] = 0
        message = str(exc).strip() or exc.__class__.__name__
        self._show_progress_area()
        self.status.set(message)
        try:
            from tkinter import messagebox

            messagebox.showerror("Report generation failed", message)
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xtb_analyzer.desktop",
        description="Import an XTB history ZIP and view your portfolio report.",
    )
    parser.add_argument("--currency", default="pln", choices=["pln", "usd", "eur"])
    parser.add_argument(
        "--zip", dest="zip_path", default=None, help="open this ZIP file on startup"
    )
    parser.add_argument(
        "--demo", action="store_true", help="Open the offline synthetic demo in the desktop window."
    )
    parser.add_argument("--check-install", metavar="JSON", help=argparse.SUPPRESS)
    parser.add_argument("--width", type=int, default=None, help="Initial window width.")
    parser.add_argument("--height", type=int, default=None, help="Initial window height.")
    parser.add_argument("--capture-ready", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.check_install:
        import io
        import json

        import pandas as pd
        import plotly
        import pyarrow
        from plotly.offline import get_plotlyjs

        _prepare_webview()
        payload = {"ok": False}
        try:
            buffer = io.BytesIO()
            pd.DataFrame({"value": [1.25]}).to_parquet(buffer)
            buffer.seek(0)
            assert pd.read_parquet(buffer).iloc[0, 0] == 1.25
            assert asset_path("assets", "app.ico").is_file()
            from datetime import datetime
            from zoneinfo import ZoneInfo

            assert datetime.now(ZoneInfo("Europe/Warsaw")).tzname() in {"CET", "CEST"}
            if is_frozen():
                from xtb_analyzer.market_data import MarketData
                from xtb_analyzer.parser import discover_export_files, load_accounts

                sample_dir = resource_root() / "examples"
                assert len(load_accounts(discover_export_files(sample_dir))) == 2
                assert not MarketData.from_examples(sample_dir).prices.empty
            assert len(get_plotlyjs()) > 100000
            if sys.platform == "win32":
                import webview.platforms.edgechromium  # noqa: F401
            elif sys.platform == "darwin":
                import webview.platforms.cocoa  # noqa: F401
            payload = {
                "ok": True,
                "python": sys.version,
                "plotly": plotly.__version__,
                "pyarrow": pyarrow.__version__,
            }
        except Exception as exc:
            payload["error"] = str(exc)
        Path(args.check_install).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return 0 if payload["ok"] else 1

    ensure_app_cwd()

    if args.demo:
        from xtb_analyzer.market_data import MarketData
        from xtb_analyzer.report import generate_report

        sample_dir = resource_root() / "examples" if is_frozen() else Path("examples")
        report = generate_report(
            data_dir=sample_dir,
            output_dir="output/demo",
            currency=args.currency,
            market_data=MarketData.from_examples(sample_dir),
            refresh_latest=False,
        )
        open_report_window(
            report,
            width=args.width or 1280,
            height=args.height or 860,
            capture_ready=args.capture_ready,
        )
        return 0

    try:
        open_desktop_app(
            currency=args.currency,
            initial_zip=args.zip_path,
            width=args.width or 1120,
            height=args.height or 760,
            capture_ready=args.capture_ready,
        )
        return 0
    except Exception:
        app = AnalyzerApp()
        app.currency.set(args.currency)
        if args.zip_path:
            app.root.after(200, lambda: app._start(args.zip_path))
        app.root.mainloop()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
