from datetime import datetime
from decimal import Decimal

import pandas as pd
import pytest

from xtb_analyzer.attribution import compute_fx_attribution
from xtb_analyzer.models import Account, Transaction


def _usd_account_with_deposit() -> Account:
    deposit = Transaction(
        id="1",
        account_id="123",
        currency="USD",
        type="transfer_in",
        timestamp=datetime(2024, 1, 1, 10, 0),
        symbol=None,
        amount=Decimal("1000"),
        comment="Currency conversion, PLN to USD from TA: 1 to: 123, Exchange rate:0.25",
    )
    return Account(account_id="123", currency="USD", transactions=[deposit])


def test_fx_attribution_decomposition():
    account = _usd_account_with_deposit()
    index = pd.DatetimeIndex([datetime(2024, 1, 1), datetime(2024, 6, 1)])
    nav = pd.DataFrame(
        {
            "local_pln": [0.0, 0.0],
            "local_usd": [1000.0, 1100.0],
            "local_eur": [0.0, 0.0],
            "deposits_pln": [4000.0, 4000.0],
        },
        index=index,
    )
    fx = pd.DataFrame({"USDPLN": [4.0, 4.2], "EURPLN": [4.3, 4.4]}, index=index)

    result = compute_fx_attribution([account], nav, fx=fx)

    # Investment: assets grew 1000 -> 1100 USD, valued at today's 4.2 PLN
    assert result.investment_gain_pln == pytest.approx(100 * 4.2)
    # Currency: 1000 USD bought for 4000 PLN (rate 4.0 incl. spread), now worth 4200 PLN
    assert result.fx_gain_pln == pytest.approx(1000 * 4.2 - 4000)
    assert result.total_gain_pln == pytest.approx(result.investment_gain_pln + result.fx_gain_pln)

    usd_row = result.by_currency[result.by_currency["currency"] == "USD"].iloc[0]
    assert usd_row["pln_spent"] == pytest.approx(4000.0)
    assert usd_row["units_received"] == pytest.approx(1000.0)
    assert usd_row["avg_deposit_rate"] == pytest.approx(4.0)
    assert usd_row["current_rate"] == pytest.approx(4.2)


def test_fx_attribution_identity_with_nav():
    """investment + fx must equal NAV_pln - deposits_pln when rates match."""
    account = _usd_account_with_deposit()
    index = pd.DatetimeIndex([datetime(2024, 1, 1), datetime(2024, 6, 1)])
    fx = pd.DataFrame({"USDPLN": [4.0, 4.2], "EURPLN": [4.3, 4.4]}, index=index)
    local_usd = pd.Series([1000.0, 1100.0], index=index)
    nav = pd.DataFrame(
        {
            "local_pln": [0.0, 0.0],
            "local_usd": local_usd,
            "local_eur": [0.0, 0.0],
            "nav_pln": local_usd * fx["USDPLN"],
            "deposits_pln": [4000.0, 4000.0],
        },
        index=index,
    )

    result = compute_fx_attribution([account], nav, fx=fx)
    expected_total = float(nav["nav_pln"].iloc[-1] - nav["deposits_pln"].iloc[-1])
    assert result.total_gain_pln == pytest.approx(expected_total)
