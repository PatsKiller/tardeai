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
| Social-only high score | WATCH / WAIT only |
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

> Legacy alias: `scripts/momentum_scalp_paper_fast_path.py` still works and prints a deprecation note.
