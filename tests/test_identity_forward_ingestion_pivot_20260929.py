"""Forward-ingestion identity pivots — NEW writes must carry registry GUIDs.

Backfill fixes history. This file is the going-forward contract: each durable
ingestion pivot that creates research / instrument / thesis / spine / watch /
comms rows must stamp subject_guid (and issuer_guid when known) at write time.

If a producer drops the stamp, these tests fail in CI — do not weaken them.
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

REG = "ecb5ba89-96c6-536c-ba76-89e468a81bf1"
ISSUER = "8dfc96ee-0000-5000-8000-000000000001"


@pytest.fixture()
def registry(monkeypatch: pytest.MonkeyPatch):
    by_sym = {
        "NFLX": REG,
        "SCHD": "11111111-2222-5333-8444-555555555501",
        "AAPL": "11111111-2222-5333-8444-555555555502",
    }

    def _resolve(symbol: str, *, root=None):
        sym = str(symbol or "").upper()
        guid = by_sym.get(sym)
        if not guid:
            return {
                "symbol": sym or None,
                "subject_guid": None,
                "issuer_guid": None,
                "security_guid": None,
                "identity_status": "UNRESOLVED",
                "identity_lookup": "UNRESOLVED",
            }
        return {
            "symbol": sym,
            "subject_guid": guid,
            "issuer_guid": ISSUER,
            "security_guid": guid,
            "identity_status": "CONFIRMED",
            "identity_lookup": "RESOLVED",
        }

    monkeypatch.setattr(
        "scripts.lib.identity_carriage.resolve_security_identity",
        _resolve,
    )
    # Also patch research_identity used by Hermes enqueue/complete.
    def _ri_resolve(_doc, symbol):
        env = _resolve(str(symbol or ""))
        if not env.get("subject_guid"):
            return None
        return {
            "symbol": env["symbol"],
            "subject_guid": env["subject_guid"],
            "issuer_guid": env.get("issuer_guid"),
            "identity_status": "CONFIRMED",
        }

    import importlib
    for name in ("scripts.lib.research_identity", "lib.research_identity"):
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        monkeypatch.setattr(mod, "load_registry", lambda *a, **k: {})
        monkeypatch.setattr(mod, "resolve", _ri_resolve)
    return _resolve


def test_pivot_instrument_record_new_write_stamps(registry):
    from scripts.lib.cio_instrument_record import new_record
    from scripts.lib.identity_carriage import is_registry_guid

    for kind in ("HELD", "WATCH", "EXIT"):
        rec = new_record(kind, "NFLX")
        assert is_registry_guid(rec.get("subject_guid")), kind
        assert rec.get("issuer_guid") == ISSUER
        assert rec["subject_key"] == f"{kind}:NFLX"


def test_pivot_instrument_record_upsert_persists_guid(registry, tmp_path: Path):
    from scripts.lib.cio_instrument_record import InstrumentRecordStore, new_record
    from scripts.lib.identity_carriage import is_registry_guid

    store = InstrumentRecordStore(tmp_path / "cio_instrument_records.jsonl")
    rec = new_record("HELD", "NFLX")
    store.upsert(rec)
    tip = store.load("HELD:NFLX")
    assert tip is not None
    assert is_registry_guid(tip.get("subject_guid"))


def test_pivot_hermes_lifecycle_new_complete_stamps(registry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Enqueue → worker complete: COMPLETED request + result carry GUID."""
    import lib.cio_hermes_research as hr
    from lib.hermes_worker import HermesWorker, StubResearchBackend
    from scripts.lib.identity_carriage import is_registry_guid

    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "cio").mkdir(parents=True)
    monkeypatch.setattr(hr, "REQUEST_PATH", Path("data/cio/hermes_research_requests.jsonl"))
    monkeypatch.setattr(hr, "RESULT_PATH", Path("data/cio/hermes_research_results.jsonl"))
    monkeypatch.setattr(hr, "PROJECTION_PATH", Path("data/cio/hermes_research_projection.json"))

    plan = {
        "plan_id": f"plan_fwd_{uuid4().hex[:8]}",
        "situation_type": "S6_CONCENTRATION_OR_DISPOSITION",
        "symbols": ["NFLX"],
        "thesis_version": "desk@v5",
        "fire_reasons": ["forward_ingestion_pivot"],
    }
    enq = hr.enqueue_research_request(plan, priority="high")
    assert enq.get("created")
    HermesWorker(store=hr, backend=StubResearchBackend(), worker_id="fwd").run_once(limit=1)

    reqs = [json.loads(x) for x in hr.REQUEST_PATH.read_text().splitlines() if x.strip()]
    results = [json.loads(x) for x in hr.RESULT_PATH.read_text().splitlines() if x.strip()]
    completed = [r for r in reqs if r.get("event") == "HERMES_RESEARCH_COMPLETED"]
    assert completed, "no HERMES_RESEARCH_COMPLETED row"
    assert is_registry_guid(completed[-1].get("subject_guid"))
    assert results and is_registry_guid(results[-1].get("subject_guid"))


def test_pivot_hermes_complete_upserts_spine_with_registry_guid(
    registry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """CADI-011 forward path: completed Hermes → spine row with registry UUID."""
    monkeypatch.setenv("CROSS_ASSET_SPINE", "1")
    monkeypatch.delenv("CROSS_ASSET_SHADOW", raising=False)
    (tmp_path / "data" / "cio").mkdir(parents=True)

    from scripts.lib.cross_asset.hooks import notify_hermes_result_completed
    from scripts.lib.cross_asset.security_research_spine import view_for_silo
    from scripts.lib.identity_carriage import is_registry_guid

    out = notify_hermes_result_completed(
        {
            "symbol": "NFLX",
            "result_id": f"rr_fwd_{uuid4().hex[:8]}",
            "research_id": f"res_fwd_{uuid4().hex[:8]}",
            "status": "completed",
            "summary": "Forward pivot: new Hermes complete stamps spine.",
            "confidence": 0.61,
            # Intentionally omit subject_guid — resolve must fill registry UUID.
        },
        root=tmp_path,
    )
    assert out.get("ok") is True
    assert not out.get("skipped")
    v = view_for_silo("NFLX", "options_desk", root=tmp_path)
    assert v.get("found") is True
    assert is_registry_guid(v.get("subject_guid"))
    assert (v.get("thesis") or {}).get("summary", "").startswith("Forward pivot")


def test_pivot_thesis_publish_new_version_stamps(registry, tmp_path: Path):
    from scripts.lib.cio_theses import CIOThesisStore
    from scripts.lib.identity_carriage import is_registry_guid

    store = CIOThesisStore(
        event_path=tmp_path / "theses.jsonl",
        projection_path=tmp_path / "theses_proj.json",
    )
    out = store.publish(
        "Forward thesis for NFLX",
        thesis_id=f"sym-fwd-{uuid4().hex[:8]}",
        linked_symbols=["NFLX"],
        notify=False,
    )
    assert is_registry_guid(out.get("subject_guid"))
    assert out["subject_guid"] in (out.get("linked_subject_guids") or [])


def test_pivot_watchlist_discovery_write_stamps(registry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """proactive_discovery merge path stamps each new/updated watch entry."""
    from scripts.lib.identity_carriage import is_registry_guid, stamp_security_fields

    # Unit the exact merge line used by discovery (avoid full Finviz scrape).
    candidate = {"symbol": "NFLX", "bucket": "research_queue", "score": 1.0}
    old = {}
    merged = {**old, **candidate, "review_status": "active_ai_candidate"}
    merged = stamp_security_fields(merged, symbol="NFLX")
    assert is_registry_guid(merged.get("subject_guid"))

    # Source gate: discovery still calls stamp_security_fields
    root = Path(__file__).resolve().parents[1]
    src = (root / "scripts" / "proactive_discovery.py").read_text(encoding="utf-8")
    assert "stamp_security_fields" in src


def test_pivot_publish_communication_stamps_from_body(registry, monkeypatch: pytest.MonkeyPatch):
    """Comms chokepoint stamps subject on NEW outbound publish."""
    from scripts.lib.comms.adapters import from_plain_message
    from scripts.lib.comms import client as cc

    monkeypatch.setattr(cc, "_db_conn", lambda: None)
    monkeypatch.setattr(
        "scripts.lib.cio_outbound_identity.primary_subject_guid",
        lambda text, **k: REG if "NFLX" in (text or "") else None,
    )
    event = from_plain_message(
        producer="test_forward_pivot",
        body="NFLX research complete — shared spine updated.",
        subject_key="telegram:ops:nflx",
        message_class="ops",
    )
    result = cc.publish_communication(event)
    assert result.ok
    assert event.subject_guid == REG


def test_forward_pivot_source_gates_remain_wired():
    """Grep gate: producers must keep calling stamp helpers (not backfill-only)."""
    root = Path(__file__).resolve().parents[1]
    checks = {
        "scripts/lib/cio_instrument_record.py": "stamp_security_fields",
        "scripts/lib/cio_theses.py": "stamp_security_fields",
        "scripts/lib/cio_hermes_research.py": "resolve_security_identity",
        "scripts/lib/cross_asset/security_research_spine.py": "is_registry_guid",
        "scripts/proactive_discovery.py": "stamp_security_fields",
        "scripts/lib/comms/client.py": "_stamp_subject_identity",
        "scripts/lib/cross_asset/hooks.py": "notify_hermes_result_completed",
    }
    for rel, needle in checks.items():
        text = (root / rel).read_text(encoding="utf-8")
        assert needle in text, f"{rel} missing forward stamp pivot {needle}"
