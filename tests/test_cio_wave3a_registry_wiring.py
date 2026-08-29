"""Wave 3A — registry (one index) and corpus_hit wiring.

Split from the seasonality-move tests: these exercise cio_corpus_index and
cio_research_gate, which the R1 PR scope guard keeps out of any PR that touches
scripts/lib/research_governance/.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

def test_registry_is_one_index_over_both_populations():
    from scripts.lib.cio_corpus_index import registry

    r = registry()
    assert r["counts"]["library_facts"] == 11
    assert r["counts"]["catalog"] == 34
    assert r["freshness_law"].startswith("research_source_index")


def test_no_catalogued_work_can_corpus_hit():
    """34/34 are COPYRIGHT with no lawful full text -> grade D -> never closes."""
    from scripts.lib.cio_corpus_index import registry

    cat = registry()["catalog"]
    assert cat, "catalog did not load"
    assert all(c["evidence_grade"] == "D" for c in cat)
    assert not any(c["can_corpus_hit"] for c in cat)
    assert all(not c["on_disk"] for c in cat), (
        "a work reported as on-disk needs a real path, hash and re-grade")


def test_catalog_records_why_it_cannot_be_used():
    from scripts.lib.cio_corpus_index import registry

    c = registry()["catalog"][0]
    assert c["license_class"] == "COPYRIGHT"
    assert c["full_text_status"] == "NOT_FOUND_IN_FILE_LIBRARY"
    assert c["claim_status"] == "SOURCE_CLAIM_INCOMPLETE"


def test_registry_entries_carry_the_required_fields():
    from scripts.lib.cio_corpus_index import registry

    r = registry()
    for row in r["library_facts"] + r["catalog"]:
        for field in ("source_id", "family", "title", "path", "content_hash",
                      "as_of", "evidence_grade", "application_law",
                      "dimension_scope"):
            assert field in row, field


def test_stale_source_index_blocks_a_corpus_hit(monkeypatch):
    """Wave 3A wiring: new information must not be answered with old context."""
    from datetime import datetime, timezone

    import scripts.lib.research_source_index as rsi
    from scripts.lib.cio_research_gate import decide

    monkeypatch.setattr(rsi, "decide", lambda *a, **k: "RESEARCH_EXECUTED")
    now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    r = decide({"material": True, "kind": "held_core_thesis",
                "source_id": "s", "content_hash": "h",
                "corpus": {"closes": True, "reason": "corpus_fact_reproduced",
                           "source_refs": [{"source_id": "sta_x"}]}}, now=now)
    assert r["decision"] != "corpus_hit"


def test_fresh_source_still_allows_a_corpus_hit():
    from datetime import datetime, timezone

    from scripts.lib.cio_research_gate import decide

    now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    r = decide({"material": True, "kind": "held_core_thesis",
                "corpus": {"closes": True, "reason": "corpus_fact_reproduced",
                           "source_refs": [{"source_id": "sta_x"}],
                           "max_influence_pct": 10.0}}, now=now)
    assert r["decision"] == "corpus_hit"


def test_corpus_hit_uses_the_relocated_series():
    """Fixture tying the gate to the new library home (operator asked for 1-2)."""
    from scripts.lib.cio_corpus_index import consult, seasonality_context

    ctx = seasonality_context()
    assert ctx, "seasonality context empty — series did not resolve"
    r = consult("seasonality")
    assert r["closes"] is True
    assert r["seasonality"]["n"] == 75
