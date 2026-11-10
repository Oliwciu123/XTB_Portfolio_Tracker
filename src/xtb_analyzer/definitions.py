"""Structured definitions, numerical examples, and reference ranges for portfolio KPIs."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MetricRange:
    band: str
    meaning: str
    tone: str = "neutral"  # "pos" | "neutral" | "neg"


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    title: str
    formula: str
    explanation: str
    example: str
    ranges: tuple[MetricRange, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "title": self.title,
            "formula": self.formula,
            "explanation": self.explanation,
            "example": self.example,
            "ranges": [asdict(r) for r in self.ranges],
        }


METRIC_DEFINITIONS: dict[str, MetricDefinition] = {
    "nav": MetricDefinition(
        key="nav",
        title="Portfolio Net Asset Value (NAV)",
        formula="NAV = Cash Balances + Σ (Open Shares × Spot Price)",
        explanation=(
            "Measures the total liquidation value of all cash and open holdings across your "
            "accounts on the valuation date, translated into the selected report currency."
        ),
        example=(
            "If you hold 10 shares of MSFT at $400 ($4,000) plus $500 uninvested cash ($4,500 "
            "total) and USD/PLN is 4.00, your PLN Portfolio NAV is 18,000.00 PLN."
        ),
        ranges=(
            MetricRange(
                "NAV > Net Deposits", "Portfolio has generated a cumulative net gain", "pos"
            ),
            MetricRange(
                "NAV < Net Deposits", "Market value is below net contributed capital", "neg"
            ),
        ),
    ),
    "contributions": MetricDefinition(
        key="contributions",
        title="Gross Contributions",
        formula="Gross Contributions = Σ Inbound External Deposits",
        explanation=(
            "Tracks the total external cash funded into your brokerage accounts from outside "
            "sources. Internal currency transfers between your own XTB sub-accounts are excluded "
            "so capital is never double-counted."
        ),
        example=(
            "Depositing 10,000 PLN in January and converting 4,000 PLN into your USD sub-account "
            "in March still records 10,000 PLN in gross contributions (not 14,000 PLN)."
        ),
        ranges=(
            MetricRange(
                "Steady monthly inflows", "Supports dollar-cost averaging across cycles", "pos"
            ),
            MetricRange(
                "Single lump-sum inflow", "Performance depends more on entry valuation", "neutral"
            ),
        ),
    ),
    "profit_loss": MetricDefinition(
        key="profit_loss",
        title="Total Profit / Loss",
        formula="Profit / Loss = Current NAV + Withdrawals − Gross Contributions",
        explanation=(
            "Shows how much total wealth your portfolio has added or lost in monetary terms after "
            "accounting for every deposit and withdrawal, including realized trades, unrealized "
            "positions, dividends, interest, fees, and currency movements."
        ),
        example=(
            "If you deposited 50,000 PLN, withdrew 5,000 PLN to your bank, and your account is "
            "currently worth 58,000 PLN, your total profit is 58,000 + 5,000 − 50,000 = +13,000 PLN."
        ),
        ranges=(
            MetricRange("> 0", "Net wealth creation above contributed capital", "pos"),
            MetricRange("= 0", "Break-even relative to cash funded", "neutral"),
            MetricRange("< 0", "Cumulative capital loss across open and closed assets", "neg"),
        ),
    ),
    "roi": MetricDefinition(
        key="roi",
        title="Return on Contributed Capital (ROI)",
        formula="ROI = (NAV + Withdrawals − Gross Contributions) / Gross Contributions",
        explanation=(
            "Measures total monetary profit as a percentage of all capital you ever deposited. "
            "Easy to interpret, though it treats money deposited last week the same as money "
            "invested five years ago."
        ),
        example=(
            "Depositing 40,000 PLN in total and earning +10,000 PLN of net profit produces an "
            "ROI of +10,000 / 40,000 = +25.00%."
        ),
        ranges=(
            MetricRange(
                "> +20%", "Strong cumulative capital growth over multi-year horizons", "pos"
            ),
            MetricRange("0% to +20%", "Positive cumulative gain on funded capital", "neutral"),
            MetricRange("< 0%", "Portfolio value plus withdrawals trails total deposits", "neg"),
        ),
    ),
    "mwr_xirr": MetricDefinition(
        key="mwr_xirr",
        title="Money-Weighted Return (MWR / XIRR)",
        formula="Σ [Cash Flow_i / (1 + XIRR)^(days_i / 365.25)] = 0",
        explanation=(
            "Captures your personal return by weighting each deposit and withdrawal by the exact "
            "number of days that money worked in the market. XIRR is the annualized compound rate; "
            "MWR scales that rate to your actual holding period."
        ),
        example=(
            "Investing 10,000 PLN for 2 full years and adding 10,000 PLN one month before ending "
            "at 22,500 PLN yields ~11.4% annualized XIRR (higher than raw 12.5% / 2 yrs because "
            "half the capital was only invested for 1 month)."
        ),
        ranges=(
            MetricRange("> 10% annualized", "Outpaces historical nominal equity averages", "pos"),
            MetricRange(
                "4% – 10% annualized", "Typical balanced or inflation-beating return", "neutral"
            ),
            MetricRange(
                "< 0% annualized", "Negative compound return on deployed cash flows", "neg"
            ),
        ),
    ),
    "twr": MetricDefinition(
        key="twr",
        title="Time-Weighted Return (TWR & Annualized CAGR)",
        formula="TWR = Π [NAV_t / (NAV_{t−1} + Flow_t)] − 1",
        explanation=(
            "Measures the pure performance of your investment selections by neutralizing the "
            "timing and size of deposits or withdrawals. Because external cash flows are stripped "
            "out, TWR (and its annualized CAGR) is the standard metric for comparing against market "
            "indices like the S&P 500."
        ),
        example=(
            "Your portfolio rises +10% in H1 (from 10,000 to 11,000 PLN), you deposit 39,000 PLN "
            "(to 50,000 PLN), and it rises +5% in H2 (to 52,500 PLN). TWR is (1.10 × 1.05) − 1 = +15.50%."
        ),
        ranges=(
            MetricRange(
                "TWR > Benchmark", "Asset selection beat a passive index over the period", "pos"
            ),
            MetricRange(
                "0% < TWR < Benchmark", "Positive growth, but trailed passive indexing", "neutral"
            ),
            MetricRange("TWR < 0%", "Underlying holdings declined on a time-weighted basis", "neg"),
        ),
    ),
    "volatility": MetricDefinition(
        key="volatility",
        title="Annualized Volatility",
        formula="Volatility = StdDev(Daily TWR) × √252",
        explanation=(
            "Quantifies how widely your daily portfolio returns swing around their average, scaled "
            "to one trading year (252 days). Lower volatility means a smoother equity curve; higher "
            "volatility signals wider day-to-day price swings."
        ),
        example=(
            "If daily time-weighted returns have a standard deviation of 1.15%, annualized "
            "volatility is 1.15% × √252 ≈ 18.26%."
        ),
        ranges=(
            MetricRange("< 12%", "Low — typical of bond-heavy or conservative portfolios", "pos"),
            MetricRange(
                "12% – 22%",
                "Moderate — typical of diversified global or S&P 500 equities",
                "neutral",
            ),
            MetricRange(
                "> 25%", "High — concentrated growth stocks, tech, or leveraged exposure", "neg"
            ),
        ),
    ),
    "sharpe": MetricDefinition(
        key="sharpe",
        title="Sharpe Ratio",
        formula="Sharpe = √252 × Mean(Daily Excess Return) / StdDev(Daily Return)",
        explanation=(
            "Measures how much annualized return you earn for each unit of total volatility "
            "(both upside surges and downside drops). Higher values indicate more efficient "
            "compensation for the risk taken."
        ),
        example=(
            "A portfolio delivering a +15% annualized return with 12% annualized volatility "
            "(at a 0% baseline risk-free rate) achieves a Sharpe ratio of 15% / 12% = 1.25."
        ),
        ranges=(
            MetricRange("< 0.0", "Negative — portfolio lost value over the measured window", "neg"),
            MetricRange(
                "0.0 – 1.0", "Sub-optimal to modest return per unit of volatility", "neutral"
            ),
            MetricRange("1.0 – 2.0", "Good — strong risk-adjusted performance", "pos"),
            MetricRange("> 2.0", "Excellent — exceptional return relative to volatility", "pos"),
        ),
    ),
    "sortino": MetricDefinition(
        key="sortino",
        title="Sortino Ratio",
        formula="Sortino = √252 × Mean(Daily Return) / DownsideDeviation(Return < 0)",
        explanation=(
            "Refines the Sharpe ratio by penalizing only harmful downside volatility (negative "
            "days) rather than upside rallies. Ideal for growth portfolios that experience sharp "
            "positive breakouts without frequent losses."
        ),
        example=(
            "If annualized return is +16% and annualized downside deviation is 9% (even though "
            "total volatility is 15%), the Sortino ratio is 16% / 9% = 1.78."
        ),
        ranges=(
            MetricRange("< 0.0", "Negative average return", "neg"),
            MetricRange("0.0 – 1.0", "Modest compensation for downside risk", "neutral"),
            MetricRange("1.0 – 2.0", "Good — downside swings are well-compensated", "pos"),
            MetricRange("> 2.0", "Very strong — limited downside relative to gains", "pos"),
        ),
    ),
    "alpha": MetricDefinition(
        key="alpha",
        title="Annualized Alpha (Jensen's Alpha)",
        formula="Alpha = [Mean(R_p) − Beta × Mean(R_b)] × 252",
        explanation=(
            "Measures the excess annualized return your portfolio generated above (or below) what "
            "its market sensitivity (Beta) to the primary benchmark would predict. Positive alpha "
            "indicates value added through stock picking or sector allocation."
        ),
        example=(
            "If the S&P 500 rises +10%, your portfolio Beta is 1.20 (implying +12% expected market "
            "return), and your portfolio actually returns +15.5%, your annualized Alpha is +3.50%."
        ),
        ranges=(
            MetricRange("> +2.0%", "Strong outperformance after adjusting for market Beta", "pos"),
            MetricRange(
                "-2.0% to +2.0%", "Roughly in line with benchmark risk exposure", "neutral"
            ),
            MetricRange("< -2.0%", "Underperformed a Beta-equivalent passive position", "neg"),
        ),
    ),
    "beta": MetricDefinition(
        key="beta",
        title="Portfolio Beta",
        formula="Beta = Cov(R_portfolio, R_benchmark) / Var(R_benchmark)",
        explanation=(
            "Measures how sensitively your portfolio moves when the benchmark index moves by 1%, "
            "both expressed in the report currency. A Beta of 1.00 moves in lockstep with the index."
        ),
        example=(
            "With a Beta of 1.25 vs the S&P 500, a +2.0% rally in the benchmark corresponds on "
            "average to a +2.5% move in your portfolio (and a −2.5% move on a −2.0% market drop)."
        ),
        ranges=(
            MetricRange("< 0.85", "Defensive — less sensitive to broad market swings", "pos"),
            MetricRange("0.85 – 1.15", "Market-like sensitivity close to the index", "neutral"),
            MetricRange(
                "> 1.15", "Aggressive — amplifies both market rallies and sell-offs", "neg"
            ),
        ),
    ),
    "max_drawdown": MetricDefinition(
        key="max_drawdown",
        title="Maximum Drawdown (MDD)",
        formula="MDD = min_t [(Wealth_t − PeakWealth_{0..t}) / PeakWealth_{0..t}]",
        explanation=(
            "Captures the worst peak-to-trough percentage drop in the portfolio's time-weighted "
            "wealth index before a new high was reached. Represents the deepest historical storm "
            "an investor had to sit through."
        ),
        example=(
            "If your TWR wealth index climbed from 1.00 to 1.50, fell to 1.20 during a bear market, "
            "and later recovered to 1.65, the Maximum Drawdown is (1.20 − 1.50) / 1.50 = −20.00%."
        ),
        ranges=(
            MetricRange("0% to -15%", "Shallow drawdown — resilient capital preservation", "pos"),
            MetricRange(
                "-15% to -30%", "Moderate — normal equity market correction territory", "neutral"
            ),
            MetricRange(
                "Deeper than -30%", "Severe drawdown — requires > +43% gain to recover", "neg"
            ),
        ),
    ),
    "calmar": MetricDefinition(
        key="calmar",
        title="Calmar Ratio",
        formula="Calmar = Annualized TWR / |Maximum Drawdown|",
        explanation=(
            "Compares compound annual growth directly against the worst historical peak-to-trough "
            "drawdown. Answers how many percentage points of annual return you earned per percentage "
            "point of maximum pain."
        ),
        example=(
            "An annualized TWR of +14.0% paired with a Maximum Drawdown of −20.0% gives a Calmar "
            "ratio of 14.0% / 20.0% = 0.70."
        ),
        ranges=(
            MetricRange("< 0.5", "High drawdown cost relative to compound annual growth", "neg"),
            MetricRange("0.5 – 1.0", "Healthy balance for long-only equity portfolios", "neutral"),
            MetricRange("> 1.0", "Strong — annual compound return exceeds worst drawdown", "pos"),
        ),
    ),
    "var_95": MetricDefinition(
        key="var_95",
        title="Daily Value at Risk (Historical 95% VaR)",
        formula="VaR_95 = 5th Percentile of Daily TWR Returns",
        explanation=(
            "Shows the threshold loss exceeded on only the worst 5% of trading days (roughly 1 day "
            "per trading month) based on your actual historical return distribution."
        ),
        example=(
            "A Daily VaR (95%) of −1.85% on a 100,000 PLN portfolio means that on 95% of days "
            "daily losses stayed milder than −1,850 PLN, while 1 in 20 days lost 1.85% or more."
        ),
        ranges=(
            MetricRange("0% to -1.2%", "Contained single-day tail risk", "pos"),
            MetricRange("-1.2% to -2.5%", "Typical diversified equity daily risk", "neutral"),
            MetricRange("Worse than -2.5%", "Elevated single-day tail swings", "neg"),
        ),
    ),
    "win_rate": MetricDefinition(
        key="win_rate",
        title="Closed-Lot Win Rate",
        formula="Win Rate = Winning Closed Lots / Total Closed Lots",
        explanation=(
            "Percentage of closed FIFO stock lots that were sold for a net profit (after FX and "
            "commissions). High win rates feel comfortable, though trend-following portfolios can "
            "also thrive with a ~45% win rate if winners are much larger than losers."
        ),
        example=(
            "Closing 12 FIFO lots where 8 realized a net PLN profit and 4 realized a loss gives a "
            "Win Rate of 8 / 12 = 66.67%."
        ),
        ranges=(
            MetricRange("> 60%", "High consistency across closed trades", "pos"),
            MetricRange(
                "45% – 60%", "Balanced — profitability depends on average win/loss size", "neutral"
            ),
            MetricRange(
                "< 45%", "Low hit rate — requires large outlier winners to stay profitable", "neg"
            ),
        ),
    ),
    "profit_factor": MetricDefinition(
        key="profit_factor",
        title="Profit Factor",
        formula="Profit Factor = Gross Closed Profits / |Gross Closed Losses|",
        explanation=(
            "Measures how many units of realized gross profit were earned for every 1 unit of "
            "realized gross loss across closed positions. Combines both hit rate and payoff ratio "
            "into a single effectiveness number."
        ),
        example=(
            "If profitable sales summed to +9,000 PLN and losing sales summed to −4,000 PLN, the "
            "Profit Factor is 9,000 / 4,000 = 2.25 (+5,000 PLN net realized gain)."
        ),
        ranges=(
            MetricRange("< 1.00", "Unprofitable closed trades — losses exceed gains", "neg"),
            MetricRange("1.00 – 1.50", "Positive edge with modest margin over losses", "neutral"),
            MetricRange("1.50 – 2.50", "Solid — healthy realized profit-to-loss ratio", "pos"),
            MetricRange("> 2.50", "Strong — realized gains substantially outweigh losses", "pos"),
        ),
    ),
    "best_month": MetricDefinition(
        key="best_month",
        title="Best Monthly Return",
        formula="Best Month = max_m [Π_{t in m} (1 + r_t) − 1]",
        explanation=(
            "The highest calendar-month time-weighted return achieved by the portfolio across its "
            "entire history, unaffected by deposits made during that month."
        ),
        example=(
            "If daily TWR returns during November compounded from 1.000 to 1.094, your Best Month "
            "is +9.40%."
        ),
        ranges=(
            MetricRange("> +8%", "Strong upside participation during market rallies", "pos"),
            MetricRange("0% to +8%", "Moderate monthly peak", "neutral"),
        ),
    ),
    "worst_month": MetricDefinition(
        key="worst_month",
        title="Worst Monthly Return",
        formula="Worst Month = min_m [Π_{t in m} (1 + r_t) − 1]",
        explanation=(
            "The sharpest single calendar-month percentage decline in time-weighted value across "
            "the portfolio's history."
        ),
        example=(
            "If daily TWR returns during September compounded from 1.000 down to 0.924, your Worst "
            "Month is −7.60%."
        ),
        ranges=(
            MetricRange("0% to -5%", "Mild worst-case monthly pullback", "pos"),
            MetricRange("-5% to -10%", "Typical equity market correction month", "neutral"),
            MetricRange("Worse than -10%", "Sharp monthly sell-off", "neg"),
        ),
    ),
    "fx_conversion_cost": MetricDefinition(
        key="fx_conversion_cost",
        title="Estimated FX Conversion Cost (0.5%)",
        formula="Estimated Fee = Converted PLN Capital × 0.5%",
        explanation=(
            "Estimates the implicit currency conversion spread paid when funding USD or EUR "
            "accounts from PLN at XTB's standard 0.5% conversion markup. Because cash operations "
            "already record net converted units, this cost is already inside NAV and not deducted twice."
        ),
        example=(
            "Converting 20,000 PLN into USD across several deposits incurs an estimated 20,000 × "
            "0.005 = 100.00 PLN conversion cost."
        ),
    ),
    "investment_gain": MetricDefinition(
        key="investment_gain",
        title="Pure Investment Gain (PLN)",
        formula="Investment Gain = Σ_c [(LocalValue_c − NetDepositedUnits_c) × CurrentFX_c]",
        explanation=(
            "Isolates how much PLN profit came strictly from stock prices, dividends, and interest "
            "inside each currency bucket, evaluated at current exchange rates."
        ),
        example=(
            "Funding $10,000 that grows to $12,000 (+$2,000 local gain) when USD/PLN is 4.00 "
            "contributes +$2,000 × 4.00 = +8,000.00 PLN of pure investment gain."
        ),
    ),
    "fx_gain": MetricDefinition(
        key="fx_gain",
        title="Currency (FX) Gain / Loss (PLN)",
        formula="FX Gain = Σ_c [NetDepositedUnits_c × CurrentFX_c − PLN_Spent_c]",
        explanation=(
            "Isolates how much PLN profit or loss came from PLN strengthening or weakening against "
            "your foreign-currency capital base (including initial conversion spreads)."
        ),
        example=(
            "Buying $10,000 for 38,000 PLN (3.80 PLN/USD) and holding while USD/PLN rises to 4.05 "
            "adds $10,000 × 4.05 − 38,000 = +2,500.00 PLN of FX gain."
        ),
    ),
    "pit38_revenue": MetricDefinition(
        key="pit38_revenue",
        title="PIT-38 Section C Revenue (Przychód)",
        formula="Revenue = Σ [Gross Sale Proceeds × NBP_Table_A(SellDate − 1bd)]",
        explanation=(
            "Total gross proceeds from selling stocks/ETFs during the selected tax year, converted "
            "to PLN using the official NBP Table A mid rate from the last business day preceding "
            "each sale date (Art. 30b & Art. 11a PIT)."
        ),
        example=(
            "Selling 10 shares at $150 ($1,500 gross) on Monday May 4 when the last prior NBP Table A "
            "rate (Thursday Apr 30 before May 1 holiday) was 4.0200 yields 6,030.00 PLN of revenue."
        ),
    ),
    "pit38_costs": MetricDefinition(
        key="pit38_costs",
        title="PIT-38 Deductible Costs (Koszty uzyskania przychodu)",
        formula="Costs = Σ [FIFO Buy Cost × NBP(BuyDate − 1bd)] + Commissions_PLN",
        explanation=(
            "Original acquisition cost of the exact shares sold under First-In, First-Out (FIFO) "
            "lot matching—each lot translated at the D−1 NBP rate from its own purchase date—plus "
            "proportional buy and sell brokerage commissions."
        ),
        example=(
            "Selling 5 shares out of a 10-share lot bought for $1,000 when D−1 USD/PLN was 3.9000 "
            "assigns (5 / 10) × $1,000 × 3.9000 = 1,950.00 PLN of deductible acquisition cost."
        ),
    ),
    "pit38_income": MetricDefinition(
        key="pit38_income",
        title="PIT-38 Section C Profit / Loss (Dochód / Strata)",
        formula="Net Result = Section C Revenue − Deductible Costs",
        explanation=(
            "Taxable capital gain (Dochód) or tax loss (Strata) on closed equity positions in the "
            "selected calendar year. Notice that FX movements can create a PLN taxable profit even "
            "when the foreign-currency trade broke even, or vice versa."
        ),
        example=(
            "With 12,400.00 PLN in Section C revenue and 9,400.00 PLN in FIFO deductible costs, "
            "taxable income is +3,000.00 PLN (generating 3,000 × 19% = 570 PLN tax)."
        ),
        ranges=(
            MetricRange(
                "Profit > 0 PLN", "Taxed at Poland's 19% flat capital-gains rate", "neutral"
            ),
            MetricRange(
                "Loss < 0 PLN",
                "0 PLN Section C tax; loss can offset future Section C gains (up to 5 yrs)",
                "pos",
            ),
        ),
    ),
    "pit38_wht_credit": MetricDefinition(
        key="pit38_wht_credit",
        title="Foreign Withholding Tax Credit (Podatek u źródła)",
        formula="WHT Credit = min(Foreign WHT Paid_PLN, 19% × Gross Dividend_PLN)",
        explanation=(
            "Foreign tax withheld at source on dividends (converted at D−1 NBP rate) can be "
            "credited against Poland's 19% dividend tax, capped at 19% per dividend payment under "
            "double-taxation treaties (Art. 30a ust. 9 PIT)."
        ),
        example=(
            "On a $100 US dividend (400 PLN) with 15% US W-8BEN tax ($15 = 60 PLN): Polish 19% tax "
            "is 76 PLN, WHT credit is 60 PLN, leaving 16 PLN (4%) to pay in Poland. On a €100 German "
            "dividend with 26.38% WHT, credit caps at 19% and Polish surcharge is 0 PLN."
        ),
    ),
    "pit38_total_tax": MetricDefinition(
        key="pit38_total_tax",
        title="Total Polish PIT-38 Tax Payable",
        formula="Total Tax = Section C Tax (19%) + Dividend Surcharge (Do dopłaty)",
        explanation=(
            "Combined estimated Polish tax obligation for the selected year across closed equity "
            "trades (Section C) and foreign dividend surcharges (Section G). Capital losses in "
            "Section C cannot offset dividend tax in Section G under Polish law."
        ),
        example=(
            "If Section C capital-gains tax is 570 PLN and net foreign dividend tax to pay (4% top-up "
            "on US dividends) is 48 PLN, total estimated PIT-38 payable is 618 PLN."
        ),
    ),
}


def definitions_json_map() -> dict[str, dict[str, object]]:
    """Serialize all metric definitions for offline browser popovers."""
    return {key: item.to_dict() for key, item in METRIC_DEFINITIONS.items()}
