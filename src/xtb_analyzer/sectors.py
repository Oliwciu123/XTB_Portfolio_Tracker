from __future__ import annotations

from functools import lru_cache

import pandas as pd
import yfinance as yf

from xtb_analyzer.prices import xtb_to_yahoo


@lru_cache(maxsize=256)
def get_sector_info(yahoo_ticker: str) -> tuple[str | None, str | None]:
    try:
        info = yf.Ticker(yahoo_ticker).info
        return info.get("sector"), info.get("industry")
    except Exception:
        return None, None


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
