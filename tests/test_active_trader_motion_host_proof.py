from __future__ import annotations

import json
from pathlib import Path

from active_trader.motion_host_proof import run_proof


def _write_json(path: Path, body: dict) -> None:
    path.write_text(json.dumps(body) + "\n", encoding="utf-8")


def test_host_proof_confirms_fresh_read_only_get_and_no_journal_write(tmp_path: Path) -> None:
    journal = tmp_path / "motion.jsonl"
    heartbeat = tmp_path / "heartbeat.json"
    state = tmp_path / "state.json"
    snapshot = {
        "contract": "active-trader-motion-snapshot-v1",
        "generated_at": 100.0,
        "ui_refresh_after_s": 5,
        "t2": {"operating_cap": 2, "provider_hard_cap": 8, "leases": [], "decisions": []},
        "positions": [],
        "exit_signals": [],
        "read_only": True,
        "write": False,
        "authority": {
            "mutation": False,
            "order": False,
            "session_authorize": False,
            "canary": False,
            "financial_action": False,
        },
    }
    _write_json(journal, snapshot)
    _write_json(
        heartbeat,
        {
            "contract": "active-trader-motion-runtime-heartbeat-v1",
            "status": "healthy",
            "pid": 222,
            "process_started_at": 95.0,
            "last_success_at": 100.0,
            "restored_state": True,
            "write_scope": "motion_journal_and_runtime_metadata_only",
            "authority": {
                "mutation": False,
                "order": False,
                "session_authorize": False,
                "canary": False,
                "financial_action": False,
            },
        },
    )
    _write_json(state, {"contract": "active-trader-motion-runtime-state-v1"})
    before = journal.read_bytes()

    result = run_proof(
        journal_path=journal,
        heartbeat_path=heartbeat,
        state_path=state,
        endpoint=None,
        max_age_s=60.0,
        timeout_s=1.0,
        require_restored_state=True,
        previous_pid=111,
        now=101.0,
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert journal.read_bytes() == before


def test_host_proof_fails_when_snapshot_and_heartbeat_are_stale(tmp_path: Path) -> None:
    journal = tmp_path / "motion.jsonl"
    heartbeat = tmp_path / "heartbeat.json"
    state = tmp_path / "state.json"
    _write_json(
        journal,
        {
            "contract": "active-trader-motion-snapshot-v1",
            "generated_at": 1.0,
            "ui_refresh_after_s": 30,
            "t2": {"leases": [], "decisions": []},
            "positions": [],
            "exit_signals": [],
        },
    )
    _write_json(
        heartbeat,
        {
            "contract": "active-trader-motion-runtime-heartbeat-v1",
            "status": "healthy",
            "last_success_at": 1.0,
            "write_scope": "motion_journal_and_runtime_metadata_only",
            "authority": {
                "mutation": False,
                "order": False,
                "session_authorize": False,
                "canary": False,
                "financial_action": False,
            },
        },
    )
    _write_json(state, {"contract": "active-trader-motion-runtime-state-v1"})

    result = run_proof(
        journal_path=journal,
        heartbeat_path=heartbeat,
        state_path=state,
        endpoint=None,
        max_age_s=60.0,
        timeout_s=1.0,
        require_restored_state=False,
        previous_pid=None,
        now=1000.0,
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["heartbeat_fresh"] is False
    assert result["checks"]["direct_fresh"] is False
