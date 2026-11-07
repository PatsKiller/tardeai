"""run-profit-capture-refresh must write the file the scheduler watches.

Found 2026-11-07: the lane read `SILENT` from 2026-10-04, output file
`logs/profit_capture_refresh_cron.log` (CRON_LOG_REDIRECT) 0 bytes, while every
Sunday fire had completed — `safe_flock_events.jsonl` for
`tradeai_profit_capture_refresh`: completed 2026-11-01T03:30:29-05:00 (08:30:29Z),
exit 0 (the 2026-10-25 pair: started 03:30:01, completed 03:30:28), and its own log
ended `reliable_n=10 / floor 20 ; verdicts=DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE` then
`=== profit-capture refresh done (20261101_0830) ===`.

The script wrote everything to its private detail log and nothing to stdout, and
stdout is exactly what cron redirects into the file the registry declares. So the
lane was healthy and unobservable at the same time.

These are source assertions (the run itself needs the live DB, psql and git), plus
the offline dry run, which must stay silent and write nothing.
"""
import subprocess
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "scripts" / "run_profit_capture_refresh.sh"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_the_run_says_start_headline_and_done_on_stdout():
    src = _source()
    assert 'say() { echo "$1"; echo "$1" >> "$LOG"; }' in src, "say() must print AND append"
    for marker in ("profit-capture refresh start", "profit-capture refresh done",
                   "reliable_n query failed"):
        line = next(l for l in src.splitlines() if marker in l)
        assert line.strip().startswith("say "), f"{marker!r} must go to the cron log, not only $LOG"


def test_the_headline_is_reported_even_when_psql_fails():
    src = _source()
    assert "RELIABLE_N=" in src
    assert 'say "$RELIABLE_N"' in src
    # The psql error goes to the detail log; stdout still gets a line either way.
    assert '2>>"$LOG"' in src


def test_the_dry_run_stays_offline_and_silent():
    proc = subprocess.run(["bash", str(SOURCE), "--dry-run"], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0
    assert proc.stdout.startswith("DRY-RUN run-profit-capture-refresh:")
    assert "LANE_OUTPUT" in proc.stderr
    assert "profit-capture refresh start" not in proc.stdout, "a dry run reports nothing it did not do"
