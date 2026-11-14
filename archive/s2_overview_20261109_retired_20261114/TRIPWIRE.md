TRIPWIRE
# Tripwire — retired overview-projection contract test and gate (2026-11-14)

Status: ACTIVE
as_of: 2026-11-14
Schema: ArchiveTripwire@v1

Nothing may **import, run, or read these archived paths as authority**. The archived test pins the reader
contract that ACC-CACHE r4 deleted on purpose: `overview_projection.read()` used to answer
`(None, {"source": "inline", "reason": aged|invalidated|missing|clock_skew|code_mismatch|write_tracking_off})`
so the route could compute the overview INLINE on every miss. S2 item 2 (operator 2026-11-14) made the route
compute-free: the reader answers a labelled LAST-KNOWN-GOOD (`stale: true` with a named reason) or a named
UNKNOWN (`(None, {"source": "none", "reason": ...})`), and `serve()` never calls its compute argument.

On R7 head `6e4c41770` the archived file is **10 failed / 39 passed** over the three
`test_overview_projection_*` files plus `test_s2_overview_never_inline_20261114.py`; its 10 failures are the
contract change itself, not a defect. The 16 tests whose behaviour did not change are ported to
`tests/test_overview_projection_20261114.py` (gate `overview_projection_20261114`); the other 10 are mapped,
test by test, in `COVERAGE-MAP.md` in this directory.

Archived under: `archive/s2_overview_20261109_retired_20261114/`
Superseded by: `tests/test_overview_projection_20261114.py` + `config/ci_gates/overview_projection_20261114.json`
for the builder / identity / path / invalidation half, and `tests/test_s2_overview_never_inline_20261114.py`
with gate `S2_READ_MODEL_20261114` for the reader matrix half.
Reason: git history and this archive keep the bytes; rule 6 forbids deletion.

Fires when: production code, a gate, crontab, systemd or n8n references
`archive/s2_overview_20261109_retired_20261114/` as a live input, or a gate file names the archived test.

Restore (operator only): see the `ARCHIVE_MANIFEST.json` entries for this batch (two `git mv` commands, one per
file). Restoring the test without restoring the pre-S2 reader puts 10 known failures back on the line, and
restoring the gate registers them.
