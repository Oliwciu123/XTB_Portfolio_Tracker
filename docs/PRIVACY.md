# Privacy and publication checklist

The distributable example is generated from scratch by
`scripts/generate_sample_data.py`. Only the export layout was used as a reference.
Names, accounts, dates, trades, income, balances and market series are fictional.
The constants 90000000, 90000001 and 90000002 are synthetic identifiers.

Real records were discovered in the original Git history. With the owner's
explicit approval, affected blobs and identifying text were replaced in local
history using git-filter-repo. Named refs, stashes and the remaining checkpoint
tree were checked. Private recovery copies are excluded from Git. Never upload
the whole working directory or its private backups as a public archive.

**The GitHub remote was not force-pushed.** Before making it public, the owner
must replace the remote main with the reviewed cleaned history, verify the
repository's visibility, and inspect any GitHub releases, old attachments, PR refs
or cached views separately. A rewritten branch alone cannot remove separately
uploaded files. Collaborators should use a fresh clone after the rewrite.

As checked on 2026-11-07, GitHub is private and has only `main`. Its old tip is
`cb9960163c0ae3c7651a72fcfb4f150248f7be88`. After reviewing the cleaned history,
the owner can explicitly replace that exact remote tip:

```sh
git push --force-with-lease=refs/heads/main:cb9960163c0ae3c7651a72fcfb4f150248f7be88 origin main:main
```

This command has **not** been executed. If the lease fails, inspect the new remote
work before proceeding; do not overwrite it blindly. Verify a fresh GitHub clone
and successful CI, inspect old attachments/releases, then change visibility.

Keep exports, reports, caches, `.env` files and credentials out of commits.
The ignore rules cover normal locations, but review every staged file. Synthetic
fixtures belong in `examples/` and `tests/fixtures/`; private inputs belong in
`data/`. No credentials are needed for the demo.
