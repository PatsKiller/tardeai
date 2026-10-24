"""Research prompt version labels preserve missingness without inventing a thesis pin.

The canonical context is exercised with every external source replaced by fixtures;
no model, provider, memory service, database, or production state is consulted.
"""

from __future__ import annotations

import json

import pytest

from scripts.lib import research_prompt_context as rpc


@pytest.fixture
def context_for_version(tmp_path, monkeypatch):
    monkeypatch.setattr(rpc, "_now", lambda: "2026-10-23T20:30:00+00:00")
    monkeypatch.setattr(rpc, "_db_one", lambda *args, **kwargs: {})
    monkeypatch.setattr(rpc, "_operator_watch_memberships", lambda symbol, memberships: memberships)

    def build(version):
        fields = {
            "symbol_thesis_id": "symbol_fixture",
            "symbol_thesis_version": version,
            "thesis_state": "INSUFFICIENT_DATA",
            "thesis_stance": "UNKNOWN",
            "memberships": ["WATCH"],
        }
        monkeypatch.setattr("scripts.lib.symbol_thesis_attach.thesis_fields_for_symbol", lambda *args, **kwargs: fields)
        return rpc.build_research_prompt_context(
            "FIXTURE",
            question="What evidence is missing?",
            root=tmp_path,
            rag_catalog={},
            deterministic_current={},
            previous_research={},
            operator_feedback=[],
            memory_context={},
            ratified_lessons=[],
            financial_senses_receipts=[],
        )

    return build


@pytest.mark.parametrize("version", [None, "", "  ", "null", " NULL ", "None", "undefined", "UNKNOWN", "v.null"])
def test_missing_version_has_explicit_narrative_label_and_retains_raw_identity(context_for_version, version):
    context = context_for_version(version)
    thesis = context["standing_thesis"]
    assert thesis["version"] == version
    assert thesis["version_status"] == "UNAVAILABLE"
    assert thesis["version_display"] == "thesis version unavailable"
    assert thesis["state"] == "INSUFFICIENT_DATA"
    assert thesis["thesis_id"] == "symbol_fixture"
    assert context["authority"] == "READ_ONLY_ADVISORY"
    assert context["memory_behavior_influence"] == 0


@pytest.mark.parametrize("version", [0, 7, "symbol_fixture@v7", "desk@v5", "  symbol_fixture@v7  "])
def test_known_version_is_copied_without_adding_a_second_version_prefix(context_for_version, version):
    thesis = context_for_version(version)["standing_thesis"]
    assert thesis["version"] == version
    assert thesis["version_status"] == "AVAILABLE"
    assert thesis["version_display"] == f"thesis version {str(version).strip()}"
    assert thesis["state"] == "INSUFFICIENT_DATA"  # a display label never promotes thesis state


def test_serialized_context_carries_the_narrative_rule_and_hashes_its_display_semantics(context_for_version):
    context = context_for_version(None)
    thesis = json.loads(json.dumps(context))["standing_thesis"]
    assert "Use version_display verbatim" in thesis["version_rendering_rule"]
    assert "Never prepend 'v'" in thesis["version_rendering_rule"]
    assert "infer a version" in thesis["version_rendering_rule"]
    assert thesis["version"] is None
    assert context["as_of"] == "2026-10-23T20:30:00+00:00"
    body = {k: v for k, v in context.items() if k not in {"prompt_context_hash", "as_of"}}
    assert context["prompt_context_hash"] == rpc._hash(body)
    changed = json.loads(json.dumps(body))
    changed["standing_thesis"]["version_display"] = "invented pin"
    assert rpc._hash(changed) != context["prompt_context_hash"]
