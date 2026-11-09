"""CIO_BRIEF_CONSISTENCY_LQ1318_20261109 — the brief's claims map to its rows, and its pieces are one run.

LQ-20261107-1318 (operator 2026-11-08 20:22 ET: "why did we get two different results? why wasn't it uniform?").
The preview and Home disagreed because one was prose and the other was a document. These tests pin the two rules
that make such a disagreement a FAIL instead of a surprise:

* every synopsis line carries ``source_ids`` and every id resolves to a row or a named feed;
* every summary sentence names a symbol the brief has a row for, or carries a source tag;
* a summary (or synopsis) saying "no cause" about a name whose research row names one is a contradiction;
* every run-scoped piece (synopsis, each stop_advice row) is from the document's own run — by ``run_id`` when the
  piece carries one, by clock within a tolerance when it only carries a time.

Hermetic: synthetic symbols and documents, no database, no network, no production state.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import cio_brief_consistency as C  # noqa: E402
from lib import since_close_card as SC  # noqa: E402

GEN = "2026-11-09T01:14:38+00:00"
ASOF = "2026-11-09T01:06:00+00:00"


def brief(**over) -> dict:
    doc = {
        "schema": "CIOOvernightBrief@v1",
        "lane_id": "cio-overnight-brief",
        "generated_at": GEN,
        "as_of": ASOF,
        "run_id": "cio-brief-test0001",
        "advisory_only": True,
        "synopsis": {
            "posture": "DEFENSIVE",
            "verdict": "AAA needs a stop decision; BBB holds.",
            "book": {"line": "2 position(s) in 1 account", "source_ids": ["positions_current:2026-11-08T20:00:00-05:00"]},
            "market": {"line": "RED sector tape, not market-wide", "source_ids": ["market_risk:2026-11-09T01:00:00+00:00"]},
            "do_now": {"line": "First: AAA in acct1 — RAISE", "source_ids": ["stop_last_known:AAA:acct1"]},
            "as_of": ASOF,
            "source_ids": ["market_risk:2026-11-09T01:00:00+00:00", "positions_current:2026-11-08T20:00:00-05:00"],
        },
        "summary": {"text": "AAA rose 4.00% on a bank downgrade (research).", "source": "llm"},
        "holdings": [
            {"symbol": "AAA", "news": [{"id": 1, "title": "Bank downgrades AAA"}],
             "research": {"status": "answered", "lane": "grok",
                          "text": "WHO/WHAT: A bank cut its rating (news:1).\n\nWHY: The downgrade names weaker guidance for next year.\n\nIMPACT: Negative."}},
            {"symbol": "BBB",
             "research": {"status": "answered", "lane": "grok",
                          "text": "WHO/WHAT: No named party.\n\nWHY: Evidence does not support a WHY for the move.\n\nIMPACT: None."}},
        ],
        "stop_advice": [
            {"symbol": "AAA", "account": "acct1", "answer": "RAISE", "event_summary": "Bank downgrades AAA",
             "as_of": ASOF, "source_ids": ["news:1", "stop_last_known:AAA:acct1"]},
            {"symbol": "BBB", "account": "acct1", "answer": "HOLD", "event_summary": "BBB wins a contract",
             "as_of": ASOF, "source_ids": ["stop_last_known:BBB:acct1"]},
        ],
        "watchlist": [],
        "week_ahead": {"macro": [], "earnings": []},
        "counts": {"selected": 2},
    }
    for k, v in over.items():
        if k == "synopsis" and isinstance(v, dict):
            doc["synopsis"] = {**doc["synopsis"], **v}
        else:
            doc[k] = v
    return doc


def codes(doc) -> list[str]:
    return [f["code"] for f in C.check_brief(doc)["findings"]]


# ── the clean document is clean ──────────────────────────────────────────────────────────────────────────────


def test_a_consistent_brief_passes():
    rep = C.check_brief(brief())
    assert rep["state"] == "PASS", rep["findings"]
    assert rep["run_id"] == "cio-brief-test0001"
    assert rep["checked"] == {"rows": 4, "synopsis_blocks": 3, "summary_sentences": 1, "summary_claims": True}


def test_not_a_brief_fails_rather_than_passing_empty():
    assert C.check_brief(None)["state"] == "FAIL"
    rep = C.check_brief({"hello": "world"})
    assert rep["state"] == "FAIL" and rep["findings"][0]["code"] == "not_a_document"
    wrong = brief(schema="CIOOvernightBrief@v0")
    assert "not_a_document" in codes(wrong) and "CIOOvernightBrief@v0" in C.check_brief(wrong)["findings"][0]["detail"]


# ── claims: every line has a row behind it ──────────────────────────────────────────────────────────────────


def test_a_synopsis_line_without_source_ids_fails():
    doc = brief()
    doc["synopsis"]["do_now"] = {"line": "First: AAA in acct1 — RAISE"}  # no source_ids
    assert "synopsis_line_without_sources" in codes(doc)


def test_an_unresolvable_source_id_fails():
    for sid in ("xray:1", "news:999", "stop_last_known:ZZZ:acct1"):
        doc = brief()
        doc["synopsis"]["market"] = {"line": "RED sector tape", "source_ids": [sid]}
        assert "unknown_source_id" in codes(doc), sid


def test_a_source_id_resolves_to_the_row_it_names():
    doc = brief()
    assert C.resolves("news:1", doc)            # a news row on AAA
    assert C.resolves("research:grok", doc)      # a lane that answered
    assert C.resolves("stop_last_known:BBB:acct1", doc)  # a name with a row
    assert C.resolves("market_risk", doc)        # a named feed
    assert not C.resolves("stop_last_known:ZZZ", doc)    # a name with no row
    assert not C.resolves("", doc)


def test_a_summary_sentence_without_a_symbol_or_a_tag_fails():
    doc = brief(summary={"text": "The book is calm.", "source": "llm"})
    assert "unmapped_summary_sentence" in codes(doc)


def test_a_summary_sentence_with_a_symbol_or_a_tag_passes():
    assert "unmapped_summary_sentence" not in codes(brief(summary={"text": "AAA rose 4.00% (research).", "source": "llm"}))
    assert "unmapped_summary_sentence" not in codes(brief(summary={"text": "The tape is red (market_risk).", "source": "llm"}))


def test_a_deterministic_summarys_context_lines_are_projection_not_claim():
    # The real assembled brief (dry run 2026-11-08 20:36 ET) writes these lines itself from the same rows; gating
    # them would fail the producer on every run and get the gate suppressed.
    text = ("4 held name(s) need attention: AAA +8.62%. Market regime: high_volatility (score 5.0); risk tier RED "
            "(59.6). Macro this week: Consumer Price Index. Every action below is advisory; the CIO remains the "
            "verdict owner per account.")
    doc = brief(summary={"text": text, "source": "deterministic"})
    rep = C.check_brief(doc)
    assert rep["state"] == "PASS", rep["findings"]
    assert rep["checked"]["summary_claims"] is False


def test_a_deterministic_summary_still_fails_the_no_cause_contradiction():
    doc = brief(summary={"text": "BBB has no cause for its move.", "source": "deterministic"})
    doc["holdings"][1]["research"]["text"] = "WHO/WHAT: none.\n\nWHY: A customer contract was announced.\n\nIMPACT: Positive."
    assert "summary_says_no_cause_research_names_one" in codes(doc)


# ── the contradiction the operator saw ──────────────────────────────────────────────────────────────────────


def test_a_summary_saying_no_cause_about_a_name_whose_research_names_one_fails():
    doc = brief()
    doc["holdings"][1]["research"]["text"] = "WHO/WHAT: none.\n\nWHY: A large customer contract was announced.\n\nIMPACT: Positive."
    doc["summary"]["text"] = "BBB fell 2.00% and there is no cause for the move (research)."
    rep = C.check_brief(doc)
    assert [f["code"] for f in rep["findings"]] == ["summary_says_no_cause_research_names_one"]
    assert rep["findings"][0]["where"].endswith("BBB")


def test_the_same_sentence_passes_when_the_research_also_says_the_evidence_does_not_support_it():
    doc = brief()
    doc["summary"]["text"] = "BBB fell 2.00% and there is no cause for the move (research)."
    assert "summary_says_no_cause_research_names_one" not in codes(doc)


def test_a_synopsis_line_saying_no_cause_about_a_name_whose_research_names_one_fails():
    doc = brief()
    doc["holdings"][1]["research"]["text"] = "WHO/WHAT: none.\n\nWHY: An analyst upgrade drove the move.\n\nIMPACT: Positive."
    doc["synopsis"]["market"] = {"line": "BBB has no cause for its move; the tape is red",
                                 "source_ids": ["market_risk:2026-11-09T01:00:00+00:00"]}
    assert "synopsis_says_no_cause_research_names_one" in codes(doc)


# ── one run ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_pieces_from_the_documents_own_run_are_same_run():
    r = C.run_check(brief())
    assert r["same_run"] is True and r["text"] is None and r["differing"] == []
    assert r["run_id"] == "cio-brief-test0001"


def test_a_piece_naming_another_run_is_a_mismatch():
    doc = brief()
    doc["stop_advice"][1]["run_id"] = "cio-brief-other"
    r = C.run_check(doc)
    assert r["same_run"] is False
    assert r["differing"][0]["piece"] == "stop_advice[BBB]"
    assert "cio-brief-other" in r["text"]


def test_a_piece_built_long_before_the_run_is_a_mismatch():
    doc = brief()
    doc["synopsis"]["as_of"] = "2026-11-08T23:30:00+00:00"  # 104 min before generated_at
    r = C.run_check(doc)
    assert r["same_run"] is False and "synopsis was built 104 min before this run" in r["text"]


def test_a_piece_within_the_tolerance_is_the_same_run():
    doc = brief()
    doc["synopsis"]["as_of"] = "2026-11-09T00:30:00+00:00"  # 44 min: a run's own steps finish apart
    assert C.run_check(doc)["same_run"] is True


def test_a_brief_without_a_run_id_is_not_vouched_for():
    doc = brief(run_id="")
    r = C.run_check(doc)
    assert r["same_run"] is False and "no run_id" in r["text"]


def test_a_piece_with_neither_id_nor_clock_is_listed_not_failed():
    doc = brief()
    doc["stop_advice"][1].pop("as_of")
    r = C.run_check(doc)
    assert r["same_run"] is True and r["unverifiable"] == ["stop_advice[BBB]"]


# ── the card's block carries the run ────────────────────────────────────────────────────────────────────────


def test_the_cards_cio_block_carries_the_briefs_run():
    block = SC.cio_brief_block(brief())
    assert block["status"] == "available"
    assert block["run_id"] == "cio-brief-test0001"
    assert block["run"]["run_id"] == "cio-brief-test0001" and block["run"]["same_run"] is True


def test_a_mixed_block_is_marked_in_the_card():
    doc = copy.deepcopy(brief())
    doc["synopsis"]["as_of"] = "2026-11-08T22:00:00+00:00"
    block = SC.cio_brief_block(doc)
    assert block["run"]["same_run"] is False and "synopsis was built" in block["run"]["text"]


def test_a_pending_block_has_no_run():
    assert SC.cio_brief_block(None) == {"status": "pending", "label": "CIO brief pending"}
