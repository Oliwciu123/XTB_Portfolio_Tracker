# Methodology and numerical checks

## Scope

The engine reconstructs long-only positions and cash from supported XTB histories.
Reference cases cover parsing, funding, partial sales, withdrawals, conversions,
splits, NAV, ROI, XIRR, TWR, risk and attribution. Tests verify the model, not the
accuracy of a market-data provider or every XTB export version.

## Portfolio value and returns

NAV is cash plus shares multiplied by prices in the account currency. Portfolio
prices are not dividend-adjusted: dividends and withholding taxes are cash rows.
Yahoo split adjustments are reversed for historical valuation, and positions and
unit costs change on the split date. Purchase cost comes from the cash debit.

Profit is `NAV + withdrawals − gross deposits`. ROI divides that profit by gross
deposits. External conversions use the exchange rate in the export where available;
other flows use the historical rate. Transfers between included accounts are
internal flows. An inbound conversion from an excluded account funds the analyzed
subset and is therefore external to that subset.

Daily TWR is `rₜ = NAVₜ / (NAVₜ₋₁ + Fₜ) − 1`; total TWR is `Π(1+rₜ) − 1`.
Flows occur at the start of the day. This is an approximation because an export
does not provide NAV immediately before each cash operation. A nonpositive capital
base produces no artificial daily return; complete withdrawals and recapitalization
therefore require care. Annualized TWR is shown after at least 30 days.

XIRR uses signed external flows and terminal NAV, solving NPV by bisection over
`(-0.9999, 100)` with ACT/365.25 year fractions. Missing opposite signs, same-day-only
flows or an unbracketed root yield no rate. Unconventional flows can have multiple
roots; the solver does not establish uniqueness. Period MWR is
`(1 + XIRR)^(holding days / 365.25) − 1`, rather than simple ROI.

## Currency and FX attribution

PLN FX rates come from NBP, requested in intervals of up to 93 days with preceding
history for nonbusiness days. Yahoo is a fallback. EUR/USD is derived from EUR/PLN
divided by USD/PLN. Each calculation uses a shared FX snapshot. Missing usable
prices or FX raise an error rather than silently valuing holdings at zero or 1:1.

For currency c, let V be local portfolio value, D net funded currency units, P
the PLN cost and f the current PLN exchange rate:

- Investment component: `(V − D) × f`.
- Currency component: `D × f − P`.

These sum exactly to PLN profit. Internal conversions carry the source currency's
capital cost proportionally to the target. This assigns the interaction effect
by convention; it is not a unique causal decomposition. The displayed 0.5%
conversion-cost estimate is an assumption, not a verified broker charge.

## Benchmarks

Adjusted benchmark prices are converted from quote currency into report currency.
The model buys or sells fractional units with the portfolio's external flows,
using the last known price on nontrading days. It is a hypothetical comparison,
not an executable trading simulation. A missing starting history excludes a series.
ETF/equity adjusted close models dividend reinvestment; price indices do not.

Custom Yahoo symbols are available in the desktop app when history, currency and
FX are supported. GBp/GBX and ZAc subunits are normalized. Futures do not model
multipliers, collateral or rolling. No benchmark commissions, spreads or taxes
are charged. The chart shows deposit-matched ROI, uses linear curves and exports
the displayed series to CSV. It does not shift observations to future month ends.

## Risk, income and holdings

Risk uses daily TWR, not changes in cumulative ROI. Volatility and Sharpe use 252
observations per year and a default annual risk-free rate of zero. Sortino uses
the root mean square of negative deviations from zero across all observations.
Undefined ratios display as unavailable. Historical daily VaR is the fifth
percentile of returns, not a guaranteed loss bound.

Drawdown uses the chain-linked wealth index and includes the initial wealth of 1.
Beta is covariance divided by benchmark variance; alpha is the annualized
arithmetic regression intercept. Benchmarks are expressed in report currency.
Monthly returns compound daily factors; first and last months may be partial.
Short or irregular samples make annualized figures approximate.

Company P&L includes realized and unrealized price gains; dividends appear in
income. Local P&L is translated at current FX, so it is not a tax-basis calculation.
Position, sector and currency allocations describe invested holdings and exclude
cash. Sector classifications depend on provider metadata.

## Polish PIT-38 tax settlement

The `PIT-38` section provides an educational Polish tax settlement across calendar
years (including current year-to-date estimates):

- **NBP Table A `D-1` conversion:** acquisition costs, disposal proceeds, commissions,
  gross dividends and foreign withholding taxes are translated into PLN using the
  official NBP Table A mid rate from the last business day strictly preceding the
  transaction date (`Art. 11a` PIT), looking back across weekends and Polish holidays.
- **FIFO capital gains (`Section C`, `Art. 30b` PIT):** sales match oldest open lots
  first within each sub-account and symbol. Partial lot sales pro-rate acquisition
  principal and buy-side commissions; stock splits adjust lot share counts while
  preserving original `D-1` PLN cost basis.
- **Dividends & foreign WHT (`Art. 30a` PIT):** gross dividends incur Poland's 19%
  flat rate; foreign tax withheld at source (`podatek u źródła`) is credited up to a
  19% cap per dividend payment, yielding net Polish surcharge (`do dopłaty`). Section C
  capital losses do not offset dividend tax.

## Data and refresh

Historical and current prices can be stale or revised. A five-second desktop
polling interval is not a promise of a fresh trade every five seconds. Standalone
HTML reports show their saved snapshot; the desktop bridge enables refresh and
custom benchmark downloads. The offline demo uses fictional quotes, FX and indices
and disables live fetching. Plotly.js is embedded, with no CDN requirement.

## Synthetic scenario

The distributable demo uses NumPy seed 42 and a pinned end date in `demo.json`.
Its 15 assets have distinct GBM drift, volatility and market-factor loadings.
Multiplicative drift shocks of 0.75 in 2022 and 0.88 in 2024 are applied across
their date windows; random returns mean observed drawdowns differ from those
shock magnitudes. No path is rescaled to a target ending price or positive return.
FX follows mean-reverting log processes, with EUR/PLN derived consistently.

Monthly funding alternates between the USD and EUR accounts. Withdrawals, partial
and complete sales, dividends, withholding tax, internal FX transfers, fees and
interest exercise the cash ledger. Transactions use simulated spot prices;
the model does not reproduce actual corporate actions, holidays, ETF tracking or
historical index total returns. Explicit instrument and benchmark currencies
avoid network lookups in the demo, including the PLN-denominated WIG20 scenario.

An independent cash/share ledger in `demo.json` reconciles terminal NAV. Tests
also check byte-identical regeneration, a nonmonotonic NAV path, drawdowns and
the XIRR/TWR equations. The simple parser fixtures are a separate test dataset.

Provider references: [NBP API](https://api.nbp.pl/) and
[Yahoo price adjustments](https://help.yahoo.com/kb/SLN28256.html).
