"""Desktop app builds the same report from a history zip. No private exports."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from xtb_analyzer.parser import discover_export_files
from xtb_analyzer.session import report_from_zip_bytes

FIXTURES = Path(__file__).parent / "fixtures"


def _history_zip(tmp_path: Path) -> Path:
    usd = FIXTURES / "xtb_currency_prefix_cash_ops.csv"
    eur = usd.read_text(encoding="utf-8").replace("11111111", "22222222").replace("PLN to USD", "PLN to EUR")
    pln = (
        usd.read_text(encoding="utf-8")
        .replace("11111111", "33333333")
        .replace("PLN to USD", "EUR to PLN")
        .replace("EX.US", "PKO.PL")
    )
    archive = tmp_path / "history.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(usd, "11111111/USD_11111111_2006-01-01_2026-10-08.csv")
        zf.writestr("22222222/EUR_22222222_2006-01-01_2026-08-01.csv", eur)
        zf.writestr("33333333/PLN_33333333_2006-01-01_2026-10-08.csv", pln)
    return archive


def test_zip_bytes_run_existing_report_pipeline(tmp_path: Path, monkeypatch):
    seen: dict[str, object] = {}

    def fake_generate_report(data_dir, output_dir, currency="pln", use_cache=True, refresh_latest=True, on_progress=None):
        files = discover_export_files(data_dir)
        seen["files"] = sorted(path.name for path in files)
        seen["currencies"] = sorted(path.name.split("_", 1)[0] for path in files)
        seen["currency"] = currency
        seen["refresh_latest"] = refresh_latest
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report = output_dir / "report.html"
        report.write_text("<html><h1>Raport portfela XTB</h1><h2>Podsumowanie</h2></html>", encoding="utf-8")
        return report

    monkeypatch.setattr("xtb_analyzer.session.generate_report", fake_generate_report)
    archive = _history_zip(tmp_path)
    report = report_from_zip_bytes(
        archive.read_bytes(),
        tmp_path / "work",
        currency="pln",
        refresh_latest=False,
    )
    assert "Raport portfela XTB" in report.read_text(encoding="utf-8")
    assert seen["currencies"] == ["EUR", "PLN", "USD"]
    assert seen["currency"] == "pln"
    assert seen["refresh_latest"] is False


def test_windows_drop_fills_a_zip_path():
    from xtb_analyzer.desktop import parse_dropped_paths

    assert parse_dropped_paths("{C:/Users/me/history.zip}") == ["C:/Users/me/history.zip"]
    assert parse_dropped_paths("{C:\\Users\\me\\a.zip} {C:\\Users\\me\\notes.txt}") == ["C:\\Users\\me\\a.zip"]


def test_window_has_progress_and_no_offline_switch(tmp_path: Path, monkeypatch):
    pytest.importorskip("tkinter")
    import tkinter as tk

    from xtb_analyzer.desktop import AnalyzerApp

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    app = AnalyzerApp(root)
    texts: list[str] = []

    def walk(widget) -> None:
        try:
            texts.append(str(widget.cget("text")))
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            walk(child)

    walk(app.root)
    blob = " ".join(texts)
    assert "przyszłości" not in blob
    assert "bieżących notowań" not in blob
    assert "historią kont" in blob
    assert app.progress is not None
    monkeypatch.setattr(app, "_start", lambda path: None)
    app._choose(str(tmp_path / "history.zip"))
    assert app.zip_path.get().endswith("history.zip")
    assert app._drop_label.cget("text") == "history.zip"
    root.destroy()


def test_window_load_zip_without_opening_report(tmp_path: Path, monkeypatch):
    pytest.importorskip("tkinter")
    import tkinter as tk

    from xtb_analyzer.desktop import AnalyzerApp

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()

    def fake_generate_report(data_dir, output_dir, currency="pln", use_cache=True, refresh_latest=True, on_progress=None):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report = output_dir / "report.html"
        report.write_text("<html><h2>Podsumowanie</h2></html>", encoding="utf-8")
        return report

    monkeypatch.setattr("xtb_analyzer.session.generate_report", fake_generate_report)
    app = AnalyzerApp(root)
    report = app.load_zip(
        _history_zip(tmp_path),
        currency="eur",
        refresh_latest=False,
        present=False,
        upload_root=tmp_path / "uploads",
    )
    assert report.is_file()
    assert app.report_path == report
    root.destroy()
