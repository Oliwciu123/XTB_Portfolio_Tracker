# Repository audit

## Findings and changes

- **Privacy:** real account fixtures, identifiers and notebook output existed in
  history. Replaced affected records with wholly fictional fixtures, removed
  outputs, and rewrote local history after explicit owner approval. Private
  recovery copies remain ignored. The remote has not been rewritten; see PRIVACY.md.
- **Presentation:** Polish UI, comments and documentation obscured the public
  project. Current application text and documentation are English. Polish input
  aliases remain intentionally accepted by the parser.
- **Dependencies:** pyarrow was used but not consistently declared; GUI/notebook
  tools were mixed into the main installation. Runtime dependencies are explicit,
  desktop/build/notebook extras are optional, and uv.lock fixes resolved versions.
- **Portability:** removed a hardcoded Linux package path; packaged app storage
  uses platformdirs. Source commands work from the repository root on each OS.
- **Structure:** retained the existing src layout, removed the obsolete Flask
  preview server, moved release instructions to an English guide, and ignored
  editor settings, environments, data and generated output.
- **Reproducibility:** the old demo depended on real exports and online quotes.
  The new demo injects deterministic fictional prices/FX into the production
  calculation path. Screenshot generation blocks HTTP(S) requests.
- **Quality:** added Ruff formatting/linting, core type annotations, independent
  sample NAV/TWR/XIRR checks and multi-OS CI. Existing financial regression cases
  remain in the suite.
- **Charts:** retained linear lines without point markers, hidden Plotly toolbars,
  PNG buttons, expanded time ranges, and stable categorical plots. Headings live
  outside plot canvases to reduce label collisions.

## Analysis change with a concrete reason

The legacy `compute_metrics()` API divided profit by net contributions. After a
withdrawal, this disagreed with the main report and could erase profit after a
full exit. It now uses gross deposits as the denominator and subtracts net
contributions to calculate profit. A regression case deposits 1,000, reaches NAV
1,100 and withdraws 1,100: profit remains 100 and ROI remains 10%.

The core report's financial definitions were preserved. Market-data injection
changes where data comes from, not how NAV, TWR or XIRR are calculated. Precision,
cash-flow timing, benchmark and FX conventions are documented in METHODOLOGY.md.

## Validation boundaries

Local verification covers lint, formatting, tests, offline report generation and
real Chromium screenshots. CI defines Ubuntu, Windows and macOS checks; those
remote runs require publishing the cleaned main branch. Native packaged desktop
behavior and market-provider availability are separate from the offline demo.
