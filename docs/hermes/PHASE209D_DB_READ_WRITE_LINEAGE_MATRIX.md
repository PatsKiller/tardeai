# Phase 209D — Hermes DB Read/Write Lineage (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T12:28:03-04:00
Measured at: efcc51365 / not measured

Script: `scripts/audit_hermes_db_lineage.py` → `data/hermes/hermes_db_lineage_latest.json`.

| Table | Rows | Writes/24h | Code writers | Role |
|-------|------|-----------|--------------|------|
| hermes_research_intelligence | 1975 | 443 | 8 | core staging (source discovery, autonomous, librarian status) |
| hermes_memory_events | 438 | 96 | 1+ | coordinator/coordination logs |
| hermes_promotion_audit | 1975 | — | 1+ | promotion advisory/audit trail |
| hermes_validation_findings | 28 | 0 | 2 | validation findings |
| hermes_embedding_queue | 9 | 0 | 1 | embedding candidates (gated) |
| hermes_alerts | 0 | 0 | 1 | alerts (currently empty) |

- **TradeAI safe views: 13** (`hermes_v_*` / safe views) — read-only inputs (the WALL).
- Active writing (research_intelligence 443/24h, memory_events 96/24h) confirms the fleet is live.
- Hermes tables are staging/advisory only — NO writes to core trading/broker/proposal/holdings tables.
