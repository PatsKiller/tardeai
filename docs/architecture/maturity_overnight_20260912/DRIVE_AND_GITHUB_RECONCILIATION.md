# GitHub and Drive memorialization — status, 2026-09-12

## GitHub

| item | state |
|---|---|
| campaign branch | `feat/l3-record-integrity-20260912` |
| PR | [#975](https://github.com/PatsKiller/tardeai/pull/975) |
| base | `eb648174aebc75d0e34eb105b8ff54925efccc7b` |
| force-pushes | 0 |
| history rewrites of pushed commits | 0 |
| merge state at time of writing | **not merged** — held until the exact head is green |

Per-commit audit with file stats: `evidence/GIT_AUDIT_COMMITS.md`.

### Documents committed to the repository

This campaign's package lives under
`trade-ai-campaigns/trade-ai-maturity-overnight-20260912/`, which is outside the
repository. That is deliberate for the *working* artifacts — they change every
few minutes and would be pure churn in git history. The canonical, dated
documents (AS-IS, FUTURE, GAP, scorecard) belong in
`docs/architecture/` alongside their predecessors, and committing them is the
remaining memorialization step.

**Done.** The canonical set is committed at
`docs/architecture/maturity_overnight_20260912/`.

The prior campaign's terminal verdict found exactly the failure this avoids: a
package that "exists only as Gmail attachments and untracked local files", with
the note that *email distribution is not memorialization*. Its newest AS-IS was
never in the repository at all — `git ls-files` found nothing matching its
claimed path. Committing the documents is what makes that claim checkable.

## Drive

**Not reconciled by this lane, and not reconcilable by it.**

`bin/guard` exposes no Drive scope — the prior campaign recorded a `drive-write`
request as `NOT GRANTABLE` and refused to substitute another scope for it. Drive
memorialization runs through the operator's own Google authentication.

What that means for anyone reading a Drive copy today:

- Drive's newest `CIO_AS_IS` was, at the previous campaign's audit, dated
  `2026-09-10-0114`, and `TERMINAL_VERDICT.md` had **never been uploaded**.
- Nothing in this campaign changed that.
- **Any Drive document describing current maturity predates the implementation
  it claims to describe.** Treat Drive as stale until an operator mirrors this
  package and re-downloads each artifact to recompute its SHA-256.

## Supersession

Prior current-claim documents are **not** deleted. When this package's documents
are committed, the previous dated set should be marked `SUPERSEDED` in place,
preserving the audit trail — the same discipline the 2026-09-11 verdict used
when it superseded the 2026-09-10 one.

This campaign supersedes no prior document, because it has committed none yet.
