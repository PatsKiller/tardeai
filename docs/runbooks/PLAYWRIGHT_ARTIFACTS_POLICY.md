# Playwright / visual-review artifact policy

Status: IMPLEMENTED_AND_VERIFIED (this branch) · Owner: operator + any session running visual captures

## The rule

Screenshots, visual-review captures, and crawler output are **ephemeral run artifacts, not
documentation**. They must never be committed to Git under `docs/` and never uploaded to the
canonical `Trade_AI_Docs_v2` Drive folder.

History: 2026-07-14 a 37-shot Redeploy visual review was committed to `docs/redeploy_review_2026-07-14/`
and mirrored to Drive. Removed in `chore(docs): remove temporary redeploy visual-review captures`.
This policy prevents recurrence.

## Where captures go

```
artifacts/playwright/<tool-or-desk>/<run_id>/   # run_id = UTC timestamp, e.g. 20260714T1530Z
```

- `artifacts/` is **gitignored** (root `.gitignore`).
- `artifacts/` lives outside `docs/`, so `sync-docs-to-drive.sh` never sees it; the sync script
  additionally hard-excludes `*redeploy_review*` and any `*/artifacts/*` path as belt-and-suspenders.
- Every run writes an `index.html` (or `README.md`) manifest into its run directory so CI/operator
  review needs no directory spelunking.
- Sharing for review: attach to the PR, or upload to a **non-canonical** Drive scratch folder —
  never `Trade_AI_Docs_v2`.

## Retention

`scripts/artifacts_retention.sh` deletes run directories older than `ARTIFACTS_RETENTION_DAYS`
(default **7**). Run it manually or via cron alongside other retention jobs
(`docs_retention.sh` pattern). It only ever touches `artifacts/`.

## What still belongs in docs/

- Markdown audit *reports* (e.g. `docs/audits/*.md`) — text, reviewable, diffable.
- Permanent visual-regression *tests* and their committed baseline configs (not run output).
- Acceptance evidence explicitly requested as documentation, in Markdown with numbers, not PNG dumps.
