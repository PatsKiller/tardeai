TRIPWIRE
# Tripwire — retired S2 Home SWR containment (2026-11-14)

Status: ACTIVE
as_of: 2026-11-14
Schema: ArchiveTripwire@v1

Anything that **imports, runs, or reads these archived paths as authority** is a finding: the S2 read-model
release (`S2_READ_MODEL_20261114`) replaced request-thread stale-while-revalidate with a durable
`HomeDoNowSnapshot@v1` / `OverviewProjection@v1` read. The retired test pins the removed refresh function and
is 9 passed without the read-model patch, 1 failed / 8 errors with it — keeping it registered turns the gate red.

Archived under: `archive/s2_home_swr_r6_retired_20261114/`
Superseded by: the `S2_READ_MODEL_20261114` gate (`tests/test_s2_home_do_now_snapshot_20261114.py`,
`tests/test_s2_overview_never_inline_20261114.py`) together with
`PATCH-S2-read-model-r4-52ab48c26-cc-deepseek-9.patch`.
Reason: git history and this archive keep the bytes; rule 6 forbids deletion.

Fires when: production code, a gate, crontab, systemd or n8n references
`archive/s2_home_swr_r6_retired_20261114/` as a live input, or a gate file names the archived test.

Restore (operator only): see the ARCHIVE_MANIFEST.json entries for this batch (two `git mv` commands, one per file).
