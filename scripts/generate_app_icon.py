"""Draw the application icon at each shipped size.

The mark is a navy squircle with a cyan portfolio path. Each size is drawn
directly so the 16px icon stays a bold chart rather than a blurred reduction.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "xtb_analyzer" / "assets"
ICO_SIZES = (16, 32, 48, 64, 128, 256)
PNG_SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)

NAVY = (11, 18, 32, 255)
CYAN = (34, 211, 238, 255)
BENCH = (148, 163, 184, 230)
BASELINE = (22, 78, 99, 255)
ENDPOINT = (224, 242, 254, 255)

PORTFOLIO = ((0.16, 0.70), (0.34, 0.54), (0.48, 0.60), (0.66, 0.34), (0.84, 0.18))
BENCHMARK = ((0.16, 0.80), (0.40, 0.72), (0.62, 0.64), (0.86, 0.56))


def _xy(size: int, point: tuple[float, float]) -> tuple[int, int]:
    return (round(point[0] * (size - 1)), round(point[1] * (size - 1)))


def draw_icon(size: int) -> Image.Image:
    """Paint one icon. Stroke width tracks the canvas so small sizes stay legible."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = max(2, round(size * 0.22))
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=NAVY)
    stroke = max(2, round(size * 0.075))
    if size >= 32:
        baseline_y = round(0.78 * (size - 1))
        draw.line(
            [_xy(size, (0.18, 0.78)), (round(0.84 * (size - 1)), baseline_y)],
            fill=BASELINE,
            width=max(1, stroke // 3),
        )
        draw.line([_xy(size, point) for point in BENCHMARK], fill=BENCH, width=max(1, stroke // 2))
    portfolio = [_xy(size, point) for point in PORTFOLIO]
    draw.line(portfolio, fill=CYAN, width=stroke, joint="curve")
    end_x, end_y = portfolio[-1]
    dot = max(2, round(size * 0.065))
    draw.ellipse((end_x - dot, end_y - dot, end_x + dot, end_y + dot), fill=ENDPOINT)
    return image


def save_ico(path: Path, images: dict[int, Image.Image]) -> None:
    """Write a PNG-compressed ICO that keeps each pre-rendered size."""
    blobs: list[tuple[int, bytes]] = []
    for size in ICO_SIZES:
        buffer = io.BytesIO()
        images[size].save(buffer, format="PNG")
        blobs.append((size, buffer.getvalue()))
    header = struct.pack("<HHH", 0, 1, len(blobs))
    entries = bytearray()
    body = bytearray()
    offset = 6 + 16 * len(blobs)
    for size, blob in blobs:
        stored = 0 if size >= 256 else size
        entries.extend(struct.pack("<BBBBHHII", stored, stored, 0, 0, 1, 32, len(blob), offset))
        body.extend(blob)
        offset += len(blob)
    path.write_bytes(header + bytes(entries) + bytes(body))


def save_icns(path: Path, images: dict[int, Image.Image]) -> None:
    """Write an ICNS whose chunks are the PNG sizes macOS packaging expects."""
    ostypes = {
        16: (b"icp4",),
        32: (b"icp5", b"ic11"),
        64: (b"icp6", b"ic12"),
        128: (b"ic07",),
        256: (b"ic08", b"ic13"),
        512: (b"ic09", b"ic14"),
        1024: (b"ic10",),
    }
    chunks = bytearray()
    for size, types in ostypes.items():
        buffer = io.BytesIO()
        images[size].save(buffer, format="PNG")
        blob = buffer.getvalue()
        for ostype in types:
            chunks.extend(ostype + struct.pack(">I", 8 + len(blob)) + blob)
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(chunks)) + bytes(chunks))


def save_preview(path: Path, images: dict[int, Image.Image]) -> None:
    """Place the 256px and 32px icons on one navy plate."""
    plate = Image.new("RGB", (360, 280), (9, 15, 29))
    plate.paste(images[256], (16, 12), images[256])
    plate.paste(images[32], (292, 124), images[32])
    path.parent.mkdir(parents=True, exist_ok=True)
    plate.save(path)


def main() -> None:
    images = {size: draw_icon(size) for size in PNG_SIZES}
    ASSETS.mkdir(parents=True, exist_ok=True)
    images[1024].save(ASSETS / "app.png")
    save_ico(ASSETS / "app.ico", images)
    save_icns(ASSETS / "app.icns", images)
    print(f"Wrote {ASSETS / 'app.ico'}, {ASSETS / 'app.png'}, {ASSETS / 'app.icns'}")


if __name__ == "__main__":
    main()
