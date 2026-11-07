"""Generate fictional XTB histories and correlated market data (seed 42).

Nothing is downloaded or derived from a real account. For byte reproducibility,
fix both seed and end date: --seed 42 --end-date 2026-11-07.
"""

from __future__ import annotations

import argparse
import io
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS = {"USD": "90000001", "EUR": "90000002"}
HEADER = [
    "Type",
    "Instrument",
    "Ticker",
    "Category",
    "Time",
    "Amount",
    "ID",
    "Comment",
    "Product",
    "Position ID",
]


@dataclass(frozen=True)
class Asset:
    symbol: str
    currency: str
    sector: str
    initial_price: float
    drift: float
    volatility: float
    beta: float


ASSETS = (
    Asset("MSFT.US", "USD", "Technology", 220, 0.13, 0.25, 1.05),
    Asset("AAPL.US", "USD", "Technology", 130, 0.10, 0.29, 1.10),
    Asset("NVDA.US", "USD", "Technology", 13, 0.22, 0.48, 1.35),
    Asset("AMZN.US", "USD", "Consumer discretionary", 160, 0.12, 0.34, 1.18),
    Asset("JPM.US", "USD", "Financials", 125, 0.08, 0.27, 0.92),
    Asset("KO.US", "USD", "Consumer staples", 50, 0.055, 0.17, 0.62),
    Asset("SAP.DE", "EUR", "Technology", 105, 0.11, 0.28, 1.02),
    Asset("SIE.DE", "EUR", "Industrials", 125, 0.075, 0.26, 0.98),
    Asset("ASML.NL", "EUR", "Technology", 500, 0.15, 0.38, 1.25),
    Asset("MC.FR", "EUR", "Consumer discretionary", 500, 0.07, 0.30, 1.08),
    Asset("AIR.FR", "EUR", "Industrials", 90, 0.085, 0.32, 1.12),
    Asset("SXR8.DE", "EUR", "Diversified ETF", 350, 0.09, 0.20, 1.00),
    Asset("EUNL.DE", "EUR", "Diversified ETF", 65, 0.075, 0.18, 0.94),
    Asset("IS3N.DE", "EUR", "Diversified ETF", 30, 0.06, 0.24, 1.06),
    Asset("VUSA.DE", "EUR", "Diversified ETF", 60, 0.088, 0.205, 1.01),
)
BENCHMARKS = (
    Asset("demo_sp500", "USD", "S&P 500 (synthetic)", 3500, 0.085, 0.19, 1.00),
    Asset("demo_nasdaq100", "USD", "Nasdaq-100 (synthetic)", 12500, 0.12, 0.27, 1.18),
    Asset("demo_sox", "USD", "SOX (synthetic)", 2700, 0.15, 0.36, 1.32),
    Asset("demo_wig20", "PLN", "WIG20 (synthetic)", 2000, 0.055, 0.25, 0.88),
)


def _archive(files: dict[str, bytes]) -> bytes:
    """Canonical ZIP metadata also makes nested XLSX files byte-identical."""
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(files.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 0
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content, compresslevel=9)
    return buffer.getvalue()


def _workbook(currency: str, rows: list[dict[str, str]], end: str) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Cash Operations"
    for row in (
        ["Account number", ACCOUNTS[currency]],
        ["Cash Operations"],
        ["Date from (UTC)", "2021-01-01 00:00:00"],
        ["Date to (UTC)", end + " 23:59:59"],
        HEADER,
    ):
        sheet.append(row)
    for tx in rows:
        sheet.append([tx.get(key, "") for key in HEADER])
    book.properties.creator = "Synthetic demo generator"
    book.properties.lastModifiedBy = "Synthetic demo generator"
    book.properties.created = datetime(2021, 1, 1)
    book.properties.modified = datetime(2021, 1, 1)
    buffer = io.BytesIO()
    book.save(buffer)
    with ZipFile(io.BytesIO(buffer.getvalue())) as original:
        files = {name: original.read(name) for name in original.namelist()}
    files["docProps/core.xml"] = re.sub(
        rb"(<dcterms:modified[^>]*>).*?(</dcterms:modified>)",
        rb"\g<1>2021-01-01T00:00:00Z\g<2>",
        files["docProps/core.xml"],
    )
    return _archive(files)


def _markets(calendar: pd.DatetimeIndex, rng: np.random.Generator):
    market = rng.standard_normal(len(calendar))
    regime = np.zeros(len(calendar))
    for start, end, shock in (
        ("2022-02-01", "2022-10-14", 0.75),
        ("2024-07-15", "2024-09-13", 0.88),
    ):
        mask = (calendar >= start) & (calendar <= end)
        if mask.any():
            regime[mask] = np.log(shock) / mask.sum()

    def gbm(asset: Asset):
        loading = 0.7 * asset.beta
        noise = loading * market + np.sqrt(1 - loading**2) * rng.standard_normal(len(calendar))
        changes = (
            (asset.drift - 0.5 * asset.volatility**2) / 252
            + asset.volatility * noise / np.sqrt(252)
            + regime * asset.beta
        )
        changes[0] = 0
        return asset.initial_price * np.exp(np.cumsum(changes))

    prices = pd.DataFrame({a.symbol: gbm(a) for a in ASSETS}, index=calendar).round(8)
    benchmarks = pd.DataFrame({a.symbol: gbm(a) for a in BENCHMARKS}, index=calendar).round(8)

    def reverting(initial, target, speed, volatility):
        values = np.zeros(len(calendar))
        values[0] = np.log(initial)
        shocks = rng.standard_normal(len(calendar))
        for i in range(1, len(calendar)):
            values[i] = (
                values[i - 1]
                + speed * (np.log(target) - values[i - 1]) / 252
                + volatility * (0.2 * market[i] + np.sqrt(0.96) * shocks[i]) / np.sqrt(252)
            )
        return np.exp(values)

    fx = pd.DataFrame(
        {"USDPLN": reverting(3.72, 4.02, 0.8, 0.10), "EURUSD": reverting(1.22, 1.12, 0.9, 0.08)},
        index=calendar,
    )
    fx["EURPLN"] = fx.USDPLN * fx.EURUSD
    fx["USDEUR"] = 1 / fx.EURUSD
    return prices, fx.round(10), benchmarks


def generate(output_dir: str | Path, seed: int = 42, end_date: str | date | None = None) -> dict:
    """Write a reproducible demo; explicit end_date avoids a moving test fixture."""
    end = pd.Timestamp(end_date or datetime.now(ZoneInfo("Europe/Warsaw")).date())
    calendar = pd.bdate_range("2021-01-01", end, name="date")
    if len(calendar) < 260:
        raise ValueError("The demonstration requires at least one year of history.")
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    prices, fx, benchmarks = _markets(calendar, rng)
    events: dict[pd.Timestamp, list[tuple]] = {}

    def schedule(day, priority, kind, *args):
        day = pd.Timestamp(day)
        index = calendar.searchsorted(day)
        if index < len(calendar):
            events.setdefault(calendar[index], []).append((priority, kind, *args))

    for currency, amount in (("USD", 13000), ("EUR", 11000)):
        schedule(calendar[0], 0, "deposit", currency, amount)
    for i, asset in enumerate(ASSETS):
        schedule("2021-01-04", 8, "buy", asset.currency, asset.symbol, 1700 if i < 6 else 1100)
    for i, month in enumerate(pd.date_range("2021-02-01", end, freq="MS")):
        currency = "USD" if i % 2 == 0 else "EUR"
        amount = round(rng.uniform(300, 900), 2)
        choices = [a.symbol for a in ASSETS if a.currency == currency]
        schedule(month + pd.Timedelta(days=4), 0, "deposit", currency, amount)
        schedule(
            month + pd.Timedelta(days=int(rng.integers(7, 16))),
            8,
            "buy",
            currency,
            str(rng.choice(choices)),
            amount * 1.35,
        )
    for i, day in enumerate(
        (
            "2022-03-15",
            "2022-09-20",
            "2023-04-14",
            "2023-11-10",
            "2024-04-15",
            "2024-10-15",
            "2025-04-15",
            "2025-10-15",
            "2026-04-15",
            "2026-10-15",
        )
    ):
        schedule(day, 2, "sell", "USD" if i % 2 == 0 else "EUR", i < 2, i in (3, 9))
    for i, day in enumerate(("2023-01-20", "2024-06-20", "2025-08-20", "2026-09-20")):
        schedule(day, 3, "withdraw", "USD" if i % 2 == 0 else "EUR", 550 + 100 * i)
    for day in ("2022-11-15", "2024-03-15", "2026-02-15"):
        schedule(day, 1, "convert", "USD", "EUR", 450)
    for year in range(2021, end.year + 1):
        for month in (3, 6, 9, 12):
            schedule(f"{year}-{month:02}-15", 4, "dividend", "USD", "KO.US", 0.028 / 4)
        for currency, symbol, month, yield_ in (
            ("USD", "JPM.US", 5, 0.024),
            ("EUR", "SAP.DE", 5, 0.014),
        ):
            schedule(f"{year}-{month:02}-20", 4, "dividend", currency, symbol, yield_)
        for currency in ACCOUNTS:
            schedule(f"{year}-09-30", 5, "interest", currency)
            schedule(f"{year}-10-01", 6, "fee", currency)

    cash = dict.fromkeys(ACCOUNTS, Decimal(0))
    positions = dict.fromkeys([a.symbol for a in ASSETS], Decimal(0))
    cost = positions.copy()
    retired: set[str] = set()
    rows: dict[str, list] = {c: [] for c in ACCOUNTS}
    external: list[dict] = []
    realized: list[float] = []
    day_counts: dict[pd.Timestamp, int] = {}

    def emit(day, currency, kind, amount, symbol="", comment=""):
        amount = Decimal(str(amount)).quantize(Decimal(".01"))
        cash[currency] += amount
        sequence = sum(len(r) for r in rows.values())
        minute = day_counts.get(day, 0)
        day_counts[day] = minute + 1
        rows[currency].append(
            {
                "Type": kind,
                "Instrument": symbol or "Synthetic cash operation",
                "Ticker": symbol,
                "Category": "STOCK" if symbol else "CASH",
                "Time": f"{day.date()} 12:{minute:02}:00",
                "Amount": str(amount),
                "ID": str(88000000 + sequence),
                "Comment": comment,
                "Product": "Synthetic demonstration",
                "Position ID": "",
            }
        )
        return amount

    def sell(day, currency, symbol, fraction):
        qty = (positions[symbol] * Decimal(str(fraction))).quantize(Decimal(".000001"), ROUND_DOWN)
        if qty <= 0:
            return
        price = Decimal(str(prices.loc[day, symbol]))
        basis = cost[symbol] * qty / positions[symbol]
        proceeds = emit(
            day, currency, "Stock sell", qty * price, symbol, f"CLOSE BUY {symbol} {qty} @ {price}"
        )
        positions[symbol] -= qty
        cost[symbol] -= basis
        realized.append(float(proceeds - basis))

    for day, operations in sorted(events.items()):
        for _, kind, *args in sorted(operations, key=lambda op: op[0]):
            currency = args[0]
            if kind == "deposit":
                amount = args[1]
                rate = 0.995 / float(fx.loc[day, currency + "PLN"])
                emit(
                    day,
                    currency,
                    "Transfer",
                    amount,
                    comment=f"Currency conversion, PLN to {currency} from TA: 90000000 to: {ACCOUNTS[currency]}, Exchange rate:{rate:.12f}",
                )
                external.append(
                    {
                        "date": str(day.date()),
                        "currency": currency,
                        "amount": amount,
                        "pln": amount / float(f"{rate:.12f}"),
                    }
                )
            elif kind == "buy":
                _, symbol, budget = args
                if symbol in retired:
                    symbol = next(
                        a.symbol
                        for a in ASSETS
                        if a.currency == currency and a.symbol not in retired
                    )
                price = Decimal(str(prices.loc[day, symbol]))
                budget = min(Decimal(str(budget)), cash[currency] * Decimal(".92"))
                qty = (budget / price).quantize(Decimal(".000001"), ROUND_DOWN)
                spent = -emit(
                    day,
                    currency,
                    "Stock purchase",
                    -qty * price,
                    symbol,
                    f"OPEN BUY {symbol} {qty} @ {price}",
                )
                positions[symbol] += qty
                cost[symbol] += spent
            elif kind == "sell":
                _, loss, full = args
                choices = [
                    a.symbol
                    for a in ASSETS
                    if a.currency == currency
                    and positions[a.symbol] > 0
                    and a.symbol not in ("KO.US", "JPM.US", "SAP.DE")
                ]
                symbol = sorted(
                    choices,
                    key=lambda s: float(positions[s] * Decimal(str(prices.loc[day, s])) / cost[s]),
                )[0 if loss else -1]
                sell(day, currency, symbol, 1 if full else 0.30)
                if full:
                    retired.add(symbol)
            elif kind == "withdraw":
                amount = Decimal(str(args[1]))
                if cash[currency] < amount:
                    symbol = max(
                        (a.symbol for a in ASSETS if a.currency == currency),
                        key=lambda s: positions[s] * Decimal(str(prices.loc[day, s])),
                    )
                    sell(day, currency, symbol, 0.35)
                emit(day, currency, "Withdrawal", -amount, comment="Synthetic bank withdrawal")
                external.append(
                    {
                        "date": str(day.date()),
                        "currency": currency,
                        "amount": -float(amount),
                        "pln": -float(amount) * float(fx.loc[day, currency + "PLN"]),
                    }
                )
            elif kind == "convert":
                _, target, amount = args
                if cash[currency] < amount:
                    symbol = max(
                        (a.symbol for a in ASSETS if a.currency == currency),
                        key=lambda s: positions[s] * Decimal(str(prices.loc[day, s])),
                    )
                    sell(day, currency, symbol, 0.35)
                rate = float(fx.loc[day, "USDEUR"])
                comment = f"Currency conversion, {currency} to {target}, Exchange rate:{rate:.12f}"
                emit(day, currency, "Transfer", -amount, comment=comment)
                emit(day, target, "Transfer", round(amount * rate, 2), comment=comment)
            elif kind == "dividend":
                _, symbol, yield_ = args
                gross = emit(
                    day,
                    currency,
                    "Dividend",
                    float(positions[symbol]) * prices.loc[day, symbol] * yield_,
                    symbol,
                    "Synthetic cash dividend",
                )
                emit(
                    day,
                    currency,
                    "Withholding tax",
                    -gross * Decimal(".15"),
                    symbol,
                    "Synthetic dividend withholding tax",
                )
            elif kind == "interest":
                emit(day, currency, "Free funds interest", 12.00, comment="Synthetic cash interest")
                emit(day, currency, "Interest tax", -2.28, comment="Synthetic interest tax")
            elif kind == "fee":
                emit(day, currency, "Fee", -3.50, comment="Synthetic account fee")
            assert cash[currency] >= 0, (day, currency, kind)

    for name, frame in (("prices.csv", prices), ("fx.csv", fx), ("benchmarks.csv", benchmarks)):
        frame.to_csv(folder / name, float_format="%.10f", lineterminator="\n")
    pd.DataFrame([asdict(a) for a in ASSETS]).to_csv(
        folder / "instruments.csv", index=False, lineterminator="\n"
    )
    pd.DataFrame(
        [{"key": a.symbol, "currency": a.currency, "name": a.sector} for a in BENCHMARKS]
    ).to_csv(folder / "benchmark_metadata.csv", index=False, lineterminator="\n")
    books = {c: _workbook(c, tx, str(calendar[-1].date())) for c, tx in rows.items()}
    for currency, content in books.items():
        (folder / f"XTB_{currency}_cs.xlsx").write_bytes(content)
    (folder / "synthetic_history.zip").write_bytes(
        _archive(
            {
                f"{ACCOUNTS[c]}/{c}_{ACCOUNTS[c]}_2021-01-01_{calendar[-1].date()}.xlsx": content
                for c, content in books.items()
            }
        )
    )
    manifest = {
        "synthetic": True,
        "seed": seed,
        "as_of": str(end.date()),
        "start": str(calendar[0].date()),
        "end": str(calendar[-1].date()),
        "business_days": len(calendar),
        "operations": sum(map(len, rows.values())),
        "cash": {c: float(v) for c, v in cash.items()},
        "shares": {s: float(v) for s, v in positions.items()},
        "external_flows": external,
        "realized_gains": sum(x > 0 for x in realized),
        "realized_losses": sum(x < 0 for x in realized),
    }
    (folder / "demo.json").write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    readme = (
        "# Fictional XTB portfolio\n\n"
        f"Generated with NumPy seed {seed}: {manifest['start']} to {manifest['end']}, "
        f"{manifest['operations']} cash operations, 15 instruments.\n\n"
        "Every account, operation, quote, FX rate and benchmark is invented. Tickers identify "
        "instrument categories only; these paths are not historical returns.\n\n"
        "Prices use distinct GBM parameters and a shared market factor. Deterministic drift shocks "
        "in 2022 and 2024 are scenarios, not fitted market events. FX follows log mean reversion. "
        "The calendar is business days, not exchange holidays; corporate actions are not simulated.\n\n"
        "`instruments.csv` records parameters, sectors and quote currencies. `benchmark_metadata.csv` "
        "identifies the fictional indices and their currencies. `demo.json` records an independent "
        "cash/share ledger and cash flows for reconciliation.\n\n"
        "Regenerate: `uv run python scripts/generate_demo_data.py --seed 42` (through today). "
        "Pin `--end-date YYYY-MM-DD` for byte-identical files. Run `uv run xtb-analyzer --demo --open`.\n"
    )
    (folder / "README.md").write_bytes(readme.encode("utf-8"))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "examples")
    args = parser.parse_args()
    result = generate(args.output_dir, args.seed, args.end_date)
    print(
        f"Generated {result['operations']} fictional operations through {result['end']} (seed {args.seed})."
    )


if __name__ == "__main__":
    main()
