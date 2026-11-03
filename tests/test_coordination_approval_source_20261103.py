"""Synthetic coordinator decision contracts; no live state, broker, or GitHub."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/lib/coordination_approval_source.py"
SPEC = importlib.util.spec_from_file_location("coordination_approval_source_tested", PATH)
assert SPEC and SPEC.loader
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)
SHA = "a" * 40
NOW = datetime(2026, 11, 3, 3, tzinfo=timezone.utc)


def ledger(tmp_path, rows):
    path = tmp_path / M.LEDGER_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def pending(ident="first", **extra):
    return {"kind": "decision_needed", "decision_id": ident, "title": "Keep this proposal?",
            "ts": "2026-11-02T20:00:00-05:00", "coordinator": "test-lead", **extra}


def test_public_question_provenance_and_no_raw_payload(tmp_path):
    ledger(tmp_path, [pending(detail="PRIVATE-DETAIL", operator_quote="PRIVATE-QUOTE", secret="PRIVATE-EXTRA")])
    result = M.load(tmp_path, SHA, NOW)
    assert result["gap"] is None
    row = result["rows"][0]
    assert row["id"] == "decision:first"
    assert row["as_of"] == row["created_at"] == "2026-11-03T01:00:00Z"
    assert row["document"]["source_sha"] == SHA
    assert row["source_ref"] == M.LEDGER_REL
    assert "coordinator_decisions:first" in row["source_refs"]
    assert row["decision_mode"] == "GOVERNED_PATH"
    assert "PRIVATE" not in json.dumps(result)
    assert "03:00:00Z" not in json.dumps(result)  # capture time never dates a fact


def test_keep_retire_is_an_explicit_operator_question(tmp_path):
    ledger(tmp_path, [pending(decision_type="keep_retire", question="Keep or retire the obsolete packet?")])
    row = M.load(tmp_path, SHA)["rows"][0]
    assert row["decision_type"] == "keep_retire"
    assert row["options"] == ["keep", "retire"]
    assert row["governed_href"] == "/coordination?decision=first"


@pytest.mark.parametrize("kind", sorted(M.TERMINAL))
def test_only_exact_explicit_resolution_closes_question(tmp_path, kind):
    ledger(tmp_path, [pending("one"), pending("two"),
                      {"kind": kind, "decision_id": "one", "ts": "2026-11-03T02:00:00Z"}])
    result = M.load(tmp_path, SHA)
    assert [row["decision_id"] for row in result["rows"]] == ["two"]
    assert result["resolved"][0]["decision_id"] == "one"
    assert result["resolved"][0]["resolution"] == kind


def test_similar_text_directives_and_unbound_approval_do_not_resolve(tmp_path):
    ledger(tmp_path, [pending(), {"kind": "operator_directive", "subject": "first approved"},
                      {"kind": "approval_recorded", "subject": "first", "ts": "2026-11-03T02:00:00Z"},
                      {"kind": "decision_resolved", "decision_id": "first-other", "ts": "2026-11-03T02:00:00Z"}])
    assert len(M.load(tmp_path, SHA)["rows"]) == 1


def test_explicit_subject_convention_and_mismatched_ids(tmp_path):
    ledger(tmp_path, [pending(decision_id=None, subject="decision:exact")])
    assert M.load(tmp_path, SHA)["rows"][0]["decision_id"] == "exact"
    ledger(tmp_path, [pending(subject="decision:other")])
    assert M.load(tmp_path, SHA)["gap"] == "COORDINATOR_DECISION_EVENT_INVALID"


@pytest.mark.parametrize("updates", [{"decision_id": "../escape"}, {"ts": "2026-11-03T02:00:00"},
                                    {"decision_type": "execute"}, {"title": None}])
def test_invalid_explicit_decision_is_a_named_gap(tmp_path, updates):
    ledger(tmp_path, [pending(**updates)])
    result = M.load(tmp_path, SHA)
    assert result["gap"]
    assert result["rows"] == []


def test_missing_corrupt_and_empty_are_distinct(tmp_path):
    assert M.load(tmp_path, SHA)["gap"] == "COORDINATOR_DECISION_LEDGER_MISSING"
    path = ledger(tmp_path, [])
    assert M.load(tmp_path, SHA) == {"rows": [], "resolved": [], "gap": None, "as_of": None,
                                   "source": M.SOURCE, "source_ref": M.LEDGER_REL}
    path.write_text(json.dumps(pending()) + "\n{broken")
    assert M.load(tmp_path, SHA)["gap"] == "COORDINATOR_DECISION_LEDGER_CORRUPT"
    ledger(tmp_path, [{"kind": []}])
    assert M.load(tmp_path, SHA)["gap"] == "COORDINATOR_DECISION_LEDGER_CORRUPT"


def test_byte_event_and_item_bounds_are_named_not_silent_truncation(tmp_path, monkeypatch):
    path = ledger(tmp_path, [pending()])
    monkeypatch.setattr(M, "MAX_BYTES", 1)
    assert M.load(tmp_path, SHA)["gap"] == "COORDINATOR_DECISION_LEDGER_BYTE_BUDGET_EXCEEDED"
    monkeypatch.setattr(M, "MAX_BYTES", 10000)
    monkeypatch.setattr(M, "MAX_EVENTS", 1)
    path.write_text(path.read_text() + "{}\n")
    assert M.load(tmp_path, SHA)["gap"] == "COORDINATOR_DECISION_LEDGER_EVENT_BUDGET_EXCEEDED"
    monkeypatch.setattr(M, "MAX_EVENTS", 100)
    monkeypatch.setattr(M, "MAX_ITEMS", 1)
    ledger(tmp_path, [pending("one"), pending("two")])
    assert M.load(tmp_path, SHA)["gap"] == "COORDINATOR_DECISION_ITEM_BUDGET_EXCEEDED"


def test_source_sha_and_unsafe_ledger_refused(tmp_path):
    assert M.load(tmp_path, "main")["gap"] == "COORDINATOR_DECISION_SOURCE_SHA_REQUIRED"
    path = tmp_path / M.LEDGER_REL
    path.parent.mkdir(parents=True)
    path.symlink_to(tmp_path / "other.jsonl")
    assert M.load(tmp_path, SHA)["gap"] == "COORDINATOR_DECISION_LEDGER_UNSAFE"


def test_reload_observes_changed_ledger_without_writing(tmp_path):
    path = ledger(tmp_path, [pending()])
    original = path.read_bytes()
    assert len(M.load(tmp_path, SHA)["rows"]) == 1
    assert path.read_bytes() == original
    ledger(tmp_path, [pending(), {"kind": "decision_resolved", "decision_id": "first", "ts": "2026-11-03T02:00:00Z"}])
    changed = path.read_bytes()
    assert not M.load(tmp_path, SHA)["rows"]
    assert path.read_bytes() == changed
