"""Indicator guides must use this portfolio's numbers and match the dashboard."""

from __future__ import annotations

import html
import math
import re
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from xtb_analyzer import __version__
from xtb_analyzer.definitions import METRIC_DEFINITIONS
from xtb_analyzer.indicator_guides import build_indicator_guides
from xtb_analyzer.market_data import MarketData
from xtb_analyzer.parser import discover_export_files, load_accounts
from xtb_analyzer.report import collect_report_data, generate_report
from xtb_analyzer.risk import TRADING_DAYS

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
ROOT = EXAMPLES.parent


def _card_values(report_html: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for part in report_html.split("data-metric-key='")[1:]:
        key, rest = part.split("'", 1)
        if key in found:
            continue
        match = re.search(r"class='stat-value'>(.*?)</div>", rest)
        if match:
            found[key] = html.unescape(match.group(1)).strip()
    return found


def test_guides_reconcile_with_dashboard_cards(tmp_path: Path):
    market = MarketData.from_examples(EXAMPLES)
    accounts = load_accounts(discover_export_files(EXAMPLES))
    data = collect_report_data(accounts, market_data=market, refresh_latest=False)
    guides = build_indicator_guides(data)
    assert list(guides["order"]) == list(METRIC_DEFINITIONS)
    report_path = generate_report(EXAMPLES, tmp_path, market_data=market, refresh_latest=False)
    cards = _card_values(report_path.read_text(encoding="utf-8"))

    daily = data.twr_returns.replace([np.inf, -np.inf], np.nan).dropna()
    sharpe = math.sqrt(TRADING_DAYS) * float(daily.mean()) / float(daily.std(ddof=1))
    volatility = float(daily.std(ddof=1)) * math.sqrt(TRADING_DAYS)
    roi = float(data.measures.gain) / float(data.measures.invested)
    assert sharpe == pytest.approx(float(data.risk.sharpe), rel=1e-9, abs=1e-9)
    assert volatility == pytest.approx(float(data.risk.volatility_annual), rel=1e-9, abs=1e-9)
    assert roi == pytest.approx(float(data.measures.roi), rel=1e-12, abs=1e-12)
    assert guides["indicators"]["sharpe"]["check"]["result"] == pytest.approx(sharpe)
    assert guides["indicators"]["volatility"]["check"]["result"] == pytest.approx(volatility)
    assert guides["indicators"]["roi"]["check"]["result"] == pytest.approx(roi)

    xirr = guides["indicators"]["mwr_xirr"]["check"]["xirr"]
    days = guides["indicators"]["mwr_xirr"]["check"]["days"]
    if xirr is not None:
        period = (1 + xirr) ** (days / 365.25) - 1
        assert guides["indicators"]["mwr_xirr"]["check"]["result"] == pytest.approx(
            period, rel=1e-9, abs=1e-9
        )

    for key, guide in guides["indicators"].items():
        assert guide["steps"][-1]["value"] == guide["display_value"]
        assert guide["formula_tex"]
        assert key in cards, key
        assert cards[key] == guide["display_value"], (
            f"{key}: card {cards[key]!r} guide {guide['display_value']!r}"
        )
        active = [item for item in guide["ranges"] if item["active"]]
        assert len(active) <= 1


def test_version_is_1_3_0():
    assert __version__ == "1.3.0"


def test_app_icon_has_required_sizes():
    import struct

    blob = (ROOT / "src" / "xtb_analyzer" / "assets" / "app.ico").read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", blob, 0)
    assert (reserved, kind) == (0, 1)
    sizes = set()
    for index in range(count):
        width, height, _colors, _res, _planes, _bits, nbytes, offset = struct.unpack_from(
            "<BBBBHHII", blob, 6 + 16 * index
        )
        sizes.add((width or 256, height or 256))
        assert blob[offset : offset + 8] == b"\x89PNG\r\n\x1a\n"
        assert nbytes > 0
    assert sizes >= {(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}
    png = Image.open(ROOT / "src" / "xtb_analyzer" / "assets" / "app.png")
    assert png.size == (1024, 1024)
    icns = (ROOT / "src" / "xtb_analyzer" / "assets" / "app.icns").read_bytes()
    assert icns.startswith(b"icns")
    for ostype in (b"ic07", b"ic08", b"ic09", b"ic10", b"ic11", b"ic12", b"icp4", b"icp5"):
        assert ostype in icns
