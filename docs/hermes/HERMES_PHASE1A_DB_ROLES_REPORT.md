# Hermes Phase 1A DB Roles Report — Trade AI v12

**Date:** 2026-05-30
**Status:** COMPLETE — roles created, grants applied, verified

---

## 1. Summary

Roles and grants applied successfully. Operator ran migration via `sudo -u postgres psql -d trade_ai` on 2026-05-30.

Two NOLOGIN group roles created with least-privilege grants on hermes_* tables only. Zero production table grants. Zero data inserts.

---

## 2. Discovery Results

| Check | Result |
|-------|--------|
| Current DB user | `trade_ai` |
| `rolcreaterole` | FALSE |
| `rolsuper` | FALSE |
| `sudo -n -u postgres psql` | FAILED (password required) |
| Peer auth (`psql -U postgres -h /var/run/postgresql`) | FAILED |
| Postgres password in .env | NOT FOUND |
| Postgres entry in .pgpass | NOT FOUND |
| johnclaw in postgres group | NO |

---

## 3. Backup Verified

| Item | Value |
|------|-------|
| Backup path | `/home/johnclaw/backups/trade_ai_pre_hermes_phase1_20260530_094558.sql.gz` |
| Exists | YES |

---

## 4. hermes_* Tables Verified

| Table | Exists | Rows |
|-------|--------|------|
| hermes_research_intelligence | YES | 0 |
| hermes_validation_findings | YES | 0 |
| hermes_alerts | YES | 0 |
| hermes_embedding_queue | YES | 0 |
| hermes_memory_events | YES | 0 |
| hermes_promotion_audit | YES | 0 |

---

## 5. Migration Files Ready

| File | Path | Status |
|------|------|--------|
| Role/grant migration | `sql/migrations/20260530_hermes_phase1a_roles_and_grants.sql` | READY — not applied |
| Rollback | `docs/hermes/HERMES_PHASE1A_DB_ROLES_ROLLBACK.sql` | READY |

---

## 6. Verification Results (post-apply)

### Roles

| Role | Login | CreateRole | Superuser |
|------|-------|------------|-----------|
| hermes_readonly | NO | NO | NO |
| hermes_staging_writer | NO | NO | NO |

### Grants (22 total, all on hermes_* tables)

**hermes_readonly (6 grants):** SELECT on all 6 hermes_* tables.

**hermes_staging_writer (16 grants):**
- SELECT, INSERT, UPDATE on 5 tables (research_intelligence, validation_findings, alerts, embedding_queue, memory_events)
- SELECT only on hermes_promotion_audit
- USAGE, SELECT on 5 hermes_* sequences (for BIGSERIAL INSERT)

### Production Table Grants

```
(0 rows) — CONFIRMED: zero production table grants
```

### Row Counts

All 6 hermes_* tables: **0 rows** — CONFIRMED

---

## 9. Safety Confirmation

| Item | Status |
|------|--------|
| Production table writes | **ZERO** |
| Production table grants | **ZERO** |
| Data inserts | **ZERO** |
| Login users created | **ZERO** |
| Passwords set | **ZERO** |
| .env changes | **ZERO** |
| Broker access | **ZERO** |
| Proposal mutations | **ZERO** |
| paper_trades mutations | **ZERO** |
| Journal mutations | **ZERO** |
| Cron changes | **ZERO** |
| Systemd changes | **ZERO** |
| Hermes daemon started | **NO** |

---

## 10. Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Operator forgets to run the migration | LOW | This report documents exact command |
| Wrong database targeted | LOW | Migration specifies `-d trade_ai` |

---

## 11. Rollback

```bash
# Requires postgres superuser
sudo -u postgres psql -d trade_ai -f docs/hermes/HERMES_PHASE1A_DB_ROLES_ROLLBACK.sql
```

---

## 12. Next Approval Gate

After roles are created:
- Operator approval for Hermes runtime DB writes (Phase 1 active use)
- Operator approval for production read grants (separate phase)
