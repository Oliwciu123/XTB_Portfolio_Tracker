"""Upload endpoint returns the report produced from a history zip."""

from __future__ import annotations

import threading
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from xtb_analyzer.parser import discover_export_files
from xtb_analyzer.web import make_handler

FIXTURES = Path(__file__).parent / "fixtures"


def _history_zip(tmp_path: Path) -> bytes:
    usd = FIXTURES / "xtb_currency_prefix_cash_ops.csv"
    eur = usd.read_text(encoding="utf-8").replace("11111111", "22222222").replace("PLN to USD", "PLN to EUR")
    archive = tmp_path / "history.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(usd, "11111111/USD_11111111_2006-01-01_2026-10-08.csv")
        zf.writestr("22222222/EUR_22222222_2006-01-01_2026-08-01.csv", eur)
    return archive.read_bytes()


def _multipart(payload: bytes, *, currency: str = "pln", no_live: bool = True) -> tuple[bytes, str]:
    boundary = "----xtbtestboundary"
    parts = [
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="currency"\r\n\r\n{currency}\r\n'
        ).encode(),
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="archive"; filename="history.zip"\r\n'
            f"Content-Type: application/zip\r\n\r\n"
        ).encode()
        + payload
        + b"\r\n",
    ]
    if no_live:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="no_live"\r\n\r\n1\r\n'.encode()
        )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


def test_get_upload_page_and_post_zip(tmp_path: Path, monkeypatch):
    seen: dict[str, object] = {}

    def fake_generate_report(data_dir, output_dir, currency="pln", use_cache=True, refresh_latest=True):
        files = discover_export_files(data_dir)
        seen["files"] = sorted(path.name for path in files)
        seen["currency"] = currency
        seen["refresh_latest"] = refresh_latest
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report = output_dir / "report.html"
        report.write_text("<html><title>Raport portfela XTB</title><p>ok</p></html>", encoding="utf-8")
        return report

    monkeypatch.setattr("xtb_analyzer.web.generate_report", fake_generate_report)
    handler = make_handler(tmp_path / "uploads", refresh_latest=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with urlopen(f"http://127.0.0.1:{port}/") as response:
            page = response.read().decode("utf-8")
        assert "Archiwum ZIP" in page

        body, content_type = _multipart(_history_zip(tmp_path))
        request = Request(
            f"http://127.0.0.1:{port}/upload",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        with urlopen(request) as response:
            report = response.read().decode("utf-8")
        assert "Raport portfela XTB" in report
        assert seen["files"] == [
            "EUR_22222222_2006-01-01_2026-08-01.csv",
            "USD_11111111_2006-01-01_2026-10-08.csv",
        ]
        assert seen["currency"] == "pln"
        assert seen["refresh_latest"] is False
    finally:
        server.shutdown()
        server.server_close()


def test_upload_rejects_non_zip(tmp_path: Path):
    handler = make_handler(tmp_path / "uploads")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        body, content_type = _multipart(b"not-a-zip")
        request = Request(
            f"http://127.0.0.1:{port}/upload",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            urlopen(request)
        except HTTPError as exc:
            page = exc.read().decode("utf-8")
            assert exc.code == 400
        else:
            raise AssertionError("expected HTTP 400")
        assert "ZIP" in page
    finally:
        server.shutdown()
        server.server_close()
