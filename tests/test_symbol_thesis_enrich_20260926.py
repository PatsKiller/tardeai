"""Options research answers improve the SYMBOL thesis through the existing path.

Hermes result -> accept_research_result -> reconcile_symbol_thesis ->
publish_symbol_thesis -> CIOThesisStore. No second writer. Every store here is
a tmp_path store; nothing touches data/cio in the tree.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib.cio_question_ids import ANSWER_MAP, structured_answers
from scripts.lib.cio_theses import CIOThesisStore
from scripts.lib.research_thesis_delta import (
    _evidence_ids,
    accept_research_result,
    enrich_settings,
)
from scripts.lib.symbol_thesis_publish import publish_symbol_thesis
from scripts.lib.symbol_thesis_review import daily_thesis_changes

NOW = datetime(2026, 9, 26, 20, 0, tzinfo=timezone.utc)
CFG = {"cooldown_hours": 24}

RECOMMENDATION = (
    "HOOD remains a WATCH in the growth sleeve after the latest monthly metrics review. "
    "Funded accounts increased 4.1% as net deposits supported visible asset growth. "
    "Crypto trading revenue remains the most important named driver for transaction revenue mix. "
    "Management guidance supports continued growth but does not justify an independent ADD decision. "
    "Regulatory exposure on payment for order flow is the strongest counterpoint to monitor. "
    "The standing thesis is confirmed because customer asset evidence improved modestly. "
    "The thesis would be invalidated if net deposits turn negative or crypto volumes collapse. "
    "HOOD should therefore remain on watch, with the CIO applying deterministic portfolio gates. "
    "This research changes evidence completeness only and grants no trading or broker authority."
)


def _store(root: Path) -> CIOThesisStore:
    return CIOThesisStore(
        event_path=root / "data/cio/cio_theses.jsonl",
        projection_path=root / "data/cio/cio_theses_projection.json",
    )


def _ctx() -> dict:
    return {
        "standing_thesis": {"thesis_id": "symbol_hood", "version": "symbol_hood@v1"},
        "as_of": "2026-09-26T18:00:00+00:00",
        "deterministic_changes_since_prior_review": [],
    }


def _answer(qid: str, summary: str, detail: str = "", status: str = "answered") -> dict:
    return {"question_id": qid, "status": status, "summary": summary, "detail": detail,
            "citations": [], "confidence": 0.7}


def _result(classification: str = "CONFIRMS", *, answers: list | None = None, **kw) -> dict:
    row = {
        "recommendation": RECOMMENDATION,
        "dissent": "",
        "confidence": 0.79,
        "classification": classification,
        "evidence_as_of": "2026-09-25T20:00:00+00:00",
        "evidence": [
            {"evidence_id": "ev_hood_deposits", "text": "HOOD net deposits rose 4.1%."},
            {"evidence_id": "ev_hood_guidance", "text": "Guidance retained the growth range."},
        ],
        "contradictory_evidence": [{"evidence_id": "ev_hood_pfof", "text": "PFOF regulatory risk."}],
        "thesis_stance": "WATCH",
        "answers": answers if answers is not None else [
            _answer("q_thesis_check", "HOOD thesis: asset growth funds a platform re-rating.",
                    "Deposits and funded accounts both rose."),
            _answer("q_catalyst_map", "Q3 earnings on 2026-10-29.", "Monthly metrics mid-October.",
                    status="partial"),
            _answer("q_invalidation", "Net deposits turn negative for two months.",
                    "Or crypto volume falls 50% from the trailing average."),
            _answer("q_bear_case", "Crypto volume is cyclical and PFOF is a regulatory target.",
                    "A downturn cuts transaction revenue by a third."),
        ],
    }
    row.update(kw)
    return row


def _seed(root: Path, *, writer: str = "research_thesis_delta", summary: str | None = None,
          invalidation: list | None = None, catalysts: list | None = None) -> dict:
    return publish_symbol_thesis(
        "HOOD",
        summary=summary or "HOOD is watched for platform growth; asset growth must continue.",
        stance="watch",
        portfolio_role="GROWTH",
        evidence_for=["ev_old_support"],
        counter_evidence=["ev_old_counter"],
        invalidation_conditions=invalidation or [],
        catalysts=catalysts,
        store=_store(root),
        actor_id=writer,
        provenance={"writer": writer, "trigger": "seed"},
    )


def _accept(root: Path, result: dict, *, research_id: str = "res_hood_1", **kw) -> dict:
    kw.setdefault("enrich_config", CFG)
    kw.setdefault("now", NOW)
    return accept_research_result(
        "HOOD", result, prompt_context=_ctx(), research_id=research_id, root=root,
        source_result_id="rr_hood_1", run_id="run_1", source_sha="sha1", **kw,
    )


# ── 1. structured answers ────────────────────────────────────────────────────


def test_structured_answers_full_text_skips_unanswered():
    long = "x" * 1500
    res = {"answers": [
        _answer("q_thesis_check", "T", long),
        _answer("q_catalyst_map", "none found", "calendar empty", status="unanswered"),
        _answer("q_invalidation", "I", status="partial"),
        _answer("q_bear_case", "B", "bear detail"),
        _answer("q_cio_followup_1", "F1", "follow-up detail"),
        _answer("q2", "positional ignored"),
    ]}
    out = structured_answers(res)
    assert out["thesis"] == "T " + long  # full text, not the lifecycle's 600-char cut
    assert "catalysts" not in out
    assert out["invalidation"] == "I"
    assert out["bear_case"] == "B bear detail"
    assert out["cio_followup_1"] == "F1 follow-up detail"
    assert set(ANSWER_MAP.values()) == {"thesis", "catalysts", "invalidation", "bear_case"}
    assert structured_answers(None) == {}


def test_lifecycle_uses_the_shared_map_and_keeps_truncation():
    from scripts.lib import options_thesis_lifecycle as life
    assert life.ANSWER_MAP is ANSWER_MAP
    out = life.answers_from_result({"answers": [_answer("q_thesis_check", "T", "y" * 900)]}, "res_1")
    assert len(out["thesis"]) == 600


def test_enrich_settings_read_from_portfolio_intent():
    s = enrich_settings()
    assert s["scope"] == "options_horizon"
    assert s["cooldown_hours"] > 0
    assert "research_thesis_delta" in s["machine_writers"]
    assert enrich_settings({"cooldown_hours": 0})["cooldown_hours"] == 0


# ── 2. publish path: mapping + merge semantics ───────────────────────────────


def test_material_research_maps_answers_and_merges_evidence(tmp_path: Path):
    _seed(tmp_path, invalidation=["authored: exit if deposits fall"])
    out = _accept(tmp_path, _result("STRENGTHENS"))
    assert out["version_published"] is True
    cur = _store(tmp_path).get_current("symbol_hood")

    # (a) invalidation merged: the standing condition first, the answer appended
    assert cur["invalidation_conditions"][0] == "authored: exit if deposits fall"
    assert cur["invalidation_conditions"][1].startswith("Net deposits turn negative")
    # (b) catalysts as structured rows with provenance; future date kept
    cats = cur["catalysts"]
    assert len(cats) == 1 and cats[0]["source_research_id"] == "res_hood_1"
    assert cats[0]["event_date"] == "2026-10-29"
    assert cats[0]["as_of"] == "2026-09-25T20:00:00+00:00"
    # (c) bear case has an ev id in counter_evidence with its text kept
    bear_id = _evidence_ids([{"text": structured_answers(_result())["bear_case"]}], "CONTRADICTION")[0]
    assert bear_id in cur["counter_evidence"]
    assert cur["evidence_text"][bear_id].startswith("Crypto volume is cyclical")
    # (d) evidence merged old+new, never new-only
    assert cur["evidence_for"][:1] == ["ev_old_support"]
    assert {"ev_hood_deposits", "ev_hood_guidance"} <= set(cur["evidence_for"])
    assert cur["counter_evidence"][0] == "ev_old_counter"
    assert "ev_hood_pfof" in cur["counter_evidence"]
    # provenance: research id is the res_ id; the rr_ result id is kept separately
    prov = cur["write_provenance"]
    assert prov["source_research_ids"] == ["res_hood_1"]
    assert prov["source_result_id"] == "rr_hood_1"
    assert "scope" not in prov  # scope is an ENRICHES marker only


def test_past_dated_catalyst_is_pruned(tmp_path: Path):
    _seed(tmp_path, catalysts=[{"text": "Investor day 2026-09-01", "as_of": "x", "source_research_id": "r0"},
                               {"text": "Undated product launch", "as_of": "x", "source_research_id": "r0"}])
    _accept(tmp_path, _result("STRENGTHENS"))
    texts = [c["text"] for c in _store(tmp_path).get_current("symbol_hood")["catalysts"]]
    assert "Investor day 2026-09-01" not in texts
    assert "Undated product launch" in texts
    assert any("2026-10-29" in t for t in texts)


def test_authored_summary_is_kept(tmp_path: Path):
    authored = "Operator thesis: HOOD is a platform compounder; watch deposits and crypto mix."
    _seed(tmp_path, writer="symbol_thesis_synthesis", summary=authored)
    out = _accept(tmp_path, _result("STRENGTHENS"))
    assert out["version_published"] is True
    assert _store(tmp_path).get_current("symbol_hood")["summary"] == authored


@pytest.mark.parametrize("writer,summary", [
    ("research_thesis_delta", None),
    ("symbol_thesis_synthesis", "RESEARCH_REQUIRED: living thesis for HOOD incomplete."),
])
def test_machine_or_placeholder_summary_replaced_by_thesis_check(tmp_path: Path, writer, summary):
    _seed(tmp_path, writer=writer, summary=summary)
    _accept(tmp_path, _result("STRENGTHENS"))
    got = _store(tmp_path).get_current("symbol_hood")["summary"]
    assert got.startswith("HOOD thesis: asset growth funds a platform re-rating.")


def test_mint_record_without_provenance_is_machine(tmp_path: Path):
    _store(tmp_path).publish("Minted HOOD summary text", thesis_id="symbol_hood", stance="watch",
                             linked_symbols=["HOOD"], extra={"mint_state": "LIVE_MINTED"})
    _accept(tmp_path, _result("STRENGTHENS"))
    assert _store(tmp_path).get_current("symbol_hood")["summary"].startswith("HOOD thesis:")


# ── 3. ENRICHES ─────────────────────────────────────────────────────────────


def test_enriches_fills_empty_fields_only(tmp_path: Path):
    seeded = _seed(tmp_path)
    out = _accept(tmp_path, _result("CONFIRMS"))  # existing gates: no publish
    assert out["delta"]["thesis_publish_eligible"] is False
    assert out["version_published"] is True and out["enriched"] is True
    assert out["enrich_fields"] == ["catalysts", "invalidation_conditions"]
    assert out["classification"] == "THESIS_ENRICHED"
    cur = _store(tmp_path).get_current("symbol_hood")
    assert cur["thesis_version"] == "symbol_hood@v2"
    # never stance / summary / evidence
    for k in ("stance", "summary", "evidence_for", "counter_evidence", "portfolio_role"):
        assert cur[k] == seeded[k], k
    assert cur["invalidation_conditions"][0].startswith("Net deposits turn negative")
    assert cur["catalysts"][0]["event_date"] == "2026-10-29"
    prov = cur["write_provenance"]
    assert prov["trigger"] == "ENRICHES"
    assert prov["scope"] == "options_horizon"
    assert prov["source_research_ids"] == ["res_hood_1"]
    assert "THESIS_ENRICHED" in cur["change_note"]
    daily = daily_thesis_changes(root=tmp_path, store=_store(tmp_path))
    assert daily["counts"]["ENRICHED"] == 1


def test_enriches_leaves_filled_fields_and_stance_alone(tmp_path: Path):
    _seed(tmp_path, invalidation=["authored condition"])
    # WEAKENS at grade A would publish normally; use NO answers for invalidation
    # and a CONFIRMS result so only the empty catalysts field can be filled.
    out = _accept(tmp_path, _result("CONFIRMS", thesis_stance="AVOID"))
    assert out["enrich_fields"] == ["catalysts"]
    cur = _store(tmp_path).get_current("symbol_hood")
    assert cur["invalidation_conditions"] == ["authored condition"]
    assert cur["stance"] == "watch"


@pytest.mark.parametrize("change", [
    {"classification": "INSUFFICIENT_DATA"},
    {"recommendation": "Too short to grade."},  # grade F -> not A
])
def test_enriches_requires_grade_a_and_not_insufficient(tmp_path: Path, change):
    _seed(tmp_path)
    out = _accept(tmp_path, _result(**{"classification": "CONFIRMS", **change}))
    assert out["version_published"] is False
    assert _store(tmp_path).get_current("symbol_hood")["thesis_version"] == "symbol_hood@v1"


def test_enriches_needs_a_standing_thesis(tmp_path: Path):
    out = _accept(tmp_path, _result("CONFIRMS"))
    assert out["version_published"] is False
    assert _store(tmp_path).get_current("symbol_hood") is None


def test_enriches_respects_cooldown(tmp_path: Path):
    _seed(tmp_path)
    first = _accept(tmp_path, _result("CONFIRMS", answers=[
        _answer("q_invalidation", "Net deposits turn negative for two months.")]))
    assert first["enriched"] is True
    catalyst_only = _result("CONFIRMS", answers=[_answer("q_catalyst_map", "Q3 earnings on 2026-10-29.")])
    # published_ts is wall clock; evaluate "now" relative to it
    ts = datetime.fromisoformat(_store(tmp_path).get_current("symbol_hood")["published_ts"])
    blocked = _accept(tmp_path, catalyst_only, research_id="res_hood_2", now=ts + timedelta(hours=1))
    assert blocked["version_published"] is False
    assert blocked["publish_suppressed_reason"] == "enrich_cooldown"
    later = _accept(tmp_path, dict(catalyst_only, confidence=0.8), research_id="res_hood_3",
                    now=ts + timedelta(hours=25))
    assert later["enriched"] is True and later["enrich_fields"] == ["catalysts"]
    assert _store(tmp_path).get_current("symbol_hood")["thesis_version"] == "symbol_hood@v3"


def test_replay_of_same_result_publishes_nothing(tmp_path: Path):
    _seed(tmp_path)
    res = _result("CONFIRMS")
    first = _accept(tmp_path, res)
    assert first["enriched"] is True
    replay = _accept(tmp_path, res, now=NOW + timedelta(days=3))
    assert replay["delta"]["classification"] == "NO_NEW_INFO"
    assert replay["version_published"] is False
    assert _store(tmp_path).get_current("symbol_hood")["thesis_version"] == "symbol_hood@v2"
    again = _accept(tmp_path, res, now=NOW + timedelta(days=3))
    assert again.get("duplicate") is True


def test_caller_result_not_mutated(tmp_path: Path):
    _seed(tmp_path)
    res = _result("STRENGTHENS")
    before = json.dumps(res, sort_keys=True)
    _accept(tmp_path, res)
    assert json.dumps(res, sort_keys=True) == before


# ── 4. product reassessment passes the res_ id ──────────────────────────────


def test_reassessment_passes_parent_research_id(tmp_path: Path, monkeypatch):
    from scripts.lib import cio_product_reassessment as cpr
    from scripts.lib import research_thesis_delta as rtd

    seen: dict = {}

    def fake_accept(symbol, result, **kw):
        seen.update(kw)
        raise RuntimeError("stop after capture")

    monkeypatch.setattr(rtd, "accept_research_result", fake_accept)
    request = {"plan_id": "plan_1", "research_id": "res_abc123", "symbol": "HOOD",
               "prompt_context": {"standing_thesis": {}}}
    result = {"research_id": "res_abc123", "result_id": "rr_def456", "symbol": "HOOD"}
    try:
        cpr.reassess_on_research_completed(request, result, root=tmp_path, notify=False,
                                           queue={}, previously_traded=[], holdings={})
    except Exception:
        pass
    assert seen.get("research_id") == "res_abc123"
    assert seen.get("source_result_id") == "rr_def456"
