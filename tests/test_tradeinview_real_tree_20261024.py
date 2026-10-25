"""Schema proof against an immutable, separately captured production COPY.

This suite never opens a database or production path. CI without the private
copy records an explicit skip; the operator-requested local proof supplies it
through TRADEINVIEW_PRODUCTION_COPY. Positive bar coverage is a separate pinned
synthetic proof: the captured bundle did not collect bars, CIO or stop rows.

COVERS = ["scripts/api_v3_trade_journey.py", "scripts/lib/data_broker/trade_journey.py",
          "scripts/lib/data_broker/trade_calendar.py", "scripts/lib/data_broker/holding_history.py",
          "scripts/lib/data_broker/trade_replay.py", "scripts/lib/data_broker/tradeinview_sources.py",
          "config/schemas/tradeinview_projection_v1.schema.json"]
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import types

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import api_v3_trade_journey as api
from lib.data_broker import trade_calendar as cal
from lib.data_broker import holding_history as hist
from lib.data_broker import trade_journey as tj
from lib.data_broker import trade_replay as replay
from lib.data_broker import tradeinview_sources as src

EXPECTED_SHA = "544bf5124797b52ccf3cb9fce1f74147f135339184b7c5a85115b2c1f9bd61c9"


@pytest.fixture(scope="module")
def copy_bundle():
    name = os.environ.get("TRADEINVIEW_PRODUCTION_COPY")
    if not name:
        pytest.skip("private immutable production COPY not supplied; no live-state fallback")
    path = Path(name)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert before == EXPECTED_SHA
    bundle = json.loads(path.read_bytes())
    assert bundle["database_read_only"] is True
    assert "PER_QUERY_READONLY" in bundle["snapshot_coherence"]
    yield bundle
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.fixture
def pinned(copy_bundle, monkeypatch):
    now = datetime.fromisoformat(copy_bundle["captured_at"])
    monkeypatch.setattr(src, "_SNAPSHOT_CACHE", {})
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz or timezone.utc)
    for module in (cal, hist, tj, replay):
        monkeypatch.setattr(module, "datetime", Clock)
    monkeypatch.setitem(sys.modules, "ohlc_charts", types.SimpleNamespace(
        trade_chart=lambda *_a, **_kw: pytest.fail("provider path reached from COPY proof")))
    return now


def verify_export(name, payload, bundle):
    schema = json.loads((ROOT / "config/schemas/tradeinview_projection_v1.schema.json").read_text())
    Draft202012Validator(schema).validate(payload)
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    assert payload["provider_calls"] == payload["writes"] == 0 and payload["read_only"] is True
    target = os.environ.get("TRADEINVIEW_EXPORT_DIR")
    if target:
        folder = Path(target)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (name + ".json")).write_bytes(encoded + b"\n")
        receipt = {"input_sha256": EXPECTED_SHA, "input_captured_at": bundle["captured_at"],
                   "source_snapshot_coherence": bundle["snapshot_coherence"],
                   "schema": payload["schema"], "bytes": len(encoded),
                   "output_sha256": hashlib.sha256(encoded).hexdigest(),
                   "provider_calls": 0, "writes": 0,
                   "proof_scope": "COPY-derived projection API helper; central API2 routing owned separately by W3"}
        (folder / (name + ".receipt.json")).write_text(json.dumps(receipt, indent=2) + "\n")
    return encoded


def collector(bundle, kind):
    return deepcopy(bundle["snapshots"]["calendar" if kind == "calendar" else "history"])


def test_calendar_endpoint_copy_schema_pages_and_keeps_original_totals(copy_bundle, pinned, monkeypatch):
    monkeypatch.setattr(src, "collect_snapshot", lambda **kw: collector(copy_bundle, kw["kind"]))
    out = api.get_calendar({"month": "2026-10"})
    encoded = verify_export("calendar.actual-populated", out, copy_bundle)
    assert len(encoded) < 500_000
    assert out["events_paging"]["known_total"] > len(out["events"])
    assert out["events_paging"]["total_count"] is None  # original source query was truncated
    second = api.get_calendar({"month": "2026-10", "event_offset": "50"})
    verify_export("calendar.actual-next-page", second, copy_bundle)
    assert out["summary"] == second["summary"] and out["weeks"] == second["weeks"]
    assert not {e["id"] for e in out["events"]} & {e["id"] for e in second["events"]}
    trips, _ = src.normalise_closed(copy_bundle["snapshots"]["calendar"])
    expected = [t for t in trips if (t.get("exit_date") or "").startswith("2026-10-")]
    assert out["summary"]["known_trade_count"] == len(expected)
    day = next(d for d in out["days"] if d["known_trade_count"])
    detail = api.get_calendar({"month": "2026-10", "day": day["date"]})
    verify_export("calendar.actual-day", detail, copy_bundle)


def test_history_endpoint_copy_required_names_accounts_and_original_trip_ids(copy_bundle, pinned, monkeypatch):
    monkeypatch.setattr(src, "collect_snapshot", lambda **kw: collector(copy_bundle, kw["kind"]))
    out = api.get_history({"range": "all", "symbol": "AXTI"})
    verify_export("history.actual-axti", out, copy_bundle)
    by = {r["symbol"]: r for r in out["symbols"]}
    assert {"AXTI", "V", "SCHD", "SCHG", "SPCX", "NFLX"} <= set(by)
    for symbol in ("AXTI", "V", "SCHD", "SCHG", "SPCX", "NFLX"):
        assert by[symbol]["accounts"]
        assert all(a["account_label"] and "_" not in a["account_label"] for a in by[symbol]["accounts"])
    source_trips, _ = hist.history_trips(copy_bundle["snapshots"]["history"])
    actual_ids = {t["trade_id"] for t in source_trips if t["symbol"] == "AXTI"}
    assert {t["trade_id"] for t in out["detail"]["trips"]} == actual_ids
    assert out["detail"]["stats"]["times_held"] is None
    assert any(g["source"] == "Fidelity sync" for g in out["gaps"])


def test_replay_endpoint_copy_missing_uncaptured_bars_is_truthful(copy_bundle, pinned, monkeypatch):
    data = collector(copy_bundle, "history")
    history = hist.build_history(data, {"range": "all", "symbol": "AXTI"}, now=pinned)
    trade = history["detail"]["trips"][0]
    monkeypatch.setattr(src, "collect_snapshot", lambda **kw: deepcopy(data))
    out = api.get_replay({"trade_id": trade["trade_id"], "stored_only": "1", "interval": "1D"})
    verify_export("replay.actual-uncaptured-bars", out, copy_bundle)
    verify_export("replay.actual-history-linked", out, copy_bundle)
    calendar = cal.build_calendar(copy_bundle["snapshots"]["calendar"], {"month": "2026-10"}, now=pinned)
    first_day = next(d for d in calendar["days"] if d["trades"])
    calendar_trip = first_day["trades"][0]
    calendar_replay = api.get_replay({"trade_id": calendar_trip["trade_id"], "stored_only": "1"})
    verify_export("replay.actual-calendar-linked", calendar_replay, copy_bundle)
    assert calendar_replay["trade_id"] == calendar_trip["trade_id"] and calendar_replay["ok"]
    assert out["trade_id"] == trade["trade_id"] and out["symbol"] == "AXTI"
    assert out["kind"] == "none" and out["bars"] == []
    assert out["stats"]["max_gain_pct"] is out["stats"]["max_drawdown_pct"] is None
    assert any("bar coverage" in g["reason"] for g in out["gaps"])


def test_journeys_endpoint_copy_clocks_and_symbols_are_from_captured_inputs(copy_bundle, pinned, monkeypatch):
    data = collector(copy_bundle, "history")
    from lib import portfolio_positions as pp
    monkeypatch.setattr(pp, "load_store", lambda path=None: deepcopy(src.file_document(data, "holdings")))
    class Store:
        def read_projection(self):
            raise ValueError("COPY did not collect this source")
    monkeypatch.setitem(sys.modules, "lib.cio_opportunity_store", types.SimpleNamespace(CIOOpportunityStore=Store))
    monkeypatch.setitem(sys.modules, "lib.identity_registry", types.SimpleNamespace(
        load_cached=lambda: {}, lookup_symbol=lambda *_: None))
    monkeypatch.setattr(tj, "load_opportunity_history", lambda *_a, **_kw: {})
    desk = src.file_document(data, "reentry")
    monkeypatch.setattr(tj, "load_desk_snapshot", lambda path=None: (
        {r["symbol"]: r for r in desk.get("rows") or []}, desk.get("computed_at")))
    def read(sql, params=None):
        for name in ("schwab_round_trips", "trade_closed", "trade_transactions"):
            if "FROM " + name in sql:
                return deepcopy(src.source_rows(data, name))
        raise ValueError("COPY did not collect this source")
    def gather(*_a, **kwargs):
        trades, inputs = original(read, **kwargs)
        inputs["gaps"].append({"input": "COPY coverage", "detail": "CIO, identity, recommendation and observed-stop collections not captured"})
        return trades, inputs
    original = tj.gather
    monkeypatch.setattr(tj, "gather", gather)
    monkeypatch.setattr(tj, "_db_query", lambda: read)
    monkeypatch.setattr(tj, "_cio_prospects", lambda *_a: (None, "COPY_not_collected"))
    trust = {"ingest_receipt": data["files"]["ingest_receipt"],
             "stop_health_receipt": data["files"]["stop_health_receipt"],
             "holdings_written_at": data["files"]["holdings"].get("written_at"),
             "registry": {"status": "missing", "reason": "registered schedule not captured"}}
    monkeypatch.setattr(tj, "_redesign_inputs", lambda now: deepcopy(trust))
    monkeypatch.setattr(tj, "_CACHE", {})
    out = api.get_list({"days": "30", "fresh": "1"})
    verify_export("journeys.actual-captured-inputs", out, copy_bundle)
    expected = {src.symbol(r.get("symbol")) for name in ("schwab_round_trips", "trade_closed")
                for r in src.source_rows(data, name)} | {src.symbol(r.get("symbol")) for r in src.file_document(data, "holdings").get("holdings") or []}
    assert {r["symbol"] for r in out["journeys"]} <= expected
    chips = {c["key"]: c for c in out["freshness_chips"]}
    assert chips["ledger_sync"]["at"] is None  # missing in original copy
    assert chips["stop_monitor"]["at"] == data["files"]["stop_health_receipt"]["document"]["finished_at"]
    assert out["next_broker_sync"]["at"] is None
