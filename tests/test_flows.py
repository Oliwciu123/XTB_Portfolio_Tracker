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
