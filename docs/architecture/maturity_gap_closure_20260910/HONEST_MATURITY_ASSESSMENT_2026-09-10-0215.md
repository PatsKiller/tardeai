Status:      ACTIVE
as_of:       2026-09-10-0215 America/New_York (2026-09-10 02:15:05 EDT(-0400))
utc:         2026-09-10T06:15:05Z
Measured at: live host truth on served release 2de99cd89-main-exact-phase2-20260910-012515
Canonical campaign path: docs/architecture/maturity_gap_closure_20260910/HONEST_MATURITY_ASSESSMENT_2026-09-10-0215.md
Authority:   dated reading — not a behaviour spec; hermetic ≠ OBSERVED
Campaign:    /home/johnclaw/trade-ai-campaigns/maturity-gap-closure-20260909/
MBI_BEHAVIOR: 0
Supersedes:  CIO_*_2026-09-10-0114.md (emailed 01:16 ET) and CIO_*_2026-09-09-1401.md
See also:    paired AS-IS / FUTURE / GAP / HONEST_MATURITY at stamp 2026-09-10-0215

# Honest maturity assessment — 2026-09-10-0215

**Version stamp (America/New_York):** `2026-09-10-0215`
**UTC:** `2026-09-10T06:15:05Z`

Serving SHA: `2de99cd8965ee5ae503d9f278e997fe5902d5792`
Release: `2de99cd89-main-exact-phase2-20260910-012515`
Executing dev tree: `2de99cd8965ee5ae503d9f278e997fe5902d5792` (**reconciled this wave**)

Overall: **CM2_PARTIAL — floor raised, ceiling unchanged**

The floor moved for a specific reason: evidence that used to be destroyed on every
promote now survives one. The ceiling did not move, because the three-cycle organic
bar takes three hours of wall-clock and cycle 1 landed at 06:00Z.

## Per-capability table

| Capability | Icon | Level | Change since 2026-09-09-1401 |
|---|---|---|---|
| Wave 0 / charter | █ | OBSERVED_LIVE (sealed) | — |
| DB barrier | ◈ | INTEGRATED / DEPLOYED | — |
| Poller identity | █ | OBSERVED_LIVE | — |
| **Identity chain incl. executing tree** | █ | OBSERVED_LIVE | **NEW — dev tree was 66 behind** |
| **Persistent wake state root** | █ | OBSERVED_LIVE | **NEW — fork closed, shared root live** |
| **Commitments** | █ | OBSERVED_LIVE | **was ◌ HERMETIC_ONLY** |
| Cred / provenance | ◇ | DOCKED | — |
| D-live outbound | █ | OBSERVED_LIVE | — |
| D-live inbound | ◇ | DOCKED | was ⛔ — checkpoint repaired |
| **Event settlement schema** | ◈ | INTEGRATED | **was ⛔ — migration applied** |
| Research router | ◈ | INTEGRATED | — |
| **Research → wake edge** | ░ | UNWIRED | producer merged, **0 cron refs, flag OFF** |
| Retention/curation | ▒ | DOCUMENTATION_ONLY | — |
| Judgment | ◌ | HERMETIC_ONLY | — |
| Scoring | ◌ | HERMETIC_ONLY | — |
| Self-repair | ▓ | PARTIAL | — |
| Rich docs package | ▓ | PARTIAL | on disk + email; **not in git, not on Drive** |
| Drive 13/13 | ⛔ | BLOCKED | `gog` scope ungrantable; connector path open |

## Why "Commitments" moved off HERMETIC_ONLY

Not because a test passed. Because the 06:00Z scheduled wake wrote three durable
`CommitmentRecord@v2` rows to a root that survives a promote, each parented to an
organic `schedule_slot` wake and paired with a `SETTLED` consumption receipt. That
is producer + store + consumer + organic trigger — the whole bar, observed.

## What this wave actually tested

- Live resolver on the served release: resolves to the shared root, verified read-only
- The 06:00Z wake firing under the new code and creating that root
- `information_schema` / `pg_constraint` / `pg_indexes` before-image of the settlement migration
- 48 tests green: SOP evidence integrity, producer, producer runner, state-root stability, release manifest
- `check_test_coverage.py --fail-on-new` → 0 new unlisted
- Dev-tree reconciliation with protected-file hash equality proven either side

## Blockers remaining

1. **Research producer never scheduled** — needs a native `cron` grant (requested,
   `abc31b5a63940bdc`). Until then every wake selects `material_change`.
2. **Drive Kersta 13/13** — `gog` drive scope ungrantable. A sanctioned connector
   path is now confirmed reachable and is the recommended route.
3. **Rich docs not in git** — the `*-1401` set sat untracked in the dev tree, which
   is exactly why GitHub and Drive both read 0. Addressed this wave.
4. **Cortex judgment / scoring** — still hermetic; no serving-SHA producer.
5. **6 stranded organic wakes** — operator decision, not an engineering fix.

## The honesty clause, unchanged

`effect_kind='none'` is legal but is never consumption evidence. Hermetic ≠ OBSERVED.
Exit code 0 is not evidence of work. Nothing in this document is derived from a
manual, replay, backfill, fixture or controlled-canary trigger.
