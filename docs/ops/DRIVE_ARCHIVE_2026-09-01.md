Status:      ACTIVE
as_of:       2026-09-01T12:05:00-04:00
Measured at: Drive read-back after every move; gog v0.12.0, account john@jwwhiting.com
Canonical repo path: docs/ops/DRIVE_ARCHIVE_2026-09-01.md
Authority:   record of a Drive archive MOVE; not a deletion record
See also:    docs/ops/CIO_AFTERNOON_FIVE_2026-09-01.md
             docs/ops/CIO_OVERNIGHT_CLOSEOUT_2026-09-01.md

# Drive archive — 2026-09-01

**MOVED, never trashed, never deleted.** `gog drive move` relocates; no `delete`, no `--force`,
no `--permanent` was issued at any point. Verified by reading **both** folders back afterwards.

Destination: **`ARCHIVE_2026-09-01`** —
<https://drive.google.com/drive/folders/1-OlLyAZ49HL8qOYGHVBYDuPQ4T8E2g79>

## Moved — 4

| modified | title | id |
|---|---|---|
| 2026-09-01 04:08 | `SUPERSEDED-0406Z_CIO_OVERNIGHT_STITCH_2026-09-01.md` | `1iEXO_Hpx7FY…` |
| 2026-09-01 03:06 | `CIO_ASIS_VS_SPEC_2026-08-30.md` (duplicate) | `1qflVko1BlCs…` |
| 2026-09-01 03:06 | `PROJECT_THE_DESK_V2.md` (duplicate) | `1r2uQU8a0BF8…` |
| 2026-09-01 03:06 | `CIO_FUTURE_STATE_FULL_MATURITY.md` (duplicate) | `1Ob_-BlTMEOA…` |

The three 03:06 copies are the earlier upload of the same three architecture documents; the 03:55
copies were kept live, as instructed.

## Kept live — 11

`CIO_OVERNIGHT_STITCH` · `CIO_OVERNIGHT_CLOSEOUT` · `WAVE_OVERNIGHT` ·
`CIO_ASIS_VS_SPEC_2026-08-30` · `CIO_FUTURE_STATE_FULL_MATURITY` · `PROJECT_THE_DESK_V2` ·
`CIO_SURFACE_ASOF` · `CIO_DARK_CONTRACTS` · `CIO_OUTCOME_DRY` · `CIO_OUTCOME_EDGE_CENSUS` ·
`CIO_M5_TIMER_WATCH`

`[VERIFIED]` read-back of `gog drive ls --parent 1Ur6VXRgl2HfVwbDTqdGlkPnLS_Q_85nc`: 11 files,
the 03:06 duplicates absent, the 03:55 keepers present.

## Not found — 10 of the 14 requested titles

```
CHECKPOINT_W1_2026-09-01          W6_STRUCTURE_PROOFS_2026-09-01
CHECKPOINT_W2_2026-09-01          NIGHT_THREE_REPORT_2026-09-01
W3_3A_POPULATION_2026-09-01       A4_2B_UNKNOWN_RETIREMENTS_2026-09-01
W3_3B_FROZEN_FIELDS_2026-09-01    RUN_LEDGER_2026-09-01
W3_3C_PROVENANCE_2026-09-01       GROK_RUN_REPORT_2026-09-01
W5_SEARCH_COST_PROOFS_2026-09-01
```

**These are an absence, not a failed query.** `gog drive search` was confirmed working against other
terms in the same session (it returned 11 hits for `2026-09-01` and located the 03:06 duplicates by
name). Each of the above returned `No results`.

They are most likely a peer session's local artifacts that never synced. **This document does not
claim they were archived, and it does not claim they do not exist anywhere** — only that they are
not on this Drive account, measured at the timestamp above.

## AGENTS.md

No `AGENTS.md` exists on Drive, so the instruction to mark a Drive copy `SUPERSEDED BY` the repo
copy had no target. Nothing was written. The repo copy is the only one.

## Tripwire

The four moved ids are recorded above. Anything still citing the old parent will resolve to the
`ARCHIVE_2026-09-01` folder rather than 404 — a move preserves the file id, so **existing links keep
working** and point at the archived location. If a consumer is found depending on those titles being
in the live folder, that is a finding for the next wave, and this table is the evidence needed to
restore them.

## Also observed, not caused by this step

`HOLDINGS_STATE_RECONCILIATION_2026-09-01.md` and `INDEX.md` appeared on Drive at 14:05 UTC. That is
the hourly `5 * * * *` docs sync picking them up now that they are on `main` — the normal pipeline,
not an upload from this session.
