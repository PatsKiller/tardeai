"""R18-DATA: store registry, Aegis/Advisory contract, operator product, no purge."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.canonical_store_registry import load_json_store, registry, resolve_store
from scripts.lib.cio_operator_product import build_operator_product, render_human, unavailable
from scripts.lib.data_integrity_audit import holdings_freshness, instrument_audit
from scripts.lib.data_store_inventory import inventory, writer_reader_graph
from scripts.lib.instrument_normalize import classify_instrument
from scripts.lib.ops_health_routing import classify_message
from scripts.lib.tradeai_record_envelope import entity_ref, envelope
from scripts.lib.r17_checkpoint_reconciliation import reconcile_store
import aegis_evening_packet as pkt


def test_registry_resolves_canonical_not_stale_filename(tmp_path: Path) -> None:
    (tmp_path / "data/cio").mkdir(parents=True)
    brief = {"schema": "CIOInvestmentProduct@v1", "recommendations": [{"symbol": "NVDA", "recommended_action": "WATCH", "title": "NVDA watch", "rationale": "thesis"}]}
    (tmp_path / "data/cio/cio_investment_brief.json").write_text(json.dumps(brief))
    loc = load_json_store("cio.product.current", root=tmp_path)
    assert loc["available"] is True
    assert loc["data"]["schema"] == "CIOInvestmentProduct@v1"
    missing = resolve_store("cio.product.current", root=tmp_path / "empty")
    assert missing["exists"] is False
    assert "cio_investment_product_latest.json" in str((registry()["stores"]["cio.product.current"].get("aliases")))


def test_aegis_finds_brief_when_stale_filename_absent(tmp_path, monkeypatch) -> None:
    (tmp_path / "data/cio").mkdir(parents=True)
    (tmp_path / "data/runtime").mkdir(parents=True)
    brief = {"schema": "CIOInvestmentProduct@v1", "as_of": "2026-08-26T00:00:00+00:00",
             "recommendations": [{"symbol": "CACI", "recommended_action": "REVIEW", "title": "CACI conviction", "rationale": "Hermes up"}]}
    (tmp_path / "data/cio/cio_investment_brief.json").write_text(json.dumps(brief))
    (tmp_path / "data/runtime/advisory_desk_latest.json").write_text(json.dumps({"ok": True, "rows": []}))
    monkeypatch.setattr(pkt, "ROOT", tmp_path)
    packet = pkt.build_packet()
    assert packet["cio"]["available"] is True
    assert packet["cio"]["source"] == "cio.product.current"
    assert "cio_investment_product_latest" not in str(packet["cio"].get("path") or "")
    assert packet["advisory"]["available"] is True
    assert packet["advisory"]["source"] == "advisory.current"


def test_aegis_explicit_unavailable_reason(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pkt, "ROOT", tmp_path)
    packet = pkt.build_packet()
    assert packet["cio"]["available"] is False
    assert packet["cio"]["reason"] == "PRODUCER_NOT_RUN"
    assert packet["advisory"]["available"] is False
    assert packet["advisory"]["reason"] == "PRODUCER_NOT_RUN"


def test_operator_product_human_and_unavailable() -> None:
    u = unavailable(reason="STALE", detail="mtime too old")
    assert u["available"] is False
    assert u["reason"] == "STALE"
    text = render_human(u)
    assert "CIO_PRODUCT_UNAVAILABLE" in text
    assert "STALE" in text


def test_ops_health_not_investment() -> None:
    r = classify_message("Research lane RAW-store health deepseek: zero_non_error_24h COST_CONFIGURATION_INVALID")
    assert r["is_investment_intelligence"] is False
    assert r["channel"] == "OPS_HEALTH"
    assert "No investment decision is being changed" in r["human"]


def test_occ_option_not_unknown_equity() -> None:
    c = classify_instrument("AAPL240119C00190000")
    assert c["instrument_class"] == "OPTION"
    assert c["underlying_symbol"] == "AAPL"
    assert classify_instrument("NVDA")["instrument_class"] == "EQUITY"
    assert classify_instrument("CASH", is_cash=True)["instrument_class"] == "CASH"


def test_envelope_never_mints_security_guid() -> None:
    cash = entity_ref(entity_type="PORTFOLIO_CASH", semantic_subject="PORTFOLIO_CASH:CONSOLIDATED")
    assert cash["entity_guid"] is None
    env = envelope({"x": 1}, entity_refs=[cash], producer="test", semantic_key="k")
    assert env["schema"] == "TradeAIRecordEnvelope@v1"
    assert env["synthetic"] is False


def test_holdings_write_rejected_is_last_known_good() -> None:
    h = holdings_freshness({"write_rejected": True, "holdings": [{"symbol": "NOC"}]})
    assert h["state"] == "WRITE_REJECTED"
    assert "LAST_KNOWN_GOOD" in (h["note"] or "")
    inst = instrument_audit([{"symbol": "NVDA"}, {"symbol": "AAPL240119C00190000"}])
    assert inst["classes"]["EQUITY"] == 1
    assert inst["option_n"] == 1


def test_no_destructive_purge(tmp_path: Path) -> None:
    from scripts.lib.data_integrity_audit import audit
    (tmp_path / "data/cio").mkdir(parents=True)
    (tmp_path / "data/cio/outcome_checkpoints.jsonl").write_text("")
    a = audit(root=tmp_path)
    assert a["purge_plan"]["destructive_changes_applied"] is False
    r = reconcile_store(tmp_path)
    assert r["deleted"] == 0
