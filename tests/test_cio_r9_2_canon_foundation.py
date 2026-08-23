from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.cio_canon_v1 import (
    append_claim_candidate,
    admit_canon_source,
    build_canon_claim,
    build_methodology_policy,
    catalog_maturity,
    transition_claim,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config/cio_research_source_catalog.json"


def _admitted(tmp_path: Path):
    source_path = tmp_path / "owned.md"
    source_path.write_text("# Chapter 1\n\nDiversification reduces idiosyncratic risk.\n", encoding="utf-8")
    return admit_canon_source(
        source_id="malkiel_random_walk",
        source_path=source_path,
        catalog_path=CATALOG,
        lawful_basis="LAWFUL_PRIVATE",
        operator_authorized=True,
        edition="operator-owned test edition",
        verified_at="2026-08-23T15:00:00+00:00",
    )


def test_current_catalog_remains_honestly_source_incomplete() -> None:
    maturity = catalog_maturity(CATALOG)
    assert maturity["catalog_total"] == 34
    assert maturity["source_text_present"] == 0
    assert maturity["missing_sources"] == 34
    assert maturity["source_claim_incomplete"] == 34
    assert maturity["ratified_claim_ids"] == []
    assert maturity["rag_target"] == "content_embeddings"
    assert maturity["new_vector_database"] is False


def test_source_admission_requires_explicit_lawful_operator_authorization(tmp_path: Path) -> None:
    source_path = tmp_path / "book.txt"
    source_path.write_text("lawful operator fixture", encoding="utf-8")
    with pytest.raises(PermissionError, match="operator authorization"):
        admit_canon_source(
            source_id="malkiel_random_walk",
            source_path=source_path,
            catalog_path=CATALOG,
            lawful_basis="LAWFUL_PRIVATE",
            operator_authorized=False,
            edition="fixture",
        )
    with pytest.raises(ValueError, match="lawful_basis"):
        admit_canon_source(
            source_id="malkiel_random_walk",
            source_path=source_path,
            catalog_path=CATALOG,
            lawful_basis="UNKNOWN",
            operator_authorized=True,
            edition="fixture",
        )


def test_text_extraction_preserves_source_hash_and_locator(tmp_path: Path) -> None:
    source, chunks = _admitted(tmp_path)
    assert source["schema"] == "CanonSource@v1"
    assert source["ingestion_state"] == "EXTRACTED"
    assert source["operator_authorized"] is True
    assert len(source["source_hash"]) == 64
    assert chunks[0]["locator"].startswith("lines ")
    assert chunks[0]["source_hash"] == source["source_hash"]
    assert chunks[0]["rag_status"] == "STAGED_NOT_INDEXED"
    assert chunks[0]["rag_target"] == "content_embeddings"


def test_claim_requires_admitted_source_and_exact_chunk(tmp_path: Path) -> None:
    source, chunks = _admitted(tmp_path)
    claim = build_canon_claim(
        source_record=source,
        chunk=chunks[0],
        claim_summary="Diversification can reduce idiosyncratic risk.",
        domain="portfolio_construction",
        asset_class="multi_asset",
        claim_type="PRINCIPLE",
    )
    assert claim["schema"] == "CanonClaim@v1"
    assert claim["status"] == "EXTRACTED"
    assert claim["decision_eligible"] is False
    assert claim["exact_source_locator"] == chunks[0]["locator"]
    bad_chunk = dict(chunks[0], source_hash="different")
    with pytest.raises(ValueError, match="source/chunk mismatch"):
        build_canon_claim(
            source_record=source,
            chunk=bad_chunk,
            claim_summary="bad",
            domain="risk",
            asset_class="equity",
            claim_type="PRINCIPLE",
        )


def test_books_do_not_automatically_become_methodology(tmp_path: Path) -> None:
    source, chunks = _admitted(tmp_path)
    claim = build_canon_claim(
        source_record=source,
        chunk=chunks[0],
        claim_summary="Diversification can reduce idiosyncratic risk.",
        domain="portfolio_construction",
        asset_class="multi_asset",
        claim_type="PRINCIPLE",
    )
    assert build_methodology_policy([claim])["ratified_advisory_claim_ids"] == []
    reviewed = transition_claim(claim, target_status="REVIEWED", review_receipt="review_1")
    shadow = transition_claim(reviewed, target_status="SHADOW", shadow_receipt="shadow_1")
    with pytest.raises(PermissionError, match="operator ratification"):
        transition_claim(shadow, target_status="RATIFIED_ADVISORY")
    ratified = transition_claim(shadow, target_status="RATIFIED_ADVISORY", operator_ratified=True)
    policy = build_methodology_policy([claim, reviewed, shadow, ratified])
    assert policy["ratified_advisory_claim_ids"] == [claim["claim_id"]]
    assert policy["automatic_promotion"] is False
    assert policy["financial_action"] is False


def test_quantitative_claim_needs_validation_before_ratification(tmp_path: Path) -> None:
    source, chunks = _admitted(tmp_path)
    claim = build_canon_claim(
        source_record=source,
        chunk=chunks[0],
        claim_summary="A quantitative rule candidate.",
        domain="portfolio_construction",
        asset_class="equity",
        claim_type="QUANTITATIVE_RULE",
    )
    reviewed = transition_claim(claim, target_status="REVIEWED", review_receipt="review_1")
    shadow = transition_claim(reviewed, target_status="SHADOW", shadow_receipt="shadow_1")
    with pytest.raises(ValueError, match="validation receipt"):
        transition_claim(shadow, target_status="RATIFIED_ADVISORY", operator_ratified=True)
    ratified = transition_claim(
        shadow,
        target_status="RATIFIED_ADVISORY",
        operator_ratified=True,
        validation_receipt="governed_validation_1",
    )
    assert ratified["decision_eligible"] is True


def test_claim_candidate_append_is_idempotent(tmp_path: Path) -> None:
    source, chunks = _admitted(tmp_path)
    claim = build_canon_claim(
        source_record=source,
        chunk=chunks[0],
        claim_summary="Diversification can reduce idiosyncratic risk.",
        domain="portfolio_construction",
        asset_class="multi_asset",
        claim_type="PRINCIPLE",
    )
    store = tmp_path / "claims.jsonl"
    first = append_claim_candidate(claim, store_path=store)
    second = append_claim_candidate(claim, store_path=store)
    assert first["appended"] is True
    assert second == {"appended": False, "reason": "DUPLICATE_CLAIM_ID", "claim_id": claim["claim_id"]}
    assert len(store.read_text(encoding="utf-8").splitlines()) == 1


def test_canon_foundation_has_no_network_download_or_execution_surface() -> None:
    for relative in (
        "scripts/lib/cio_canon_v1.py",
        "scripts/ingest_canon_source.py",
        "scripts/create_canon_claim_candidate.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8").lower()
        for forbidden in ("requests.get", "urlopen", "wget", "curl ", "place_order", "cancel_order", "modify_stop", "broker_client"):
            assert forbidden not in source
