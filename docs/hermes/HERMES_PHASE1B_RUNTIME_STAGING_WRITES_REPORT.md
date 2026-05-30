# Hermes Phase 1B Runtime Staging Writes Report — Trade AI v12

**Date:** 2026-05-30
**Status:** COMPLETE

---

## 1. Summary

Created `scripts/hermes_staging_ingest.py` — a controlled ingestion script that writes only to hermes_* staging tables. Defaults to `--dry-run`, requires `--apply` for committed writes. Passed all 5 tests including 3 negative validation tests. One smoke row committed to `hermes_memory_events` (id=2).

---

## 2. Preflight

| Check | Result |
|-------|--------|
| Backup exists | YES — `/home/johnclaw/backups/trade_ai_pre_hermes_phase1_20260530_094558.sql.gz` |
| hermes_readonly role | EXISTS, NOLOGIN |
| hermes_staging_writer role | EXISTS, NOLOGIN |
| Production table grants | ZERO |
| hermes_* row counts before | ALL ZERO |
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |

---

## 3. Script Created

| File | Purpose |
|------|---------|
| `scripts/hermes_staging_ingest.py` | Controlled ingestion into hermes_* tables |

### Script Safety Features

| Feature | Implementation |
|---------|---------------|
| Default mode | `--dry-run` (no write) |
| Commit mode | `--apply` required |
| Table allowlist | 5 hermes_* tables only |
| Production table rejection | Any non-hermes_* table rejected |
| Source enforcement | Forces `source='hermes'`, rejects other values |
| Forbidden keywords | Rejects payloads mentioning broker/proposal/trade/journal mutation |
| Required columns | Validates per-table required fields |
| Confidence range | Enforces 0.0–1.0 |

---

## 4. Sample Payload

| File | Path |
|------|------|
| Smoke payload | `docs/hermes/samples/hermes_phase1b_smoke_payload.json` |

---

## 5. Test Results

| # | Test | Input | Expected | Result |
|---|------|-------|----------|--------|
| 1 | Dry-run valid payload | smoke_payload.json | Pass, no write | **PASS** |
| 2 | Invalid source | `source='not_hermes'` | Reject | **PASS** — `REJECTED: source='not_hermes'` |
| 3 | Invalid table | `--table paper_trades` | Reject | **PASS** — `REJECTED: table 'paper_trades' not in allowed list` |
| 4 | Forbidden keyword | `approve_proposal` in content | Reject | **PASS** — `REJECTED: forbidden keyword 'approve_proposal'` |
| 5 | Apply smoke write | smoke_payload.json `--apply` | 1 row committed | **PASS** — id=2 committed |

---

## 6. Smoke Write

| Field | Value |
|-------|-------|
| Table | `hermes_memory_events` |
| Row ID | **2** |
| source | `hermes` |
| hermes_agent_name | `chief_hermes_coordinator` |
| event_type | `agent_state_change` |
| status | `active` |
| topic | `Hermes Phase 1B staging write smoke test` |
| metadata_json.test | `true` |
| metadata_json.phase | `1B` |
| metadata_json.purpose | `smoke_test` |

---

## 7. Post-Write Verification

### hermes_* Row Counts

| Table | Before | After |
|-------|--------|-------|
| hermes_research_intelligence | 0 | 0 |
| hermes_validation_findings | 0 | 0 |
| hermes_alerts | 0 | 0 |
| hermes_embedding_queue | 0 | 0 |
| hermes_memory_events | 0 | **1** |
| hermes_promotion_audit | 0 | 0 |

### Production Tables

| Table | Count | Changed? |
|-------|-------|----------|
| paper_trades | 38 | NO |
| paper_trade_proposals | 145 | NO |

---

## 8. Safety Confirmation

| Item | Status |
|------|--------|
| Production table writes | **ZERO** |
| Production table grants added | **ZERO** |
| Broker access | **ZERO** |
| Proposal mutations | **ZERO** |
| paper_trades mutations | **ZERO** |
| Journal mutations | **ZERO** |
| content_embeddings writes | **ZERO** |
| Embeddings generated | **ZERO** |
| Cron changes | **ZERO** |
| Systemd changes | **ZERO** |
| .env changes | **ZERO** |
| Dashboard code changes | **ZERO** |
| API endpoint changes | **ZERO** |
| Hermes daemon started | **NO** |
| Login roles created | **ZERO** |
| Passwords set | **ZERO** |

---

## 9. Rollback

Remove smoke row:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
PGPASSWORD=$(grep DB_PASSWORD .env | cut -d= -f2) \
  psql -h localhost -U trade_ai -d trade_ai \
  -f docs/hermes/HERMES_PHASE1B_RUNTIME_STAGING_WRITES_ROLLBACK.sql
```

---

## 10. Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Script bypassed by direct SQL | LOW | Hermes doesn't have DB credentials yet |
| Forbidden keyword list incomplete | LOW | Expandable; CHECK constraints also enforce |
| Smoke row left in table | NONE | Clearly marked test=true, phase=1B |

---

## 11. Next Approval Gates

| Gate | Status |
|------|--------|
| Real Hermes research ingestion | NEEDS OPERATOR APPROVAL |
| Production read grants for hermes_readonly | NEEDS OPERATOR APPROVAL |
| Embedding integration | NEEDS OPERATOR APPROVAL |
| Dashboard integration | NEEDS OPERATOR APPROVAL |
| Promotion scripts | NEEDS OPERATOR APPROVAL |
