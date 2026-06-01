# Phase 41A — Systemd Migration Candidate Selection

**Date:** 2026-06-01
**Status:** COMPLETE — 5 candidates selected

---

## Selected Candidates (Safest 5)

| # | Job | Current Schedule | Writes | Risk |
|---|-----|-----------------|--------|------|
| 1 | governance_system_facts | Mon-Fri 7:40 + Sun 18:00 | governance JSON/MD files | LOW |
| 2 | governance_status | Mon-Fri 7:50 + Sun 18:10 | governance JSON/MD files | LOW |
| 3 | maturity_control_board | Mon-Fri 7:55 + Sun 18:15 | maturity JSON files | LOW |
| 4 | operator_readiness | Mon-Fri 8:00 + Sun 18:20 | readiness JSON/MD files | LOW |
| 5 | iris_taxonomy (daily) | Daily 7:00 + Sun 10:00 | taxonomy DB tables | LOW |

## Why These 5

- All are governance/maturity reporting — not trading/proposal/broker
- All write only to report files or governance metadata tables
- All already use flock (3/5) or are idempotent
- None touch proposals, trades, journal, holdings, or broker
- Consolidates 11 cron lines into 5 systemd timers (each timer replaces 2 cron lines)

## Cron Lines to Disable (11 total)

After timer validation, these exact lines will be commented out in crontab.
