# CIO Reentry → S3 wire (Fix #1) — 2026-08-20

**READ_ONLY_ADVISORY.** No orders, stops, Telegram enable, or S7/watch changes.

## Problem

Investigation on CURRENT proved:

| Plane | Status |
|-------|--------|
| Reentry producer (`build_decision_desk` → `reentry_decision_desk_latest.json`) | **LIVE** |
| `get_cio_snapshot` domains `reentry` / `reentry_decision_desk` | **MISSING** |
| `eval_s3` evidence | `None` → **S3 = 0** |

Gap was evidence plumbing + status vocabulary, not a missing producer.

## Fix

1. `project_reentry_desk_for_cio` / `normalize_reentry_s3_status` in  
   `scripts/lib/data_broker/reentry_decision_desk.py`  
   - Maps `intel.state` → top-level `READY` \| `NEAR` \| `BLOCK`  
   - `READY TO REVIEW` / `IN_ZONE` → `READY`  
   - `NEAR ENTRY` / `OVERSOLD REVIEW` → `NEAR`  
   - WAIT / HELD / MISSING* → `BLOCK` (desk-visible, not S3)
2. `_domain_reentry` in `scripts/lib/data_broker/cio_portfolio.py`  
   - Reads `data/runtime/reentry_decision_desk_latest.json` (zero provider calls)  
   - Registers collectors `reentry` + `reentry_decision_desk`  
   - Fail-soft → `DATA_UNAVAILABLE` (no raise)

`eval_s3` unchanged. `max_plans_per_pass` / dedup unchanged. Notify unchanged (default off).

## Acceptance checks

```bash
cd <worktree-or-CURRENT>
export PYTHONPATH=.:scripts
pytest -q tests/test_cio_reentry_s3_wire.py

# Host dry-run (notify off)
CIO_SITUATION_NOTIFY=0 python3 - <<'PY'
from lib.cio_situation_detector import build_evidence_from_broker, CIOSituationDetector
ev = build_evidence_from_broker()
desk = ev.get("reentry_decision_desk") or ev.get("reentry")
print("domain_present", desk is not None)
if isinstance(desk, dict):
    print("counts", desk.get("counts"))
cands = CIOSituationDetector().collect_candidates(ev)
s3 = [c for c in cands if str(c.get("situation_type")).startswith("S3")]
print("S3", len(s3), [c.get("symbols") for c in s3[:20]])
PY
```

**Content note:** After the wire, S3 count reflects live READY/NEAR only. A non-None domain with S3=0 is a content outcome (desk has no READY/NEAR), not a plumbing failure.

## Non-goals (still)

- Always-on Telegram / `CIO_SITUATION_NOTIFY` enable  
- S7 / watch wire (Fix #2)  
- S1 open-plan cap redesign  
- Force-enqueue Hermes / thesis acquisition / LLM caps  

## Follow-on

Fix #2: watch_intelligence items with READY|GO|NEAR for S7 (separate PR).
