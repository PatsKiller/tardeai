"""Card and Aegis fixes from the live page and the Aegis dry test (2026-09-26).

Dry test: all three Aegis lanes flagged "debit mislabeled credit" on a protective
put, and options_ensemble had no daily cost cap. Page: a source label ("high") was
shown as a market thesis, counter-evidence printed raw ids, and illiquid hedges
(OI 0, 185% spread) were sent to research that cannot clear them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


def test_debit_is_not_called_credit():
    import options_engine as oe
    put = oe._proposal_ensemble_content({"strategy": "protective_put", "symbol": "XLB", "premium_total": 345.0})
    csp = oe._proposal_ensemble_content({"strategy": "cash_secured_put", "symbol": "DELL", "premium_total": 2157.0})
    assert "Total debit (you pay): $345.0" in put and "credit" not in put.split("Total debit")[0].lower()
    assert "Total credit (you collect): $2157.0" in csp


def test_market_thesis_is_not_a_source_label():
    from lib.options_plain_english import committee_memo
    p = {"strategy": "cash_secured_put", "symbol": "DELL", "research_context": {"summary": "high"}}
    assert committee_memo(p, {}, {})["market_thesis"].startswith("Not researched")


def test_contrarian_view_is_text_or_a_count_never_raw_ids():
    from lib.options_plain_english import committee_memo
    t = {"symbol_thesis_version": "symbol_hood@v4", "thesis_state": "CURRENT", "counter_evidence": ["ev_76cb4eec211aabce"]}
    m = committee_memo({"strategy": "cash_secured_put", "symbol": "HOOD"}, t, {})
    assert "ev_" not in m["contrarian_view"] and m["contrarian_view"].startswith("1 counter-evidence item")
    m2 = committee_memo({"strategy": "cash_secured_put", "symbol": "HOOD",
                         "research_answers": {"bear_case": "High-beta crypto sympathy"}}, t, {})
    assert m2["contrarian_view"] == "High-beta crypto sympathy"


def test_lifecycle_skips_ideas_research_cannot_fix(tmp_path):
    from datetime import datetime, timezone
    from lib import options_thesis as ot
    from lib.options_thesis_lifecycle import advance
    s = ot.OptionsThesisStore(tmp_path / "t.jsonl")
    s._append({"event_type": "OPTIONS_THESIS_VERSION", "position_guid": "g", "version": 1, "pin": "opt_g@v1"})
    p = {"symbol": "XLB", "option_strategy_guid": "g", "options_thesis": {"pin": "opt_g@v1", "missing_required": ["catalysts"]},
         "enterprise": {"blocks": ["OI 0 < 50", {"code": "thesis_missing_catalysts"}]}}
    called = []
    rep = advance([p], s, {}, request_research=lambda x: called.append(x) or {}, research_status=lambda r: {},
                  review_fn=lambda x, m: {}, record_decision=lambda r: None, apply=True,
                  now=datetime.now(timezone.utc))
    assert rep[0]["action"] == "SKIP_ENTERPRISE_BLOCK" and called == []


def test_options_ensemble_has_a_daily_cost_cap():
    d = json.loads((ROOT / "config" / "llm_process_registry.json").read_text(encoding="utf-8"))
    pr = next(p for p in d["processes"] if p["id"] == "options_ensemble")
    assert pr["daily_cost_cap_usd"] > 0 and "gemma" not in json.dumps(pr).lower()
    assert pr["allowed_lanes"] == ["grok", "chatgpt", "deepseek-flash"]
