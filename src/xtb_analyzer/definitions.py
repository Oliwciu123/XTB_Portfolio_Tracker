"""Structured definitions, offline typeset math formulas, examples, and reference ranges for KPIs."""

from __future__ import annotations

from dataclasses import asdict, dataclass


def _frac(num: str, den: str) -> str:
    return (
        f"<span class='m-frac'>"
        f"<span class='m-num'>{num}</span>"
        f"<span class='m-den'>{den}</span>"
        f"</span>"
    )


def _sqrt(radicand: str) -> str:
    return (
        "<span class='m-sqrt'>"
        "<svg class='m-sqrt-sym' viewBox='0 0 22 100' preserveAspectRatio='none' aria-hidden='true'>"
        "<polyline points='1,56 8,96 20,2 22,2' fill='none' stroke='currentColor' "
        "stroke-width='6' vector-effect='non-scaling-stroke' stroke-linecap='round' stroke-linejoin='round'/>"
        "</svg>"
        f"<span class='m-sqrt-body'>{radicand}</span>"
        "</span>"
    )


def _bigop(glyph: str, sub: str = "", sup: str = "") -> str:
    sup_html = (
        f"<span class='m-lim-sup'>{sup}</span>" if sup else "<span class='m-lim-empty'></span>"
    )
    sub_html = (
        f"<span class='m-lim-sub'>{sub}</span>" if sub else "<span class='m-lim-empty'></span>"
    )
    return (
        f"<span class='m-bigop'>{sup_html}<span class='m-op-glyph'>{glyph}</span>{sub_html}</span>"
    )


def _under(op: str, sub: str) -> str:
    return (
        f"<span class='m-underop'>"
        f"<span class='m-op-word'>{op}</span>"
        f"<span class='m-lim-sub'>{sub}</span>"
        f"</span>"
    )


def _v(sym: str, sub: str = "", sup: str = "", bar: bool = False) -> str:
    core = f"<span class='m-bar-over'>{sym}</span>" if bar else sym
    tail = ""
    if sub and sup:
        tail = f"<span class='m-scripts'><sup>{sup}</sup><sub>{sub}</sub></span>"
    elif sub:
        tail = f"<sub>{sub}</sub>"
    elif sup:
        tail = f"<sup>{sup}</sup>"
    return f"<span class='m-var'>{core}</span>{tail}"


def _t(label: str, sub: str = "", sup: str = "") -> str:
    tail = ""
    if sub and sup:
        tail = f"<span class='m-scripts'><sup>{sup}</sup><sub>{sub}</sub></span>"
    elif sub:
        tail = f"<sub>{sub}</sub>"
    elif sup:
        tail = f"<sup>{sup}</sup>"
    return f"<span class='m-rm'>{label}</span>{tail}"


def _abs(inner: str) -> str:
    return f"<span class='m-abs'>{inner}</span>"


def _paren(inner: str) -> str:
    return f"<span class='m-delim'>(</span>{inner}<span class='m-delim'>)</span>"


def _eq(lhs: str, rhs: str) -> str:
    return f"<div class='m-expr' role='math'>{lhs}<span class='m-rel'>=</span>{rhs}</div>"


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
    formula_html: str
    explanation: str
    example: str
    ranges: tuple[MetricRange, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "title": self.title,
            "formula": self.formula,
            "formula_html": self.formula_html,
            "explanation": self.explanation,
            "example": self.example,
            "ranges": [asdict(r) for r in self.ranges],
        }


METRIC_DEFINITIONS: dict[str, MetricDefinition] = {
    "nav": MetricDefinition(
        key="nav",
        title="Portfolio Net Asset Value (NAV)",
        formula="NAV = Cash + sum_i (Shares_i * Price_i * FX_i)",
        formula_html=_eq(
            _t("NAV"),
            f"{_t('Cash')} <span class='m-bin'>+</span> "
            f"{_bigop('&sum;', 'i=1', 'M')} "
            f"{_paren(_t('Shares', 'i') + ' &middot; ' + _t('Price', 'i') + ' &middot; ' + _t('FX', 'i'))}",
        ),
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
        formula="Gross Contributions = sum_{k in inbound} Deposit_k",
        formula_html=_eq(
            _t("Contributions", "gross"),
            f"{_bigop('&sum;', 'k &isin; inbound')} {_t('Deposit', 'k')}",
        ),
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
        formula="Profit / Loss = NAV + Withdrawals - Gross Contributions",
        formula_html=_eq(
            _t("P&amp;L"),
            f"{_t('NAV')} <span class='m-bin'>+</span> {_t('Withdrawals')} "
            f"<span class='m-bin'>&minus;</span> {_t('Contributions', 'gross')}",
        ),
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
        formula="ROI = (NAV + Withdrawals - Gross Contributions) / Gross Contributions",
        formula_html=_eq(
            _t("ROI"),
            _frac(
                f"{_t('NAV')} <span class='m-bin'>+</span> {_t('Withdrawals')} "
                f"<span class='m-bin'>&minus;</span> {_t('Contributions', 'gross')}",
                _t("Contributions", "gross"),
            ),
        ),
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
        formula="sum_{i=1..N} CF_i / (1 + XIRR)^(d_i / 365.25) = 0",
        formula_html=(
            "<div class='m-expr' role='math'>"
            f"{_bigop('&sum;', 'i=1', 'N')} "
            f"{_frac(_t('CF', 'i'), _paren('1 + ' + _t('XIRR')) + '<sup>' + _v('d', 'i') + ' / 365.25</sup>')}"
            "<span class='m-rel'>=</span>0"
            "</div>"
        ),
        explanation=(
            "Captures your personal return by weighting each deposit and withdrawal by the exact "
            "number of days that money worked in the market. XIRR is the annualized compound rate; "
            "period MWR compounds XIRR over your actual holding horizon."
        ),
        example=(
            "Investing 10,000 PLN on Jan 1, 2024, adding 10,000 PLN on Dec 1, 2025, and ending at "
            "22,500 PLN on Jan 1, 2026 yields +11.38% annualized XIRR and +24.08% 2-year MWR "
            "(versus +12.50% simple ROI, because the second 10,000 PLN worked for only 1 month)."
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
        formula="TWR = prod_{t=1..T} [NAV_t / (NAV_{t-1} + F_t)] - 1",
        formula_html=_eq(
            _t("TWR"),
            f"{_bigop('&prod;', 't=1', 'T')} "
            f"{_paren(_frac(_t('NAV', 't'), _t('NAV', 't&minus;1') + ' + ' + _v('F', 't')))} "
            f"<span class='m-bin'>&minus;</span> 1",
        ),
        explanation=(
            "Measures the pure performance of your investment selections by neutralizing the "
            "timing and size of deposits or withdrawals. Because external cash flows are stripped "
            "out, TWR (and its annualized rate) is the standard metric for comparing against "
            "market indices like the S&P 500."
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
        formula="sigma_ann = sqrt(252) * sqrt((1 / (N - 1)) * sum_{t=1..N} (r_t - mean(r))^2)",
        formula_html=_eq(
            _v("&sigma;", "ann"),
            f"{_sqrt('252')} &middot; "
            f"{_sqrt(_frac('1', _v('N') + ' &minus; 1') + ' ' + _bigop('&sum;', 't=1', 'N') + ' ' + _paren(_v('r', 't') + ' &minus; ' + _v('r', bar=True)) + '<sup>2</sup>')}",
        ),
        explanation=(
            "Quantifies how widely your daily portfolio returns swing around their average, scaled "
            "to one trading year (252 days). Lower volatility means a smoother equity curve; higher "
            "volatility signals wider day-to-day price swings."
        ),
        example=(
            "If daily time-weighted returns have a sample standard deviation of 1.15%, annualized "
            "volatility is 1.15% × √252 = 18.26%."
        ),
        ranges=(
            MetricRange("< 12%", "Low — typical of bond-heavy or conservative portfolios", "pos"),
            MetricRange(
                "12% – 22%",
                "Moderate — typical of diversified global or S&P 500 equities",
                "neutral",
            ),
            MetricRange(
                "> 25%", "High — concentrated growth stocks, tech, or single-sector risk", "neg"
            ),
        ),
    ),
    "sharpe": MetricDefinition(
        key="sharpe",
        title="Sharpe Ratio",
        formula="Sharpe = sqrt(252) * (mean(r_p) - r_f / 252) / sigma_p",
        formula_html=_eq(
            _t("Sharpe"),
            f"{_sqrt('252')} &middot; "
            f"{_frac(_v('r', 'p', bar=True) + ' &minus; ' + _v('r', 'f') + ' / 252', _v('&sigma;', 'p'))}",
        ),
        explanation=(
            "Measures how much annualized return you earn for each unit of total volatility "
            "(both upside surges and downside drops), using a 0% baseline risk-free rate by default. "
            "Higher values indicate more efficient compensation for the risk taken."
        ),
        example=(
            "A portfolio delivering a +15% annualized return with 12% annualized volatility "
            "(at r_f = 0%) achieves a Sharpe ratio of 15% / 12% = 1.25."
        ),
        ranges=(
            MetricRange("< 0.0", "Negative — portfolio lost value on a time-weighted basis", "neg"),
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
        formula="Sortino = sqrt(252) * mean(r_excess) / sqrt((1 / N) * sum_{t=1..N} min(r_t, 0)^2)",
        formula_html=_eq(
            _t("Sortino"),
            _frac(
                f"{_sqrt('252')} &middot; {_v('r', 'excess', bar=True)}",
                _sqrt(
                    f"{_frac('1', _v('N'))} {_bigop('&sum;', 't=1', 'N')} "
                    f"{_t('min')}{_paren(_v('r', 't,excess') + ', 0')}<sup>2</sup>"
                ),
            ),
        ),
        explanation=(
            "Refines the Sharpe ratio by penalizing only harmful downside deviations below zero "
            "across all trading days, rather than upside rallies. Ideal for growth portfolios that "
            "experience sharp positive breakouts without frequent losses."
        ),
        example=(
            "If annualized return is +16% and annualized target downside deviation is 9% (even "
            "though total volatility is 15%), the Sortino ratio is 16% / 9% = 1.78."
        ),
        ranges=(
            MetricRange("< 0.0", "Negative average daily return", "neg"),
            MetricRange("0.0 – 1.0", "Modest compensation for downside risk", "neutral"),
            MetricRange("1.0 – 2.0", "Good — downside swings are well-compensated", "pos"),
            MetricRange("> 2.0", "Very strong — limited downside relative to gains", "pos"),
        ),
    ),
    "alpha": MetricDefinition(
        key="alpha",
        title="Annualized Alpha (Jensen's Alpha)",
        formula="alpha = [mean(r_p) - beta * mean(r_b)] * 252",
        formula_html=_eq(
            _v("&alpha;"),
            f"<span class='m-delim'>[</span>{_v('r', 'p', bar=True)} "
            f"<span class='m-bin'>&minus;</span> {_v('&beta;')} &middot; {_v('r', 'b', bar=True)}"
            f"<span class='m-delim'>]</span> <span class='m-bin'>&times;</span> 252",
        ),
        explanation=(
            "Measures the excess annualized return your portfolio generated above (or below) what "
            "its market sensitivity (Beta) to the primary benchmark would predict. Positive alpha "
            "indicates value added through stock picking or sector allocation."
        ),
        example=(
            "If the S&P 500 rises +10% annualized, your portfolio Beta is 1.20 (implying +12.0% "
            "expected market return), and your portfolio achieves +15.5%, your Alpha is +3.50%."
        ),
        ranges=(
            MetricRange("> +2.0%", "Strong outperformance after adjusting for market Beta", "pos"),
            MetricRange(
                "-2.0% to +2.0%", "Broadly in line with benchmark risk exposure", "neutral"
            ),
            MetricRange("< -2.0%", "Underperformed a Beta-equivalent passive position", "neg"),
        ),
    ),
    "beta": MetricDefinition(
        key="beta",
        title="Portfolio Beta",
        formula="beta = Cov(r_p, r_b) / Var(r_b)",
        formula_html=_eq(
            _v("&beta;"),
            _frac(
                f"{_t('Cov')}{_paren(_v('r', 'p') + ', ' + _v('r', 'b'))}",
                f"{_t('Var')}{_paren(_v('r', 'b'))}",
            ),
        ),
        explanation=(
            "Measures how sensitively your portfolio moves when the benchmark index moves by 1%, "
            "both expressed in the report currency. A Beta of 1.00 moves in lockstep with the index."
        ),
        example=(
            "With a Beta of 1.25 vs the S&P 500, a +2.0% rally in the benchmark corresponds on "
            "average to a +2.5% move in your portfolio (and a −2.5% move on a −2.0% market drop)."
        ),
        ranges=(
            MetricRange(
                "< 0.85", "Defensive — lower sensitivity to broad equity swings", "neutral"
            ),
            MetricRange("0.85 – 1.15", "Market-like sensitivity close to the benchmark", "pos"),
            MetricRange(
                "> 1.15", "High-beta — amplifies both market rallies and drawdowns", "neutral"
            ),
        ),
    ),
    "max_drawdown": MetricDefinition(
        key="max_drawdown",
        title="Maximum Drawdown (MDD)",
        formula="MDD = min_t [(W_t - max_{s<=t} W_s) / max_{s<=t} W_s]",
        formula_html=_eq(
            _t("MDD"),
            f"{_under('min', 't')} "
            f"{_paren(_frac(_v('W', 't') + ' &minus; ' + _under('max', 's &le; t') + ' ' + _v('W', 's'), _under('max', 's &le; t') + ' ' + _v('W', 's')))}",
        ),
        explanation=(
            "Captures the worst peak-to-trough percentage drop in the portfolio's time-weighted "
            "wealth index before a new peak was reached. Represents the deepest historical decline "
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
        formula="Calmar = TWR_ann / |MDD|",
        formula_html=_eq(_t("Calmar"), _frac(_t("TWR", "ann"), _abs(_t("MDD")))),
        explanation=(
            "Compares compound annualized time-weighted growth directly against the magnitude of "
            "the worst historical drawdown. Answers how much annual return you earned per unit of "
            "peak-to-trough pain."
        ),
        example=(
            "An annualized TWR of +14.0% paired with a Maximum Drawdown of −20.0% gives a Calmar "
            "ratio of 14.0% / 20.0% = 0.70."
        ),
        ranges=(
            MetricRange("< 0.0", "Negative compound return over the holding window", "neg"),
            MetricRange("0.0 – 0.5", "Positive growth, but high drawdown cost", "neutral"),
            MetricRange("0.5 – 1.0", "Healthy balance for long-only equity portfolios", "neutral"),
            MetricRange("> 1.0", "Strong — annual compound return exceeds worst drawdown", "pos"),
        ),
    ),
    "var_95": MetricDefinition(
        key="var_95",
        title="Daily Value at Risk (Historical 95% VaR)",
        formula="VaR_95 = Percentile_5(r_1, r_2, ..., r_T)",
        formula_html=_eq(
            _t("VaR", "95%"),
            f"{_t('Q', '0.05')}{_paren(_v('r', '1') + ', ' + _v('r', '2') + ', &hellip;, ' + _v('r', 'T'))}",
        ),
        explanation=(
            "Shows the empirical threshold loss exceeded on only the worst 5% of trading days "
            "(roughly 1 day per trading month) based on your actual historical daily TWR returns."
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
        formula="Win Rate = N_winning_lots / N_closed_lots",
        formula_html=_eq(_t("Win Rate"), _frac(_v("N", "wins"), _v("N", "closed"))),
        explanation=(
            "Percentage of closed FIFO stock lots that were sold for a net PLN profit (after FX "
            "and commissions). High win rates feel comfortable, though trend-following portfolios "
            "can also thrive with a ~45% win rate if winners are much larger than losers."
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
        formula="Profit Factor = sum_{i in wins} Gain_i / |sum_{j in losses} Loss_j|",
        formula_html=_eq(
            _t("Profit Factor"),
            _frac(
                f"{_bigop('&sum;', 'i &isin; wins')} {_v('G', 'i')}",
                _abs(f"{_bigop('&sum;', 'j &isin; losses')} {_v('L', 'j')}"),
            ),
        ),
        explanation=(
            "Measures how many PLN of realized gross profit were earned for every 1 PLN of "
            "realized gross loss across closed FIFO lot slices. Combines hit rate and payoff ratio "
            "into a single effectiveness metric."
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
        formula="Best Month = max_m [prod_{t in m} (1 + r_t) - 1]",
        formula_html=_eq(
            _t("Best Month"),
            f"{_under('max', 'm')} "
            f"<span class='m-delim'>[</span>{_bigop('&prod;', 't &isin; m')} "
            f"{_paren('1 + ' + _v('r', 't'))} <span class='m-bin'>&minus;</span> 1<span class='m-delim'>]</span>",
        ),
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
        formula="Worst Month = min_m [prod_{t in m} (1 + r_t) - 1]",
        formula_html=_eq(
            _t("Worst Month"),
            f"{_under('min', 'm')} "
            f"<span class='m-delim'>[</span>{_bigop('&prod;', 't &isin; m')} "
            f"{_paren('1 + ' + _v('r', 't'))} <span class='m-bin'>&minus;</span> 1<span class='m-delim'>]</span>",
        ),
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
        formula="Fee_est = 0.005 * sum_k PLN_converted,k",
        formula_html=_eq(
            _t("Fee", "est"),
            f"0.005 &middot; {_bigop('&sum;', 'k')} {_t('PLN', 'converted,k')}",
        ),
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
        formula="G_inv = sum_c (V_c - D_c) * FX_c",
        formula_html=_eq(
            _v("G", "inv"),
            f"{_bigop('&sum;', 'c')} {_paren(_v('V', 'c') + ' &minus; ' + _v('D', 'c'))} &middot; {_t('FX', 'c')}",
        ),
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
        formula="G_fx = sum_c (D_c * FX_c - P_c)",
        formula_html=_eq(
            _v("G", "FX"),
            f"{_bigop('&sum;', 'c')} {_paren(_v('D', 'c') + ' &middot; ' + _t('FX', 'c') + ' &minus; ' + _v('P', 'c'))}",
        ),
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
        formula="Revenue = sum_k Proceeds_k * NBP_{D_sell,k - 1}",
        formula_html=_eq(
            _t("Revenue", "PLN"),
            f"{_bigop('&sum;', 'k')} {_t('Proceeds', 'k')} &middot; {_t('NBP', 'D_sell &minus; 1')}",
        ),
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
        formula="Costs = sum_k (Cost_FIFO,k * NBP_{D_buy,k - 1} + Comm_PLN,k)",
        formula_html=_eq(
            _t("Costs", "PLN"),
            f"{_bigop('&sum;', 'k')} {_paren(_t('Cost', 'FIFO,k') + ' &middot; ' + _t('NBP', 'D_buy &minus; 1') + ' + ' + _t('Comm', 'PLN,k'))}",
        ),
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
        formula="Net_C = Revenue_PLN - Costs_PLN",
        formula_html=_eq(
            _t("Net", "Section C"),
            f"{_t('Revenue', 'PLN')} <span class='m-bin'>&minus;</span> {_t('Costs', 'PLN')}",
        ),
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
        formula="Credit = sum_j min(WHT_PLN,j, 0.19 * Div_gross,PLN,j)",
        formula_html=_eq(
            _t("Credit", "WHT"),
            f"{_bigop('&sum;', 'j')} {_t('min')}{_paren(_t('WHT', 'PLN,j') + ', 0.19 &middot; ' + _t('Div', 'PLN,j'))}",
        ),
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
        formula="Tax_total = round(0.19 * max(Net_C, 0)) + round(Tax_div,due)",
        formula_html=_eq(
            _t("Tax", "total"),
            f"0.19 &middot; {_t('max')}{_paren(_t('Net', 'C') + ', 0')} "
            f"<span class='m-bin'>+</span> {_bigop('&sum;', 'j')} {_paren('0.19 &middot; ' + _t('Div', 'j') + ' &minus; ' + _t('Credit', 'j'))}",
        ),
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


FORMULA_TEX: dict[str, str] = {
    "nav": (
        r"\mathrm{NAV}=\mathrm{Cash}+\sum_{i=1}^{M}"
        r"\left(\mathrm{Shares}_{i}\cdot\mathrm{Price}_{i}\cdot\mathrm{FX}_{i}\right)"
    ),
    "contributions": (
        r"\mathrm{Contributions}_{\mathrm{gross}}"
        r"=\sum_{k\in\mathrm{inbound}}\mathrm{Deposit}_{k}"
    ),
    "profit_loss": (
        r"\mathrm{P\&L}=\mathrm{NAV}+\mathrm{Withdrawals}"
        r"-\mathrm{Contributions}_{\mathrm{gross}}"
    ),
    "roi": (
        r"\mathrm{ROI}=\frac{\mathrm{NAV}+\mathrm{Withdrawals}"
        r"-\mathrm{Contributions}_{\mathrm{gross}}}{\mathrm{Contributions}_{\mathrm{gross}}}"
    ),
    "mwr_xirr": (r"\sum_{i=1}^{N}\frac{\mathrm{CF}_{i}}{(1+\mathrm{XIRR})^{d_{i}/365.25}}=0"),
    "twr": (
        r"\mathrm{TWR}=\prod_{t=1}^{T}"
        r"\left(\frac{\mathrm{NAV}_{t}}{\mathrm{NAV}_{t-1}+F_{t}}\right)-1"
    ),
    "volatility": (
        r"\sigma_{\mathrm{ann}}=\sqrt{252}\cdot"
        r"\sqrt{\frac{1}{N-1}\sum_{t=1}^{N}\left(r_{t}-\bar{r}\right)^{2}}"
    ),
    "sharpe": (
        r"\mathrm{Sharpe}=\sqrt{252}\cdot"
        r"\frac{\bar{r}_{p}-r_{f}/252}{\sigma_{p}}"
    ),
    "sortino": (
        r"\mathrm{Sortino}=\frac{\sqrt{252}\cdot\bar{r}_{\mathrm{excess}}}"
        r"{\sqrt{\frac{1}{N}\sum_{t=1}^{N}\min(r_{t,\mathrm{excess}},0)^{2}}}"
    ),
    "alpha": (r"\alpha=\left[\bar{r}_{p}-\beta\cdot\bar{r}_{b}\right]\times 252"),
    "beta": (r"\beta=\frac{\mathrm{Cov}(r_{p},r_{b})}{\mathrm{Var}(r_{b})}"),
    "max_drawdown": (
        r"\mathrm{MDD}=\min_{t}"
        r"\left(\frac{W_{t}-\max_{s\le t}W_{s}}{\max_{s\le t}W_{s}}\right)"
    ),
    "calmar": (r"\mathrm{Calmar}=\frac{\mathrm{TWR}_{\mathrm{ann}}}{\left|\mathrm{MDD}\right|}"),
    "var_95": (r"\mathrm{VaR}_{95\%}=Q_{0.05}(r_{1},r_{2},\ldots,r_{T})"),
    "win_rate": (r"\mathrm{Win\ Rate}=\frac{N_{\mathrm{wins}}}{N_{\mathrm{closed}}}"),
    "profit_factor": (
        r"\mathrm{Profit\ Factor}="
        r"\frac{\sum_{i\in\mathrm{wins}}G_{i}}"
        r"{\left|\sum_{j\in\mathrm{losses}}L_{j}\right|}"
    ),
    "best_month": (
        r"\mathrm{Best\ Month}=\max_{m}"
        r"\left[\prod_{t\in m}(1+r_{t})-1\right]"
    ),
    "worst_month": (
        r"\mathrm{Worst\ Month}=\min_{m}"
        r"\left[\prod_{t\in m}(1+r_{t})-1\right]"
    ),
    "fx_conversion_cost": (
        r"\mathrm{Fee}_{\mathrm{est}}=0.005\cdot\sum_{k}\mathrm{PLN}_{\mathrm{converted},k}"
    ),
    "investment_gain": (r"G_{\mathrm{inv}}=\sum_{c}(V_{c}-D_{c})\cdot\mathrm{FX}_{c}"),
    "fx_gain": (r"G_{\mathrm{FX}}=\sum_{c}(D_{c}\cdot\mathrm{FX}_{c}-P_{c})"),
    "pit38_revenue": (
        r"\mathrm{Revenue}_{\mathrm{PLN}}=\sum_{k}\mathrm{Proceeds}_{k}"
        r"\cdot\mathrm{NBP}_{D_{\mathrm{sell}}-1}"
    ),
    "pit38_costs": (
        r"\mathrm{Costs}_{\mathrm{PLN}}=\sum_{k}\left(\mathrm{Cost}_{\mathrm{FIFO},k}"
        r"\cdot\mathrm{NBP}_{D_{\mathrm{buy}}-1}+\mathrm{Comm}_{\mathrm{PLN},k}\right)"
    ),
    "pit38_income": (
        r"\mathrm{Net}_{\mathrm{C}}=\mathrm{Revenue}_{\mathrm{PLN}}-\mathrm{Costs}_{\mathrm{PLN}}"
    ),
    "pit38_wht_credit": (
        r"\mathrm{Credit}_{\mathrm{WHT}}=\sum_{j}\min\left(\mathrm{WHT}_{\mathrm{PLN},j},"
        r"\,0.19\cdot\mathrm{Div}_{\mathrm{PLN},j}\right)"
    ),
    "pit38_total_tax": (
        r"\mathrm{Tax}_{\mathrm{total}}=0.19\cdot\max(\mathrm{Net}_{\mathrm{C}},0)"
        r"+\sum_{j}\left(0.19\cdot\mathrm{Div}_{j}-\mathrm{Credit}_{j}\right)"
    ),
}

INDICATOR_SUMMARY: dict[str, str] = {
    "nav": "Cash plus the market value of open holdings, in the report currency.",
    "contributions": "External cash paid in, ignoring transfers between your own XTB accounts.",
    "profit_loss": "Change in wealth after every deposit and withdrawal.",
    "roi": "Total profit as a percentage of all cash you deposited.",
    "mwr_xirr": "Return that weights each deposit by how long that cash was invested.",
    "twr": "Investment performance with deposit and withdrawal timing removed.",
    "volatility": "How widely daily returns move around their average, scaled to a trading year.",
    "sharpe": "Annualized excess return earned for each unit of total volatility.",
    "sortino": "Annualized excess return earned for each unit of downside volatility.",
    "alpha": "Annualized return above or below what this portfolio's beta would predict.",
    "beta": "How much the portfolio moves when the benchmark moves.",
    "max_drawdown": "Deepest peak-to-trough decline in the time-weighted wealth index.",
    "calmar": "Annualized time-weighted return divided by the worst drawdown.",
    "var_95": "Daily loss threshold breached on only the worst 5% of days.",
    "win_rate": "Share of closed FIFO lots that were sold at a profit.",
    "profit_factor": "Realized gross profit for each unit of realized gross loss.",
    "best_month": "Strongest calendar-month time-weighted return.",
    "worst_month": "Weakest calendar-month time-weighted return.",
    "fx_conversion_cost": "Estimated 0.5% cost of converting PLN into foreign currency.",
    "investment_gain": "PLN profit from prices, dividends, and interest, excluding currency moves.",
    "fx_gain": "PLN profit or loss from exchange-rate moves on foreign capital.",
    "pit38_revenue": "PLN sale proceeds for the selected tax year at each sale's prior-day NBP rate.",
    "pit38_costs": "FIFO purchase cost of the shares sold, plus brokerage commissions, in PLN.",
    "pit38_income": "Section C revenue minus deductible costs for the selected tax year.",
    "pit38_wht_credit": "Foreign dividend tax credited against Polish dividend tax, capped at 19%.",
    "pit38_total_tax": "Estimated Polish tax on equity sales plus the net dividend surcharge.",
}


def definitions_json_map() -> dict[str, dict[str, object]]:
    """Serialize metric definitions, including offline MathJax source."""
    payload = {key: item.to_dict() for key, item in METRIC_DEFINITIONS.items()}
    missing_tex = set(METRIC_DEFINITIONS) - set(FORMULA_TEX)
    missing_summary = set(METRIC_DEFINITIONS) - set(INDICATOR_SUMMARY)
    if missing_tex or missing_summary:
        raise KeyError(f"Indicator copy missing: tex={missing_tex} summary={missing_summary}")
    for key, item in payload.items():
        item["formula_tex"] = FORMULA_TEX[key]
        item["summary"] = INDICATOR_SUMMARY[key]
    return payload
