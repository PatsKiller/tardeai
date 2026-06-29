# Momentum Scalp Validation Fast Path

_Canonical operator-facing doc. Source: `scripts/momentum_scalp_validation_fast_path.py`; covered by
`tests/test_momentum_scalp_validation_fast_path.py`._

## Terminology note

"Validation execution" is the operator-facing term for sandbox/simulated strategy-sample collection
used to build the empirical sample before promotion. Some legacy storage/adapters still use `paper_*`
names for backward compatibility (the `paper_trades` table, `proposal_paper_submitter`,
`paper_trade_logger`, the `alpaca_paper` sandbox account) — but the canonical TradeAI lifecycle term
is **validation**, not paper.

## What this is

- **Validation approval is not required** for momentum_scalp sample collection — deterministic gates
  replace it. A momentum_scalp proposal that passes ALL gates is submitted straight to the
  sandbox/simulated path via the existing safe submitter (legacy `proposal_paper_submitter`,
  sandbox-only + idempotent).
- **Live trading is unchanged** — operator confirmation + 2FA remain immutable and out of scope. The
  validation fast path is sandbox/simulated only and never reaches a live broker submit.
- Large-float social scouts stay manual-review only; social-only candidates stay WATCH/WAIT only.
- **4.5 still requires the empirical sample** (≥30 confirmed closed simulated validation trades,
  ≥50% win, ≥1.3 PF, ≥6 months, human promotion review).

## Deterministic gates (none weakened)

strategy=momentum_scalp · account=alpaca_paper (sandbox) · route=momentum_scalp/GO/verified/not-social/
not-scout · micro-float (≤20M, ≤$25, RVOL≥5) · inside 06:00–12:00 ET · age ≤ 30-min TTL · valid plan +
R:R≥1.5 · fresh quote · price-drift ≤ max · liquidity known.

## Candidate routing table

| Candidate type | Outcome |
|----------------|---------|
| Verified micro-float momentum GO | Validation fast-path eligible (deterministic submit, no approval) |
| Verified large-float social scout (>20M) | Manual-review scout only — never validation fast-path |
| **Social Scout (≥2/5 pillars, not GO)** | **Operator-awareness pill only — REJECTED from the fast path (`SOCIAL_SCOUT_NOT_VALIDATION_ELIGIBLE`); never validation-eligible.** See [SOCIAL_SCOUT_PILLARS.md](SOCIAL_SCOUT_PILLARS.md). |
| Social-only high score | WATCH / WAIT / SCOUT only |
| Stale quote | Reject / defer (freshness preserved) |
| Out of window | Reject / defer |
| Invalid plan | Reject |
| Live account | Reject (sandbox-only) |

## Usage

```bash
python3 scripts/momentum_scalp_validation_fast_path.py --dry-run         # read-only (default)
python3 scripts/momentum_scalp_validation_fast_path.py --submit-sandbox  # gate-pass → sandbox submit
python3 scripts/momentum_scalp_validation_fast_path.py --loop --sleep-seconds 120 --dry-run
```

Env-gated wiring (default OFF): `MOMENTUM_SCALP_VALIDATION_FAST_PATH=1` (run after generation, dry-run);
`MOMENTUM_SCALP_VALIDATION_SUBMIT=1` (sandbox submit). Idempotent + daily/concurrent caps enforced.

## Scheduled sample collection (live)

Two complementary sandbox-only paths run weekdays inside the 06:00–12:00 ET window to accumulate the
empirical validation sample. Both are idempotent and the internal window gate self-enforces (post-12:00
batches no-op), so running both is safe overlap, not double submission.

| Path | Cron | Timing role |
|------|------|-------------|
| **Finviz 5-min early lane** | `*/5 6-11 * * 1-5` `run_finviz_momentum_scalp_scan.py --window early --apply --sync-signals --generate-proposals --run-validation-fast-path --submit-validation` (flock-locked) | **Every 5 min** — refreshes the Finviz source then chains signal sync → proposals → validation so fresh candidates reach validation fast (operator decision 2026-06-28). See [MOMENTUM_SCALP_SOURCE_LIFECYCLE.md](MOMENTUM_SCALP_SOURCE_LIFECYCLE.md). |
| Generation hook | `*/30 9-16 * * 1-5` `auto_proposal_generator.py --today --apply` with `MOMENTUM_SCALP_VALIDATION_FAST_PATH=1 MOMENTUM_SCALP_VALIDATION_SUBMIT=1` | Fires the fast path immediately after each proposal batch — tightest timing, before quotes stale |
| Standalone runner | `*/2 6-11 * * 1-5` `momentum_scalp_validation_fast_path.py --submit-sandbox` (flock-locked) | Every 2 min — backup; catches proposals that become entry-valid between generation cycles |

The hook lives in `run_auto_proposals()` (`maybe_run_after_generation`); it is sandbox/simulated only and
never reaches a live broker submit. Maturity stays at the honest empirical level (confirmed-closed sample
out of the 30 required) until the window runs and samples accrue — purely operational/data from here.

> Legacy alias: `scripts/momentum_scalp_paper_fast_path.py` still works and prints a deprecation note.
> Legacy env aliases `MOMENTUM_SCALP_PAPER_FAST_PATH[_SUBMIT]=1` are still honored by the hook.
