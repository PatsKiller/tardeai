"""LQ-20261107-2166 Portfolio G3: Stop Management protection correctness (synthetic fixtures only).

Layer 1 tests scripts/lib/stops_protection.py (rollup of cio_truth per-row states; LQ-2181). Layer 2 loads api_v2 with config/proposals/stops_management_g3.patch
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


SCH, MOO = "schwab_synth_taxable", "moomoo_synth"


def R(sym, state, *, counted=True, acct=SCH):
    return {"symbol": sym, "account_id": acct, "protection_state": state, "protection": {"state": state, "counted": counted}}


OKB = [{"broker": "schwab", "state": "OK", "age_s": 0}]


# ---------- layer 1: pure logic ----------
def test_snapshot_unreadable_is_unknown_not_empty():
    assert sp.grade_snapshot(None, NOW)["state"] == "UNKNOWN"
    assert sp.grade_snapshot([], NOW)["state"] == "UNKNOWN"


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


def test_broker_with_no_stop_read_source_is_unknown_never_ok_and_not_a_banner():
    """REVIEW-2178b blocker 1: Moomoo/Alpaca were inheriting the Schwab snapshot's OK."""
    snap = sp.grade_snapshot([{"snapshot_at": NOW - dt.timedelta(minutes=1)}], NOW)
    rows = {r["broker"]: r for r in sp.broker_rows({}, snap, ["moomoo", "alpaca", "schwab"], stored_only=True)}
    for b in ("moomoo", "alpaca"):
        assert rows[b]["state"] == "UNKNOWN" and rows[b]["cause"] == "No Stop Read"
    assert rows["schwab"]["state"] == "OK"
    assert sp.banner_degraded(list(rows.values()), stored_only=True) is False  # a standing fact, not a failed read


def test_summary_ok_gap_unknown_precedence():
    ok = [R("A", "PROTECTED"), R("B", "PROTECTED")]
    assert sp.summary(ok, OKB)["verdict"] == "OK"
    assert sp.summary(ok + [R("C", "GAP"), R("D", "UNKNOWN")], OKB)["verdict"] == "GAP"       # GAP beats UNKNOWN
    assert sp.summary(ok + [R("D", "UNKNOWN")], OKB)["verdict"] == "UNKNOWN"
    assert sp.summary(ok, [{"broker": "schwab", "state": "UNKNOWN"}])["verdict"] == "UNKNOWN"   # unread source blocks OK
    assert sp.summary(ok, [{"broker": "schwab", "state": "STALE", "age_s": 7200}])["verdict"] == "UNKNOWN"


def test_summary_unverified_brokers_carry_age_s():
    s = sp.summary([R("A", "PROTECTED")], [{"broker": "schwab", "state": "STALE", "age_s": 7200, "cause": "old"}])
    assert s["unverified_brokers"] == [{"broker": "schwab", "state": "STALE", "age_s": 7200, "cause": "old"}]


def test_summary_exempt_skipped_small_listed_not_counted_and_counts_equal_rows():
    rows = [R("A", "PROTECTED"), R("X", "EXEMPT"), R("DUST", "GAP", counted=False), R("B", "UNKNOWN")]
    s = sp.summary(rows, OKB)
    assert (s["counted"], s["protected"], s["gap"], s["unknown"], s["listed_not_counted"]) == (2, 1, 0, 1, 1)
    assert s["counted"] == sum(1 for r in rows if r["protection_state"] != "EXEMPT" and r["protection"]["counted"])


def test_summary_unreadable_universe_is_unknown_not_ok():
    assert sp.summary(None, OKB)["verdict"] == "UNKNOWN"


def test_summary_never_reuses_the_row_key_protection_state():
    assert "protection_state" not in sp.summary([R("A", "PROTECTED")], OKB)


def test_row_protection_from_the_shared_universe_and_unknown_when_missing():
    idx = sp.attach([R("A", "PROTECTED")])
    assert sp.row_protection(idx, "a", SCH)["protection_state"] == "PROTECTED"
    miss = sp.row_protection(idx, "ZZZ", SCH)
    assert miss["protection_state"] == "UNKNOWN" and miss["protection"]["cause"] == "Not In Position Universe"
    assert sp.row_protection(None, "A", SCH)["protection"]["cause"] == "Stop Read Failed"


def test_no_second_copy_of_the_exemption_or_floor_logic():
    src = (ROOT / "scripts/lib/stops_protection.py").read_text()
    assert "EXEMPT_SYMBOLS" not in src and "MIN_COUNTED_VALUE" not in src and "def is_exempt" not in src


# ---------- layer 2: api_v2 with the G3 patch + the REAL cio_truth.resolve ----------
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



RNOW = dt.datetime(2026, 11, 11, 23, 0, tzinfo=dt.timezone.utc)
CAPTURED = "2026-11-11T22:55:00+00:00"


def H(sym, acct=SCH, value=5000.0, shares=10):
    return {"symbol": sym, "account": acct, "shares": shares, "current_price": value / shares, "price": value / shares,
            "market_value": value, "is_cash": False}


def stop_row(sym, status="pending_activation", acct=SCH):
    return {"account": acct, "symbol": sym, "order_id": f"o-{sym}", "order_type": "STOP", "stop_price": 90.0, "qty": 10,
            "status": status, "captured_at": CAPTURED}


def _fresh():
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=2)


def _snap_row(sym, at, acct=SCH):
    return {"symbol": sym, "account": acct, "status": "WORKING", "order_type": "STOP", "stop_price": 90.0, "qty": 10,
            "snapshot_at": at}


def _setup(api, monkeypatch, tmp_path, holds, *, stops, snap, live=None, confirm=()):
    """stops: stop_last_known rows for cio_truth.resolve (None = unreadable). Real resolve, injected inputs."""
    from lib import cio_truth

    real = cio_truth.resolve

    def resolve(root=None, now=None, *, db_query=None, inputs=None):
        if stops == "RAISE":
            raise RuntimeError("resolve boom")
        return real(tmp_path, RNOW, inputs={
            "holdings": {"as_of": RNOW.isoformat(), "generated_at": RNOW.isoformat(),
                         "holdings": [{k: v for k, v in h.items() if k != "current_price"} | {"day_change": 0} for h in holds]},
            "broker_stops": stops, "stop_fills": {}, "companies": {}, "policy": {}, "planned_stops": {}, "cio_status": {}})

    monkeypatch.setattr(cio_truth, "resolve", resolve)
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


def _fresh_snap():
    return {"stops": [], "raw_rows": [_snap_row("Z", _fresh())]}


def test_api_pending_activation_is_protected_through_the_real_path(api, monkeypatch, tmp_path):
    """REVIEW-2178b blocker 2: pending_activation proven via cio_truth.resolve -> management row -> summary."""
    _setup(api, monkeypatch, tmp_path, [H("SYNA")], stops=[stop_row("SYNA")], snap=_fresh_snap())
    out = api._stops_management_api_build({}, stored_only=True)
    row = out["rows"][0]
    assert row["protection_state"] == "PROTECTED" and "pending" in row["protection"]["reason"].lower()
    assert out["protection_summary"]["verdict"] == "OK" and out["protection_summary"]["protected"] == 1
    assert out["broker_stops_degraded"] is False


def test_api_moomoo_is_unknown_not_gap_and_summary_unknown(api, monkeypatch, tmp_path):
    """blocker 1 through the api: no stop read source -> UNKNOWN 'No Stop Read' in both the row and the broker row."""
    _setup(api, monkeypatch, tmp_path, [H("SYNB", MOO)], stops=[stop_row("SYNA")], snap=_fresh_snap())
    out = api._stops_management_api_build({}, stored_only=True)
    row = out["rows"][0]
    assert row["protection_state"] == "UNKNOWN" and row["protection"]["cause"] == "No Stop Read"
    moo = [b for b in out["broker_status_rows"] if b["broker"] == "moomoo"][0]
    assert moo["state"] == "UNKNOWN" and moo["cause"] == "No Stop Read"
    assert out["protection_summary"]["gap"] == 0 and out["protection_summary"]["verdict"] == "UNKNOWN"


def test_api_stored_mode_fresh_snapshot_no_banner(api, monkeypatch, tmp_path):
    _setup(api, monkeypatch, tmp_path, [H("SYNA")], stops=[stop_row("SYNA")], snap=_fresh_snap())
    assert api._stops_management_api_build({}, stored_only=True)["broker_stops_degraded"] is False


def test_api_unreadable_snapshot_is_a_real_failed_read(api, monkeypatch, tmp_path):
    _setup(api, monkeypatch, tmp_path, [H("SYNA")], stops=[stop_row("SYNA")], snap={"stops": [], "raw_rows": None})
    out = api._stops_management_api_build({}, stored_only=True)
    assert out["broker_stops_degraded"] is True and out["protection_summary"]["verdict"] == "UNKNOWN"
    assert out["protection_summary"]["unverified_brokers"][0]["state"] == "UNKNOWN"


def test_api_stale_snapshot_never_broker_verified_and_summary_unknown_with_age(api, monkeypatch, tmp_path):
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)
    snap = {"stops": [_snap_row("SYNA", old)], "raw_rows": [_snap_row("SYNA", old)]}
    _setup(api, monkeypatch, tmp_path, [H("SYNA")], stops=[stop_row("SYNA")], snap=snap)
    out = api._stops_management_api_build({}, stored_only=True)
    row = out["rows"][0]
    assert row["broker_verified"] is False and row["stop_age_s"] >= 5 * 3600
    s = out["protection_summary"]
    assert s["verdict"] == "UNKNOWN" and s["unverified_brokers"][0]["age_s"] >= 5 * 3600
    assert out["broker_stops_degraded"] is False            # stale is a row, not the red banner


def test_api_good_read_no_stop_is_gap(api, monkeypatch, tmp_path):
    live = {"by_key": {}, "fetched_at": "2026-11-11T15:00:00+00:00", "degraded": False, "error": None}
    _setup(api, monkeypatch, tmp_path, [H("SYNA"), H("SYNC")], stops=[stop_row("SYNA")], snap=_fresh_snap(), live=live)
    out = api._stops_management_api_build({}, stored_only=False)
    by = {r["symbol"]: r for r in out["rows"]}
    assert by["SYNC"]["protection_state"] == "GAP" and out["protection_summary"]["verdict"] == "GAP"


def test_api_summary_counts_equal_the_per_row_states_one_universe(api, monkeypatch, tmp_path):
    hs = [H("SYNA"), H("SYNC"), H("SYNB", MOO), H("DUST", value=50.0)]
    _setup(api, monkeypatch, tmp_path, hs, stops=[stop_row("SYNA")], snap=_fresh_snap())
    out = api._stops_management_api_build({}, stored_only=True)
    s = out["protection_summary"]
    states = [r["protection_state"] for r in out["rows"] if r["symbol"] != "DUST"]
    assert s["counted"] == len(states) == 3 and s["protected"] == states.count("PROTECTED")
    assert s["gap"] == states.count("GAP") and s["unknown"] == states.count("UNKNOWN") and s["listed_not_counted"] == 1


def test_api_no_payload_carries_protection_state_as_both_string_and_object(api, monkeypatch, tmp_path):
    _setup(api, monkeypatch, tmp_path, [H("SYNA")], stops=[stop_row("SYNA")], snap=_fresh_snap())
    out = api._stops_management_api_build({}, stored_only=True)
    assert "protection_state" not in out and isinstance(out["protection_summary"], dict)
    assert all(isinstance(r["protection_state"], str) for r in out["rows"])


def test_api_resolve_failure_is_logged_and_unknown_never_gap(api, monkeypatch, tmp_path, caplog):
    _setup(api, monkeypatch, tmp_path, [H("SYNA")], stops="RAISE", snap=_fresh_snap())
    with caplog.at_level("WARNING"):
        out = api._stops_management_api_build({}, stored_only=True)
    assert "cio_truth.resolve" in out["source_failures"] and out["protection_summary"]["verdict"] == "UNKNOWN"
    assert out["rows"][0]["protection_state"] == "UNKNOWN" and out["broker_stops_degraded"] is True
    assert any("unreadable" in r.getMessage() for r in caplog.records)


def test_api_unreadable_confirmations_logged(api, monkeypatch, tmp_path):
    _setup(api, monkeypatch, tmp_path, [H("SYNA")], stops=[stop_row("SYNA")], snap=_fresh_snap(), confirm=None)
    assert api._stops_management_api_build({}, stored_only=True)["source_failures"].get("stop_confirmations")


def test_api_source_exception_is_logged_not_silent(api, monkeypatch, tmp_path, caplog):
    _setup(api, monkeypatch, tmp_path, [H("SYNA")], stops=[stop_row("SYNA")], snap=_fresh_snap())
    monkeypatch.setattr(api, "_fidelity_monitored_stops_list", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with caplog.at_level("WARNING"):
        out = api._stops_management_api_build({}, stored_only=True)
    assert "fidelity_monitored" in out["source_failures"]
    assert any("unreadable" in r.getMessage() for r in caplog.records)
