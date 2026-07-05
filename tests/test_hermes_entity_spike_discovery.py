#!/usr/bin/env python3
"""Entity-spike discovery (URDL Stage 3, spec Part E) test suite.

Pure synthetic-data tests — the DB seam (entity_spikes._execute) and the
inbox write path (inbox.upsert_candidate) are monkeypatched, so the whole
suite runs under TRADE_AI_CI with no PostgreSQL.

    .venv/bin/python -m pytest tests/test_hermes_entity_spike_discovery.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.hermes_discovery import dedupe, entity_spikes  # noqa: E402

# ── synthetic fixtures ────────────────────────────────────────────────────────

def _row(entity_type, value, n, n_sources, sources=None, sample="", stream="entity_links"):
    return {"entity_type": entity_type, "entity_value": value, "n": n,
            "n_sources": n_sources,
            "sources": sources or [f"src{i}" for i in range(n_sources)],
            "sample": sample, "stream": stream}


SPIKING = _row("topic", "quantum networking breakout", n=12, n_sources=4)
FLAT = _row("topic", "fed rate path", n=10, n_sources=5)          # baseline 9 → lift ~1.1
SINGLE_SOURCE = _row("topic", "one outlet obsession", n=9, n_sources=1)
RARE = _row("topic", "barely mentioned thing", n=1, n_sources=3)
TICKER_SPIKE = _row("ticker", "ABCD", n=8, n_sources=3)

PRIOR = {
    ("topic", "quantum networking breakout"): 2,   # lift 6.0
    ("topic", "fed rate path"): 9,                 # lift ~1.1 → filtered
    ("topic", "one outlet obsession"): 1,
    # TICKER_SPIKE + RARE absent → new entities
}


def _spikes(current=None, prior=None, **kw):
    kw.setdefault("min_recurrence", 2)
    kw.setdefault("min_sources", 2)
    return entity_spikes.compute_spikes(
        current if current is not None else [SPIKING, FLAT, SINGLE_SOURCE, RARE, TICKER_SPIKE],
        prior if prior is not None else PRIOR, **kw)


# ── detection gates ──────────────────────────────────────────────────────────

def test_spike_detected_on_synthetic_lift():
    spikes = _spikes()
    labels = {s["entity_value"] for s in spikes}
    assert "quantum networking breakout" in labels
    spike = next(s for s in spikes if s["entity_value"] == "quantum networking breakout")
    assert spike["lift"] == 6.0
    assert spike["current_count"] == 12 and spike["prior_count"] == 2
    assert spike["new_entity"] is False


def test_flat_term_not_a_spike():
    assert "fed rate path" not in {s["entity_value"] for s in _spikes()}


def test_cross_source_gate():
    skipped = {}
    spikes = _spikes(skipped=skipped)
    assert "one outlet obsession" not in {s["entity_value"] for s in spikes}
    assert skipped.get("low_cross_source", 0) >= 1
    # loosening the gate lets it through (it has lift 9x)
    loose = _spikes(min_sources=1)
    assert "one outlet obsession" in {s["entity_value"] for s in loose}


def test_recurrence_gate():
    skipped = {}
    spikes = _spikes(skipped=skipped)
    assert "barely mentioned thing" not in {s["entity_value"] for s in spikes}
    assert skipped.get("low_recurrence", 0) >= 1


def test_new_entity_lift_capped():
    spike = next(s for s in _spikes() if s["entity_value"] == "ABCD")
    assert spike["new_entity"] is True
    assert spike["lift"] <= entity_spikes.LIFT_CAP
    big = _row("topic", "meme explosion", n=500, n_sources=6)
    capped = entity_spikes.compute_spikes([big], {}, min_recurrence=2, min_sources=2)
    assert capped[0]["lift"] == entity_spikes.LIFT_CAP


def test_momentum_signal_normalized_and_bounded():
    assert 0.0 <= entity_spikes.momentum_signal(0.0) <= 1.0
    assert entity_spikes.momentum_signal(entity_spikes.LIFT_FULL_SCALE) == 1.0
    assert entity_spikes.momentum_signal(999.0, relevant=True) == 1.0
    plain = entity_spikes.momentum_signal(3.0)
    boosted = entity_spikes.momentum_signal(3.0, relevant=True)
    assert boosted == pytest.approx(plain + entity_spikes.RELEVANCE_BOOST)


# ── payload building: coverage dedupe + candidate typing ─────────────────────

def test_covered_key_deduped_but_distinct_subtopic_passes():
    spikes = _spikes()
    covered = {dedupe.normalize_key("quantum networking breakout")}
    skipped = {}
    payloads = entity_spikes.build_payloads(
        spikes, covered=covered, relevant_syms=set(), skipped=skipped)
    labels = {p["label"] for p in payloads}
    assert "quantum networking breakout" not in labels
    assert skipped.get("covered_by_directive_or_topic") == 1
    # a distinct normalized_key (subtopic) is NOT suppressed
    sub = _row("topic", "quantum networking chip suppliers", n=10, n_sources=3)
    sub_payloads = entity_spikes.build_payloads(
        entity_spikes.compute_spikes([sub], {}, min_recurrence=2, min_sources=2),
        covered=covered, relevant_syms=set())
    assert len(sub_payloads) == 1


def test_candidate_types_and_safe_action_level():
    payloads = entity_spikes.build_payloads(_spikes(), covered=set(), relevant_syms=set())
    by_label = {p["label"]: p for p in payloads}
    topic = by_label["quantum networking breakout"]
    ticker = by_label["ABCD news attention spike"]
    assert topic["candidate_type"] == "TOPIC_CANDIDATE"
    assert ticker["candidate_type"] == "TREND_CANDIDATE"
    assert ticker["seed_symbols"] == ["ABCD"]
    for p in payloads:
        assert p["safe_action_level"] == "OPERATOR_REVIEW_REQUIRED"
        assert p["evidence"], "evidence refs required"
        assert 0.0 <= p["signals"]["trend_momentum"] <= 1.0
        assert p["meta"]["producer"] == entity_spikes.PRODUCER
        assert p["meta"]["spike"]["cross_source_count"] >= 2


def test_relevance_boost_applied_to_watchlist_symbol():
    # lift 2.0 (below LIFT_FULL_SCALE) so the boost is visible pre-clamp
    row = _row("ticker", "ABCD", n=8, n_sources=3)
    spikes = lambda: entity_spikes.compute_spikes(
        [row], {("ticker", "abcd"): 4}, min_recurrence=2, min_sources=2)
    plain = entity_spikes.build_payloads(spikes(), covered=set(), relevant_syms=set())
    boosted = entity_spikes.build_payloads(spikes(), covered=set(), relevant_syms={"ABCD"})
    get = lambda ps: next(p for p in ps if p["label"] == "ABCD news attention spike")
    assert get(boosted)["signals"]["trend_momentum"] > get(plain)["signals"]["trend_momentum"]
    assert get(boosted)["meta"]["holdings_or_watchlist_relevant"] is True


def test_run_cap_respected():
    many = [_row("topic", f"hot theme number {i}", n=10, n_sources=3) for i in range(30)]
    spikes = entity_spikes.compute_spikes(many, {}, min_recurrence=2, min_sources=2)
    skipped = {}
    payloads = entity_spikes.build_payloads(spikes, covered=set(), relevant_syms=set(),
                                            limit=5, skipped=skipped)
    assert len(payloads) == 5
    assert skipped.get("run_cap") == 25


# ── full run with monkeypatched DB seam + inbox ───────────────────────────────

def _fake_execute_factory(directive_labels=(), topic_names=()):
    """Synthetic _execute covering every SQL this module issues."""
    def fake_execute(sql, params=None, fetch=None):
        s = " ".join(sql.split()).lower()
        if "information_schema.tables" in s:
            return {"ok": 1}
        if "from content_entity_links" in s and "group by 1, 2" in s and "n_sources" in s:
            return [dict(r) for r in (SPIKING, FLAT, SINGLE_SOURCE, RARE, TICKER_SPIKE)]
        if "from content_entity_links" in s:
            return [{"entity_type": t, "entity_value": v, "n": n}
                    for (t, v), n in PRIOR.items()]
        if "from hermes_research_intelligence" in s and "n_sources" in s:
            return []
        if "from hermes_research_intelligence" in s:
            return []
        if "from watch_directives" in s:
            return [{"label": lb, "spec": {}} for lb in directive_labels]
        if "from topic_monitor" in s:
            return [{"display_name": nm} for nm in topic_names]
        if "from watchlist_items" in s:
            return [{"symbol": "ABCD"}]
        raise AssertionError(f"unexpected SQL in test: {s[:120]}")
    return fake_execute


def test_run_discovery_dry_run_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setattr(entity_spikes, "_execute", _fake_execute_factory())
    called = []
    monkeypatch.setattr(entity_spikes.inbox, "upsert_candidate",
                        lambda **kw: called.append(kw) or {"id": 1})
    report = entity_spikes.run_discovery(dry_run=True)
    assert report["dry_run"] is True
    assert called == [], "dry-run must not write the inbox"
    assert report["spikes_detected"] == 2  # quantum topic + ABCD ticker
    assert report["would_upsert"] == 2 and report["upserted"] == 0
    assert report["by_type"] == {"TOPIC_CANDIDATE": 1, "TREND_CANDIDATE": 1}
    # domain populated (registered registry domain) for every candidate
    for c in report["candidates"]:
        assert c["domain"] and c["domain"] != "unclassified"
        assert c["spike"]["lift"] >= entity_spikes.MIN_LIFT


def test_run_discovery_live_writes_via_inbox_only(monkeypatch):
    monkeypatch.setattr(entity_spikes, "_execute", _fake_execute_factory())
    captured = []

    def fake_upsert(**kw):
        captured.append(kw)
        return {"id": len(captured), "status": "DISCOVERED", "seen_count": 1,
                "discovery_score": 0.5,
                "meta_json": {"research_domain": "macro"}}

    monkeypatch.setattr(entity_spikes.inbox, "upsert_candidate", fake_upsert)
    report = entity_spikes.run_discovery(dry_run=False)
    assert report["upserted"] == 2 == len(captured)
    for kw in captured:
        assert kw["actor"] == entity_spikes.ACTOR
        assert kw["safe_action_level"] == "OPERATOR_REVIEW_REQUIRED"
        assert "trend_momentum" in kw["signals"]
    # research_domain surfaced from the persisted row
    assert all(c["research_domain"] == "macro" for c in report["candidates"])


def test_run_discovery_directive_coverage_dedupe(monkeypatch):
    monkeypatch.setattr(entity_spikes, "_execute", _fake_execute_factory(
        directive_labels=["Quantum networking breakout"]))
    monkeypatch.setattr(entity_spikes.inbox, "upsert_candidate",
                        lambda **kw: pytest.fail("must not upsert"))
    report = entity_spikes.run_discovery(dry_run=True)
    labels = {c["label"] for c in report["candidates"]}
    assert "quantum networking breakout" not in labels
    assert report["skipped_reasons"].get("covered_by_directive_or_topic") == 1


def test_missing_tables_skip_gracefully(monkeypatch):
    def no_tables(sql, params=None, fetch=None):
        if "information_schema.tables" in sql:
            return None  # table absent
        return []
    monkeypatch.setattr(entity_spikes, "_execute", no_tables)
    report = entity_spikes.run_discovery(dry_run=True)
    assert report["spikes_detected"] == 0
    assert any("content_entity_links" in n for n in report["notes"])
    assert any("hermes_research_intelligence" in n for n in report["notes"])


def test_subject_and_domain_enrichment_path():
    """Payloads flow through the Stage-1 enrichment: classify_domain accepts
    them and build_subject yields a populated subject envelope."""
    from lib.hermes_discovery import domains, subjects
    payload = entity_spikes.build_payloads(_spikes(), covered=set(),
                                           relevant_syms=set())[0]
    view = {"candidate_type": payload["candidate_type"], "label": payload["label"],
            "summary": payload["summary"], "meta": payload["meta"],
            "evidence": payload["evidence"],
            "seed_symbols": payload.get("seed_symbols") or []}
    domain = domains.classify_domain(view)
    assert domain in domains.load_domains()
    subject = subjects.build_subject(view, domain)
    assert subject["subject_id"].startswith("subj_")
    assert subject["canonical_label"] == payload["label"]
    assert subject["domain"] == domain
    assert subject["safe_action_level"] in ("OPERATOR_REVIEW_REQUIRED",)


# ── HARD RULE: no broker/execution/promotion imports, no threshold writes ─────

FORBIDDEN_IMPORT_RE = re.compile(
    r"^\s*(from|import)\s+\S*(schwab|alpaca|broker|execution|order|trade_exec|"
    r"snaptrade|promotion|atm_|paper_trading|live_trading)", re.IGNORECASE)

MODULE_FILES = [
    ROOT / "scripts" / "lib" / "hermes_discovery" / "entity_spikes.py",
    ROOT / "scripts" / "hermes_entity_spike_discovery.py",
]


@pytest.mark.parametrize("path", MODULE_FILES, ids=lambda p: p.name)
def test_no_broker_execution_or_promotion_imports(path):
    src = path.read_text(encoding="utf-8")
    hits = [line for line in src.splitlines() if FORBIDDEN_IMPORT_RE.match(line)]
    assert not hits, f"forbidden import(s) in {path.name}: {hits}"
    # never transitions/promotes candidates, never touches trading thresholds
    # or execution surfaces
    low = src.lower()
    for token in ("transition_candidate", "decide_candidate", "promoted_to_watch",
                  "trading_threshold", "adaptive_threshold", "hermes_maturity_gates",
                  "submit_order", "place_order", "schwab", "alpaca", "execute_trade"):
        assert token not in low, f"forbidden token {token!r} in {path.name}"
