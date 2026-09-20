"""AGENTS.md §13.4 type vocabulary must stay discoverable.

A pre-build check (§13.5) is unusable if an agent cannot learn the registered
names. This guards presence of the vocabulary section, AgentView@v1 /
AGENT_COMMITMENT@v1 (scheduled producers as of ledger CLOSED 2026-09-19), and
explicit "SPECIFIED, no producer yet" marking for INDUSTRY/THEME/EVENT prefixes.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUB = ROOT / "AGENTS.md"


def _section_134() -> str:
    text = HUB.read_text(encoding="utf-8")
    start = text.index("## 13.4 · The type vocabulary")
    end = text.index("## 13.5 · Pre-build check", start)
    return text[start:end]


def test_section_134_and_135_exist():
    text = HUB.read_text(encoding="utf-8")
    assert "## 13.4 · The type vocabulary — what already exists" in text
    assert "## 13.5 · Pre-build check" in text
    assert "Read §13.4." in text


def test_section_134_names_registered_ids_and_subject_keys():
    body = _section_134()
    for name in (
        "workflow_id",
        "operator_turn_id",
        "instrument_record_id",
        "HELD:SYM",
        "EXIT:SYM",
        "WATCH:SYM",
        "SECTOR:name",
        "SLEEVE:CASH",
        "InstrumentRecord@v1",
        "operator_turns[]",
        "OutcomeCheckpoint@v1",
        "SpecialistArtifact@v1-lite",
        "CIOCouncilSynthesis@v1",
        "CIOOperatorProduct@v1",
    ):
        assert name in body, name


def test_agentview_commitment_and_specified_prefixes_marked_explicitly():
    body = _section_134()
    assert "AgentView@v1" in body
    assert "AGENT_COMMITMENT@v1" in body
    # 1.2.5: these have AEC scheduled producers (ledger CLOSED) — do not re-assert
    # the former "specified and currently have no producer" wording.
    assert "have scheduled producers" in body
    # Prefixes still specified without a record producer:
    assert "SPECIFIED, no producer yet" in body


def test_section_19_lists_diagram_documents():
    text = HUB.read_text(encoding="utf-8")
    start = text.index("# 19 · Where things live")
    end = text.index("# 20 · Amending this file", start)
    body = text[start:end]
    assert "CIO_ASIS_VS_SPEC_2026-08-30.md" in body
    assert "CIO_FUTURE_STATE_FULL_MATURITY.md" in body


def test_section_7_names_the_vocabulary_trap():
    text = HUB.read_text(encoding="utf-8")
    assert "A standard that omits the vocabulary cannot enforce the pre-build check." in text
