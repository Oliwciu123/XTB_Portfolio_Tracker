"""Safely unpack an XTB multi-account history zip."""

from __future__ import annotations

import zipfile
from pathlib import Path

MAX_ZIP_BYTES = 64 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_ZIP_MEMBERS = 200
_SKIP_PREFIXES = ("__MACOSX/",)


class ZipImportError(ValueError):
    """The upload is not a usable XTB history archive."""


def extract_xtb_zip(source: str | Path, dest: str | Path) -> Path:
    """Extract ``source`` into ``dest``, rejecting path traversal and oversized archives.

    Directory entries, macOS metadata, and empty names are skipped. Member paths
    may use either ``/`` or ``\\`` separators.
    """
    source = Path(source)
    dest = Path(dest)
    size = source.stat().st_size if source.exists() else 0
    if size > MAX_ZIP_BYTES:
        raise ZipImportError(f"Archive contains {size} bytes; limit is {MAX_ZIP_BYTES} bytes.")
    if size < 22:
        raise ZipImportError("File is too small to be a ZIP archive.")

    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()

    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise ZipImportError("This is not a valid ZIP archive.") from exc

    extracted = 0
    total_uncompressed = 0
    with archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if len(members) > MAX_ZIP_MEMBERS:
            raise ZipImportError(
                f"Archive contains too many files ({len(members)}; limit {MAX_ZIP_MEMBERS})."
            )
        for info in members:
            name = info.filename.replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            if name.startswith(_SKIP_PREFIXES) or "/__MACOSX/" in f"/{name}":
                continue
            if name.rsplit("/", 1)[-1].startswith("."):
                continue
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise ZipImportError("Uncompressed archive exceeds the size limit.")
            target = _safe_member_path(dest_resolved, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as src, target.open("wb") as out:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            extracted += 1

    if extracted == 0:
        raise ZipImportError("ZIP archive contains no files.")
    return dest_resolved


def _safe_member_path(dest: Path, name: str) -> Path:
    parts = [part for part in name.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ZipImportError(f"Unsafe archive path: {name}")
    target = dest.joinpath(*parts).resolve()
    if target != dest and dest not in target.parents:
        raise ZipImportError(f"Unsafe archive path: {name}")
    return target
