"""LQ-20261113-3140-r2: the operator's acceptance A1-A4 for the stored-product refresh suppression.

Every PG case runs on the disposable initdb cluster (tests/support/isolated_pg), writes through the REAL
``store_pg.write_current`` upsert and enters through the REAL CLI (``product_builder.run_cli`` / ``cio_pages.main``);
only the build function (the source) and the connection are injected. Synthetic fixtures; no live store, no Valkey.

THE ORDERING RULE (store_pg._UPSERT_SQL), stated once so the tests can pin it:
  always      new.checked_at >= stored.checked_at              (an older in-flight build never overwrites)
  and one of  (a) new.as_of >= stored.as_of                    (valid rows: strict ordering, never relaxed)
              (b) stored.as_of > stored.checked_at + 120 s     (stored clock INVALID: a future source time)
                  AND new.as_of <= new.checked_at + 120 s      (and the replacement's own clock is valid)
              (c) stored.status = DEGRADED AND new.status = OK AND the stored row was left by a FAILED SLICE (r4:
                  reason starts 'slices failed:' - what a real failed build writes, first build or not, aborted
                  slice or held clock; r3 also accepted a clock_carried mark or the 'product clock held at the
                  stored' reason, both kept). A DEGRADED row with a genuine clock keeps strict ordering.

WHAT EACH BUILDER PASSES AS ``as_of`` (pinned below):
  home          min over the live slices' own clocks (since_close excluded)   - a source clock
  market_risk   the Market Risk snapshot's own clock                          - a source clock
  risk          the holdings truth clock                                      - a source clock
  reports       the time the files were verified (read time)                  - a verification clock, by design
  cio.pages     sources_read_at, the child's read time                        - a verification clock, by design
  A source-clock builder never turns the build time into its clock; no clock at all is a FAILED build.
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
from scripts.lib.cc_products import hot_tier  # noqa: E402
from scripts.lib.cc_products import product_builder as pb  # noqa: E402
from scripts.lib.cc_products import read_path as rp  # noqa: E402
from scripts.lib.cc_products import store_pg  # noqa: E402
from test_cc_products_refresh_suppression_lq3140_20261113 import (  # noqa: E402,F401
    NOW, STATUS_CLOCK, _fake_slices, _home_ctx, _home_run)
from test_home_products_builder_20261113 import (  # noqa: E402,F401
    T0, _ctx, _log, _row, cluster, connect, fake_build, needs_pg, spec)

_REAL_PB_RUN_ONCE = pb.run_once   # captured once: a second monkeypatch in one test must not wrap the first
_REAL_CIO_RUN_ONCE = cp.run_once
LIM = dict(stale_after_s=180, hard_expiry_s=900, purge_after_s=3600)


CARRIED = {"status": {"as_of": None, "error": "RuntimeError", "clock_carried": True}}   # what build_home writes (r1)
HELD = "slices failed: status; product clock held at the stored 2026-11-13T19:59:00+00:00"


def _seed(connect, *, as_of, checked_at, status="OK", payload=None, pid="syn.product", scope="global",
          watermarks=None, reason=None):
    """Write a stored row through the real upsert, as an EARLIER build (today's code included) would have."""
    c = connect()
    try:
        out = store_pg.write_current(
            c.cursor(), pid, scope, json.dumps(payload or {"v": "seed"}).encode(), as_of=as_of, built_at=checked_at,
            next_refresh_at=checked_at + timedelta(seconds=60), source_watermarks=watermarks or {}, builder_sha="seed",
            build_ms=1, status=status, **({"reason": reason} if reason else {}), **LIM)
        c.commit()
        return out
    finally:
        c.close()


def _cli(connect, tmp_path, monkeypatch, capsys, *, as_of=None, now, payload=None, status="OK", product="syn.product",
         build_fn=None, ctx_factory=_ctx, s=None):
    """product_builder.run_cli against the isolated cluster. Returns (exit_code, receipt)."""
    if s is not None or product == "syn.product":
        monkeypatch.setitem(pb.CATALOGUE, product, s or spec(product_id=product))
    real = _REAL_PB_RUN_ONCE

    def run_once(spec_, **k):
        k.update(connect=connect, hot=None, now=now, locks=pb.HostLocks(tmp_path / "l"), ctx_factory=ctx_factory,
                 build_fn=build_fn or fake_build(as_of.isoformat(), payload=payload, status=status))
        return real(spec_, **k)

    monkeypatch.setattr(pb, "run_once", run_once)
    monkeypatch.setattr(hot_tier, "HotTier", lambda: None)
    capsys.readouterr()
    rc = pb.run_cli(types.SimpleNamespace(product=product, timeout=None, rlimit_mb=None, dry_run=False,
                                          builder_sha=None))
    return rc, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _cio_payload(stamp="2026-11-12T17:55:00+00:00"):
    return {"portfolio": {"as_of": stamp, "total_usd": 1.0}, "regime": {"as_of": "2026-11-12T17:50:00+00:00"},
            "conflicts": {"as_of": None, "gap": {"reason": "n"}, "findings": []}}


def _cio_build(root, *, db_query, ledger_root=None):
    return _cio_payload()


def _cio_cli(connect, tmp_path, monkeypatch, capsys, build_fn=_cio_build):
    """cio_pages.main against the isolated cluster. Returns (exit_code, receipt)."""
    real = _REAL_CIO_RUN_ONCE
    monkeypatch.setattr(cp, "run_once", lambda **k: real(**{**k, "connect": connect, "hot": None, "root": tmp_path,
                                                            "build_fn": build_fn, "db_query_factory": lambda: None}))
    monkeypatch.setattr(hot_tier, "HotTier", lambda: None)
    capsys.readouterr()
    rc = cp.main([])
    return rc, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _log_rows(connect, pid="syn.product"):
    return [(o, (d or {}).get("receipt_outcome")) for o, d, _ in _log(connect, pid)]


# ================================================================= A1: a failed Home slice recovers and PUBLISHES
@needs_pg
def test_A1_home_recovers_and_publishes_with_a_source_clock_older_than_the_stored_product_clock(
        connect, tmp_path, monkeypatch, capsys):
    """Stored Home row = DEGRADED, as_of 19:59, written while the status slice was down (the clock the old code ran
    ahead to). The slice recovers; its GENUINE clock is 19:50 - older than the stored 19:59. It must publish."""
    _fake_slices(monkeypatch, {"status_fails": False})
    _seed(connect, as_of=NOW - timedelta(minutes=1), checked_at=NOW, status="DEGRADED", pid="home",
          watermarks=CARRIED,
          payload={"seeded": "while status was down"})
    assert _row(connect, "home")["as_of"] == NOW - timedelta(minutes=1) > STATUS_CLOCK
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, product="home", now=NOW + timedelta(seconds=30),
                   build_fn=B.build_home, ctx_factory=_home_ctx(connect, tmp_path))
    assert rc == 0 and rec["outcome"] == "OK" and rec["wrote"] is True, rec
    row = _row(connect, "home")
    assert row["status"] == "OK" and row["as_of"] == STATUS_CLOCK       # the genuine, older source clock, published
    assert _log_rows(connect, "home")[-1] == ("BUILT", "OK")


@needs_pg
def test_A1_r3_a_degraded_row_with_a_GENUINE_clock_is_not_overwritten_by_an_older_ok_build(
        connect, tmp_path, monkeypatch, capsys):
    """r3: a real DEGRADED row (no carried/held marker) keeps strict as_of ordering: as_of must not go backwards."""
    _seed(connect, as_of=T0, checked_at=T0, status="DEGRADED", watermarks={"status": {"as_of": "x", "state": "stale"}})
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 - timedelta(minutes=5),
                   now=T0 + timedelta(seconds=30), payload={"v": "older-source"})
    assert rc == 3 and rec["outcome"] == "REFUSED_OLDER"
    assert _row(connect)["as_of"] == T0


@needs_pg
def test_A1_r3_a_row_held_by_reason_only_still_recovers(connect, tmp_path, monkeypatch, capsys):
    """The held marker is the reason text too (build_home with no prior slice clock writes no clock_carried mark)."""
    _seed(connect, as_of=T0, checked_at=T0, status="DEGRADED", reason=HELD)
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 - timedelta(minutes=5),
                   now=T0 + timedelta(seconds=30))
    assert rc == 0 and rec["outcome"] == "OK" and _row(connect)["as_of"] == T0 - timedelta(minutes=5)


@needs_pg
def test_A1_r4_C1_the_slices_failed_marker_is_a_prefix_not_a_substring(connect, tmp_path, monkeypatch, capsys):
    """REVIEW-3140-r4 C1: builders.py writes the reason as 'slices failed: ...' first. Text that only CONTAINS it is
    not that marker, so a genuine-clock DEGRADED row with such a reason keeps strict as_of ordering."""
    _seed(connect, as_of=T0, checked_at=T0, status="DEGRADED", reason="no source clock; slices failed: status")
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 - timedelta(minutes=5),
                   now=T0 + timedelta(seconds=30), payload={"v": "older-source"})
    assert rc == 3 and rec["outcome"] == "REFUSED_OLDER"
    assert _row(connect)["as_of"] == T0


@needs_pg
def test_A1_r3_non_object_watermarks_do_not_error_and_do_not_count_as_carried(connect, tmp_path, monkeypatch, capsys):
    _seed(connect, as_of=T0, checked_at=T0, status="DEGRADED", watermarks={"a": "clock_carried", "b": [1],
                                                                       "c": {"clock_carried": False}})
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 - timedelta(minutes=5),
                   now=T0 + timedelta(seconds=30))
    assert rc == 3 and rec["outcome"] == "REFUSED_OLDER"


# ---------------- r4 (REVIEW-3144c): what a REAL failed build leaves, first build included, must recover --------
@needs_pg
def test_A1_r4_P2_a_first_ever_build_with_a_failed_slice_recovers_and_publishes(connect, tmp_path, monkeypatch):
    """P2 (REVIEW-3144c). Nothing was stored before the failed build, so no slice clock existed to carry: the row a
    FIRST build leaves is DEGRADED, reason 'slices failed: ...', as_of AHEAD of the genuine status clock. The
    recovery's genuine clock (STATUS_CLOCK) is older; it must publish. r3 refused it, r2 and r4 publish."""
    state = {"status_fails": True}
    _fake_slices(monkeypatch, state)
    first = _home_run(connect, tmp_path, state, 0)
    row = _row(connect, "home")
    assert row["status"] == "DEGRADED" and row["reason"].startswith("slices failed:"), (first, row["reason"])
    assert row["as_of"] > STATUS_CLOCK                     # stamped with the read time: nothing genuine to carry
    assert not any((w or {}).get("clock_carried") is True                       # and nothing marked as carried
                   for w in row["source_watermarks"].values() if isinstance(w, dict))
    state["status_fails"] = False
    rec = _home_run(connect, tmp_path, state, 1)
    assert rec["outcome"] in ("OK", "UNCHANGED"), rec       # r3: REFUSED_OLDER
    row = _row(connect, "home")
    assert row["status"] == "OK" and row["as_of"] == STATUS_CLOCK


@needs_pg
def test_A1_r4_P3_a_degraded_row_left_by_the_deployed_code_recovers(connect, tmp_path, monkeypatch):
    """P3 (REVIEW-3144c). The currently served, pre-r1 code writes a failed slice as DEGRADED with as_of = the read
    time, reason 'slices failed: status', and NO clock_carried mark. That already-affected row is exactly what
    recovery must publish over; r3 refused it, r2 and r4 publish."""
    state = {"status_fails": False}
    _fake_slices(monkeypatch, state)
    assert _home_run(connect, tmp_path, state, 0)["outcome"] == "OK"
    c = connect()
    try:
        c.cursor().execute(                                # the row shape the deployed code leaves
            "UPDATE cc_product_current SET status='DEGRADED', as_of=%s, reason='slices failed: status', "
            "source_watermarks='{}'::jsonb WHERE product_id='home'", (STATUS_CLOCK + timedelta(minutes=9),))
        c.commit()
    finally:
        c.close()
    rec = _home_run(connect, tmp_path, state, 1)
    assert rec["outcome"] in ("OK", "UNCHANGED"), rec       # r3: REFUSED_OLDER
    assert _row(connect, "home")["status"] == "OK"


@needs_pg
@pytest.mark.parametrize("shape", ["carried_marker", "held_reason", "slices_failed_reason"])
def test_A1_r4_clause_c_is_a_recovery_exemption_an_older_DEGRADED_build_is_still_refused(
        connect, tmp_path, monkeypatch, capsys, shape):
    """REVIEW-3144c's surviving mutant: clause (c) must require the NEW build to be OK. A DEGRADED build with an
    older clock is not a recovery, whatever marker the stored row has — including the r4 'slices failed:' reason."""
    kw = {"carried_marker": dict(watermarks=CARRIED), "held_reason": dict(reason=HELD),
          "slices_failed_reason": dict(reason="slices failed: status")}[shape]
    _seed(connect, as_of=T0, checked_at=T0, status="DEGRADED", **kw)
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 - timedelta(minutes=5), status="DEGRADED",
                   now=T0 + timedelta(seconds=30))
    assert rc == 3 and rec["outcome"] == "REFUSED_OLDER", (shape, rec)
    assert _row(connect)["as_of"] == T0


@needs_pg
def test_A1_a_degraded_build_with_an_older_clock_is_still_refused(connect, tmp_path, monkeypatch, capsys):
    """The recovery exemption is for an OK build over a DEGRADED row only: a degraded build is not a recovery."""
    _seed(connect, as_of=T0, checked_at=T0, status="DEGRADED")
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 - timedelta(minutes=5), status="DEGRADED",
                   now=T0 + timedelta(seconds=30))
    assert rc == 3 and rec["outcome"] == "REFUSED_OLDER"
    assert _row(connect)["as_of"] == T0


@needs_pg
def test_A1_an_ok_build_does_not_replace_an_ok_row_with_an_older_clock(connect, tmp_path, monkeypatch, capsys):
    """Valid rows keep strict ordering: the exemption does not fire when the stored row is OK."""
    _seed(connect, as_of=T0, checked_at=T0, status="OK")
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 - timedelta(minutes=5),
                   now=T0 + timedelta(seconds=30))
    assert rc == 3 and rec["outcome"] == "REFUSED_OLDER" and _row(connect)["as_of"] == T0


@needs_pg
def test_A1_an_older_in_flight_ok_build_cannot_use_the_degraded_exemption(connect, tmp_path, monkeypatch, capsys):
    """Even over a DEGRADED row, a build that is older by BUILD TIME is an in-flight loser."""
    _seed(connect, as_of=T0, checked_at=T0 + timedelta(seconds=60), status="DEGRADED", watermarks=CARRIED)
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 - timedelta(minutes=5),
                   now=T0 + timedelta(seconds=30))
    assert rc == 3 and rec["outcome"] == "REFUSED_OLDER"


# ============================================ A2: a future as_of neither appears fresh nor blocks updates for good
@needs_pg
def test_A2_recovery_from_an_already_stored_future_clock(connect, tmp_path, monkeypatch, capsys):
    """The stored row already carries a future as_of (written by today's code, before the guard). The next honest
    build must publish: the old ``EXCLUDED.as_of >= stored.as_of`` predicate refused it until the wall clock caught up."""
    _seed(connect, as_of=T0 + timedelta(hours=2), checked_at=T0)
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 + timedelta(seconds=30), payload={"v": "honest"},
                   now=T0 + timedelta(seconds=40))
    assert rc == 0 and rec["outcome"] == "OK" and rec["wrote"] is True, rec
    row = _row(connect)
    assert row["as_of"] == T0 + timedelta(seconds=30) and json.loads(bytes(row["body"])) == {"v": "honest"}


@needs_pg
def test_A2_a_future_clock_is_never_stored_by_the_cli_and_does_not_block_the_next_build(
        connect, tmp_path, monkeypatch, capsys):
    ok, _ = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0, now=T0 + timedelta(seconds=10))
    assert ok == 0
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 + timedelta(hours=2),
                   now=T0 + timedelta(seconds=70))
    assert rc == 1 and rec["outcome"] == "FAILED" and "future source clock" in rec["error"]
    assert _row(connect)["as_of"] == T0
    rc2, rec2 = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 + timedelta(seconds=100),
                     now=T0 + timedelta(seconds=130), payload={"v": "after"})
    assert rc2 == 0 and rec2["outcome"] == "OK"


@needs_pg
def test_A2_the_reader_does_not_show_a_stored_future_clock_as_fresh(connect):
    _seed(connect, as_of=T0 + timedelta(hours=2), checked_at=T0)
    env = rp.read_product("syn.product", fetch_row=lambda p, s: _row(connect, p, s), now=T0 + timedelta(seconds=30))
    assert env["status"] == "UNKNOWN" and "source clock is in the future" in env["reason"]
    assert env["data"] is None and env["last_good"] == {"v": "seed"}


@needs_pg
def test_A2_a_replacement_must_itself_have_a_valid_clock(connect):
    """Straight through the upsert: a stored future clock is replaceable only by a VALID clock."""
    _seed(connect, as_of=T0 + timedelta(hours=2), checked_at=T0)
    c = connect()
    try:
        bad = store_pg.write_current(
            c.cursor(), "syn.product", "global", b'{"v":"bad"}', as_of=T0 + timedelta(hours=1),
            built_at=T0 + timedelta(seconds=10), next_refresh_at=T0 + timedelta(minutes=2),
            source_watermarks={}, builder_sha="x", build_ms=1, **LIM)
        assert bad["refused"] is True                               # 1 h ahead is still a future clock
        good = store_pg.write_current(
            c.cursor(), "syn.product", "global", b'{"v":"good"}', as_of=T0 + timedelta(seconds=5),
            built_at=T0 + timedelta(seconds=10), next_refresh_at=T0 + timedelta(minutes=2),
            source_watermarks={}, builder_sha="x", build_ms=1, **LIM)
        assert good["refused"] is False
        c.commit()
    finally:
        c.close()


# ===================================== A3: older in-flight cannot overwrite; a valid clock correction can; no relaxing
@needs_pg
def test_A3_an_older_in_flight_build_cannot_overwrite_a_newer_result(connect, tmp_path, monkeypatch, capsys):
    """Build A starts first, B starts later and finishes first; A finishes last with the OLDER build time."""
    rc_b, _ = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 + timedelta(seconds=50), payload={"v": "B"},
                   now=T0 + timedelta(seconds=60))
    assert rc_b == 0
    rc_a, rec_a = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 + timedelta(seconds=20),
                       payload={"v": "A"}, now=T0 + timedelta(seconds=30))
    assert rc_a == 3 and rec_a["outcome"] == "REFUSED_OLDER"
    assert json.loads(bytes(_row(connect)["body"])) == {"v": "B"}


@needs_pg
def test_A3_an_in_flight_build_older_by_build_time_is_refused_even_with_a_newer_source_clock(
        connect, tmp_path, monkeypatch, capsys):
    _seed(connect, as_of=T0 + timedelta(seconds=50), checked_at=T0 + timedelta(seconds=60))
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 + timedelta(seconds=55),
                   now=T0 + timedelta(seconds=30), payload={"v": "late"})
    assert rc == 3 and rec["outcome"] == "REFUSED_OLDER"
    assert json.loads(bytes(_row(connect)["body"])) == {"v": "seed"}


@needs_pg
def test_A3_an_older_in_flight_build_cannot_replace_an_invalid_future_row_either(connect, tmp_path, monkeypatch,
                                                                                capsys):
    _seed(connect, as_of=T0 + timedelta(hours=2), checked_at=T0 + timedelta(seconds=60))
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 + timedelta(seconds=20),
                   now=T0 + timedelta(seconds=30), payload={"v": "late"})
    assert rc == 3 and rec["outcome"] == "REFUSED_OLDER"


@needs_pg
def test_A3_a_valid_clock_correction_can_publish(connect, tmp_path, monkeypatch, capsys):
    """The stored clock ran ahead (invalid: more than 120 s past its own build); the corrected, older clock publishes."""
    _seed(connect, as_of=T0 + timedelta(minutes=30), checked_at=T0)
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 + timedelta(seconds=15),
                   now=T0 + timedelta(seconds=20), payload={"v": "corrected"})
    assert rc == 0 and rec["outcome"] == "OK"
    assert _row(connect)["as_of"] == T0 + timedelta(seconds=15)


@needs_pg
@pytest.mark.parametrize("ahead_s,replaceable", [(120, False), (121, True)])
def test_A3_the_discriminator_boundary_is_the_skew_allowance(connect, tmp_path, monkeypatch, capsys, ahead_s,
                                                             replaceable):
    """stored.as_of > stored.checked_at + 120 s is invalid. Exactly 120 s ahead is a valid row: never relaxed."""
    _seed(connect, as_of=T0 + timedelta(seconds=ahead_s), checked_at=T0)
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 + timedelta(seconds=10),
                   now=T0 + timedelta(seconds=20))
    assert (rc, rec["outcome"]) == ((0, "OK") if replaceable else (3, "REFUSED_OLDER"))


def test_A3_the_three_skew_constants_agree():
    assert store_pg.FUTURE_CLOCK_SKEW_S == pb.FUTURE_CLOCK_SKEW_S == rp.FUTURE_CLOCK_SKEW_S == 120


# ============================================ A4: refused = non-zero + FAILED receipt; UNCHANGED stays distinct
@needs_pg
def test_A4_a_refused_write_is_a_nonzero_exit_and_a_failed_build_log_receipt(connect, tmp_path, monkeypatch, capsys):
    _seed(connect, as_of=T0, checked_at=T0)
    before = _row(connect)
    rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0 - timedelta(minutes=5),
                   now=T0 + timedelta(seconds=30))
    assert rc == 3 and rec["outcome"] == "REFUSED_OLDER" and rec["wrote"] is False and rec["error"]
    last = _log(connect)[-1]
    assert last[0] == "FAILED" and last[1]["receipt_outcome"] == "REFUSED_OLDER"
    after = _row(connect)
    assert (after["seq"], after["as_of"], after["etag"]) == (before["seq"], before["as_of"], before["etag"])


@needs_pg
def test_A4_cio_pages_refused_write_is_a_nonzero_exit_and_a_failed_build_log_receipt(connect, tmp_path, monkeypatch,
                                                                                    capsys):
    ahead = datetime.now(timezone.utc) + timedelta(minutes=10)         # a NEWER, valid stored result
    _seed(connect, as_of=ahead, checked_at=ahead, pid="cio.pages", payload={"v": "newer"})
    rc, rec = _cio_cli(connect, tmp_path, monkeypatch, capsys)
    assert rc == 3 and rec["outcome"] == "REFUSED_OLDER" and rec["wrote"] is False
    last = _log(connect, "cio.pages")[-1]
    assert last[0] == "FAILED" and last[1]["receipt_outcome"] == "REFUSED_OLDER"
    assert json.loads(bytes(_row(connect, "cio.pages")["body"])) == {"v": "newer"}


@needs_pg
def test_A4_unchanged_is_a_distinct_outcome_exit_zero_and_does_not_move_the_source_clock(
        connect, tmp_path, monkeypatch, capsys):
    """Same body, same SOURCE clock, built later: UNCHANGED (row + exit 0). as_of stays the source clock; it never
    becomes the build or request time. checked_at is what moves."""
    rc1, r1 = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0, now=T0 + timedelta(seconds=10))
    assert (rc1, r1["outcome"]) == (0, "OK")
    rc2, r2 = _cli(connect, tmp_path, monkeypatch, capsys, as_of=T0, now=T0 + timedelta(minutes=5))
    assert (rc2, r2["outcome"], r2["wrote"]) == (0, "UNCHANGED", True)
    assert _log_rows(connect)[-1] == ("UNCHANGED", None)               # its own row word, not FAILED/REFUSED_OLDER
    row = _row(connect)
    assert row["as_of"] == T0 and row["as_of"] != T0 + timedelta(minutes=5)
    c = connect()
    try:
        cur = c.cursor()
        cur.execute("SELECT checked_at, built_at FROM cc_product_current WHERE product_id='syn.product'")
        checked, built = cur.fetchone()
    finally:
        c.close()
    assert checked == T0 + timedelta(minutes=5) and built == T0 + timedelta(seconds=10) and row["seq"] == 1


@needs_pg
def test_A4_unchanged_home_keeps_the_min_slice_clock_not_the_build_time(connect, tmp_path, monkeypatch, capsys):
    _fake_slices(monkeypatch, {"status_fails": False})
    for i in (1, 2):
        rc, rec = _cli(connect, tmp_path, monkeypatch, capsys, product="home", now=NOW + timedelta(minutes=i),
                       build_fn=B.build_home, ctx_factory=_home_ctx(connect, tmp_path))
        assert rc == 0, rec
    assert rec["outcome"] == "UNCHANGED"
    assert _row(connect, "home")["as_of"] == STATUS_CLOCK != NOW


@needs_pg
def test_A4_cio_pages_unchanged_is_exit_zero_and_as_of_is_its_own_read_time_by_design(connect, tmp_path, monkeypatch,
                                                                                    capsys):
    """cio.pages' as_of IS sources_read_at (the verification clock, see product_clock): an unchanged body moves it to
    the new read time. It is the child's real read time - never the payload's section clocks, never ``now``."""
    t_a = datetime.now(timezone.utc)
    rc1, _ = _cio_cli(connect, tmp_path, monkeypatch, capsys)
    first = _row(connect, "cio.pages")
    assert rc1 == 0 and t_a <= first["as_of"] <= datetime.now(timezone.utc)
    rc2, r2 = _cio_cli(connect, tmp_path, monkeypatch, capsys)
    second = _row(connect, "cio.pages")
    assert (rc2, r2["outcome"]) == (0, "UNCHANGED") and second["seq"] == first["seq"]
    assert second["as_of"] >= first["as_of"] and second["as_of"] <= datetime.now(timezone.utc)
    assert second["as_of"].isoformat() != "2026-11-12T17:55:00+00:00"   # not a payload section clock
    assert _log_rows(connect, "cio.pages")[-1] == ("UNCHANGED", None)


# ---------------------------------------------- what each builder passes as as_of (pinned, no DB)
def test_A4_pin_market_risk_passes_the_snapshot_clock_not_the_read_time(monkeypatch):
    snap = "2026-11-13T19:41:00+00:00"
    monkeypatch.setattr(B, "market_risk_projection", lambda ctx: {"state": "evaluated", "as_of": snap})
    monkeypatch.setattr(B, "home_cio_card", lambda ctx, mr: ({"schema": "HomeCioCard@v1"}, {}))
    q = lambda sql, params=None, fetch="all": None  # noqa: E731
    out = B.build_market_risk(types.SimpleNamespace(db_query=q, db_query_raising=q))
    assert out["as_of"] == snap and out["source_watermarks"]["_product"]["clock_rule"] == "market_risk_snapshot.as_of"
    assert out["as_of"] != out["source_watermarks"]["_product"]["sources_read_at"]


def test_A4_pin_risk_passes_the_holdings_truth_clock_not_the_read_time(monkeypatch):
    import scripts.lib.cio_truth as ct
    truth = "2026-11-13T19:30:00+00:00"
    monkeypatch.setattr(ct, "risk_payload", lambda db_query: {"truth": {"as_of": truth}})
    q = lambda sql, params=None, fetch="all": None  # noqa: E731
    out = B.build_risk(types.SimpleNamespace(code_root=ROOT, db_query=q, db_query_raising=q))
    assert out["as_of"] == truth and out["source_watermarks"]["_product"]["clock_rule"] == "cio_truth.truth.as_of"
    assert out["as_of"] != out["source_watermarks"]["_product"]["sources_read_at"]


def test_A4_pin_home_passes_the_oldest_live_slice_clock_not_the_read_time(monkeypatch, tmp_path):
    _fake_slices(monkeypatch, {"status_fails": False})
    q = lambda sql, params=None, fetch="all": None  # noqa: E731
    out = B.build_home(types.SimpleNamespace(code_root=ROOT, portfolio_state_dir=tmp_path, db_query=q,
                                             db_query_raising=q, get_conn=lambda: None))
    assert out["as_of"] == STATUS_CLOCK.isoformat() != NOW.isoformat()


def test_A4_pin_the_verification_clock_builders_say_so(monkeypatch):
    """cio.pages and reports pass the read time on purpose; the watermarks name the rule (no hidden source time)."""
    _, marks = cp.product_clock(_cio_payload(), NOW)
    assert marks["_product"]["as_of_rule"] == "sources_read_at"
    assert cp.product_clock(_cio_payload(), NOW)[0] == NOW.isoformat()
