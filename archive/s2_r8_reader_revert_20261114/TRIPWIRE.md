# Tripwire — R7 stored-only reader, reverted in R8 (2026-11-14)

Status: ACTIVE
as_of: 2026-11-14
Schema: ArchiveTripwire@v1

Nothing may **import, run, or read these archived paths as authority**. They pin or implement the stored-only
reader that R7 shipped for `/api/v2/overview` and `/api/v2/home/do-now` (ACC-CACHE r4, 0eb740a8b + 979ffb34f).
That reader never computed: outside its last-good window it answered a named UNKNOWN with every number null.
The overview-projection lane runs weekdays only, so on Saturday 2026-11-14 the header went blank
(INC-OVW-20261114; the projection on disk was 63,686 s old). The do-now snapshot had no registered producer at
all, so R7's do-now read was UNKNOWN on every request.

LEAD-RULING-R8-base-after-R7-rollback-20261114T1951Z: R8 reverts the reader behaviour to R6's inline fallback
and keeps only reader-independent producer guards (the overview build never moves the projection backwards).

Archived under: `archive/s2_r8_reader_revert_20261114/`
Superseded by: `tests/test_s2_r8_reader_revert_20261114.py` + `config/ci_gates/S2_R8_READER_REVERT_20261114.json`,
and the R6 reader contract restored in `tests/test_overview_projection_20261114.py`.
Returns with: the INC-OVW permanent fix (24/7 n8n schedule plus admission test, OP-038/OP-042), which must
re-point the gates in the same change.
Reason: git history and this archive keep the bytes; rule 6 forbids deletion.

Fires when: production code, a gate, crontab, systemd or n8n references
`archive/s2_r8_reader_revert_20261114/` as a live input, or a gate file names an archived test.

Restore (operator only): the five `git mv` commands in the `ARCHIVE_MANIFEST.json` entries for this batch.
