"""Reference calculations on the distributable sample, with networking prohibited."""

from __future__ import annotations

import importlib.util
import json
import socket
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from xtb_analyzer.market_data import MarketData
from xtb_analyzer.parser import discover_export_files, load_accounts
from xtb_analyzer.report import collect_report_data, generate_report
from xtb_analyzer.returns import build_external_cash_flows

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def demo(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("The synthetic demo must not use the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    accounts = load_accounts(discover_export_files(EXAMPLES))
    market = MarketData.from_examples(EXAMPLES)
    return accounts, market, collect_report_data(accounts, market_data=market)


def test_sample_nav_reconciles_cash_positions_and_external_flows(demo):
    accounts, market, data = demo
    ledger = json.loads((EXAMPLES / "demo.json").read_text())
    latest_fx = market.fx.iloc[-1]
    expected = 0.0
    for currency, cash in ledger["cash"].items():
        symbols = [s for s, c in market.quote_currencies.items() if c == currency]
        local_nav = cash + sum(ledger["shares"][s] * market.prices[s].iloc[-1] for s in symbols)
        expected += local_nav * latest_fx[currency + "PLN"]
    gross = sum(f["pln"] for f in ledger["external_flows"] if f["amount"] > 0)
    net = sum(f["pln"] for f in ledger["external_flows"])
    assert len(accounts) == 2
    assert data.nav["nav_usd"].iloc[-1] == pytest.approx(expected / latest_fx.USDPLN)
    assert data.measures.final_value == pytest.approx(expected)
    assert data.measures.invested == pytest.approx(gross)
    assert data.measures.roi == pytest.approx((expected - net) / gross)
    assert data.attribution.total_gain_pln == pytest.approx(expected - net)
    assert market.prices.index[-1] == pd.Timestamp(ledger["end"])
    assert sum(len(a.transactions) for a in accounts) == ledger["operations"]


def test_demo_is_volatile_and_has_realized_gains_and_losses(demo):
    _, market, data = demo
    values = data.nav.nav_pln
    assert not values.is_monotonic_increasing
    assert (values / values.cummax() - 1).min() < -0.10
    assert data.risk.max_drawdown < -0.10
    assert len(market.prices.columns) == 15
    assert data.company_pnl.realized_pnl.min() < 0 < data.company_pnl.realized_pnl.max()
    assert 150 <= sum(len(a.transactions) for a in data.accounts) <= 300


def test_demo_files_are_byte_reproducible(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "demo_generator", EXAMPLES.parent / "scripts/generate_demo_data.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve postponed annotations through the registered module.
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    end = json.loads((EXAMPLES / "demo.json").read_text())["as_of"]
    first, second = tmp_path / "first", tmp_path / "second"
    module.generate(first, seed=42, end_date=end)
    module.generate(second, seed=42, end_date=end)
    files = sorted(p.name for p in first.iterdir())
    assert files == sorted(p.name for p in second.iterdir())
    for name in files:
        assert (first / name).read_bytes() == (second / name).read_bytes()
        assert (first / name).read_bytes() == (EXAMPLES / name).read_bytes()


def test_sample_xirr_zeroes_actual_flow_npv(demo):
    accounts, market, data = demo
    flows = build_external_cash_flows(accounts, data.nav, fx=market.fx)
    rate = data.measures.xirr
    assert rate is not None
    residual = sum(f.amount / (1 + rate) ** ((f.date - flows[0].date).days / 365.25) for f in flows)
    assert residual == pytest.approx(0, abs=1e-6)


def test_pln_benchmark_keeps_its_declared_quote_currency(demo):
    _, market, data = demo
    ledger = json.loads((EXAMPLES / "demo.json").read_text())
    levels = market.benchmarks["demo_wig20"]
    units = sum(f["pln"] / levels.asof(pd.Timestamp(f["date"])) for f in ledger["external_flows"])
    assert market.benchmark_currencies["demo_wig20"] == "PLN"
    assert data.benchmarks["demo_wig20"].iloc[-1] == pytest.approx(units * levels.iloc[-1])


def test_sample_twr_matches_an_independent_daily_chain(demo):
    _, _, data = demo
    nav = data.nav.nav_pln.to_numpy()
    capital = data.nav.deposits_pln.to_numpy()
    daily_flows = np.diff(capital, prepend=0)
    previous_nav = np.concatenate(([0], nav[:-1]))
    expected = np.prod(nav / (previous_nav + daily_flows)) - 1
    assert data.measures.twr == pytest.approx(expected)


def test_sample_report_is_self_contained_and_identified_as_synthetic(tmp_path, demo):
    _, market, _ = demo
    report = generate_report(EXAMPLES, tmp_path, market_data=market)
    html = report.read_text(encoding="utf-8")
    assert "Synthetic demo: fictional trades" in html
    assert 'lang="en"' in html
    assert '<script src="' not in html
    assert "__DEMO_JSON__" not in html
