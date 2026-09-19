---
Status: APPLIED 2026-09-19T18:27 ET (correct consumer)
as_of: 2026-09-19T22:27:00Z
Measured at: crontab install under cron grant fbfcc0397b2a4975; backup /tmp/crontab.bak.wake_l3_persistent.20260919182730
Canonical repo path: docs/ops/PROPOSED_WAKE_L3_CRON_FLAGS_2026-09-19.md
Authority: AGENTS.md §9.3 / §17 — scheduler edits are operator-only
---

# PROPOSED — enable WAKE_L3 flags on the **L3 consumer** cron

## Correction `[VERIFIED]` 2026-09-19T22:25Z

`WAKE_L3_*` was applied to `*/5 cio_wake_dispatch_entrypoint.py`. That entrypoint
**never calls** `PersistentAgentWake._maybe_judge` / L3 (zero `l3`/`critique`
lines in `cio_wake_dispatcher.log`). L3 lives in `scripts/run_persistent_wake.py`
(hourly). Flags on the dispatch cron are inert for M2.

Live `persistent_wake.log` still shows DeepSeek `HTTP_402` and ChatGPT
`CODEX_HEADLESS_UNAVAILABLE` on author/curation paths. Free-oauth author chain
(chatgpt→grok) lands with #1094 tip; promote required.

## Why

M2 (critique → `next_research_question` writeback) is wired in
`persistent_agent_wake` but the **hourly** persistent-wake schedule must set:

- `WAKE_L3_JUDGMENT=1`
- `WAKE_L3_ALLOW_LIVE_PROVIDER=1`

## Proposed crontab change (operator / cron grant)

On the existing hourly `run_persistent_wake.py` line, after `set +a;`, add:

```bash
WAKE_L3_JUDGMENT=1 WAKE_L3_ALLOW_LIVE_PROVIDER=1
```

Keep free-first / cost caps unchanged. Lane registry row must stay in sync if
the match string changes.
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


## Applied receipt `[VERIFIED]` 2026-09-19T18:27 ET

- Backup: `/tmp/crontab.bak.wake_l3_persistent.20260919182730`
- Diff: single line — hourly `run_persistent_wake.py` gained `WAKE_L3_JUDGMENT=1 WAKE_L3_ALLOW_LIVE_PROVIDER=1` after `set +a;`
- Match `scripts/run_persistent_wake.py --agent-id cio` unchanged
- Grant: cron request `fbfcc0397b2a4975` (uses consumed)
