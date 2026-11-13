"""LQ-20261107-2646 (REVIEW-2606 F3): one migration for the precompute store, and the 2595 writers obey it.

Before: 2595's ``store_pg`` carried its own ``TEST_DDL`` (no ``checked_at``, nullable ``as_of``/``lane``, a ``bytes``
build-log column, outcomes ``OK``/``TIMEOUT``/``REFUSED``) while the operator migration was 2591's phase-0 DDL. Every
2595 test passed against the copy, and the first production write would have failed on a NOT NULL or a CHECK.

Now: ``migrations/2026_11_12_cc_data_products.sql`` is the only DDL. These tests apply it VERBATIM, as role
trade_ai, to a disposable initdb cluster (never the production database) and drive the real writers against it.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))

from support.isolated_pg import IsolatedPostgres  # noqa: E402

from scripts.lib.cc_products import cio_pages, hermes_projection, store_pg  # noqa: E402

MIGRATION = ROOT / "migrations" / "2026_11_12_cc_data_products.sql"
DOWN = ROOT / "migrations" / "2026_11_12_cc_data_products.down.sql"

try:
    from support.isolated_pg import pg_bin_dir

    pg_bin_dir()
    HAVE_PG = True
except Exception:  # noqa: BLE001
    HAVE_PG = False

psycopg2 = pytest.importorskip("psycopg2")
pytestmark = pytest.mark.skipif(not HAVE_PG, reason="no PostgreSQL server binaries on this host")

T0 = datetime(2026, 11, 12, 15, 0, 0, tzinfo=timezone.utc)


def _dsn(c) -> dict:
    return dict(host=c.host, port=c.port, user=c.user, password=c.password, dbname=c.dbname, connect_timeout=10)


def _apply(cur, path: Path) -> None:
    cur.execute("SET ROLE trade_ai")  # the operator command: psql -c 'SET ROLE trade_ai' -f <file>
    cur.execute(path.read_text())
    cur.execute("RESET ROLE")


@pytest.fixture(scope="module")
def pg():
    cluster = IsolatedPostgres()
    try:
        cluster.start()
        assert cluster.verify_isolated()["verdict"] == "ISOLATED"
        conn = psycopg2.connect(**_dsn(cluster))
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("CREATE ROLE trade_ai NOLOGIN")
            cur.execute("GRANT CREATE, USAGE ON SCHEMA public TO trade_ai")
            _apply(cur, MIGRATION)
            _apply(cur, MIGRATION)  # idempotent: a second apply is a no-op
            _apply(cur, DOWN)
            _apply(cur, DOWN)
            _apply(cur, MIGRATION)
        conn.close()
        yield cluster
    finally:
        cluster.stop()


@pytest.fixture
def conn(pg):
    c = psycopg2.connect(**_dsn(pg))
    with c.cursor() as cur:
        cur.execute("TRUNCATE cc_product_current, cc_product_build_log, hermes_projection_entry, hermes_projection_meta")
    c.commit()
    yield c
    c.rollback()
    c.close()


def _write(cur, body=b'{"a":1}', *, built_at=T0, as_of=T0 - timedelta(seconds=30)):
    return store_pg.write_current(
        cur, "cio.pages", "global", body, as_of=as_of, built_at=built_at,
        next_refresh_at=built_at + timedelta(seconds=120), stale_after_s=360, hard_expiry_s=1800,
        purge_after_s=604800, source_watermarks={"_product": {"oldest_section_as_of": None}}, builder_sha="s",
        build_ms=5)


def test_the_migration_owns_every_store_table_and_the_three_review_checks(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT c.relname, pg_get_userbyid(c.relowner) FROM pg_class c "
                    "WHERE c.relname LIKE 'cc_product_%%' AND c.relkind IN ('r', 'S') "
                    "   OR c.relname LIKE 'hermes_projection_%%' AND c.relkind = 'r' ORDER BY 1")
        owned = dict(cur.fetchall())
        cur.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'cc_product_current'::regclass "
                    "AND contype = 'c' ORDER BY 1")
        checks = [r[0] for r in cur.fetchall()]
    assert owned == {name: "trade_ai" for name in (
        "cc_product_build_log", "cc_product_build_log_id_seq", "cc_product_current", "cc_product_delta", "cc_product_dirty", "cc_product_seq",
        "hermes_projection_entry", "hermes_projection_meta")}
    assert checks == ["cc_product_current_bytes_ck", "cc_product_current_limits_ck", "cc_product_current_status_ck"]


def test_store_pg_carries_no_private_ddl():
    src = Path(store_pg.__file__).read_text()
    assert "CREATE TABLE" not in src.upper() and not hasattr(store_pg, "TEST_DDL")
    assert store_pg.MIGRATION_PATH == MIGRATION


def test_write_current_satisfies_the_phase0_ddl_and_sets_checked_at(conn):
    with conn.cursor() as cur:
        res = _write(cur)
        cur.execute("SELECT seq, built_at, checked_at, bytes, octet_length(body), status FROM cc_product_current")
        row = cur.fetchone()
    assert res["changed"] is True and res["seq"] == 1
    assert row == (1, T0, T0, 7, 7, "OK")


def test_an_unchanged_body_moves_checked_at_and_keeps_built_at(conn):
    later = T0 + timedelta(seconds=120)
    with conn.cursor() as cur:
        _write(cur)
        res = _write(cur, built_at=later, as_of=later - timedelta(seconds=5))
        cur.execute("SELECT seq, built_at, checked_at, as_of FROM cc_product_current")
        row = cur.fetchone()
    assert res["changed"] is False
    assert row == (1, T0, later, later - timedelta(seconds=5))  # built_at = when this body was produced


def test_a_missing_as_of_is_refused_before_the_database(conn):
    with conn.cursor() as cur:
        with pytest.raises(ValueError, match="as_of"):
            _write(cur, as_of=None)
        cur.execute("SELECT count(*) FROM cc_product_current")
        assert cur.fetchone()[0] == 0


@pytest.mark.parametrize("receipt_outcome,stored", [
    ("OK", "BUILT"), ("UNCHANGED", "UNCHANGED"), ("FAILED", "FAILED"), ("TIMEOUT", "FAILED"),
    ("REFUSED", "REFUSED_SIZE"), ("SKIPPED_BUSY", "SKIPPED_BUSY"),
])
def test_every_receipt_outcome_lands_in_the_phase0_vocabulary(conn, receipt_outcome, stored):
    with conn.cursor() as cur:
        store_pg.log_build(cur, "cio.pages", "global", receipt_outcome, started_at=T0, finished_at=T0, build_ms=3,
                           lane="dp-fast", peak_rss_kb=10, bytes_=99, error=None)
        cur.execute("SELECT outcome, lane, bytes_written, detail FROM cc_product_build_log")
        row = cur.fetchone()
    detail = {} if receipt_outcome == stored else {"receipt_outcome": receipt_outcome}
    assert row == (stored, "dp-fast", 99, detail)


def test_log_build_without_a_lane_is_refused_before_the_database(conn):
    with conn.cursor() as cur, pytest.raises(ValueError, match="lane"):
        store_pg.log_build(cur, "cio.pages", "global", "OK", started_at=T0, finished_at=T0, build_ms=0, lane=None)


def _payload(**_kw) -> dict:
    return {"portfolio": {"as_of": "2026-11-12T14:58:00+00:00", "v": 1},
            "concentration_policy": {"as_of": "2026-10-24T00:00:00+00:00", "v": 2}}


def _boom(*_a, **_kw):
    raise RuntimeError("source unreadable")


def test_run_once_writes_the_real_store_built_then_unchanged_then_failed_keeps_last_good(pg, conn, tmp_path):
    def connect():
        return psycopg2.connect(**_dsn(pg))

    def run(build_fn):
        return cio_pages.run_once(connect=connect, root=tmp_path, dry_run=False, builder_sha="t",
                                  db_query_factory=lambda: None, build_fn=build_fn)

    r1, r2, r3 = run(lambda root, **kw: _payload()), run(lambda root, **kw: _payload()), run(_boom)
    assert (r1["outcome"], r2["outcome"], r3["outcome"]) == ("OK", "UNCHANGED", "FAILED")
    with conn.cursor() as cur:
        cur.execute("SELECT product_id, scope_key, seq, status, bytes = octet_length(body), built_at <= checked_at, "
                    "source_watermarks->'_product'->>'oldest_section_as_of' FROM cc_product_current")
        current = cur.fetchall()
        cur.execute("SELECT lane, outcome, bytes_written IS NOT NULL, error FROM cc_product_build_log ORDER BY id")
        log = cur.fetchall()
    assert current == [("cio.pages", "global", 1, "OK", True, True, "2026-10-24T00:00:00+00:00")]
    assert log[:2] == [("dp-fast", "BUILT", True, None), ("dp-fast", "UNCHANGED", True, None)]
    assert log[2][:3] == ("dp-fast", "FAILED", False) and "source unreadable" in log[2][3]
    assert len(log) == 3


def test_hermes_ingest_writes_the_same_migrated_database(pg, conn, tmp_path):
    src = tmp_path / "hermes_research_projection.json"
    src.write_text(json.dumps({"updated_ts": "2026-11-12T14:00:00+00:00",
                               "by_research_id": {"r1": {"research_id": "r1", "plan_id": "p1", "symbol": "AAPL"}},
                               "by_plan_id": {"p1": {"open": ["r1"]}},
                               "by_fingerprint_open": {}, "by_fingerprint_completed": {}}))
    receipt = hermes_projection.ingest(lambda: psycopg2.connect(**_dsn(pg)), src, dry_run=False)
    assert receipt["outcome"] == "OK", receipt
    with conn.cursor() as cur:
        cur.execute("SELECT map, entry_key, plan_id, symbol FROM hermes_projection_entry ORDER BY 1, 2")
        assert cur.fetchall() == [("by_plan_id", "p1", "p1", None), ("by_research_id", "r1", "p1", "AAPL")]
        cur.execute("SELECT ingest_seq, entries->>'by_research_id' FROM hermes_projection_meta")
        assert cur.fetchone() == (1, "1")


def test_a_build_without_a_clock_logs_failed_and_keeps_the_last_good_row(pg, conn, tmp_path, monkeypatch):
    def connect():
        return psycopg2.connect(**_dsn(pg))

    def run():
        return cio_pages.run_once(connect=connect, root=tmp_path, dry_run=False, builder_sha="t",
                                  db_query_factory=lambda: None, build_fn=lambda root, **kw: _payload())

    assert run()["outcome"] == "OK"
    real = cio_pages.product_clock
    monkeypatch.setattr(cio_pages, "product_clock", lambda payload, read_at: (None, real(payload, read_at)[1]))
    r2 = run()  # the child is forked, so it sees the patched clock
    assert r2["outcome"] == "FAILED" and "as_of" in r2["error"]
    with conn.cursor() as cur:
        cur.execute("SELECT seq, status FROM cc_product_current")
        assert cur.fetchall() == [(1, "OK")]
        cur.execute("SELECT lane, outcome, error FROM cc_product_build_log ORDER BY id")
        log = cur.fetchall()
    assert [r[:2] for r in log] == [("dp-fast", "BUILT"), ("dp-fast", "FAILED")] and "as_of" in log[1][2]
