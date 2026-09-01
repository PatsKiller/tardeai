# Overnight G4 — Archive mechanism

**Wave:** Overnight G4  
**Date:** 2026-08-31  
**Authority:** READ_ONLY_ADVISORY · no deploy · archive nothing  
**Branch:** `fix/overnight-g4-archive-mechanism`  
**Rails:** AGENTS.md §0.6 (Never delete — archive with a tripwire)  
**Source proposal:** Census Part 4 archive proposal (2026-08-30)

## Finding

AGENTS.md §0.6 requires: never delete; archive with a tripwire that fires if
anything reads the archived path. Census Part 4 sketched the mechanism
(`archive/` + `ARCHIVE_MANIFEST.json` + tripwire + weekly report) and
explicitly did **not** execute it. The mechanism itself was still missing on
`origin/main`, so there was nowhere honest to put an operator-approved batch
and no tripwire to catch a live import of archived material.

## Change this tranche

| File | Change |
|------|--------|
| `scripts/cio_archive_mechanism.py` | Mechanism: schema, validate, tripwire, report CLI |
| `archive/ARCHIVE_MANIFEST.json` | Empty `ArchiveManifest@v1` (items: []) |
| `archive/.gitkeep` | Keep empty archive tree in git |
| `tests/test_overnight_g4_archive_mechanism.py` | Schema + empty-tree quiet + tripwire raises on import/read |
| `scripts/run_cio_hardening_ci.py` | Allowlist this overnight suite |
| `.gitignore` | Stop blanket-ignoring `archive/` so the mechanism can be tracked |

**Archived paths moved this tranche:** **none.** First batch is operator-only.

Note: a prior blanket `archive/` gitignore made `git mv` into `archive/`
untrackable — incompatible with §0.6. Local dumps stay in `backups/` /
`file_backups/`.

## Manifest schema (`ArchiveManifest@v1`)

Location: `archive/ARCHIVE_MANIFEST.json`

Per-item required fields:

| Field | Meaning |
|-------|---------|
| `path` | Repo-relative path under `archive/` (git history preserved) |
| `verdict` | `DARK` \| `ONE_SHOT` \| `ORPHANED` \| `ORPHANED_ROUTE` \| `SUPERSEDED` |
| `evidence` | Why archived; cite census/`as_of`; never invent a reason |
| `date` | Archive date `YYYY-MM-DD` |
| `review_by` | Revisit date (default `date + 30d`) |
| `restore_command` | Exact restore — prefer `git mv <archived> <original>` |

Optional: `original_path`, `batch`.

## Tripwire

`assert_no_archived_reads()` scans the live tree (not `archive/` itself) for
imports and path-literal reads of **effective archived paths** (manifest items
∪ non-scaffolding files under `archive/`).

On a hit it raises `ArchivedPathAccessFinding` — never swallowed — so a read of
archived material cannot look like success.

With the empty manifest shipped here, the tripwire is quiet by construction.

## Invariants

- Build mechanism; **archive nothing** without operator approval.
- Never delete; restore is `git mv` back (history preserved).
- Cadence unknown / single observation → do not archive (Part 4 R2/R3).
- Cron / systemd archive annotations remain operator-only.

## Proof commands

```bash
python3 scripts/cio_archive_mechanism.py schema
python3 scripts/cio_archive_mechanism.py validate
python3 scripts/cio_archive_mechanism.py tripwire
python3 scripts/cio_archive_mechanism.py report
python3 -m pytest -q tests/test_overnight_g4_archive_mechanism.py
python3 scripts/run_cio_hardening_ci.py
python3 scripts/check_test_coverage.py --fail-on-new
python3 scripts/check_dark_contracts.py --fail-on-new
```

## Deploy

None. Push + merge only. No files moved into `archive/` beyond scaffolding.
