# CIO Closed-Loop Lineage — Phase A Closeout (2026-08-20)

**Authority:** READ_ONLY_ADVISORY · No broker/order/stop/2FA  
**Base:** `origin/main` `8db42725`  
**Branch:** `wt/cio-closed-loop-maturity`

## What shipped

Live-forward `IntelligenceLineage@v1` hooks (in addition to existing rebuild/drain):

| Hook | Module | Stage |
|---|---|---|
| `enqueue_research_request` success | `cio_hermes_research.py` | `RESEARCH_REQUESTED` |
| `mark_completed` / persist result | `cio_hermes_research.py` | `RESEARCH_COMPLETED` (+ lineage_id on result) |
| `on_hermes_completed` | `hermes_research_loop.py` | complete + memory admit stamp |
| `reassess_on_research_completed` | `cio_product_reassessment.py` | `SYNTHESIZED` → `ADVISORY_USED` |

API: `GET /api/v3/intelligence/lineage` now reports `live_forward_count`, `live_forward_today`, `live_forward_7d`.

## Tests

`tests/test_cio_intelligence_lineage.py` (+ live-forward golden) · `test_cio_product_reassessment.py` · `test_hermes_research_loop.py` → **32 passed**.

Dry proof: `evidence/PHASE_A_LINEAGE_DRY_PROOF.json` (fixture research_id / result_id / lineage_id).

## Host units (unchanged ownership)

| Unit | Role |
|---|---|
| `tradeai-hermes-cio-worker.timer` | Structured queue drain (`--drain --max 2`) |
| Do not duplicate | Challenge overlay drain remains `intelligence_lineage.reconcile` / drain helpers |

## Residual gaps (honest)

- Outcomes matured still historically ~0 → Phase D.
- Material financial Telegram still policy-gated → Phase B canary flags (default OFF).
- Continuous desk memo schedule optional → Phase C.
- Do **not** claim full R7 / autonomy until live held-symbol drain produces non-null `lineage_id` on CURRENT **and** outcome matured count > 0.

## Host verify after promote

```bash
curl -sS localhost:7777/api/v3/intelligence/lineage | jq '{count,live_forward_count,live_forward_today,by_status}'
# optional drain (uses CURRENT):
# systemctl --user start tradeai-hermes-cio-worker.service
```

## LIVE HOST PROOF (2026-08-20)

| Field | Value |
|---|---|
| CURRENT SHA | `c5a6de188dfaabf856eeba6aa2cc18ba0699c095` |
| Release | `c5a6de18-main-exact-phase2-20260820-142426` |
| symbol | SCHD (held) |
| plan_id | `plan_43043a4ccdbe` (S6 proposed, desk@v5) |
| research_id | `res_da001ade8459` |
| result_id | `rr_a5131352ef0f` |
| lineage_id | `lin_4c9d72b25d58f05a6170` |
| status | **ADVISORY_USED** (live_forward) |
| product_id | `prod_05c8ef7715fd42b9` |
| reassessment_id | `reassessment:plan_43043a4ccdbe:rr_a5131352ef0f` |
| drain | `hermes_cio_worker.py --drain --max 1 --backend stub` on CURRENT (hooks proven; Flash not required for lineage attach) |
| API after | `live_forward_today=1`, `by_status.ADVISORY_USED=1` |

Residual #1 **CLOSED** for live-forward identity on CURRENT.

