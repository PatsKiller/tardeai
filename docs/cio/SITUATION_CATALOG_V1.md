# Situation Catalog v1 (code freeze — Phase 2a)

**Authority:** READ_ONLY_ADVISORY only  
**Detector version:** `situation-catalog-v1.0.0`  
**Config:** `config/cio_situations.yaml`  
**Code:** `scripts/lib/cio_situation_detector.py`, `scripts/lib/cio_plans.py`  
**Plans:** `data/cio/cio_plans.jsonl`  
**SHADOW default:** plans + `situation.raised` events only; `notify: false`

Also see freeze note: `docs/advisory/desk-v1/SITUATION_CATALOG_V1_FREEZE.md`

**R11 operator-value layer:** `CIOSituationState@v1` does not replace S1–S8.
It answers “what material situation deserves attention now?” (EXCESS_CASH,
CONCENTRATION, POLICY_GAP, …). S1–S8 remain draft-plan identities. Mapping is
in `scripts/lib/cio_situation_state.py` `LEGACY_PLAN_TYPE`.

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

---

## P2 live Data Broker wiring (2026-08-11)

**Entry points**
- `scripts/cio_heartbeat.py` → `build_evidence_from_snapshot` → `run_detector_safe`
- `scripts/cio_reactive_cycle.py` → `build_evidence_from_broker()` (live `get_cio_snapshot`)
- Manual: `CIOSituationDetector().run(build_evidence_from_broker())`

**Domains used (live)**
`holdings_detail`, `portfolio`, `cost_basis`, `cash_buying_power`, `risk`, `rotation`, `hermes_research`, `watch`/`watch_intelligence` (often empty), `sectors`, …

**High-value situations on this host**
- **S5** cash above band (~45% cash / total)
- **S6** concentration (e.g. SCHD ~17.6% portfolio weight)
- **S1** deep drawdown / reclaim (e.g. SPCX basis from cost_basis domain)

**Telegram notify** (dedicated `@tradeai_cio_bot` only)
```bash
# in ~/.config/tradeai/cio-telegram.env
CIO_SITUATION_NOTIFY=1
# requires TELEGRAM_CIO_BOT_TOKEN (SM render) + TELEGRAM_CIO_CHAT_IDS allowlist
```
Policy: `config/cio_llm_policy.yaml` `notify_situation_types` (S1/S2/S5/S6/S8).

**Wake traces:** `situation.raised` rows in `data/cio/cio_wake_traces.jsonl`.
