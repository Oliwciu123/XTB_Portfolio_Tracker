"""Capture genuine application and Plotly screenshots using fictional, offline data.

Run ``uv run playwright install chromium`` once, then
``uv run python scripts/make_screenshots.py`` from the repository root.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

from xtb_analyzer.desktop import _DESKTOP_START_HTML
from xtb_analyzer.market_data import MarketData
from xtb_analyzer.report import generate_report

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--channel", default=None, help="Optional installed browser: chrome or msedge"
    )
    args = parser.parse_args()
    images = ROOT / "docs" / "images"
    images.mkdir(parents=True, exist_ok=True)
    folder = ROOT / "examples"
    report = generate_report(
        data_dir=folder,
        output_dir=ROOT / "output" / "demo",
        market_data=MarketData.from_examples(folder),
        refresh_latest=False,
    )
    start_screen = report.parent / "desktop-start.html"
    start_screen.write_text(_DESKTOP_START_HTML, encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=args.channel)
        page = browser.new_page(viewport={"width": 1440, "height": 1080}, device_scale_factor=1)
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        # Screenshots must never depend on external fonts, quotes, or user data.
        page.route("http://**/*", lambda route: route.abort())
        page.route("https://**/*", lambda route: route.abort())
        page.goto(report.resolve().as_uri())
        page.locator("#chart-nav .main-svg").first.wait_for(state="visible")
        page.wait_for_function(
            """() => {
                const plot = document.getElementById('chart-nav');
                return Math.abs(plot._fullLayout.width - plot.clientWidth) < 2;
            }"""
        )
        page.locator("#live-status-text").get_by_text("Offline synthetic demo").wait_for()
        assert page.evaluate(
            """() => ['chart-monthly', 'chart-pnl', 'chart-holdings'].every(id => {
                const plot = document.getElementById(id);
                return plot.layout.dragmode === false && plot._context.scrollZoom === false;
            })"""
        ), "Categorical plots must remain fixed"
        nav_controls = page.locator('[data-chart-target="chart-nav"]')
        nav_controls.locator('[data-chart-range="1w"]').click()
        page.wait_for_function(
            """() => {
                const axis = document.getElementById('chart-nav').layout.xaxis;
                return !axis.autorange &&
                    Math.abs((new Date(axis.range[1]) - new Date(axis.range[0])) / 86400000 - 7) < 0.01;
            }"""
        )
        nav_controls.locator("[data-chart-reset]").click()
        page.wait_for_function("document.getElementById('chart-nav').layout.xaxis.autorange")
        page.screenshot(path=images / "dashboard.png", animations="disabled")
        page.screenshot(path=images / "report.png", full_page=True, animations="disabled")
        page.locator(".chart").filter(has=page.locator("#chart-nav")).screenshot(
            path=images / "nav.png", animations="disabled"
        )
        page.locator('[data-target="benchmarks"]').click()
        page.locator("#chart-benchmark .main-svg").first.wait_for(state="visible")
        # Tab activation schedules Plotly's resize; capture only its final layout.
        page.wait_for_function(
            """() => {
                const plot = document.getElementById('chart-benchmark');
                return Math.abs(plot._fullLayout.width - plot.clientWidth) < 2;
            }"""
        )
        page.locator(".chart").filter(has=page.locator("#chart-benchmark")).screenshot(
            path=images / "returns.png", animations="disabled"
        )
        page.goto(start_screen.resolve().as_uri())
        page.locator("#dropzone-heading").wait_for(state="visible")
        page.screenshot(path=images / "desktop-start.png", animations="disabled")
        assert not errors, f"JavaScript errors during screenshot capture: {errors}"
        browser.close()
    print(f"Captured five real PNG screenshots in {images.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
