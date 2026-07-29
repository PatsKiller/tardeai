from __future__ import annotations

import json
from pathlib import Path

import pytest

from active_trader.momentum_exit_policy import MomentumExitPolicy
from active_trader.motion_runtime import (
    AlreadyRunning,
    MotionRuntime,
    MotionRuntimeConfig,
    cadence_for_snapshot,
    failure_backoff,
    single_instance_lock,
)
from active_trader.t2_jit_policy import T2Lease, T2LeaseManager


def _config(tmp_path: Path) -> MotionRuntimeConfig:
    return MotionRuntimeConfig(
        journal_path=tmp_path / "motion.jsonl",
        state_path=tmp_path / "state.json",
        heartbeat_path=tmp_path / "heartbeat.json",
        lock_path=tmp_path / "runtime.lock",
        max_lines=50,
    )


def test_cadence_is_bounded_to_active_near_fire_and_idle(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    assert cadence_for_snapshot({"ui_refresh_after_s": 5}, cfg) == 5
    assert cadence_for_snapshot({"ui_refresh_after_s": 7}, cfg) == 10
    assert cadence_for_snapshot({"ui_refresh_after_s": 10}, cfg) == 10
    assert cadence_for_snapshot({"ui_refresh_after_s": 30}, cfg) == 30
    assert cadence_for_snapshot({}, cfg) == 30


def test_failure_backoff_is_exponential_and_bounded(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    assert [failure_backoff(i, cfg) for i in range(1, 7)] == [5, 10, 20, 30, 30, 30]


def test_single_instance_lock_rejects_overlap(tmp_path: Path) -> None:
    lock = tmp_path / "producer.lock"
    with single_instance_lock(lock):
        with pytest.raises(AlreadyRunning):
            with single_instance_lock(lock):
                pass
    with single_instance_lock(lock):
        assert lock.read_text(encoding="utf-8").strip().isdigit()


def test_state_round_trip_restores_unexpired_t2_and_exit_hysteresis(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    now = 100.0
    manager = T2LeaseManager()
    manager._leases = {
        "ABC": T2Lease(
            lease_id="t2_abc",
            symbol="ABC",
            admitted_at=80.0,
            renewed_at=95.0,
            expires_at=120.0,
            priority=42.0,
            position_open=True,
        )
    }
    manager._cooldown_until = {"XYZ": 115.0}
    policy = MomentumExitPolicy()
    policy._deterioration_started_at = 90.0
    policy._fire_started_at = 95.0
    policy._high_watermark = 12.5
    policy._armed = True

    runtime = MotionRuntime(
        cfg,
        lease_manager=manager,
        exit_policies={"ABC": policy},
        now_fn=lambda: now,
    )
    runtime.last_success_at = 99.0
    runtime.cycle_count = 7
    runtime._persist_state(now)

    restored = MotionRuntime(cfg, now_fn=lambda: 101.0)
    assert [lease.symbol for lease in restored.lease_manager.leases] == ["ABC"]
    assert restored.lease_manager._cooldown_until == {"XYZ": 115.0}
    assert restored.exit_policies["ABC"]._deterioration_started_at == 90.0
    assert restored.exit_policies["ABC"]._fire_started_at == 95.0
    assert restored.exit_policies["ABC"]._high_watermark == 12.5
    assert restored.exit_policies["ABC"]._armed is True
    assert restored.last_success_at == 99.0
    assert restored.cycle_count == 7


def test_expired_t2_state_is_not_restored(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.state_path.write_text(
        json.dumps(
            {
                "contract": "active-trader-motion-runtime-state-v1",
                "t2": {
                    "leases": [
                        {
                            "lease_id": "expired",
                            "symbol": "ABC",
                            "admitted_at": 1,
                            "renewed_at": 2,
                            "expires_at": 3,
                            "priority": 1,
                            "position_open": False,
                        }
                    ],
                    "cooldown_until": {"ABC": 3},
                },
                "exit_policies": {},
            }
        ),
        encoding="utf-8",
    )
    restored = MotionRuntime(cfg, now_fn=lambda: 10.0)
    assert restored.lease_manager.leases == ()
    assert restored.lease_manager._cooldown_until == {}


def test_run_once_reuses_state_writes_heartbeat_and_prunes_closed_positions(
    tmp_path: Path,
) -> None:
    cfg = _config(tmp_path)
    manager = T2LeaseManager()
    keep = MomentumExitPolicy()
    discard = MomentumExitPolicy()
    seen: dict[str, object] = {}

    def cycle_runner(**kwargs):
        seen.update(kwargs)
        cfg.journal_path.write_text('{"generated_at":200}\n', encoding="utf-8")
        return {
            "contract": "active-trader-motion-snapshot-v1",
            "generated_at": 200.0,
            "ui_refresh_after_s": 5,
            "t2": {"leases": [], "decisions": []},
            "positions": [{"symbol": "ABC"}],
            "exit_signals": [],
        }

    runtime = MotionRuntime(
        cfg,
        lease_manager=manager,
        exit_policies={"ABC": keep, "OLD": discard},
        candidate_loader=lambda _now: [{"symbol": "CAND"}],
        momentum_loader=lambda _now: [{"symbol": "ABC"}],
        cycle_runner=cycle_runner,
        now_fn=lambda: 200.0,
    )
    snapshot, delay = runtime.run_once()

    assert delay == 5
    assert snapshot["contract"] == "active-trader-motion-snapshot-v1"
    assert seen["lease_manager"] is manager
    assert seen["exit_policies"] is runtime.exit_policies
    assert seen["candidate_observations"] == [{"symbol": "CAND"}]
    assert seen["momentum_observations"] == [{"symbol": "ABC"}]
    assert set(runtime.exit_policies) == {"ABC"}

    state = json.loads(cfg.state_path.read_text(encoding="utf-8"))
    heartbeat = json.loads(cfg.heartbeat_path.read_text(encoding="utf-8"))
    assert state["cycle_count"] == 1
    assert state["authority"]["order"] is False
    assert heartbeat["status"] == "healthy"
    assert heartbeat["next_cycle_in_s"] == 5
    assert heartbeat["last_success_at"] == 200.0
    assert heartbeat["write_scope"] == "motion_journal_and_runtime_metadata_only"
    assert heartbeat["authority"]["financial_action"] is False


def test_failure_writes_error_heartbeat_without_fabricating_journal(tmp_path: Path) -> None:
    cfg = _config(tmp_path)

    def broken_cycle(**_kwargs):
        raise RuntimeError("source unavailable")

    runtime = MotionRuntime(
        cfg,
        candidate_loader=lambda _now: [],
        momentum_loader=lambda _now: [],
        cycle_runner=broken_cycle,
        now_fn=lambda: 300.0,
        monotonic_fn=lambda: 0.0,
    )
    assert runtime.run_forever(max_cycles=1) == 0
    assert not cfg.journal_path.exists()
    heartbeat = json.loads(cfg.heartbeat_path.read_text(encoding="utf-8"))
    assert heartbeat["status"] == "error"
    assert heartbeat["consecutive_failures"] == 1
    assert heartbeat["next_cycle_in_s"] == 5
    assert heartbeat["error_type"] == "RuntimeError"
    assert heartbeat["last_success_at"] is None


def test_corrupt_state_fails_closed_to_fresh_runtime(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.state_path.write_text("{not-json", encoding="utf-8")
    runtime = MotionRuntime(cfg, now_fn=lambda: 1.0)
    assert runtime.lease_manager.leases == ()
    assert runtime.exit_policies == {}
    assert runtime.last_success_at is None
