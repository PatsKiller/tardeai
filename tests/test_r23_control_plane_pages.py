"""R23 Command Center pages consume CONTROL_PLANE_API_V1_BASELINE summary GET APIs."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.control_plane_contract_v1 import SCHEMA, load_fixture, validate_envelope

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "apps/command-center-v3/src/pages/control-plane/r23"
PREVIEW = PAGES / "preview"
CONTRACT_TS = ROOT / "apps/command-center-v3/src/control-plane/contractV1.ts"
FETCH = PAGES / "fetchControlPlaneSummary.ts"

PAGE_FILES = {
    "research": PAGES / "ResearchAttentionPage.tsx",
    "data": PAGES / "DataIntegrityPage.tsx",
    "identity": PAGES / "IdentityPage.tsx",
    "notifications": PAGES / "NotificationsPage.tsx",
}

SUMMARY_GET = {
    "research": "/api/v3/control-plane/research",
    "stores": "/api/v3/control-plane/stores",
    "identity": "/api/v3/control-plane/identity",
    "notifications": "/api/v3/control-plane/notifications",
}

CANONICAL_FILES = {
    "research": "data/runtime/research_attention.json",
    "stores": "data/runtime/canonical_store_registry.json or store_registry.json",
    "identity": "data/runtime/identity_registry.json",
    "notifications": "data/runtime/notification_receipts.json",
}

RESEARCH_FIELDS = [
    "universe",
    "active set",
    "due",
    "event-woken",
    "why now",
    "why not now",
    "research gap",
    "source usage",
    "llm eligibility",
    "cost",
    "yield",
]

STORE_FIELDS = [
    "logical store",
    "physical root",
    "persistent root",
    "writer",
    "readers",
    "freshness",
    "duplicates",
    "quarantine",
    "orphans",
    "schema",
]

IDENTITY_FIELDS = [
    "issuer",
    "security",
    "listing",
    "ticker alias",
    "cik",
    "figi",
    "isin",
    "cusip",
    "confirmed",
    "candidate",
    "unresolved_with_reason",
]

NOTIFICATION_FIELDS = [
    "candidate",
    "classification",
    "canary",
    "interdict",
    "renderer",
    "delivery",
    "receipt",
    "dedupe",
]


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _all_page_source() -> str:
    parts = []
    for path in sorted(PAGES.rglob("*")):
        if path.suffix in {".ts", ".tsx"}:
            parts.append(_src(path))
    return "\n".join(parts)


def test_r23_page_files_exist_under_control_plane_dir():
    assert PAGES.is_dir()
    for name, path in PAGE_FILES.items():
        assert path.is_file(), name
    assert (PAGES / "index.ts").is_file()
    assert (PAGES / "ControlPlaneFrame.tsx").is_file()
    assert FETCH.is_file()
    assert (PAGES / "useControlPlaneSummary.ts").is_file()


def test_preview_json_is_byte_identical_to_frozen_fixtures_and_labeled_fixture():
    preview_src = _src(PAGES / "previewEnvelopes.ts")
    assert "FIXTURE" in preview_src
    assert "NOT live page data" in preview_src or "not live page data" in preview_src.lower()
    assert "UNAVAILABLE" in preview_src
    for name in ("research", "stores", "identity", "notifications"):
        canonical = json.loads((ROOT / "fixtures/control_plane/v1.0.0" / f"{name}.json").read_text(encoding="utf-8"))
        preview = json.loads((PREVIEW / f"{name}.json").read_text(encoding="utf-8"))
        assert preview == canonical
        assert validate_envelope(preview) == []
        assert preview["schema"] == SCHEMA == "ControlPlane@v1.0.0"


def test_pages_do_not_default_to_preview_json():
    for name, path in PAGE_FILES.items():
        text = _src(path)
        assert "from './previewEnvelopes'" not in text, name
        assert "RESEARCH_PREVIEW" not in text, name
        assert "STORES_PREVIEW" not in text, name
        assert "IDENTITY_PREVIEW" not in text, name
        assert "NOTIFICATIONS_PREVIEW" not in text, name
        assert "envelope = RESEARCH_PREVIEW" not in text
        assert "payload.rows" not in text
        assert "payload.stores" not in text


def test_fetch_helper_uses_get_summary_urls_and_baseline_envelope():
    text = _src(FETCH)
    assert "CONTROL_PLANE_API_V1_BASELINE" in text
    assert "084674c560abd7bb910726f62e41508703c07e40" in text
    assert "method: 'GET'" in text
    assert "method: 'POST'" not in text
    assert "method: 'PUT'" not in text
    assert "method: 'PATCH'" not in text
    assert "method: 'DELETE'" not in text
    for url in SUMMARY_GET.values():
        assert url in text, url
    for path in CANONICAL_FILES.values():
        assert path in text, path
    for key in ("ok", "as_of", "source_sha", "freshness", "data_quality", "evidence_class", "data"):
        assert key in text, key
    assert "items" in text
    assert "pagination" in text
    assert "live_claim=false" in text


def test_view_state_distinguishes_unavailable_empty_valid_invalid_schema():
    text = _src(FETCH)
    frame = _src(PAGES / "ControlPlaneFrame.tsx")
    combined = text + "\n" + frame
    for state in (
        "UNAVAILABLE",
        "INVALID_SCHEMA",
        "STALE",
        "DEGRADED",
        "EMPTY_VALID",
        "AVAILABLE",
    ):
        assert state in combined, state
    assert "pagination.total === 0" in text
    assert "quality === 'AVAILABLE'" in text
    assert "if (quality === 'UNAVAILABLE') return 'UNAVAILABLE'" in text
    assert "if (quality === 'INVALID_SCHEMA') return 'INVALID_SCHEMA'" in text
    assert "NOT EMPTY_VALID" in frame
    assert "pagination.total===0" in frame or "pagination.total === 0" in frame
    # Pages must read data_quality, not ok.
    assert "read data_quality, not ok" in text
    assert "UNAVAILABLE still has ok:true" in text


def test_pages_bind_to_matching_get_urls():
    mapping = {
        "research": SUMMARY_GET["research"],
        "data": SUMMARY_GET["stores"],
        "identity": SUMMARY_GET["identity"],
        "notifications": SUMMARY_GET["notifications"],
    }
    files = {
        "research": CANONICAL_FILES["research"],
        "data": CANONICAL_FILES["stores"],
        "identity": CANONICAL_FILES["identity"],
        "notifications": CANONICAL_FILES["notifications"],
    }
    for name, url in mapping.items():
        text = _src(PAGE_FILES[name])
        assert url in text, name
        assert "useControlPlaneSummary" in text, name
        assert files[name] in text or files[name] in _src(FETCH)
        assert "absent" in text
        assert "live_claim=false" in text


def test_research_attention_shows_required_columns_without_fixture_subjects_as_live():
    text = _src(PAGE_FILES["research"]).lower()
    for field in RESEARCH_FIELDS:
        assert field in text, field
    assert "displayitemfield(row, 'subject_id')" in text
    assert "schd" not in text
    assert "tail1" not in text
    fixture_src = _src(PREVIEW / "research.json")
    assert "SCHD" in fixture_src
    assert "why_now" in fixture_src
    assert "llm_eligibility" in fixture_src
    assert "source_usage" in fixture_src
    preview = load_fixture("research")
    subjects = [row["subject_id"] for row in preview["payload"]["rows"]]
    assert "SCHD" in subjects
    assert "TAIL1" in subjects


def test_data_integrity_shows_canonical_store_registry_shape_without_recompute():
    text = _src(PAGE_FILES["data"]).lower()
    for field in STORE_FIELDS:
        assert field in text, field
    assert "canonicalstoreregistry" in text
    assert "does not recompute freshness" in text
    assert "duplicate_count" in _src(PAGE_FILES["data"])
    assert "orphan_count" in _src(PAGE_FILES["data"])
    preview = load_fixture("stores")
    logical = [row["logical_store"] for row in preview["payload"]["stores"]]
    assert "cio.operator_product.current" in logical
    page = _src(PAGE_FILES["data"])
    assert "cio.operator_product.current" not in page


def test_identity_shows_spine_and_contract_states_without_minting():
    text = _src(PAGE_FILES["identity"])
    lower = text.lower()
    for field in IDENTITY_FIELDS:
        assert field in lower, field
    assert "NO MINT CONTROL" in text
    assert "NEVER mint security_guid from ticker" in text
    assert "never_mint_from_ticker" in text
    assert "CONFIRMED" in text
    assert "CANDIDATE" in text
    assert "UNRESOLVED_WITH_REASON" in text
    preview = load_fixture("identity")
    assert preview["payload"]["never_mint_from_ticker"] is True
    states = {row["state"] for row in preview["payload"]["rows"]}
    assert states >= {"CONFIRMED", "CANDIDATE", "UNRESOLVED_WITH_REASON"}


def test_identity_does_not_substitute_ticker_for_entity_id():
    text = _src(PAGE_FILES["identity"])
    assert "entity_id ||" not in text
    assert "aliases[0]" not in text
    assert "mint" in text.lower()
    assert "displayItemField(row, 'entity_id')" in text
    assert "not filled from ticker alias" in text.lower() or "not filled from ticker" in text.lower()


def test_notifications_show_funnel_and_receipt_fields_without_computing_eligibility():
    text = _src(PAGE_FILES["notifications"])
    lower = text.lower()
    for field in NOTIFICATION_FIELDS:
        assert field in lower, field
    assert "computes_notification_eligibility=false" in text
    assert "does not compute notification eligibility" in lower
    assert "does not decide notification class" in lower
    assert "displayItemField(row, 'class')" in text
    assert "displayItemField(row, 'canary')" in text
    assert "not synthesized" in lower or "not ui-computed" in lower
    preview = load_fixture("notifications")
    assert "CANDIDATE" in preview["payload"]["funnel"]
    assert "n1" in _src(PREVIEW / "notifications.json")
    assert "n1" not in text


def test_pages_do_not_infer_cio_runtime_or_maturity():
    src = _all_page_source()
    forbidden = [
        "inferRuntime",
        "inferMaturity",
        "inferNotification",
        "computeMaturity",
        "computeCio",
        "computes_cio_decisions=true",
        "computes_agent_state=true",
        "computes_maturity=true",
        "computes_notification_eligibility=true",
    ]
    for token in forbidden:
        assert token not in src, token
    assert "computes_cio_decisions" in src
    assert "computes_maturity" in src
    assert "READ_ONLY_ADVISORY" in src


def test_envelope_flags_are_rendered_not_recomputed():
    frame = _src(PAGES / "ControlPlaneFrame.tsx")
    for key in (
        "ok",
        "as_of",
        "evidence_class",
        "source_sha",
        "data_quality",
        "freshness",
        "authority",
        "memory_behavior_influence",
        "computes_cio_decisions",
        "computes_agent_state",
        "computes_maturity",
        "computes_notification_eligibility",
        "financial_action",
        "live_claim",
    ):
        assert key in frame, key
    assert "not a LIVE claim" in frame
    assert "UNAVAILABLE" in frame
    assert "EMPTY_VALID" in frame
    assert "INVALID_SCHEMA" in frame


def test_missing_item_fields_render_absent():
    display = _src(PAGES / "display.ts")
    assert 'ABSENT = \'absent\'' in display or 'ABSENT = "absent"' in display
    assert "hasOwnProperty.call(item, key)" in display
    assert "return ABSENT" in display
    for path in PAGE_FILES.values():
        assert "displayItemField" in _src(path)


def test_index_exports_all_four_pages_and_intended_routes():
    text = _src(PAGES / "index.ts")
    assert "ResearchAttentionPage" in text
    assert "DataIntegrityPage" in text
    assert "IdentityPage" in text
    assert "NotificationsPage" in text
    assert "fetchControlPlaneSummary" in text
    routes = _src(PAGES / "r23Routes.ts")
    assert "/control-plane/research" in routes
    assert "/control-plane/data" in routes
    assert "/control-plane/identity" in routes
    assert "/control-plane/notifications" in routes
    assert "Not registered" in routes or "Not registered" in text
    assert "CONTROL_PLANE_API_V1_BASELINE" in routes


def test_frozen_contract_file_still_does_not_infer():
    src = CONTRACT_TS.read_text(encoding="utf-8")
    assert "ControlPlane@v1.0.0" in src
    assert "inferRuntime" not in src
