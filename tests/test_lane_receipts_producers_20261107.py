"""The five bundle lanes whose declared output_signal had no producer (LQ-20261107-23 receipt gap).

Each lane's registry/allowlist row declares ``output_signal: data/runtime/<lane>_last.json`` and the n8n
health contract reads ``ok_at`` from it. Five of the seven lanes in the bundle declared that path but no
code in the tree ever wrote it (``scripts/rag_indexer.py`` and ``scripts/hermes_scope_governor.py`` did),
so a cutover would have produced a lane that runs and grades EMPTY on its first live run. The gate does
not verify the write: a declaration without a producer passes the plan.

What is asserted here, per lane, with synthetic fixtures only (no DB, no network, no sender):

* a REAL run writes the receipt at exactly the path the allowlist declares, with ``ok_at`` and v2 output
  fields (produced_count / attempted_count / empty_reason), so the health contract can read it;
* a DRY run writes NOTHING (no receipt file at all) — ``dry_run_report`` prints instead;
* a FAILED run writes ``status: failed`` with ``ok_at`` absent, so a failing lane goes stale instead of
  keeping a previous success looking green (a receipt must cover every exit);
* a run the executor identifies (TRADEAI_RUN_ID) also writes the immutable per-attempt v2 receipt the
  executor's ``output_verdict`` reads.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

ALLOWLIST = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
_LANES = {row["lane_id"]: row for row in (ALLOWLIST.get("lanes") or ALLOWLIST)}

LANE_MODULES = {
    "agent-event-router": "agent_event_router",
    "hermes-youtube-discovery": "hermes_youtube_discovery",
    "plan-drift-revalidator": "plan_drift_revalidator",
    "run-scalp-shadow-logger": "scalp_shadow_logger",
    "social-scalp-scanner": "social_scalp_scanner",
}


def _import(name: str):
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    return importlib.import_module(name)


@pytest.fixture()
def state_root(tmp_path, monkeypatch):
    """Every receipt in these tests lands under the test's own root, never the live runtime dir."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    for env in ("TRADEAI_RUN_ID", "TRADEAI_RUN_ATTEMPT", "TRADEAI_RUN_MODE", "TRADEAI_CODE_SHA"):
        monkeypatch.delenv(env, raising=False)
    return tmp_path


def _runtime(root: Path) -> Path:
    return root / "data" / "runtime"


def _receipt(root: Path, lane_id: str) -> dict:
    return json.loads((_runtime(root) / f"{lane_id}_last.json").read_text(encoding="utf-8"))


def _assert_wrote_nothing(root: Path) -> None:
    wrote = sorted(p.name for p in _runtime(root).rglob("*")) if (_runtime(root)).exists() else []
    assert wrote == [], f"a dry run must write no receipt, wrote {wrote}"


# ── the declaration/producer contract, statically ────────────────────────────────────────────────


@pytest.mark.parametrize("lane_id,module_name", sorted(LANE_MODULES.items()))
def test_each_lane_declares_a_runtime_receipt_and_its_module_writes_that_lane(lane_id, module_name, state_root):
    """The allowlist path and the module's own LANE_ID must be the same file, or the contract reads a ghost."""
    row = _LANES.get(lane_id)
    if row is None:
        # These five rows ship in the onboarding bundle and are not in config/n8n_run_allowlist.json at this
        # base; the moment the bundle is applied this becomes a full assertion instead of a skip.
        pytest.skip("lane declared in the onboarding bundle; not yet applied to config/n8n_run_allowlist.json")
    assert row["output_signal"] == f"data/runtime/{lane_id}_last.json"
    mod = _import(module_name)
    assert mod.LANE_ID == lane_id
    src = (ROOT / "scripts" / f"{module_name}.py").read_text(encoding="utf-8")
    assert "write_lane_receipt" in src and "dry_run_report" in src


# ── lane 1: agent-event-router ───────────────────────────────────────────────────────────────────


def test_agent_event_router_writes_a_v2_receipt_on_a_real_run_and_an_attempt_copy(state_root, monkeypatch):
    mod = _import("agent_event_router")
    monkeypatch.setattr(mod, "drain_queue", lambda dry: 3)
    monkeypatch.setattr(sys, "argv", ["agent_event_router.py"])
    monkeypatch.setenv("TRADEAI_RUN_ID", "test-run-1")
    monkeypatch.setenv("TRADEAI_RUN_ATTEMPT", "1")
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")

    mod.main()

    doc = _receipt(state_root, "agent-event-router")
    assert doc["status"] == "ok" and doc["ok_at"]
    assert doc["output_fields"] == "LaneRunReceipt@v2"
    assert doc["produced_count"] == 3 and doc["attempted_count"] == 3 and doc["empty_reason"] is None
    attempt = _runtime(state_root) / "lane_attempts" / "agent-event-router" / "test-run-1.json"
    assert attempt.exists(), "the executor's output_verdict reads only the per-attempt receipt"
    assert json.loads(attempt.read_text())["schema"] == "LaneRunReceipt@v2"


def test_agent_event_router_dry_run_writes_nothing(state_root, monkeypatch):
    mod = _import("agent_event_router")
    monkeypatch.setattr(mod, "drain_queue", lambda dry: 0)
    monkeypatch.setattr(sys, "argv", ["agent_event_router.py", "--dry-run"])
    mod.main()
    _assert_wrote_nothing(state_root)


def test_agent_event_router_failure_receipt_does_not_look_green(state_root, monkeypatch):
    mod = _import("agent_event_router")

    def boom(dry):
        raise RuntimeError("db gone")

    monkeypatch.setattr(mod, "drain_queue", boom)
    monkeypatch.setattr(sys, "argv", ["agent_event_router.py"])
    with pytest.raises(SystemExit):
        mod.main()
    doc = _receipt(state_root, "agent-event-router")
    assert doc["status"] == "failed" and doc["ok_at"] is None and doc["error"] == "RuntimeError"


# ── lane 2: hermes-youtube-discovery ─────────────────────────────────────────────────────────────


class _FakeConn:
    def cursor(self):
        return object()

    def commit(self):
        pass

    def close(self):
        pass


def _stub_youtube_deps(monkeypatch, rows_written=1):
    db = types.ModuleType("db_adapter")
    db.get_connection = lambda: _FakeConn()
    ingest = types.ModuleType("youtube_transcript_ingest")
    ingest.ingest_video = lambda url, added_by=None: {"status": "ok"}
    writer = types.ModuleType("lib.writers.hermes_research_writer")
    writer.write_research_rows = lambda cur, rows, producer=None: types.SimpleNamespace(rows_written=rows_written)
    monkeypatch.setitem(sys.modules, "db_adapter", db)
    monkeypatch.setitem(sys.modules, "youtube_transcript_ingest", ingest)
    monkeypatch.setitem(sys.modules, "lib.writers.hermes_research_writer", writer)
    monkeypatch.setattr("time.sleep", lambda s: None)


def test_youtube_discovery_writes_its_receipt_and_counts_staged_findings(state_root, monkeypatch):
    mod = _import("hermes_youtube_discovery")
    _stub_youtube_deps(monkeypatch, rows_written=1)
    monkeypatch.setattr(mod, "get_targets", lambda limit: ["AAAA", "BBBB"])
    monkeypatch.setattr(mod, "searx_youtube", lambda q, n=3: ["https://youtu.be/x"])
    monkeypatch.setattr(sys, "argv", ["hermes_youtube_discovery.py", "--apply", "--limit", "2"])

    assert mod.main() == 0

    doc = _receipt(state_root, "hermes-youtube-discovery")
    assert doc["status"] == "ok" and doc["ok_at"]
    assert doc["produced_count"] == 2, "two staged hermes_research rows"
    assert doc["attempted_count"] == 2 and doc["empty_reason"] is None


def test_youtube_discovery_failure_writes_a_failed_receipt(state_root, monkeypatch):
    mod = _import("hermes_youtube_discovery")
    _stub_youtube_deps(monkeypatch)

    def boom(limit):
        raise RuntimeError("watchlist unreadable")

    monkeypatch.setattr(mod, "get_targets", boom)
    monkeypatch.setattr(sys, "argv", ["hermes_youtube_discovery.py", "--apply"])
    with pytest.raises(RuntimeError):
        mod.main()
    doc = _receipt(state_root, "hermes-youtube-discovery")
    assert doc["status"] == "failed" and doc["ok_at"] is None


def test_youtube_discovery_without_apply_writes_no_receipt(state_root, monkeypatch):
    mod = _import("hermes_youtube_discovery")
    _stub_youtube_deps(monkeypatch)
    monkeypatch.setattr(mod, "get_targets", lambda limit: ["AAAA"])
    monkeypatch.setattr(mod, "searx_youtube", lambda q, n=3: [])
    monkeypatch.setattr(sys, "argv", ["hermes_youtube_discovery.py"])
    assert mod.main() == 0
    _assert_wrote_nothing(state_root)


# ── lane 3: plan-drift-revalidator ──────────────────────────────────────────────────────────────


def _bad_plan(symbol="AAAA"):
    return {
        "symbol": symbol,
        "rank": 1,
        "kind": "drifted",
        "price": 10.0,
        "limit": 12.0,
        "drift_pct": 16.7,
        "target": 14.0,
        "plan_age": "2026-10-01T00:00:00Z",
    }


def test_plan_drift_revalidator_receipt_states_what_it_replanned(state_root, monkeypatch):
    mod = _import("plan_drift_revalidator")
    monkeypatch.setattr(mod, "find_defective", lambda top, cap: [_bad_plan("AAAA"), _bad_plan("BBBB")])
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="replanned", stderr="")
    )
    monkeypatch.setattr(sys, "argv", ["plan_drift_revalidator.py", "--apply"])

    assert mod.main() == 0
    doc = _receipt(state_root, "plan-drift-revalidator")
    assert doc["status"] == "ok" and doc["produced_count"] == 2 and doc["attempted_count"] == 2


def test_plan_drift_revalidator_failed_batch_is_not_green(state_root, monkeypatch):
    mod = _import("plan_drift_revalidator")
    monkeypatch.setattr(mod, "find_defective", lambda top, cap: [_bad_plan("AAAA")])
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr="planner died")
    )
    monkeypatch.setattr(sys, "argv", ["plan_drift_revalidator.py", "--apply"])

    assert mod.main() == 1, "a failed planner batch must not exit 0"
    doc = _receipt(state_root, "plan-drift-revalidator")
    assert doc["status"] == "failed" and doc["ok_at"] is None
    assert doc["skipped_reasons"].get("batch_failed") == 1


def test_plan_drift_revalidator_with_nothing_to_do_says_so(state_root, monkeypatch):
    mod = _import("plan_drift_revalidator")
    monkeypatch.setattr(mod, "find_defective", lambda top, cap: [])
    monkeypatch.setattr(sys, "argv", ["plan_drift_revalidator.py", "--apply"])
    assert mod.main() == 0
    doc = _receipt(state_root, "plan-drift-revalidator")
    assert doc["status"] == "ok" and doc["produced_count"] == 0
    assert doc["empty_reason"] == "no_defective_plans"


def test_plan_drift_revalidator_dry_run_writes_nothing(state_root, monkeypatch):
    mod = _import("plan_drift_revalidator")
    monkeypatch.setattr(mod, "find_defective", lambda top, cap: [_bad_plan("AAAA")])
    monkeypatch.setattr(sys, "argv", ["plan_drift_revalidator.py", "--dry-run"])
    assert mod.main() == 0
    _assert_wrote_nothing(state_root)


# ── lane 4: run-scalp-shadow-logger ─────────────────────────────────────────────────────────────


def test_scalp_shadow_logger_receipt_counts_rows_written(state_root, monkeypatch):
    mod = _import("scalp_shadow_logger")

    def fake_run(args):
        mod.LAST_COUNTS.update(scored=5, rows_written=4, trigger_rows_written=1, reason=None)
        return 0

    monkeypatch.setattr(mod, "run", fake_run)
    assert mod.main(["--live", "--apply"]) == 0
    doc = _receipt(state_root, "run-scalp-shadow-logger")
    assert doc["status"] == "ok" and doc["produced_count"] == 5 and doc["attempted_count"] == 5


def test_scalp_shadow_logger_dry_run_writes_nothing(state_root, monkeypatch):
    mod = _import("scalp_shadow_logger")

    def fake_run(args):
        mod.LAST_COUNTS.update(scored=5, rows_written=0, trigger_rows_written=0, reason=None)
        return 0

    monkeypatch.setattr(mod, "run", fake_run)
    assert mod.main(["--live", "--apply", "--dry-run"]) == 0
    _assert_wrote_nothing(state_root)


def test_scalp_shadow_logger_failure_writes_a_failed_receipt(state_root, monkeypatch):
    mod = _import("scalp_shadow_logger")

    def boom(args):
        raise RuntimeError("bars unavailable")

    monkeypatch.setattr(mod, "run", boom)
    with pytest.raises(RuntimeError):
        mod.main(["--live", "--apply"])
    doc = _receipt(state_root, "run-scalp-shadow-logger")
    assert doc["status"] == "failed" and doc["ok_at"] is None


# ── lane 5: social-scalp-scanner ────────────────────────────────────────────────────────────────


def test_social_scalp_scanner_receipt_counts_saved_rows(state_root, monkeypatch):
    mod = _import("social_scalp_scanner")

    def fake_scan():
        mod.LAST_COUNTS.update(candidates=3, saved=2, go=1, reason=None)

    monkeypatch.setattr(mod, "run_scan", fake_scan)
    assert mod.main([]) == 0
    doc = _receipt(state_root, "social-scalp-scanner")
    assert doc["status"] == "ok" and doc["produced_count"] == 2 and doc["attempted_count"] == 3


def test_social_scalp_scanner_dry_run_cannot_reach_the_scan(state_root, monkeypatch):
    mod = _import("social_scalp_scanner")

    def must_not_run():
        raise AssertionError("a dry run reached the live scan (it sends Telegram)")

    monkeypatch.setattr(mod, "run_scan", must_not_run)
    assert mod.main(["--dry-run"]) == 0
    _assert_wrote_nothing(state_root)


def test_social_scalp_scanner_gate_not_fired_keeps_the_lane_alive(state_root, monkeypatch):
    mod = _import("social_scalp_scanner")
    trig = types.ModuleType("lib.scalp_list_trigger")
    trig.gate_main = lambda lane: {"decision": {"fire": False, "decision": "no_advance"}, "list_env": {}}
    trig.commit = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "lib.scalp_list_trigger", trig)
    import lib

    monkeypatch.setattr(lib, "scalp_list_trigger", trig, raising=False)
    monkeypatch.setattr(mod, "run_scan", lambda: pytest.fail("the gate said not to scan"))

    assert mod.main(["--on-list-advance"]) == 0
    doc = _receipt(state_root, "social-scalp-scanner")
    assert doc["status"] == "ok" and doc["produced_count"] == 0
    assert doc["empty_reason"] == "list_not_advanced"


def test_social_scalp_scanner_failure_writes_a_failed_receipt(state_root, monkeypatch):
    mod = _import("social_scalp_scanner")

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(mod, "run_scan", boom)
    with pytest.raises(RuntimeError):
        mod.main([])
    doc = _receipt(state_root, "social-scalp-scanner")
    assert doc["status"] == "failed" and doc["ok_at"] is None
