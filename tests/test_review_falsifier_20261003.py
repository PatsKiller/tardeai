"""Optional `falsifier` in the options / buy-ready CIO LLM reviews (operator-approved 2026-10-03).

A review may state the one observable condition that would prove it wrong. It is
optional (reviews written before the field existed stay valid), shape-checked, and
held to the same no-sizing and number-traceability rules as the other free text.
When present it reaches the decision-lineage falsifier stage.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import buy_ready_cio_review as br  # noqa: E402
from scripts.lib import options_cio_review as ocr  # noqa: E402

FACTS = {"symbol": "DELL", "equity_plan": {"stop": 118.4, "target": 142.0}, "earnings_date": "2026-11-20"}


def _options_review(**extra) -> dict:
    review = {"outcome": "MONITOR_ONLY", "confidence": "MEDIUM", "reasoning": "Thesis sound, timing thin.",
              "concerns": [], "assumptions_challenged": [], "evidence_for": [], "evidence_against": ["IV is low"],
              "exit_plan_view": "adequate", "unknowns": []}
    review.update(extra)
    return review


def _buy_ready_review(**extra) -> dict:
    review = {"verdict": "MODIFY", "reason": "Wait for the zone.",
              "scores": {k: {"score": 5, "evidence": "ok"} for k in br.SCORE_KEYS},
              "equity_view": "fine", "options_view": "fine", "portfolio_view": "fine",
              "modifications": [], "unknowns": []}
    review.update(extra)
    return review


def test_falsifier_is_optional_for_both_reviews():
    assert ocr.validate(_options_review(), FACTS) == (True, [])
    assert br.validate_review(_buy_ready_review(), FACTS) == (True, [])
    assert ocr.validate(_options_review(falsifier=None), FACTS)[0] is True


def test_a_traceable_falsifier_is_accepted():
    text = "A close below the 118.4 stop, or no beat at the 2026-11-20 earnings."
    assert ocr.validate(_options_review(falsifier=text), FACTS) == (True, [])
    assert br.validate_review(_buy_ready_review(falsifier=text), FACTS) == (True, [])


def test_empty_wrong_type_or_too_long_falsifier_is_rejected():
    for bad in ("", "   ", ["not", "a string"], "x" * (br.FALSIFIER_MAX_CHARS + 1)):
        ok_o, errs_o = ocr.validate(_options_review(falsifier=bad), FACTS)
        ok_b, errs_b = br.validate_review(_buy_ready_review(falsifier=bad), FACTS)
        assert not ok_o and any("falsifier" in e for e in errs_o), bad
        assert not ok_b and any("falsifier" in e for e in errs_b), bad


def test_sizing_language_in_the_falsifier_is_refused():
    text = "If it fails, buy 200 shares on the dip."
    assert any("sizing" in e for e in ocr.validate(_options_review(falsifier=text), FACTS)[1])
    assert any("sizing" in e for e in br.validate_review(_buy_ready_review(falsifier=text), FACTS)[1])


def test_an_invented_number_in_the_falsifier_is_refused():
    text = "Wrong if price closes below 97.35."
    assert any("traceable" in e for e in ocr.validate(_options_review(falsifier=text), FACTS)[1])
    assert any("traceable" in e for e in br.validate_review(_buy_ready_review(falsifier=text), FACTS)[1])


def test_both_prompts_ask_for_the_falsifier():
    assert '"falsifier"' in ocr.PROMPT
    assert '"falsifier"' in br.OUTPUT_CONTRACT


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_a_reviewed_falsifier_reaches_the_lineage_falsifier_stage(tmp_path, monkeypatch):
    import scripts.api_v3_cio as api

    root = tmp_path / "cio"
    root.mkdir()
    for name in ("cio_workflow_lineage.jsonl", "intelligence_lineages.jsonl",
                 "outcome_checkpoints.jsonl", "decision_dispositions.jsonl", "agent_run_traces.jsonl"):
        _write(root / name, [])
    falsifier = "A close below the 118.4 stop."
    row = {"decision_id": "dec_f1", "symbol": "DELL", "action": "MONITOR_ONLY",
           "action_class": "options_thesis_review", "created_at": "2026-10-03T12:00:00+00:00",
           "metadata": json.dumps({"model": {"model_used": "deepseek-flash", "provider": "deepseek"},
                                   "review": _options_review(falsifier=falsifier)})}
    stub = types.ModuleType("api_v2")
    stub._db_query = lambda sql, params, fetch=None: row
    monkeypatch.setitem(sys.modules, "api_v2", stub)
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(root))
    monkeypatch.setattr(api, "load_known_decision_catalog", lambda: {})
    result = api.get_cio_decision_lineage("dec_f1")
    assert result["ok"] is True, result
    stage = result["lineage"]["stages"]["falsifier"]
    assert stage["state"] == "LIVE"
    assert stage["value"] == falsifier
    assert stage["source_ref"] == "cio_decisions:dec_f1"


def test_a_review_without_a_falsifier_leaves_the_stage_not_live(tmp_path, monkeypatch):
    import scripts.api_v3_cio as api

    root = tmp_path / "cio"
    root.mkdir()
    for name in ("cio_workflow_lineage.jsonl", "intelligence_lineages.jsonl",
                 "outcome_checkpoints.jsonl", "decision_dispositions.jsonl", "agent_run_traces.jsonl"):
        _write(root / name, [])
    row = {"decision_id": "dec_f2", "action_class": "options_thesis_review", "created_at": "2026-10-03T12:00:00+00:00",
           "metadata": {"review": _options_review()}}
    stub = types.ModuleType("api_v2")
    stub._db_query = lambda sql, params, fetch=None: row
    monkeypatch.setitem(sys.modules, "api_v2", stub)
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(root))
    monkeypatch.setattr(api, "load_known_decision_catalog", lambda: {})
    stage = api.get_cio_decision_lineage("dec_f2")["lineage"]["stages"]["falsifier"]
    assert stage["state"] != "LIVE" and stage["value"] is None
