"""Render sharp screenshots from the production report and optional native windows.

Browser: uv run python scripts/make_screenshots.py
Windows desktop: uv run --extra desktop python scripts/make_screenshots.py --native
Native capture reads the HWND of processes started here; it never captures the desktop.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from PIL import Image, ImageStat
from playwright.sync_api import Page, sync_playwright

from xtb_analyzer.market_data import MarketData
from xtb_analyzer.report import generate_report

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "docs" / "images"


def optimize(path: Path) -> None:
    """Keep full pixel dimensions; use a palette only if lossless PNG exceeds 1 MB."""
    with Image.open(path) as original:
        image = original.convert("RGB")
        image.save(path, optimize=True, compress_level=9)
        if path.stat().st_size >= 1_000_000:
            image.quantize(colors=256, dither=Image.Dither.NONE).save(
                path, optimize=True, compress_level=9
            )
    assert path.stat().st_size < 1_000_000, f"Screenshot exceeds 1 MB: {path.name}"


def settled(page: Page) -> None:
    """Wait for every Plotly promise, then resize the visible tab and paint twice."""
    page.wait_for_function(
        """() => {
            const plots = [...document.querySelectorAll('.js-plotly-plot')];
            return plots.length === 8 && plots.every(p => p._fullLayout && p.calcdata);
        }"""
    )
    page.evaluate(
        """async () => {
            const plots = [...document.querySelectorAll('.js-plotly-plot')];
            await Promise.all(plots.filter(p => p.offsetParent !== null).map(p => Plotly.Plots.resize(p)));
            await new Promise(requestAnimationFrame);
            await new Promise(requestAnimationFrame);
        }"""
    )


def section(page: Page, name: str) -> None:
    page.locator(f'[data-target="{name}"]').click()
    settled(page)


def native_hover_boxes(page: Page) -> list[dict[str, object]]:
    return page.evaluate(
        """() => [...document.querySelectorAll('.hoverlayer .hovertext, .hoverlayer .legend')].map(node => {
            const box = node.getBoundingClientRect();
            return {w: box.width, h: box.height};
        }).filter(item => item.w > 0.5 || item.h > 0.5)"""
    )


_HOVER_SECTION = {
    "chart-nav": "overview",
    "chart-monthly": "overview",
    "chart-deposits": "deposits",
    "chart-benchmark": "benchmarks",
    "chart-pnl": "holdings",
    "chart-holdings": "holdings",
    "chart-currency": "holdings",
    "chart-sector": "holdings",
}


def show_custom_hover(page: Page, plot_id: str) -> None:
    """Move onto a chart and require the custom card without a Plotly tooltip box."""
    page.locator(f'[data-target="{_HOVER_SECTION[plot_id]}"]').click()
    page.wait_for_timeout(250)
    page.locator(f"#{plot_id}").scroll_into_view_if_needed()
    target = page.locator(f"#{plot_id} .nsewdrag")
    box = target.bounding_box() if target.count() else None
    if box is None:
        slice_box = page.locator(f"#{plot_id} .slice").first.bounding_box()
        if slice_box is None:
            raise AssertionError(f"No plot area for {plot_id}")
        page.mouse.move(
            slice_box["x"] + slice_box["width"] * 0.5,
            slice_box["y"] + slice_box["height"] * 0.5,
        )
    else:
        page.mouse.move(box["x"] + box["width"] * 0.58, box["y"] + box["height"] * 0.42)
    page.wait_for_function(
        """() => {
            const card = document.getElementById('chart-hover-card');
            return card && !card.hidden && card.querySelector('.chc-val');
        }"""
    )
    leftover = native_hover_boxes(page)
    if leftover:
        raise AssertionError(f"Native Plotly hover is visible on {plot_id}: {leftover}")


def retypeset_formula(page: Page) -> None:
    page.evaluate(
        """async () => {
            const el = document.getElementById('guide-formula');
            const tex = el.getAttribute('data-tex') || '';
            el.textContent = '\\\\[' + tex + '\\\\]';
            if (window.MathJax && MathJax.typesetPromise) await MathJax.typesetPromise([el]);
        }"""
    )
    page.wait_for_function("() => document.querySelector('#guide-formula svg path')")


def shoot_formulas(page: Page, folder: Path, label: str, *, capture: bool = True) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    keys = page.locator("#guide-jump option").evaluate_all("opts => opts.map(o => o.value)")
    for key in keys:
        page.select_option("#guide-jump", key)
        page.wait_for_function(
            """(key) => document.getElementById('guide-jump').value === key
                && document.querySelector('#guide-formula svg path')""",
            arg=key,
        )
        retypeset_formula(page)
        fit = page.evaluate(
            """() => {
                const host = document.getElementById('guide-formula');
                const svg = host.querySelector('svg[role="img"]');
                const hostBox = host.getBoundingClientRect();
                const svgBox = svg.getBoundingClientRect();
                return {
                    svgH: svgBox.height,
                    top: svgBox.top - hostBox.top,
                    bottom: hostBox.bottom - svgBox.bottom
                };
            }"""
        )
        if fit["svgH"] < 12 or fit["top"] < -2 or fit["bottom"] < -2:
            raise AssertionError(f"{label} {key} formula is clipped: {fit}")
        if capture:
            page.locator('#guide-formula svg[role="img"]').screenshot(
                path=folder / f"{label}-{key}.png", animations="disabled"
            )


def capture_report(
    channel: str | None,
    media_dir: Path | None = None,
    formula_dir: Path | None = None,
) -> None:
    folder = ROOT / "examples"
    report = generate_report(
        data_dir=folder,
        output_dir=ROOT / "output" / "demo",
        market_data=MarketData.from_examples(folder),
        refresh_latest=False,
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=channel)
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=2)
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("http://**/*", lambda route: route.abort())
        page.route("https://**/*", lambda route: route.abort())
        page.goto(report.resolve().as_uri())
        settled(page)
        page.locator("#live-status-text").get_by_text("Offline synthetic demo").wait_for()
        assert page.evaluate(
            """() => ['chart-monthly', 'chart-pnl', 'chart-holdings'].every(id => {
                const plot = document.getElementById(id);
                return !plot.layout.dragmode && !plot._context.scrollZoom;
            })"""
        )
        controls = page.locator('[data-chart-target="chart-nav"]')
        controls.locator('[data-chart-range="1w"]').click()
        page.wait_for_function(
            """() => {
                const x = document.getElementById('chart-nav').layout.xaxis;
                return !x.autorange && Math.abs((new Date(x.range[1])-new Date(x.range[0]))/86400000-7)<.01;
            }"""
        )
        controls.locator("[data-chart-reset]").click()
        settled(page)
        page.mouse.move(2, 2)
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=IMAGES / "dashboard.png", animations="disabled")
        page.screenshot(path=IMAGES / "report-overview.png", animations="disabled")
        for selector, name in (
            ("#nav-history", "nav.png"),
            ("#risk-monthly", "report-risk.png"),
        ):
            page.locator(selector).screenshot(path=IMAGES / name, animations="disabled")
        page.locator(".chart").filter(has=page.locator("#chart-monthly")).screenshot(
            path=IMAGES / "monthly-pnl.png", animations="disabled"
        )
        section(page, "benchmarks")
        labels = page.locator("#chart-benchmark .xaxislayer-above .xtick text")
        boxes = [labels.nth(i).bounding_box() for i in range(labels.count())]
        boxes = sorted((b for b in boxes if b), key=lambda b: b["x"])
        assert len(boxes) >= 2, "Benchmark date axis must display useful labels"
        assert all(
            left["x"] + left["width"] < right["x"]
            for left, right in zip(boxes, boxes[1:], strict=False)
        ), "Benchmark date labels overlap"
        page.locator(".chart").filter(has=page.locator("#chart-benchmark")).screenshot(
            path=IMAGES / "returns-benchmarks.png", animations="disabled"
        )
        section(page, "holdings")
        page.locator("#live-company-pnl").screenshot(
            path=IMAGES / "holdings-table.png", animations="disabled"
        )
        page.locator(".chart").filter(has=page.locator("#chart-pnl")).screenshot(
            path=IMAGES / "company-pnl.png", animations="disabled"
        )
        page.locator(".panel-block").filter(has=page.locator("#chart-holdings")).screenshot(
            path=IMAGES / "allocation.png", animations="disabled"
        )
        page.locator(".panel-block").filter(has=page.locator("#live-company-pnl")).screenshot(
            path=IMAGES / "report-holdings.png", animations="disabled"
        )
        section(page, "costs")
        page.locator(".panel-block").filter(has=page.locator("#live-attribution")).screenshot(
            path=IMAGES / "fx-attribution.png", animations="disabled"
        )
        section(page, "deposits")
        page.mouse.move(2, 2)
        page.locator("#deposits").evaluate("el => el.scrollIntoView({block: 'start'})")
        page.screenshot(path=IMAGES / "deposits.png", animations="disabled")
        section(page, "pit38")
        page.locator("#pit38").evaluate("el => el.scrollIntoView({block: 'start'})")
        page.screenshot(path=IMAGES / "pit38.png", animations="disabled")
        for plot_id in (
            "chart-nav",
            "chart-deposits",
            "chart-monthly",
            "chart-benchmark",
            "chart-pnl",
            "chart-holdings",
            "chart-currency",
            "chart-sector",
        ):
            show_custom_hover(page, plot_id)
        show_custom_hover(page, "chart-nav")
        page.screenshot(path=IMAGES / "hover-readout.png", animations="disabled")
        if media_dir is not None:
            media_dir.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=media_dir / "v130-single-hover-readout.png", animations="disabled")
        page.mouse.move(2, 2)
        page.locator('[data-metric-key="sharpe"]').first.click()
        page.locator("#metric-popover").wait_for(state="visible")
        page.screenshot(path=IMAGES / "indicator-popover.png", animations="disabled")
        if media_dir is not None:
            page.screenshot(path=media_dir / "v130-indicator-popover.png", animations="disabled")
        page.locator("#metric-popover-learn").click()
        page.wait_for_function("() => document.querySelector('#guide-formula svg path')")
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=IMAGES / "indicator-guide.png", animations="disabled")
        if media_dir is not None:
            page.screenshot(path=media_dir / "v130-indicator-guide-page.png", animations="disabled")
        if formula_dir is not None:
            shoot_formulas(page, formula_dir, "desktop")
            page.set_viewport_size({"width": 390, "height": 844})
            page.evaluate("() => document.body.classList.add('formula-review-mobile')")
            shoot_formulas(page, formula_dir, "mobile-width", capture=False)
            page.set_viewport_size({"width": 1400, "height": 900})
            shoot_formulas(page, formula_dir, "mobile")
        assert not errors, f"JavaScript errors: {errors}"
        browser.close()


def capture_native(demo: bool, executable: Path | None = None) -> None:
    """Capture the actual pywebview client area by HWND, without browser/window chrome."""
    if sys.platform != "win32":
        raise RuntimeError("Native window capture currently requires Windows.")
    from ctypes import wintypes

    name = "desktop-dashboard" if demo else "desktop-start"
    ready = ROOT / "output" / "demo" / (name + "-ready.json")
    ready.unlink(missing_ok=True)
    command = [str(executable)] if executable else [sys.executable, "-m", "xtb_analyzer.desktop"]
    command += [
        "--width",
        "1616",
        "--height",
        "1039",
        "--capture-ready",
        str(ready),
    ]
    if demo:
        command.append("--demo")
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass
    with (ready.parent / (name + ".log")).open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, cwd=ROOT, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW
        )
        try:
            deadline = time.monotonic() + 60
            while not ready.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError(
                        f"Native {name} did not finish rendering; inspect {log.name}"
                    )
                time.sleep(0.2)
            proof = json.loads(ready.read_text(encoding="utf-8"))
            handles: list[int] = []
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            def found(hwnd, _):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == proof["pid"] and user32.IsWindowVisible(hwnd):
                    title = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(hwnd, title, 256)
                    if title.value.startswith("XTB Portfolio"):
                        handles.append(hwnd)
                return True

            user32.EnumWindows(callback_type(found), 0)
            if len(handles) != 1:
                raise RuntimeError(f"Expected one native application window; found {len(handles)}")
            hwnd = handles[0]
            time.sleep(0.8)
            bounds, client = wintypes.RECT(), wintypes.RECT()
            origin = wintypes.POINT(0, 0)
            user32.GetWindowRect(hwnd, ctypes.byref(bounds))
            user32.GetClientRect(hwnd, ctypes.byref(client))
            user32.ClientToScreen(hwnd, ctypes.byref(origin))
            from windows_capture import WindowsCapture

            frames: list[Image.Image] = []
            received = threading.Event()
            capture = WindowsCapture(window_hwnd=hwnd, cursor_capture=False)

            @capture.event
            def on_frame_arrived(frame, capture_control):
                # WGC owns this HWND's pixels even if another app is in front.
                frames.append(Image.fromarray(frame.frame_buffer[:, :, [2, 1, 0]].copy()))
                received.set()
                capture_control.stop()

            @capture.event
            def on_closed():
                received.set()

            control = capture.start_free_threaded()
            if not received.wait(timeout=20) or not frames:
                control.stop()
                raise RuntimeError("Windows Graphics Capture did not deliver the target window")
            control.wait()
            frame = frames[0]
            # WGC excludes invisible resize borders: align the client to its bottom edge.
            left = max(0, (frame.width - client.right) // 2)
            top = max(0, frame.height - client.bottom - left)
            frame = frame.crop((left, top, left + client.right, top + client.bottom))
            assert max(ImageStat.Stat(frame.convert("RGB")).stddev) > 15, "Empty native capture"
            frame.save(IMAGES / (name + ".png"))
            print(f"Captured real pywebview {name}: {frame.width}x{frame.height}")
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=15)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--channel", default=None, help="Optional installed Chromium browser channel."
    )
    parser.add_argument(
        "--native", action="store_true", help="Also capture actual Windows desktop windows."
    )
    parser.add_argument(
        "--desktop-exe", type=Path, help="Use a packaged executable for native captures."
    )
    parser.add_argument("--media-dir", type=Path, help="Also write the v1.3.0 review shots here.")
    parser.add_argument(
        "--formula-dir", type=Path, help="Write one formula screenshot per indicator and width."
    )
    args = parser.parse_args()
    if args.desktop_exe:
        if not args.native:
            parser.error("--desktop-exe requires --native")
        args.desktop_exe = args.desktop_exe.resolve(strict=True)
    IMAGES.mkdir(parents=True, exist_ok=True)
    capture_report(args.channel, media_dir=args.media_dir, formula_dir=args.formula_dir)
    if args.native:
        capture_native(demo=False, executable=args.desktop_exe)
        capture_native(demo=True, executable=args.desktop_exe)
    for path in sorted(IMAGES.glob("*.png")):
        optimize(path)
        with Image.open(path) as image:
            print(
                f"{path.name}: {image.width}x{image.height}, {path.stat().st_size / 1024:.0f} KiB"
            )


if __name__ == "__main__":
    main()
