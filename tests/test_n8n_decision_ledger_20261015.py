"""Audit 2026-10-15 (DD18 / DD02 / DD13 / DD17): the D1-D9 decision ledger, the DD01-DD18 findings tracker and the
threat model stay complete and consistent with the reference architecture. Hermetic: reads committed docs only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
N8N = ROOT / "docs" / "architecture" / "n8n"
REF = N8N / "N8N_REFERENCE_ARCHITECTURE.md"
LEDGER_JSON = N8N / "N8N_DECISION_LEDGER.json"
LEDGER_MD = N8N / "N8N_DECISION_LEDGER.md"
TRACKER = N8N / "AUDIT_20261015_FINDINGS.md"
THREAT = N8N / "N8N_THREAT_MODEL.md"
STATUSES = {"accepted", "partially_realized", "specified_not_enforced"}


def _section(text: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert m, heading
    return m.group(1)


def _architecture_decisions() -> list[str]:
    sec = _section(REF.read_text(encoding="utf-8"), "11. Decisions and rationale")
    return re.findall(r"^\| (D\d+) \|", sec, re.M)


def _ledger() -> dict:
    return json.loads(LEDGER_JSON.read_text(encoding="utf-8"))


def _table_rows(text: str, first_cell: str) -> dict[str, list[str]]:
    rows = {}
    for line in text.splitlines():
        m = re.match(rf"^\| ({first_cell}) \|(.*)\|\s*$", line)
        if m:
            rows[m.group(1)] = [c.strip() for c in m.group(2).split("|")]
    return rows


def test_architecture_still_lists_nine_decisions():
    # 2026-10-15: D10 (operator OAuth-first routing decision, #1770) joined D1-D9.
    assert _architecture_decisions() == [f"D{i}" for i in range(1, 11)]


def test_every_architecture_decision_has_a_complete_ledger_row():
    ledger = _ledger()
    assert ledger["schema"] == "N8nDecisionLedger@v1"
    required = ledger["required_fields"]
    rows = {d["id"]: d for d in ledger["decisions"]}
    assert set(_architecture_decisions()) == set(rows), "ledger and reference architecture §11 disagree"
    for did, row in rows.items():
        missing = [f for f in required if f not in row]
        assert not missing, (did, missing)
        for f in required:
            if f == "runtime_evidence":
                continue  # may be empty until evidence exists; checked below
            assert row[f] not in ("", [], {}, None), (did, f)
        assert row["status"] in STATUSES, did
        assert "to confirm" in row["accountable_owner_role"].lower(), (did, "owner must be a ROLE to confirm")
        rat = row["ratification"]
        assert (
            rat.get("policy")
            and rat.get("ratifier")
            and rat.get("ref")
            and re.match(r"\d{4}-\d{2}-\d{2}", rat.get("date", ""))
        )


def test_accepted_requires_dated_runtime_evidence():
    for row in _ledger()["decisions"]:
        for ev in row["runtime_evidence"]:
            assert re.match(r"\d{4}-\d{2}-\d{2}$", ev["date"]) and ev["evidence"] and ev["source"], row["id"]
        if row["status"] == "accepted":
            assert row["runtime_evidence"], f"{row['id']}: accepted without dated runtime evidence"


@pytest.mark.parametrize("key", ["implementing_files", "test_ids"])
def test_ledger_paths_exist(key):
    for row in _ledger()["decisions"]:
        for rel in row[key]:
            assert (ROOT / rel.split("::")[0]).exists(), (row["id"], rel)


def test_markdown_ledger_mirrors_the_json():
    md = LEDGER_MD.read_text(encoding="utf-8")
    rows = _table_rows(_section(md, "Ledger"), r"D\d+")
    ledger = {d["id"]: d for d in _ledger()["decisions"]}
    assert set(rows) == set(ledger)
    for did, cells in rows.items():
        assert cells[1] == ledger[did]["status"], did
    summary = _table_rows(_section(md, "Summary"), "|".join(sorted(STATUSES)))
    for status, cells in summary.items():
        ids = sorted(d for d, r in ledger.items() if r["status"] == status)
        assert int(cells[0]) == len(ids), status
        assert (cells[1] == "—" and not ids) or [x.strip() for x in cells[1].split(",")] == ids, status


def test_findings_tracker_has_every_register_row_complete():
    rows = _table_rows(
        _section(TRACKER.read_text(encoding="utf-8"), "1. Register DD01–DD18 (audit §16–§17)"), r"DD\d\d"
    )
    assert sorted(rows) == [f"DD{i:02d}" for i in range(1, 19)]
    for did, cells in rows.items():
        assert len(cells) == 8 and all(cells), (did, cells)
        cls, evidence, _finding, closure, _owner, _assignee, pr, status = cells
        assert cls in {"P1", "P2"}, did
        assert evidence in {"New", "Known", "New/Known", "Known/New"}, did
        assert closure.startswith('"') and closure.endswith('"'), f"{did}: closure evidence must be quoted verbatim"
        assert pr, did
        assert not status.startswith("CLOSED") or re.search(r"\d{4}-\d{2}-\d{2}", status), f"{did}: CLOSED needs a date"


def test_tracker_preserves_new_versus_known_and_maturity():
    text = TRACKER.read_text(encoding="utf-8")
    assert "Newly demonstrated contradictions" in text and "Already disclosed gaps" in text
    assert "Level 2 of 5 (independent audit 2026-10-15)" in text
    for step in (
        "Threat model",
        "Enforced identity and revocation",
        "Reliable output/effect semantics",
        "Independent delivery and recovery tests",
        "Accept one bounded business process",
    ):
        assert step in text, step


def test_reference_architecture_carries_the_maturity_line_and_pointers():
    text = REF.read_text(encoding="utf-8")
    header = text.split("```", 2)[1]
    assert "Maturity:    Level 2 of 5 (independent audit 2026-10-15)" in header
    for doc in ("AUDIT_20261015_FINDINGS.md", "N8N_THREAT_MODEL.md", "N8N_DECISION_LEDGER.md"):
        assert doc in header and (N8N / doc).is_file(), doc
    assert "bridge_oauth_transport.py" in text, "OAuth adapters exist (audit correction C-1)"


def test_threat_model_covers_every_boundary_with_stride():
    text = THREAT.read_text(encoding="utf-8")
    for b in ("B1", "B2", "B3", "B4", "B5"):
        sec = re.search(rf"^### {b} .*?(?=^### |^## )", text, re.S | re.M)
        assert sec, b
        letters = set(re.findall(r"^\| ([STRIDE](?:/[STRIDE])*) \|", sec.group(0), re.M))
        covered = {ch for item in letters for ch in item.split("/")}
        assert covered == set("STRIDE"), (b, sorted(covered))
    for must in ("Compromised n8n container", "uid `johnclaw`", "Residual risks", "Report-mode controls"):
        assert must in text, must


def test_spec_documents_exist_and_declare_their_level():
    hitl = (N8N / "N8N_HITL_CONTRACT_SPEC.md").read_text(encoding="utf-8")
    assert "SPECIFIED (maturity Level 1 of 5)" in hitl
    assert len(re.findall(r"^\| H\d+ \|", hitl, re.M)) == 12
    llm = (N8N / "N8N_LLM_STEP_ROUTE_SPEC.md").read_text(encoding="utf-8")
    for test_ref in re.findall(r"`::(test_\w+)`", llm):
        assert f"def {test_ref}(" in (ROOT / "tests" / "test_bridge_oauth_llm_step_20261014.py").read_text(
            encoding="utf-8"
        )
