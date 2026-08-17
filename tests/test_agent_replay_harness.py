"""Phase 2.5 — dry replay harness unit tests.

No broker, no network. Deterministic only. The harness is DRY-ONLY and must
never invoke a notify callback or write to production stores.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_replay_harness import (  # noqa: E402
    load_wake_traces,
    render_replay_report,
    replay_wakes,
)


def _write_fixture(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "wake_fixture.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


# ── load_wake_traces ───────────────────────────────────────────────────────


def test_load_wake_traces_parses_real_shaped_and_skips_blanks(tmp_path):
    rows = [
        {"agent_id": "alex", "wake_id": "w1", "trace_id": "tr_1", "phase": "open"},
        {"agent_id": "alex", "wake_id": "w2", "trace_id": "tr_2", "phase": "close"},
    ]
    raw = [
        json.dumps(rows[0]),
        "",  # blank
        "   ",  # whitespace-only
        "{not valid json",  # invalid
        json.dumps(rows[1]),
        '["this", "is", "a", "list"]',  # valid JSON but not a dict
        "",
    ]
    path = tmp_path / "wake_fixture_raw.jsonl"
    path.write_text("\n".join(raw) + "\n", encoding="utf-8")

    loaded = load_wake_traces(path)
    assert loaded == rows
    assert len(loaded) == 2


def test_load_wake_traces_missing_file_returns_empty(tmp_path):
    assert load_wake_traces(tmp_path / "does_not_exist.jsonl") == []


# ── trace coverage / completeness ──────────────────────────────────────────


def test_replay_trace_coverage_computed(tmp_path):
    rows = [
        {"agent_id": "alex", "wake_id": "w1", "trace_id": "tr_1", "phase": "open"},
        {"agent_id": "alex", "wake_id": "w2", "trace_id": "tr_2", "phase": "close"},
        {"agent_id": "alex", "wake_id": "w3", "trace_id": "", "phase": "open"},
    ]
    metrics = replay_wakes(_write_fixture(tmp_path, rows))
    assert metrics["number_of_wakes"] == 3
    assert metrics["trace_coverage"] == pytest.approx(2 / 3)
    assert metrics["trace_completeness"] == pytest.approx(1 / 3)


def test_replay_traced_vs_lineage_break(tmp_path):
    rows = [
        {"agent_id": "alex", "wake_id": "w_traced", "trace_id": "tr_1", "phase": "open"},
        {"agent_id": "alex", "wake_id": "w_broken", "trace_id": "", "phase": "open"},
    ]
    metrics = replay_wakes(_write_fixture(tmp_path, rows))
    assert metrics["trace_coverage"] == pytest.approx(0.5)
    assert metrics["decision_lineage_breaks"] == 1
    # Empty trace_id alone is a lineage break, not a context build failure.
    assert metrics["context_build_failures"] == 0


# ── context build failure ──────────────────────────────────────────────────


def test_replay_context_build_failure_counted(tmp_path):
    rows = [
        {"agent_id": "alex", "wake_id": "w1", "trace_id": "tr_1", "phase": "open"},
        {"agent_id": "alex", "wake_id": "w2", "trace_id": "tr_2", "phase": "open"},
    ]

    def loader(wake):
        if wake.get("wake_id") == "w2":
            raise RuntimeError("missing truth")
        return None

    metrics = replay_wakes(_write_fixture(tmp_path, rows), decision_loader=loader)
    assert metrics["context_build_failures"] == 1


# ── follow-up binding ──────────────────────────────────────────────────────


def test_replay_missing_next_review_for_wait_no_binding(tmp_path):
    rows = [
        {"agent_id": "alex", "wake_id": "w1", "trace_id": "tr_1", "phase": "open"},
    ]

    def loader(wake):
        return {"decision_id": "dec_1", "current_action": "WAIT", "act_now": False}

    metrics = replay_wakes(_write_fixture(tmp_path, rows), decision_loader=loader)
    assert metrics["missing_next_review"] == 1
    assert metrics["notifications_considered"] == 1
    # WAIT with act_now=False is non-material → suppressed, never sent.
    assert metrics["notifications_sent"] == 0
    assert metrics["suppressed"] == 1


def test_replay_bound_next_review_not_missing(tmp_path):
    rows = [
        {"agent_id": "alex", "wake_id": "w1", "trace_id": "tr_1", "phase": "open"},
    ]

    def loader(wake):
        return {
            "decision_id": "dec_1",
            "current_action": "WAIT",
            "act_now": False,
            "next_review": {
                "kind": "TIME",
                "due_at": "2026-08-17T00:00:00Z",
                "revisit_id": "rv_1",
            },
        }

    metrics = replay_wakes(_write_fixture(tmp_path, rows), decision_loader=loader)
    assert metrics["missing_next_review"] == 0


# ── notification simulation / dedupe ───────────────────────────────────────


def test_replay_duplicate_unchanged_suppressed(tmp_path):
    rows = [
        {"agent_id": "alex", "wake_id": "w1", "trace_id": "tr_1", "phase": "open"},
        {"agent_id": "alex", "wake_id": "w2", "trace_id": "tr_2", "phase": "open"},
    ]
    decision = {
        "decision_id": "dec_1",
        "current_action": "ACT_NOW",
        "act_now": True,
        "decision_input_digest": "in_1",
        "decision_evidence_digest": "ev_1",
    }

    def loader(wake):
        return dict(decision)

    metrics = replay_wakes(_write_fixture(tmp_path, rows), decision_loader=loader)
    assert metrics["notifications_considered"] == 2
    assert metrics["notifications_sent"] == 1
    assert metrics["suppressed"] == 1
    assert metrics["duplicate_unchanged"] == 1


# ── DRY-ONLY: no network / no notify call ──────────────────────────────────


def test_replay_never_calls_notify(tmp_path):
    calls = []

    def sentinel_notify(**kwargs):
        calls.append(kwargs)
        raise AssertionError("notify must never be invoked")

    rows = [
        {"agent_id": "alex", "wake_id": "w1", "trace_id": "tr_1", "phase": "open"},
    ]

    def loader(wake):
        # A material decision that WOULD be sent, to prove we still never call.
        return {"decision_id": "dec_1", "current_action": "ACT_NOW", "act_now": True}

    metrics = replay_wakes(
        _write_fixture(tmp_path, rows),
        decision_loader=loader,
        notify=sentinel_notify,
    )
    assert calls == []
    # The computed simulation still records a would-be send.
    assert metrics["notifications_sent"] == 1


# ── report rendering ───────────────────────────────────────────────────────


def test_render_replay_report_renders():
    metrics = {
        "number_of_wakes": 3,
        "trace_coverage": 2 / 3,
        "trace_completeness": 1 / 3,
        "decision_lineage_breaks": 1,
        "context_build_failures": 0,
        "notifications_considered": 1,
        "notifications_sent": 0,
        "suppressed": 1,
        "duplicate_unchanged": 0,
        "missing_next_review": 1,
        "operator_dispositions_recovered": 0,
    }
    report = render_replay_report(metrics)
    assert isinstance(report, str)
    assert report
    assert "Dry Replay Report" in report
    assert "trace coverage" in report
    assert "missing next-review binding" in report
    assert "3" in report
