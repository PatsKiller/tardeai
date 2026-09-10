"""The wake composes a finding instead of a template claim — when, and only when,
there is something new to say.

Before this, every organic wake produced the same shape:

    "selection:unconsumed_research:f92f7e0b... warrants review"

An id and the words "warrants review": the machine-readable twin of the Telegram
alerts the operator described as "the same text day after day". The research that
caused the wake was never read.

These controls pin the three things that make composition safe to leave on:
the gate runs FIRST (no new evidence = no model call), the cap bounds a bad feed
day, and every existing decide guarantee survives.
"""
from __future__ import annotations

import json

import pytest

from scripts.lib import cio_wake_compose as cwc

ENV_ON = {"CIO_NARRATIVE_COMPOSITION_ENABLED": "1"}


@pytest.fixture()
def feed(tmp_path):
    p = tmp_path / "research.jsonl"
    rows = [
        {"subject_guid": "g1", "symbol": "AES", "content_hash": "h1",
         "title": "Filing A", "source_url": "https://reuters.com/a"},
        {"subject_guid": "g1", "symbol": "AES", "content_hash": "h2",
         "title": "Filing B", "source_url": "https://ft.com/b"},
        {"subject_guid": "OTHER", "symbol": "ZZZ", "content_hash": "h9"},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return {**ENV_ON, "TRADEAI_WAKE_RESEARCH_OBJECTS_PATH": str(p)}


def _ctx(**kw):
    base = {"wake_id": "w1", "agent_id": "cio", "subject_guid": "g1",
            "memory_facts": [], "comm_events": [], "operator_turns": [],
            "memory_empty": True,
            "selection": {"source": "unconsumed_research", "source_id": "r1",
                          "observed_at": "2026-09-10T13:45:00Z"}}
    base.update(kw)
    return base


def _narrator(**kw):
    return [{"sentence": "AES filed something material.", "cites": ["content_hash:h1"]}]


# --- the feed read ------------------------------------------------------------

def test_only_this_subjects_research_is_read(feed):
    got = cwc.research_for_subject("g1", feed)
    assert {r["content_hash"] for r in got} == {"h1", "h2"}


def test_a_missing_feed_is_empty_not_an_error(feed):
    assert cwc.research_for_subject("g1", {**feed, "TRADEAI_WAKE_RESEARCH_OBJECTS_PATH": "/nope"}) == []


# --- the flag -----------------------------------------------------------------

def test_disabled_by_default_returns_the_untouched_default_decision(feed):
    out = cwc.composing_decide(_ctx(), env={k: v for k, v in feed.items()
                                            if k != "CIO_NARRATIVE_COMPOSITION_ENABLED"},
                               narrator=_narrator)
    assert "narrative" not in out
    assert out["commitment"]["claim"].startswith("selection:")


# --- the gate runs BEFORE the model ------------------------------------------

def test_nothing_new_means_NO_model_call(feed):
    """The economics of leaving this on. A subject with nothing new costs zero."""
    called = []

    def narrator(**kw):
        called.append(1)
        return _narrator()

    ctx = _ctx(memory_facts=[{"fact_id": "f1",
                              "content": {"cited_ids": ["content_hash:h1", "content_hash:h2"]}}])
    out = cwc.composing_decide(ctx, env=feed, narrator=narrator)
    assert called == [], "the model was called for a subject with nothing new"
    assert out.get("composition_reason") == "no_change"
    assert "narrative" not in out


def test_new_evidence_composes_and_replaces_the_template_claim(feed):
    out = cwc.composing_decide(_ctx(), env=feed, narrator=_narrator)
    assert out["composition_reason"] == "first_view"
    assert out["commitment"]["claim"] == "AES filed something material."
    assert out["commitment"]["cited_ids"] == ["content_hash:h1"]
    assert out["narrative"]["subject_label"] == "AES"


# --- the cap ------------------------------------------------------------------

def test_the_per_process_cap_bounds_a_bad_feed_day(feed, monkeypatch):
    monkeypatch.setattr(cwc, "_composed_this_process", 0)
    env = {**feed, "CIO_NARRATIVE_MAX_PER_WAKE": "1"}
    first = cwc.composing_decide(_ctx(), env=env, narrator=_narrator)
    second = cwc.composing_decide(_ctx(subject_guid="g1"), env=env, narrator=_narrator)
    assert "narrative" in first
    assert second.get("composition_reason") == "capped"


# --- every existing guarantee survives ---------------------------------------

def test_a_refusing_decision_is_never_upgraded_into_speech(feed):
    """default_decide refuses when there is no memory and no selection. A
    composition layer must not turn a refusal into a statement."""
    out = cwc.composing_decide(_ctx(selection=None), env=feed, narrator=_narrator)
    assert out["act"] is False and "narrative" not in out


def test_the_original_selection_source_id_is_never_reminted(feed):
    out = cwc.composing_decide(_ctx(), env=feed, narrator=_narrator)
    assert out["primary_source_id"] == "r1"


def test_the_commitment_shape_is_preserved(feed):
    out = cwc.composing_decide(_ctx(), env=feed, narrator=_narrator)
    c = out["commitment"]
    assert c["commitment_kind"] == "SELECTION_OBSERVATION"
    assert c["normalized_claim"] and c["claim"]


def test_no_research_leaves_the_default_decision_alone(feed):
    out = cwc.composing_decide(_ctx(subject_guid="UNKNOWN"), env=feed, narrator=_narrator)
    assert "narrative" not in out
