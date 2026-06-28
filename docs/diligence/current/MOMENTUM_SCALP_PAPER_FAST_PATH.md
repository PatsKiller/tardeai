# Momentum Scalp Paper Fast Path

_Operator decision 2026-06-28: momentum_scalp PAPER sample-collection does not require human/operator
paper approval. Deterministic gates replace the approval queue. Source:
`scripts/momentum_scalp_paper_fast_path.py`; covered by `tests/test_momentum_scalp_paper_fast_path.py`._

## What changed

- **Paper approval removed for momentum_scalp sample collection.** A momentum_scalp PENDING paper
  proposal that passes all deterministic gates is submitted straight to the paper-only path via the
  existing safe submitter (`proposal_paper_submitter.submit_paper`) — no human paper approval, no
  ATM approval queue.
- **Deterministic gates replace paper approval** (every one must pass; none weakened):
  strategy = momentum_scalp · account = alpaca_paper · route = momentum_scalp / actionability GO /
  catalyst_verified / not social-only / not scout · micro-float (≤20M, price ≤25, RVOL ≥5) ·
  inside 06:00–12:00 ET · proposal age ≤ 30-min TTL · valid trade plan + R:R ≥ 1.5 · **fresh quote** ·
  price drift ≤ max · liquidity known.
- **Live approval / 2FA unchanged.** The fast path is **paper-only** and never touches the live broker
  path. Live trading still requires the existing operator confirmation + two-factor path
  (`live_execution_policy` in `momentum_scalp.yaml`).
- **Large-float scouts** remain manual-review only and can never enter the momentum_scalp paper
  fast-path. **Social-only** candidates remain WATCH/WAIT only.
- **4.5 still requires the empirical paper sample** (≥30 confirmed closed paper trades, ≥50% win,
  ≥1.3 PF, ≥6 months, human promotion review). Removing paper approval does not change that.

## Candidate routing table

| Candidate type | Outcome |
|----------------|---------|
| Verified micro-float momentum GO (≤20M, ≤$25, RVOL≥5) | **Paper fast-path eligible** (deterministic submit, no approval) |
| Verified large-float social scout (>20M) | Manual-review scout only — never paper fast-path |
| Social-only high score | WATCH / WAIT only |
| Stale quote | Reject / defer (freshness preserved) |
| Out of window | Reject / defer |
| Invalid plan (missing/inverted/low R:R) | Reject |
| Live account (schwab/fidelity/etc.) | Reject (paper-only) |

## Usage

```bash
python3 scripts/momentum_scalp_paper_fast_path.py --dry-run     # read-only report (default)
python3 scripts/momentum_scalp_paper_fast_path.py --paper-only  # gate-pass → existing paper submit
```

Optional wiring (default OFF): `MOMENTUM_SCALP_PAPER_FAST_PATH=1` runs the fast path after proposal
generation (dry-run); `MOMENTUM_SCALP_PAPER_FAST_PATH_SUBMIT=1` enables paper submit. Idempotent —
the runner excludes already-EXECUTED proposals and `submit_paper` re-checks its own duplicate /
open-position / order-idempotency gates, and the daily/concurrent caps are enforced.

## Safety

No live broker writes. Operator confirmation / 2FA unchanged and out of scope. Autonomous live
submit remains disabled. Quote-freshness, TTL, intraday-window, liquidity, route-policy, social-only
cap, risk-sizing, and account-policy gates are all unchanged. LLMs advisory only.
