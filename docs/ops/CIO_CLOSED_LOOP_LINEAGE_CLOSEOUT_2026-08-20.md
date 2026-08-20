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
