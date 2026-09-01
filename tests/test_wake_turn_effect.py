"""M3 asks for the wake's decision with and without the operator turn.

The turn was landing and the decision was demonstrably shaped by it — the defer
question quotes the operator's own note, `{intent: defer, note: "wait for price
buffer"}`, on `HELD:SCHD`. But the record kept only the with-branch, so "the
turn changed the outcome" and "the turn coincided with the outcome" looked
identical from runtime evidence, and constructing the counterfactual by hand is
what the maturity bar refuses.

The producer now records its own counterfactual. Deterministic, not simulated:
without the turn, `note` falls back to the lesson's note and `_defer_question`
derives a different question from it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import cio_rehydrate as rh  # noqa: E402


def _rows(tmp_path, monkeypatch, turn, lesson):
    monkeypatch.setattr(
        "scripts.lib.canonical_store_registry.production_state_root",
        lambda *a, **k: tmp_path,
    )
    rh._record_turn_effect(
        {"subject_key": "HELD:SCHD"},
        turn=turn, lesson=lesson,
        question_with=rh._defer_question(str(turn.get("note") or (lesson or {}).get("note") or "")),
        next_eligible_at="2026-09-06T00:00:00+00:00",
        priority="cc",
    )
    f = tmp_path / "data" / "cio" / "wake_turn_effects.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


def test_it_records_both_branches(tmp_path, monkeypatch):
    rows = _rows(tmp_path, monkeypatch,
                 {"intent": "defer", "note": "wait for price buffer", "ts": "2026-08-11T21:33:52Z"},
                 {"claim": "defer honored, no new catalyst"})
    r = rows[0]
    assert r["schema"] == "WakeTurnEffect@v1"
    assert "wait for price buffer" in r["with_turn"]["next_research_question"]
    assert "wait for price buffer" not in r["without_turn"]["next_research_question"]
    assert r["turn_changed_decision"] is True


def test_the_without_branch_is_derived_not_invented(tmp_path, monkeypatch):
    """It must equal what _defer_question actually produces with no note."""
    rows = _rows(tmp_path, monkeypatch,
                 {"intent": "defer", "note": "wait for price buffer"}, {})
    assert rows[0]["without_turn"]["next_research_question"] == rh._defer_question("")


def test_an_ineffective_turn_is_recorded_as_such(tmp_path, monkeypatch):
    """The honest negative: if the lesson carries the same note, the turn changed
    nothing, and that is recorded rather than hidden."""
    rows = _rows(tmp_path, monkeypatch,
                 {"intent": "defer", "note": "wait for price buffer"},
                 {"note": "wait for price buffer"})
    assert rows[0]["turn_changed_decision"] is False


def test_it_carries_the_turn_provenance(tmp_path, monkeypatch):
    rows = _rows(tmp_path, monkeypatch,
                 {"intent": "defer", "note": "n", "ts": "2026-08-11T21:33:52Z",
                  "plan_id": "plan_79fe9e72f2d4"}, {})
    t = rows[0]["turn"]
    assert t["ts"] == "2026-08-11T21:33:52Z" and t["plan_id"] == "plan_79fe9e72f2d4"
    assert rows[0]["memory_behavior_influence"] == 0
    assert rows[0]["authority"] == "READ_ONLY_ADVISORY"


def test_it_is_append_only(tmp_path, monkeypatch):
    _rows(tmp_path, monkeypatch, {"intent": "defer", "note": "a"}, {})
    rows = _rows(tmp_path, monkeypatch, {"intent": "defer", "note": "b"}, {})
    assert len(rows) == 2, "a second wake must not replace the first"


def test_a_failing_audit_cannot_break_the_wake(monkeypatch):
    """A wake must never fail because its audit line could not be written."""
    monkeypatch.setattr(
        "scripts.lib.canonical_store_registry.production_state_root",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no root")),
    )
    rh._record_turn_effect({"subject_key": "X"}, turn={"note": "n"}, lesson={},
                           question_with="q", next_eligible_at=None, priority="cc")


def test_the_record_schema_is_not_widened_for_this():
    """apply_cognition accepts exactly four cognition fields and refuses the
    rest. That rail is correct and this audit does not go through it."""
    src = (ROOT / "scripts/lib/cio_rehydrate.py").read_text(encoding="utf-8")
    i = src.index("def _record_turn_effect")
    block = src[i:i + 2600]
    # The CALL, not the word: the docstring names apply_cognition precisely to
    # explain why the audit does not route through it.
    assert "apply_cognition(" not in block
    assert "BehaviorWriteRefused" in block
