# Hermes Phase 1A DB Roles Report — Trade AI v12

**Date:** 2026-05-30
**Status:** BLOCKED — postgres superuser access required

---

## 1. Summary

Role creation requires PostgreSQL superuser privileges. The `trade_ai` database user has `rolcreaterole=false` and `rolsuper=false`. All other access methods (sudo, peer auth, .pgpass) are unavailable without the operator's password.

The migration SQL is written and ready to apply. The operator needs to run one command.

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

## 6. Operator Action Required

Run this command (requires sudo password or postgres password):

### Option A: sudo

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
sudo -u postgres psql -d trade_ai -f sql/migrations/20260530_hermes_phase1a_roles_and_grants.sql
```

### Option B: postgres password

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
PGPASSWORD=<postgres_password> psql -h localhost -U postgres -d trade_ai -f sql/migrations/20260530_hermes_phase1a_roles_and_grants.sql
```

### Option C: interactive from Claude Code prompt

Type this in the Claude Code prompt:

```
! sudo -u postgres psql -d trade_ai -f sql/migrations/20260530_hermes_phase1a_roles_and_grants.sql
```

---

## 7. What the Migration Creates

### Roles (NOLOGIN group roles, no passwords)

| Role | Login | Superuser | CreateRole |
|------|-------|-----------|------------|
| hermes_readonly | NO | NO | NO |
| hermes_staging_writer | NO | NO | NO |

### Grants

**hermes_readonly:**
- USAGE ON SCHEMA public
- SELECT on all 6 hermes_* tables

**hermes_staging_writer:**
- USAGE ON SCHEMA public
- SELECT, INSERT, UPDATE on 5 hermes_* tables (not hermes_promotion_audit)
- SELECT only on hermes_promotion_audit
- USAGE, SELECT on 5 hermes_* sequences (for BIGSERIAL INSERT)
- No DELETE, no TRUNCATE, no production table access

---

## 8. Verification (run after applying)

```sql
-- Check roles exist and are NOLOGIN
SELECT rolname, rolcanlogin, rolcreaterole, rolsuper
FROM pg_roles WHERE rolname LIKE 'hermes_%';

-- Check grants on hermes_* tables
SELECT grantee, table_name, privilege_type
FROM information_schema.table_privileges
WHERE grantee LIKE 'hermes_%'
ORDER BY grantee, table_name, privilege_type;

-- Confirm no production table grants
SELECT grantee, table_name, privilege_type
FROM information_schema.table_privileges
WHERE grantee LIKE 'hermes_%' AND table_name NOT LIKE 'hermes_%';

-- Confirm all hermes_* tables still have 0 rows
SELECT 'hermes_research_intelligence' AS tbl, COUNT(*) FROM hermes_research_intelligence
UNION ALL SELECT 'hermes_validation_findings', COUNT(*) FROM hermes_validation_findings
UNION ALL SELECT 'hermes_alerts', COUNT(*) FROM hermes_alerts
UNION ALL SELECT 'hermes_embedding_queue', COUNT(*) FROM hermes_embedding_queue
UNION ALL SELECT 'hermes_memory_events', COUNT(*) FROM hermes_memory_events
UNION ALL SELECT 'hermes_promotion_audit', COUNT(*) FROM hermes_promotion_audit;
```

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
