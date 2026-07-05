from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yfinance as yf

from xtb_analyzer.prices import xtb_to_yahoo

SECTOR_CACHE_FILE = Path("data/cache/sectors.json")


def _load_sector_cache() -> dict[str, dict[str, str | None]]:
    if not SECTOR_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(SECTOR_CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_sector_cache(cache: dict[str, dict[str, str | None]]) -> None:
    SECTOR_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECTOR_CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


@lru_cache(maxsize=256)
def get_sector_info(yahoo_ticker: str) -> tuple[str | None, str | None]:
    disk_cache = _load_sector_cache()
    if yahoo_ticker in disk_cache:
        entry = disk_cache[yahoo_ticker]
        return entry.get("sector"), entry.get("industry")

    try:
        info = yf.Ticker(yahoo_ticker).info
        sector = info.get("sector")
        industry = info.get("industry")
    except Exception:
        sector = industry = None

    disk_cache[yahoo_ticker] = {"sector": sector, "industry": industry}
    _save_sector_cache(disk_cache)
    return sector, industry


def enrich_positions_with_sectors(positions: pd.DataFrame) -> pd.DataFrame:
    if positions.empty:
        return positions
    frame = positions.copy()
    sectors = []
    industries = []
    for symbol in frame["symbol"]:
        sector, industry = get_sector_info(xtb_to_yahoo(symbol))
        sectors.append(sector or "Unknown")
        industries.append(industry or "Unknown")
    frame["sector"] = sectors
    frame["industry"] = industries
    return frame


def sector_allocation(positions: pd.DataFrame) -> pd.DataFrame:
    if positions.empty or "sector" not in positions.columns:
        return pd.DataFrame()
    grouped = (
        positions.groupby("sector", as_index=False)
        .agg(
            market_value_pln=("market_value_pln", "sum"),
            unrealized_pnl=("unrealized_pnl", "sum"),
            symbols=("symbol", "count"),
        )
        .sort_values("market_value_pln", ascending=False)
    )
    total = grouped["market_value_pln"].sum()
    grouped["weight"] = grouped["market_value_pln"] / total if total else 0.0
    return grouped
