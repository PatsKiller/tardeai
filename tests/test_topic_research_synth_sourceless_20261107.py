"""A brief grounded on nothing is not research.

2026-11-07 DATA TRUTH audit, P0 defect 2: ``hermes:44896`` (CEF tax and income) has ``grounded_on: []``
and ``grounded_count: 0``, yet it was ``status: promoted``, labelled ``provenance_grade: "wire"``, and
asserted that "SSDI benefits themselves are generally excluded from MAGI calculations" — false, since the
taxable part of SSDI is in AGI and therefore in IRMAA MAGI. The model wrote that from memory because the
synthesizer called it with zero articles.

Three defences, all tested here with synthetic rows (no DB, no network, no model call):

1. the synthesizer refuses to synthesize when no article survives the relevance gate;
2. it refuses a brief whose claims share nothing with the sources it was grounded on;
3. the desk labels a grounding-tracked zero-source brief ``ungrounded`` (never ``wire``) and withholds
   its text, so the stored assertion stops reaching the operator.

What the trace does NOT do: it cannot tell a supported claim from a contradicted one. It answers "is
there a source that says this at all?", which is the question that separates 44896 (no sources) and the
Shanxi claim in 44932 (six sources, none mentioning it) from a brief that really rests on its citations.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TS = _load("topic_research_synth_sourceless", "scripts/topic_research_synthesizer.py")
RI = _load("research_intelligence_sourceless", "scripts/lib/research_intelligence.py")
NAR = _load("research_intelligence_narrative_sourceless", "scripts/lib/research_intelligence_narrative.py")
ARB = _load("analyst_report_builder_sourceless", "scripts/analyst_report_builder.py")


SOURCE = {"title": "CEFs implications: SSDI benefits and MAGI for IRMAA",
          "summary": "The taxable portion of SSDI benefits is included in AGI and therefore in MAGI.",
          "source": "IRS", "source_url": "https://example.invalid/ssdi-magi"}

#: The sentence the audit found in hermes:44896. No cited source says this; it is the claim the trace
#: check exists to catch.
FALSE_CLAIM = "SSDI benefits themselves are generally excluded from MAGI calculations because they are not wages."

CEF_SOURCE = {"title": "CEFs implications for income", "summary": "Funds pay monthly distributions.",
              "source": "Wire", "source_url": "https://example.invalid/cef"}


# ── 1. the claim trace ────────────────────────────────────────────────────────────────────────────
def test_a_claim_that_two_source_tokens_support_traces():
    assert TS._claim_traces("Taxable SSDI benefits count toward MAGI thresholds", [SOURCE])


def test_an_unsupported_ssdi_claim_does_not_trace_to_a_cef_source():
    """44896's actual shape: a retirement-tax claim and a source set that never mentions SSDI or MAGI."""
    assert not TS._claim_traces(FALSE_CLAIM, [CEF_SOURCE])


def test_one_shared_token_is_not_a_trace():
    """Homonyms and generic terms must not count; the relevance gate already learned this lesson."""
    assert not TS._claim_traces("Roth conversion strategy", [{"title": "Roth Capital conference",
                                                              "summary": "Banking news."}])


def test_no_sources_traces_nothing():
    assert not TS._claim_traces("Anything at all about Medicare Part B premiums", [])


def test_the_trace_counts_summary_prose_not_just_evidence_rows():
    """The false claim reached the desk as summary prose, so evidence[] alone is not enough to check."""
    result = {"summary": f"{FALSE_CLAIM} The fund also pays monthly distributions.",
              "evidence": [{"tag": "fact", "text": "CEF distributions can include return of capital."}]}
    trace = TS._claim_trace(result, [CEF_SOURCE])
    assert trace["claims"] >= 2, trace
    assert trace["untraced"] >= 1, trace
    assert any("excluded from MAGI" in s for s in trace["untraced_samples"]), trace


# ── 2. the producer refuses zero sources ──────────────────────────────────────────────────────────
class _FakeCursor:
    """Answers the three reads ``run()`` makes for one reground row; no DB."""

    def __init__(self, rows, news):
        self.rows = rows
        self.news = news
        self._result = []

    def execute(self, sql, params=None):
        if "FROM hermes_research_intelligence" in sql:
            self._result = list(self.rows)
        elif "FROM topic_monitor" in sql:
            self._result = [("Investor context", "CEF tax and income", ["CEF tax"])]
        elif "FROM news_articles" in sql:
            self._result = list(self.news)
        else:
            self._result = []

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


class _FakeConn:
    def __init__(self, rows, news):
        self.cur = _FakeCursor(rows, news)

    def cursor(self):
        return self.cur

    def commit(self):
        pass


ROW_44896 = (44896, "Tax and income implications of CEFs", {"topic_monitor_id": 7, "grounded_count": 0})


def _never_synthesize(monkeypatch):
    calls = []

    def _boom(*a, **k):
        calls.append(1)
        raise AssertionError("the model must not be called when no source survived the gate")

    monkeypatch.setattr(TS, "_synthesize", _boom)
    return calls


def test_zero_sources_refuses_to_synthesize(monkeypatch, capsys):
    """44896's exact shape: one row, no article — the model is never called and nothing is written."""
    calls = _never_synthesize(monkeypatch)
    monkeypatch.setattr(TS, "_get_conn", lambda: _FakeConn([ROW_44896], []))
    assert TS.run(apply=False, max_rows=5, reground=True) == 0
    capsys.readouterr()  # drain the run's own output
    assert calls == [], "synthesize was called with an empty source list"


def test_zero_sources_reports_the_refusal_reason(monkeypatch, capsys):
    _never_synthesize(monkeypatch)
    monkeypatch.setattr(TS, "_get_conn", lambda: _FakeConn([ROW_44896], []))
    TS.run(apply=False, max_rows=5, reground=True)
    out = capsys.readouterr().out
    assert TS.NO_SOURCES in out
    assert '"refused_no_sources": 1' in out


def test_an_off_topic_article_also_counts_as_no_source(monkeypatch, capsys):
    """The relevance gate can empty the list just as surely as a failed crawl."""
    calls = _never_synthesize(monkeypatch)
    news = [("Amazon earnings preview beats estimates", "Retail.", "Wire", "https://example.invalid/x")]
    monkeypatch.setattr(TS, "_get_conn", lambda: _FakeConn([ROW_44896], news))
    TS.run(apply=False, max_rows=5, reground=True)
    assert '"refused_no_sources": 1' in capsys.readouterr().out
    assert calls == []


def test_untraceable_claims_are_refused_even_when_a_source_exists(monkeypatch, capsys):
    """A source the claim does not restate is no better than no source (the Shanxi shape, 44932)."""
    monkeypatch.setattr(TS, "_get_conn", lambda: _FakeConn(
        [ROW_44896], [(CEF_SOURCE["title"], CEF_SOURCE["summary"], CEF_SOURCE["source"], CEF_SOURCE["source_url"])]))
    monkeypatch.setattr(TS, "_synthesize", lambda *a, **k: {
        "summary": f"{FALSE_CLAIM} {FALSE_CLAIM}", "thesis": "No.", "confidence": 0.4, "lane": "grok",
        "evidence": [{"tag": "fact", "text": FALSE_CLAIM}], "data_i_doubt": None,
        "agent_contract": None, "grounded_on": [{"title": CEF_SOURCE["title"], "source": "Wire", "url": None}],
    })
    assert TS.run(apply=False, max_rows=5, reground=True) == 0
    out = capsys.readouterr().out
    assert TS.NO_TRACEABLE_CLAIMS in out
    assert '"refused_untraceable": 1' in out


def test_a_traced_brief_is_still_written(monkeypatch, capsys):
    """The gate must not block a real, grounded brief — that would empty the desk."""
    monkeypatch.setattr(TS, "_get_conn", lambda: _FakeConn(
        [ROW_44896], [(SOURCE["title"], SOURCE["summary"], SOURCE["source"], SOURCE["source_url"])]))
    monkeypatch.setattr(TS, "_synthesize", lambda *a, **k: {
        "summary": "The taxable portion of SSDI benefits is included in AGI and therefore in MAGI thresholds.",
        "thesis": "Taxable SSDI counts.", "confidence": 0.5, "lane": "grok",
        "evidence": [{"tag": "fact", "text": "SSDI benefits and MAGI interact through AGI."}],
        "data_i_doubt": None, "agent_contract": None,
        "grounded_on": [{"title": SOURCE["title"], "source": "IRS", "url": SOURCE["source_url"]}],
    })
    assert TS.run(apply=False, max_rows=5, reground=True) == 0
    assert '"synthesized": 1' in capsys.readouterr().out


# ── 3. the desk grades and withholds ─────────────────────────────────────────────────────────────
def test_a_synth_brief_with_zero_grounded_sources_is_ungrounded_not_wire():
    out = NAR.enrich_narrative(title="CEF tax and income", summary="Text the model wrote from memory.",
                               cats=["retirement_tax"], research_type="topic_research", sources=[])
    assert out["provenance_grade"] == "ungrounded", out.get("provenance_grade")
    assert out["provenance_reason"] == "no_sources"


def test_a_stored_narrative_is_ungrounded_too_when_there_are_no_sources():
    """The stored-narrative branch had the same "wire" label; stored advisory text is no more grounded."""
    ev = {"narrative": {"executive_summary": ["SSDI is excluded from MAGI."]}}
    out = NAR.enrich_narrative(title="CEF tax and income", summary="", evidence_json=ev,
                               cats=["retirement_tax"], research_type="topic_research", sources=[])
    assert out["provenance_grade"] == "ungrounded"
    assert out["provenance_reason"] == "no_sources"


def test_a_grounded_brief_keeps_its_provenance():
    out = NAR.enrich_narrative(title="CEF tax and income", summary="Grounded text.", cats=["retirement_tax"],
                               research_type="topic_research", sources=[SOURCE])
    assert out.get("provenance_grade") != "ungrounded"


def test_the_withheld_predicate_needs_an_explicit_zero():
    """Absent means not grounding-tracked; unreadable means unknown. Neither is evidence of zero."""
    assert RI._is_ungrounded_synth("synth:grok", {"grounded_count": 0}) is True
    assert RI._is_ungrounded_synth("synth:grok", {"grounded_count": "0"}) is True
    assert RI._is_ungrounded_synth("synth:grok", {"grounded_count": 3}) is False
    assert RI._is_ungrounded_synth("synth:grok", {}) is False
    assert RI._is_ungrounded_synth("synth:grok", {"grounded_count": "many"}) is False
    assert RI._is_ungrounded_synth("deep_research_local", {"grounded_count": 0}) is False
    assert RI._is_ungrounded_synth(None, {"grounded_count": 0}) is False


def test_the_item_withholds_the_text_and_says_why():
    item = {"summary": FALSE_CLAIM, "thesis": "t", "sources": [{"url": "x"}], "source_count": 1,
            "provenance_grade": "wire", "quality_tier": "B", "confidence": 0.35,
            "key_questions": ["Does SSDI count?"], "data_gaps": ["No source dates"]}
    out = RI._withhold_ungrounded(dict(item), "promoted")
    assert out["summary"] == RI.WITHHELD_SUMMARY
    assert FALSE_CLAIM not in json.dumps(out), "the unsourced assertion must not survive in the item"
    assert out["sources"] == [] and out["source_count"] == 0
    assert out["confidence"] is None and out["key_questions"] == [] and out["data_gaps"] == [], \
        "nothing derived from the withheld text stays on the card"
    assert out["provenance_grade"] == "ungrounded" and out["provenance_reason"] == "no_sources"
    assert out["publish_state"] == "withheld_ungrounded"
    assert out["quality_tier"] == "ungrounded", "a withheld brief must not claim a quality tier"
    assert out["grounding"] == {"grounded_count": 0, "withheld": True, "stored_status": "promoted"}
    assert "withheld" in out["next_action_label"].lower()


# ── 4. the Intelligence Deep Dive report must not republish what the desk withholds ──────────────
def _report_rows(*rows):
    return list(rows)


def _row(topic, summary, research_type="topic_research", model="synth:grok", ev=None):
    return {"topic": topic, "summary": summary, "research_type": research_type,
            "model_used": model, "evidence_json": ev if ev is not None else {"grounded_count": 0},
            "created_at": None}


def test_the_deep_report_drops_a_withheld_brief_and_says_how_many(monkeypatch):
    """The report reads the store directly, so it calls the desk's predicate instead of restating it."""
    sql_seen = {}

    def _fake_query(sql, params=None, fetch="all"):
        sql_seen["sql"] = sql
        return _report_rows(
            _row("CEF tax and income", FALSE_CLAIM),
            _row("Coking coal", "Grounded text.", ev={"grounded_count": 4}),
            _row("Older advisory", "Advisory text.", research_type="protection_advisory",
                 model="deep_research_local", ev={}),
        )

    monkeypatch.setattr(ARB, "_db_query", _fake_query)
    kept, withheld = ARB._recent_research_rows("CEF", 7)
    assert "model_used" in sql_seen["sql"] and "evidence_json" in sql_seen["sql"], \
        "the query must select the two columns the withhold rule needs"
    assert withheld == 1
    assert len(kept) == 2, "only the ungrounded topic brief is dropped"
    assert FALSE_CLAIM not in json.dumps(kept)
    bullets = ARB._hermes_bullets(kept, withheld)
    assert any("1 brief(s) withheld" in b for b in bullets), bullets
    assert not any(FALSE_CLAIM in b for b in bullets)


def test_a_report_with_only_withheld_briefs_explains_instead_of_claiming_none_matched(monkeypatch):
    """A silent empty section would read as "no research" — it is research the desk refused to publish."""
    monkeypatch.setattr(ARB, "_db_query", lambda sql, params=None, fetch="all": _report_rows(
        _row("CEF tax and income", FALSE_CLAIM)))
    kept, withheld = ARB._recent_research_rows("CEF", 7)
    assert kept == [] and withheld == 1
    assert ARB._hermes_bullets(kept, withheld) == [
        "1 brief(s) withheld — written without sources, so not shown here."]


def test_the_report_rule_is_the_desk_rule_not_a_copy(monkeypatch):
    """One implementation: the builder asks ``lib.research_intelligence``, it does not carry a copy.

    The spy answers "withhold" for a model prefix a local copy would never match, so the row can only
    be dropped if the builder really called the shared predicate.
    """
    import lib.research_intelligence as desk
    seen = []

    def spy(model, ev):
        seen.append((model, ev))
        return True

    monkeypatch.setattr(desk, "is_withheld_synth", spy)
    monkeypatch.setattr(ARB, "_db_query", lambda sql, params=None, fetch="all": _report_rows(
        _row("Anything", "text", model="not-a-synth-prefix", ev={})))
    kept, withheld = ARB._recent_research_rows(None, 7)
    assert seen and seen[0][0] == "not-a-synth-prefix", "the builder must ask the desk's rule"
    assert kept == [] and withheld == 1
