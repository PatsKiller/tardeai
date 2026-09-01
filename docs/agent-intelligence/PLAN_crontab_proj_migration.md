# Plan: Crontab `$PROJ` / `$PY` Runtime Migration (deferred)

Status:      ACTIVE
as_of:       2026-08-16T22:57:35-04:00
Measured at: efcc51365 / not measured

**Status**: PLAN ONLY — do not execute without a fresh operator GO. No changes
made under this plan during Phase 0 topology convergence.

## Context

The live `crontab` (936 lines) routes the majority of scheduled jobs through two
header variables:

```
PROJ=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
PY=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python
```

The old tree (`trade-ai-v12-rebuild`) is the **system-wide runtime** for the
whole trading stack, not just CIO. Consequences:

- **482** lines reference `trade-ai-v12-rebuild` literally.
- **135** lines hardcode `cd /home/johnclaw/trade-ai-v12-rebuild/...`.
- **347** lines use `$PROJ`.
- ~13 CIO-matching cron entries (e.g. `record_decision_outcome.py`,
  `agent_outcome_scorer.py`, `hermes_*`, `overnight_batch.py`,
  `rerun_cio_dual_consensus.py`) run old-tree code via `$PROJ`/`$PY` and are
  **invisible** to the topology audit's literal-path matching.

## Why this is out of Phase 0 scope

1. It is a full-stack migration, not a CIO-only change. The old tree serves
   Hermes, watchpool, Alpaca reconcilers, governance population, and other
   non-CIO surfaces.
2. The audit correctly flags literal old-tree paths, but a variable-indirection
   (`$PROJ`) is a different failure class — it requires the audit to resolve
   environment variables (via `crontab` header parsing), which is a separate
   enhancement with its own false-positive/negative risk.
3. Repointing `$PROJ` wholesale would touch ~347 jobs with no per-job import/
   data-safety verification yet.

## Proposed approach (for a future PR)

1. **Audit enhancement**: `_cron_lines()` / `enumerate_cron()` should parse the
   crontab header for `SHELL`/`PROJ`/`PY` and substitute them when resolving
   checkout paths, so `cd $PROJ && $PY scripts/x.py` is resolved to a concrete
   checkout and classified like a literal path.
2. **Staged repoint** (per surface, not wholesale):
   - CIO cron entries first (the ~13 `$PROJ`/`$PY` CIO jobs) → `CURRENT`.
   - Then decide on Hermes/watchpool/broker surfaces separately.
3. **Safety gates** (same as Phase 0):
   - Full crontab backup + rollback before install.
   - Per-script import smoke test from `CURRENT` before repointing.
   - Verify data symlinks (`data/`, `data/runtime`, `data/portfolios/state`)
     point to canonical state so no state divergence.
4. **Decision needed**: whether the old tree becomes a true "legacy only" tree
   (frozen, no further edits) or continues as active dev root for non-CIO
   surfaces. This determines whether `$PROJ` should point to `CURRENT` or to a
   new dedicated runtime root.

## Risks

- Wholesale repoint could break non-CIO jobs that depend on old-tree-only
  modules, configs, or data layouts.
- The venv (`$PY`) is shared runtime (not code) — its location is less urgent
  than `$PROJ`; a dedicated per-release venv is a separate decision.
- Cron has **no version history / undo** (per guardrails); a bad install needs
  the pre-install backup to restore.

## Rollback

`crontab < /tmp/crontab.backup.<timestamp>` (a full backup is captured before
any future install).
