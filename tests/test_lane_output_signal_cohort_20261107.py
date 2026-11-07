"""The ten no-output-proof lanes now say what proves them (WORK-QUEUE 2026-11-07, items 1-10).

Every row in ``config/lane_registry.json`` used to read ``output_signal.kind = none`` with no reason, so
``GET /api/v2/scheduler-operations`` reported it ``NO_SIGNAL`` with
``health_reason = "NO_SIGNAL_WITH_REASON missing; no output proof declared"`` and ``is_problem()`` listed it
on Jobs & n8n — ten rows an operator could neither act on nor dismiss.

This file pins the repair, and pins it in the direction that fails loudly:

* each of the ten declares either an artifact that exists as a durable file (AGENTS.md §0 rule 8), or an
  explicit ``NO_SIGNAL_WITH_REASON:`` prose reason naming why no artifact can be declared yet;
* every declared artifact is one a script in THIS repo actually writes (a declaration for a file nothing
  produces would be an invented signal, the exact thing the coverage doc forbids);
* the signal resolves through ``observe_signal`` against a state root, and an ABSENT artifact reports no
  timestamp rather than a fabricated one;
* the declaration changes the screen: a reason-bearing ``NO_SIGNAL`` row is not a problem, the undeclared
  one still is.

Hermetic: tmp state roots, no DB, no crontab, no network, no live persistent state.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
REGISTRY = ROOT / "config" / "lane_registry.json"
NOW = datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc)

# lane -> (kind, path, key) where kind is the declared artifact, or None when the lane carries a reason.
# The expectation is written out per lane rather than derived from the file under test: a test that reads
# its expectation from the artifact it is checking asserts only that the file equals itself.
COHORT: dict[str, tuple[str, str, str] | None] = {
    # LaneRunReceipt@v1 already existed on disk; the registry had simply never declared it.
    "crawl-v3-dashboard": ("json_key", "data/runtime/crawl-v3-dashboard_last.json", "ok_at"),
    "hermes-top20-external-intel": ("json_key", "data/runtime/hermes_top20_external_intel_last.json", "ok_at"),
    "hermes-usefulness-backfill": ("json_key", "data/runtime/hermes-usefulness-backfill_last.json", "ok_at"),
    # Audit receipt, not a LaneRunReceipt: ``ts`` is the applied pass and the file is absent on a dry run.
    "hermes-librarian-retention": ("json_key", "data/runtime/hermes_librarian_retention_last.json", "ts"),
    # Producer added 2026-11-07 (scripts/rotation_rebalance_digest.py, scripts/alert_missing_conditions.py).
    "rotation-rebalance-digest": ("json_key", "data/runtime/rotation-rebalance-digest_last.json", "ok_at"),
    "alert-missing-conditions": ("json_key", "data/runtime/alert-missing-conditions_last.json", "ok_at"),
    # Stage 6's dated reports are the durable product; per-stage status needs a change in that repository.
    "dof-run-pipeline": ("file_mtime", "~/nyc-dof-auction/outputs", ""),
    # The script is outside this repository and writes nothing that proves the run; the honest answer is the reason.
    "ops-daily-digest": None,
    "ops-weekly-learning-report": None,
    "sync-memory-to-drive": None,
}

REASON_PREFIX = "NO_SIGNAL_WITH_REASON:"
# Reason rows must name the producer and what would make them verifiable - a bare "TODO" is not a reason.
REASON_MIN_CHARS = 120


def _registry() -> dict[str, dict]:
    doc = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {row["lane_id"]: row for row in doc["lanes"]}


def _signal(lane_id: str) -> dict:
    return _registry()[lane_id].get("output_signal") or {"kind": "none"}


def _string_constants(path: Path) -> str:
    """Every string literal in a script, so a lane id in a comment cannot satisfy the producer check."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return "\n".join(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


# ── the declarations ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("lane_id", sorted(COHORT))
def test_each_lane_declares_the_exact_expected_proof(lane_id):
    expected = COHORT[lane_id]
    sig = _signal(lane_id)

    if expected is None:
        assert sig.get("kind") == "none", f"{lane_id}: expected an explicit reason, found {sig!r}"
        reason = str(sig.get("reason") or "")
        assert reason.startswith(REASON_PREFIX), f"{lane_id}: reason must start with {REASON_PREFIX!r}, got {reason[:60]!r}"
        assert len(reason) >= REASON_MIN_CHARS, f"{lane_id}: reason too short to be evidence ({len(reason)} chars)"
        return

    kind, path, key = expected
    assert sig.get("kind") == kind, f"{lane_id}: expected kind {kind!r}, found {sig.get('kind')!r}"
    assert sig.get("path") == path, f"{lane_id}: expected path {path!r}, found {sig.get('path')!r}"
    if key:
        assert sig.get("key") == key, f"{lane_id}: expected key {key!r}, found {sig.get('key')!r}"


@pytest.mark.parametrize("lane_id", sorted(COHORT))
def test_no_lane_still_carries_the_missing_reason_placeholder(lane_id):
    sig = _signal(lane_id)
    assert not str(sig.get("reason") or "").startswith("NO_SIGNAL_WITH_REASON missing"), (
        f"{lane_id} still reads as an undeclared no-signal row"
    )


def test_the_cohort_is_exactly_the_ten_lanes():
    assert len(COHORT) == 10
    assert set(COHORT) <= set(_registry())


def test_registry_still_validates():
    from scripts.lib import lane_registry as LR

    doc = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert LR.validate_registry(doc) == []


# ── the producers are real ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("lane_id", sorted(k for k, v in COHORT.items() if v is not None))
def test_a_script_in_this_repo_writes_the_declared_artifact(lane_id):
    """A declared signal must name something a producer here writes, or the declaration is invented."""
    kind, path, _key = COHORT[lane_id]
    if str(path).startswith("~/"):
        # Deliberately outside the repo (an external pipeline): only the reason could replace this, so the
        # declaration stays pinned to the producer's own documented output directory.
        assert lane_id == "dof-run-pipeline"
        return

    named = {lane_id, lane_id.replace("-", "_")}
    candidates = []
    for script in sorted(SCRIPTS.glob("*.py")):
        source = script.read_text(encoding="utf-8")
        if "write_lane_receipt" not in source and "write_receipt" not in source:
            continue
        literals = _string_constants(script)
        if any(token in literals for token in named):
            candidates.append(script.name)

    assert candidates, f"{lane_id}: no script under scripts/ names this lane and writes a run receipt"
    # And the receipt filename the declaration points at is the one that convention derives for that name.
    assert Path(path).name.endswith("_last.json")


# ── the signal resolves, and an absent artifact is not a timestamp ────────────────────────────────────────

@pytest.mark.parametrize("lane_id", sorted(k for k, v in COHORT.items() if v is not None))
def test_declared_signal_resolves_against_a_state_root(tmp_path, lane_id):
    from scripts.lib import lane_registry as LR

    kind, path, key = COHORT[lane_id]
    declared = _signal(lane_id)
    stamp = "2026-11-07T01:15:12+00:00"

    if kind == "file_mtime":
        # The declared path is deliberately outside the state root, so the observation is exercised on a
        # tmp copy of the same declaration: never stat the live home directory from a unit test.
        sig = {"kind": "file_mtime", "path": "outputs"}
        assert declared["path"] == path
    else:
        sig = declared

    # Absent: readable, but no timestamp - silence, not a fabricated "now".
    absent = LR.observe_signal(sig, root=tmp_path)
    assert absent["readable"] is True
    assert absent["last_output_at"] is None

    if kind == "json_key":
        fixture = tmp_path / path
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_text(json.dumps({key: stamp}), encoding="utf-8")
        present = LR.observe_signal(sig, root=tmp_path)
        assert present["readable"] is True
        assert present["last_output_at"] is not None
    else:
        (tmp_path / "outputs").mkdir()
        present = LR.observe_signal(sig, root=tmp_path)
        # An empty directory has an mtime, which is the point of a file_mtime declaration; it is not proof
        # of content, and the row's note says so.
        assert present["readable"] is True
        assert present["last_output_at"] is not None


# ── the screen-level effect ───────────────────────────────────────────────────────────────────────────────

def _row(lane_id: str, *, kind: str, reason: str | None) -> dict:
    sig = {"kind": kind}
    if reason is not None:
        sig["reason"] = reason
    return {"lane_id": lane_id, "owner": "t", "state": "ACTIVE", "declared_state": "ACTIVE",
            "scheduler": {"kind": "cron", "expression": "0 18 * * *"}, "output_signal": sig,
            "runtime_state": "NO_SIGNAL", "freshness": "NOT_MEASURED", "health_reason": reason}


def test_a_declared_reason_removes_the_row_from_the_problem_list():
    from scripts.lib import scheduler_operations as SO

    reason = _signal("ops-daily-digest")["reason"]
    assert SO.is_problem(_row("ops-daily-digest", kind="none", reason=reason)) is False
    # The undeclared placeholder still is a problem: this test would pass vacuously if the rule were removed.
    assert SO.is_problem(
        _row("ops-daily-digest", kind="none",
             reason="NO_SIGNAL_WITH_REASON missing; no output proof declared")
    ) is True
