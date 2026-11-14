"""LQ-20261113-3140: a stored product must not silently stop refreshing (REFUSED_OLDER).

Two reproduced scenarios (R2-EFFECT-KEY-VERIFICATION Q3):
  (1) a Home slice fails -> the product clock jumps forward -> the slice recovers with its real, older clock -> every
      honest build is REFUSED_OLDER (exit 0, nothing visible);
  (2) a future-dated as_of is stored -> REFUSED_OLDER until the wall clock catches up, and the reader shows a
      clamped age of 0 as fresh.
The 'no older build overwrites a newer one' rule is NOT relaxed (test_older_build_is_still_refused).
Synthetic fixtures only; PG cases run on the disposable initdb cluster from test_home_products_builder_20261113.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))

from scripts.lib.cc_products import builders as B  # noqa: E402
from scripts.lib.cc_products import cio_pages as cp  # noqa: E402
from scripts.lib.cc_products import product_builder as pb  # noqa: E402
from scripts.lib.cc_products import read_path as rp  # noqa: E402
from test_home_products_builder_20261113 import (  # noqa: E402,F401  (fixtures + helpers)
    T0, _ctx, _log, _row, _run, cluster, connect, fake_build, needs_pg, spec)

NOW = datetime(2026, 11, 13, 20, 0, 0, tzinfo=timezone.utc)
STATUS_CLOCK = NOW - timedelta(minutes=10)


# ------------------------------------------------------------------------------------ (2) future clock, write time
@needs_pg
def test_future_source_clock_is_failed_and_never_stored(connect, tmp_path):
    ok = _run(connect, tmp_path, T0, now=T0 + timedelta(seconds=10))
    assert ok["outcome"] == "OK"
    bad = _run(connect, tmp_path, T0 + timedelta(hours=2), now=T0 + timedelta(seconds=70))
    assert bad["outcome"] == "FAILED" and "future source clock" in bad["error"]
    assert _row(connect)["as_of"] == T0                      # never stored
    nxt = _run(connect, tmp_path, T0 + timedelta(seconds=100), now=T0 + timedelta(seconds=130),
               payload={"v": "honest"})
    assert nxt["outcome"] == "OK"                            # not REFUSED_OLDER: the bad clock was not kept
    assert json.loads(bytes(_row(connect)["body"])) == {"v": "honest"}


@needs_pg
def test_skew_within_allowance_is_accepted(connect, tmp_path):
    r = _run(connect, tmp_path, T0 + timedelta(seconds=110), now=T0)
    assert r["outcome"] == "OK"
    r2 = _run(connect, tmp_path, T0 + timedelta(seconds=130), now=T0 + timedelta(seconds=1))
    assert r2["outcome"] == "FAILED" and "future source clock" in r2["error"]


def test_future_clock_error_boundary():
    b = T0
    assert pb.future_clock_error(b + timedelta(seconds=120), b) is None
    assert "future source clock" in pb.future_clock_error(b + timedelta(seconds=121), b)
    assert pb.future_clock_error(None, b) is None


def test_skew_constants_agree():
    assert pb.FUTURE_CLOCK_SKEW_S == rp.FUTURE_CLOCK_SKEW_S == 120


# ------------------------------------------------------------------------------------ (2) future clock, read time
def _row_for(as_of, *, now):
    return {"product_id": "p", "scope_key": "global", "body": json.dumps({"v": 1}).encode(), "etag": "e", "seq": 1,
            "as_of": as_of, "built_at": now, "checked_at": now, "next_refresh_at": now, "stale_after_s": 180,
            "hard_expiry_s": 900, "status": "OK", "reason": None, "schema_version": 1, "source_watermarks": {}}


def test_reader_never_shows_a_future_clock_as_fresh():
    now = NOW
    env = rp.read_product("p", fetch_row=lambda p, s: _row_for(now + timedelta(hours=1), now=now), now=now)
    assert env["status"] == "UNKNOWN" and "source clock is in the future" in env["reason"]
    assert env["data"] is None and env["last_good"] == {"v": 1}
    assert env["age_s"] is not None and env["age_s"] >= 0


def test_reader_clamps_small_skew_and_stays_ok():
    now = NOW
    env = rp.read_product("p", fetch_row=lambda p, s: _row_for(now + timedelta(seconds=60), now=now), now=now)
    assert env["status"] == "OK" and env["age_s"] == 0


# ------------------------------------------------------------------------------------ (1) Home slice failure
def _fake_slices(monkeypatch, state):
    import lib.home_incidents as hi
    import lib.home_priorities_live as hp
    import lib.home_status_live as hs
    import lib.home_v010_api as hv

    sys.path.insert(0, str(ROOT / "scripts"))

    def _status(*a, **k):
        if state["status_fails"]:
            raise RuntimeError("status source down")
        return {"trade_ready": {"verdict": "YES", "computed_at": STATUS_CLOCK.isoformat(), "read_from": "snapshot"}}

    monkeypatch.setattr(hi, "build", lambda q: {"snapshot": {"computed_at": NOW.isoformat()}, "rows": []})
    monkeypatch.setattr(hp, "build", lambda *a, **k: {"rank": {}})
    monkeypatch.setattr(hs, "serve", _status)
    monkeypatch.setattr(hv, "home_gates", lambda *a, **k: {"snapshot": {"computed_at": NOW.isoformat()}})
    real = B.datetime

    class _D(real):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is None else NOW.astimezone(tz)

    monkeypatch.setattr(B, "datetime", _D)


def _home_ctx(connect, tmp_path):
    def _ctx_factory():
        conn = connect()
        conn.autocommit = True

        def q(sql, params=None, fetch="all"):
            import psycopg2.extras
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return cur.fetchone() if fetch == "one" else cur.fetchall()
        return types.SimpleNamespace(code_root=ROOT, portfolio_state_dir=tmp_path, db_query=q, db_query_raising=q,
                                     get_conn=lambda: conn)
    return _ctx_factory


def _home_run(connect, tmp_path, state, i):
    s = pb.CATALOGUE["home"]
    return pb.run_once(s, connect=connect, dry_run=False, now=NOW + timedelta(seconds=30 * (i + 1)),
                       locks=pb.HostLocks(tmp_path / "l"), build_fn=B.build_home,
                       ctx_factory=_home_ctx(connect, tmp_path))


@needs_pg
def test_home_recovers_after_a_slice_failure_instead_of_refused_older(connect, tmp_path, monkeypatch):
    state = {"status_fails": False}
    _fake_slices(monkeypatch, state)
    r1 = _home_run(connect, tmp_path, state, 0)
    assert r1["outcome"] == "OK"
    assert _row(connect, "home")["as_of"] == STATUS_CLOCK

    state["status_fails"] = True
    r2 = _home_run(connect, tmp_path, state, 1)
    row = _row(connect, "home")
    assert r2["outcome"] in ("OK", "UNCHANGED") and row["status"] == "DEGRADED"
    assert row["as_of"] == STATUS_CLOCK, "a failed slice must not move the product clock forward"
    assert row["source_watermarks"]["status"]["clock_carried"] is True

    state["status_fails"] = False
    r3 = _home_run(connect, tmp_path, state, 2)
    assert r3["outcome"] in ("OK", "UNCHANGED"), r3          # on the old code this is REFUSED_OLDER
    assert _row(connect, "home")["status"] == "OK"


@needs_pg
def test_older_build_is_still_refused(connect, tmp_path):
    assert _run(connect, tmp_path, T0, now=T0 + timedelta(seconds=10))["outcome"] == "OK"
    old = _run(connect, tmp_path, T0 - timedelta(minutes=5), now=T0 + timedelta(seconds=20))
    assert old["outcome"] == "REFUSED_OLDER" and old["wrote"] is False
    assert _row(connect)["as_of"] == T0


def _home_marks(monkeypatch, tmp_path, stored, *, fail="status"):
    state = {"status_fails": fail == "status"}
    _fake_slices(monkeypatch, state)

    def q(sql, params=None, fetch="all"):
        return stored if "cc_product_current" in sql else []
    ctx = types.SimpleNamespace(code_root=ROOT, portfolio_state_dir=tmp_path, db_query=q, db_query_raising=q,
                                get_conn=lambda: None)
    return B.build_home(ctx)


def test_failed_slice_with_a_stored_clock_carries_it(monkeypatch, tmp_path):
    stored = {"as_of": STATUS_CLOCK, "source_watermarks": {"status": {"as_of": STATUS_CLOCK.isoformat(),
                                                                       "clock_basis": "source"}}}
    out = _home_marks(monkeypatch, tmp_path, stored)
    assert out["source_watermarks"]["status"] == {"as_of": STATUS_CLOCK.isoformat(), "clock_basis": "source",
                                                  "error": "RuntimeError", "clock_carried": True}
    # LQ-3136 composition: the carried clock keeps its basis, so it still counts as the real source clock
    assert out["source_watermarks"]["_product"]["source_as_of"] == STATUS_CLOCK.isoformat()
    assert out["as_of"] == STATUS_CLOCK.isoformat() and out["status"] == "DEGRADED"


def test_failed_slice_without_a_slice_clock_holds_the_stored_product_clock(monkeypatch, tmp_path):
    stored = {"as_of": STATUS_CLOCK, "source_watermarks": {}}
    out = _home_marks(monkeypatch, tmp_path, stored)
    assert out["source_watermarks"]["status"]["as_of"] is None
    assert out["as_of"] == STATUS_CLOCK.isoformat()
    assert "product clock held at the stored" in out["reason"]


def test_first_build_with_a_failed_slice_has_nothing_to_hold(monkeypatch, tmp_path):
    out = _home_marks(monkeypatch, tmp_path, None)
    assert out["as_of"] == NOW.isoformat() and out["status"] == "DEGRADED"   # no stored row: nothing to protect


def test_no_failed_slice_leaves_as_of_alone(monkeypatch, tmp_path):
    stored = {"as_of": NOW - timedelta(hours=3), "source_watermarks": {}}
    out = _home_marks(monkeypatch, tmp_path, stored, fail=None)
    assert out["as_of"] == STATUS_CLOCK.isoformat() and out["status"] == "OK"


# ------------------------------------------------------------------------ (2) market_risk / risk fallback
def _mr(monkeypatch, stored):
    monkeypatch.setattr(B, "market_risk_projection", lambda ctx: {"state": "evaluated", "tier": "RED"})
    monkeypatch.setattr(B, "home_cio_card", lambda ctx, mr: ({"schema": "HomeCioCard@v1"}, {}))
    q = lambda sql, params=None, fetch="all": stored  # noqa: E731
    return types.SimpleNamespace(db_query=q, db_query_raising=q)


def test_market_risk_without_a_clock_keeps_the_stored_clock_not_the_read_time(monkeypatch):
    out = B.build_market_risk(_mr(monkeypatch, {"as_of": STATUS_CLOCK, "source_watermarks": {}}))
    assert out["as_of"] == STATUS_CLOCK.isoformat() and out["status"] == "DEGRADED"
    assert "kept at the stored" in out["reason"]


def test_market_risk_without_a_clock_and_nothing_stored_has_no_clock(monkeypatch):
    out = B.build_market_risk(_mr(monkeypatch, None))
    assert out["as_of"] is None and out["status"] == "DEGRADED" and "no source time available" in out["reason"]


def test_risk_without_a_clock_keeps_the_stored_clock(monkeypatch):
    import scripts.lib.cio_truth as ct
    monkeypatch.setattr(ct, "risk_payload", lambda db_query: {"truth": {}})
    q = lambda sql, params=None, fetch="all": {"as_of": STATUS_CLOCK, "source_watermarks": {}}  # noqa: E731
    ctx = types.SimpleNamespace(code_root=ROOT, db_query=q, db_query_raising=q)
    out = B.build_risk(ctx)
    assert out["as_of"] == STATUS_CLOCK.isoformat() and out["status"] == "DEGRADED"
    assert out["source_watermarks"]["_product"]["oldest_section_as_of"] is None  # never claims the read time


def test_a_clockless_build_is_a_failed_build_not_a_published_one(tmp_path):
    r = pb.run_once(spec(), connect=None, dry_run=True, locks=pb.HostLocks(tmp_path),
                    build_fn=lambda ctx: {"data": {}, "as_of": None, "source_watermarks": {}}, ctx_factory=_ctx)
    assert r["outcome"] == "FAILED"


# ------------------------------------------------------------------------------- (3) REFUSED_OLDER is visible
def test_cli_exit_is_non_zero_for_refused_older(monkeypatch, capsys):
    monkeypatch.setattr(pb, "run_once", lambda *a, **k: {"outcome": "REFUSED_OLDER"})
    args = types.SimpleNamespace(product="home", timeout=None, rlimit_mb=None, dry_run=True, builder_sha=None)
    assert pb.run_cli(args) == pb.REFUSED_OLDER_EXIT == 3
    assert '"REFUSED_OLDER"' in capsys.readouterr().out


def test_cio_pages_run_once_honours_a_refused_write(tmp_path):
    """cio_pages.run_once used to report OK/UNCHANGED (wrote=True) when write_current refused the older build."""
    import test_cc_products_cio_pages as T

    class RefusingStore(T.FakeStore):
        def write_current(self, *a, **k):
            return {"changed": False, "refused": True, "seq": None, "etag": None}

    events = []
    receipt, store, _ = T._run(tmp_path, T.build_ok, events=events, store=RefusingStore(events))
    assert receipt["outcome"] == "REFUSED_OLDER" and receipt["wrote"] is False
    assert "not published" in receipt["error"]
    assert "log:REFUSED_OLDER" in events and "log:OK" not in events and "log:UNCHANGED" not in events, events


def test_cio_pages_cli_exit_is_non_zero_for_refused_older(monkeypatch, capsys):
    monkeypatch.setattr(cp, "run_once", lambda **k: {"outcome": "REFUSED_OLDER"})
    monkeypatch.setattr(cp, "default_state_root", lambda: Path("/nonexistent"))
    monkeypatch.setattr(cp, "default_ledger_root", lambda: Path("/nonexistent"))
    assert cp.main(["--dry-run"]) == 3


def test_an_unreadable_stored_row_is_no_stored_clock_never_an_invented_one(monkeypatch):
    def boom(sql, params=None, fetch="all"):
        raise RuntimeError("store down")
    monkeypatch.setattr(B, "market_risk_projection", lambda ctx: {"state": "evaluated", "tier": "RED"})
    monkeypatch.setattr(B, "home_cio_card", lambda ctx, mr: ({"schema": "HomeCioCard@v1"}, {}))
    out = B.build_market_risk(types.SimpleNamespace(db_query=boom, db_query_raising=boom))
    assert out["as_of"] is None and out["status"] == "DEGRADED"
    assert B._stored_clock(types.SimpleNamespace(db_query=boom), "home") == (None, {})
    assert B._stored_clock(None, "home") == (None, {})
