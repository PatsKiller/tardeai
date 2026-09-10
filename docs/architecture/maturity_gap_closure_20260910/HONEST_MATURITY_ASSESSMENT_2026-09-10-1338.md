Status:      ACTIVE
as_of:       2026-09-10-1338 America/New_York (2026-09-10 13:38:54 EDT(-0400))
utc:         2026-09-10T17:38:54Z
Measured at: live host truth on served release 9c3f4871c-main-exact-phase2-20260910-112135
Canonical repo path: docs/architecture/maturity_gap_closure_20260910/HONEST_MATURITY_ASSESSMENT_2026-09-10-1338.md
Authority:   dated reading — not a behaviour spec; hermetic ≠ OBSERVED
Campaign:    /home/johnclaw/trade-ai-campaigns/maturity-gap-closure-20260909/
MBI_BEHAVIOR: 0
Supersedes:  CIO_*_2026-09-10-0215.md
See also:    paired AS-IS / FUTURE / GAP / HONEST_MATURITY at stamp 2026-09-10-1338

# Honest maturity assessment — 2026-09-10-1338

**Version stamp (America/New_York):** `2026-09-10-1338`
**UTC:** `2026-09-10T17:38:54Z`

Serving SHA: `9c3f4871c7222229d2d5c073d0448e83e5d0261d`
Release: `9c3f4871c-main-exact-phase2-20260910-112135`
Executing dev tree: `1afe3c3d819b9cb08fdc5d8eea05c8f60d4920e5` (== origin/main)

Overall: **CM2_PARTIAL — production reached, provenance is the new ceiling**

The floor moved decisively: the organic engine is no longer "cycle 1 of 3" — it is
36 contiguous schedule-slot wakes with 36 settled receipts, plus judgment and
research objects. The ceiling moved to a new place: the provenance field on every
record is `source_sha = "unknown"`, and the served release lags main by 7 commits.

## Per-capability table

| Capability | Icon | Level | Change since 2026-09-10-0215 |
|---|---|---|---|
| Wave 0 / charter | █ | OBSERVED_LIVE (sealed) | — |
| DB barrier | ◈ | INTEGRATED / DEPLOYED | — |
| Poller identity | █ | OBSERVED_LIVE | — |
| Identity chain (git pins) | ▓ | PARTIAL | **REGRESSED** — served 7 behind main |
| **Evidence provenance** | ✗ | ABSENT | **NEW FINDING** — `source_sha = "unknown"` on all records |
| Persistent wake state root | █ | OBSERVED_LIVE | **volume: 3 → 36 wakes** |
| **Commitments** | █ | OBSERVED_LIVE | 3 → 42; FROZEN state now exercised |
| **Research → wake edge** | █ | OBSERVED_LIVE | **was ░ UNWIRED** — 15 objects, 11 research wakes |
| **Judgment (AgentView@v1)** | █ | OBSERVED_LIVE | **was ◌ HERMETIC_ONLY** — 9 organic views |
| Cred / provenance | ▓ | PARTIAL | the `source_sha` defect lives here |
| D-live outbound / inbound | ◇ | DOCKED | — |
| Event settlement schema | ◈ | INTEGRATED | carried forward; DB read now secret-guarded |
| Retention/curation | ▒ | DOCUMENTATION_ONLY | — |
| Scoring | ◌ | HERMETIC_ONLY | blocked behind SHA + outcomes |
| Self-repair | ▓ | PARTIAL | — |
| Rich docs package | ▓ | PARTIAL | on disk + email; not in git, not on Drive |
| Drive 13/13 | ⛔ | BLOCKED | connector path open |

## Why "Judgment" moved off HERMETIC_ONLY

Not because a test passed. Because `agent_views.jsonl` holds 9 `AgentView@v1`
records produced on the scheduled wake (15:00Z and 17:00Z), each with citations
and `critic_pass = true`. That is producer + store + organic trigger — the
observation bar. The only unmet clause is the SHA: `source_sha = "unknown"`.

## Why "Research → wake" moved off UNWIRED

`research_objects.jsonl` holds 15 governed objects with producer
`governed_research_producer` and policy `governed_brave_router` +
`budget_governed`; producer health reports `outcome = produced`; and 11 of 36
wakes now select on `unconsumed_research`. The 0215 blocker ("producer merged,
never scheduled") is gone.

## What this wave actually observed

- 36 wakes, all `schedule_slot`, `SETTLED`
- 36 receipts, all `SETTLED`, `AgentConsumptionReceipt@v2`
- 42 commitments (36 OPEN + 6 FROZEN), `CommitmentRecord@v2`
- 9 `AgentView@v1` records, organic, cited, critic-passed
- 15 research objects, producer health `produced`, `llm: null` (free-first)
- Health endpoint `ok: true`; disk 82% used, 82G free

## Blockers remaining

1. **`source_sha = "unknown"` on every record** — the provenance field is never
   stamped. This is the new top blocker: it is the only clause separating
   "produced organically" from "proven on the serving SHA".
2. **Served release 7 behind main** — promote `1afe3c3d8` to CURRENT
   (`release-write`).
3. **Commitment outcomes** — 6 `FROZEN` are holds, not verdicts; no
   `refuted`/`expired` has been exercised.
4. **Scoring** — still hermetic; no settled-outcome calibration set.
5. **Rich docs not in git / Drive** — this set is on disk and email only.

## The honesty clause, unchanged

`effect_kind='none'` is legal but is never consumption evidence. Hermetic ≠
OBSERVED. Exit code 0 is not evidence of work. A `source_sha` of `"unknown"`
means a record's producer cannot be proven, regardless of how organic its trigger
was. Nothing in this document is derived from a manual, replay, backfill, fixture
or controlled-canary trigger.
