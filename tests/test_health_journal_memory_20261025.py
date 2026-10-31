"""ANCHOR: HEALTH_JOURNAL_MEMORY_20261025 — batch 37: Health + Journal page memory.

* scheduler_operations.read_run_ledger cuts each receipt to RECEIPT_KEYS inside SQLite (the newest 10k receipts are
  ~56 MB of JSON; the Jobs-health rebuild parsed all of it in Python). Same rows; peak-allocation regression on a
  synthetic ledger.
* jobs_health.plain_reason: evidence codes become sentences and file paths are never shown (Ops Controls → Jobs
  "Missed" explanation printed raw codes and a script path).
Hermetic: synthetic sqlite in tmp_path; no live state.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import jobs_health as J  # noqa: E402
from scripts.lib import scheduler_operations as so  # noqa: E402


def _ledger(path: Path, n: int) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE runs (run_id TEXT, lane_id TEXT, mode TEXT, state TEXT, requested_at TEXT, "
                 "finished_at TEXT, exit_code INTEGER, receipt_json TEXT)")
    rows = []
    for i in range(n):
        kind = i % 6
        if kind == 0:
            receipt = None
        elif kind == 1:
            receipt = ""
        elif kind == 2:
            receipt = "{}"
        else:
            receipt = json.dumps({"schema": "RunReceipt@v2", "run_id": f"r{i}", "lane_id": f"lane-{i % 9}", "mode": "live",
                                  "state": "RUN_DONE", "exit_code": i % 2, "duration_s": i * 0.5, "lock_skipped": bool(i % 3),
                                  "timed_out": False, "output_signal": {"kind": "json_key", "path": "data/x.json"},
                                  "stderr_tail": None if i % 4 else "boom ü", "stage_clamp": [1, 2],
                                  "big_payload": "x" * 4000, "nested": {"deep": list(range(50))}})
        rows.append((f"r{i}", f"lane-{i % 9}", "live", "RUN_DONE", f"2026-10-25T{i % 24:02d}:{i % 60:02d}:00Z",
                     None, i % 2, receipt))
    conn.executemany("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return path


def _python_path(path, monkeypatch):
    monkeypatch.setattr(so, "_read_runs_projected", lambda conn: None)
    try:
        return so.read_run_ledger(path)
    finally:
        monkeypatch.undo()


def test_projected_ledger_rows_equal_python_rows(tmp_path, monkeypatch):
    path = _ledger(tmp_path / "ledger.sqlite", 600)
    ref = _python_path(path, monkeypatch)
    got = so.read_run_ledger(path)
    assert got == ref and got[1] is True and len(got[0]) == 600
    assert any(r["receipt"] is None for r in got[0]) and any(r["receipt"] and r["receipt"]["lock_skipped"] is True for r in got[0])


def test_projected_ledger_falls_back_on_non_object_receipt(tmp_path, monkeypatch):
    path = _ledger(tmp_path / "ledger.sqlite", 30)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE runs SET receipt_json='[1,2]' WHERE run_id='r5'")
    conn.commit()
    conn.close()
    conn = sqlite3.connect(path)
    assert so._read_runs_projected(conn) is None  # the Python path decides, exactly as before
    conn.close()


def test_projected_ledger_peak_allocation(tmp_path, monkeypatch):
    """Peak-allocation regression: big receipts are cut to RECEIPT_KEYS before Python sees them."""
    path = _ledger(tmp_path / "ledger.sqlite", 3000)
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        _python_path(path, monkeypatch)
        python_peak = tracemalloc.get_traced_memory()[1] - base
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        so.read_run_ledger(path)
        projected_peak = tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()
    assert projected_peak < python_peak * 0.75, (projected_peak, python_peak)


def test_plain_reason_never_shows_paths_or_raw_codes():
    p = J.plain_reason
    assert p("scripts/secrets/bws_env.sh: line 4: TOKEN: unbound variable") == "the secrets loader: line 4: TOKEN: unbound variable"
    assert p("journal_malformed_line") == "some run-journal lines could not be read"
    assert p("lane-a:receipt_unavailable") == "lane-a: its run receipt could not be read"
    assert p("output_unverifiable") == "The run finished but its output could not be verified"
    assert p("refused: symlink_component in logs/x.log") == "refused: symlink_component in a log file"
    assert p("lock wrapper refused release path") == "lock wrapper refused release path"
    assert p(None) is None
    for text in ("/home/user/trade-ai/data/x.json missing", "run ~/n8n/packet.sh failed", "see tools/run.py"):
        assert "/" not in p(text) and ".py" not in p(text)


def test_missed_explanation_is_plain_language():
    lanes = [{"lane_id": "job-c", "state": "ACTIVE", "scheduler": {"kind": "cron", "expression": "0 9 * * *"}}]
    snapshot = {"events": [], "successes": {}, "collection_gaps": ["journal_history_window_truncated",
                                                                   "job-c:fallback_log_unavailable"]}
    from datetime import datetime, timezone
    report = J.build({"lanes": lanes}, snapshot, [], {}, now=datetime(2026, 10, 26, 15, tzinfo=timezone.utc),
                     trading_day=lambda d: True)
    why = report["summary"]["gap_reasons"]["missed"]
    assert "journal_history_window_truncated" not in why and "fallback_log_unavailable" not in why
    assert "older runs are not counted" in why and "job-c: its log could not be read" in why
