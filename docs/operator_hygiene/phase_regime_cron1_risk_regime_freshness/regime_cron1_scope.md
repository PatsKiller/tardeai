# REGIME-CRON-1 Scope & Safety

## Current Issue

The risk-regime dashboard shows a valid snapshot from 2026-05-11 but it is 9 days stale. The classifier cron runs daily but never wrote results to the DB due to a `dry_run=True` default parameter bug.

## Session 33 Design (from Drive docs)

Risk regime is **proposal-only / no-auto-rotation**:
- **Collector** gathers market indicators (VIX, scan breadth, gap volatility, source health, news sentiment, market session)
- **Classifier** scores indicators into a regime label (risk_on_trend, risk_off, choppy_range, high_volatility, low_volatility_grind, broad_momentum, unknown)
- **Profiler** maps strategies to their preferred/disfavored regimes
- **Rotation engine** generates signals (favor/de_emphasize/review_required/neutral) — all marked `requires_admin_approval=True`
- **Dashboard** renders the current regime, indicators, signals, and trade alignments

Risk regime may inform review and propose rotation signals. It may not automatically enable, disable, promote, pause, or change any strategy.

## What REGIME-CRON-1 Changes

1. Fix `dry_run=False` parameter passing in collector, classifier, and rotation engine
2. Add transaction recovery to snapshot writer
3. Add run log recording
4. Create safe cron wrapper with guards and telemetry
5. Create health report script
6. Create staleness and schema contract audit scripts
7. Write fresh snapshot via classifier --apply

## What REGIME-CRON-1 Does NOT Change

- Strategy activation/deactivation
- YAML thresholds or Finviz criteria
- Trade execution or order submission
- Proposal approval gates
- Broker credentials or .env
- Alert routing tier assignments
- Auto-rotation behavior (remains disabled)

## AGENT-WORKER-1 Lessons Applied

1. **Schema verification** — schema contract audit confirms all referenced columns exist
2. **Cron batch vs daemon** — confirmed regime classifier is cron-triggered batch (not daemon)
3. **Transaction rollback recovery** — save_snapshot tests connection health, rolls back on error
4. **Read-only health report** — run_regime_cron1_health.py defaults to read-only
5. **No fake completion** — failed classifiers do not mark stale data current, run log records failure

## Rollback

```bash
bash scripts/rollback_regime_cron1_classifier_cron.sh
```

Reverts cron changes. The code fixes (dry_run parameter) are in git and can be reverted with `git revert`.
