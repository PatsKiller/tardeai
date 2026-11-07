"""Defense defects (design defense/v001): D5 oversight None-format, D7 truthful schedules, D1 engine row,
API stale fallback. Synthetic values only (the repo is public)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import api_v2  # noqa: E402
import defense_oversight as dov  # noqa: E402
from lib import defense_engine as de  # noqa: E402


# ── D5 ───────────────────────────────────────────────────────────────────────

def test_oversight_formats_none_without_raising():
    assert dov._signed(None) == "not measured" and dov._signed(1.25) == "+1.2" and dov._signed(True) == "not measured"
    assert dov._k(None) == "value not on file" and dov._k(12500) == "$12K"


def test_oversight_brief_survives_none_sector_reads(tmp_path, monkeypatch):
    rt = tmp_path / "data" / "runtime"
    rt.mkdir(parents=True)
    (rt / "defense_recommendations_latest.json").write_text(json.dumps({"generated_at": "2030-01-07T15:00:00+00:00",
        "groups": {"protect": [{"id": "p1", "title": "WATCH ZZAA", "direction": "hold"}]},
        "stances": [{"symbol": "ZZAA", "account": "a1", "account_label": "Acct A", "stance": "HOLD", "value": None}]}))
    (rt / "sector_momentum_latest.json").write_text(json.dumps({"generated_at": "2030-01-07T15:00:00+00:00",
        "rows": [{"sector": "Technology", "state": "WEAK", "rs20": None, "breadth_pct": 40}],
        "market": {"styles": [{"key": "growth", "state": None, "s20": None}]}}))
    monkeypatch.setattr(dov, "ROOT", tmp_path)
    monkeypatch.setattr(dov, "_constitution", lambda: "synthetic constitution")
    out = json.dumps(dov.build_oversight_brief(), default=str)
    assert "RS20 not measured" in out and "value not on file" in out


# ── D7 ───────────────────────────────────────────────────────────────────────

def test_data_rhythm_schedules_are_the_scheduled_ones(monkeypatch, tmp_path):
    monkeypatch.setattr(api_v2, "PROJECT_ROOT", tmp_path)
    sched = {p["key"]: p["schedule"] for p in api_v2._build_data_rhythm()["producers"]}
    assert sched["recommendations"].startswith("2× daily 10:10 + 17:50")
    assert sched["inverse_stoplights"].startswith("Daily 17:55") and "10:15 +" not in sched["inverse_stoplights"]
    assert sched["cash_alternatives"].startswith("Not scheduled")
    assert sched["gap_checker"].startswith("Not scheduled")


# ── GET /api/v2/defense/engine ───────────────────────────────────────────────

def _doc(age_h: float) -> dict:
    return {"schema": de.SCHEMA, "generated_at": (datetime.now(timezone.utc) - timedelta(hours=age_h)).isoformat(),
            "tier": {"tier": "YELLOW"}}


def _root(tmp_path, doc):
    p = tmp_path / de.OUT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    if doc is not None:
        p.write_text(json.dumps(doc))
    return tmp_path


def test_engine_route_registered():
    assert '"/api/v2/defense/engine": _defense_engine_get' in Path(api_v2.__file__).read_text()


def test_engine_serves_fresh_file(tmp_path, monkeypatch):
    monkeypatch.setattr(api_v2, "PROJECT_ROOT", _root(tmp_path, _doc(0.2)))
    api_v2._DEFENSE_ENGINE_CACHE.clear()
    out = api_v2._defense_engine_get()
    assert out["ok"] and out["served_from"] == "file" and out["stale"] is False


def test_engine_stale_file_is_rebuilt_in_request(tmp_path, monkeypatch):
    import defense_engine_build as deb
    monkeypatch.setattr(api_v2, "PROJECT_ROOT", _root(tmp_path, _doc(5)))
    import lib.defense_stops_slice as dss
    seen = {}
    monkeypatch.setattr(dss, "resolve_live", lambda root: ({"synthetic": True}, None))

    def fake(root, now=None, truth=None):
        seen["truth"] = truth
        return {**_doc(0), "tier": {"tier": "RED"}}
    monkeypatch.setattr(deb, "build", fake)
    api_v2._DEFENSE_ENGINE_CACHE.clear()
    out = api_v2._defense_engine_get()
    assert out["served_from"] == "request_build" and "h old" in out["fallback_reason"]
    assert out["data"]["tier"]["tier"] == "RED" and out["data"]["served"]["served_from"] == "request_build"
    assert seen["truth"] == {"synthetic": True}  # the request build uses live stops, not the 17:55 slice


def test_engine_build_failure_serves_old_file_labelled_stale(tmp_path, monkeypatch):
    import defense_engine_build as deb

    import lib.defense_stops_slice as dss
    monkeypatch.setattr(dss, "resolve_live", lambda root: (None, "synthetic gap"))

    def boom(root, now=None, truth=None):
        raise RuntimeError("synthetic")
    monkeypatch.setattr(api_v2, "PROJECT_ROOT", _root(tmp_path, _doc(5)))
    monkeypatch.setattr(deb, "build", boom)
    api_v2._DEFENSE_ENGINE_CACHE.clear()
    out = api_v2._defense_engine_get()
    assert out["ok"] and out["stale"] is True and "RuntimeError" in out["fallback_reason"]
    monkeypatch.setattr(api_v2, "PROJECT_ROOT", _root(tmp_path / "empty", None))
    api_v2._DEFENSE_ENGINE_CACHE.clear()
    out = api_v2._defense_engine_get()
    assert out["ok"] is False and out["data"] is None


# ── D4: the recommendations job reads holdings DB-first ──────────────────────

def test_recommendations_holdings_come_from_the_holdings_document(tmp_path, monkeypatch):
    import defense_recommendations as dr
    from lib import holdings_document as hd
    monkeypatch.setattr(dr, "ROOT", tmp_path)
    monkeypatch.setattr(hd, "load_document", lambda store, **k: {
        "document_source": "positions_current", "as_of": "2030-01-07T15:00",
        "holdings": [{"symbol": "ZZAA", "shares": 1, "price": 10.0, "account": "a1"}]})
    doc = dr._holdings_document()
    assert [r["symbol"] for r in doc["holdings"]] == ["ZZAA"]
    assert dr.HOLDINGS_SOURCE == {"source": "positions_current", "fallback_reason": None}


def test_recommendations_holdings_fall_back_to_the_file_with_a_reason(tmp_path, monkeypatch):
    import defense_recommendations as dr
    from lib import holdings_document as hd
    store = tmp_path / "data" / "portfolios" / "state" / "holdings.json"
    store.parent.mkdir(parents=True)
    store.write_text(json.dumps({"as_of": "2030-01-06", "holdings": [{"symbol": "ZZOLD"}]}))
    monkeypatch.setattr(dr, "ROOT", tmp_path)
    monkeypatch.setattr(hd, "load_document", lambda store, **k: {"document_fallback_reason": "db disabled"})
    doc = dr._holdings_document()
    assert doc["holdings"] == [{"symbol": "ZZOLD"}]
    assert dr.HOLDINGS_SOURCE == {"source": "holdings_json_fallback", "fallback_reason": "db disabled"}
