"""HOME_DIAGNOSTICS_20261111 — Home v010 Cause/Source/Owner + threshold registry, collector lane and read handler
(LQ-20261107-2149/2150). Synthetic fixtures only: no database, no network, no state root."""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import home_diagnostics as hd  # noqa: E402
from lib import home_v010_api as api  # noqa: E402
import home_diagnostics_collect as collect  # noqa: E402

UTC = timezone.utc
# Wed 2026-11-11 (NYSE open day): 11:00 ET rth, 18:00 ET extended, 23:00 ET closed. EST = UTC-5.
RTH = datetime(2026, 11, 11, 16, 0, tzinfo=UTC)
EXT = datetime(2026, 11, 11, 23, 0, tzinfo=UTC)
CLOSED = datetime(2026, 11, 12, 4, 0, tzinfo=UTC)
SUNDAY = datetime(2026, 11, 15, 17, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def reg():
    return hd.load_registry()


def _w(reg, wid):
    return next(w for w in reg["widgets"] if w["widget_id"] == wid)


def _row(reg, wid, fact, now):
    w = _w(reg, wid)
    return hd.evaluate(w, reg["_sources"][w["source_id"]], fact, now, reg["owners"], reg["causes"])


def _ago(now, s):
    return (now - timedelta(seconds=s)).isoformat()


# ---- registry ------------------------------------------------------------------------------------

def test_registry_has_thirteen_widgets_and_every_row_has_owner_and_cause(reg):
    assert len(reg["widgets"]) == 13
    for w in reg["widgets"]:
        src = reg["_sources"][w["source_id"]]
        assert src["owner"] in reg["owners"] and src["cause_category"] in reg["causes"]
        assert w["refresh_rate"] and w["failure_mode"]


def test_owner_of_a_lane_backed_source_comes_from_lane_registry(reg):
    lanes = {r["lane_id"]: r["owner"] for r in json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]}
    backed = [s for s in reg["_sources"].values() if s.get("owner_lane")]
    assert backed
    for s in backed:
        assert s["owner"] == lanes[s["owner_lane"]]


def test_unknown_lane_or_disagreeing_owner_is_refused(tmp_path):
    base = json.loads((ROOT / "config/home_status_registry.json").read_text())
    bad = copy.deepcopy(base)
    next(s for s in bad["sources"] if s.get("owner_lane"))["owner_lane"] = "no-such-lane"
    p = tmp_path / "r.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(hd.RegistryError, match="not a lane"):
        hd.load_registry(p)
    bad = copy.deepcopy(base)
    next(s for s in bad["sources"] if s.get("owner_lane"))["owner"] = "cio"
    p.write_text(json.dumps(bad))
    with pytest.raises(hd.RegistryError, match="disagrees"):
        hd.load_registry(p)


def test_authority_thresholds_are_reused_not_restated(reg):
    rules = _w(reg, "status_portfolio")["rules"]
    assert rules[0]["threshold_s"] == 1800 and rules[0]["threshold_basis"] == "data_source_authority:positions_store.open"
    assert rules[1]["threshold_s"] == 72 * 3600


def test_unknown_authority_domain_is_refused(tmp_path):
    thr = json.loads((ROOT / "config/home_thresholds.json").read_text())
    thr["widgets"][5]["rules"] = [{"sessions": ["rth", "extended", "closed"], "authority_domain": "nope", "basis": "open"}]
    p = tmp_path / "t.json"
    p.write_text(json.dumps(thr))
    with pytest.raises(hd.RegistryError, match="authority domain"):
        hd.load_registry(thresholds_path=p)


def test_widget_without_session_coverage_or_with_wrong_count_is_refused(reg):
    doc = copy.deepcopy({k: v for k, v in reg.items() if k != "_sources"})
    doc["widgets"][0]["rules"] = doc["widgets"][0]["rules"][:1]
    with pytest.raises(hd.RegistryError, match="cover every session"):
        hd.validate_registry(doc)
    doc = copy.deepcopy({k: v for k, v in reg.items() if k != "_sources"})
    doc["widgets"] = doc["widgets"][:12]
    with pytest.raises(hd.RegistryError, match="13 widgets"):
        hd.validate_registry(doc)


def test_probe_where_must_be_a_literal_comparison():
    doc = json.loads((ROOT / "config/home_status_registry.json").read_text())
    next(s for s in doc["sources"] if s["probe"].get("where"))["probe"]["where"] = "1=1; DROP TABLE x"
    with pytest.raises(hd.RegistryError):
        hd.validate_registry({**doc, "widgets": [], "max_snapshot_age_s": 1, "probe_timeout_s": 1})


# ---- sessions ------------------------------------------------------------------------------------

def test_session_of():
    assert hd.session_of(RTH) == "rth" and hd.session_of(EXT) == "extended"
    assert hd.session_of(CLOSED) == "closed" and hd.session_of(SUNDAY) == "closed"


# ---- evaluate: every status path -----------------------------------------------------------------

def test_ok_stale_and_threshold_boundary(reg):
    ok = _row(reg, "status_portfolio", {"read": "ok", "as_of": _ago(RTH, 600)}, RTH)
    assert ok["state"] == "OK" and ok["age_s"] == 600 and ok["threshold_s"] == 1800 and ok["cause"] is None and ok["cause_category"] is None and ok["why"] is None
    stale = _row(reg, "status_portfolio", {"read": "ok", "as_of": _ago(RTH, 1801)}, RTH)
    assert stale["state"] == "STALE" and stale["cause_category"] == "DATA_STALENESS" and stale["owner"]


def test_unknown_is_never_ok(reg):
    for fact in ({"read": "error", "error": "OperationalError: down"}, {"read": "ok", "as_of": None},
                 {"read": "none", "error": "no store"}, {"read": "weird"}):
        r = _row(reg, "status_portfolio", fact, RTH)
        assert r["state"] != "OK" and r["cause"] and r["why"] and r["source"] and r["owner"]


def test_missing_source_is_no_source_unknown_not_zero(reg):
    r = _row(reg, "validation_gates", {"read": "none", "error": "no validation_gates store"}, RTH)
    # LQ-20261107-2141: the gate store now exists, so the row no longer says NEEDS BACKEND; an unreadable read is still UNKNOWN
    assert r["state"] == "UNKNOWN" and r["cause_category"] == "NO_SOURCE" and r["needs_backend"] is False


def test_validation_gates_row_is_computed_from_the_newest_evaluation(reg):
    """LQ-2141: fresh evaluation -> OK; older than 900 s -> STALE; never the NEEDS BACKEND placeholder."""
    fresh = _row(reg, "validation_gates", {"read": "ok", "as_of": _ago(RTH, 60)}, RTH)
    assert fresh["state"] == "OK" and fresh["needs_backend"] is False
    stale = _row(reg, "validation_gates", {"read": "ok", "as_of": _ago(RTH, 3600)}, RTH)
    assert stale["state"] == "STALE"
    assert _row(reg, "validation_gates", {"read": "ok", "as_of": None}, RTH)["state"] == "UNKNOWN"


def test_timeout_is_timed_out(reg):
    r = _row(reg, "status_portfolio", {"read": "timeout", "error": "TimeoutError: 30s"}, RTH)
    assert r["state"] == "TIMED_OUT" and r["cause_category"] == "READ_TIMEOUT"


def test_future_timestamp_is_unknown_not_fresh(reg):
    r = _row(reg, "status_portfolio", {"read": "ok", "as_of": (RTH + timedelta(hours=2)).isoformat()}, RTH)
    assert r["state"] == "UNKNOWN" and "future" in r["why"]


def test_event_driven_source_is_ok_when_read_works_and_shows_event_age(reg):
    r = _row(reg, "status_alerts", {"read": "ok", "as_of": RTH.isoformat(), "last_event_at": _ago(RTH, 7200)}, RTH)
    assert r["state"] == "OK" and r["threshold_s"] is None and r["age_s"] == 7200


def test_vix_evening_is_off_session_not_stale(reg):
    fact = {"read": "ok", "as_of": _ago(EXT, 4 * 3600)}
    r = _row(reg, "vix_market", fact, EXT)
    assert r["state"] == "OK" and r["off_session"] is True and r["threshold_basis"] == "session_closed" and r["cause_category"] is None and r["session_note"] and r["age_s"] == 4 * 3600
    assert r["in_session_threshold"] == "30 m"
    assert _row(reg, "vix_market", {"read": "ok", "as_of": _ago(RTH, 4 * 3600)}, RTH)["state"] == "STALE"


def test_day_order_stops_are_off_session_after_the_close_but_stale_in_session(reg):
    fact = {"read": "ok", "as_of": _ago(CLOSED, 8 * 3600)}
    assert _row(reg, "action_unprotected_position", fact, CLOSED)["off_session"] is True
    assert _row(reg, "status_orders", fact, CLOSED)["off_session"] is True
    assert _row(reg, "status_orders", {"read": "ok", "as_of": _ago(RTH, 8 * 3600)}, RTH)["state"] == "STALE"


def test_friday_close_read_on_sunday_is_ok_for_quotes_and_a_missed_session_is_stale(reg):
    friday_close = datetime(2026, 11, 13, 21, 0, tzinfo=UTC)
    assert _row(reg, "status_data", {"read": "ok", "as_of": friday_close.isoformat()}, SUNDAY)["state"] == "OK"
    assert _row(reg, "status_data", {"read": "ok", "as_of": _ago(RTH, 3 * 86400 + 1)}, RTH)["state"] == "STALE"
    assert _row(reg, "status_data", {"read": "ok", "as_of": _ago(RTH, 3 * 3600)}, RTH)["state"] == "STALE"


def test_unreadable_source_never_reads_off_session(reg):
    r = _row(reg, "vix_market", {"read": "error", "error": "x"}, EXT)
    assert r["state"] == "UNKNOWN"


# ---- build_snapshot / probe ------------------------------------------------------------------------

def _q_ok(now):
    def q(sql):
        return [(now - timedelta(seconds=60),)]
    return q


def test_snapshot_has_13_rows_with_all_seven_drawer_fields(reg):
    snap = hd.build_snapshot(reg, _q_ok(RTH), RTH)
    assert len(snap["rows"]) == 13 and snap["generated_at"] and snap["session"] == "rth"
    for r in snap["rows"]:
        for k in ("widget", "source", "refresh_rate", "age", "threshold", "state", "failure_mode", "owner"):
            assert k in r
        if r["state"] != "OK":
            assert r["cause"] and r["source"] and r["owner"]
    assert sum(snap["counts"].values()) == 13


def test_probe_is_read_only_select_and_a_failure_does_not_hide_the_others(reg):
    seen = []

    def q(sql):
        seen.append(sql)
        if "stop_last_known" in sql:
            raise RuntimeError("boom")
        if "market_quotes" in sql:
            raise TimeoutError("slow")
        return [(RTH,)]
    snap = hd.build_snapshot(reg, q, RTH)
    assert seen and all(s.lstrip().upper().startswith("SELECT") for s in seen)
    by = {r["widget_id"]: r for r in snap["rows"]}
    assert by["status_orders"]["state"] == "UNKNOWN" and by["status_data"]["state"] == "TIMED_OUT"
    assert by["status_portfolio"]["state"] == "OK"


def test_last_good_survives_a_failed_read(reg):
    first = hd.build_snapshot(reg, _q_ok(RTH), RTH)
    later = RTH + timedelta(minutes=5)

    def q(sql):
        raise RuntimeError("down")
    second = hd.build_snapshot(reg, q, later, previous=first)
    row = next(r for r in second["rows"] if r["widget_id"] == "status_portfolio")
    assert row["state"] == "UNKNOWN" and row["last_good_at"]


# ---- serve / handler ---------------------------------------------------------------------------------

def test_serve_fresh_snapshot_ok(reg):
    snap = hd.build_snapshot(reg, _q_ok(RTH), RTH)
    out = hd.serve(snap, reg, RTH + timedelta(seconds=120))
    assert out["state"] == "OK" and out["snapshot_age_s"] == 120 and len(out["rows"]) == 13


@pytest.mark.parametrize("snap", [None, {}, {"schema": "x"}, "junk"])
def test_serve_missing_or_bad_snapshot_is_all_unknown(reg, snap):
    out = hd.serve(snap, reg, RTH)
    assert out["detail"] == "no_snapshot" and len(out["rows"]) == 13
    assert all(r["state"] == "UNKNOWN" and r["cause_category"] == "COLLECTOR_STALE" for r in out["rows"])


def test_serve_stale_snapshot_is_all_unknown_even_if_rows_said_ok(reg):
    snap = hd.build_snapshot(reg, _q_ok(RTH), RTH)
    assert any(r["state"] == "OK" for r in snap["rows"])
    out = hd.serve(snap, reg, RTH + timedelta(seconds=reg["max_snapshot_age_s"] + 60))
    assert out["detail"] == "collector_stale" and "old" in out["reason"]
    assert all(r["state"] == "UNKNOWN" and r["cause_category"] == "COLLECTOR_STALE" for r in out["rows"])
    assert any(r["last_good_at"] for r in out["rows"])


def test_handler_reads_only_and_writes_nothing(tmp_path, reg):
    out = api.diagnostics(tmp_path, RTH, reg)
    assert out["detail"] == "no_snapshot" and list(tmp_path.iterdir()) == []
    (tmp_path / hd.SNAPSHOT_NAME).write_text(json.dumps(hd.build_snapshot(reg, _q_ok(RTH), RTH)))
    before = (tmp_path / hd.SNAPSHOT_NAME).stat().st_mtime_ns
    assert api.diagnostics(tmp_path, RTH + timedelta(seconds=30), reg)["state"] == "OK"
    assert (tmp_path / hd.SNAPSHOT_NAME).stat().st_mtime_ns == before


def test_handler_with_corrupt_snapshot_is_unknown(tmp_path, reg):
    (tmp_path / hd.SNAPSHOT_NAME).write_text("{not json")
    assert api.diagnostics(tmp_path, RTH, reg)["detail"] == "no_snapshot"


def test_handler_does_not_import_a_database_module():
    src = (ROOT / "scripts/lib/home_v010_api.py").read_text()
    assert "psycopg" not in src and "connect_" not in src


# ---- collector ------------------------------------------------------------------------------------

def test_collector_dry_run_writes_nothing(tmp_path, capsys):
    rc = collect.main(["--state-dir", str(tmp_path)], query=_q_ok(RTH), now=RTH)
    assert rc == 0 and list(tmp_path.iterdir()) == []
    assert "DRY RUN: nothing written" in capsys.readouterr().out


def test_collector_apply_writes_snapshot_atomically(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.lane_last_receipt.write_lane_receipt", lambda *a, **k: None, raising=False)
    rc = collect.main(["--apply", "--state-dir", str(tmp_path)], query=_q_ok(RTH), now=RTH)
    assert rc == 0
    doc = json.loads((tmp_path / hd.SNAPSHOT_NAME).read_text())
    assert doc["schema"] == hd.SCHEMA and len(doc["rows"]) == 13
    assert [p.name for p in tmp_path.iterdir()] == [hd.SNAPSHOT_NAME]


def test_collector_writes_lane_receipt_with_produced_count(tmp_path, monkeypatch):
    got = {}
    monkeypatch.setattr("lib.lane_last_receipt.write_lane_receipt", lambda *a, **k: got.update(args=a, kw=k), raising=False)
    collect.main(["--apply", "--state-dir", str(tmp_path)], query=_q_ok(RTH), now=RTH)
    assert got["args"][0] == "home-diagnostics" and got["kw"]["ok"] is True and got["kw"]["produced_count"] == 13


def test_collector_db_down_exits_1_and_writes_truthful_all_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.lane_last_receipt.write_lane_receipt", lambda *a, **k: None, raising=False)

    def boom(timeout_s):
        raise ConnectionError("no route")
    monkeypatch.setattr(collect, "_db_query_factory", boom)
    rc = collect.main(["--apply", "--state-dir", str(tmp_path)], now=RTH)
    assert rc == 1
    doc = json.loads((tmp_path / hd.SNAPSHOT_NAME).read_text())
    db_rows = [r for r in doc["rows"] if r["state"] != "OK"]
    assert len(doc["rows"]) == 13 and all(r["state"] != "OK" for r in doc["rows"]) and db_rows


def test_collector_invalid_registry_exits_2_and_writes_nothing(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    rc = collect.main(["--apply", "--state-dir", str(tmp_path), "--registry", str(bad)], query=_q_ok(RTH), now=RTH)
    assert rc == 2 and [p.name for p in tmp_path.iterdir()] == ["bad.json"]


# ---- LQ-20261107-2175 rework (REVIEW-2164b C2 / C3) ------------------------------------------------------

def _snap_with_status_data_age(reg, age_s):
    """A snapshot where every db source was written ``age_s`` before collection."""
    def q(sql):
        return [(RTH - timedelta(seconds=age_s),)]
    return hd.build_snapshot(reg, q, RTH)


def test_c2_served_age_and_state_are_recomputed_at_serve_time(reg):
    """Review probe: source 800 s old at collection, status_data limit 900 s -> OK at T, but 1650 s old at T+850."""
    snap = _snap_with_status_data_age(reg, 800)
    at_collect = next(r for r in snap["rows"] if r["widget_id"] == "status_data")
    assert at_collect["state"] == "OK" and at_collect["age_s"] == 800
    for later, true_age in ((850, 1650), (899, 1699)):
        out = hd.serve(snap, reg, RTH + timedelta(seconds=later))
        row = next(r for r in out["rows"] if r["widget_id"] == "status_data")
        assert out["state"] == "OK"  # the snapshot itself is still within its limit
        assert row["age_s"] == true_age and row["state"] == "STALE", row
        assert row["cause_category"] == "DATA_STALENESS" and row["why"]
    assert out["counts"]["STALE"] >= 1 and sum(out["counts"].values()) == 13


def test_c2_collect_time_failures_are_not_regraded(reg):
    def q(sql):
        raise RuntimeError("boom")
    snap = hd.build_snapshot(reg, q, RTH)
    out = hd.serve(snap, reg, RTH + timedelta(seconds=300))
    by_state = {r["widget_id"]: r["state"] for r in out["rows"]}
    assert by_state["status_orders"] == "UNKNOWN" and "OK" not in {r["state"] for r in out["rows"] if r.get("read") == "error"}


def test_c3_states_are_the_spec_vocabulary_and_off_session_is_ok_with_a_basis(reg):
    assert hd.STATES == ("OK", "WARN", "STALE", "UNKNOWN", "TIMED_OUT")
    snap = hd.build_snapshot(reg, _q_ok(EXT), EXT)
    assert {r["state"] for r in snap["rows"]} <= set(hd.STATES)
    assert "rows" in snap and "widgets" not in snap
    r = _row(reg, "vix_market", {"read": "ok", "as_of": _ago(EXT, 3600)}, EXT)
    assert r["state"] == "OK" and r["off_session"] and r["threshold_basis"] == "session_closed"


def test_c3_invalid_registry_still_returns_13_unknown_read_failure_rows(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise hd.RegistryError("synthetic invalid registry")
    monkeypatch.setattr(hd, "load_registry", boom)
    out = api.diagnostics(tmp_path, RTH)
    assert out["state"] == "UNKNOWN" and out["detail"] == "registry_invalid" and len(out["rows"]) == 13
    assert all(r["state"] == "UNKNOWN" and r["cause_category"] == "READ_FAILURE" for r in out["rows"])


def test_d1_orders_after_the_close_is_warn_never_ok_and_vix_stays_ok(reg):
    """Operator D1 (11-11 23:19 ET): an expired DAY stop as the only protection -> Orders WARN, never OK."""
    fact = {"read": "ok", "as_of": _ago(CLOSED, 8 * 3600)}
    for wid in ("status_orders", "action_unprotected_position"):
        r = _row(reg, wid, fact, CLOSED)
        assert r["state"] == "WARN" and r["off_session"] is True and r["cause_category"] == "SESSION_CLOSED", wid
        assert r["cause"] and r["owner"] and "DAY" in r["why"] or "Day" in r["why"]
    assert _row(reg, "vix_market", {"read": "ok", "as_of": _ago(EXT, 3600)}, EXT)["state"] == "OK"
    # in session the same stale stop is STALE, not WARN
    assert _row(reg, "status_orders", {"read": "ok", "as_of": _ago(RTH, 8 * 3600)}, RTH)["state"] == "STALE"


def test_d1_no_source_timeout_and_failed_read_defaults(reg):
    assert _row(reg, "validation_gates", {"read": "none"}, RTH)["state"] == "UNKNOWN"
    assert _row(reg, "status_orders", {"read": "timeout"}, RTH)["state"] == "TIMED_OUT"
    assert _row(reg, "status_orders", {"read": "error", "error": "x"}, RTH)["state"] == "UNKNOWN"
    assert _row(reg, "status_orders", {"read": "ok", "as_of": None}, RTH)["state"] == "UNKNOWN"
