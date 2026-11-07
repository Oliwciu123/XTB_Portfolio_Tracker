"""Published screenshots must be real, readable and reachable from the README."""

import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def test_readme_image_links_exist_and_are_sharp():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme)
    local = [ROOT / image for image in images if not image.startswith("https://")]
    assert local, "README must show the actual application"
    assert ROOT / "docs/images/dashboard.png" in local
    for path in local:
        assert path.is_file(), f"Broken README image: {path}"
        with Image.open(path) as image:
            assert image.format == "PNG"
            assert image.width >= 1600, f"Screenshot is too small: {path.name}"
            image.verify()
        assert path.stat().st_size < 1_000_000, path.name
