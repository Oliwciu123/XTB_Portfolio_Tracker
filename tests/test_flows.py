from decimal import Decimal

from xtb_analyzer.flows import CONVERSION_FEE_RATE, extract_deposits
from xtb_analyzer.parser import load_accounts


def test_extract_deposits_from_usd_account():
    accounts = load_accounts(["data/XTB_USD_account_cs.csv"])
    deposits = extract_deposits(accounts)
    assert len(deposits) == 8
    first = deposits[0]
    assert first.currency == "USD"
    assert first.amount_foreign == Decimal("1206.28")
    assert round(float(first.pln_spent), 2) == 4499.99


def test_conversion_fee_rate():
    assert CONVERSION_FEE_RATE == Decimal("0.005")


def test_conversion_loss_is_commission_only():
    accounts = load_accounts(["data/XTB_USD_account_cs.csv"])
    from xtb_analyzer.flows import analyze_conversion_losses

    losses = analyze_conversion_losses(accounts)
    assert not losses.empty
    for _, row in losses.iterrows():
        expected = float(row["pln_spent"]) * 0.005
        assert abs(row["total_loss_pln"] - expected) < 0.01
        assert abs(row["commission_loss_pln"] - expected) < 0.01
