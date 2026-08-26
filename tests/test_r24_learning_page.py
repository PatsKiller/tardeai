"""R24 Learning page: consume CONTROL_PLANE_API_V1_BASELINE data.items; never promote."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.control_plane_contract_v1 import load_fixture

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "apps/command-center-v3/src/pages/control-plane/r24"
FROZEN = PAGES / "frozen/learning.json"

REQUIRED_KINDS = {
    "decision",
    "checkpoint",
    "outcome",
    "lesson",
    "hypothesis",
    "experiment",
    "specialist_performance",
    "model_performance",
    "routing_candidate",
}

REQUIRED_LABELS = [
    "Decisions",
    "Checkpoints",
    "Outcomes",
    "Lessons",
    "Hypotheses",
    "Experiments",
    "Specialist performance",
    "Model performance",
    "Routing candidates",
]


def _page_sources() -> str:
    files = [
        PAGES / "LearningPage.tsx",
        PAGES / "payloadTypes.ts",
        PAGES / "frozenEnvelope.ts",
        PAGES / "httpEnvelope.ts",
        PAGES / "useControlPlaneEnvelope.ts",
        PAGES / "controlPlaneChrome.tsx",
    ]
    return "\n".join(p.read_text(encoding="utf-8") for p in files)


def test_learning_fixture_has_required_kinds_and_zero_auto_promotions():
    """Labeled FIXTURE unit: ControlPlane@v1.0.0 vocabulary still has nine kinds."""
    payload = load_fixture("learning")["payload"]
    kinds = {item["kind"] for item in payload["items"]}
    assert REQUIRED_KINDS <= kinds
    assert payload["auto_promotions"] == 0


def test_frozen_learning_json_matches_integrator_fixture():
    """Labeled FIXTURE: vendored JSON stays byte-equal; it is not the live view."""
    fixture = json.loads((ROOT / "fixtures/control_plane/v1.0.0/learning.json").read_text(encoding="utf-8"))
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    assert frozen == fixture


def test_learning_page_renders_each_kind_and_item_fields():
    src = (PAGES / "LearningPage.tsx").read_text(encoding="utf-8")
    types = (PAGES / "payloadTypes.ts").read_text(encoding="utf-8")
    combined = src + "\n" + types
    for kind in REQUIRED_KINDS:
        assert kind in combined
        assert f"kind={kind}" in src or f"'{kind}'" in types
    for label in REQUIRED_LABELS:
        assert label in types
    for field in (
        "item_id", "kind", "status", "score", "evidence_class",
        "proof_refs", "limiting_factor", "next_proof",
    ):
        assert field in src


def test_learning_page_displays_auto_promotions_and_does_not_promote():
    src = _page_sources()
    page = (PAGES / "LearningPage.tsx").read_text(encoding="utf-8")
    assert "auto_promotions" in page
    assert "absent" in page
    assert "does not auto-promote" in page
    assert "promote control" in page
    assert "autoPromote" not in src
    assert "onPromote" not in src
    assert "<button" not in page.lower()
    assert "method: 'POST'" not in src
    assert 'method: "POST"' not in src
    assert "method: 'PUT'" not in src
    assert "method: 'PATCH'" not in src
    assert "method: 'DELETE'" not in src


def test_learning_page_consumes_http_baseline_data_not_live():
    src = _page_sources()
    hook = (PAGES / "useControlPlaneEnvelope.ts").read_text(encoding="utf-8")
    assert "CONTROL_PLANE_API_V1_BASELINE" in src
    assert "data.items" in src
    assert "liveClaim: false" in src
    assert "READ_ONLY_ADVISORY" in src
    assert "FIXTURE" in src
    assert "keeping FIXTURE" not in hook
    assert "FROZEN_ENVELOPES" not in hook
    assert "ControlPlane@v1.0.0" in src
    assert "/control-plane/learning" in src
    assert "/api/v3/control-plane/learning" in src
    assert "does not claim R20-R24 live" in src or "not claim R20-R24 live" in src
    assert "MEMORY_BEHAVIOR_INFLUENCE=0" in src
    assert "UNAVAILABLE" in src
    assert "EMPTY_VALID" in src
