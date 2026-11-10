"""Tests for Deposit Analytics, Interactive Metric Definitions, and Playwright UI behaviors."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from xtb_analyzer.charts import plot_monthly_deposits
from xtb_analyzer.definitions import METRIC_DEFINITIONS, definitions_json_map
from xtb_analyzer.flows import (
    aggregate_deposits_monthly,
    extract_deposit_operations,
    filter_deposit_operations,
    top_deposit_months,
)
from xtb_analyzer.market_data import MarketData
from xtb_analyzer.models import Account, Transaction
from xtb_analyzer.report import generate_report

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _dep_tx(
    tx_id: str,
    acc: str,
    curr: str,
    ts: str,
    amount: float,
    comment: str = "",
    kind: str = "transfer_in",
) -> Transaction:
    return Transaction(
        id=tx_id,
        account_id=acc,
        currency=curr,
        type=kind,  # type: ignore[arg-type]
        timestamp=datetime.fromisoformat(ts),
        symbol=None,
        amount=Decimal(str(amount)),
        comment=comment,
    )


def test_deposit_aggregations_single_year_multi_year_and_top10():
    """Verify total, single-year, multi-year combinations, month filters, and Top 10 ranking."""
    fx = pd.DataFrame(
        {
            "USDPLN": [4.0, 4.0],
            "EURPLN": [4.5, 4.5],
            "EURUSD": [1.125, 1.125],
            "USDEUR": [0.888889, 0.888889],
        },
        index=pd.to_datetime(["2023-01-01", "2026-12-31"]),
    )
    pln_acc = Account(
        account_id="pln-1",
        currency="PLN",
        transactions=[
            _dep_tx("1", "pln-1", "PLN", "2023-01-10 10:00:00", 5000),
            _dep_tx("2", "pln-1", "PLN", "2023-03-15 10:00:00", 2000),
            _dep_tx("3", "pln-1", "PLN", "2024-01-12 10:00:00", 3000),
            _dep_tx("4", "pln-1", "PLN", "2024-06-20 10:00:00", 1500),
            _dep_tx("5", "pln-1", "PLN", "2025-01-08 10:00:00", 4000),
            _dep_tx("6", "pln-1", "PLN", "2025-03-18 10:00:00", 2500),
            _dep_tx("7", "pln-1", "PLN", "2025-03-25 14:00:00", 1200),
            # Withdrawals must not inflate inbound deposit analytics
            _dep_tx("w1", "pln-1", "PLN", "2025-04-01 10:00:00", -800, kind="transfer_out"),
        ],
    )
    usd_acc = Account(
        account_id="usd-1",
        currency="USD",
        transactions=[
            # Direct $500 external deposit @ 4.00 PLN/USD => 2000 PLN in Jan 2025
            _dep_tx(
                "8",
                "usd-1",
                "USD",
                "2025-01-20 11:00:00",
                500,
                comment="Direct USD bank deposit",
            ),
            # Internal conversion from the included PLN account must NOT be double-counted
            _dep_tx(
                "9",
                "usd-1",
                "USD",
                "2025-02-01 11:00:00",
                250,
                comment="Currency conversion, PLN to USD, Exchange rate:0.25",
            ),
        ],
    )

    ops = extract_deposit_operations([pln_acc, usd_acc], currency="pln", fx=fx)
    assert len(ops) == 8
    # Total deposited: 5000 + 2000 + 3000 + 1500 + 4000 + 2500 + 1200 + 2000 = 21200 PLN
    assert ops["amount"].sum() == pytest.approx(21200.0)

    # Calendar month sum across ALL years: Jan = 5000 (2023) + 3000 (2024) + 6000 (2025) = 14000 PLN
    cal_all = aggregate_deposits_monthly(ops, by_calendar_month=True)
    assert len(cal_all) == 12
    jan_all = cal_all.loc[cal_all["month"] == 1, "total_amount"].iloc[0]
    mar_all = cal_all.loc[cal_all["month"] == 3, "total_amount"].iloc[0]
    assert jan_all == pytest.approx(14000.0)
    assert mar_all == pytest.approx(2000.0 + 3700.0)

    # Multi-year combination: 2023 + 2025 (excluding 2024!)
    cal_23_25 = aggregate_deposits_monthly(ops, years=[2023, 2025], by_calendar_month=True)
    assert cal_23_25.loc[cal_23_25["month"] == 1, "total_amount"].iloc[0] == pytest.approx(11000.0)
    assert cal_23_25.loc[cal_23_25["month"] == 6, "total_amount"].iloc[0] == pytest.approx(0.0)

    # Individual month inspection: March 2025 has 2 operations totaling 3700 PLN
    mar_2025 = filter_deposit_operations(ops, year_month="2025-03")
    assert len(mar_2025) == 2
    assert mar_2025["amount"].sum() == pytest.approx(3700.0)

    # Top 10 ranking reactive to scope
    top_all = top_deposit_months(ops, limit=10)
    assert list(top_all["year_month"].iloc[:3]) == ["2025-01", "2023-01", "2025-03"]
    assert list(top_all["total_amount"].iloc[:3]) == pytest.approx([6000.0, 5000.0, 3700.0])

    top_2024_only = top_deposit_months(ops, years=[2024], limit=10)
    assert list(top_2024_only["year_month"]) == ["2024-01", "2024-06"]
    assert top_2024_only["share_pct"].sum() == pytest.approx(1.0)

    fig = plot_monthly_deposits(ops, currency="pln", years=[2023, 2025])
    assert len(fig.data) == 1
    assert sum(fig.data[0].y) == pytest.approx(16700.0)


def test_metric_definitions_catalog_complete_and_valid():
    """Every KPI definition must provide plain-English explanation, numerical example, and valid bands."""
    required_keys = {
        "nav",
        "contributions",
        "profit_loss",
        "roi",
        "mwr_xirr",
        "twr",
        "volatility",
        "sharpe",
        "sortino",
        "alpha",
        "beta",
        "max_drawdown",
        "calmar",
        "var_95",
        "win_rate",
        "profit_factor",
        "pit38_revenue",
        "pit38_costs",
        "pit38_income",
        "pit38_wht_credit",
        "pit38_total_tax",
    }
    assert required_keys <= set(METRIC_DEFINITIONS.keys())
    serialized = definitions_json_map()
    for key, item in serialized.items():
        assert item["title"], f"Missing title for {key}"
        assert item["formula"], f"Missing formula for {key}"
        assert len(str(item["explanation"])) >= 40, f"Explanation too short for {key}"
        assert any(ch.isdigit() for ch in str(item["example"])), f"Example lacks numbers for {key}"
        for rng in item["ranges"]:  # type: ignore[union-attr]
            assert rng["tone"] in {"pos", "neutral", "neg"}


def test_playwright_interactive_deposits_definitions_and_pit38(tmp_path: Path):
    """End-to-end browser verification of Deposits filters, Metric Popovers, and PIT-38 switching."""
    playwright_mod = pytest.importorskip("playwright.sync_api")
    market = MarketData.from_examples(EXAMPLES)
    report_path = generate_report(EXAMPLES, tmp_path, market_data=market, refresh_latest=False)

    with playwright_mod.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(report_path.resolve().as_uri())

        # 1. Interactive Metric Definitions: click Sharpe ratio info button, verify content, close with Escape
        sharpe_btn = page.locator('[data-metric-key="sharpe"]').first
        sharpe_btn.click()
        popover = page.locator("#metric-popover")
        assert popover.is_visible()
        assert "Sharpe Ratio" in popover.inner_text()
        assert "1.25" in popover.inner_text()
        assert "1.0 – 2.0" in popover.inner_text()
        page.keyboard.press("Escape")
        assert popover.is_hidden()

        # 2. Deposit Analytics: switch tab, combine 2024 + 2025, inspect March, verify Top 10 & operations
        page.locator('[data-target="deposits"]').click()
        assert page.locator("#deposits").is_visible()
        page.locator('[data-dep-year="2024"]').click()
        page.locator('[data-dep-year="2025"]').click()
        banner_txt = page.locator("#dep-scope-banner").inner_text()
        assert "2024 + 2025" in banner_txt
        top10_txt = page.locator("#deposits-top10-table").inner_text()
        assert "2021-01" not in top10_txt
        assert "2024-01" in top10_txt

        # Switch to calendar-month aggregation and filter down to March
        page.locator('[data-dep-grouping="calendar"]').click()
        page.locator('[data-dep-month="3"]').click()
        ops_rows = page.locator("#deposits-ops-table tbody tr")
        assert ops_rows.count() == 2  # Mar 2024 + Mar 2025

        # 3. Polish PIT-38: switch tab, verify 2026 YTD default & switch to 2024 loss year
        page.locator('[data-target="pit38"]').click()
        assert page.locator("#pit38").is_visible()
        cards_2026 = page.locator("#pit38-cards-wrap").inner_text()
        assert "2026 YTD estimate" in cards_2026
        assert "1,561.30 PLN" in cards_2026

        page.locator('[data-pit-year="2024"]').click()
        cards_2024 = page.locator("#pit38-cards-wrap").inner_text()
        assert "-712.72 PLN" in cards_2024
        assert "35.82 PLN" in cards_2024

        # Mobile viewport usability check for metric definition modal
        page.set_viewport_size({"width": 390, "height": 844})
        pit_info = page.locator('#pit38-cards-wrap [data-metric-key="pit38_wht_credit"]').first
        pit_info.click()
        assert popover.is_visible()
        assert "Foreign Withholding Tax Credit" in popover.inner_text()
        page.locator("#metric-popover-close").click()
        assert popover.is_hidden()

        assert not errors, f"Browser page errors: {errors}"
        browser.close()
