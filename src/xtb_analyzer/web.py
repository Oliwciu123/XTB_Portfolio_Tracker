"""Local web app: upload an XTB history zip and show the HTML report.

Run from the project root::

    python -m xtb_analyzer.web

The report is produced by :func:`xtb_analyzer.report.generate_report` — the same
pipeline as ``python -m xtb_analyzer``.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from xtb_analyzer.parser import find_project_root
from xtb_analyzer.report import generate_report
from xtb_analyzer.zip_import import MAX_ZIP_BYTES, ZipImportError, extract_xtb_zip

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

_PAGE = """<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>XTB Portfolio Analyzer</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
    background: #0f1419; color: #e7ecf1;
    font: 16px/1.5 "Segoe UI", system-ui, sans-serif;
  }
  main {
    width: min(640px, calc(100% - 32px));
    background: #1a2332; border: 1px solid #2c3a4d; border-radius: 16px; padding: 32px;
  }
  h1 { font-size: 1.5rem; margin: 0 0 8px; }
  p.lead { margin: 0 0 24px; color: #b7c3d1; }
  label { display: block; font-weight: 600; margin-bottom: 8px; }
  .drop {
    border: 1.5px dashed #4c627a; border-radius: 12px; padding: 28px 16px; text-align: center;
    background: #121a24; margin-bottom: 16px;
  }
  .drop.drag { border-color: #7eb6ff; background: #182433; }
  input[type=file] { display: block; margin: 12px auto 0; max-width: 100%; }
  .row { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; margin: 8px 0 20px; }
  select, button {
    font: inherit; color: inherit; background: #121a24; border: 1px solid #4c627a; border-radius: 8px;
    padding: 8px 12px;
  }
  button {
    background: #2f6fed; border-color: #2f6fed; color: white; font-weight: 600; cursor: pointer;
    padding: 10px 18px;
  }
  button:disabled { opacity: 0.6; cursor: progress; }
  .hint { color: #8ea0b5; font-size: 0.92rem; }
  .file-name { margin-top: 8px; color: #d5e4f5; }
  #status { margin-top: 16px; color: #9ec1ff; }
</style>
</head>
<body>
<main>
  <h1>Raport portfela XTB</h1>
  <p class="lead">Wgraj archiwum ZIP z historią kont (każda waluta osobno).
  Po przeliczeniu zobaczysz ten sam interaktywny raport co z linii poleceń.</p>
  <form id="upload" action="/upload" method="post" enctype="multipart/form-data">
    <label for="archive">Archiwum ZIP</label>
    <div class="drop" id="drop">
      Upuść plik tutaj albo wybierz go z dysku
      <input id="archive" name="archive" type="file" accept=".zip,application/zip" required>
      <div class="file-name" id="chosen"></div>
    </div>
    <div class="row">
      <label for="currency">Waluta raportu</label>
      <select id="currency" name="currency">
        <option value="pln" selected>PLN</option>
        <option value="usd">USD</option>
        <option value="eur">EUR</option>
      </select>
      <label><input type="checkbox" name="no_live" value="1"> bez pobierania bieżących notowań</label>
    </div>
    <button type="submit" id="go">Policz raport</button>
    <p class="hint">ZIP z xStation: folder konta i plik
    <code>USD_&lt;numer&gt;_&lt;od&gt;_&lt;do&gt;.xlsx</code> (oraz EUR / PLN).
    Działają też <code>XTB_USD_cs.xlsx</code> i <code>XTB_EURO_cs.xlsx</code>.</p>
    <p id="status" hidden>Trwa liczenie statystyk, porównań i benchmarków…</p>
  </form>
</main>
<script>
const input = document.getElementById("archive");
const drop = document.getElementById("drop");
const chosen = document.getElementById("chosen");
const form = document.getElementById("upload");
const button = document.getElementById("go");
const status = document.getElementById("status");
function showName() {
  chosen.textContent = input.files.length ? input.files[0].name : "";
}
input.addEventListener("change", showName);
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => {
  e.preventDefault();
  drop.classList.add("drag");
}));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => {
  e.preventDefault();
  drop.classList.remove("drag");
}));
drop.addEventListener("drop", (e) => {
  if (e.dataTransfer.files.length) {
    input.files = e.dataTransfer.files;
    showName();
  }
});
form.addEventListener("submit", () => {
  button.disabled = true;
  status.hidden = false;
});
</script>
</body>
</html>
"""


def report_from_zip_bytes(
    payload: bytes,
    work_dir: str | Path,
    *,
    currency: str = "pln",
    use_cache: bool = True,
    refresh_latest: bool = True,
) -> Path:
    """Extract a history zip and write the standard HTML report next to it."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    zip_path = work_dir / "upload.zip"
    zip_path.write_bytes(payload)
    extract_dir = work_dir / "extracted"
    extract_xtb_zip(zip_path, extract_dir)
    return generate_report(
        data_dir=extract_dir,
        output_dir=work_dir / "output",
        currency=currency,
        use_cache=use_cache,
        refresh_latest=refresh_latest,
    )


def _parse_multipart(body: bytes, content_type: str) -> dict[str, dict[str, object]]:
    match = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type, flags=re.IGNORECASE)
    if not match:
        raise ZipImportError("Brak boundary w żądaniu.")
    boundary = (match.group(1) or match.group(2)).strip()
    sep = b"--" + boundary.encode("utf-8", errors="strict")
    fields: dict[str, dict[str, object]] = {}
    for chunk in body.split(sep):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        if chunk.endswith(b"--"):
            chunk = chunk[:-2].strip(b"\r\n")
        header_blob, separator, data = chunk.partition(b"\r\n\r\n")
        if not separator:
            continue
        headers = header_blob.decode("utf-8", errors="replace")
        name_match = re.search(r'name="([^"]*)"', headers)
        if not name_match:
            continue
        file_match = re.search(r'filename="([^"]*)"', headers)
        if data.endswith(b"\r\n"):
            data = data[:-2]
        fields[name_match.group(1)] = {
            "filename": file_match.group(1) if file_match else None,
            "data": data,
        }
    return fields


def _error_page(message: str) -> bytes:
    safe = html.escape(message)
    return (
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>"
        "<title>Nie udało się policzyć raportu</title></head><body>"
        "<h1>Nie udało się policzyć raportu</h1>"
        f"<pre>{safe}</pre><p><a href='/'>Wróć</a></p></body></html>"
    ).encode("utf-8")


def make_handler(
    upload_root: Path,
    *,
    default_currency: str = "pln",
    use_cache: bool = True,
    refresh_latest: bool = True,
):
    """Build a request handler bound to ``upload_root`` (gitignored data/uploads)."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "xtb-analyzer"

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path not in ("/", "/index.html"):
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
            page = _PAGE.replace(
                '<option value="pln" selected>PLN</option>',
                '<option value="pln">PLN</option>',
            )
            selected = default_currency if default_currency in {"pln", "usd", "eur"} else "pln"
            page = page.replace(
                f'<option value="{selected}">',
                f'<option value="{selected}" selected>',
                1,
            )
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path != "/upload":
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_ZIP_BYTES + 1024 * 1024:
                self._send(400, _error_page("Plik jest pusty albo za duży."), "text/html; charset=utf-8")
                return
            body = self.rfile.read(length)
            content_type = self.headers.get("Content-Type", "")
            try:
                fields = _parse_multipart(body, content_type)
                archive = fields.get("archive") or {}
                payload = archive.get("data") or b""
                filename = str(archive.get("filename") or "")
                if not isinstance(payload, (bytes, bytearray)) or not payload:
                    raise ZipImportError("Nie wybrano pliku ZIP.")
                if filename and not filename.lower().endswith(".zip"):
                    raise ZipImportError("Wgraj archiwum .zip z historią kont XTB.")
                if not bytes(payload).startswith(b"PK"):
                    raise ZipImportError("Wybrany plik nie jest archiwum ZIP.")
                raw_currency = (fields.get("currency") or {}).get("data")
                if isinstance(raw_currency, bytes):
                    currency = raw_currency.decode("utf-8", errors="replace")
                elif raw_currency:
                    currency = str(raw_currency)
                else:
                    currency = default_currency
                currency = currency.strip().lower()
                if currency not in {"pln", "usd", "eur"}:
                    currency = default_currency
                no_live = "no_live" in fields
                work = upload_root / uuid.uuid4().hex
                report = report_from_zip_bytes(
                    bytes(payload),
                    work,
                    currency=currency,
                    use_cache=use_cache,
                    refresh_latest=refresh_latest and not no_live,
                )
                html_bytes = report.read_bytes()
            except (ZipImportError, FileNotFoundError, ValueError, OSError) as exc:
                self._send(400, _error_page(str(exc)), "text/html; charset=utf-8")
                return
            self._send(200, html_bytes, "text/html; charset=utf-8")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xtb_analyzer.web",
        description="Lokalna aplikacja: wgraj ZIP z historią XTB i zobacz raport HTML.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="adres (domyślnie tylko localhost)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port (domyślnie 8765)")
    parser.add_argument("--currency", default="pln", choices=["pln", "usd", "eur"], help="domyślna waluta raportu")
    parser.add_argument("--no-cache", action="store_true", help="pomiń cache cen i kursów")
    parser.add_argument("--no-live", action="store_true", help="nie pobieraj bieżących notowań")
    parser.add_argument(
        "--upload-dir",
        default=None,
        help="katalog na rozpakowane wgrania (domyślnie data/uploads, gitignore)",
    )
    args = parser.parse_args(argv)

    upload_root = Path(args.upload_dir) if args.upload_dir else find_project_root() / "data" / "uploads"
    upload_root.mkdir(parents=True, exist_ok=True)
    handler = make_handler(
        upload_root,
        default_currency=args.currency,
        use_cache=not args.no_cache,
        refresh_latest=not args.no_live,
    )
    try:
        server = ThreadingHTTPServer((args.host, args.port), handler)
    except OSError as exc:
        print(f"Nie można uruchomić serwera na {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1

    url = f"http://{args.host}:{args.port}/"
    print(f"XTB Portfolio Analyzer: {url}")
    print("Wgraj ZIP z historią kont. Zatrzymanie: Ctrl+C.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nZatrzymano.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
