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
    assert ok["status"] == "OK" and ok["age_s"] == 600 and ok["threshold_s"] == 1800 and ok["cause"] is None and ok["cause_category"] is None and ok["why"] is None
    stale = _row(reg, "status_portfolio", {"read": "ok", "as_of": _ago(RTH, 1801)}, RTH)
    assert stale["status"] == "STALE" and stale["cause_category"] == "DATA_STALENESS" and stale["owner"]


def test_unknown_is_never_ok(reg):
    for fact in ({"read": "error", "error": "OperationalError: down"}, {"read": "ok", "as_of": None},
                 {"read": "none", "error": "no store"}, {"read": "weird"}):
        r = _row(reg, "status_portfolio", fact, RTH)
        assert r["status"] != "OK" and r["cause"] and r["why"] and r["source"] and r["owner"]


def test_missing_source_is_no_source_unknown_not_zero(reg):
    r = _row(reg, "validation_gates", {"read": "none", "error": "no validation_gates store"}, RTH)
    assert r["status"] == "UNKNOWN" and r["cause_category"] == "NO_SOURCE" and r["needs_backend"] is True


def test_timeout_is_timed_out(reg):
    r = _row(reg, "status_portfolio", {"read": "timeout", "error": "TimeoutError: 30s"}, RTH)
    assert r["status"] == "TIMED OUT" and r["cause_category"] == "READ_TIMEOUT"


def test_future_timestamp_is_unknown_not_fresh(reg):
    r = _row(reg, "status_portfolio", {"read": "ok", "as_of": (RTH + timedelta(hours=2)).isoformat()}, RTH)
    assert r["status"] == "UNKNOWN" and "future" in r["why"]


def test_event_driven_source_is_ok_when_read_works_and_shows_event_age(reg):
    r = _row(reg, "status_alerts", {"read": "ok", "as_of": RTH.isoformat(), "last_event_at": _ago(RTH, 7200)}, RTH)
    assert r["status"] == "OK" and r["threshold_s"] is None and r["age_s"] == 7200


def test_vix_evening_is_off_session_not_stale(reg):
    fact = {"read": "ok", "as_of": _ago(EXT, 4 * 3600)}
    r = _row(reg, "vix_market", fact, EXT)
    assert r["status"] == "OFF_SESSION" and r["cause_category"] == "SESSION_CLOSED" and r["age_s"] == 4 * 3600
    assert r["in_session_threshold"] == "30 m"
    assert _row(reg, "vix_market", {"read": "ok", "as_of": _ago(RTH, 4 * 3600)}, RTH)["status"] == "STALE"


def test_day_order_stops_are_off_session_after_the_close_but_stale_in_session(reg):
    fact = {"read": "ok", "as_of": _ago(CLOSED, 8 * 3600)}
    assert _row(reg, "action_unprotected_position", fact, CLOSED)["status"] == "OFF_SESSION"
    assert _row(reg, "status_orders", fact, CLOSED)["status"] == "OFF_SESSION"
    assert _row(reg, "status_orders", {"read": "ok", "as_of": _ago(RTH, 8 * 3600)}, RTH)["status"] == "STALE"


def test_friday_close_read_on_sunday_is_ok_for_quotes_and_a_missed_session_is_stale(reg):
    friday_close = datetime(2026, 11, 13, 21, 0, tzinfo=UTC)
    assert _row(reg, "status_data", {"read": "ok", "as_of": friday_close.isoformat()}, SUNDAY)["status"] == "OK"
    assert _row(reg, "status_data", {"read": "ok", "as_of": _ago(RTH, 3 * 86400 + 1)}, RTH)["status"] == "STALE"
    assert _row(reg, "status_data", {"read": "ok", "as_of": _ago(RTH, 3 * 3600)}, RTH)["status"] == "STALE"


def test_unreadable_source_never_reads_off_session(reg):
    r = _row(reg, "vix_market", {"read": "error", "error": "x"}, EXT)
    assert r["status"] == "UNKNOWN"


# ---- build_snapshot / probe ------------------------------------------------------------------------

def _q_ok(now):
    def q(sql):
        return [(now - timedelta(seconds=60),)]
    return q


def test_snapshot_has_13_rows_with_all_seven_drawer_fields(reg):
    snap = hd.build_snapshot(reg, _q_ok(RTH), RTH)
    assert len(snap["widgets"]) == 13 and snap["generated_at"] and snap["session"] == "rth"
    for r in snap["widgets"]:
        for k in ("widget", "source", "refresh_rate", "age", "threshold", "status", "failure_mode", "owner"):
            assert k in r
        if r["status"] != "OK":
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
    by = {r["widget_id"]: r for r in snap["widgets"]}
    assert by["status_orders"]["status"] == "UNKNOWN" and by["status_data"]["status"] == "TIMED OUT"
    assert by["status_portfolio"]["status"] == "OK"


def test_last_good_survives_a_failed_read(reg):
    first = hd.build_snapshot(reg, _q_ok(RTH), RTH)
    later = RTH + timedelta(minutes=5)

    def q(sql):
        raise RuntimeError("down")
    second = hd.build_snapshot(reg, q, later, previous=first)
    row = next(r for r in second["widgets"] if r["widget_id"] == "status_portfolio")
    assert row["status"] == "UNKNOWN" and row["last_good_at"]


# ---- serve / handler ---------------------------------------------------------------------------------

def test_serve_fresh_snapshot_ok(reg):
    snap = hd.build_snapshot(reg, _q_ok(RTH), RTH)
    out = hd.serve(snap, reg, RTH + timedelta(seconds=120))
    assert out["status"] == "ok" and out["snapshot_age_s"] == 120 and len(out["widgets"]) == 13


@pytest.mark.parametrize("snap", [None, {}, {"schema": "x"}, "junk"])
def test_serve_missing_or_bad_snapshot_is_all_unknown(reg, snap):
    out = hd.serve(snap, reg, RTH)
    assert out["status"] == "no_snapshot" and len(out["widgets"]) == 13
    assert all(r["status"] == "UNKNOWN" and r["cause_category"] == "COLLECTOR_STALE" for r in out["widgets"])


def test_serve_stale_snapshot_is_all_unknown_even_if_rows_said_ok(reg):
    snap = hd.build_snapshot(reg, _q_ok(RTH), RTH)
    assert any(r["status"] == "OK" for r in snap["widgets"])
    out = hd.serve(snap, reg, RTH + timedelta(seconds=reg["max_snapshot_age_s"] + 60))
    assert out["status"] == "collector_stale" and "old" in out["reason"]
    assert all(r["status"] == "UNKNOWN" and r["cause_category"] == "COLLECTOR_STALE" for r in out["widgets"])
    assert any(r["last_good_at"] for r in out["widgets"])


def test_handler_reads_only_and_writes_nothing(tmp_path, reg):
    out = api.diagnostics(tmp_path, RTH, reg)
    assert out["status"] == "no_snapshot" and list(tmp_path.iterdir()) == []
    (tmp_path / hd.SNAPSHOT_NAME).write_text(json.dumps(hd.build_snapshot(reg, _q_ok(RTH), RTH)))
    before = (tmp_path / hd.SNAPSHOT_NAME).stat().st_mtime_ns
    assert api.diagnostics(tmp_path, RTH + timedelta(seconds=30), reg)["status"] == "ok"
    assert (tmp_path / hd.SNAPSHOT_NAME).stat().st_mtime_ns == before


def test_handler_with_corrupt_snapshot_is_unknown(tmp_path, reg):
    (tmp_path / hd.SNAPSHOT_NAME).write_text("{not json")
    assert api.diagnostics(tmp_path, RTH, reg)["status"] == "no_snapshot"


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
    assert doc["schema"] == hd.SCHEMA and len(doc["widgets"]) == 13
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
    db_rows = [r for r in doc["widgets"] if r["status"] != "OK"]
    assert len(doc["widgets"]) == 13 and all(r["status"] != "OK" for r in doc["widgets"]) and db_rows


def test_collector_invalid_registry_exits_2_and_writes_nothing(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    rc = collect.main(["--apply", "--state-dir", str(tmp_path), "--registry", str(bad)], query=_q_ok(RTH), now=RTH)
    assert rc == 2 and [p.name for p in tmp_path.iterdir()] == ["bad.json"]
