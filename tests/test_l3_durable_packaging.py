"""Durable packaging contract for F_JUDGMENT_NOT_DURABLE close-out."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.judgment_schema import JudgmentSchemaError
from scripts.lib.l3_agent_view_synthesis import (
    package_durable_l3_commitment,
    package_durable_l3_view,
    synthesize_agent_view,
    synthesize_commitment,
)
from tests.helpers.l3_fixtures import (
    FACT_A1,
    SUBJECT_A,
    make_author_json,
    make_grounded_input,
    mock_author_response,
    mock_critic_response,
)
from scripts.lib.l3_judgment_pipeline import run_l3_judgment_pipeline
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _judged_parts():
    raw = make_grounded_input()
    result = run_l3_judgment_pipeline(
        raw,
        author_call_fn=lambda **k: mock_author_response(
            make_author_json(stance="INSUFFICIENT", claim="Sparse evidence; abstain.")
        ),
        critic_call_fn=lambda **k: mock_critic_response(verdict="accept"),
        now=datetime(2026, 9, 11, 14, 0, tzinfo=ET),
    )
    assert result.ok
    return result


def test_package_durable_view_preserves_class_a_and_ids():
    result = _judged_parts()
    row = package_durable_l3_view(
        agent_view=result.agent_view,
        author=result.author,
        critique=result.critique,
        wake_id="wake-dry-1",
        source_sha="14063a767a5fe3054acef671c356bb3532685e46",
    )
    assert row["provenance_class"] == "A"
    assert row["cost_class"] != "zero"
    assert row["judgment_id"]
    assert row["critique_id"]
    assert row["falsifier"]
    assert row["provenance"]["llm"] is not None
    assert row["wake_id"] == "wake-dry-1"
    # Must not look like the historic template defect
    assert not (row["stance"] == "RECOMMEND" and row["cost_class"] == "zero" and row["provenance"]["llm"] is None)


def test_package_rejects_template_masquerade():
    with pytest.raises(JudgmentSchemaError):
        package_durable_l3_view(
            agent_view={
                "provenance_class": "T",
                "cost_class": "zero",
                "judgment_id": None,
                "falsifier": "",
                "provenance": {"llm": None},
            },
            author={"judgment_id": "j1"},
            critique={"critique_id": "c1"},
            wake_id="w",
            source_sha="abc",
        )


def test_package_commitment_requires_falsifier():
    result = _judged_parts()
    row = package_durable_l3_commitment(
        commitment=result.commitment,
        author=result.author,
        critique=result.critique,
        wake_id="wake-dry-1",
        source_sha="14063a767a5fe3054acef671c356bb3532685e46",
    )
    assert row is not None
    assert row["falsifier"]
    assert row["judgment_id"]
    assert row["provenance"]["llm"]["author_model"]
    assert (
        package_durable_l3_commitment(
            commitment={"claim": "x", "falsifier": ""},
            author=result.author,
            critique=result.critique,
            wake_id="w",
            source_sha="s",
        )
        is None
    )
