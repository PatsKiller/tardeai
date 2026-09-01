"""decide_after_load consults the retained wake hits.

#832 gave `wake_research_persist.json` a `hits[]` that survives the every-cycle
overwrite. Nothing read it: the only references to the artifact were its own
writer and a shape test, so the durable evidence that research already fired
for a subject reached no decision.

The record is the memory and stays the memory. `hits[]` is the cross-check:
when a cognition persist fails the record forgets, and only the retained hit
still shows the desk looked -- exactly when re-researching the same subject is
most likely and least visible.

MBI_BEHAVIOR = 0 throughout: this adds observation fields and one divergence
flag. It changes no routing, no cadence, and no size.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib.cio_research_preflight import decide_after_load  # noqa: E402
from scripts.lib.wake_research_persist import (  # noqa: E402
    last_hit_for_subject,
    observe_last_hit,
)

NOW = None  # decide_after_load defaults to utcnow; these tests do not need a clock


def _doc(hits):
    # `current` MUST be a dict: load_document treats a non-dict `current` as the
    # legacy last-cycle-only shape and returns hits=[]. A fixture with
    # `current: None` therefore silently tests nothing -- which is how the first
    # draft of this file passed its reader tests and failed its wiring tests.
    return {"schema": "WakeResearchPersist@v1", "current": {}, "hits": hits}


def _hit(as_of, subjects, decisions, research_called=1, persisted=1):
    return {
        "as_of": as_of, "dispatched": len(subjects),
        "research_called": research_called, "persisted": persisted,
        "subjects": list(subjects), "decisions": list(decisions),
        "unattended": True,
    }


def _write(tmp_path, doc):
    p = tmp_path / "wake_research_persist.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


# ---------------------------------------------------------------- reader ----

def test_last_hit_picks_the_named_subject():
    doc = _doc([
        _hit("2026-09-01T17:00:00+00:00", ["EXIT:WLDS"], ["flash"]),
        _hit("2026-09-01T18:00:00+00:00", ["HELD:SCHD"], ["skip"]),
    ])
    hit = last_hit_for_subject(doc, "EXIT:WLDS")
    assert hit is not None
    assert hit["as_of"] == "2026-09-01T17:00:00+00:00"
    assert hit["decision"] == "flash"


def test_most_recent_hit_wins():
    doc = _doc([
        _hit("2026-09-01T17:00:00+00:00", ["EXIT:WLDS"], ["flash"]),
        _hit("2026-09-01T19:00:00+00:00", ["EXIT:WLDS"], ["skip"]),
        _hit("2026-09-01T18:00:00+00:00", ["EXIT:WLDS"], ["flash"]),
    ])
    hit = last_hit_for_subject(doc, "EXIT:WLDS")
    assert hit["as_of"] == "2026-09-01T19:00:00+00:00", "newest by as_of, not list order"
    assert hit["decision"] == "skip"


def test_a_subject_with_no_hit_returns_none_not_someone_elses():
    doc = _doc([_hit("2026-09-01T17:00:00+00:00", ["HELD:SCHD"], ["flash"])])
    assert last_hit_for_subject(doc, "EXIT:WLDS") is None


def test_misaligned_subjects_and_decisions_do_not_attribute_a_decision():
    """`hit_from_cycle` skips empty subject_keys but appends every decision, so
    the lists are index-aligned only while every row carries a subject. Reading
    positionally through a misalignment would give one subject another's
    outcome. The hit is still returned; the decision is withheld."""
    doc = _doc([_hit("2026-09-01T17:00:00+00:00", ["EXIT:WLDS"], ["flash", "skip"])])
    hit = last_hit_for_subject(doc, "EXIT:WLDS")
    assert hit is not None
    assert hit["decision"] is None


def test_unreadable_document_is_not_the_same_as_no_hit(tmp_path):
    bad = tmp_path / "wake_research_persist.json"
    bad.write_text("{not json", encoding="utf-8")
    out = observe_last_hit("EXIT:WLDS", path=bad)
    assert out["readable"] is False, "a malformed document is UNVERIFIABLE"
    assert out["hit"] is None
    assert out["detail"], "the reason must be recorded, not swallowed"


def test_missing_document_is_readable_with_no_hit(tmp_path):
    out = observe_last_hit("EXIT:WLDS", path=tmp_path / "absent.json")
    assert out["readable"] is True, "we looked and there was nothing: that is silence"
    assert out["hit"] is None


# ------------------------------------------------------- decide_after_load ---

def _spy():
    calls = []

    def fn(inp, *, now=None):
        calls.append(inp)
        return {"decision": "flash", "reason": "spy"}
    return fn, calls


def test_decide_surfaces_the_hit(tmp_path):
    """THE MUTATION PIN. hits present + reader blind -> this goes red."""
    p = _write(tmp_path, _doc([
        _hit("2026-09-01T17:35:28+00:00", ["EXIT:WLDS"], ["flash"]),
    ]))
    fn, _ = _spy()
    out = decide_after_load("EXIT:WLDS", plan={"material": True},
                            decide_fn=fn, hits_path=p)
    assert out["last_hit_readable"] is True
    assert out["last_hit_at"] == "2026-09-01T17:35:28+00:00", (
        "decide_after_load must consult hits[]; a blind reader reports None here"
    )
    assert out["last_hit_decision"] == "flash"


def test_decide_reports_no_hit_for_an_unrelated_subject(tmp_path):
    p = _write(tmp_path, _doc([
        _hit("2026-09-01T17:35:28+00:00", ["HELD:SCHD"], ["flash"]),
    ]))
    fn, _ = _spy()
    out = decide_after_load("EXIT:WLDS", plan={"material": True},
                            decide_fn=fn, hits_path=p)
    assert out["last_hit_readable"] is True
    assert out["last_hit_at"] is None, "no false attribution across subjects"


def test_decide_is_fail_soft_when_the_document_is_broken(tmp_path):
    bad = tmp_path / "wake_research_persist.json"
    bad.write_text("{not json", encoding="utf-8")
    fn, calls = _spy()
    out = decide_after_load("EXIT:WLDS", plan={"material": True},
                            decide_fn=fn, hits_path=bad)
    assert out["last_hit_readable"] is False
    assert out["decision"] == "flash", "a broken consult must not stop the gate"
    assert len(calls) == 1


def test_not_material_still_carries_the_consult_fields(tmp_path):
    p = _write(tmp_path, _doc([_hit("2026-09-01T17:00:00+00:00", ["EXIT:WLDS"], ["flash"])]))
    out = decide_after_load("EXIT:WLDS", plan={"material": False}, hits_path=p)
    assert out["decision"] == "skip" and out["reason"] == "not_material"
    assert "last_hit_readable" in out, "every return path carries the consult"


# ------------------------------------------------ duplicate research flag ----

def test_duplicate_research_flagged_when_the_record_is_silent(tmp_path):
    """Research fires for a subject a hit already covered, and the record holds
    no cadence -- the shape a failed cognition persist leaves behind."""
    p = _write(tmp_path, _doc([_hit("2026-09-01T17:00:00+00:00", ["EXIT:WLDS"], ["flash"])]))
    fn, _ = _spy()
    out = decide_after_load("EXIT:WLDS", plan={"material": True},
                            decide_fn=fn, hits_path=p)
    assert out["duplicate_research_suspected"] is True


def test_no_duplicate_flag_without_a_hit(tmp_path):
    p = _write(tmp_path, _doc([]))
    fn, _ = _spy()
    out = decide_after_load("EXIT:WLDS", plan={"material": True},
                            decide_fn=fn, hits_path=p)
    assert out["duplicate_research_suspected"] is False


def test_no_duplicate_flag_when_the_gate_skips(tmp_path):
    p = _write(tmp_path, _doc([_hit("2026-09-01T17:00:00+00:00", ["EXIT:WLDS"], ["flash"])]))

    def skip_fn(inp, *, now=None):
        return {"decision": "skip", "reason": "cadence_not_due"}
    out = decide_after_load("EXIT:WLDS", plan={"material": True},
                            decide_fn=skip_fn, hits_path=p)
    assert out["duplicate_research_suspected"] is False


def test_consult_never_changes_the_routing(tmp_path):
    """MBI-adjacent guard: the decision with a hit equals the decision without
    one. This adds observation, not policy."""
    fn, _ = _spy()
    with_hit = decide_after_load(
        "EXIT:WLDS", plan={"material": True}, decide_fn=fn,
        hits_path=_write(tmp_path, _doc([
            _hit("2026-09-01T17:00:00+00:00", ["EXIT:WLDS"], ["flash"])])))
    fn2, _ = _spy()
    without = decide_after_load(
        "EXIT:WLDS", plan={"material": True}, decide_fn=fn2,
        hits_path=tmp_path / "absent.json")
    assert with_hit["decision"] == without["decision"]
    assert with_hit["reason"] == without["reason"]


def test_loader_contract_a_null_current_discards_hits(tmp_path):
    """Observation, not a change: #832's loader keys the new shape on `current`
    being a dict, so a document with `current: null` and a populated `hits[]`
    loads as legacy and the hits are dropped. `write_cycle` always writes a dict
    current, so this is latent rather than live. Pinned here so a future reader
    of this artifact does not rediscover it the way this file's author did.
    The persist shape is out of scope for this change and is left alone."""
    p = tmp_path / "wake_research_persist.json"
    p.write_text(json.dumps({
        "schema": "WakeResearchPersist@v1", "current": None,
        "hits": [_hit("2026-09-01T17:00:00+00:00", ["EXIT:WLDS"], ["flash"])],
    }), encoding="utf-8")
    out = observe_last_hit("EXIT:WLDS", path=p)
    assert out["readable"] is True
    assert out["hit"] is None, "documented loader behaviour, not a reader bug"


def _seed_record(root: Path, subject_key: str, next_eligible_at: str) -> None:
    """A real InstrumentRecord under `root`, so the record-loaded branch runs."""
    store = root / "data" / "cio"
    store.mkdir(parents=True, exist_ok=True)
    kind, _, name = subject_key.partition(":")
    (store / "cio_instrument_records.jsonl").write_text(
        json.dumps({
            "schema": "InstrumentRecord@v1", "subject_key": subject_key,
            "kind": kind, "symbols": [name],
            "next_eligible_at": next_eligible_at,
            "research_ids": [], "artifact_ids": [],
            "operator_turn_ids": [], "lesson_ids": [],
        }) + "\n", encoding="utf-8")


def test_no_duplicate_flag_when_the_record_still_carries_cadence(tmp_path):
    """The suppression branch, exercised.

    A record with `next_eligible_at` means the gate HAD memory to reason from,
    so a fresh research call is the gate's own decision -- not a lost one. The
    stamp is in the past so the cadence check does not short-circuit and the
    gate genuinely runs.

    Without this the guard is untested: every other case here loads no record,
    so `record_next_eligible` is always None and removing the guard changes
    nothing any assertion can see.
    """
    _seed_record(tmp_path, "EXIT:WLDS", "2026-08-01T00:00:00+00:00")
    p = _write(tmp_path, _doc([
        _hit("2026-09-01T17:00:00+00:00", ["EXIT:WLDS"], ["flash"]),
    ]))
    fn, calls = _spy()
    out = decide_after_load("EXIT:WLDS", plan={"material": True},
                            decide_fn=fn, hits_path=p, root=tmp_path)
    assert out["record_loaded"] is True, "the record-loaded branch must actually run"
    assert out["decide_called"] is True, "a past stamp must not short-circuit the gate"
    assert out["last_hit_at"] == "2026-09-01T17:00:00+00:00", "the hit is still consulted"
    assert out["duplicate_research_suspected"] is False, (
        "the record remembered; this is the gate's decision, not a lost one"
    )
