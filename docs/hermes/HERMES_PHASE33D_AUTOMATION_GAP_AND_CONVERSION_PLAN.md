# Hermes Phase 33D — Automation Gap and Conversion Plan

**Date:** 2026-06-01
**Status:** COMPLETE — design only

---

## Current Automation vs Gaps

| Workflow | Automated? | Gap? |
|----------|-----------|------|
| Ticker thesis challenger | YES (daily timer) | NO |
| Hermes gateway | YES (systemd service) | NO |
| SearXNG container | YES (Docker Compose) | Health check missing |
| Librarian dry-run | MANUAL | YES — should be schedulable |
| Research Backlog health | MANUAL | YES — should be daily |
| Source discovery | MANUAL | YES — should be schedulable dry-run |
| Embedding review | MANUAL | YES — should be weekly |
| Promotion review | MANUAL | YES — should be weekly |
| Observation audit | MANUAL | YES — should be daily |
| SearXNG health check | MISSING | YES |
| Hermes timer health check | PARTIAL (dashboard) | Dashboard only |

## Workflows That Should Remain Manual

| Workflow | Reason |
|----------|--------|
| Embedding apply (--apply) | Must be operator-approved |
| Promotion apply | Must be operator-approved |
| SearXNG manual queries | Operator-directed research |
| Income-rotation research | Operator-directed, one-time |
| Safe view creation | Schema change, requires review |
| Model routing changes | Safety-critical |
| .env changes | Safety-critical |

## Cron to Systemd Migration Candidates

| Job | Current | Recommended | Priority |
|-----|---------|-------------|----------|
| Telegram command handler | cron (2 min) | systemd service | MEDIUM |
| Drive doc sync | cron (hourly :05) | Keep cron | LOW |
| Others (185) | cron | Keep cron (not Hermes) | LOW |

## Docker Health Monitoring Needed

| Service | Check | Current | Gap |
|---------|-------|---------|-----|
| SearXNG | HTTP 200 on :18888 | None | Add to System Applications health |
| Future containers | TBD | None | Design when needed |

## SearXNG: Stay Docker-Only?

**YES** — SearXNG is correctly containerized. Benefits: isolated, portable, easy rollback (`docker compose down -v`). No reason to change.

## Hermes: Stay Systemd?

**YES** — Hermes gateway and autonomous loop are correctly using systemd user services/timers. Benefits: kill switch, journal logging, restart policy, lingering, dashboard status.

## Missing Dashboard Health Checks

| Item | Gap |
|------|-----|
| SearXNG container status | Already in System Applications (Phase 16D) |
| Hermes timer last-run result | Partial — kill switch and loop status shown |
| Research Backlog staleness | NOT SHOWN — add age indicator |
| Embedding queue depth | NOT SHOWN |

## Missing Alerts

| Alert | Gap |
|-------|-----|
| SearXNG down | No alert |
| Hermes timer failed | No alert (timer logs only) |
| Research Backlog >7 days stale | No alert |
| Embedding queue stuck | No alert |

## Daily Operator Review Requirements

1. Hermes autonomous loop result (journalctl)
2. SearXNG container status (docker ps)
3. Research Backlog dashboard (new items?)
4. Hermes Intelligence page (new staged/promoted?)

---

## Recommended Candidate Automations (Future Phases)

| Automation | Type | Write? | Cap | Phase |
|-----------|------|--------|-----|-------|
| Daily observation audit | systemd timer | NO (read-only) | N/A | 34 |
| Daily Research Backlog health | systemd timer | NO (file output) | N/A | 35 |
| Daily expanded Librarian dry-run | systemd timer | NO (file output) | 25 findings | 36 |
| Daily source-discovery dry-run | systemd timer | NO (file output) | 5 queries | 37 |
| Weekly embedding candidate review | systemd timer | NO (file output) | 2 recs | 39 |
| Weekly promotion review | systemd timer | NO (file output) | all staged | 39 |
| SearXNG health check | systemd timer | NO (alert only) | N/A | 34 |

**None enabled in Phase 33.**
