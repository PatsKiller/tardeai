"""`source=runs` on the coordination projection (n8n scheduler-of-record program, stream G, 2026-10-08).

The `runs` table is written by stream B's gateway `run` operation and settled by the executor; this
projection reads it read-only and must be an honest empty page when the ledger or the table is not
there yet. Existing sources keep their shape (the 10-07 tests pin them)."""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_coordination_projection as P  # noqa: E402

NOW = datetime(2026, 10, 8, 13, 0, tzinfo=timezone.utc)
DDL = ("CREATE TABLE runs(run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_by TEXT, caller_id TEXT, "
       "requested_at TEXT, started_at TEXT, finished_at TEXT, exit_code INTEGER, duration_s REAL, receipt_json TEXT)")


def make_ledger(path: Path, rows: list[tuple]) -> Path:
    conn = sqlite3.connect(path)
    conn.execute(DDL)
    conn.executemany("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return path


def row(run_id, lane, mode, state, *, exit_code=0, finished="2026-10-08T12:30:00+00:00", caller="n8n-relay"):
    return (run_id, lane, mode, state, caller, caller, "2026-10-08T12:29:00+00:00", "2026-10-08T12:29:05+00:00",
            finished, exit_code, 4.5, "{}")


def test_absent_ledger_and_absent_table_are_empty_pages_not_errors(tmp_path):
    out = P.project(tmp_path / "absent.sqlite", source="runs", now=NOW)
    assert out["status"] == "NO_LEDGER" and out["items"] == [] and out["schema"] == P.RUNS_SCHEMA
    p = tmp_path / "old.sqlite"
    sqlite3.connect(p).execute("CREATE TABLE receipts(x)").connection.commit()
    out = P.project(p, source="runs", now=NOW)
    assert out["status"] == "OK" and out["count"] == 0 and "no runs table" in out["note"]


def test_runs_items_carry_the_contract_fields_newest_first_and_filter(tmp_path):
    p = make_ledger(tmp_path / "l.sqlite", [
        row("r1", "n8n-lab-watchdog", "dry_run", "RUN_DONE", finished="2026-10-08T11:00:00+00:00"),
        row("r2", "n8n-lab-watchdog", "live", "RUN_FAILED", exit_code=2, finished="2026-10-08T12:30:00+00:00"),
        row("r3", "premarket-data-pipeline", "live", "RUN_SKIPPED_LOCK", finished="2026-10-08T12:00:00+00:00"),
    ])
    out = P.project(p, source="runs", now=NOW)
    assert out["status"] == "OK" and [i["run_id"] for i in out["items"]] == ["r2", "r3", "r1"]
    it = out["items"][0]
    assert set(it) >= {"run_id", "lane_id", "mode", "state", "exit_code", "duration_s", "requested_by", "requested_at", "finished_at", "receipt_ref"}
    assert it["receipt_ref"] == "data/runtime/n8n_runs/r2.json" and it["state_text"] == "run failed" and it["age_s"] == 1800
    assert it["requested_by"] == "n8n-relay" and it["evidence"] == "ledger:l.sqlite#runs/r2"
    assert P.project(p, source="runs", lane_id="n8n-lab-watchdog")["count"] == 2
    assert [i["run_id"] for i in P.project(p, source="runs", state="run_skipped_lock")["items"]] == ["r3"]
    assert P.project(p, source="runs", limit=1)["count"] == 1


def test_other_sources_are_untouched_by_the_runs_table(tmp_path):
    p = make_ledger(tmp_path / "l.sqlite", [row("r1", "x", "live", "RUN_DONE")])
    out = P.project(p, now=NOW)       # default source: the receipts table, which this ledger lacks
    assert out["schema"] == P.SCHEMA and out["status"].startswith("UNREADABLE") and "source" not in out


def test_api_routes_pass_source_through_and_serve_the_board_file_read_only():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    i = src.index('base_path == "/api/v2/coordination/events"')
    block = src[i:i + 800]
    assert 'source=q.get("source") or None' in block and "sqlite" not in block
    j = src.index('base_path == "/api/v2/coordination/migration-board"')
    block = src[j:j + 1200]
    assert "n8n_migration_board_last.json" in block and '"NO_BOARD"' in block and "n8n_migration_board import" not in block
    assert "subprocess" not in block and "crontab" not in block
