"""UI honesty: no [:400] stub, no DATA_UNAVAILABLE as thesis body, cache follows jsonl."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.symbol_thesis_coverage import classify_symbol
from scripts.lib.thesis_substantiveness import pass_fixture


class _Store:
    def __init__(self, recs=None):
        self._recs = recs or {}

    def get_current(self, tid):
        return self._recs.get(tid)


def test_thesis_summary_is_not_truncated_to_400():
    body = pass_fixture("NOC") + " " + ("backlog durability. " * 80)
    assert len(body) > 400
    rec = {
        "status": "active",
        "published_ts": "2026-08-22T22:47:21+00:00",
        "updated_ts": "2026-08-22T22:47:21+00:00",
        "summary": body,
        "stance": "hold",
        "thesis_version": "symbol_noc@v3",
    }
    store = _Store({"symbol_noc": rec, "desk": {"thesis_version": "desk@v5"}})
    uni = {"memberships": ["HELD"], "held": True}
    out = classify_symbol("NOC", universe_rec=uni, store=store)
    assert out["thesis_summary"] is not None
    assert len(out["thesis_summary"]) > 400
    assert out["thesis_summary"] == body.strip()


def test_operator_text_strips_data_unavailable_token():
    from scripts.lib.symbol_thesis_attach import _operator_text

    assert _operator_text("DATA_UNAVAILABLE") is None
    assert _operator_text("DATA_UNAVAILABLE — no living symbol thesis") is None
    assert _operator_text("Hold the defense compounder") == "Hold the defense compounder"
    assert _operator_text(None) is None


def test_core_thesis_fallback_is_not_the_machine_token():
    src = (ROOT / "scripts/lib/symbol_thesis_cc.py").read_text(encoding="utf-8")
    assert 'DATA_UNAVAILABLE — no living symbol thesis' not in src
    assert '"core_thesis": fields.get("thesis_summary") or "No living thesis"' in src
    assert '[:400]' not in src
    assert '[:300]' not in src


def test_universe_metrics_exposes_substantive_and_thin():
    src = (ROOT / "scripts/lib/symbol_thesis_attach.py").read_text(encoding="utf-8")
    assert "held_substantive_pct" in src
    assert "substantive_pct_material" in src
    assert "_store_token" in src
    cc = (ROOT / "scripts/lib/symbol_thesis_cc.py").read_text(encoding="utf-8")
    assert '"substantive_pct": metrics.get("substantive_pct_material")' in cc
    assert '"held_current": metrics.get("held_current")' in cc


def test_percentage_definitions_declare_numerator_denominator_and_scope(monkeypatch, tmp_path):
    import scripts.lib.symbol_thesis_attach as attach

    rows = {
        "NOC": {"symbol": "NOC", "material": True, "memberships": ["HELD"], "coverage_state": "CURRENT"},
        "PFLT": {"symbol": "PFLT", "material": True, "memberships": ["HELD"], "coverage_state": "THIN"},
        "AVAV": {"symbol": "AVAV", "material": True, "memberships": ["REENTRY"], "coverage_state": "RESEARCH_REQUIRED"},
    }
    monkeypatch.setattr(attach, "_load", lambda root: ({}, _Store({"desk": {"thesis_version": "desk@v1"}}), rows))
    out = attach.universe_metrics(root=tmp_path)
    held = out["percentage_definitions"]["held_substantive"]
    material = out["percentage_definitions"]["material_coverage"]
    assert held == {
        "numerator": 1,
        "denominator": 2,
        "numerator_states": ["CURRENT"],
        "membership_scope": "HELD_equity_tickers_excluding_cash_and_unresolved_identifiers",
        "formula": "100 * CURRENT / held",
        "pct": 50.0,
    }
    assert material["numerator"] == 2
    assert material["denominator"] == 3
    assert material["pct"] == 66.7


def test_serving_stamp_and_boot_stamp_exist_in_server():
    src = (ROOT / "scripts/portfolio_server.py").read_text(encoding="utf-8")
    assert "ServingFreshness@v1" in src
    assert "PROCESS_STARTED_AT" in src
    assert "portfolio_server_boot.json" in src
    pin = (ROOT / "scripts/lib/current_pin_integrity.py").read_text(encoding="utf-8")
    assert "collect_process_freshness" in pin
    assert "loaded_pin_ne_current_pin" in pin


def test_serving_stamp_has_complete_freshness_contract(monkeypatch):
    import scripts.portfolio_server as server

    class Handler:
        path = "/api/v3/cio/universe-theses"

    monkeypatch.setattr(server, "LOADED_PIN_SHA", "abc")
    monkeypatch.setattr(server, "_read_pin_sha", lambda root: "abc")
    stamped = server._stamp_serving(Handler(), {"as_of": datetime.now(timezone.utc).isoformat()})
    freshness = stamped["_serving"]
    assert freshness["source_pin"] == "abc"
    assert freshness["loaded_pin"] == "abc"
    assert freshness["process_started_at"]
    assert freshness["data_as_of"]
    assert freshness["cache_age"] is not None
    assert freshness["pin_match"] is True


def test_ciohub_renders_substantive_and_thin_not_coverage_only():
    src = (ROOT / "apps/command-center-v3/src/pages/CioHub.tsx").read_text(encoding="utf-8")
    assert "Held substantive" in src
    assert "thesis_state === 'THIN'" in src
    assert "cio-daily-thesis-changes" in src
    assert "dec_${id.slice" not in src
    assert "heldSub.numerator" in src
    assert "materialCov.denominator" in src
