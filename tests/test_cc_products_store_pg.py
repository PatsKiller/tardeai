"""store_pg against a disposable initdb cluster (LQ-20261107-2595). Never touches the production database.

LQ-20261107-2646 (REVIEW-2606 F3): the cluster is stood up from the operator migration itself
(``store_pg.MIGRATION_PATH``, applied as role trade_ai), not from a private DDL copy.
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))

from support.isolated_pg import IsolatedPostgres  # noqa: E402

from scripts.lib.cc_products import store_pg  # noqa: E402
from scripts.lib.cc_products.store_pg import (  # noqa: E402
    MAX_BODY_BYTES,
    MIGRATION_PATH,
    BodyTooLarge,
    log_build,
    read_current,
    try_lock,
    write_current,
)

try:
    from support.isolated_pg import pg_bin_dir

    pg_bin_dir()
    HAVE_PG = True
except Exception:  # noqa: BLE001
    HAVE_PG = False

psycopg2 = pytest.importorskip("psycopg2")
pytestmark = pytest.mark.skipif(not HAVE_PG, reason="no PostgreSQL server binaries on this host")

T0 = datetime(2026, 11, 12, 15, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def cluster():
    pg = IsolatedPostgres()
    try:
        pg.start()
        assert pg.verify_isolated()["verdict"] == "ISOLATED"
        conn = _connect(pg)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("CREATE ROLE trade_ai NOLOGIN")
            cur.execute("GRANT CREATE, USAGE ON SCHEMA public TO trade_ai")
            cur.execute("SET ROLE trade_ai")
            cur.execute(MIGRATION_PATH.read_text())
            cur.execute("RESET ROLE")
        conn.close()
        yield pg
    finally:
        pg.stop()


def _connect(pg):
    return psycopg2.connect(host=pg.host, port=pg.port, dbname=pg.dbname, user=pg.user, password=pg.password,
                            connect_timeout=10)


@pytest.fixture
def conn(cluster):
    c = _connect(cluster)
    with c.cursor() as cur:
        cur.execute("TRUNCATE cc_product_current, cc_product_build_log")
    c.commit()
    yield c
    c.rollback()
    c.close()


def _write(cur, body, *, built_at=T0, as_of=T0 - timedelta(seconds=30), nra=None, **kw):
    params = dict(
        as_of=as_of,
        built_at=built_at,
        next_refresh_at=nra or built_at + timedelta(seconds=120),
        stale_after_s=360,
        hard_expiry_s=1800,
        purge_after_s=604800,
        source_watermarks={"w7": "2026-11-12T14:59:30+00:00"},
        builder_sha="sha-1",
        build_ms=12,
    )
    params.update(kw)
    return write_current(cur, "cio.pages", "global", body, **params)


def test_write_then_read_round_trip(conn):
    with conn.cursor() as cur:
        assert read_current(cur, "cio.pages") is None
        res = _write(cur, b'{"a":1}')
        assert res["changed"] is True and res["seq"] == 1
        assert res["etag"] == store_pg.etag_for(b'{"a":1}') and res["etag"].startswith("sha256:")
        conn.commit()
        row = read_current(cur, "cio.pages", "global")
    assert set(row) == set(store_pg.COLUMNS)
    assert row["body"] == b'{"a":1}' and isinstance(row["body"], bytes)
    assert row["seq"] == 1 and row["status"] == "OK"
    assert row["as_of"] == T0 - timedelta(seconds=30) and row["as_of"].tzinfo is not None
    assert row["built_at"] == T0 and row["built_at"].tzinfo is not None
    assert row["source_watermarks"] == {"w7": "2026-11-12T14:59:30+00:00"}
    assert row["bytes"] == 7 and row["build_ms"] == 12 and row["builder_sha"] == "sha-1"
    assert (row["stale_after_s"], row["hard_expiry_s"], row["purge_after_s"]) == (360, 1800, 604800)


def test_read_works_with_a_dict_cursor(conn):
    import psycopg2.extras

    with conn.cursor() as cur:
        _write(cur, b"{}")
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        row = read_current(cur, "cio.pages")
        assert row["body"] == b"{}" and row["seq"] == 1
        assert try_lock(cur, "cio.pages") is True


def test_unchanged_body_keeps_seq_and_built_at_and_moves_checked_at(conn):
    with conn.cursor() as cur:
        _write(cur, b'{"a":1}')
        later = T0 + timedelta(seconds=120)
        res = _write(cur, b'{"a":1}', built_at=later, as_of=later - timedelta(seconds=5), builder_sha="sha-2",
                     build_ms=99)
        assert res == {"changed": False, "seq": 1, "etag": store_pg.etag_for(b'{"a":1}')}
        row = read_current(cur, "cio.pages")
    assert row["seq"] == 1
    assert row["built_at"] == T0  # phase-0 DDL: built_at = when this body was produced (LQ-2646)
    with conn.cursor() as cur:
        cur.execute("SELECT checked_at FROM cc_product_current WHERE product_id = 'cio.pages'")
        assert cur.fetchone()[0] == later
    assert row["next_refresh_at"] == later + timedelta(seconds=120)
    # LQ-2595 integration: an unchanged body keeps body/seq/etag, but as_of is the new build's source
    # watermark (else a product whose content is steady would read STALE, then UNKNOWN, while rebuilding fine)
    assert row["as_of"] == later - timedelta(seconds=5)
    assert row["builder_sha"] == "sha-1" and row["build_ms"] == 12


def test_changed_body_bumps_seq(conn):
    with conn.cursor() as cur:
        _write(cur, b'{"a":1}')
        r2 = _write(cur, b'{"a":2}', built_at=T0 + timedelta(seconds=120))
        r3 = _write(cur, b'{"a":3}', built_at=T0 + timedelta(seconds=240))
        r4 = _write(cur, b'{"a":3}', built_at=T0 + timedelta(seconds=360))
        row = read_current(cur, "cio.pages")
    assert (r2["changed"], r2["seq"]) == (True, 2)
    assert (r3["changed"], r3["seq"]) == (True, 3)
    assert (r4["changed"], r4["seq"]) == (False, 3)
    assert row["body"] == b'{"a":3}' and row["seq"] == 3


def test_scopes_are_independent(conn):
    with conn.cursor() as cur:
        _write(cur, b"1")
        write_current(cur, "cio.pages", "acct:9", b"2", as_of=T0, built_at=T0, next_refresh_at=None,
                      stale_after_s=1, hard_expiry_s=2, purge_after_s=3, source_watermarks={}, builder_sha="",
                      build_ms=0)
        assert read_current(cur, "cio.pages")["body"] == b"1"
        other = read_current(cur, "cio.pages", "acct:9")
    assert other["body"] == b"2" and other["seq"] == 1 and other["as_of"] == T0


def test_body_over_two_megabytes_raises_and_writes_nothing(conn):
    with conn.cursor() as cur:
        _write(cur, b"x" * MAX_BODY_BYTES)  # exactly at the cap is allowed
        with pytest.raises(BodyTooLarge):
            _write(cur, b"y" * (MAX_BODY_BYTES + 1), built_at=T0 + timedelta(seconds=1))
        row = read_current(cur, "cio.pages")
    assert row["seq"] == 1 and row["bytes"] == MAX_BODY_BYTES and row["built_at"] == T0


def test_log_build_inserts_a_row(conn):
    with conn.cursor() as cur:
        log_build(cur, "cio.pages", "global", "OK", started_at=T0, finished_at=T0 + timedelta(seconds=2),
                  build_ms=2000, lane="dp-fast", peak_rss_kb=123456, bytes_=789, error=None)
        log_build(cur, "cio.pages", "global", "SKIPPED_BUSY", started_at=T0, finished_at=T0, build_ms=0,
                  lane="dp-fast")
        cur.execute("SELECT product_id, scope_key, lane, outcome, build_ms, peak_rss_kb, bytes_written, error, "
                    "started_at "
                    "FROM cc_product_build_log ORDER BY id")
        rows = cur.fetchall()
    assert rows[0] == ("cio.pages", "global", "dp-fast", "BUILT", 2000, 123456, 789, None, T0)  # receipt OK
    assert rows[1][3] == "SKIPPED_BUSY" and rows[1][2] == "dp-fast"
    assert len(rows) == 2


def test_log_build_rejects_unknown_outcome(conn):
    with conn.cursor() as cur, pytest.raises(ValueError):
        log_build(cur, "cio.pages", "global", "MAYBE", started_at=T0, finished_at=T0, build_ms=0, lane="dp-fast")


def test_try_lock_is_false_while_held_and_never_blocks(cluster, conn):
    holder = _connect(cluster)
    other = _connect(cluster)
    try:
        with holder.cursor() as hc:
            assert try_lock(hc, "cio.pages") is True
            assert try_lock(hc, "cio.pages") is True  # re-entrant in the holder's own transaction

        result: dict = {}

        def attempt():
            with other.cursor() as oc:
                oc.execute("SET lock_timeout = '5s'")
                t0 = time.monotonic()
                result["got"] = try_lock(oc, "cio.pages")
                result["elapsed"] = time.monotonic() - t0

        th = threading.Thread(target=attempt, daemon=True)
        th.start()
        th.join(3.0)
        assert not th.is_alive(), "try_lock blocked while another connection held the lock"
        assert result["got"] is False
        assert result["elapsed"] < 1.0
        other.rollback()

        with other.cursor() as oc:
            assert try_lock(oc, "cio.pages", "acct:1") is True  # a different scope is a different lock
        other.rollback()

        holder.rollback()  # xact lock released at transaction end
        with other.cursor() as oc:
            assert try_lock(oc, "cio.pages") is True
        other.rollback()
    finally:
        holder.close()
        other.close()
