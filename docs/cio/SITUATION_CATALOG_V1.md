# Situation Catalog v1 (code freeze — Phase 2a)

**Authority:** READ_ONLY_ADVISORY only  
**Detector version:** `situation-catalog-v1.0.0`  
**Config:** `config/cio_situations.yaml`  
**Code:** `scripts/lib/cio_situation_detector.py`, `scripts/lib/cio_plans.py`  
**Plans:** `data/cio/cio_plans.jsonl`  
**SHADOW default:** plans + `situation.raised` events only; `notify: false`

Also see freeze note: `docs/advisory/desk-v1/SITUATION_CATALOG_V1_FREEZE.md`

**Related CIO desk tracks:** [P2B_PLAN_ENRICHMENT.md](P2B_PLAN_ENRICHMENT.md) ·
[THESIS_STORE_P3.md](THESIS_STORE_P3.md) · [WAKE_TRACES_P5.md](WAKE_TRACES_P5.md) ·
[CIO_TELEGRAM_CONVERSE_RUNBOOK.md](CIO_TELEGRAM_CONVERSE_RUNBOOK.md)

Plans may carry `thesis_version` (`desk@vN`) from the P3 thesis store when a desk thesis is published.

---

## Situations

| Code | Name | When (summary) | Owner |
|---|---|---|---|
| S1 | POSITION_LIFECYCLE | Held path: deep DD from basis, partial recovery, reclaim, major catalyst | alex |
| S2 | STOP_GAP | No stop or stop inconsistent with basis/recovery | alex |
| S3 | REENTRY_CANDIDATE | reentry_decision_desk READY/NEAR (read desk; no re-rank) | alex |
| S4 | SECTOR_ROTATION | Material sector_momentum / rotation_ladders vs holdings | steph |
| S5 | CASH_DEPLOYMENT | Cash above band + constructive rotation/watch READY cluster (label PARTIAL cash) | steph |
| S6 | CONCENTRATION_OR_DISPOSITION | Weight high or long-held material loser | morgan |
| S7 | WATCH_PROMOTION | Watch READY/GO/strong NEAR | alex |
| S8 | DEFENSIVE_REGIME | Risk-off regime, heat up, defensive proposals | alex |

**Rule:** every numeric claim from Data Broker evidence pack or `DATA_UNAVAILABLE`.

---

## Plan schema

See `scripts/lib/cio_plans.py`. Statuses: `draft|proposed|accepted|superseded|cancelled`.

API: `create_plan`, `update_plan`, `get_plan`, `list_open_plans`, `supersede_plan`.

---

## Non-goals (v1 / Phase 2a)

- Auto orders/stops  
- Telegram/WhatsApp bots  
- Free-text OPERATOR_MESSAGE path  
- Full Flash/Pro narrative (template summary only)  
- Desk promotion  
- Mem0/LangGraph/MCP  
- Second ranking system vs Watch/Reentry  

---

## Operator commands

```bash
# List open plans
.venv/bin/python -c "from scripts.lib.cio_plans import CIOPlanStore; \
  print(CIOPlanStore().list_open_plans(limit=20))"

# Run detector on SpaceX fixture (tests)
.venv/bin/python -m pytest tests/test_cio_situations_phase2a.py -q

# Disable detector
# config/cio_situations.yaml enabled: false
# or: CIO_SITUATIONS_ENABLED=0

# SHADOW (default)
# shadow: true ; CIO_SITUATIONS_NOTIFY=0

# Hooks (fail-soft)
# scripts/cio_heartbeat.py — after event emit
# scripts/cio_reactive_cycle.py — after goal wakes
```

## Acceptance

SpaceX-class mock (basis 210, last 138, trough 108, target 200, lockup+earnings, no stop above BE) must emit **S1 and/or S2** with hold / stop-above-BE / trim advisory options, non-empty evidence_refs, zero invented numbers, zero broker calls.
