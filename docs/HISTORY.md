# History consolidation

The owner requested a retrospective consolidation on 2026-11-07. The local branch
`backup/pre-rewrite` preserves the prior history; it is not intended for publication.
The new commits group actual feature milestones, rather than presenting the
original sequence of experiments and merges as individual changes.

Dates follow the original commits:

- 2026-06-28: project setup, cash-operation parsing and accounting foundations.
- 2026-06-30: NAV reconstruction and the initial analysis workflow.
- 2026-07-05: Nasdaq-100 benchmark.
- 2026-08-05: XIRR, TWR, risk metrics and HTML reports.
- 2026-08-06: allocation layout fixes and V2/multi-account export support.
- 2026-10-15: native desktop workflow and portable Windows build.
- 2026-10-21: the October SOX, live-refresh and interface changes.
- 2026-11-07: English cleanup, the seeded demo, CI, screenshots and documentation.

XIRR/TWR were not present in June, so they retain their actual August milestone.
The new simulation and screenshot work retain their November dates. Author and
committer identity are standardized to the maintainer's requested public name and
GitHub noreply address. Consolidation does not imply that every file was written
at a milestone's first timestamp, or that these are the untouched original commits.

Validation records apply to the final tree. Earlier fixture history was sanitized
before consolidation; no real exports were used to rebuild this history.
