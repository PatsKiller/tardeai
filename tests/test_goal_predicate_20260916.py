"""Controls for P2 — the goal predicate, and victory that cannot be declared.

The measured condition this closes (2026-09-16): three goals, 34,347 wakes over
36 days, `GOAL_STATUS_CHANGED` = 0, `success_criteria` empty on all three, and a
`close_goal()` that defaulted to status="achieved" and required no evidence at
all. Nothing had ever closed a goal, and anything that did could have claimed
victory with one line and no proof.

Each control below must go RED if the corresponding guarantee is removed.
Offline: temp files only, no database, no network, no live store.
"""
from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_goals as G  # noqa: E402

SRC = ROOT / "scripts" / "lib" / "cio_goals.py"

REAL_FALSIFIER = "the operator states the cash level was deliberate and no drift is observed by 2026-10-16"


@pytest.fixture
def store(tmp_path):
    return G.CIOGoalStore(
        event_path=tmp_path / "goals.jsonl",
        projection_path=tmp_path / "proj.json",
        cursor_path=tmp_path / "cursors.json",
    )


def _projection_hash(goals: dict) -> str:
    return hashlib.sha256(json.dumps(goals, sort_keys=True, default=str).encode()).hexdigest()


def _older_reader_module() -> types.ModuleType:
    """The real module with the GOAL_PREDICATE_SET knowledge surgically removed.

    This is not a hand-written imitation of an old reader: it is THIS file's own
    source with the new event type stripped from `VALID_EVENT_TYPES` and its
    `_apply_event` branch deleted, compiled and executed as its own module. It
    therefore stays a faithful "reader that has never heard of this event" no
    matter how the file evolves -- including after the commit that adds it,
    which is why `git show HEAD:` would not work here.

    If anyone ever gives `_apply_event` an `else: raise` for unknown types, this
    module raises on replay and every test using it goes red.
    """
    lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped == '"GOAL_PREDICATE_SET",':
            continue  # drop it from VALID_EVENT_TYPES
        if stripped.startswith('elif et == "GOAL_PREDICATE_SET":'):
            skipping = True
            continue
        if skipping:
            indent = len(line) - len(line.lstrip())
            if stripped and indent <= 8:
                skipping = False  # dedented back out of the branch body
            else:
                continue
        out.append(line)
    text = "".join(out)
    assert 'elif et == "GOAL_PREDICATE_SET"' not in text, "the branch was not removed"

    mod = types.ModuleType("cio_goals_older_reader")
    mod.__file__ = str(SRC)
    exec(compile(text, str(SRC), "exec"), mod.__dict__)
    assert "GOAL_PREDICATE_SET" not in mod.VALID_EVENT_TYPES
    return mod


# ── the event type is safe in BOTH directions ────────────────────────────────


def test_append_event_rejects_an_event_type_it_does_not_know(store):
    g = store.create_goal(owner_agent="alex", title="Cash concentration")
    with pytest.raises(ValueError, match="invalid event_type"):
        store._append_event("GOAL_INVENTED_BY_A_TYPO", g["goal_id"], {}, actor_id="test")


def test_apply_event_silently_ignores_an_event_type_it_does_not_know(store):
    """The other half of the pair: a reader must degrade, not crash."""
    g = store.create_goal(owner_agent="alex", title="Cash concentration")
    goals = {g["goal_id"]: dict(store._goals[g["goal_id"]])}
    before = _projection_hash(goals)
    store._apply_event(goals, {
        "event_type": "GOAL_FROM_A_FUTURE_DEPLOY",
        "goal_id": g["goal_id"],
        "occurred_at": "2026-09-16T12:00:00+00:00",
        "payload": {"anything": "at all"},
    })
    assert _projection_hash(goals) == before, "an unknown event must not mutate the projection"


def test_an_older_reader_replays_a_log_containing_the_new_event(store, tmp_path):
    """The P2 pass condition: replay the RAW log with an older code path."""
    g = store.create_goal(owner_agent="alex", title="Cash concentration")
    store.set_predicate(g["goal_id"], evaluator="all_terms_true@v1", terms=["corroborated"])
    assert store.get_goal(g["goal_id"])["predicate"]["evaluator"] == "all_terms_true@v1"

    older = _older_reader_module()
    old_store = older.CIOGoalStore(
        event_path=store.event_path,                 # the SAME raw log
        projection_path=tmp_path / "old_proj.json",
        cursor_path=tmp_path / "old_cursors.json",
    )
    old_store.rebuild_projection()                    # must not raise

    goal = old_store.get_goal(g["goal_id"])
    assert goal is not None, "the older reader lost the goal entirely"
    assert goal["title"] == "Cash concentration"
    assert "predicate" not in goal, "the older reader must degrade to 'no predicate'"


def test_the_older_reader_also_refuses_to_write_the_event_it_cannot_read(store, tmp_path):
    older = _older_reader_module()
    old_store = older.CIOGoalStore(
        event_path=tmp_path / "old.jsonl",
        projection_path=tmp_path / "old_proj.json",
        cursor_path=tmp_path / "old_cursors.json",
    )
    g = old_store.create_goal(owner_agent="alex", title="Cash")
    with pytest.raises(ValueError, match="invalid event_type"):
        old_store._append_event("GOAL_PREDICATE_SET", g["goal_id"], {}, actor_id="test")


def test_a_log_without_predicate_events_projects_identically_under_both_readers(store, tmp_path):
    """P2 changed no existing projection semantics -- proven, not asserted."""
    g = store.create_goal(owner_agent="morgan", title="Allocation practicality", priority="HIGH")
    store.update_thesis(g["goal_id"], "thesis one", agent_id="morgan")
    store.record_wake(g["goal_id"], agent_id="morgan", outcome="shadow_completed")

    older = _older_reader_module()
    old_store = older.CIOGoalStore(
        event_path=store.event_path,
        projection_path=tmp_path / "old_proj.json",
        cursor_path=tmp_path / "old_cursors.json",
    )
    old_store.rebuild_projection()
    assert _projection_hash(old_store._goals) == _projection_hash(store._goals)


def test_rebuilding_the_projection_twice_is_deterministic(store):
    g = store.create_goal(owner_agent="alex", title="Desk morning thesis")
    store.set_predicate(g["goal_id"], evaluator="all_terms_true@v1", terms=["a", "b"])
    first = _projection_hash(store._goals)
    store.rebuild_projection()
    assert _projection_hash(store._goals) == first


# ── predicate identity reuses the goal id ────────────────────────────────────


def test_predicate_identity_is_goal_id_version_and_hash(store):
    g = store.create_goal(owner_agent="alex", title="Desk morning thesis")
    store.set_predicate(g["goal_id"], evaluator="all_terms_true@v1", terms=["corroborated"])
    p = store.get_goal(g["goal_id"])["predicate"]

    assert p["predicate_version"] == 1
    assert p["predicate_identity"] == G.predicate_identity(
        g["goal_id"], p["predicate_version"], p["predicate_hash"]
    )
    assert p["predicate_identity"].startswith(g["goal_id"] + ":"), "no new id namespace"


def test_setting_a_predicate_again_increments_the_version(store):
    g = store.create_goal(owner_agent="alex", title="Desk morning thesis")
    store.set_predicate(g["goal_id"], evaluator="all_terms_true@v1", terms=["a"])
    store.set_predicate(g["goal_id"], evaluator="all_terms_true@v1", terms=["a", "b"])
    p = store.get_goal(g["goal_id"])["predicate"]
    assert p["predicate_version"] == 2
    assert p["terms"] == ["a", "b"]


def test_predicate_hash_tracks_meaning_not_timing():
    same = G.predicate_hash("all_terms_true@v1", ["a", "b"])
    assert same == G.predicate_hash("all_terms_true@v1", ["a", "b"])
    assert same != G.predicate_hash("all_terms_true@v1", ["a", "c"])
    assert same != G.predicate_hash("other_evaluator@v1", ["a", "b"])


def test_predicate_identity_refuses_to_mint_without_a_goal():
    with pytest.raises(ValueError, match="goal_id"):
        G.predicate_identity("", 1, "deadbeef")


# ── evaluation never invents a victory ───────────────────────────────────────


def test_unknown_evaluator_is_unevaluable_never_satisfied(store):
    g = store.create_goal(owner_agent="alex", title="Desk morning thesis")
    store.set_predicate(g["goal_id"], evaluator="evaluator_from_a_newer_deploy@v9", terms=["a"])
    verdict = store.evaluate_goal(g["goal_id"], {"a": True})
    assert verdict["verdict"] == G.VERDICT_UNEVALUABLE
    assert verdict["verdict"] != G.VERDICT_SATISFIED
    assert "unknown_evaluator" in verdict["reason"]


def test_a_predicate_with_no_terms_is_unevaluable_not_vacuously_true(store):
    g = store.create_goal(owner_agent="alex", title="Desk morning thesis")
    store.set_predicate(g["goal_id"], evaluator="all_terms_true@v1", terms=[])
    verdict = store.evaluate_goal(g["goal_id"], {})
    assert verdict["verdict"] == G.VERDICT_UNEVALUABLE
    assert verdict["reason"] == "no_terms"


def test_a_goal_with_no_predicate_at_all_is_unevaluable(store):
    g = store.create_goal(owner_agent="alex", title="Desk morning thesis")
    verdict = store.evaluate_goal(g["goal_id"], {"anything": True})
    assert verdict["verdict"] == G.VERDICT_UNEVALUABLE
    assert verdict["reason"] == "no_predicate"


def test_a_missing_fact_is_unevaluable(store):
    g = store.create_goal(owner_agent="alex", title="Desk morning thesis")
    store.set_predicate(g["goal_id"], evaluator="all_terms_true@v1", terms=["corroborated", "tier0_pass"])
    verdict = store.evaluate_goal(g["goal_id"], {"corroborated": True})
    assert verdict["verdict"] == G.VERDICT_UNEVALUABLE
    assert "tier0_pass" in verdict["reason"]


def test_a_false_term_is_decisively_unsatisfied(store):
    g = store.create_goal(owner_agent="alex", title="Desk morning thesis")
    store.set_predicate(g["goal_id"], evaluator="all_terms_true@v1", terms=["corroborated", "tier0_pass"])
    verdict = store.evaluate_goal(g["goal_id"], {"corroborated": False})
    assert verdict["verdict"] == G.VERDICT_UNSATISFIED


def test_every_term_supplied_and_true_is_the_only_road_to_satisfied(store):
    g = store.create_goal(owner_agent="alex", title="Desk morning thesis")
    store.set_predicate(g["goal_id"], evaluator="all_terms_true@v1", terms=["corroborated", "tier0_pass"])
    verdict = store.evaluate_goal(g["goal_id"], {"corroborated": True, "tier0_pass": True})
    assert verdict["verdict"] == G.VERDICT_SATISFIED


def test_set_predicate_refuses_an_empty_evaluator_or_a_bare_string_term(store):
    g = store.create_goal(owner_agent="alex", title="Desk morning thesis")
    with pytest.raises(ValueError, match="evaluator"):
        store.set_predicate(g["goal_id"], evaluator="  ", terms=["a"])
    with pytest.raises(ValueError, match="not a bare string"):
        store.set_predicate(g["goal_id"], evaluator="all_terms_true@v1", terms="a")


# ── victory cannot be declared without proof ─────────────────────────────────


def test_close_goal_refuses_empty_evidence(store, tmp_path):
    g = store.create_goal(owner_agent="alex", title="Cash concentration cost")
    with pytest.raises(ValueError, match="evidence is empty"):
        store.close_goal(g["goal_id"], evidence=[], falsifier=REAL_FALSIFIER, checkpoint_root=tmp_path)
    assert store.get_goal(g["goal_id"])["status"] == "open", "a refused close must not close anything"


def test_close_goal_refuses_whitespace_evidence(store, tmp_path):
    g = store.create_goal(owner_agent="alex", title="Cash concentration cost")
    with pytest.raises(ValueError, match="evidence is empty"):
        store.close_goal(g["goal_id"], evidence=["", "   "], falsifier=REAL_FALSIFIER, checkpoint_root=tmp_path)


def test_close_goal_refuses_a_bare_string_mistaken_for_a_list(store, tmp_path):
    g = store.create_goal(owner_agent="alex", title="Cash concentration cost")
    with pytest.raises(ValueError, match="not a bare string"):
        store.close_goal(g["goal_id"], evidence="one ref", falsifier=REAL_FALSIFIER, checkpoint_root=tmp_path)


def test_evidence_is_a_required_parameter_not_an_optional_one(store):
    """Omitting it must be a TypeError -- there is no defaultable 'no proof'."""
    g = store.create_goal(owner_agent="alex", title="Cash concentration cost")
    with pytest.raises(TypeError):
        store.close_goal(g["goal_id"], status="cancelled")


def test_a_close_with_evidence_records_it_on_the_event(store, tmp_path):
    g = store.create_goal(owner_agent="alex", title="Cash concentration cost")
    store.close_goal(
        g["goal_id"],
        status="achieved",
        evidence=["receipt:gap_resolution_receipts.jsonl#abc", "checkpoint:ck_1"],
        falsifier=REAL_FALSIFIER,
        checkpoint_root=tmp_path,
    )
    events = [json.loads(l) for l in store.event_path.read_text().splitlines() if l.strip()]
    closed = [e for e in events if e["event_type"] == "GOAL_STATUS_CHANGED"]
    assert len(closed) == 1
    assert closed[0]["payload"]["evidence"] == [
        "receipt:gap_resolution_receipts.jsonl#abc", "checkpoint:ck_1",
    ]
    assert store.get_goal(g["goal_id"])["status"] == "achieved"


# ── a goal may not be born overdue ───────────────────────────────────────────


def test_create_goal_refuses_a_due_ts_before_created_ts(store):
    """The live defect: all three goals due ten minutes BEFORE they existed."""
    from datetime import datetime, timedelta, timezone
    past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with pytest.raises(ValueError, match="born overdue"):
        store.create_goal(owner_agent="alex", title="Desk morning thesis", due_ts=past)
    assert store.list_open_goals() == [], "the refused goal must not exist"


def test_create_goal_allows_due_equal_to_created(store):
    g = store.create_goal(owner_agent="alex", title="Due at birth")
    store.update_goal(g["goal_id"], due_ts=g["created_ts"])
    assert store.get_goal(g["goal_id"])["due_ts"] == g["created_ts"]


def test_update_goal_refuses_moving_due_before_creation(store):
    from datetime import timedelta
    g = store.create_goal(owner_agent="alex", title="Desk morning thesis")
    before_birth = (G._parse_ts(g["created_ts"]) - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="born overdue"):
        store.update_goal(g["goal_id"], due_ts=before_birth)


def test_update_goal_allows_a_due_date_in_the_past_but_after_creation(store):
    """'This is due now' is legitimate; 'due before it existed' is not."""
    from datetime import timedelta
    g = store.create_goal(owner_agent="alex", title="Desk morning thesis")
    after_birth = (G._parse_ts(g["created_ts"]) + timedelta(seconds=1)).isoformat()
    store.update_goal(g["goal_id"], due_ts=after_birth)
    assert store.get_goal(g["goal_id"])["due_ts"] == after_birth


def test_an_unparseable_due_ts_raises_rather_than_being_ignored(store):
    with pytest.raises(ValueError, match="not an ISO timestamp"):
        store.create_goal(owner_agent="alex", title="Desk morning thesis", due_ts="soon")


# ── the repair is an append, never a rewrite ─────────────────────────────────


def test_the_live_defect_is_repaired_by_appending_not_by_rewriting(tmp_path):
    """Reproduces the live shape, then repairs it through the shipped tool."""
    import scripts.repair_goal_due_ts as repair

    log = tmp_path / "goals.jsonl"
    # Write the live shape directly: born-overdue goals predate the guard, so
    # the API can no longer create one.
    created = "2026-08-11T14:21:40.005000+00:00"
    due = "2026-08-11T14:11:40.004974+00:00"
    rows = []
    for gid, owner, title in (
        ("goal_695a5dbe2401", "alex", "Desk morning thesis"),
        ("goal_f2664540d8c1", "morgan", "Cash concentration cost"),
        ("goal_f1d5c0a993d0", "steph", "Allocation practicality"),
    ):
        rows.append(json.dumps({
            "event_id": f"0000-{gid}",
            "event_type": "GOAL_CREATED",
            "goal_id": gid,
            "occurred_at": created,
            "actor_id": "cio_goals",
            "actor_type": "system",
            "authority": "READ_ONLY_ADVISORY",
            "payload": {
                "goal_id": gid, "owner_agent": owner, "title": title, "status": "open",
                "priority": "NORMAL", "created_ts": created, "updated_ts": created,
                "due_ts": due, "success_criteria": "", "linked_event_types": [],
                "linked_symbols": [], "linked_action_ids": [], "thesis_summary": "",
                "last_wake_ts": None, "wake_count": 0, "last_outcome": None,
                "thesis_history": [],
            },
        }, sort_keys=True))
    log.write_text("\n".join(rows) + "\n")
    original_bytes = log.read_bytes()

    dry = repair.run(apply=False, event_path=log)
    assert dry["inverted_found"] == 3
    assert dry["repaired"] == 0
    assert log.read_bytes() == original_bytes, "a dry run must write nothing at all"

    applied = repair.run(
        apply=True, event_path=log,
        projection_path=tmp_path / "proj.json", cursor_path=tmp_path / "cur.json",
    )
    assert applied["repaired"] == 3
    assert applied["events_after"] == applied["events_before"] + 3

    new_bytes = log.read_bytes()
    assert new_bytes.startswith(original_bytes), "history was rewritten, not appended to"

    events = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    appended = [e for e in events if e["event_type"] == "GOAL_UPDATED"]
    assert len(appended) == 3

    fixed = repair.run(apply=False, event_path=log)
    assert fixed["inverted_found"] == 0, "the repair did not actually fix the inversion"

    store = G.CIOGoalStore(
        event_path=log,
        projection_path=tmp_path / "proj2.json",
        cursor_path=tmp_path / "cur2.json",
    )
    for goal in store._goals.values():
        assert G._parse_ts(goal["due_ts"]) >= G._parse_ts(goal["created_ts"])
