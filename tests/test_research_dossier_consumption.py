"""Lane C — research identity, dossier, consumption receipt tests."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from scripts.lib.research_object import build_research_object, validate_url
from scripts.lib.research_dossier import build_dossier, dedupe_research
from scripts.lib.research_consumption import (
    AgentViewState,
    consume_dossier,
    persist_receipt,
    load_receipts,
    MissingConsumptionReceipt,
    ReferentialIntegrityError,
)
from scripts.lib.campaign_interfaces_c import mint_research_object_id


CLOCK = lambda: datetime(2026, 9, 7, 15, 0, tzinfo=timezone.utc)


def _obj(symbol, guid, url, title, body, mentioned=None):
    return build_research_object(
        source_url=url,
        title=title,
        body=body,
        primary_symbol=symbol,
        primary_subject_guid=guid,
        mentioned=mentioned or [],
        published_at="2026-09-07T00:00:00Z",
        clock=CLOCK,
        producer="test",
        source_sha="fixture",
        provenance_extra={"producer": "test"},
    )


def test_url_and_provenance_validation():
    with pytest.raises(ValueError):
        validate_url("ftp://bad.example/x")
    with pytest.raises(ValueError):
        build_research_object(
            source_url="https://example.com/a",
            title="t",
            body="b",
            primary_symbol="V",
            primary_subject_guid="",
            clock=CLOCK,
        )


def test_primary_vs_mentioned_security():
    obj = _obj(
        "V",
        "guid-v",
        "https://www.reuters.com/finance/v-ma",
        "Visa and MA compared",
        "EARNINGS note",
        mentioned=[
            {"symbol": "MA", "subject_guid": "guid-ma", "role": "compared"},
            {"symbol": "PYPL", "subject_guid": "guid-pypl", "role": "mentioned"},
        ],
    )
    assert obj.primary_symbol() == "V"
    assert set(obj.mentioned_symbols()) == {"MA", "PYPL"}
    roles = {m["symbol"]: m["role"] for m in obj.mentions}
    assert roles["V"] == "primary"
    assert roles["MA"] == "compared"


def test_multi_security_article_retention():
    obj = _obj(
        "V",
        "guid-v",
        "https://www.bloomberg.com/news/v-ma-pypl",
        "Payments trio EARNINGS",
        "V MA PYPL",
        mentioned=[
            {"symbol": "MA", "subject_guid": "guid-ma", "role": "mentioned"},
            {"symbol": "PYPL", "subject_guid": "guid-pypl", "role": "mentioned"},
        ],
    )
    d = build_dossier(
        subject_guid="guid-v",
        primary_symbol="V",
        research_objects=[obj],
        clock=CLOCK,
    )
    assert obj.research_id in d.research_ids
    # Primary evidence present
    assert any(e["research_id"] == obj.research_id for e in d.primary_evidence)
    # Mentioned securities retained, not truncated to single subject
    mentioned_syms = {e.get("mentioned_symbol") for e in d.mentioned_evidence}
    assert "MA" in mentioned_syms and "PYPL" in mentioned_syms


def test_dossier_ranking_and_deduplication():
    a = _obj(
        "V", "guid-v",
        "https://www.sec.gov/Archives/v-1",
        "SEC filing",
        "body",
    )
    # Same content hash collision via duplicate url+body → same research_id path
    b = _obj(
        "V", "guid-v",
        "https://finance.yahoo.com/news/v-dup",
        "Yahoo copy EARNINGS",
        "other",
    )
    # Duplicate research_id injection
    dup = dict(a.to_dict())
    rows = dedupe_research([a.to_dict(), dup, b.to_dict()])
    ids = [r["research_id"] for r in rows]
    assert len(ids) == len(set(ids))
    # SEC ranks better than yahoo
    d = build_dossier(
        subject_guid="guid-v", primary_symbol="V",
        research_objects=[b, a], clock=CLOCK,
    )
    assert d.primary_evidence[0]["authoritative_source_rank"] <= d.primary_evidence[-1]["authoritative_source_rank"]


def test_consumption_receipt_referential_integrity(tmp_path: Path):
    obj = _obj(
        "V", "guid-v",
        "https://www.reuters.com/v-earnings",
        "V EARNINGS guidance cut DOWNGRADE",
        "material",
    )
    d = build_dossier(
        subject_guid="guid-v", primary_symbol="V",
        research_objects=[obj], clock=CLOCK,
    )
    view = AgentViewState(
        agent_id="agent-c-test",
        subject_guid="guid-v",
        next_research_question="old question",
        notify_priority="NORMAL",
        view_summary="old",
    )
    updated, receipt = consume_dossier(
        agent_id="agent-c-test",
        agent_version="test",
        dossier=d,
        view=view,
        purpose="wake_research",
        clock=CLOCK,
    )
    assert receipt.source_kind == "research_object"
    assert receipt.source_id == obj.research_id
    assert receipt.source_id in d.research_ids
    assert receipt.effect_kind == "changed_question"
    assert receipt.effect_ref
    assert updated.next_research_question != view.next_research_question
    path = tmp_path / "receipts.json"
    persist_receipt(receipt, path)
    rows = load_receipts(path)
    assert len(rows) == 1
    assert rows[0]["receipt_id"] == receipt.receipt_id


def test_relevant_research_changes_agent_irrelevant_does_not():
    relevant = _obj(
        "V", "guid-v",
        "https://www.reuters.com/v-down",
        "V DOWNGRADE after EARNINGS miss",
        "material event",
    )
    irrelevant = _obj(
        "V", "guid-v",
        "https://example.com/blog/color",
        "Nice logo redesign",
        "no material tokens here",
    )
    d_rel = build_dossier(
        subject_guid="guid-v", primary_symbol="V",
        research_objects=[relevant], clock=CLOCK,
    )
    d_irr = build_dossier(
        subject_guid="guid-v", primary_symbol="V",
        research_objects=[irrelevant], clock=CLOCK,
    )
    base = AgentViewState(
        agent_id="agent-c-test",
        subject_guid="guid-v",
        next_research_question="unchanged?",
        notify_priority="NORMAL",
        view_summary="base",
    )
    u1, r1 = consume_dossier(
        agent_id="agent-c-test", agent_version="t",
        dossier=d_rel, view=base, clock=CLOCK,
    )
    u2, r2 = consume_dossier(
        agent_id="agent-c-test", agent_version="t",
        dossier=d_irr, view=base, clock=CLOCK,
    )
    assert r1.effect_kind == "changed_question"
    assert u1.next_research_question != base.next_research_question
    assert r2.effect_kind == "none"
    assert u2.next_research_question == base.next_research_question
    # Explicit: isolated proof only — not organic maturity.
    assert r1.provenance["producer"] == "research_consumption"
    assert r1.source_sha == "fixture"


def test_missing_provenance_rejected():
    from scripts.lib.research_object import validate_provenance
    with pytest.raises(ValueError):
        validate_provenance({})
    with pytest.raises(ValueError):
        validate_provenance({"producer": "x"})  # missing inputs list


def test_single_subject_truncation_negative_control():
    """Negative control: a dossier builder that drops mentions must be detectable."""
    obj = _obj(
        "V", "guid-v",
        "https://www.bloomberg.com/multi",
        "Multi EARNINGS",
        "body",
        mentioned=[
            {"symbol": "MA", "subject_guid": "guid-ma", "role": "mentioned"},
            {"symbol": "PYPL", "subject_guid": "guid-pypl", "role": "mentioned"},
        ],
    )
    d = build_dossier(
        subject_guid="guid-v", primary_symbol="V",
        research_objects=[obj], clock=CLOCK,
    )
    # Detector: if mentioned_evidence empty while object has >1 mention → truncation
    assert len(obj.mentions) > 1
    truncated = len(d.mentioned_evidence) == 0
    assert truncated is False  # our builder retains them


def test_missing_consumption_receipt_negative_control():
    obj = _obj(
        "V", "guid-v",
        "https://www.reuters.com/v2",
        "V EARNINGS",
        "body",
    )
    d = build_dossier(
        subject_guid="guid-v", primary_symbol="V",
        research_objects=[obj], clock=CLOCK,
    )
    view = AgentViewState(agent_id="a", subject_guid="guid-other")
    with pytest.raises(ReferentialIntegrityError):
        consume_dossier(
            agent_id="a", agent_version="t", dossier=d, view=view, clock=CLOCK,
        )


def test_research_id_immutable_deterministic():
    a = mint_research_object_id(
        "https://www.reuters.com/v", "2026-09-07T00:00:00Z", "guid-v"
    )
    b = mint_research_object_id(
        "https://www.reuters.com/v", "2026-09-07T00:00:00Z", "guid-v"
    )
    assert a == b


def test_fixture_not_organic_tag():
    obj = _obj(
        "V", "guid-v",
        "https://www.reuters.com/v-fx",
        "V EARNINGS",
        "body",
    )
    assert obj.provenance.get("producer") == "test"
    d = build_dossier(
        subject_guid="guid-v", primary_symbol="V",
        research_objects=[obj], clock=CLOCK,
    )
    view = AgentViewState(agent_id="a", subject_guid="guid-v")
    _, receipt = consume_dossier(
        agent_id="a", agent_version="t", dossier=d, view=view, clock=CLOCK,
    )
    assert receipt.source_sha == "fixture"
    assert receipt.provenance.get("producer") == "research_consumption"
    # Explicit exclusion from maturity counts: fixture provenance.
    assert receipt.source_sha != "organic"


def test_duplicate_equivalent_inputs_do_not_double_write(tmp_path: Path):
    obj = _obj(
        "V", "guid-v",
        "https://www.reuters.com/v-dup2",
        "V EARNINGS DOWNGRADE",
        "body",
    )
    d = build_dossier(
        subject_guid="guid-v", primary_symbol="V",
        research_objects=[obj], clock=CLOCK,
    )
    view = AgentViewState(agent_id="a", subject_guid="guid-v")
    _, r1 = consume_dossier(
        agent_id="a", agent_version="t", dossier=d, view=view, clock=CLOCK,
    )
    _, r2 = consume_dossier(
        agent_id="a", agent_version="t", dossier=d, view=view, clock=CLOCK,
    )
    assert r1.receipt_id == r2.receipt_id  # idempotent identity
    path = tmp_path / "receipts.json"
    persist_receipt(r1, path)
    persist_receipt(r2, path)
    assert len(load_receipts(path)) == 1
