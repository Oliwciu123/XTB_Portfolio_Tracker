from decimal import Decimal
from pathlib import Path

from xtb_analyzer.flows import CONVERSION_FEE_RATE, analyze_conversion_losses, extract_deposits
from xtb_analyzer.parser import load_accounts

FIXTURES = Path(__file__).parent / "fixtures"


def test_conversion_fee_rate():
    assert CONVERSION_FEE_RATE == Decimal("0.005")


def test_extract_deposits_from_modern_fixture():
    accounts = load_accounts([FIXTURES / "modern_usd_cash_ops.csv"])
    deposits = extract_deposits(accounts)
    assert len(deposits) == 8
    first = deposits[0]
    assert first.currency == "USD"
    assert first.amount_foreign == Decimal("1000.00")
    assert round(float(first.pln_spent), 2) == 4000.00


def test_conversion_loss_is_commission_only():
    accounts = load_accounts([FIXTURES / "modern_usd_cash_ops.csv"])
    losses = analyze_conversion_losses(accounts)
    assert not losses.empty
    for _, row in losses.iterrows():
        expected = float(row["pln_spent"]) * 0.005
        assert abs(row["total_loss_pln"] - expected) < 0.01
        assert abs(row["commission_loss_pln"] - expected) < 0.01
