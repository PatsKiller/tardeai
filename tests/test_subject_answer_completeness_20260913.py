"""A question about a named stock is answered with everything the house holds on it.

Litmus 2026-09-13 21:59 EDT: "How is Visa doing, what's the supporting research,
what are the analyst recommendations and targets and dates". The reply was
"Research on file (options_desk)" and four covered-call rows, three identical,
one with 'edge 67.61000000000001'. It had no price, no levels and no analyst
line, and its Sources line still named yahoo_analyst_targets_history. On file:
close $370.45 (Sep 11), 30-day +1.7%, re-entry levels, and a Yahoo row from
Aug 28 (Strong Buy, 37 analysts, mean target $417.90), 16 days old.

These tests pin:
* research selection: operational notes out unless asked, one row per type,
  near-duplicates merged, substantive research first, float noise rounded
* the subject brief: price and 30-day change, levels, analysts with as-of date
  and age, research, and a plain "what this means" with a next step
* the Sources line names only what the reply shows
* a DeepSeek summary is used only when every number in it is in the brief and
  the close, mean target and as-of date survive; otherwise the brief is sent
* end to end, the Visa question gets price, levels, analysts and research

Offline: injected snapshot, rows and research; no database, no model.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import lib.cio_operator_desk_loop as desk  # noqa: E402

COVERS = ["scripts/lib/cio_operator_desk_loop.py", "scripts/lib/reply_provenance.py"]

VISA_Q = ("How is Visa doing what's the supporting research what are the analyst "
          "recommendations and targets and dates")

RAW_RESEARCH = [
    {"symbol": "V", "research_type": "options_desk", "topic": "V 2026-09-13 Options",
     "summary": "covered call: V Sell Covered Call: $395.0 2026-10-16 · edge 67.61000000000001 · POP 87.6%",
     "as_of": "2026-09-13"},
    {"symbol": "V", "research_type": "options_desk", "topic": "V 2026-09-13 Options",
     "summary": "covered call: V Sell Covered Call: $395.0 2026-10-16 · edge 66.18 · POP 87.6%", "as_of": "2026-09-13"},
    {"symbol": "V", "research_type": "options_desk", "topic": "V 2026-09-13 Options",
     "summary": "covered call: V Sell Covered Call: $395.0 2026-10-16 · edge 66.18 · POP 87.6%", "as_of": "2026-09-13"},
    {"symbol": "V", "research_type": "stop_curation", "topic": "Grok stop R:R review",
     "summary": "Grok stop curation [concern]: Stop quantity and position size are mismatched.", "as_of": "2026-09-11"},
    {"symbol": "V", "research_type": "stop_health", "topic": "Stop health: TRIGGERED",
     "summary": "TRIGGERED — stop FILLED — if fired: −$4,224,901 (−98.3% vs cost $21386.1)", "as_of": "2026-09-09"},
    {"symbol": "V", "research_type": "deep_research_local", "topic": "V deep research synthesis",
     "summary": "Prior notes reference a covered-call idea on V using a $390 strike expiring 2026-10-09.",
     "as_of": "2026-09-09"},
]

PRICE = {"V": {"close": 370.45, "price_date": "2026-09-11", "start_close": 364.21, "start_date": "2026-08-14",
               "change_30d_pct": 1.7, "stale": False}}
LEVELS = {"V": {"symbol": "V", "price": 370.45, "stop": 360.21, "target": 391.74,
                "resistance": {"state": "BELOW", "level": 384.06}, "sma_20": 368.1, "sma_50": 365.2, "rsi": 52.3}}
ANALYST = {"symbol": "V", "rating": "strong_buy", "rating_mean": 1.4, "target_low": 330.0, "target_mean": 417.9,
           "target_high": 460.0, "analysts": 37, "as_of": "2026-08-28", "age_days": 16, "stale": True,
           "source": "yahoo"}


def _avail():
    return {
        "subject_symbols": ["V"],
        "subject_price": PRICE,
        "subject_levels": LEVELS,
        "subject_levels_as_of": "2026-09-13T23:12:00-04:00",
        "analyst_view": {"items": [ANALYST], "symbols": ["V"]},
        "hermes_research": {"items": desk.select_subject_research(RAW_RESEARCH), "symbols": ["V"]},
    }


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setenv("CIO_SUBJECT_FLASH", "0")
    monkeypatch.setenv("CIO_REENTRY_FLASH", "0")
    monkeypatch.setattr(desk, "PENDING_PATH", tmp_path / "pending.jsonl")
    monkeypatch.setattr(desk, "_register_gaps", lambda *a, **k: {"registered": 0})
    monkeypatch.setattr(desk, "_enqueue_hermes_research", lambda *a, **k: {"ok": True})


# ── research selection ───────────────────────────────────────────────────────


def test_research_selection_puts_substance_first_and_collapses_the_options_repeats():
    got = desk.select_subject_research(RAW_RESEARCH)
    assert [g["research_type"] for g in got] == ["deep_research_local", "options_desk"]
    assert "67.61000000000001" not in got[1]["summary"] and "67.61" in got[1]["summary"]


def test_research_query_keeps_the_newest_rows_of_every_type():
    # Newest-first over all rows let 56 options-desk and 110 stop-curation rows
    # crowd out V's single deep-research note before selection ever saw it.
    sql = " ".join(desk.SUBJECT_RESEARCH_SQL.split())
    assert "PARTITION BY research_type ORDER BY created_at DESC" in sql and "WHERE rn <= %s" in sql
    assert "status = 'promoted'" in sql and desk.SUBJECT_RESEARCH_PER_TYPE >= 1


def test_operational_notes_only_when_the_question_is_about_stops():
    got = desk.select_subject_research(RAW_RESEARCH, include_operational=True)
    assert {"stop_curation", "stop_health"} <= {g["research_type"] for g in got}
    assert desk._STOP_QUESTION.search("where should my stop be on V")
    assert not desk._STOP_QUESTION.search(VISA_Q)


# ── the brief ────────────────────────────────────────────────────────────────


def test_brief_has_price_levels_analysts_research_and_meaning():
    brief = desk.format_subject_brief(["V"], _avail())
    assert "Price $370.45 (close Sep 11) · 30-day +1.7% from $364.21 on Aug 14" in brief
    assert "Levels (re-entry desk, computed Sep 13): stop $360.21 · target $391.74 · resistance $384.06" in brief
    assert ("Analysts (Yahoo, as of Aug 28, 16 days old, may be out of date): Strong Buy · 37 analysts · "
            "mean target $417.90 (low $330.00, high $460.00)") in brief
    assert "- Sep 09 · deep research: Prior notes" in brief and "options desk: covered call" in brief
    assert "stop_curation" not in brief and "4,224,901" not in brief
    meaning = next(line for line in brief.splitlines() if line.startswith("What this means:"))
    assert "3.7% below resistance $384.06" in meaning and "2.8% above the stop $360.21" in meaning
    assert "mean target $417.90 is 12.8% above the last close, but that view is 16 days old" in meaning
    # Auto-enqueue owns the operator ack; takeaway no longer prompts "say 'research V'".
    assert "House research for V is thin or missing." in meaning


def test_a_stock_off_the_desk_says_no_levels_are_on_file():
    avail = {**_avail(), "subject_levels": {}}
    assert "V is not on the re-entry desk, so no support, resistance or stop is on file." in \
        desk.format_subject_brief(["V"], avail)


def test_no_analyst_coverage_is_said_not_skipped():
    avail = {**_avail(), "analyst_view": {"items": [], "symbols": []}}
    assert "Analysts: no coverage on file for V." in desk.format_subject_brief(["V"], avail)


# ── curate + Sources ─────────────────────────────────────────────────────────


def _evidence():
    return {"available": _avail(), "gaps": [], "blocking_gaps": [], "complete": True,
            "sources": ["get_cio_snapshot", "ticker_prices", "/x/reentry_decision_desk_latest.json"]}


def test_curated_reply_shows_every_domain_its_sources_name():
    ev = _evidence()
    cur = desk._curate_from_evidence(VISA_Q, ev)
    assert cur["source"] == "tradeai_deterministic"
    text = desk._with_sources_footer(cur["text"], ev, cur)
    sources = next(line for line in text.splitlines() if line.startswith("Sources:"))
    assert "yahoo_analyst_targets_history" in sources and "Analysts (Yahoo" in text
    assert "ticker_prices (daily closes)" in sources and "Price $370.45" in text
    assert "hermes_research_intelligence" in sources and "Research on file:" in text


def test_a_faithful_flash_summary_is_used(monkeypatch):
    monkeypatch.setenv("CIO_SUBJECT_FLASH", "1")
    good = ("*V* closed at $370.45 on Sep 11, up 1.7% over 30 days, 3.7% below resistance $384.06.\n"
            "*Analysts:* Strong Buy, 37 analysts, mean target $417.90 as of Aug 28 — 16 days old.\n"
            "*Research:* thin, mostly options-desk notes. Say 'research V' to refresh.")
    monkeypatch.setattr(desk, "_subject_flash_call", lambda messages: {"ok": True, "content": good, "model": "deepseek-flash"})
    cur = desk._curate_from_evidence(VISA_Q, _evidence())
    assert cur["source"] == "deepseek_flash" and "$417.90" in cur["text"] and "READ_ONLY_ADVISORY" in cur["text"]


@pytest.mark.parametrize("bad,why", [
    ("*V* closed at $370.45 on Sep 11. Analysts: mean target $417.90 as of Aug 28, high $475.00.", "numbers_not_in_facts"),
    ("*V* closed at $370.45 on Sep 11 and analysts like it a lot, as of Aug 28 with plenty of upside ahead.", "missing:$417.90"),
    ("*V* closed at $370.45 on Sep 11. Mean target $417.90 as of Aug 28. Order placed for 10 shares today.", "banned_phrase"),
])
def test_an_unfaithful_flash_summary_is_rejected_and_the_brief_is_sent(monkeypatch, bad, why):
    monkeypatch.setenv("CIO_SUBJECT_FLASH", "1")
    monkeypatch.setattr(desk, "_subject_flash_call", lambda messages: {"ok": True, "content": bad, "model": "deepseek-flash"})
    brief = desk.format_subject_brief(["V"], _avail())
    out = desk.curate_subject_reply_with_flash(operator_text=VISA_Q, facts=brief, symbols=["V"],
                                               required=desk._subject_required_tokens(["V"], _avail()))
    assert out["ok"] is False and why in out["error"]
    cur = desk._curate_from_evidence(VISA_Q, _evidence())
    assert cur["source"] == "tradeai_deterministic" and cur["text"].startswith("*V*")


# ── end to end ───────────────────────────────────────────────────────────────


def test_the_visa_question_gets_price_levels_analysts_and_research(monkeypatch):
    import scripts.lib.data_broker.cio_portfolio as cp

    monkeypatch.setattr(cp, "get_cio_snapshot", lambda max_age_s=60: {"domains": {}})
    monkeypatch.setattr(desk, "analyze_operator_intent", lambda text: {
        "intent": "research", "needs": ["research", "analyst_view"], "symbols": ["V"], "source": "heuristic", "text": text})
    monkeypatch.setattr(desk, "subject_research",
                        lambda symbols, **k: desk.select_subject_research(RAW_RESEARCH, **k))
    monkeypatch.setattr(desk, "subject_analyst_view", lambda symbols, **k: [ANALYST])
    monkeypatch.setattr(desk, "subject_price_facts", lambda symbols, **k: PRICE)
    monkeypatch.setattr(desk, "_subject_levels", lambda symbols: (LEVELS, "2026-09-13T23:12:00-04:00", None))
    res = desk.handle_operator_desk_question(VISA_Q, chat_id="c", message_id="m")
    text = res.get("text") or ""
    assert res["kind"] == "answered", res.get("kind")
    for needle in ("Price $370.45", "Levels (re-entry desk", "Analysts (Yahoo, as of Aug 28", "Research on file:",
                   "What this means:"):
        assert needle in text, needle
    assert text.count("covered call") == 1, "the repeated options rows collapse to one"
