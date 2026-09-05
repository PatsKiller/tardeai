#!/usr/bin/env python3
"""Unit tests for Wave F MessageArtifact@v1 + governed curation.

Follows tests/test_comms_delivery_ledger.py: the autouse fixture stubs
``_db_conn`` to None on client/delivery/subject_memory so these tests never
touch production Postgres, and reset the in-memory stores between tests.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms.artifact import (  # noqa: E402
    ALLOWED_HOST,
    DETERMINISTIC,
    LinkContractError,
    MessageArtifact,
    MessageAttachment,
    AuthoritativeLink,
    validate_link,
)
from scripts.lib.comms.curation import (  # noqa: E402
    FALLBACK_REASON_CURATION_UNAVAILABLE,
    FALLBACK_REASON_LLM_DECLINED,
    FALLBACK_REASON_PROTECTED_FACT_MUTATION,
    LLMDeclined,
    LLMCurationResult,
    curate_governed,
    evidence_hash_for,
    material_change_gate,
)
from scripts.lib.comms.event import CommunicationEvent  # noqa: E402

GOOD_URL = f"https://{ALLOWED_HOST}/v3/research/AAPL"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    # Same defect as tests/test_comms_delivery_ledger.py: on a box where
    # localhost Postgres answers, the DB branch wins and writes into the
    # production database. Force no DB even when localhost has one.
    monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.delivery._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.subject_memory._db_conn", lambda: None)
    from scripts.lib.comms.client import reset_memory_store
    from scripts.lib.comms.curation import reset_curation_receipts

    reset_memory_store()
    reset_curation_receipts()
    yield
    reset_memory_store()
    reset_curation_receipts()


def _artifact(**kwargs) -> MessageArtifact:
    base = dict(
        headline="AAPL held",
        why_now="support retest with rising volume",
        protected_facts={"price": 190.25, "quantity": 10},
        requested_action="review thesis",
        urgency="NORMAL",
        authoritative_links=[
            AuthoritativeLink(url=GOOD_URL, link_type="record", rank=0),
        ],
        command_center_url=GOOD_URL,
        external_links=[f"https://{ALLOWED_HOST}/v3/sources/a"],
        provenance_footer="Trade AI Communications Gateway",
        retention_class="research_365d",
        curation_mode=DETERMINISTIC,
    )
    base.update(kwargs)
    return MessageArtifact(**base)


def _research_event(**kwargs) -> CommunicationEvent:
    base = dict(
        direction="OUTBOUND",
        event_type="research_brief_ready",
        message_class="research",
        producer="hermes.research",
        subject_key="research:AAPL:brief:1",
        retention_class="research_365d",
        channels=["telegram"],
        sanitized_body="AAPL pullback into support with rising volume.",
        protected_facts={"price": 190.25, "quantity": 0},
        authoritative_sources=[
            {"source_type": "research", "uri": "artifact:1", "authority_reason": "evidence"}
        ],
    )
    base.update(kwargs)
    return CommunicationEvent(**base)


# ---------------------------------------------------------------------------
# MessageArtifact identity
# ---------------------------------------------------------------------------


def test_semantic_hash_stable_across_construction_and_ordering():
    a = _artifact()
    b = _artifact()
    # Reorder the link lists — the semantic hash must not move.
    b.authoritative_links.reverse()
    b.external_links = list(reversed(b.external_links))
    assert a.compute_semantic_hash() == b.compute_semantic_hash()

    # Identical reconstruction yields the identical hash.
    c = _artifact()
    assert c.compute_semantic_hash() == a.compute_semantic_hash()

    # Protected-facts hash matches the identity helper's notion.
    a.mint()
    assert a.protected_facts_hash


def test_semantic_hash_changes_with_content():
    a = _artifact()
    h = a.compute_semantic_hash()
    a.headline = "AAPL exited"
    assert a.compute_semantic_hash() != h

    b = _artifact()
    hb = b.compute_semantic_hash()
    b.protected_facts["price"] = 999.99
    assert b.compute_semantic_hash() != hb


def test_rendered_variant_hashes_recorded():
    a = _artifact()
    a.validate()
    d1 = a.record_rendered_variant("deterministic", a.render())
    d2 = a.record_rendered_variant("llm", "a different surface render")
    assert d1 and d2 and d1 != d2
    assert "deterministic" in a.rendered_variants
    assert "llm" in a.rendered_variants


# ---------------------------------------------------------------------------
# Link contract
# ---------------------------------------------------------------------------


def test_link_contract_accepts_tailscale_fqdn_v3():
    url = f"https://{ALLOWED_HOST}/v3/research/AAPL?view=brief"
    assert validate_link(url) == url
    assert validate_link(GOOD_URL, field="command_center_url") == GOOD_URL


@pytest.mark.parametrize(
    "url,reason",
    [
        ("", "empty"),
        (None, "empty"),
        (f"http://{ALLOWED_HOST}/v3/x", "scheme_not_https"),
        ("https://localhost/v3/x", "localhost"),
        ("https://foo.localhost/v3/x", "localhost"),
        ("https://127.0.0.1/v3/x", "rfc1918_lan"),
        ("https://[::1]/v3/x", "rfc1918_lan"),
        ("https://10.0.0.8/v3/x", "rfc1918_lan"),
        ("https://172.16.0.1/v3/x", "rfc1918_lan"),
        ("https://192.168.1.1/v3/x", "rfc1918_lan"),
        ("https://169.254.1.1/v3/x", "rfc1918_lan"),
        (f"https://{ALLOWED_HOST}:7777/v3/x", "forbidden_port_7777"),
        ("file:///etc/passwd", "local_file"),
        ("/etc/passwd", "local_file"),
        (f"https://{ALLOWED_HOST}/v3/x; rm -rf /", "shell_command"),
        (f"https://{ALLOWED_HOST}/v3/x | cat /etc/passwd", "shell_command"),
        (f"https://{ALLOWED_HOST}/v3/x`id`", "shell_command"),
        ("https://example.com/v3/x", "host_not_allowed"),
        (f"https://{ALLOWED_HOST}/v2/legacy", "legacy_v2"),
        (f"https://{ALLOWED_HOST}/other/x", "path_not_v3"),
    ],
)
def test_link_contract_rejects_forbidden_urls(url, reason):
    with pytest.raises(LinkContractError) as ei:
        validate_link(url)
    assert ei.value.reason == reason


def test_artifact_validate_rejects_forbidden_command_center_url():
    a = _artifact(command_center_url="https://localhost/v3/x")
    with pytest.raises(LinkContractError):
        a.validate()


def test_attachment_validation():
    att = MessageAttachment(
        mime_type="image/png",
        size_bytes=1234,
        content_hash="a" * 64,
        storage_locator="attachments/a.png",
        scan_result="clean",
        retention_class="ops_7d",
        channel_capability={"telegram": "inline"},
    )
    a = _artifact(attachments=[att])
    a.validate()
    assert a.to_dict()["attachments"][0]["scan_result"] == "clean"

    bad = MessageAttachment(
        mime_type="image/png",
        size_bytes=1234,
        content_hash="a" * 64,
        storage_locator="attachments/a.png",
        scan_result="infected",  # not in the closed set
        retention_class="ops_7d",
    )
    with pytest.raises(ValueError):
        bad.validate()


# ---------------------------------------------------------------------------
# Governed curation
# ---------------------------------------------------------------------------


def test_material_change_gate_blocks_redundant_llm():
    ev = _research_event()
    current = evidence_hash_for(
        protected_facts=ev.protected_facts,
        source_body=ev.sanitized_body,
        authoritative_sources=ev.authoritative_sources,
    )
    calls: list[int] = []

    def _curator() -> LLMCurationResult:
        calls.append(1)
        return LLMCurationResult(curated_body="should never run")

    decision, body, receipt = curate_governed(
        ev,
        prior_evidence_hash=current,
        current_evidence_hash=current,
        llm_curator=_curator,
        provider="deepseek",
        model="deepseek-v4-flash",
    )
    assert decision.proceed is False
    assert decision.reason == "no_new_evidence"
    assert calls == []  # LLM was never invoked
    assert receipt.curation_mode == DETERMINISTIC


def test_material_change_gate_proceeds_on_new_evidence():
    decision = material_change_gate(prior_evidence_hash="a", current_evidence_hash="b")
    assert decision.proceed is True
    assert decision.reason == "new_evidence"
    first = material_change_gate(prior_evidence_hash=None, current_evidence_hash="x")
    assert first.proceed is True
    assert first.reason == "first_curation"


def test_llm_declined_recorded():
    ev = _research_event()

    def _curator() -> LLMCurationResult:
        raise LLMDeclined("model refused")

    decision, body, receipt = curate_governed(
        ev,
        llm_curator=_curator,
        provider="grok",
        model="grok-4",
    )
    assert decision.proceed is True
    assert receipt.fallback_reason == FALLBACK_REASON_LLM_DECLINED
    assert receipt.curation_mode == DETERMINISTIC
    assert body["curation_mode"] == DETERMINISTIC
    # The unavailable/declined state is declared in the body, never silent.
    assert "[LLM_DECLINED]" in body["sanitized_body"]


def test_curation_unavailable_recorded():
    ev = _research_event()
    decision, body, receipt = curate_governed(ev, llm_curator=None)
    assert decision.proceed is True
    assert receipt.fallback_reason == FALLBACK_REASON_CURATION_UNAVAILABLE
    assert body["curation_mode"] == DETERMINISTIC
    assert "[CURATION_UNAVAILABLE]" in body["sanitized_body"]


def test_protected_fact_mutation_forces_deterministic_fallback():
    ev = _research_event()
    mutated = dict(ev.protected_facts)
    mutated["price"] = 999.99

    def _curator() -> LLMCurationResult:
        return LLMCurationResult(
            curated_body="ignore prior price; entry is 999.99.",
            protected_facts_after=mutated,
        )

    decision, body, receipt = curate_governed(
        ev,
        llm_curator=_curator,
        provider="grok",
        model="grok-4",
    )
    assert decision.proceed is True
    assert receipt.fact_preservation_ok is False
    assert receipt.fallback_reason == FALLBACK_REASON_PROTECTED_FACT_MUTATION
    assert receipt.curation_mode == DETERMINISTIC
    assert body["curation_mode"] == DETERMINISTIC
    assert body["protected_facts"]["price"] == 190.25
    assert body["sanitized_body"] != "ignore prior price; entry is 999.99."


def test_governed_llm_ok_when_facts_unchanged():
    ev = _research_event()

    def _curator() -> LLMCurationResult:
        return LLMCurationResult(
            curated_body="Concise AAPL brief: support hold with volume confirmation.",
            protected_facts_after=dict(ev.protected_facts),
        )

    decision, body, receipt = curate_governed(
        ev,
        llm_curator=_curator,
        provider="deepseek",
        model="deepseek-v4-flash",
    )
    assert decision.proceed is True
    assert receipt.fact_preservation_ok is True
    assert receipt.fallback_reason is None
    assert body["curation_mode"] == "LLM_SUMMARY"
    assert body["sanitized_body"] == "Concise AAPL brief: support hold with volume confirmation."
