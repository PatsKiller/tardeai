"""Options carry the same thesis bar as a stock purchase (2026-09-26).

Nothing in the options path read the symbol thesis store, so every card said
"no thesis pin", "Catalyst missing" came from reading the wrong field, and the
approval queue accepted ideas with no thesis. No DB, broker or network calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import options_thesis as ot  # noqa: E402

THESIS = {
    "symbol_thesis_id": "symbol_amzn",
    "symbol_thesis_version": "symbol_amzn@v5",
    "thesis_state": "CURRENT",
    "thesis_stance": "BULLISH",
    "thesis_summary": "AWS reacceleration and retail margin expansion.",
    "thesis_confidence": 0.7,
    "evidence_for": ["AWS growth reaccelerated two quarters running"],
    "counter_evidence": ["Capex intensity pressures FCF"],
    "invalidation_conditions": ["AWS growth below 12% for two quarters"],
    "portfolio_role": "CORE",
}


def _proposal(**kw):
    p = {
        "id": "opt_cash_secured_put_AMZN_schwab_taxable_210_2026-10-30_d20260926",
        "symbol": "AMZN", "strategy": "cash_secured_put", "account": "schwab_taxable",
        "option_strategy_guid": "tradeai:entity:strategy:abc123", "contract_guid": "tradeai:security:xyz",
        "strike": 210, "expiration": "2026-10-30", "dte": 34, "premium": 2.1, "breakeven": 207.9,
        "underlying_price": 231.0, "data_source": "schwab_chain", "max_loss": 20790, "edge_score": 71,
        "research_context": {"catalyst": "re:Invent 2026-12-01", "research_artifact_id": "watchlist:AMZN",
                             "source_lanes": ["watchlist_buy_strong_buy"]},
    }
    p.update(kw)
    return p


def test_complete_record_has_no_blocks():
    rec = ot.build_record(_proposal(), THESIS)
    assert rec["missing_required"] == []
    assert rec["investment_thesis"]["pin"] == "symbol_amzn@v5"
    assert rec["catalysts"] == ["re:Invent 2026-12-01"]
    assert ot.thesis_blocks(rec) == []


def test_no_symbol_thesis_blocks_like_an_equity_buy():
    rec = ot.build_record(_proposal(), {"thesis_state": "INSUFFICIENT_DATA"})
    codes = {b["code"] for b in ot.thesis_blocks(rec)}
    assert "thesis_required" in codes
    assert "thesis_missing_investment_thesis" in codes
    assert "thesis_missing_supporting_research" in codes


def test_broken_thesis_blocks():
    rec = ot.build_record(_proposal(), dict(THESIS, thesis_state="BROKEN"))
    assert any(b["code"] == "thesis_required" for b in ot.thesis_blocks(rec))


def test_missing_catalyst_and_exit_are_named():
    t = dict(THESIS, invalidation_conditions=[])
    rec = ot.build_record(_proposal(research_context={}), t)
    codes = {b["code"] for b in ot.thesis_blocks(rec)}
    assert "thesis_missing_catalysts" in codes
    assert "thesis_missing_exit_criteria" in codes  # an expiry date alone is not an exit plan


def test_no_guid_means_no_position_id():
    rec = ot.build_record(_proposal(option_strategy_guid=None), THESIS)
    assert "position_guid" in rec["missing_required"]


def test_sizing_is_never_computed():
    rec = ot.build_record(_proposal(), THESIS)
    assert rec["position_sizing_rationale"] is None
    assert "position_sizing_rationale" in rec["pending_operator"]
    assert rec["financial_action"] is False
    assert not any(k in json.dumps(rec) for k in ('"qty"', '"size_usd"', '"order"'))


def test_store_versions_only_on_change_and_chains(tmp_path):
    store = ot.OptionsThesisStore(tmp_path / "t.jsonl")
    rec = ot.build_record(_proposal(), THESIS)
    v1 = store.publish(rec)
    assert v1["stored"] and v1["version"] == 1 and v1["pin"].endswith("@v1")
    again = store.publish(ot.build_record(_proposal(generated_at="later"), THESIS))
    assert again["stored"] is False and again["version"] == 1
    v2 = store.publish(ot.build_record(_proposal(), dict(THESIS, symbol_thesis_version="symbol_amzn@v6")))
    assert v2["version"] == 2 and v2["supersedes"] == v1["pin"]
    store.record_approval(rec["position_guid"], proposal_id=rec["proposal_id"], action="approve", reviewer="operator")
    assert [e["event_type"] for e in store.history(rec["position_guid"])] == [
        "OPTIONS_THESIS_VERSION", "OPTIONS_THESIS_VERSION", "OPTIONS_THESIS_CIO_APPROVAL"]
    assert store.verify_chain()
    lines = (tmp_path / "t.jsonl").read_text().splitlines()
    tampered = json.loads(lines[0]); tampered["symbol"] = "XXX"; lines[0] = json.dumps(tampered)
    (tmp_path / "t.jsonl").write_text("\n".join(lines) + "\n")
    assert not store.verify_chain()


def test_engine_attaches_pin_catalyst_and_blocks(monkeypatch, tmp_path):
    import options_engine as oe
    import lib.symbol_thesis_attach as sta
    monkeypatch.setenv("TRADEAI_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setattr(sta, "thesis_fields_for_symbol",
                        lambda sym, **k: THESIS if sym == "AMZN" else {"thesis_state": "INSUFFICIENT_DATA"})
    good, bad = _proposal(), _proposal(symbol="PCSA", option_strategy_guid="tradeai:entity:strategy:def")
    oe._attach_options_thesis([good, bad])
    assert good["thesis_version_at_decision"] == "symbol_amzn@v5"
    assert good["catalyst"] == "re:Invent 2026-12-01"
    assert good["thesis_blocks"] == [] and good["options_thesis"]["pin"].endswith("@v1")
    assert any(b["code"] == "thesis_required" for b in bad["thesis_blocks"])
    assert (tmp_path / "data" / "cio" / "options_theses.jsonl").is_file()


def test_comparison_now_sees_the_pin():
    from lib.recommendation_comparison import build_recommendation_comparison
    cmp = build_recommendation_comparison(_proposal(thesis_version_at_decision="symbol_amzn@v5"))
    assert cmp["thesis"]["thesis_version"] == "symbol_amzn@v5"


def test_spread_guid_includes_the_long_leg(monkeypatch):
    from lib import options_identity as oi
    monkeypatch.setattr(oi, "resolve_issuer_guid", lambda und, registry=None: "tradeai:issuer:amzn")
    a = oi.stamp_proposal_identity({"symbol": "AMZN", "strategy": "credit_spread", "option_type": "put",
                                    "short_strike": 210, "long_strike": 200, "expiration": "2026-10-30"})
    b = oi.stamp_proposal_identity({"symbol": "AMZN", "strategy": "credit_spread", "option_type": "put",
                                    "short_strike": 210, "long_strike": 195, "expiration": "2026-10-30"})
    assert a["option_strategy_guid"] and a["option_strategy_guid"] != b["option_strategy_guid"]
    assert a["underlying_identity"]["issuer_guid"] == "tradeai:issuer:amzn"


def test_queue_blocks_on_thesis_source():
    src = (ROOT / "scripts" / "options_desk_enterprise.py").read_text(encoding="utf-8")
    assert 'status = "blocked" if (p.get("enterprise_blocked") or thesis_blocks) else "pending"' in src
    assert "_record_thesis_approval" in src
