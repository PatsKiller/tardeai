---
Status: APPLIED 2026-09-19 (cron grant overnight maturity)
as_of: 2026-09-19T22:10:00Z
Measured at: worktree tip (pre-merge); not applied to crontab
Canonical repo path: docs/ops/PROPOSED_WAKE_L3_CRON_FLAGS_2026-09-19.md
Authority: AGENTS.md §9.3 / §17 — scheduler edits are operator-only
---

# PROPOSED — enable WAKE_L3 flags on the wake dispatch cron

## Why

M2 (critique → `next_research_question` writeback) is wired in code
(`apply_critique_question_writeback` from `persistent_agent_wake`) but the
scheduled entrypoint never sets:

- `WAKE_L3_JUDGMENT=1`
- `WAKE_L3_ALLOW_LIVE_PROVIDER=1`

Both default OFF. Without them the organic L3 author/critic path never runs,
so `wake_critique_question.jsonl` stays absent even after `l3_judgment_author`
is registered (#1090).

DeepSeek HTTP 402 on the paid author path remains a separate provider/operator
issue; enabling the flags is necessary but not sufficient for organic M2 when
the paid lane is refused.

**Code prerequisite (landed with #1094 follow-up):** `_maybe_judge` now builds a
material question for `instrument_record_due` as well as `unconsumed_research`.
Without that, IR-due wakes skipped L3 even with flags on.

## Proposed crontab change (do not apply without operator grant)

On the existing `*/5` `cio_wake_dispatch_entrypoint.py` line, prefix:

```bash
WAKE_L3_JUDGMENT=1 WAKE_L3_ALLOW_LIVE_PROVIDER=1
```

Keep free-first / cost caps unchanged. Lane registry row must stay in sync if
the match string changes (§9.3).

## Proof after grant

1. Unattended wake with `provenance.l3` non-null on a research-selected subject.
2. `data/cio/wake_critique_question.jsonl` row with `applied=true`.
3. `report_maturity_bar_m1_m5.py` → M2 OBSERVED.

## Applied

- [VERIFIED] 2026-09-19: wake `*/5` crontab line now runs
  `cd CURRENT && WAKE_L3_JUDGMENT=1 WAKE_L3_ALLOW_LIVE_PROVIDER=1 flock ... entrypoint`
  (env after `&&` so it binds to python, not only `cd`).
- Backup: `/tmp/cron-backup-wake-l3/crontab.before.20260919T220751Z`
- Served code still needs #1094 merge+promote for IR-due L3 question + 402→chatgpt author fallback.
