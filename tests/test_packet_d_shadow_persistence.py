"""Packet D persists SHADOW acceptance evidence via agent_runtime persistence APIs."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MOD_PATH = ROOT / "scripts" / "operator_packets" / "packet_d_shadow_acceptance.py"
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location("packet_d_persist", MOD_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _stub(n_good: int = 100, n_bad: int = 20):
    def _src():
        rows = []
        for i in range(n_good):
            rows.append({
                "artifact_id": f"good-{i}",
                "symbol": f"G{i}",
                "producer_agent_id": mod.PRODUCER_AGENT_ID,
                "is_known_bad": False,
            })
        for i in range(n_bad):
            rows.append({
                "artifact_id": f"bad-{i}",
                "symbol": f"B{i}",
                "producer_agent_id": mod.PRODUCER_AGENT_ID,
                "is_known_bad": True,
            })
        return rows
    return _src


def test_persist_with_inmemory_store():
    from agent_runtime.persistence import InMemoryPersistence

    store = InMemoryPersistence()
    dsn = "postgresql://agentic_runtime_shadow_rw:pw@127.0.0.1:5433/trade_ai_agentic_lab"
    report = mod.run_shadow(dsn, source=_stub(100, 20), store=store, persist=True)
    assert report.agents_marked_operational == 0
    assert report.persisted.get("runs") == 1
    assert report.persisted.get("artifacts") == 120
    assert report.persisted.get("reviews") == 120
    assert report.persisted.get("scores") == 120
    # known-bad (20) → lessons+cases+chunks; good PASS (100) → lessons+chunks
    assert report.persisted.get("kb_lessons", 0) >= 20
    assert report.persisted.get("kb_cases", 0) >= 20
    assert report.persisted.get("kb_chunks", 0) >= 20
    assert report.run_id.startswith("shadow-d-")
    ok, fails = report.evaluate()
    assert ok, fails
    # reconstruct proves durable journal/control
    state = store.reconstruct(report.run_id)
    assert len(state.artifacts) == 120
    assert len(state.reviews) == 120
    assert len(state.scores) == 120
    # InMemory table sizes for KB
    assert len(store._store.tables["kb_lessons"]) >= 20
    assert len(store._store.tables["kb_cases"]) >= 20
    assert len(store._store.tables["kb_chunks"]) >= 20
    # Lessons are CANDIDATE only (never auto-promoted)
    for row in store._store.tables["kb_lessons"].values():
        assert row.get("lifecycle") == "CANDIDATE"
        assert row.get("created_by") == mod.IRIS_AGENT_ID
        assert row.get("created_by") != mod.PRODUCER_AGENT_ID


def test_persist_skipped_when_persist_false():
    dsn = "postgresql://agentic_runtime_shadow_rw:pw@127.0.0.1:5433/trade_ai_agentic_lab"
    report = mod.run_shadow(dsn, source=_stub(100, 20), persist=False)
    assert report.persisted.get("artifacts", 0) == 0
    ok, _ = report.evaluate()
    assert ok


def test_prod_dsn_still_refused_before_persist():
    from agent_runtime.persistence import InMemoryPersistence
    with pytest.raises(mod.ShadowGuardError):
        mod.run_shadow(
            "postgresql://agentic_runtime_shadow_rw:pw@127.0.0.1:5432/trade_ai",
            source=_stub(5, 2),
            store=InMemoryPersistence(),
        )


def test_kb_lesson_idempotent_on_rerun():
    from agent_runtime.persistence import InMemoryPersistence

    store = InMemoryPersistence()
    dsn = "postgresql://agentic_runtime_shadow_rw:pw@127.0.0.1:5433/trade_ai_agentic_lab"
    # Fixed started_at via small stub path: call persist twice with same store/rows
    report1 = mod.run_shadow(dsn, source=_stub(5, 3), store=store, persist=True)
    n1 = report1.persisted.get("kb_lessons", 0)
    assert n1 >= 3
    # Second population with new started_at creates new run + new lesson ids (aid-stable lessons
    # share lesson_id shadow-lesson-{aid} — re-insert same version is idempotent no-op)
    report2 = mod.run_shadow(dsn, source=_stub(5, 3), store=store, persist=True)
    assert report2.persisted.get("kb_lessons", 0) >= 3
    # Table should not explode with conflicting versions
    for row in store._store.tables["kb_lessons"].values():
        assert row.get("lesson_version") == 1
        assert row.get("lifecycle") == "CANDIDATE"


def test_second_run_preloaded_artifacts_known_bad_and_kb():
    """Re-run against an InMemory store that already holds first-run artifacts.

    Host failure mode after #216+#217: known_bad=0, kb_*=0, duplicate_run_rate fail.
    Second run must still process ≥20 known-bad and report ≥20 kb_lessons (CANDIDATE),
    and must not fail thresholds on intentional idempotent skips.
    """
    from agent_runtime.persistence import InMemoryPersistence

    store = InMemoryPersistence()
    dsn = "postgresql://agentic_runtime_shadow_rw:pw@127.0.0.1:5433/trade_ai_agentic_lab"
    src = _stub(100, 20)

    report1 = mod.run_shadow(dsn, source=src, store=store, persist=True)
    assert report1.known_bad_fixtures_processed >= 20
    assert report1.persisted.get("kb_lessons", 0) >= 20
    assert len(store._store.tables["agent_artifacts"]) >= 20
    n_lessons_after_first = len(store._store.tables["kb_lessons"])
    assert n_lessons_after_first >= 20

    # Second run: same store (preloaded artifacts/reviews/scores/kb), new run envelope
    report2 = mod.run_shadow(dsn, source=src, store=store, persist=True)
    assert report2.known_bad_fixtures_processed >= 20
    assert report2.persisted.get("kb_lessons", 0) >= 20
    assert len(store._store.tables["kb_lessons"]) >= 20
    # Lessons remain CANDIDATE; no version explosion
    for row in store._store.tables["kb_lessons"].values():
        assert row.get("lifecycle") == "CANDIDATE"
        assert row.get("lesson_version") == 1
        assert row.get("created_by") == mod.IRIS_AGENT_ID
    ok, fails = report2.evaluate()
    assert ok, fails
    # Intentional re-run may record skips; must not treat them as hard failures
    assert report2.failures == 0 or report2.idempotent_skips > 0
