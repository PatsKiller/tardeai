from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from scripts.agent_runtime.sentinel import finding_codes, inspect_population, inspect_ticket


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "agentic_runtime" / "sentinel_known_bad.json"


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_sentinel_blocks_every_known_bad_fixture() -> None:
    payload = fixture()
    now = datetime.fromisoformat(payload["now"])
    assert len(payload["cases"]) >= 20
    for case in payload["cases"]:
        report = inspect_ticket(case["ticket"], case["validation"], now=now)
        assert report.release_allowed is False, case["name"]
        assert report.verdict in {"BLOCK", "QUARANTINE"}, case["name"]
        assert case["expected"] in finding_codes(report), case["name"]
        assert len(report.ticket_hash) == 64
        assert len(report.validation_hash) == 64
        assert len(report.report_hash) == 64


def test_sentinel_allows_only_a_clean_deterministically_valid_ticket() -> None:
    payload = fixture()
    report = inspect_ticket(payload["valid"]["ticket"], payload["valid"]["validation"], now=datetime.fromisoformat(payload["now"]))
    assert report.verdict == "PASS"
    assert report.release_allowed is True
    assert report.findings == ()


def test_population_scan_keeps_symbol_specific_validation_binding() -> None:
    payload = fixture()
    rows = [case["ticket"] for case in payload["cases"][:3]]
    validations = {case["ticket"].get("symbol", "").upper(): case["validation"] for case in payload["cases"][:3]}
    reports = inspect_population(rows, validations, now=datetime.fromisoformat(payload["now"]))
    assert len(reports) == 3
    assert all(report.release_allowed is False for report in reports)


def test_model_or_review_fields_cannot_override_deterministic_failure() -> None:
    payload = fixture()
    case = payload["cases"][0]
    ticket = dict(case["ticket"])
    ticket["model_consensus"] = "UNANIMOUS_PASS"
    ticket["paid_expert"] = "PASS"
    report = inspect_ticket(ticket, case["validation"], now=datetime.fromisoformat(payload["now"]))
    assert "DETERMINISTIC_FAILURE_SOVEREIGN" in finding_codes(report)
    assert report.release_allowed is False
