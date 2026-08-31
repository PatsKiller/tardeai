# CIO Watch → S7 wire (Fix #2) — 2026-08-20

Status:      HISTORICAL
as_of:       2026-08-20T16:01:57-04:00
Measured at: efcc51365 / not measured

**READ_ONLY_ADVISORY.** No orders/stops. `CIO_TELEGRAM_INTERDICT=1` stays on. No Fix #1 reentry rewrite. No S1 cap redesign.

## Problem

After Fix #1 (PR #414 / `86e68ee6`): S3 live. S7_WATCH still 0 because snapshot `watch` / `watch_intelligence` came from thesis `watchlist.json` (no `items[]`, no READY|GO|NEAR), while `eval_s7` requires promotion statuses.

Watch producer (`list_watch_intelligence`) was **LIVE**; gap was evidence plumbing + honest status vocabulary.

## Fix

1. `normalize_watch_s7_status` / `project_watch_intelligence_for_cio` in  
   `scripts/lib/data_broker/watch_intelligence.py`  
   - Promotion-grade only → `READY` | `GO` | `NEAR`  
   - `proposal_allowed` → READY  
   - `trade_ai_state` READY/GO/PROMOTE/… → READY or GO  
   - `near_trigger` / `is_near_trigger` → NEAR (`strong_near` if no score)  
   - WAIT / MANAGING / street alone → **BLOCK** (no spam)
2. `_domain_watch_intelligence` in `scripts/lib/data_broker/cio_portfolio.py`  
   - Collector for domain `watch_intelligence` (broker + project)  
   - Domain `watch` remains thesis `watchlist.json` for legacy readers  
   - Fail-soft → `DATA_UNAVAILABLE` (no raise)

`eval_s7` unchanged.

## Host acceptance (notify off)

```bash
cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
export PYTHONPATH=.:scripts
CIO_SITUATION_NOTIFY=0 python3 - <<'PY'
from lib.cio_situation_detector import build_evidence_from_broker, CIOSituationDetector
from collections import Counter
ev = build_evidence_from_broker()
w = ev.get("watch_intelligence") or ev.get("watch")
print("watch_present", w is not None)
if isinstance(w, dict):
    print("counts", w.get("counts"))
    print("items", len(w.get("items") or []))
cands = CIOSituationDetector().collect_candidates(ev)
print(dict(Counter(str(c.get("situation_type")) for c in cands)))
s7 = [c for c in cands if str(c.get("situation_type")).startswith("S7")]
s3 = [c for c in cands if str(c.get("situation_type")).startswith("S3")]
print("S7", len(s7), [c.get("symbols") for c in s7[:20]])
print("S3_still", len(s3))
PY
```

**Content honesty:** If live broker has `proposal_eligible=0` and `near_trigger=0`, S7 may stay **0** after the wire — domain must still be present with projected `items` + counts. That is OK (same as empty READY reentry content).

## Non-goals

- Telegram / notify enable  
- Bulk S7 plans for all watch names  
- Hermes force-enqueue / thesis backfill / closing S1 flood  

## Follow-on

When watch desk marks `proposal_allowed` or `near_trigger`, S7 will light up without further plumbing.
