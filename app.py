"""Web server entrypoint for XTB Portfolio Analyzer on port 3000."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import uuid
from http import HTTPStatus
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
UPLOADS_DIR = DATA_DIR / "uploads"
FIXTURES_DIR = ROOT_DIR / "tests" / "fixtures"

_BUILD_LOCK = threading.Lock()
_DEPS_LOCK = threading.Lock()
_DEPS_READY = False
_FLASK_APP = None
_STATE: dict[str, str | Path | None] = {
    "active_data_dir": None,
    "active_label": "Dane demonstracyjne (XTB USD + EUR)",
    "status": "starting",
}


def _ensure_pip() -> None:
    """Ensure pip is available in the current Python interpreter."""
    check = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if check.returncode == 0:
        return
    with tempfile.NamedTemporaryFile(suffix="-get-pip.py", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", str(tmp_path))
        res = subprocess.run(
            [sys.executable, str(tmp_path), "--no-warn-script-location", "-q"],
            check=False,
        )
        if res.returncode != 0:
            subprocess.run(
                [sys.executable, str(tmp_path), "--break-system-packages", "--no-warn-script-location", "-q"],
                check=False,
            )
    finally:
        tmp_path.unlink(missing_ok=True)


def _ensure_runtime_packages() -> None:
    """Ensure required web/scientific/financial Python packages are installed after container wake."""
    global _DEPS_READY
    if _DEPS_READY:
        return
    with _DEPS_LOCK:
        if _DEPS_READY:
            return
        try:
            import flask  # noqa: F401
            import numpy  # noqa: F401
            import openpyxl  # noqa: F401
            import pandas  # noqa: F401
            import plotly  # noqa: F401
            import pyarrow  # noqa: F401
            import yfinance  # noqa: F401

            _DEPS_READY = True
            return
        except ImportError:
            pass

        _STATE["status"] = "installing"
        _ensure_pip()
        req_file = ROOT_DIR / "requirements.txt"
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--no-warn-script-location",
            "-q",
            "-r",
            str(req_file),
        ]
        res = subprocess.run(cmd, check=False)
        if res.returncode != 0:
            subprocess.run([*cmd, "--break-system-packages"], check=False)
        _DEPS_READY = True


def ensure_seed_data() -> Path:
    """Ensure canonical demo exports exist in data/ if no exports are present."""
    _ensure_runtime_packages()
    from xtb_analyzer.parser import discover_export_files

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        existing = discover_export_files(DATA_DIR)
    except Exception:
        existing = []
    if not existing:
        usd_fixture = FIXTURES_DIR / "legacy_usd_account.xlsx"
        eur_fixture = FIXTURES_DIR / "legacy_eur_account.xlsx"
        if usd_fixture.is_file():
            shutil.copy2(usd_fixture, DATA_DIR / "XTB_USD_cs.xlsx")
        if eur_fixture.is_file():
            shutil.copy2(eur_fixture, DATA_DIR / "XTB_EURO_cs.xlsx")
    return DATA_DIR


def _loading_html() -> str:
    return """<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Raport portfela XTB – Inicjalizacja…</title>
<style>
  body {
    margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
    background: #0b0f17; color: #f1f5f9; font-family: 'Plus Jakarta Sans', 'Segoe UI', Arial, sans-serif;
  }
  .card {
    background: #151d2e; border: 1px solid #1e293b; border-radius: 16px;
    padding: 36px 42px; max-width: 480px; text-align: center;
  }
  .spinner {
    width: 38px; height: 38px; margin: 0 auto 18px;
    border: 3px solid #1e293b; border-top-color: #3b82f6; border-radius: 50%;
    animation: spin 0.9s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  h1 { font-size: 20px; margin: 0 0 8px; font-weight: 600; }
  p { color: #94a3b8; font-size: 14px; margin: 0; line-height: 1.5; }
</style>
</head>
<body>
  <div class="card">
    <div class="spinner"></div>
    <h1>Przygotowywanie raportu portfela XTB…</h1>
    <p>Inicjalizacja środowiska, pobieranie aktualnych notowań, kursów walut i benchmarków. Strona odświeży się automatycznie.</p>
  </div>
  <script>
    setInterval(async function() {
      try {
        const res = await fetch('/health', { cache: 'no-store' });
        if (res.ok) {
          const data = await res.json();
          if (data.ready) window.location.reload();
        }
      } catch (e) {}
    }, 1500);
  </script>
</body>
</html>"""


def _inject_toolbar(report_html: str, currency: str, label: str, error_msg: str = "") -> str:
    """Inject a sleek top bar and Modern Slate Dark Mode upload screen for uploading a ZIP archive."""
    currency = currency.lower()
    error_banner = f"<div class='xtb-web-error'>{error_msg}</div>" if error_msg else ""
    toolbar = f"""
<style>
.xtb-web-bar {{
  position: sticky;
  top: 0;
  z-index: 40;
  background: rgba(11, 15, 23, 0.92);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid #1E293B;
  padding: 10px 28px;
  font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 13px;
  color: #F8FAFC;
}}
.xtb-web-bar-inner {{
  max-width: 1280px;
  margin: 0 auto;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}}
.xtb-web-source {{
  color: #94A3B8;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}}
.xtb-source-pill {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #161F30;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 4px 10px;
  color: #F8FAFC;
  font-weight: 600;
  font-size: 12.5px;
}}
.xtb-web-controls {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}}
.xtb-web-btn {{
  background: #161F30;
  color: #F8FAFC;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 7px 14px;
  font-size: 12.5px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}}
.xtb-web-btn:hover {{
  border-color: #3B82F6;
  background: #1E293B;
}}
.xtb-web-btn-primary {{
  background: #3B82F6;
  border-color: #3B82F6;
  color: #FFFFFF;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.28);
}}
.xtb-web-btn-primary:hover {{
  background: #2563EB;
  border-color: #2563EB;
}}
.xtb-web-error {{
  max-width: 1280px;
  margin: 10px auto 0;
  padding: 10px 14px;
  border-radius: 8px;
  background: rgba(248, 113, 113, 0.12);
  border: 1px solid #f87171;
  color: #fca5a5;
}}

/* Modern Slate Dark Mode Upload Screen (Modal / Drag Overlay) */
.xtb-upload-screen {{
  position: fixed;
  inset: 0;
  z-index: 100;
  background: rgba(11, 15, 23, 0.94);
  backdrop-filter: blur(10px);
  display: none;
  align-items: center;
  justify-content: center;
  padding: 24px;
  font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}}
.xtb-upload-screen.visible {{
  display: flex;
}}
.xtb-upload-card {{
  position: relative;
  width: 100%;
  max-width: 580px;
  background: #0B0F17;
  border: 1px solid #1E293B;
  border-radius: 20px;
  padding: 40px 38px 36px;
  text-align: center;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.55);
  display: flex;
  flex-direction: column;
  align-items: center;
}}
.xtb-upload-close {{
  position: absolute;
  top: 16px;
  right: 16px;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  color: #94A3B8;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.18s ease;
}}
.xtb-upload-close:hover {{
  color: #F8FAFC;
  background: #161F30;
  border-color: #334155;
}}
.xtb-upload-title {{
  margin: 0 0 8px;
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #F8FAFC;
}}
.xtb-upload-subtitle {{
  margin: 0 0 26px;
  font-size: 14px;
  color: #94A3B8;
  line-height: 1.5;
}}
.xtb-dropzone {{
  width: 100%;
  background: #161F30;
  border: 2px dashed #334155;
  border-radius: 16px;
  padding: 36px 28px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  transition: border-color 0.2s ease, background-color 0.2s ease, transform 0.2s ease;
}}
.xtb-dropzone:hover,
.xtb-dropzone.drag-active {{
  border-color: #3B82F6;
  background: #1E293B;
}}
.xtb-dropzone-icon {{
  width: 48px;
  height: 48px;
  color: #3B82F6;
  margin-bottom: 14px;
  transition: transform 0.2s ease;
}}
.xtb-dropzone:hover .xtb-dropzone-icon,
.xtb-dropzone.drag-active .xtb-dropzone-icon {{
  transform: translateY(-2px);
}}
.xtb-dropzone-heading {{
  margin: 0 0 6px;
  font-size: 17px;
  font-weight: 700;
  color: #F8FAFC;
}}
.xtb-dropzone-hint {{
  margin: 0 0 18px;
  font-size: 13.5px;
  color: #94A3B8;
}}
.xtb-dropzone-btn {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #3B82F6;
  color: #FFFFFF;
  border: none;
  border-radius: 8px;
  padding: 10px 22px;
  font-size: 13.5px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(59, 130, 246, 0.35);
  transition: background-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}}
.xtb-dropzone-btn:hover {{
  background: #2563EB;
  box-shadow: 0 6px 18px rgba(37, 99, 235, 0.45);
  transform: translateY(-1px);
}}
.xtb-upload-progress-wrap {{
  width: 100%;
  margin-top: 22px;
  display: none;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}}
.xtb-upload-progress-wrap.active {{
  display: flex;
}}
.xtb-upload-progress-track {{
  width: 100%;
  height: 8px;
  background: #0F172A;
  border: 1px solid #334155;
  border-radius: 999px;
  overflow: hidden;
}}
.xtb-upload-progress-bar {{
  width: 42%;
  height: 100%;
  background: #3B82F6;
  border-radius: 999px;
  animation: xtbProgressSlide 1.2s ease-in-out infinite;
}}
@keyframes xtbProgressSlide {{
  0% {{ transform: translateX(-100%); }}
  100% {{ transform: translateX(250%); }}
}}
.xtb-upload-status-text {{
  font-size: 13px;
  color: #94A3B8;
  margin: 0;
}}
</style>
<div class="xtb-web-bar">
  <div class="xtb-web-bar-inner">
    <div class="xtb-web-source">
      <span>Aktywne dane:</span>
      <span class="xtb-source-pill">{label}</span>
    </div>
    <div class="xtb-web-controls">
      <button type="button" id="xtb-open-upload-btn" class="xtb-web-btn xtb-web-btn-primary">
        Wgraj archiwum ZIP
      </button>
      <a href="/download?currency={currency}" class="xtb-web-btn" style="text-decoration:none;">Pobierz raport HTML</a>
    </div>
  </div>
  {error_banner}
</div>

<div id="xtb-upload-screen" class="xtb-upload-screen" role="dialog" aria-modal="true" aria-labelledby="xtb-upload-title">
  <div class="xtb-upload-card">
    <button type="button" id="xtb-close-upload-btn" class="xtb-upload-close" aria-label="Zamknij">×</button>
    <h2 id="xtb-upload-title" class="xtb-upload-title">Analizator portfela XTB</h2>
    <p class="xtb-upload-subtitle">Wczytaj historię konta w formacie .zip, aby wygenerować raport.</p>

    <form id="xtb-zip-form" method="post" action="/upload" enctype="multipart/form-data" style="width:100%;margin:0;">
      <input type="hidden" name="currency" value="{currency}">
      <input id="xtb-zip-input" type="file" name="file" accept=".zip" style="display:none">
      <div id="xtb-dropzone" class="xtb-dropzone" role="button" tabindex="0">
        <svg class="xtb-dropzone-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/>
          <path d="M12 12v9"/>
          <path d="m16 16-4-4-4 4"/>
        </svg>
        <div id="xtb-dropzone-heading" class="xtb-dropzone-heading">Upuść archiwum ZIP tutaj</div>
        <div class="xtb-dropzone-hint">lub kliknij, aby wybrać z dysku</div>
        <span class="xtb-dropzone-btn">Wybierz z dysku</span>
      </div>
    </form>

    <div id="xtb-upload-progress-wrap" class="xtb-upload-progress-wrap">
      <div class="xtb-upload-progress-track">
        <div class="xtb-upload-progress-bar"></div>
      </div>
      <p id="xtb-upload-status-text" class="xtb-upload-status-text">Liczenie statystyk, porównań i benchmarków…</p>
    </div>
  </div>
</div>

<script>
(function() {{
  let dragDepth = 0;
  const screen = document.getElementById('xtb-upload-screen');
  const openBtn = document.getElementById('xtb-open-upload-btn');
  const closeBtn = document.getElementById('xtb-close-upload-btn');
  const dropzone = document.getElementById('xtb-dropzone');
  const heading = document.getElementById('xtb-dropzone-heading');
  const fileInput = document.getElementById('xtb-zip-input');
  const form = document.getElementById('xtb-zip-form');
  const progressWrap = document.getElementById('xtb-upload-progress-wrap');
  const statusText = document.getElementById('xtb-upload-status-text');
  if (!screen || !dropzone || !fileInput || !form) return;

  function startFileSubmit(file) {{
    if (!file) return;
    if (heading) heading.textContent = file.name;
    if (progressWrap) progressWrap.classList.add('active');
    if (statusText) statusText.textContent = 'Wczytywanie ' + file.name + ' i generowanie raportu…';
    form.submit();
  }}

  if (openBtn) {{
    openBtn.addEventListener('click', function() {{
      screen.classList.add('visible');
    }});
  }}
  if (closeBtn) {{
    closeBtn.addEventListener('click', function() {{
      screen.classList.remove('visible');
    }});
  }}
  screen.addEventListener('click', function(e) {{
    if (e.target === screen) screen.classList.remove('visible');
  }});

  dropzone.addEventListener('click', function() {{
    fileInput.click();
  }});
  dropzone.addEventListener('keydown', function(e) {{
    if (e.key === 'Enter' || e.key === ' ') {{
      e.preventDefault();
      fileInput.click();
    }}
  }});
  fileInput.addEventListener('change', function() {{
    if (fileInput.files && fileInput.files.length > 0) {{
      startFileSubmit(fileInput.files[0]);
    }}
  }});

  window.addEventListener('dragenter', function(e) {{
    if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) {{
      e.preventDefault();
      dragDepth++;
      screen.classList.add('visible');
      dropzone.classList.add('drag-active');
    }}
  }});
  window.addEventListener('dragover', function(e) {{
    if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) {{
      e.preventDefault();
      dropzone.classList.add('drag-active');
    }}
  }});
  window.addEventListener('dragleave', function(e) {{
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) {{
      dropzone.classList.remove('drag-active');
    }}
  }});
  window.addEventListener('drop', function(e) {{
    if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
    e.preventDefault();
    dragDepth = 0;
    dropzone.classList.remove('drag-active');
    const file = e.dataTransfer.files[0];
    if (file && file.name.toLowerCase().endsWith('.zip')) {{
      const dt = new DataTransfer();
      dt.items.add(file);
      fileInput.files = dt.files;
      startFileSubmit(file);
    }} else if (progressWrap && statusText) {{
      progressWrap.classList.add('active');
      statusText.textContent = 'Wybierz archiwum w formacie .zip.';
    }}
  }});
}})();
</script>
"""
    if "<body>" in report_html:
        return report_html.replace("<body>", "<body>\n" + toolbar, 1)
    return toolbar + report_html


def _build_or_get_report(currency: str, force_rebuild: bool = False) -> Path:
    currency = currency.lower()
    if currency not in ("pln", "usd", "eur"):
        currency = "pln"

    out_dir = OUTPUT_DIR / currency
    report_file = out_dir / "report.html"
    if not force_rebuild and report_file.is_file():
        return report_file

    _ensure_runtime_packages()
    from xtb_analyzer.report import generate_report

    with _BUILD_LOCK:
        if not force_rebuild and report_file.is_file():
            return report_file
        _STATE["status"] = "building"
        active_dir = _STATE.get("active_data_dir")
        data_dir = Path(active_dir) if active_dir else ensure_seed_data()
        try:
            generate_report(
                data_dir=data_dir,
                output_dir=out_dir,
                currency=currency,
                use_cache=True,
                refresh_latest=True,
            )
        except Exception:
            generate_report(
                data_dir=data_dir,
                output_dir=out_dir,
                currency=currency,
                use_cache=True,
                refresh_latest=False,
            )
        _STATE["status"] = "ready"
        return report_file


def _get_flask_app():
    """Lazily create and configure the Flask app once runtime packages are ready."""
    global _FLASK_APP
    if _FLASK_APP is not None:
        return _FLASK_APP

    _ensure_runtime_packages()
    from flask import Flask, Response, jsonify, redirect, request, send_file, url_for

    flask_app = Flask(__name__)

    @flask_app.route("/api/live", methods=["GET"])
    def api_live() -> Response:
        from xtb_analyzer.parser import discover_export_files, load_accounts
        from xtb_analyzer.report import build_live_payload, collect_report_data, render_html_report

        currency = request.args.get("currency", "pln").lower()
        if currency not in ("pln", "usd", "eur"):
            currency = "pln"

        with _BUILD_LOCK:
            active_dir = _STATE.get("active_data_dir")
            data_dir = Path(active_dir) if active_dir else ensure_seed_data()
            csv_files = discover_export_files(data_dir)
            accounts = load_accounts(csv_files)
            try:
                data = collect_report_data(
                    accounts,
                    currency=currency,
                    use_cache=True,
                    refresh_latest=True,
                )
            except Exception:
                data = collect_report_data(
                    accounts,
                    currency=currency,
                    use_cache=True,
                    refresh_latest=False,
                )
            out_dir = OUTPUT_DIR / currency
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "report.html").write_text(render_html_report(data), encoding="utf-8")
            _STATE["status"] = "ready"
            return jsonify(build_live_payload(data))

    @flask_app.route("/api/benchmark", methods=["GET"])
    def api_benchmark() -> Response:
        from xtb_analyzer.flows import attach_deposits_to_nav
        from xtb_analyzer.parser import discover_export_files, load_accounts
        from xtb_analyzer.portfolio import build_nav_series
        from xtb_analyzer.report import build_custom_benchmark_payload

        ticker = (request.args.get("ticker") or "").strip()
        currency = request.args.get("currency", "pln").lower()
        if currency not in ("pln", "usd", "eur"):
            currency = "pln"
        if not ticker:
            return jsonify({"error": "Podaj symbol instrumentu."}), 400

        with _BUILD_LOCK:
            active_dir = _STATE.get("active_data_dir")
            data_dir = Path(active_dir) if active_dir else ensure_seed_data()
            csv_files = discover_export_files(data_dir)
            accounts = load_accounts(csv_files)
            try:
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
                return jsonify(payload)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 400

    @flask_app.route("/", methods=["GET"])
    def index() -> Response:
        currency = request.args.get("currency", "pln").lower()
        if currency not in ("pln", "usd", "eur"):
            currency = "pln"
        error_msg = request.args.get("error", "")
        refresh = request.args.get("refresh") == "1"

        report_file = OUTPUT_DIR / currency / "report.html"
        if not refresh and not report_file.is_file() and _STATE.get("status") in ("starting", "installing", "building"):
            return Response(_loading_html(), mimetype="text/html")

        report_file = _build_or_get_report(currency, force_rebuild=refresh)
        html_content = report_file.read_text(encoding="utf-8")
        label = str(_STATE.get("active_label") or "Dane demonstracyjne")
        resp = Response(_inject_toolbar(html_content, currency, label, error_msg), mimetype="text/html")
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    @flask_app.route("/upload", methods=["POST"])
    def upload_zip():
        from xtb_analyzer.session import report_from_zip_bytes
        from xtb_analyzer.zip_import import ZipImportError

        currency = request.form.get("currency", "pln").lower()
        uploaded = request.files.get("file")
        if uploaded is None or not uploaded.filename:
            return redirect(url_for("index", currency=currency, error="Wybierz plik ZIP z historią kont XTB."))

        payload = uploaded.read()
        work_dir = UPLOADS_DIR / uuid.uuid4().hex
        try:
            report_from_zip_bytes(
                payload,
                work_dir,
                currency=currency,
                use_cache=True,
                refresh_latest=True,
            )
        except ZipImportError as exc:
            return redirect(url_for("index", currency=currency, error=str(exc)))
        except Exception as exc:
            return redirect(url_for("index", currency=currency, error=f"Błąd generowania raportu: {exc}"))

        with _BUILD_LOCK:
            _STATE["active_data_dir"] = work_dir / "extracted"
            _STATE["active_label"] = uploaded.filename
            if OUTPUT_DIR.is_dir():
                shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
            out_dir = OUTPUT_DIR / currency
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(work_dir / "output" / "report.html", out_dir / "report.html")
            _STATE["status"] = "ready"
        return redirect(url_for("index", currency=currency))

    @flask_app.route("/download", methods=["GET"])
    def download_report():
        currency = request.args.get("currency", "pln").lower()
        report_file = _build_or_get_report(currency)
        return send_file(
            report_file,
            mimetype="text/html",
            as_attachment=True,
            download_name=f"xtb_report_{currency}.html",
        )

    @flask_app.route("/health", methods=["GET"])
    def health():
        ready = _DEPS_READY and (OUTPUT_DIR / "pln" / "report.html").is_file()
        return jsonify({"status": "ok", "state": _STATE.get("status", "ready"), "ready": ready})

    _FLASK_APP = flask_app
    return _FLASK_APP


def _wsgi_app(environ, start_response):
    """Zero-dependency WSGI wrapper that serves port 3000 immediately while bootstrapping."""
    path = environ.get("PATH_INFO", "/")
    if path == "/health":
        ready = _DEPS_READY and (OUTPUT_DIR / "pln" / "report.html").is_file()
        body = json.dumps({"status": "ok", "state": _STATE.get("status", "starting"), "ready": ready}).encode("utf-8")
        start_response(
            f"{HTTPStatus.OK.value} {HTTPStatus.OK.phrase}",
            [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))],
        )
        return [body]

    if not _DEPS_READY:
        body = _loading_html().encode("utf-8")
        start_response(
            f"{HTTPStatus.OK.value} {HTTPStatus.OK.phrase}",
            [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body)))],
        )
        return [body]

    flask_app = _get_flask_app()
    return flask_app(environ, start_response)


class _ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


def _startup_worker() -> None:
    try:
        if OUTPUT_DIR.is_dir():
            shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        _ensure_runtime_packages()
        _build_or_get_report("pln", force_rebuild=True)
    except Exception:
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "3000"))
    host = os.environ.get("HOST", "0.0.0.0")
    threading.Thread(target=_startup_worker, daemon=True).start()
    with make_server(host, port, _wsgi_app, server_class=_ThreadedWSGIServer, handler_class=_QuietHandler) as httpd:
        print(f"XTB Portfolio Analyzer listening on http://{host}:{port}", flush=True)
        httpd.serve_forever()
