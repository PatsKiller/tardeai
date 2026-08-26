"""R24 Maturity page: render data.items; never invent a certification score."""
from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.lib.control_plane_contract_v1 import load_fixture

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "apps/command-center-v3/src/pages/control-plane/r24"


def test_maturity_fixture_is_not_a_certification():
    """Labeled FIXTURE unit: ControlPlane@v1.0.0 payload still documents non-certification."""
    payload = load_fixture("maturity")["payload"]
    assert payload["overall_is_not_a_certification"] is True
    assert payload["limiting_dimension"] == "longitudinal"
    dims = payload["dimensions"]
    assert isinstance(dims, list) and dims
    for row in dims:
        for key in ("dimension", "score", "evidence_class", "proof_refs", "limiting_factor", "next_proof"):
            assert key in row


def test_frozen_maturity_json_matches_integrator_fixture():
    """Labeled FIXTURE: vendored JSON stays byte-equal; it is not the live view."""
    fixture = json.loads((ROOT / "fixtures/control_plane/v1.0.0/maturity.json").read_text(encoding="utf-8"))
    frozen = json.loads((PAGES / "frozen/maturity.json").read_text(encoding="utf-8"))
    assert frozen == fixture


def test_maturity_page_renders_data_items_fields():
    src = (PAGES / "MaturityPage.tsx").read_text(encoding="utf-8")
    types = (PAGES / "payloadTypes.ts").read_text(encoding="utf-8")
    assert "data.items" in src
    assert "payload.dimensions" in src  # labeled FIXTURE path only
    assert "overall_is_not_a_certification" in src
    assert "limiting_dimension" in src
    assert "limiting_factor" in src
    assert "next_proof" in src
    assert "evidence_class" in src
    for field in ("dimension", "score", "evidence_class", "proof_refs", "limiting_factor", "next_proof"):
        assert field in types
        assert field in src


def test_maturity_page_does_not_compute_or_certify():
    src = "\n".join(
        p.read_text(encoding="utf-8")
        for p in [
            PAGES / "MaturityPage.tsx",
            PAGES / "payloadTypes.ts",
            PAGES / "controlPlaneChrome.tsx",
            PAGES / "useControlPlaneEnvelope.ts",
            PAGES / "httpEnvelope.ts",
        ]
    )
    assert "does not invent a certification score" in src
    assert "computes_maturity" in src
    assert re.search(r"computes_maturity\s*=\s*true", src) is None
    assert "overall_score" not in src
    assert "certification_score" not in src
    assert "weightedAverage" not in src
    assert ".reduce(" not in src
    assert "Math.min" not in src
    assert "Math.max" not in src
    assert "Math.round" not in src
    assert "/ dimensions.length" not in src
    assert "argmin" in src  # documents that limiting_dimension is NOT argmin(score)
    assert "not argmin(score)" in src
    assert "CONTROL_PLANE_API_V1_BASELINE" in src
    assert "UNAVAILABLE" in src
    hook = (PAGES / "useControlPlaneEnvelope.ts").read_text(encoding="utf-8")
    assert "keeping FIXTURE" not in hook
    assert "FROZEN_ENVELOPES" not in hook
