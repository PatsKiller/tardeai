"""P3 versioned thesis store — publish, pin, plan linkage, context."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def thesis_store(tmp_path: Path):
    from scripts.lib.cio_theses import CIOThesisStore
    return CIOThesisStore(
        event_path=tmp_path / "cio_theses.jsonl",
        projection_path=tmp_path / "cio_theses_projection.json",
    )


def test_publish_versions_and_pin(thesis_store):
    from scripts.lib.cio_theses import make_pin, parse_pin

    v1 = thesis_store.publish(
        "Risk-aware observe-only; escalate material drift.",
        owner_agent="alex",
        stance="defensive",
        bullets=["No new risk without operator", "Cash buffer preferred"],
        change_note="initial",
        actor_id="test",
    )
    assert v1["version"] == 1
    assert v1["thesis_version"] == "desk@v1"
    assert v1["status"] == "active"
    assert parse_pin(v1["thesis_version"]) == ("desk", 1)
    assert make_pin("desk", 1) == "desk@v1"

    v2 = thesis_store.publish(
        "Same, but watch SpaceX reclaim basis carefully.",
        owner_agent="alex",
        linked_symbols=["SPACEX_TEST"],
        change_note="spacex note",
        actor_id="test",
    )
    assert v2["version"] == 2
    assert v2["thesis_version"] == "desk@v2"
    assert v2["parent_version"] == 1

    cur = thesis_store.get_current("desk")
    assert cur["version"] == 2
    old = thesis_store.get_version("desk", 1)
    assert old is not None
    assert old["status"] == "superseded"
    assert thesis_store.get_by_pin("desk@v1")["summary"].startswith("Risk-aware")
    hist = thesis_store.list_versions("desk", limit=5)
    assert len(hist) == 2
    assert hist[0]["version"] == 2


def test_rebuild_projection(tmp_path: Path):
    from scripts.lib.cio_theses import CIOThesisStore

    path = tmp_path / "t.jsonl"
    proj = tmp_path / "p.json"
    s1 = CIOThesisStore(event_path=path, projection_path=proj)
    s1.publish("A", actor_id="t")
    s1.publish("B", actor_id="t")
    # reload without projection
    proj.unlink()
    s2 = CIOThesisStore(event_path=path, projection_path=proj)
    assert s2.get_current()["summary"] == "B"
    assert s2.get_current()["version"] == 2


def test_theme_thesis_and_archive(thesis_store):
    t = thesis_store.publish(
        "Defense sleeve overweight vs model.",
        thesis_id="theme_defense",
        owner_agent="maria",
        actor_id="test",
    )
    assert t["thesis_id"] == "theme_defense"
    assert t["thesis_version"] == "theme_defense@v1"
    thesis_store.archive("theme_defense", reason="stale", actor_id="test")
    assert thesis_store.get_current("theme_defense")["status"] == "archived"


def test_link_plan_goal(thesis_store):
    thesis_store.publish("Desk thesis", actor_id="t")
    thesis_store.link(
        "desk",
        plan_ids=["plan_abc"],
        goal_ids=["goal_xyz"],
        symbols=["SPY"],
        actor_id="t",
    )
    cur = thesis_store.get_current()
    assert "plan_abc" in cur["linked_plan_ids"]
    assert "goal_xyz" in cur["linked_goal_ids"]
    assert "SPY" in cur["linked_symbols"]


def test_plan_auto_pins_current_thesis(tmp_path: Path, monkeypatch):
    from scripts.lib.cio_theses import CIOThesisStore
    from scripts.lib.cio_plans import CIOPlanStore

    tstore = CIOThesisStore(
        event_path=tmp_path / "theses.jsonl",
        projection_path=tmp_path / "theses_proj.json",
    )
    pin = tstore.publish("Living desk thesis v1", actor_id="t")["thesis_version"]

    # Point safe_current_pin at our temp store
    import scripts.lib.cio_theses as ct
    import scripts.lib.cio_plans as cp

    monkeypatch.setattr(ct, "DEFAULT_EVENT_PATH", tmp_path / "theses.jsonl")
    monkeypatch.setattr(ct, "DEFAULT_PROJECTION_PATH", tmp_path / "theses_proj.json")
    # recreate default path used by safe_current_pin
    monkeypatch.setattr(
        ct,
        "safe_current_pin",
        lambda thesis_id="desk": tstore.current_pin(thesis_id),
    )

    pstore = CIOPlanStore(
        event_path=tmp_path / "plans.jsonl",
        projection_path=tmp_path / "plans_proj.json",
    )
    plan = pstore.create_plan(
        situation_type="S1_POSITION_LIFECYCLE",
        symbols=["SPACEX_TEST"],
        title="test",
        summary="held",
        options=[{"id": "hold", "label": "Hold", "pros": "", "cons": ""}],
        recommendation="review",
        evidence_refs=[{"domain": "holdings_detail"}],
        revisit_at="2099-01-01T00:00:00+00:00",
        owner_agent="alex",
        actor_id="test",
    )
    assert plan.get("thesis_version") == pin


def test_evidence_pack_includes_desk_thesis(tmp_path: Path, monkeypatch):
    from scripts.lib.cio_theses import CIOThesisStore
    from scripts.lib.cio_plan_enrichment import build_evidence_pack
    import scripts.lib.cio_theses as ct

    tstore = CIOThesisStore(
        event_path=tmp_path / "theses.jsonl",
        projection_path=tmp_path / "theses_proj.json",
    )
    pin = tstore.publish(
        "Observe only; no new leverage.",
        stance="cautious",
        bullets=["cash first"],
        actor_id="t",
    )["thesis_version"]

    monkeypatch.setattr(
        ct,
        "safe_context_block",
        lambda thesis_id="desk": tstore.context_block(thesis_id),
    )
    # CIOThesisStore() default still hits real paths for get_by_pin — patch class default
    monkeypatch.setattr(ct, "DEFAULT_EVENT_PATH", tmp_path / "theses.jsonl")
    monkeypatch.setattr(ct, "DEFAULT_PROJECTION_PATH", tmp_path / "theses_proj.json")

    pack = build_evidence_pack({
        "plan_id": "plan_1",
        "situation_type": "S1_POSITION_LIFECYCLE",
        "symbols": ["AAA"],
        "title": "t",
        "summary": "s",
        "recommendation": "r",
        "options": [],
        "evidence_refs": [{"domain": "holdings_detail", "basis": 1}],
        "thesis_version": pin,
    })
    assert pack.get("thesis_version") == pin
    assert pack.get("desk_thesis")
    assert "Observe only" in (pack["desk_thesis"].get("summary") or "")


def test_context_for_agent_includes_desk_thesis(tmp_path: Path, monkeypatch):
    from scripts.lib.cio_goals import CIOGoalStore
    from scripts.lib.cio_theses import CIOThesisStore
    import scripts.lib.cio_theses as ct

    tstore = CIOThesisStore(
        event_path=tmp_path / "theses.jsonl",
        projection_path=tmp_path / "theses_proj.json",
    )
    tstore.publish("Desk living thesis", actor_id="t")
    monkeypatch.setattr(
        ct,
        "safe_context_block",
        lambda thesis_id="desk": tstore.context_block(thesis_id),
    )

    gstore = CIOGoalStore(
        event_path=tmp_path / "goals.jsonl",
        projection_path=tmp_path / "goals_proj.json",
        cursor_path=tmp_path / "cursors.json",
    )
    gstore.create_goal(
        owner_agent="alex",
        title="g1",
        thesis_summary="goal-level note",
        actor_id="t",
    )
    ctx = gstore.get_context_for_agent("alex")
    assert ctx.get("desk_thesis")
    assert ctx["desk_thesis"]["summary"] == "Desk living thesis"
    assert any(s.get("thesis_summary") == "goal-level note" for s in ctx.get("thesis_snippets") or [])


def test_invalid_thesis_id():
    from scripts.lib.cio_theses import CIOThesisStore
    from pathlib import Path
    import tempfile
    td = Path(tempfile.mkdtemp())
    s = CIOThesisStore(event_path=td / "e.jsonl", projection_path=td / "p.json")
    with pytest.raises(ValueError):
        s.publish("x", thesis_id="NOT VALID", actor_id="t")
