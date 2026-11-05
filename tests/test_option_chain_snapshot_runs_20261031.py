"""Options chain snapshot keeps every run, not only the latest of the day (2026-10-31).

option_chain_snapshots upserts on (as_of, symbol), so the 17:35 ET run replaced the 10:00 ET reading the Market
Risk Engine needs (2026-10-29 10:00 ET: QQQ put/call volume 3.31). option_chain_snapshot_runs keeps both. These
tests pin the slot arithmetic, the insert, the absent-table fallback, the migration pair, and that the writer
wires it in without touching the daily upsert. No network, no DB, no broker.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import option_chain_runs as ocr  # noqa: E402


class _Cur:
    def __init__(self, present=True):
        self.present, self.calls = present, []

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        return (self.present,)


def test_slots_in_daylight_and_standard_time():
    assert ocr.slot_et(datetime(2026, 10, 29, 14, 0, tzinfo=timezone.utc)) == ("2026-10-29", "10:00")
    assert ocr.slot_et(datetime(2026, 10, 29, 21, 35, tzinfo=timezone.utc)) == ("2026-10-29", "17:35")
    assert ocr.slot_et(datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)) == ("2026-11-03", "10:00")  # after DST ends
    assert ocr.slot_et(datetime(2026, 10, 30, 3, 30)) == ("2026-10-29", "23:30")  # naive = UTC; ET date wins


def test_record_run_inserts_all_fields_and_is_rerun_safe():
    cur = _Cur()
    agg = {f: i for i, f in enumerate(ocr.FIELDS)}
    ocr.record_run(cur, "QQQ", agg, as_of="2026-10-29", slot="10:00")
    sql, params = cur.calls[0]
    assert sql.startswith("INSERT INTO option_chain_snapshot_runs")
    assert "ON CONFLICT (as_of, slot_et, symbol) DO NOTHING" in sql
    assert params == ("2026-10-29", "10:00", "QQQ", *range(len(ocr.FIELDS)))


def test_table_present_reads_regclass():
    assert ocr.table_present(_Cur(True)) is True
    assert ocr.table_present(_Cur(False)) is False


def test_migration_pair_is_idempotent_and_never_drops():
    up = (ROOT / "migrations" / "2026_10_31_option_chain_snapshot_runs.sql").read_text()
    down = (ROOT / "migrations" / "2026_10_31_option_chain_snapshot_runs.down.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS option_chain_snapshot_runs" in up
    assert "PRIMARY KEY (as_of, slot_et, symbol)" in up
    assert "CREATE INDEX IF NOT EXISTS" in up
    assert "option_chain_snapshots" not in re.sub(r"--.*", "", up)  # the daily table is not altered
    assert not re.search(r"\bDROP\b", re.sub(r"--.*", "", up + down), re.I)
    assert "RENAME TO option_chain_snapshot_runs_archived_20261031" in down


def test_writer_wires_run_history_beside_the_unchanged_daily_upsert():
    src = (ROOT / "scripts" / "options_chain_snapshot.py").read_text()
    assert "ON CONFLICT (as_of, symbol) DO UPDATE SET put_oi=EXCLUDED.put_oi" in src  # daily upsert unchanged
    assert "ocr.record_run(cur, sym, agg, as_of=run_as_of, slot=run_slot)" in src
    assert "runs_ok = (not args.dry_run) and ocr.table_present(cur)" in src  # dry run never writes
    assert "migration 2026_10_31_option_chain_snapshot_runs.sql not applied" in src  # absent table is said, not fatal
