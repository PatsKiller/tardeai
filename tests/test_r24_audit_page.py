"""R24 Audit page: render data.items; no marketing; no R20-R24 live claim."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.control_plane_contract_v1 import load_fixture

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "apps/command-center-v3/src/pages/control-plane/r24"

SECTIONS = [
    "Architecture",
    "Authority",
    "Runtime",
    "Stores",
    "Agent roster",
    "Research routes",
    "Model routes",
    "Evidence",
    "Known gaps",
    "Reproduction commands",
]

CLAIM_FIELDS = [
    "claim_id",
    "claim",
    "implementation_ref",
    "test_ref",
    "evidence_ref",
    "evidence_class",
    "limitations",
    "reproduction_command",
]


def test_audit_fixture_is_not_ready_and_has_claim_fields():
    """Labeled FIXTURE unit: ControlPlane@v1.0.0 audit payload remains NOT_READY."""
    doc = load_fixture("audit")
    payload = doc["payload"]
    assert payload["readiness"] == "NOT_READY"
    assert payload["known_gaps"]
    assert payload["claims"]
    for claim in payload["claims"]:
        for field in CLAIM_FIELDS:
            assert field in claim
        assert "R20-R24 live" not in claim["claim"]


def test_frozen_audit_json_matches_integrator_fixture():
    """Labeled FIXTURE: vendored JSON stays byte-equal; it is not the live view."""
    fixture = json.loads((ROOT / "fixtures/control_plane/v1.0.0/audit.json").read_text(encoding="utf-8"))
    frozen = json.loads((PAGES / "frozen/audit.json").read_text(encoding="utf-8"))
    assert frozen == fixture


def test_audit_page_has_required_sections_and_claim_fields():
    src = (PAGES / "AuditPage.tsx").read_text(encoding="utf-8")
    types = (PAGES / "payloadTypes.ts").read_text(encoding="utf-8")
    combined = src + "\n" + types
    for label in SECTIONS:
        assert label in combined
    for field in CLAIM_FIELDS:
        assert field in src
    assert "data.items" in src
    assert "payload.claims" in src  # labeled FIXTURE path
    assert "payload.known_gaps" in src
    assert "reproduction_command" in src
    assert "readiness" in src
    assert "absent" in src


def test_audit_page_has_no_marketing_or_live_program_claim():
    src = "\n".join(
        p.read_text(encoding="utf-8")
        for p in PAGES.glob("*.tsx")
    ) + "\n" + "\n".join(
        p.read_text(encoding="utf-8")
        for p in PAGES.glob("*.ts")
    )
    lowered = src.lower()
    assert "does not claim r20-r24 live" in lowered or "not claim r20-r24 live" in lowered
    assert "no marketing claims" in lowered
    assert "r20-r24 live" in lowered  # the negation sentence
    assert "world-class" not in lowered
    assert "production-ready" not in lowered
    assert "battle-tested" not in lowered
    assert "certified live" not in lowered
    assert "mission accomplished" not in lowered
    # The live claim flag is hardcoded false in the view model.
    assert "liveClaim: false" in src
    assert "CONTROL_PLANE_API_V1_BASELINE" in src
    assert "UNAVAILABLE" in src
    assert "NOT_READY" in json.dumps(load_fixture("audit")["payload"])
    hook = (PAGES / "useControlPlaneEnvelope.ts").read_text(encoding="utf-8")
    assert "keeping FIXTURE" not in hook
