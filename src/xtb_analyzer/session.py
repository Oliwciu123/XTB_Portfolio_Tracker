"""Turn an uploaded XTB history zip into the standard HTML report."""

from __future__ import annotations

from pathlib import Path

from xtb_analyzer.report import generate_report
from xtb_analyzer.zip_import import extract_xtb_zip


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


def report_from_zip_path(
    zip_path: str | Path,
    work_dir: str | Path,
    *,
    currency: str = "pln",
    use_cache: bool = True,
    refresh_latest: bool = True,
) -> Path:
    return report_from_zip_bytes(
        Path(zip_path).read_bytes(),
        work_dir,
        currency=currency,
        use_cache=use_cache,
        refresh_latest=refresh_latest,
    )
