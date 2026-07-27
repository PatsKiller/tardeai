"""Stage 5 replay + lab-DB tests.

Replay tests require pyarrow (present in the isolated moomoo venv; this file is run
BY that venv in the Stage 5 harness). DB tests require the lab write DSN.
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

pa = pytest.importorskip("pyarrow", reason="pyarrow only in the isolated moomoo venv")

from active_trader.moomoo import replay  # noqa: E402


def test_wal_append_checksum_and_recovery(tmp_path):
    wal = tmp_path / "seg.wal"
    w = replay.WALWriter(wal)
    for i in range(50):
        w.append({"i": i, "gateway_receive_timestamp": f"2026-07-23T00:00:{i:02d}+00:00"})
    w.close()
    records = list(replay.wal_read(wal))
    assert len(records) == 50 and records[0]["i"] == 0
    # simulate a torn tail line
    with open(wal, "ab") as fh:
        fh.write(b"deadbeef\tnot-terminated-json")
    assert len(list(replay.wal_read(wal))) == 50      # torn tail dropped, prior intact
    # corrupt a crc → truncates at that record
    data = wal.read_bytes().split(b"\n")
    data[10] = b"00000000\t" + b'{"i": 999}'
    wal.write_bytes(b"\n".join(data))
    assert len(list(replay.wal_read(wal))) == 10


def test_compaction_verifies_roundtrip(tmp_path):
    wal = tmp_path / "seg.wal"
    w = replay.WALWriter(wal)
    for i in range(30):
        w.append({"i": i, "gateway_receive_timestamp": f"2026-07-23T01:00:{i:02d}+00:00"})
    w.close()
    result = replay.compact_to_parquet(wal, tmp_path / "seg.parquet")
    assert result.verified and result.row_count == 30
    assert result.min_ts and result.max_ts and len(result.wal_sha256) == 64
    # WAL retained until verification (it still exists here)
    assert wal.exists()


def test_disk_gate_states(tmp_path):
    g = replay.disk_gate(tmp_path)
    assert g["state"] in ("OK", "HIGH_WATER", "CRITICAL", "INSUFFICIENT_FREE")
    assert g["budget_bytes"] == 20 * 1024**3


def test_partition_path_shape(tmp_path):
    p = replay.partition_path(tmp_path, "2026-07-23", "RTH", "US.AAPL", "QUOTE", "wal")
    assert p.parts[-4:] == ("RTH", "US_AAPL", "QUOTE", "segment.wal")


# ---- lab DB migration 0007
DSN = os.environ.get("ACTIVE_TRADER_TEST_DATABASE_DSN", "")


@pytest.mark.skipif(not DSN, reason="lab write DSN required")
def test_migration_0007_cycle_and_tables():
    def mig(*a):
        return subprocess.run([sys.executable, str(REPO / "scripts/active_trader/migrate.py"), *a],
                              capture_output=True, text=True,
                              env={**os.environ, "ACTIVE_TRADER_TEST_DATABASE_DSN": DSN})
    assert mig("up").returncode == 0
    st = mig("status")
    assert "moomoo_market_data" in st.stdout and "pending" not in st.stdout
    assert mig("down", "--to", "6").returncode == 0
    assert mig("up").returncode == 0
    import psycopg2
    conn = psycopg2.connect(DSN); cur = conn.cursor()
    cur.execute("""SELECT count(*) FROM information_schema.tables
                   WHERE table_schema='public' AND table_name LIKE 'md_%%'""")
    assert cur.fetchone()[0] >= 10
    conn.close()
