"""Keep the orchestrator reaper cap above its measured production runtime."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import process_reaper  # noqa: E402


def test_orchestrator_reaper_cap_allows_measured_16_00_run():
    policy = json.loads((ROOT / "config/process_reaper_policy.json").read_text())
    configured = next(r for r in policy["rules"] if r["name"] == "trade_ai_orchestrator")
    fallback = next(r for r in process_reaper.DEFAULT_RULES if r["name"] == "trade_ai_orchestrator")

    assert configured["max_runtime_min"] == 30
    assert fallback["max_runtime_min"] == configured["max_runtime_min"]
    # Runtime ledger config/pipelines/after_close.json: 5 verified safe_flock
    # samples for the 16:00 label, with p95_s=1260.8 (rounded to 1261s).
    # Production process_reaper.jsonl independently records 20–23m kills.
    worker = {"pid": 123, "etimes": 22 * 60, "args": "python scripts/trade_ai_orchestrator.py"}
    assert process_reaper._flag(configured, [worker]) == ([], [])


def test_orchestrator_reaper_still_flags_runs_over_the_new_cap():
    policy = json.loads((ROOT / "config/process_reaper_policy.json").read_text())
    configured = next(r for r in policy["rules"] if r["name"] == "trade_ai_orchestrator")
    worker = {"pid": 123, "etimes": 31 * 60, "args": "python scripts/trade_ai_orchestrator.py"}
    flagged, reasons = process_reaper._flag(configured, [worker])
    assert flagged == [worker]
    assert "over runtime cap 30m" in reasons[0]


def test_orchestrator_pile_up_keeps_oldest_under_cap_worker():
    policy = json.loads((ROOT / "config/process_reaper_policy.json").read_text())
    configured = next(r for r in policy["rules"] if r["name"] == "trade_ai_orchestrator")
    oldest = {"pid": 101, "etimes": 12 * 60, "args": "python scripts/trade_ai_orchestrator.py --run-label 1600"}
    newest = {"pid": 202, "etimes": 4 * 60, "args": "python scripts/trade_ai_orchestrator.py --run-label 1600"}
    flagged, reasons = process_reaper._flag(configured, [newest, oldest])
    assert flagged == [newest]
    assert "pile-up 2 > max_concurrent 1" in reasons[0]


def test_a_completed_sweep_writes_a_lane_receipt(tmp_path, monkeypatch, capsys):
    """The Jobs projection reads ok_at; a completed sweep is a run, even with no findings (2026-11-01)."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(process_reaper, "_ps_snapshot", lambda: [])
    monkeypatch.setattr(process_reaper, "_flag", lambda rule, procs: ([], []))
    monkeypatch.setattr(sys, "argv", ["process_reaper"])
    process_reaper.main()
    receipt = json.loads((tmp_path / "data/runtime/process-reaper_last.json").read_text())
    assert receipt["lane_id"] == "process-reaper"
    assert receipt["status"] == "ok" and receipt["ok_at"]
    assert receipt["summary"]["rules_tripped"] == 0
