"""Identity carriage 4/5 — registry GUID on new SECURITY durable writes."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from scripts.lib.identity_carriage import is_registry_guid, stamp_security_fields
from scripts.lib.cio_instrument_record import new_record
from scripts.lib.cross_asset.security_research_spine import (
    empty_spine,
    upsert_from_hermes,
    validate_spine,
    view_for_silo,
)


REG_GUID = "ecb5ba89-96c6-536c-ba76-89e468a81bf1"
ISSUER = "8dfc96ee-0000-5000-8000-000000000001"


@pytest.fixture()
def fake_registry(monkeypatch: pytest.MonkeyPatch):
    def _resolve(symbol: str, *, root=None):
        sym = str(symbol or "").upper()
        if sym == "NFLX":
            return {
                "symbol": "NFLX",
                "subject_guid": REG_GUID,
                "issuer_guid": ISSUER,
                "security_guid": REG_GUID,
                "identity_status": "CONFIRMED",
                "identity_lookup": "RESOLVED",
            }
        return {
            "symbol": sym or None,
            "subject_guid": None,
            "issuer_guid": None,
            "security_guid": None,
            "identity_status": "UNRESOLVED",
            "identity_lookup": "UNRESOLVED",
        }

    monkeypatch.setattr(
        "scripts.lib.identity_carriage.resolve_security_identity",
        _resolve,
    )
    return _resolve


def test_is_registry_guid_rejects_smoke_and_ticker():
    assert is_registry_guid(REG_GUID)
    assert not is_registry_guid("smoke-guid")
    assert not is_registry_guid("NFLX")
    assert not is_registry_guid("HELD:NFLX")
    assert not is_registry_guid("guid-nflx")


def test_instrument_record_new_stamps_guid(fake_registry):
    rec = new_record("HELD", "NFLX")
    assert rec["subject_key"] == "HELD:NFLX"
    assert rec["subject_guid"] == REG_GUID
    assert rec["issuer_guid"] == ISSUER


def test_spine_refuses_smoke_guid(fake_registry, tmp_path: Path):
    ledger = tmp_path / "spine.jsonl"
    bad = upsert_from_hermes(
        "ZZZZ",
        {
            "result_id": "rr_bad",
            "research_id": "res_bad",
            "summary": "no registry",
            "subject_guid": "smoke-guid",
        },
        path=ledger,
    )
    assert bad.get("ok") is False
    assert bad.get("identity_stamp_miss") or "registry" in str(bad.get("error") or "")


def test_spine_upsert_requires_and_stamps_registry_guid(fake_registry, tmp_path: Path):
    ledger = tmp_path / "spine.jsonl"
    wr = upsert_from_hermes(
        "NFLX",
        {
            "result_id": "rr_ok",
            "research_id": "res_ok",
            "summary": "Stamped spine thesis",
            "subject_guid": "smoke-guid",  # must be replaced via registry
            "confidence": 0.5,
        },
        path=ledger,
    )
    assert wr.get("ok") is True
    assert wr["spine"]["subject_guid"] == REG_GUID
    v = view_for_silo("NFLX", "options_desk", path=ledger)
    assert v["found"] and v["subject_guid"] == REG_GUID


def test_validate_spine_rejects_non_uuid_subject_guid():
    sp = empty_spine("NFLX", subject_guid="smoke-guid")
    assert validate_spine(sp)["ok"] is False
    sp2 = empty_spine("NFLX", subject_guid=REG_GUID)
    assert validate_spine(sp2)["ok"] is True


def test_thesis_publish_stamps_linked_symbols(fake_registry, tmp_path: Path):
    from scripts.lib.cio_theses import CIOThesisStore

    store = CIOThesisStore(
        event_path=tmp_path / "theses.jsonl",
        projection_path=tmp_path / "theses_projection.json",
    )
    out = store.publish(
        "NFLX thesis for identity carriage",
        thesis_id=f"sym-{uuid4().hex[:8]}",
        linked_symbols=["NFLX"],
        notify=False,
    )
    assert out.get("subject_guid") == REG_GUID
    assert REG_GUID in (out.get("linked_subject_guids") or [])


def test_stamp_security_fields_drops_junk_guid(fake_registry):
    row = stamp_security_fields({"symbol": "NFLX", "subject_guid": "smoke-guid"}, symbol="NFLX")
    assert row["subject_guid"] == REG_GUID


def test_watchlist_entry_stamp_helper(fake_registry):
    from scripts.lib.identity_carriage import stamp_security_fields
    entry = stamp_security_fields({"symbol": "NFLX", "bucket": "research_queue"}, symbol="NFLX")
    assert entry["subject_guid"] == REG_GUID
