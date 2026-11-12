"""LQ-20261107-2166 Portfolio G3: Stop Management protection correctness (synthetic fixtures only).

Layer 1 tests scripts/lib/stops_protection.py. Layer 2 loads api_v2 with config/proposals/stops_management_g3.patch
applied to a temp copy (api_v2.py is claim-held by others; the patch is the route owner's fold). Set
G3_PATCH=0 to run layer 2 against the UNPATCHED file: that is the fail-before run.
"""
import datetime as dt
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import stops_protection as sp  # noqa: E402

NOW = dt.datetime(2026, 11, 11, 15, 0, tzinfo=dt.timezone.utc)


def H(sym, acct="schwab_taxable", shares=10, px=100.0, **kw):
    return {"symbol": sym, "account": acct, "shares": shares, "current_price": px, "is_cash": False, **kw}


# ---------- layer 1: pure logic ----------
def test_snapshot_unreadable_is_unknown_not_empty():
    assert sp.grade_snapshot(None, NOW)["state"] == "UNKNOWN"
    assert sp.grade_snapshot([], NOW)["state"] == "UNKNOWN"  # empty has no age: cannot verify


def test_stale_snapshot_is_stale_with_age_never_verified():
    g = sp.grade_snapshot([{"snapshot_at": NOW - dt.timedelta(hours=3)}], NOW)
    assert g["state"] == "STALE" and g["age_s"] == 3 * 3600 and g["broker_verified"] is False
    f = sp.grade_snapshot([{"snapshot_at": (NOW - dt.timedelta(minutes=5)).isoformat()}], NOW)
    assert f["state"] == "OK" and f["broker_verified"] is True


def test_stored_mode_fresh_snapshot_has_no_banner():
    snap = sp.grade_snapshot([{"snapshot_at": NOW - dt.timedelta(minutes=2)}], NOW)
    rows = sp.broker_rows({}, snap, ["schwab"], stored_only=True)
    assert rows[0]["state"] == "OK" and sp.banner_degraded(rows, stored_only=True) is False


def test_stored_mode_stale_is_a_row_not_a_red_banner():
    snap = sp.grade_snapshot([{"snapshot_at": NOW - dt.timedelta(hours=2)}], NOW)
    rows = sp.broker_rows({}, snap, ["schwab"], stored_only=True)
    assert rows[0]["state"] == "STALE" and rows[0]["age_s"] == 7200 and rows[0]["cause"] and rows[0]["owner"]
    assert sp.banner_degraded(rows, stored_only=True) is False


def test_live_failed_read_is_unknown_and_banners():
    snap = sp.grade_snapshot([{"snapshot_at": NOW - dt.timedelta(minutes=2)}], NOW)
    rows = sp.broker_rows({"live_read_ok": False, "error": "timeout"}, snap, ["schwab"], stored_only=False)
    assert rows[0]["state"] == "UNKNOWN" and rows[0]["cause"] == "timeout"
    assert sp.banner_degraded(rows, stored_only=False) is True


def test_floor_and_exemptions():
    assert sp.counted(H("AAA", shares=1, px=100.0)) is True
    assert sp.counted(H("AAA", shares=1, px=99.99)) is False  # listed, not counted
    assert sp.counted(H("SPAXX")) is False and sp.is_exempt(H("X", is_cash=True))
    for sym in ("SPY", "CEFX", "VTSAX", "AAPL"):  # ETF / CEF / mutual fund / stock: NOT exempt
        assert sp.is_exempt(H(sym)) is False
    assert sp.counted(H("NOPX", px=None, shares=5)) is True  # unpriced is counted, never hidden


OKB = [{"broker": "schwab", "state": "OK"}]


def test_rollup_ok_gap_unknown():
    pos = [H("A"), H("B")]
    assert sp.rollup(pos, {("A", "schwab_taxable"): "ACTIVE", ("B", "schwab_taxable"): "ACTIVE"}, OKB)["verdict"] == "OK"
    r = sp.rollup(pos, {("A", "schwab_taxable"): "ACTIVE", ("B", "schwab_taxable"): "GAP"}, OKB)
    assert r["verdict"] == "GAP" and r["gap"] == 1
    r = sp.rollup(pos, {("A", "schwab_taxable"): "ACTIVE", ("B", "schwab_taxable"): "UNKNOWN"}, OKB)
    assert r["verdict"] == "UNKNOWN"
    # all rows active but a broker is unreadable: UNKNOWN blocks OK
    r = sp.rollup(pos, {("A", "schwab_taxable"): "ACTIVE", ("B", "schwab_taxable"): "ACTIVE"}, [{"broker": "schwab", "state": "UNKNOWN"}])
    assert r["verdict"] == "UNKNOWN"
    r = sp.rollup(pos, {("A", "schwab_taxable"): "ACTIVE", ("B", "schwab_taxable"): "ACTIVE"}, [{"broker": "schwab", "state": "STALE"}])
    assert r["verdict"] == "UNKNOWN"


def test_rollup_small_positions_listed_not_counted():
    pos = [H("A"), H("DUST", shares=1, px=5.0)]
    r = sp.rollup(pos, {("A", "schwab_taxable"): "ACTIVE"}, OKB)
    assert r["verdict"] == "OK" and r["counted"] == 1 and r["listed_not_counted"] == 1


def test_pending_activation_counts_as_resting():
    assert "pending_activation" in sp.RESTING_STATES


def test_stop_state():
    assert sp.stop_state(True, sources_ok=False) == "ACTIVE"
    assert sp.stop_state(False, sources_ok=False) == "UNKNOWN"
    assert sp.stop_state(False, sources_ok=True) == "GAP"


# ---------- layer 2: api_v2 with the G3 patch ----------
@pytest.fixture(scope="module")
def api():
    src = ROOT / "scripts" / "api_v2.py"
    tmp = Path(tempfile.mkdtemp(prefix="g3_api_"))
    (tmp / "scripts").mkdir()
    for ent in (ROOT / "scripts").iterdir():  # symlink siblings so __file__-relative lookups still resolve
        if ent.name != "api_v2.py":
            (tmp / "scripts" / ent.name).symlink_to(ent)
    for d in ("config", "docs", "data", "state"):
        if (ROOT / d).exists():
            (tmp / d).symlink_to(ROOT / d)
    shutil.copy(src, tmp / "scripts" / "api_v2.py")
    if os.environ.get("G3_PATCH", "1") != "0":
        subprocess.run(["patch", "-p1", "-s", "-d", str(tmp), "-i", str(ROOT / "config/proposals/stops_management_g3.patch")], check=True)
    spec = importlib.util.spec_from_file_location("api_v2_g3", tmp / "scripts" / "api_v2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
    shutil.rmtree(tmp, ignore_errors=True)


def _setup(api, monkeypatch, holds, *, snap, live=None, confirm=()):
    monkeypatch.setattr(api, "portfolio_holdings", lambda: {"holdings": holds})
    monkeypatch.setattr(api, "_holdings_live_stops", lambda *a, **k: live or {})
    monkeypatch.setattr(api, "_stops_lifecycle_db_snapshot", lambda: snap)

    def dbq(sql, params=None, fetch="all"):
        if "stop_confirmations" in sql:
            return None if confirm is None else list(confirm)
        if "market_regime_snapshots" in sql:
            return {"regime_label": "risk_on", "trend_state": "", "confidence": None}
        return []

    monkeypatch.setattr(api, "_db_query", dbq)
    monkeypatch.setattr(api, "_load_json", lambda *a, **k: {})
    monkeypatch.setattr(api, "_fidelity_monitored_stops_list", lambda *a, **k: {"by_key": {}})


def _fresh():
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=2)


def _snap_row(sym, at):
    return {"symbol": sym, "account": "schwab_taxable", "status": "WORKING", "order_type": "STOP",
            "stop_price": 90.0, "qty": 10, "snapshot_at": at}


def test_api_stored_mode_fresh_snapshot_no_banner(api, monkeypatch):
    snap = {"stops": [_snap_row("A", _fresh())], "raw_rows": [_snap_row("A", _fresh())]}
    _setup(api, monkeypatch, [H("A")], snap=snap)
    out = api._stops_management_api_build({}, stored_only=True)
    assert out["broker_stops_degraded"] is False


def test_api_stored_mode_unreadable_snapshot_is_unknown(api, monkeypatch):
    _setup(api, monkeypatch, [H("A")], snap={"stops": [], "raw_rows": None})
    out = api._stops_management_api_build({}, stored_only=True)
    row = out["rows"][0]
    assert row["stop_state"] == "UNKNOWN"
    assert out["protection_state"]["verdict"] == "UNKNOWN"


def test_api_stale_snapshot_never_broker_verified(api, monkeypatch):
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)
    snap = {"stops": [_snap_row("A", old)], "raw_rows": [_snap_row("A", old)]}
    _setup(api, monkeypatch, [H("A")], snap=snap)
    out = api._stops_management_api_build({}, stored_only=True)
    row = out["rows"][0]
    assert row["broker_verified"] is False and row["stop_age_s"] >= 5 * 3600
    assert out["protection_state"]["verdict"] != "OK"
    assert any(b["state"] == "STALE" for b in out["broker_status_rows"])


def test_api_good_read_no_stop_is_gap(api, monkeypatch):
    live = {"by_key": {}, "fetched_at": "2026-11-11T15:00:00+00:00", "degraded": False, "error": None}
    _setup(api, monkeypatch, [H("A")], snap={"stops": [], "raw_rows": [_snap_row("Z", _fresh())]}, live=live)
    out = api._stops_management_api_build({}, stored_only=False)
    assert out["rows"][0]["stop_state"] == "GAP" and out["protection_state"]["verdict"] == "GAP"


def test_api_unreadable_confirmations_logged_and_unknown(api, monkeypatch, caplog):
    snap = {"stops": [], "raw_rows": [_snap_row("Z", _fresh())]}
    _setup(api, monkeypatch, [H("A")], snap=snap, confirm=None)
    with caplog.at_level("WARNING"):
        out = api._stops_management_api_build({}, stored_only=True)
    assert out["source_failures"].get("stop_confirmations")
    assert out["rows"][0]["stop_state"] == "UNKNOWN"


def test_api_source_exception_is_logged_not_silent(api, monkeypatch, caplog):
    snap = {"stops": [], "raw_rows": [_snap_row("Z", _fresh())]}
    _setup(api, monkeypatch, [H("A")], snap=snap)
    monkeypatch.setattr(api, "_fidelity_monitored_stops_list", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with caplog.at_level("WARNING"):
        out = api._stops_management_api_build({}, stored_only=True)
    assert "fidelity_monitored" in out["source_failures"]
    assert any("unreadable" in r.getMessage() for r in caplog.records)
    assert out["rows"][0]["stop_state"] == "UNKNOWN"
