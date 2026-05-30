# Hermes Phase 1 DB Staging Report — Trade AI v12

**Date:** 2026-05-30
**Status:** COMPLETE (tables created, roles deferred)

---

## 1. Backup

| Item | Value |
|------|-------|
| Backup path | `/home/johnclaw/backups/trade_ai_pre_hermes_phase1_20260530_094558.sql.gz` |
| Backup type | Schema-only pg_dump |
| Backup size | 85KB |
| Created before migration | YES |

**Note on backup schedule:** Existing weekly backup timer (`portfolio-backup.timer`) last ran April 21. The timer and retention policy should be audited separately.

---

## 2. Migration Files

| File | Path |
|------|------|
| Migration | `sql/migrations/20260530_hermes_phase1_staging_tables.sql` |
| Rollback | `sql/migrations/20260530_hermes_phase1_staging_tables_rollback.sql` |
| Rollback copy | `docs/hermes/HERMES_PHASE1_DB_STAGING_ROLLBACK.sql` |

---

## 3. Tables Created

| Table | Rows | Indexes | CHECK Constraints |
|-------|------|---------|-------------------|
| `hermes_research_intelligence` | 0 | 8 | 4 (source='hermes', status, thesis_type, confidence 0-1) |
| `hermes_validation_findings` | 0 | 6 | 4 (source='hermes', finding_type, severity, status) |
| `hermes_alerts` | 0 | 5 | 4 (source='hermes', alert_type, severity, status) |
| `hermes_embedding_queue` | 0 | 2 | 2 (source='hermes', embedding_status) |
| `hermes_memory_events` | 0 | 4 | 3 (source='hermes', event_type, status) |
| `hermes_promotion_audit` | 0 | 3 | 1 (promotion_type) |
| **Total** | **0** | **34** | **18** |

All tables have `CHECK (source = 'hermes')` — no non-Hermes data can be inserted.

---

## 4. Roles

| Role | Status | Reason |
|------|--------|--------|
| `hermes_readonly` | **DEFERRED** | `trade_ai` user lacks CREATEROLE privilege; requires postgres superuser |
| `hermes_staging_writer` | **DEFERRED** | Same — requires postgres superuser |

**Action required:** Operator must run role creation via postgres superuser access. The role SQL is in the migration file, ready to apply when access is available. Tables function correctly without roles — the `trade_ai` user owns them and can read/write.

---

## 5. Grants

Deferred with roles. When roles are created:

- `hermes_staging_writer`: INSERT/UPDATE on hermes_* tables only
- `hermes_readonly`: SELECT on hermes_* tables only
- Neither role gets access to production tables in this phase

---

## 6. Verification Results

```
Tables:        6/6 created ✓
Indexes:       34 created ✓
CHECK constraints: 18 applied ✓
Row counts:    all 0 ✓
Roles:         0/2 (deferred — needs postgres) ⚠
Grants:        deferred with roles ⚠
```

### Production Tables Unchanged

| Table | Row Count | Status |
|-------|-----------|--------|
| `paper_trades` | 38 | UNCHANGED |
| `paper_trade_proposals` | 145 | UNCHANGED |

---

## 7. Safety Confirmation

| Item | Status |
|------|--------|
| Production table writes | **ZERO** |
| Broker access | **ZERO** |
| Proposal mutations | **ZERO** |
| paper_trades mutations | **ZERO** |
| Journal mutations | **ZERO** |
| content_embeddings writes | **ZERO** |
| Embeddings generated | **ZERO** |
| RAG reindex | **ZERO** |
| Cron changes | **ZERO** |
| Systemd changes | **ZERO** |
| .env changes | **ZERO** |
| Dashboard code changes | **ZERO** |
| API endpoint changes | **ZERO** |
| External API keys | **ZERO** |
| Hermes daemon started | **NO** |

---

## 8. Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Roles not created yet | LOW | Tables work under trade_ai ownership; role creation deferred to postgres access |
| Backup schedule gap (last: April 21) | MEDIUM | Fresh schema backup taken pre-migration; weekly timer should be audited |

---

## 9. Rollback Command

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
PGPASSWORD=$(grep DB_PASSWORD .env | cut -d= -f2) \
  psql -h localhost -U trade_ai -d trade_ai \
  -f sql/migrations/20260530_hermes_phase1_staging_tables_rollback.sql
```

---

## 10. Next Approval Gates

| Gate | Description | Status |
|------|-------------|--------|
| Role creation | Create hermes_readonly + hermes_staging_writer via postgres superuser | NEEDS POSTGRES ACCESS |
| Hermes runtime DB writes | Allow Hermes agent to write to hermes_* tables | NEEDS OPERATOR APPROVAL |
| Production read grants | Grant SELECT on approved production tables to hermes_readonly | NEEDS OPERATOR APPROVAL |
| Dashboard integration | Show hermes_alerts in Command Center | NEEDS OPERATOR APPROVAL |
| Embedding integration | Hermes → hermes_embedding_queue → content_embeddings | NEEDS OPERATOR APPROVAL |
| Promotion scripts | hermes_* → production tables via reviewed promotion | NEEDS OPERATOR APPROVAL |
