#!/usr/bin/env python3
"""An answer must be about the subject, not about the pipeline.

On 2026-09-11 the operator asked "What are the latest analyst predictions on
Walmart" and the desk replied, in full:

    Hermes: promoted=2502 staged=342 topics=[]
    READONLYADVISORY

Three separate defects in one message, one test file:

1. 2502 is every research row in the system; WMT had 3. The evidence domain
   carried counts with no symbol filter, so its value was identical for every
   question ever asked.
2. topics=[] came from `SELECT DISTINCT research_topic`, a column that has
   never existed on that table. The statement raised every time it ran and a
   bare except swallowed it.
3. READ_ONLY_ADVISORY -- the authority rail -- arrived as READONLYADVISORY
   because the reply was sent with parse_mode="Markdown", under which Telegram
   eats underscores.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DESK = ROOT / "scripts" / "lib" / "cio_operator_desk_loop.py"
PORTFOLIO = ROOT / "scripts" / "lib" / "data_broker" / "cio_portfolio.py"
REPLY = ROOT / "scripts" / "lib" / "cio_poller_reply.py"


def _code_strings(path: Path) -> set[str]:
    """String constants the CODE uses, with docstrings excluded.

    Prose that explains a trap contains the trap's name. A raw-source scan
    cannot tell the difference between documenting a defect and committing it,
    and three tests in this campaign have now failed on their own comments.
    """
    tree = ast.parse(path.read_text())
    docs: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and \
               isinstance(body[0].value, ast.Constant) and \
               isinstance(body[0].value.value, str):
                docs.add(id(body[0].value))
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docs}



# ── 1. counters are not an answer ──────────────────────────────────────────

def test_composer_never_renders_pipeline_counters():
    """The exact string the operator received must be unconstructable."""
    from scripts.lib.cio_operator_desk_loop import _curate_from_evidence

    avail = {"hermes_research": {
        "items": [{
            "symbol": "WMT", "research_type": "stop_curation",
            "topic": "Grok stop R:R review",
            "summary": "No active protection; stop is cancelled and coverage closed.",
            "confidence": 0.7, "as_of": "2026-09-11",
        }],
        "symbols": ["WMT"],
    }}
    out = _curate_from_evidence("latest analyst predictions on Walmart",
                                {"available": avail, "gaps": []})
    text = out.get("text") or ""
    assert "promoted=" not in text
    assert "staged=" not in text
    assert "topics=[]" not in text
    # and it says what the research actually contains
    assert "WMT" in text
    assert "stop" in text.lower()


def test_counts_are_gone_from_the_evidence_domain():
    """Not merely unrendered -- not collected. A value that is identical for
    every question cannot become evidence for any of them."""
    strings = _code_strings(DESK)
    for banned in ("promoted_research_count", "staged_research_count"):
        assert banned not in strings, banned


def test_no_subject_research_is_a_gap_even_when_the_pipeline_is_busy():
    from scripts.lib.cio_operator_desk_loop import subject_research

    # No symbol named -> nothing to be about -> no rows, no exception.
    assert subject_research([]) == []
    assert subject_research(["   "]) == []


def test_subject_research_degrades_to_empty_never_raises(monkeypatch):
    """Absent research is a legitimate state; a broken read must not be
    mistaken for one, but must also not make the wake flaky.

    The failure is INJECTED rather than produced by pointing at an unroutable
    host -- a real TCP connect would make this test hang for the OS timeout,
    which is how a test suite quietly becomes something nobody runs.

    The driver is injected as a FAKE MODULE rather than imported. The first
    version of this test did `import psycopg2` to reach its connect(), which
    passed locally and failed in CI with ModuleNotFoundError: CI is source-only
    and has no database driver installed. A test asserting that a broken
    database read degrades to empty must not itself require the database
    driver to import -- the environment it most needs to protect is the one
    without it.
    """
    import types

    fake = types.ModuleType("psycopg2")

    def boom(*a, **k):
        raise RuntimeError("connection refused")

    fake.connect = boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psycopg2", fake)

    import scripts.lib.cio_operator_desk_loop as D

    assert D.subject_research(["WMT"]) == []


def test_subject_research_filters_by_symbol_in_sql():
    """The filter must be in the query, not applied after a global fetch."""
    src = DESK.read_text()
    i = src.index("def subject_research(")
    body = src[i:i + 3000]
    assert "upper(symbol) = ANY(%s)" in body
    assert "status = 'promoted'" in body


# ── 2. the column that never existed ───────────────────────────────────────

def test_research_topic_column_is_not_referenced():
    strings = _code_strings(PORTFOLIO)
    joined = " ".join(strings)
    assert "research_topic" not in joined, "column does not exist on the table"
    assert "DISTINCT topic" in joined


def test_distinct_topic_query_is_valid_postgres():
    """SELECT DISTINCT x ORDER BY y is rejected by Postgres unless y is
    selected. Ordering by updated_at here would have replaced one silently
    swallowed error with another."""
    joined = " ".join(_code_strings(PORTFOLIO))
    i = joined.index("DISTINCT topic")
    stmt = joined[i:i + 240]
    if "ORDER BY" in stmt:
        order = stmt.split("ORDER BY", 1)[1][:40]
        assert "updated_at" not in order


# ── 3. the mangled authority rail ──────────────────────────────────────────

def test_reply_is_sent_as_plain_text():
    """READ_ONLY_ADVISORY must survive the wire. Markdown eats the underscores."""
    src = REPLY.read_text()
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
           and node.func.attr == "send_message":
            kw = {k.arg: k.value for k in node.keywords}
            assert "parse_mode" in kw, "parse_mode must be explicit, not defaulted"
            assert isinstance(kw["parse_mode"], ast.Constant)
            assert kw["parse_mode"].value is None
            found = True
    assert found, "no send_message call found"


def test_authority_footer_survives_plain_text():
    from scripts import telegram_transport as T

    body = "Research on file.\nREAD_ONLY_ADVISORY"
    payload = T._base_payload("1", body, thread_id=None, reply_markup=None,
                              parse_mode=None)
    assert "parse_mode" not in payload
    assert "READ_ONLY_ADVISORY" in payload["text"]


def test_suite_does_not_require_a_database_driver():
    """CI is source-only. A test file that imports psycopg2 at module or test
    scope passes locally and fails in CI -- which is what happened here."""
    tree = ast.parse(Path(__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert not a.name.startswith("psycopg2"), a.name
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("psycopg2"), node.module
