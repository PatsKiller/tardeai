"""ControlPlane@v1.0.0 — frozen types and fixture loader.

Not an HTTP implementation. R21 implements live GET routes against this schema.
R22/R23/R24 consume fixtures while R21 is in flight.

READ_ONLY_ADVISORY. MEMORY_BEHAVIOR_INFLUENCE=0.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA = "ControlPlane@v1.0.0"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

RUNTIME_STATUS = (
    "LIVE_EVENT_DRIVEN",
    "LIVE_SCHEDULED",
    "CALLABLE_ONLY",
    "EXPECTED_IDLE",
    "SHADOW",
    "DISABLED",
    "BROKEN",
)
EVIDENCE_CLASS = (
    "SOURCE_ONLY",
    "UNIT",
    "INTEGRATION",
    "HISTORICAL_REPLAY",
    "GOLDEN_SHADOW",
    "SHADOW",
    "DRY_RUN",
    "OPERATOR_REQUESTED_LIVE",
    "CURRENT_SMOKE",
    "NATURAL_CURRENT",
    "NATURAL_LONGITUDINAL",
)
WORKFLOW_NODE_KINDS = (
    "event",
    "entity",
    "materiality",
    "graph",
    "research",
    "specialist",
    "council",
    "cio",
    "notification",
    "checkpoint",
    "outcome",
    "learning",
)
ENVELOPE_REQUIRED = (
    "schema",
    "page",
    "as_of",
    "evidence_class",
    "source_sha",
    "data_quality",
    "authority",
    "memory_behavior_influence",
    "computes_cio_decisions",
    "computes_agent_state",
    "computes_maturity",
    "computes_notification_eligibility",
    "payload",
)

REPO = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO / "fixtures" / "control_plane" / "v1.0.0"
SCHEMA_PATH = REPO / "schemas" / "control_plane" / "v1.0.0" / "envelope.json"
VERSION_PATH = REPO / "docs" / "convergence" / "CONTROL_PLANE_CONTRACT_VERSION"


def contract_version() -> str:
    if VERSION_PATH.is_file():
        return VERSION_PATH.read_text(encoding="utf-8").strip()
    return SCHEMA


def envelope(
    page: str,
    payload: dict[str, Any],
    *,
    evidence_class: str,
    source_sha: str = "fixture",
    data_quality: str = "OK",
    as_of: str = "2026-08-26T00:00:00+00:00",
) -> dict[str, Any]:
    if evidence_class not in EVIDENCE_CLASS:
        raise ValueError(f"invalid evidence_class {evidence_class}")
    return {
        "schema": SCHEMA,
        "page": page,
        "as_of": as_of,
        "evidence_class": evidence_class,
        "source_sha": source_sha,
        "data_quality": data_quality,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "computes_cio_decisions": False,
        "computes_agent_state": False,
        "computes_maturity": False,
        "computes_notification_eligibility": False,
        "payload": payload,
        "financial_action": False,
    }


def validate_envelope(doc: dict[str, Any]) -> list[str]:
    errors = []
    for k in ENVELOPE_REQUIRED:
        if k not in doc:
            errors.append(f"missing {k}")
    if doc.get("schema") != SCHEMA:
        errors.append(f"schema {doc.get('schema')!r} != {SCHEMA}")
    if doc.get("authority") != AUTHORITY:
        errors.append("authority must be READ_ONLY_ADVISORY")
    if int(doc.get("memory_behavior_influence") or 0) != 0:
        errors.append("MBI must be 0")
    if doc.get("evidence_class") not in EVIDENCE_CLASS:
        errors.append("invalid evidence_class")
    for flag in (
        "computes_cio_decisions",
        "computes_agent_state",
        "computes_maturity",
        "computes_notification_eligibility",
    ):
        if doc.get(flag) is not False:
            errors.append(f"{flag} must be false")
    return errors


def load_fixture(name: str) -> dict[str, Any]:
    path = FIXTURE_DIR / f"{name}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    errs = validate_envelope(doc)
    if errs:
        raise ValueError(f"{name}: {errs}")
    return doc


def list_fixtures() -> list[str]:
    if not FIXTURE_DIR.is_dir():
        return []
    return sorted(p.stem for p in FIXTURE_DIR.glob("*.json"))
