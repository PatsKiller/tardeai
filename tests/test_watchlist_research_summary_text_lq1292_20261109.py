#!/usr/bin/env python3
"""LQ-20261107-1292 — a research card shows the summary sentence, never LLM JSON markup.

Page walk 2026-11-07 item 137: `/v3/manual-execution` path-a cards rendered
`'{ "summary": "MPWR is not held…'`. `/api/v2/watchlist/items` returns
`watchlist_research_cards.latest_summary` as `research_summary`, and 102 rows hold JSON text.

Cause: the writer (`scripts/process_watchlist_agent_jobs.py`) stores `parsed["summary"]`, and
`parse_agent_result`'s fallback stored `raw[:300]`. A model that answers in pretty-printed JSON and
is cut off mid-object defeats `extract_json_object` (no balanced brace), so the markup became the
summary — every one of those rows is exactly 300 chars, beginning `{\\n  "summary": `.

Fix, both sides of the wire:
  * writer: `summary_text()` recovers the sentence from complete *or truncated* JSON, and every
    parser that feeds a `watchlist_research_cards` write uses it;
  * reader: `summary_text()` unwraps rows already written (no DB backfill).

Synthetic fixtures only — no database, no live payload.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from cio_agent_contract import (  # noqa: E402
    parse_agent_result,
    parse_synthesis_result,
    summary_text,
)

SUMMARY = (
    "MPWR is not held and the industrial-power cycle still supports the thesis, but the "
    "valuation leaves no margin for a miss."
)


def _pretty_answer(*, recommendation="HOLD", extra=None) -> str:
    """The shape the agents actually return: pretty-printed JSON, one key per line.

    Deliberately longer than 300 chars so that `raw[:300]` — the writer's old cut — lands inside
    the object, which is exactly how the 102 stored rows came to be.
    """
    body = {"summary": SUMMARY, "recommendation": recommendation, "confidence": 0.62}
    body.update(extra or {})
    body.setdefault("next_action", "Wait for the next earnings print before adding exposure.")
    body.setdefault(
        "key_actions",
        "Trim nothing today; re-underwrite at the next print and size only against a confirmed order book.",
    )
    return json.dumps(body, indent=2)


# ── the helper ────────────────────────────────────────────────────────────────


def test_plain_text_is_unchanged():
    assert summary_text(SUMMARY) == SUMMARY
    assert summary_text("  " + SUMMARY + "\n") == SUMMARY


def test_none_is_empty_not_the_string_none():
    assert summary_text(None) == ""


def test_complete_json_object_yields_its_summary():
    assert summary_text(_pretty_answer()) == SUMMARY


def test_truncated_pretty_json_yields_the_sentence_not_the_markup():
    """The live defect: no closing brace, so json.loads() cannot help."""
    raw = _pretty_answer()
    truncated = raw[:300]
    assert truncated.startswith('{\n  "summary": ')  # exactly what the cards showed
    text = summary_text(truncated)
    assert not text.startswith("{")
    assert '"summary"' not in text
    assert SUMMARY.startswith(text) or text.startswith(SUMMARY.split(",")[0])
    assert len(text) > 40


def test_cut_inside_the_sentence_still_shows_a_sentence_fragment():
    """The old 300-char cut can land mid-value, leaving no closing quote at all."""
    frag = '{\n  "summary": "MPWR is not held and the industrial-power'
    assert summary_text(frag) == "MPWR is not held and the industrial-power"


def test_legacy_row_of_exactly_300_chars_is_fully_unwrapped():
    """Every one of the 102 stored rows is exactly 300 chars (writer's old raw[:300])."""
    legacy = _pretty_answer()[:300]
    assert len(legacy) == 300
    text = summary_text(legacy)
    assert not text.startswith("{")
    assert '"summary"' not in text
    assert "recommendation" not in text


def test_escaped_quotes_are_unescaped():
    raw = json.dumps({"summary": 'They said "wait" twice.', "recommendation": "HOLD"})
    assert summary_text(raw) == 'They said "wait" twice.'


def test_nested_dict_summary_is_flattened_never_str_of_dict():
    raw = json.dumps({"summary": {"summary": SUMMARY}, "recommendation": "HOLD"})
    assert summary_text(raw) == SUMMARY
    assert summary_text({"summary": {"summary": SUMMARY}}) == SUMMARY
    assert "{" not in summary_text({"summary": {"summary": SUMMARY}})


def test_json_without_a_summary_member_is_left_alone_not_blanked():
    raw = json.dumps({"recommendation": "HOLD", "confidence": 0.6}, indent=2)
    assert summary_text(raw) == raw.strip()


def test_json_with_no_summary_falls_back_to_its_action_sentence():
    """14 of the 102 stored rows are exactly this shape: recommendation + action, no summary."""
    raw = json.dumps(
        {"recommendation": "RESEARCH_MORE", "confidence": 0.35, "action": "Do not initiate until price data land."},
        indent=2,
    )[:300]
    assert summary_text(raw) == "Do not initiate until price data land."
    assert summary_text({"action": "Do not initiate until price data land."}) == (
        "Do not initiate until price data land."
    )


# ── the parsers the writer consumes ───────────────────────────────────────────


def test_parse_agent_result_does_not_store_markup_for_a_truncated_answer():
    """The writer stores parsed["summary"][:500]; that must be a sentence."""
    stored = parse_agent_result(_pretty_answer()[:300])["summary"][:500]
    assert not stored.startswith("{")
    assert '"summary"' not in stored
    assert SUMMARY.startswith(stored.rstrip(".")) or stored in SUMMARY


def test_parse_agent_result_still_salvages_the_recommendation():
    parsed = parse_agent_result(_pretty_answer(recommendation="HOLD")[:300])
    assert parsed["recommendation"] == "HOLD"


def test_parse_agent_result_complete_answer_is_unchanged():
    parsed = parse_agent_result(_pretty_answer(recommendation="TRIM"))
    assert parsed["summary"] == SUMMARY
    assert parsed["recommendation"] == "TRIM"
    assert parsed["confidence"] == 0.62


def test_parse_synthesis_result_complete_answer_stores_the_sentence():
    raw = json.dumps(
        {
            "summary": SUMMARY,
            "recommendation": "ADD",
            "synthesis_narrative": "Committee agrees.",
            "confidence": 0.7,
        }
    )
    parsed = parse_synthesis_result(raw)
    assert parsed["summary"] == SUMMARY
    assert parsed["recommendation"] == "ADD"


def test_parse_synthesis_result_truncated_answer_stores_the_sentence():
    raw = json.dumps(
        {"summary": SUMMARY, "recommendation": "ADD", "confidence": 0.7}, indent=2
    )[:300]
    parsed = parse_synthesis_result(raw)
    assert not parsed["summary"].startswith("{")
    assert '"summary"' not in parsed["summary"]


def test_the_writer_write_sites_only_ever_see_text():
    """Both `watchlist_research_cards` writes store parsed["summary"] — prove it is clean."""
    src = (ROOT / "scripts" / "process_watchlist_agent_jobs.py").read_text()
    assert 'latest_summary = %s, latest_recommendation' in src
    assert "latest_summary, latest_recommendation, confidence" in src
    for line in src.splitlines():
        if "latest_summary" in line:
            assert "raw" not in line, f"raw markup reaches a card write: {line.strip()}"
    # The value both sites bind is the parser's text, never the model's raw answer.
    assert 'parsed["summary"][:500]' in src


# ── the operator backfill (planner only — it never touches a database here) ───


def _planner():
    sys.path.insert(0, str(ROOT / "scripts" / "ops"))
    import backfill_watchlist_research_summary as mod

    return mod


def test_backfill_plans_only_json_shaped_rows_and_leaves_plain_text_alone():
    updates, stuck = _planner().plan(
        [
            ("MPWR", _pretty_answer()[:300]),
            ("CSCO", SUMMARY),
            ("ANET", json.dumps({"recommendation": "HOLD"}, indent=2)),
        ]
    )
    assert [u["symbol"] for u in updates] == ["MPWR"]
    assert not updates[0]["new"].startswith("{")
    assert SUMMARY.startswith(updates[0]["new"].rstrip("."))
    # A JSON row with no summary member is reported, never blanked or rewritten.
    assert "ANET" in {s["symbol"] for s in stuck}
    assert all(s["reason"] == "no-summary-member" for s in stuck if s["symbol"] == "ANET")
    # Plain text is never rewritten either.
    assert "CSCO" not in [u["symbol"] for u in updates]


def test_backfill_never_plans_a_blank_replacement():
    updates, stuck = _planner().plan([("X", json.dumps({"summary": ""}))])
    assert updates == []
    assert stuck and stuck[0]["reason"] == "empty-after-unwrap"
