"""External content trust boundary (UNTRUSTED_DATA) tests."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_untrusted_data import (  # noqa: E402
    UNTRUSTED_DATA,
    UNTRUSTED_MARKER,
    UNTRUSTED_SECTION,
    is_untrusted,
    partition_context_sections,
    untrusted_delimiter,
    untrusted_envelope,
)


def test_envelope_marks_external_content():
    env = untrusted_envelope(
        content_type="documents", source="local", content="injected text", ref="d1"
    )
    assert is_untrusted(env)
    assert env[UNTRUSTED_MARKER] is True
    assert env["content_type"] == "documents"
    assert env["source"] == "local"


def test_delimiter_never_labels_as_operator_instructions():
    s = untrusted_delimiter(content_type="calendar", source="local", content="meeting")
    assert UNTRUSTED_DATA in s
    assert "NOT operator instructions" in s
    assert "BEGIN" in s and "END" in s


def test_untrusted_in_external_read_is_allowed():
    context = {
        "system": {"role": "advisory"},
        UNTRUSTED_SECTION: {
            "documents": untrusted_envelope(content_type="documents", source="l", content="x")
        },
    }
    report = partition_context_sections(context)
    assert report["ok"] is True
    assert report["violations"] == []


def test_untrusted_in_instruction_section_is_flagged():
    context = {
        "office_truth": {
            "cash": untrusted_envelope(content_type="documents", source="l", content="100")
        },
    }
    report = partition_context_sections(context)
    assert report["ok"] is False
    assert any("office_truth" in v for v in report["violations"])


def test_untrusted_nested_in_list_under_instruction_flagged():
    context = {
        "active_intent": [
            {"note": untrusted_envelope(content_type="research", source="l", content="r")}
        ]
    }
    report = partition_context_sections(context)
    assert report["ok"] is False
    assert any("active_intent" in v for v in report["violations"])


def test_plain_string_not_untrusted():
    assert not is_untrusted("just a string")
    assert not is_untrusted({"content": "no marker"})
