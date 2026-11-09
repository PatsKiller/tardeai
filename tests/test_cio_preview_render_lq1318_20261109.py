"""CIO_PREVIEW_RENDER_LQ1318_20261109 — a preview is a render of the brief document, never of prose.

LQ-20261107-1318 (operator 2026-11-08 20:22 ET: "why did we get two different results? why wasn't it uniform?").
The 18:00 preview was hand-composed and disagreed with Home, which renders ``latest.json``. This script closes that
gap by refusing any input that is not a ``CIOOvernightBrief@v1`` document, and by rendering every word from the
document's own rows: a HOLD row with an event states the event, the run id is on the page, and a brief whose pieces
come from different builds says so instead of looking uniform.

Hermetic: synthetic symbols and documents; the renderer is exercised in-process. No network, no database.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import cio_preview_render as R  # noqa: E402

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
            "source_ids": ["market_risk:2026-11-09T01:00:00+00:00"],
        },
        "summary": {"text": "AAA rose 4.00% on a bank downgrade (research).", "source": "llm"},
        "holdings": [
            {"symbol": "AAA", "news": [{"id": 1, "title": "Bank downgrades AAA"}],
             "research": {"status": "answered", "lane": "grok",
                          "text": "WHO/WHAT: A bank cut its rating (news:1).\n\nWHY: Weaker guidance.\n\nIMPACT: Negative."}},
            {"symbol": "BBB",
             "research": {"status": "answered", "lane": "grok",
                          "text": "WHO/WHAT: none.\n\nWHY: Evidence does not support a WHY for the move.\n\nIMPACT: None."}},
        ],
        "stop_advice": [
            {"symbol": "AAA", "account": "acct1", "answer": "RAISE", "event_summary": "Bank downgrades AAA",
             "suggested_stop": 120.46, "reason": "structure intact", "as_of": ASOF,
             "source_ids": ["news:1", "stop_last_known:AAA:acct1"]},
            {"symbol": "BBB", "account": "acct1", "answer": "HOLD", "event_summary": "BBB wins a contract",
             "as_of": ASOF, "source_ids": ["stop_last_known:BBB:acct1"]},
        ],
        "watchlist": [],
        "counts": {"selected": 2},
    }
    doc.update(over)
    return doc


def run(tmp_path: Path, doc, *extra: str) -> tuple[int, str, Path]:
    p = tmp_path / "brief.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    out = tmp_path / "preview.html"
    code = R.main(["--brief", str(p), "--out", str(out), *extra])
    return code, (out.read_text(encoding="utf-8") if out.exists() else ""), out


# ── it renders the document ─────────────────────────────────────────────────────────────────────────────────


def test_it_renders_the_briefs_own_words(tmp_path):
    code, page, out = run(tmp_path, brief())
    assert code == 0 and out.exists()
    assert "CIO — Home preview" in page
    assert "AAA needs a stop decision; BBB holds." in page          # the verdict is the document's
    assert "RED sector tape, not market-wide" in page               # the synopsis row is the document's
    assert "<b>cio-brief-test0001</b>" in page                      # the run is on the page
    assert "built Sun 11-08 20:14 ET" in page                       # the clock is the document's, in ET
    assert "advisory only" in page and "Advisory only." in page
    assert "No order is placed, sized or changed" in page


def test_the_same_document_renders_the_same_bytes(tmp_path):
    a = R.render(brief())
    b = R.render(brief())
    assert a == b and a.endswith("\n")


def test_it_names_the_counts_it_saw(tmp_path):
    page = R.render(brief())
    assert "Your actions · 1 stop change at Schwab" in page
    assert "ADD THE SELL STOP" not in page
    assert "EDIT THE STOP" in page          # RAISE
    assert "$120.46" in page


# ── the HOLD row that carries an event (the defect the operator saw) ────────────────────────────────────────


def test_a_hold_row_renders_its_event_never_a_bare_hold(tmp_path):
    page = R.render(brief())
    assert 'data-testid="stops-quiet"' in page
    assert "BBB (hold) — BBB wins a contract" in page
    assert "BBB (hold) —" in page


def test_a_hold_row_without_an_event_renders_the_bare_state():
    doc = brief()
    doc["stop_advice"][1].pop("event_summary")
    assert "BBB (hold)<" in R.render(doc)


def test_actions_are_ordered_by_urgency():
    doc = brief()
    doc["stop_advice"] = [
        {"symbol": "CCC", "answer": "RAISE", "as_of": ASOF, "source_ids": ["stop_last_known:AAA:acct1"]},
        {"symbol": "AAA", "answer": "ADD STOP", "as_of": ASOF, "source_ids": ["stop_last_known:AAA:acct1"]},
    ]
    page = R.render(doc)
    assert page.index("AAA") < page.index("CCC")  # an unprotected name before a stop that can wait
    assert "ADD A SELL STOP" in page


# ── a preview is never free text ───────────────────────────────────────────────────────────────────────────


def test_free_text_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("The book is calm; raise nothing today."))
    assert R.main(["--stdin", "--out", str(tmp_path / "x.html")]) == 2
    err = capsys.readouterr().err
    assert "a preview is never free text" in err
    assert not (tmp_path / "x.html").exists()


def test_json_that_is_not_a_brief_is_refused(tmp_path, capsys):
    for doc in ({}, {"schema": "SinceCloseCard@v1", "run_id": "x"}, {"hello": "world"},
                {"schema": "CIOOvernightBrief@v1", "run_id": "x"}):  # last one: no generated_at / synopsis
        code, page, out = run(tmp_path, doc)
        assert code == 2, doc
        assert not out.exists()
        assert "not a CIO overnight brief document" in capsys.readouterr().err


def test_a_missing_file_is_refused(tmp_path, capsys):
    assert R.main(["--brief", str(tmp_path / "nope.json")]) == 2
    assert "refused: cannot read" in capsys.readouterr().err


# ── the gate ───────────────────────────────────────────────────────────────────────────────────────────────


def test_check_passes_a_consistent_brief(tmp_path, capsys):
    p = tmp_path / "b.json"
    p.write_text(json.dumps(brief()), encoding="utf-8")
    assert R.main(["--brief", str(p), "--check"]) == 0
    out = capsys.readouterr().out
    assert "cio_brief_consistency PASS" in out and "0 finding(s)" in out


def test_check_fails_the_brief_whose_summary_contradicts_its_research(tmp_path, capsys):
    doc = brief()
    doc["holdings"][1]["research"]["text"] = "WHO/WHAT: none.\n\nWHY: A customer contract was announced.\n\nIMPACT: Positive."
    doc["summary"]["text"] = "BBB fell 2.00% and there is no cause for the move (research)."
    p = tmp_path / "b.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    assert R.main(["--brief", str(p), "--check"]) == 1
    out = capsys.readouterr().out
    assert "cio_brief_consistency FAIL" in out
    assert "summary_says_no_cause_research_names_one" in out


def test_a_page_rendered_from_a_failing_brief_still_says_which_brief_and_exits_1(tmp_path):
    doc = brief()
    doc["synopsis"]["do_now"] = {"line": "First: AAA in acct1 — RAISE"}  # no source_ids
    code, page, _ = run(tmp_path, doc)
    assert code == 1 and "cio-brief-test0001" in page  # the page is written; the exit code is the verdict


# ── one run, and escaping ──────────────────────────────────────────────────────────────────────────────────


def test_a_mixed_brief_says_so_on_the_page():
    doc = brief()
    doc["synopsis"]["as_of"] = "2026-11-08T22:00:00+00:00"
    page = R.render(doc)
    assert 'data-testid="cio-run-notice"' in page
    assert "synopsis was built" in page


def test_a_consistent_brief_carries_no_run_notice():
    assert 'data-testid="cio-run-notice"' not in R.render(brief())


def test_document_text_is_escaped():
    doc = brief()
    doc["synopsis"]["verdict"] = "AAA <script>alert(1)</script> & BBB"
    page = R.render(doc)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page and "&amp; BBB" in page


def test_the_run_id_in_the_title_is_escaped():
    doc = brief(run_id='x"><script>')
    page = R.render(doc)
    assert "<script>" not in page
