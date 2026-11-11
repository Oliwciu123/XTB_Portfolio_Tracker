"""Tests for Deposit Analytics, Interactive Metric Definitions, and Playwright UI behaviors."""

from __future__ import annotations

import re
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
        assert "m-expr" in str(item["formula_html"]), f"Missing typeset formula_html for {key}"
        assert item["formula_tex"], f"Missing formula_tex for {key}"
        assert len(str(item["summary"])) >= 20, f"Summary too short for {key}"
        assert len(str(item["explanation"])) >= 40, f"Explanation too short for {key}"
        assert any(ch.isdigit() for ch in str(item["example"])), f"Example lacks numbers for {key}"
        for rng in item["ranges"]:  # type: ignore[union-attr]
            assert rng["tone"] in {"pos", "neutral", "neg"}


def test_windows_shortcut_powershell_command_builder(tmp_path: Path):
    """Verify Windows Desktop shortcut script escapes paths and configures icon/working dir."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "create_desktop_shortcut",
        EXAMPLES.parent / "scripts" / "create_desktop_shortcut.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    ps = mod.build_powershell_shortcut_script(
        shortcut_path=tmp_path / "Oliwier's Desktop" / "XTB Portfolio Analyzer.lnk",
        exe_path=tmp_path / "dist" / "XTBPortfolioAnalyzer" / "XTBPortfolioAnalyzer.exe",
        working_dir=tmp_path / "dist" / "XTBPortfolioAnalyzer",
        icon_path=tmp_path / "dist" / "XTBPortfolioAnalyzer" / "app.ico",
    )
    assert "WScript.Shell" in ps
    assert "Oliwier''s Desktop" in ps
    assert "app.ico,0" in ps
    assert "XTBPortfolioAnalyzer.exe" in ps


def test_rendered_report_includes_deposits_definitions_and_pit38_sections(tmp_path: Path):
    """Self-contained HTML includes v1.2.0 sections, Warsaw time, 5s polling, and clean chrome."""
    from xtb_analyzer.parser import discover_export_files, load_accounts
    from xtb_analyzer.report import build_live_payload, collect_report_data

    market = MarketData.from_examples(EXAMPLES)
    accounts = load_accounts(discover_export_files(EXAMPLES))
    data = collect_report_data(accounts, market_data=market, refresh_latest=False)
    live = build_live_payload(data)
    assert live["as_of"].endswith(("CET)", "CEST)"))
    assert str(live["time_label"]).endswith(("CET", "CEST"))

    report_path = generate_report(EXAMPLES, tmp_path, market_data=market, refresh_latest=False)
    html = report_path.read_text(encoding="utf-8")

    assert "id='deposits'" in html
    assert 'id="chart-deposits"' in html
    assert "id='deposits-top10-table'" in html
    assert "Operation details" not in html
    assert 'id="data-source-notice"' not in html
    assert "<footer>" not in html
    assert 'id="about-report-btn"' in html
    assert "id='about-popover'" in html
    assert "const POLL_INTERVAL_MS = 5000;" in html
    assert "id='metric-popover'" in html
    assert "id='chart-hover-card'" in html
    assert "data-metric-key='sharpe'" in html
    assert "data-metric-key='win_rate'" in html
    assert "data-metric-key='profit_factor'" in html
    assert "id='pit38'" in html
    assert "id='pit38-fifo-table'" in html
    assert "id='pit38-div-table'" in html
    assert "__METRIC_DEFINITIONS_JSON__" not in html
    assert "__INDICATOR_GUIDES_JSON__" not in html
    assert "__DEPOSITS_JSON__" not in html
    assert "__PIT38_JSON__" not in html
    assert "id='indicator-guide'" in html
    assert "XTB Portfolio Tracker v1.3.0" in html
    assert not re.search(r"""<script[^>]+src=['"]https?:""", html)
    assert not re.search(r"""<link[^>]+href=['"]https?:""", html)


def test_playwright_interactive_deposits_definitions_and_pit38(tmp_path: Path):
    """End-to-end browser verification of v1.2.0 zoom, math, collapsible tables, and PIT-38."""
    playwright_mod = pytest.importorskip("playwright.sync_api")
    market = MarketData.from_examples(EXAMPLES)
    report_path = generate_report(EXAMPLES, tmp_path, market_data=market, refresh_latest=False)

    with playwright_mod.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Playwright Chromium browser binary is not installed")
            raise
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(report_path.resolve().as_uri())
        page.wait_for_function(
            "() => [...document.querySelectorAll('.js-plotly-plot')].length === 8"
        )

        # 0. Click-to-activate chart wheel zoom: off by default, on after click, off on Escape
        assert page.evaluate(
            "() => [...document.querySelectorAll('.js-plotly-plot')].every(p => !p._context.scrollZoom)"
        )
        nav_chart_box = page.locator('[data-chart-box="chart-nav"]')
        nav_chart_box.locator(".nsewdrag").first.click()
        assert "is-zoom-active" in (nav_chart_box.get_attribute("class") or "")
        assert page.evaluate(
            "() => document.getElementById('chart-nav')._context.scrollZoom === true"
        )
        page.keyboard.press("Escape")
        assert "is-zoom-active" not in (nav_chart_box.get_attribute("class") or "")
        assert page.evaluate(
            "() => document.getElementById('chart-nav')._context.scrollZoom === false"
        )

        # 1. Short indicator popover, then the in-report MathJax guide.
        sharpe_btn = page.locator('[data-metric-key="sharpe"]').first
        sharpe_btn.click()
        popover = page.locator("#metric-popover")
        assert popover.is_visible()
        assert page.locator("#metric-popover-formula").count() == 0
        assert "Sharpe Ratio" in popover.inner_text()
        assert "Learn more" in popover.inner_text()
        assert "1.25" not in popover.inner_text()
        dashboard_sharpe = (
            sharpe_btn.locator("xpath=ancestor::div[contains(@class, 'stat ')][1]")
            .locator(".stat-value")
            .inner_text()
            .strip()
        )
        assert dashboard_sharpe in popover.inner_text()
        page.locator("#metric-popover-learn").click()
        guide = page.locator("#indicator-guide")
        assert guide.is_visible()
        page.wait_for_function("() => document.querySelector('#guide-formula svg path')")
        assert "1.25" in guide.inner_text()
        assert "1.0 – 2.0" in guide.inner_text()
        assert dashboard_sharpe in page.locator("#guide-value").inner_text()
        assert dashboard_sharpe in page.locator("#guide-steps .is-result").inner_text()
        formula_ok = page.evaluate(
            """() => {
                const host = document.getElementById('guide-formula');
                const svg = host.querySelector('svg');
                const glyphs = [...svg.querySelectorAll('use')].filter(node => node.getBoundingClientRect().width > 0);
                const svgBox = svg.getBoundingClientRect();
                const clipped = glyphs.some(node => {
                    const box = node.getBoundingClientRect();
                    return box.top < svgBox.top - 2 || box.bottom > svgBox.bottom + 2;
                });
                return {glyphs: glyphs.length, svgH: svgBox.height, hostH: host.getBoundingClientRect().height, clipped};
            }"""
        )
        assert formula_ok["glyphs"] >= 8
        assert formula_ok["svgH"] > 24
        assert formula_ok["hostH"] + 1 >= formula_ok["svgH"]
        assert not formula_ok["clipped"]
        page.locator("#guide-next").click()
        assert page.locator("#guide-title").inner_text() != "Sharpe Ratio"
        page.locator("#guide-prev").click()
        assert "Sharpe" in page.locator("#guide-title").inner_text()
        page.keyboard.press("Escape")
        assert guide.is_hidden()

        def assert_single_hover(plot_id: str, section: str) -> None:
            page.locator(f'[data-target="{section}"]').click()
            page.wait_for_timeout(250)
            page.locator(f"#{plot_id}").scroll_into_view_if_needed()
            drag = page.locator(f"#{plot_id} .nsewdrag")
            box = drag.bounding_box() if drag.count() else None
            if box is None:
                slice_box = page.locator(f"#{plot_id} .slice").first.bounding_box()
                assert slice_box is not None, plot_id
                page.mouse.move(
                    slice_box["x"] + slice_box["width"] * 0.5,
                    slice_box["y"] + slice_box["height"] * 0.5,
                )
            else:
                page.mouse.move(box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.45)
            try:
                page.wait_for_function(
                    """() => {
                        const card = document.getElementById('chart-hover-card');
                        return card && !card.hidden && card.querySelector('.chc-val');
                    }""",
                    timeout=8000,
                )
            except Exception as exc:
                raise AssertionError(
                    f"custom hover card did not stay visible on {plot_id}"
                ) from exc
            native = page.evaluate(
                """() => [...document.querySelectorAll('.hoverlayer .hovertext, .hoverlayer .legend')].filter(node => {
                    const box = node.getBoundingClientRect();
                    return box.width > 0.5 || box.height > 0.5;
                }).length"""
            )
            assert native == 0, f"Native Plotly hover label is visible on {plot_id}"

        for plot_id, section in (
            ("chart-nav", "overview"),
            ("chart-monthly", "overview"),
            ("chart-deposits", "deposits"),
            ("chart-benchmark", "benchmarks"),
            ("chart-pnl", "holdings"),
            ("chart-holdings", "holdings"),
            ("chart-currency", "holdings"),
            ("chart-sector", "holdings"),
        ):
            assert_single_hover(plot_id, section)
        page.mouse.move(2, 2)

        # 2. Deposit Analytics: collapsible preview (10 of 72 initially), no Operation details col
        page.locator('[data-target="deposits"]').click()
        assert page.locator("#deposits").is_visible()
        dep_headers = page.locator("#deposits-ops-table thead th").all_inner_texts()
        assert "Operation details" not in dep_headers
        assert page.locator("#deposits-ops-table tbody tr:visible").count() == 10
        assert (
            "Showing 10 of 72 rows"
            in page.locator("#deposits-ops-wrap .table-collapse-bar").inner_text()
        )
        page.locator("#deposits-ops-wrap .table-expand-btn").click()
        assert page.locator("#deposits-ops-table tbody tr:visible").count() == 72

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

        # 3. Polish PIT-38: collapsed FIFO table (5 of 11 rows in 2026 YTD) + expand/collapse
        page.locator('[data-target="pit38"]').click()
        assert page.locator("#pit38").is_visible()
        assert page.locator("#pit38-fifo-table tbody tr:visible").count() == 5
        assert (
            "Showing 5 of 11 rows"
            in page.locator("#pit38-fifo-wrap .table-collapse-bar").inner_text()
        )
        page.locator("#pit38-fifo-wrap .table-expand-btn").click()
        assert page.locator("#pit38-fifo-table tbody tr:visible").count() == 11
        page.locator("#pit38-fifo-wrap .table-expand-btn").click()
        assert page.locator("#pit38-fifo-table tbody tr:visible").count() == 5

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
