# OPERATOR_DECISION — unscheduled modules (schedule vs delete)

**Campaign:** cio-maturity-nearterm-dry-20260909 live ceiling  
**Decided_at_utc:** 2026-09-09T04:02:00Z  
**Decided_by:** operator execute full ceiling (all C items)  
**Cron grant present:** YES — installed 2026-09-09T12:43:22Z

## Decision

| Module | Decision | Rationale |
|---|---|---|
| `cio_wave3b_report.py --json` | **SCHEDULED** (advisory, no alert) | Hourly `:15` on CURRENT |
| `cio_wave3c_report.py --json` | **SCHEDULED** (advisory) | Hourly `:20` on CURRENT |
| `build_catalyst_graph.py --diagnose-staleness --json` | **SCHEDULED** (diagnose only; **no `--apply`**) | Hourly `:25` on CURRENT |
| `NotificationPolicy@v1` / notification router classes | **KEEP UNSCHEDULED** pending separate design | IMMEDIATE/CC_ONLY never fire |
| `run_integrity_checks.py --json` | **ALREADY SCHEDULED** (do not duplicate) | Existing cron |

## Installed crontab lines (verified)

Evidence: `cron_install_report.20260909T124322Z.json` (`ok=true`, checks wave3b/wave3c/catalyst/marker all true).  
Backup: `crontab.before_advisory_install.20260909T124248Z.txt`

## Claim impact

- `P3_SCHEDULED` → **SCHEDULED_ADVISORY** (three honesty surfaces on CURRENT; not notification router)

