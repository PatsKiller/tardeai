# Phase 36C — Scheduled Job Consolidation Design

**Date:** 2026-06-01
**Status:** COMPLETE — design only

---

## Target Categories

### 1. Keep as Cron (Temporarily)

| Criteria | Examples |
|----------|---------|
| Simple one-shot jobs | Drive sync, Telegram polling |
| Working reliably | Most pipeline jobs |
| No resource contention | Lightweight reads |
| Count | ~140 jobs |
| Migration risk | LOW |
| Rollback | Restore crontab line |

### 2. Migrate to Systemd Timer

| Criteria | Examples |
|----------|---------|
| Durable recurring with restart needs | Quote refresh, news ingestion |
| Need journal logging | Agent intelligence |
| Need kill switch | Research-adjacent jobs |
| Count | ~15 jobs |
| Migration risk | LOW |
| Rollback | Disable timer, re-enable cron |
| Health | systemctl status, journal |
| Lock | Built-in (Type=oneshot prevents overlap) |

### 3. Merge into Pipeline Controller

| Criteria | Examples |
|----------|---------|
| Multiple related jobs running sequentially | Screener (13 jobs → 1 pipeline) |
| Agent dispatch chain | Router + intelligence + research (9 → 1) |
| Quote refresh chain | 11 invocations → 1 smart refresher |
| Count | ~30 jobs → ~3 pipelines |
| Migration risk | MEDIUM |
| Rollback | Disable pipeline, re-enable individual crons |

### 4. Convert to Event-Driven Queue

| Criteria | Examples |
|----------|---------|
| Low-latency requirement | Catalyst ingestion on news arrival |
| Triggered by external event | Research backlog item creation |
| Count | ~5 candidate workflows |
| Migration risk | HIGH |
| Rollback | Fall back to polling cron |

### 5. Retire After Validation

| Criteria | Examples |
|----------|---------|
| Duplicate of another job | Overlapping screener runs |
| Superseded by newer pipeline | Legacy scans |
| No longer needed | TBD after validation |
| Count | ~5–10 estimated |
| Migration risk | LOW |
| Rollback | Re-add crontab line |

### 6. Needs Owner Review

| Criteria | Examples |
|----------|---------|
| Unclear purpose | Jobs with no comments |
| Unknown write targets | Undocumented scripts |
| Count | ~5 estimated |
