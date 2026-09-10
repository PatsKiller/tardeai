Status:      ACTIVE
as_of:       2026-09-09-1401 America/New_York (2026-09-09 14:01:48 UTC-04:00)
utc:         2026-09-09T18:01:48Z
Measured at: maturity-gap-closure-20260909 campaign evidence (PR #932 promote + D-live + inbound strict check)
Canonical campaign path: docs/HONEST_MATURITY_ASSESSMENT_2026-09-09-1401.md
Authority:   dated reading — not a behaviour spec; hermetic ≠ OBSERVED
Campaign:    /home/johnclaw/trade-ai-campaigns/maturity-gap-closure-20260909/
MBI_BEHAVIOR: 0
Supersedes:  thin package CIO_*_2026-09-09-1352.md and body-only emails
See also:    paired AS-IS / FUTURE / GAP / HONEST_MATURITY at stamp 2026-09-09-1401
             gold structural templates: CIO_ASIS_VS_SPEC_2026-09-09.md,
             CIO_FUTURE_STATE_FULL_MATURITY.md, CIO_ASIS_VS_FUTURE_GAP_2026-09-09.md

# Honest maturity assessment — 2026-09-09-1401

**Version stamp (America/New_York):** `2026-09-09-1401` (`2026-09-09 14:01:48 UTC-04:00`)  
**UTC:** `2026-09-09T18:01:48Z`


```
LEGEND (status icons — use consistently across AS-IS / FUTURE / GAP)
  █  OBSERVED_LIVE     scheduled or live path; durable output verified on CURRENT epoch
  ◈  INTEGRATED        wired end-to-end on serving SHA (producer→store→consumer)
  ◇  DOCKED            code + schema on CURRENT; consumer or organic proof incomplete
  ▓  PARTIAL           runs, but incomplete / degraded / consumer unproven
  ░  UNWIRED           code exists and is correct; nothing calls it or consumes it
  ◌  HERMETIC_ONLY     tests/helpers PASS; must NOT be quoted as OBSERVED
  ▒  DOCUMENTATION_ONLY docs/helpers without producer+consumer+organic evidence bar
  ✗  ABSENT / DARK     never executed, no producer, or produces nothing in recorded history
  ⛔ BLOCKED           structural/policy blocker (grant scope, secret, stuck checkpoint, etc.)
  M5_CANDIDATE         scheduled + unattended proven; durability OBSERVED clause still open
```


Serving SHA: `e651b2d771a9cf5136ca6c4b56923672cfb91f95`  
Release: `e651b2d77-main-exact-phase2-20260909-131901`  
Overall: **CM2_PARTIAL_FLOOR** — outbound █; inbound ⛔; Drive ⛔; cortex ◌

## Per-capability table

| Capability | Icon | Level |
|---|---|---|
| Wave 0 / charter | █ | OBSERVED_LIVE (sealed) |
| DB barrier | ◈ | INTEGRATED / DEPLOYED |
| Poller identity | █ | OBSERVED_LIVE |
| Cred / provenance | ◇ | DOCKED |
| D-dry | ◌ | HERMETIC_ONLY |
| D-live outbound | █ | OBSERVED_LIVE |
| D-live inbound | ⛔/✗ | BLOCKED / ABSENT |
| Research router | ◈ | INTEGRATED |
| Retention/curation | ▒ | DOCUMENTATION_ONLY |
| Judgment | ◌ | HERMETIC_ONLY |
| Commitments | ◌ | HERMETIC_ONLY |
| Scoring | ◌ | HERMETIC_ONLY |
| Self-repair | ▓ | PARTIAL |
| Rich docs package | █ | OBSERVED_LIVE (this stamp) |
| Drive 13/13 | ⛔/✗ | BLOCKED / ABSENT |

## What this wave tested

- Pytest: barrier, poller identity, D-dry, F–J hermetic helpers
- Deploy health + `/v3/cio` at promote
- D-live outbound SETTLED evidence
- Strict inbound adjudication: **falsified** (0 INBOUND / 0 receipts after outbound; checkpoint stuck)

## Blockers remaining

1. Inbound checkpoint repair + organic OK consumption proof
2. Drive Kersta 13/13 via policy-legal path
