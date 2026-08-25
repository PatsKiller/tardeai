# R15.2 — Institutional intelligence live closeout

**Date:** 2026-08-25  
**Authority:** READ_ONLY_ADVISORY · `MEMORY_BEHAVIOR_INFLUENCE=0`  
**Canary:** unset · **Cash policy:** `POLICY_GAP` / unconfirmed  
**R16:** not started

## What changed in the live pin

| | SHA |
|---|---|
| Start CURRENT | `b1295931` (PR #508, overlay stdout-only) |
| origin/main | `d72ecdd1` (PR #509 merge) |
| End CURRENT | `d72ecdd13d4fad1e7551597634f326aeb6a03353` |
| pin_match | true |

Exact-main prepare/promote of #509 succeeded. Rollback remains  
`bash scripts/cio_phase2_exact_main_deploy.sh rollback` → `b1295931-main-exact-phase2-20260825-113136`.

## Natural proof on the same pin (`d72ecdd1`)

**Material scan** (`tradeai-cio-material-scan.timer`, not `systemctl start`):

- 16:07:28Z first post-promote fire: durable `intelligence_fabric` present, `paid_dispatch=0`, `llm_calls=0`, `NOTIFICATION_SUPPRESSED`
- 16:17:36Z and 16:27:37Z subsequent fires still carry the overlay (the 16:17 watcher raced the rewrite by milliseconds; disk after process exit has the overlay)
- Fresh-process read of `cio_material_scan_last.json` reconstructs overlay without rerunning the scan
- Journal compact fields `{observations, paid_dispatch, llm_calls}` match disk

**Free-first** (`tradeai-free-first-circulation.timer`, LastTrigger 12:24:16 EDT):

- `as_of=2026-08-25T16:28:08Z` on `d72ecdd1`
- 120 names: Hermes 117, RAG 2, structured 1, SearXNG 0 queries
- `fresh_no_change=120`, `paid_dispatch_entered=0`, `LLM_eligible_not_authorized=0`
- Curation store still 120 `BASELINE_PROJECTION` last written 2026-08-24 — no fake MATERIAL versions

No genuine material market event. `BLOCKED_REAL_WORLD_EVENT` for LLM curation lifecycle.

## Independent lanes (not natural)

- Same-brain across Alex/Hermes/Advisory/Telegram/Maria/Steph/Guardian/Ledger/Command Center: `consistent=true`
- Specialist artifacts + `SPECIALIST_UNAVAILABLE` without invented opinions (CURRENT_SMOKE, not live agent ticks)
- ModelTaskPerformance: LIVE=0, HISTORICAL_REPLAY=300, GOLDEN_SHADOW=240, classes not mixed, routing auto-apply blocked, registries byte-identical
- GUI `/api/v3/cio/brain` pin_match, lifecycle + knowledge gaps
- PR #507 remains OPEN docs-only R14A evidence; not merged; not a live blocker
- Tests this run: **1285 passed**, **1 failed** (`test_llm_consumption.py::test_registry_has_processes` expects `holding_protection_advisor.default_mode=manual` vs registry `automated` — pre-existing on main, not an R15 delta)

## Maturity

**80 → 86.** Highest *natural* level **84**. **87 not awarded.**

```yaml
R15_2_INSTITUTIONAL_INTELLIGENCE:
  result: PASS_WITH_HONEST_CEILING
  source:
    main_sha: d72ecdd13d4fad1e7551597634f326aeb6a03353
    current_sha: d72ecdd13d4fad1e7551597634f326aeb6a03353
    current_exact_main: true
    pr508_merged: true
    pr509_merged: true
    pr509_deployed: true
  tests:
    passed: 1285
    failed: 1
    fail_note: pre-existing llm_process_registry default_mode vs test_llm_consumption
  natural:
    material_scan_cycles_on_d72ecdd1: 3
    free_first_cycles_on_d72ecdd1: 1
    durable_overlay_receipts: true
    zero_cost_no_change_cycles: 1
    genuine_material_lifecycles: 0
    manually_started_cycles_counted: 0
  durable_receipt:
    journal_disk_critical_match: true
    restart_readable: true
    source_sha_match: true
    intelligence_overlay_present: true
  maturity:
    before: 80
    after: 86
    limiting_dimension: no genuine material event; live model samples 0; specialist live agent ticks not proven
    highest_natural_evidence_level: 84
```
