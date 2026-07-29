"""Guarded long-running producer for Active Trader motion evidence.

The runtime preserves T2 lease and momentum-exit hysteresis state across cycles and
process restarts, writes only the motion journal plus runtime metadata, and owns no
account, venue, broker, credential, session, order, or execution authority.

Cadence is driven by the snapshot contract: 5 seconds while T2 or monitored-position
work exists, 10 seconds for near-fire T1 work, and 30 seconds while idle. Failures do
not fabricate a fresh snapshot; the existing GET path therefore becomes stale or
unavailable honestly while the runtime records bounded-backoff heartbeat evidence.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import signal
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Optional

from .momentum_exit_policy import MomentumExitPolicy
from .motion_journal import DEFAULT_MAX_LINES, resolve_path
from .motion_shadow import (
    gather_candidate_observations,
    gather_momentum_observations,
    run_shadow_cycle,
)
from .t2_jit_policy import T2Lease, T2LeaseManager

RUNTIME_STATE_CONTRACT = "active-trader-motion-runtime-state-v1"
RUNTIME_HEARTBEAT_CONTRACT = "active-trader-motion-runtime-heartbeat-v1"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_STATE = _REPO_ROOT / "data" / "active_trader" / "motion_runtime_state.json"
_DEFAULT_HEARTBEAT = _REPO_ROOT / "data" / "active_trader" / "motion_runtime_heartbeat.json"
_DEFAULT_LOCK = _REPO_ROOT / "data" / "active_trader" / "motion_runtime.lock"
_ZERO_AUTHORITY = {
    "mutation": False,
    "order": False,
    "session_authorize": False,
    "canary": False,
    "financial_action": False,
}


class AlreadyRunning(RuntimeError):
    """Raised when another producer process already owns the runtime lock."""


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser() if raw else default


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        return float(default)
    if not math.isfinite(value):
        return float(default)
    return max(float(minimum), value)


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return int(default)
    try:
        value = int(raw)
    except ValueError:
        return int(default)
    return max(int(minimum), value)


def _finite_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _optional_timestamp(value: Any) -> Optional[float]:
    return _finite_float(value)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"), sort_keys=True, allow_nan=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


@contextmanager
def single_instance_lock(path: Path):
    """Own an advisory non-blocking process lock for the runtime lifetime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AlreadyRunning(f"motion runtime lock already held: {path}") from exc
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        yield fh
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()


@dataclass(frozen=True)
class MotionRuntimeConfig:
    journal_path: Path
    state_path: Path
    heartbeat_path: Path
    lock_path: Path
    max_lines: int = DEFAULT_MAX_LINES
    active_cadence_s: float = 5.0
    near_fire_cadence_s: float = 10.0
    idle_cadence_s: float = 30.0
    backoff_initial_s: float = 5.0
    backoff_max_s: float = 30.0

    @classmethod
    def from_env(cls) -> "MotionRuntimeConfig":
        return cls(
            journal_path=resolve_path(),
            state_path=_env_path("ACTIVE_TRADER_MOTION_STATE", _DEFAULT_STATE),
            heartbeat_path=_env_path("ACTIVE_TRADER_MOTION_HEARTBEAT", _DEFAULT_HEARTBEAT),
            lock_path=_env_path("ACTIVE_TRADER_MOTION_LOCK", _DEFAULT_LOCK),
            max_lines=_env_int(
                "ACTIVE_TRADER_MOTION_MAX_JOURNAL_LINES", DEFAULT_MAX_LINES
            ),
            active_cadence_s=_env_float(
                "ACTIVE_TRADER_MOTION_ACTIVE_CADENCE_S", 5.0, minimum=1.0
            ),
            near_fire_cadence_s=_env_float(
                "ACTIVE_TRADER_MOTION_NEAR_FIRE_CADENCE_S", 10.0, minimum=1.0
            ),
            idle_cadence_s=_env_float(
                "ACTIVE_TRADER_MOTION_IDLE_CADENCE_S", 30.0, minimum=1.0
            ),
            backoff_initial_s=_env_float(
                "ACTIVE_TRADER_MOTION_BACKOFF_INITIAL_S", 5.0, minimum=1.0
            ),
            backoff_max_s=_env_float(
                "ACTIVE_TRADER_MOTION_BACKOFF_MAX_S", 30.0, minimum=1.0
            ),
        )

    def __post_init__(self) -> None:
        if not (0 < self.active_cadence_s <= self.near_fire_cadence_s <= self.idle_cadence_s):
            raise ValueError("cadences must satisfy 0 < active <= near-fire <= idle")
        if not (0 < self.backoff_initial_s <= self.backoff_max_s):
            raise ValueError("backoff must satisfy 0 < initial <= max")
        if self.max_lines <= 0:
            raise ValueError("max_lines must be positive")


def cadence_for_snapshot(snapshot: Mapping[str, Any], config: MotionRuntimeConfig) -> float:
    """Map the contract hint to the bounded 5/10/30-style runtime cadence."""
    hint = _finite_float(snapshot.get("ui_refresh_after_s"))
    if hint is None:
        return config.idle_cadence_s
    if hint <= config.active_cadence_s:
        return config.active_cadence_s
    if hint <= config.near_fire_cadence_s:
        return config.near_fire_cadence_s
    return config.idle_cadence_s


def failure_backoff(consecutive_failures: int, config: MotionRuntimeConfig) -> float:
    exponent = max(0, int(consecutive_failures) - 1)
    return min(config.backoff_max_s, config.backoff_initial_s * (2**exponent))


def _lease_manager_state(manager: T2LeaseManager) -> dict[str, Any]:
    cooldowns = getattr(manager, "_cooldown_until", {})
    return {
        "leases": [lease.to_dict() for lease in manager.leases],
        "cooldown_until": {
            str(symbol): float(until)
            for symbol, until in dict(cooldowns).items()
            if _finite_float(until) is not None
        },
    }


def _restore_lease_manager_state(
    manager: T2LeaseManager, raw: Any, *, now: float
) -> None:
    if not isinstance(raw, Mapping):
        return
    restored: dict[str, T2Lease] = {}
    for item in raw.get("leases") or []:
        if not isinstance(item, Mapping):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        lease_id = str(item.get("lease_id") or "").strip()
        admitted_at = _finite_float(item.get("admitted_at"))
        renewed_at = _finite_float(item.get("renewed_at"))
        expires_at = _finite_float(item.get("expires_at"))
        priority = _finite_float(item.get("priority"))
        if (
            not symbol
            or not lease_id
            or admitted_at is None
            or renewed_at is None
            or expires_at is None
            or priority is None
            or expires_at <= now
        ):
            continue
        restored[symbol] = T2Lease(
            lease_id=lease_id,
            symbol=symbol,
            admitted_at=admitted_at,
            renewed_at=renewed_at,
            expires_at=expires_at,
            priority=priority,
            position_open=bool(item.get("position_open")),
        )
    cooldowns: dict[str, float] = {}
    raw_cooldowns = raw.get("cooldown_until")
    if isinstance(raw_cooldowns, Mapping):
        for symbol, until_raw in raw_cooldowns.items():
            until = _finite_float(until_raw)
            normalized = str(symbol or "").strip().upper()
            if normalized and until is not None and until > now:
                cooldowns[normalized] = until
    manager._leases = restored  # type: ignore[attr-defined]
    manager._cooldown_until = cooldowns  # type: ignore[attr-defined]


_POLICY_STATE_FIELDS = (
    "_deterioration_started_at",
    "_fire_started_at",
    "_recovery_started_at",
    "_high_watermark",
    "_armed",
    "_signaled",
    "_signal_reason",
)


def _exit_policy_state(policy: MomentumExitPolicy) -> dict[str, Any]:
    return {name.removeprefix("_"): getattr(policy, name) for name in _POLICY_STATE_FIELDS}


def _restore_exit_policy(raw: Any) -> MomentumExitPolicy:
    policy = MomentumExitPolicy()
    if not isinstance(raw, Mapping):
        return policy
    for attr in (
        "_deterioration_started_at",
        "_fire_started_at",
        "_recovery_started_at",
        "_high_watermark",
    ):
        setattr(policy, attr, _optional_timestamp(raw.get(attr.removeprefix("_"))))
    policy._armed = bool(raw.get("armed"))  # type: ignore[attr-defined]
    policy._signaled = bool(raw.get("signaled"))  # type: ignore[attr-defined]
    reason = raw.get("signal_reason")
    policy._signal_reason = str(reason) if isinstance(reason, str) and reason else None  # type: ignore[attr-defined]
    return policy


def _observation_symbol(item: Any) -> str:
    if isinstance(item, Mapping):
        value = item.get("symbol")
    else:
        value = getattr(item, "symbol", None)
    return str(value or "").strip().upper()


class MotionRuntime:
    def __init__(
        self,
        config: MotionRuntimeConfig,
        *,
        lease_manager: Optional[T2LeaseManager] = None,
        exit_policies: Optional[MutableMapping[str, MomentumExitPolicy]] = None,
        candidate_loader: Callable[[float], Iterable[Any]] = gather_candidate_observations,
        momentum_loader: Callable[[float], Iterable[Any]] = gather_momentum_observations,
        cycle_runner: Callable[..., Mapping[str, Any]] = run_shadow_cycle,
        now_fn: Callable[[], float] = time.time,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.lease_manager = lease_manager or T2LeaseManager()
        self.exit_policies = exit_policies if exit_policies is not None else {}
        self.candidate_loader = candidate_loader
        self.momentum_loader = momentum_loader
        self.cycle_runner = cycle_runner
        self.now_fn = now_fn
        self.monotonic_fn = monotonic_fn
        self.stop_event = threading.Event()
        self.process_started_at = float(self.now_fn())
        self.last_success_at: Optional[float] = None
        self.last_cycle_started_at: Optional[float] = None
        self.consecutive_failures = 0
        self.cycle_count = 0
        self.loaded_state_at: Optional[float] = None
        self.restored_state = False
        self.restored_t2_lease_count = 0
        self.restored_exit_policy_count = 0
        self._load_state()

    def request_stop(self) -> None:
        self.stop_event.set()

    def _load_state(self) -> None:
        try:
            raw = json.loads(self.config.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(raw, Mapping) or raw.get("contract") != RUNTIME_STATE_CONTRACT:
            return
        now = float(self.now_fn())
        _restore_lease_manager_state(self.lease_manager, raw.get("t2"), now=now)
        policies = raw.get("exit_policies")
        if isinstance(policies, Mapping):
            for symbol, policy_state in policies.items():
                normalized = str(symbol or "").strip().upper()
                if normalized:
                    self.exit_policies[normalized] = _restore_exit_policy(policy_state)
        self.last_success_at = _optional_timestamp(raw.get("last_success_at"))
        self.cycle_count = max(0, int(raw.get("cycle_count") or 0))
        self.loaded_state_at = now
        self.restored_state = True
        self.restored_t2_lease_count = len(self.lease_manager.leases)
        self.restored_exit_policy_count = len(self.exit_policies)

    def _persist_state(self, now: float) -> None:
        payload = {
            "contract": RUNTIME_STATE_CONTRACT,
            "saved_at": float(now),
            "last_success_at": self.last_success_at,
            "cycle_count": self.cycle_count,
            "t2": _lease_manager_state(self.lease_manager),
            "exit_policies": {
                symbol: _exit_policy_state(policy)
                for symbol, policy in sorted(self.exit_policies.items())
            },
            "read_only_market_state": True,
            "authority": dict(_ZERO_AUTHORITY),
        }
        _atomic_write_json(self.config.state_path, payload)

    def _write_heartbeat(
        self,
        *,
        now: float,
        status: str,
        next_cycle_in_s: float,
        snapshot: Optional[Mapping[str, Any]] = None,
        error: Optional[BaseException] = None,
    ) -> None:
        t2 = snapshot.get("t2") if isinstance(snapshot, Mapping) else None
        t2_leases = t2.get("leases") if isinstance(t2, Mapping) else []
        positions = snapshot.get("positions") if isinstance(snapshot, Mapping) else []
        exit_signals = snapshot.get("exit_signals") if isinstance(snapshot, Mapping) else []
        payload = {
            "contract": RUNTIME_HEARTBEAT_CONTRACT,
            "status": status,
            "pid": os.getpid(),
            "updated_at": float(now),
            "process_started_at": self.process_started_at,
            "last_cycle_started_at": self.last_cycle_started_at,
            "last_success_at": self.last_success_at,
            "loaded_state_at": self.loaded_state_at,
            "restored_state": self.restored_state,
            "restored_t2_lease_count": self.restored_t2_lease_count,
            "restored_exit_policy_count": self.restored_exit_policy_count,
            "cycle_count": self.cycle_count,
            "consecutive_failures": self.consecutive_failures,
            "next_cycle_in_s": float(next_cycle_in_s),
            "journal_path": str(self.config.journal_path),
            "state_path": str(self.config.state_path),
            "snapshot_contract": snapshot.get("contract") if isinstance(snapshot, Mapping) else None,
            "snapshot_generated_at": snapshot.get("generated_at") if isinstance(snapshot, Mapping) else None,
            "t2_lease_count": len(t2_leases) if isinstance(t2_leases, list) else 0,
            "position_count": len(positions) if isinstance(positions, list) else 0,
            "exit_signal_count": len(exit_signals) if isinstance(exit_signals, list) else 0,
            "error_type": type(error).__name__ if error is not None else None,
            "error": str(error)[:500] if error is not None else None,
            "write_scope": "motion_journal_and_runtime_metadata_only",
            "authority": dict(_ZERO_AUTHORITY),
        }
        _atomic_write_json(self.config.heartbeat_path, payload)

    def run_once(self) -> tuple[Mapping[str, Any], float]:
        now = float(self.now_fn())
        self.last_cycle_started_at = now
        candidates = list(self.candidate_loader(now))
        positions = list(self.momentum_loader(now))
        snapshot = self.cycle_runner(
            now=now,
            path=self.config.journal_path,
            lease_manager=self.lease_manager,
            exit_policies=self.exit_policies,
            max_lines=self.config.max_lines,
            candidate_observations=candidates,
            momentum_observations=positions,
        )
        if not isinstance(snapshot, Mapping):
            raise TypeError("motion cycle did not return a mapping")

        active_position_symbols = {
            symbol for symbol in (_observation_symbol(item) for item in positions) if symbol
        }
        for symbol in list(self.exit_policies):
            if symbol not in active_position_symbols:
                del self.exit_policies[symbol]

        self.cycle_count += 1
        self.consecutive_failures = 0
        self.last_success_at = now
        delay = cadence_for_snapshot(snapshot, self.config)
        self._persist_state(now)
        self._write_heartbeat(
            now=now,
            status="healthy",
            next_cycle_in_s=delay,
            snapshot=snapshot,
        )
        return snapshot, delay

    def run_forever(self, *, max_cycles: Optional[int] = None) -> int:
        completed = 0
        with single_instance_lock(self.config.lock_path):
            while not self.stop_event.is_set():
                started = float(self.monotonic_fn())
                try:
                    _, delay = self.run_once()
                except Exception as exc:  # fail closed: do not append a fabricated snapshot
                    self.consecutive_failures += 1
                    delay = failure_backoff(self.consecutive_failures, self.config)
                    now = float(self.now_fn())
                    self._write_heartbeat(
                        now=now,
                        status="error",
                        next_cycle_in_s=delay,
                        error=exc,
                    )
                    print(
                        json.dumps(
                            {
                                "status": "error",
                                "error_type": type(exc).__name__,
                                "error": str(exc)[:500],
                                "consecutive_failures": self.consecutive_failures,
                                "next_cycle_in_s": delay,
                            },
                            sort_keys=True,
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
                completed += 1
                if max_cycles is not None and completed >= max_cycles:
                    return 0
                elapsed = max(0.0, float(self.monotonic_fn()) - started)
                self.stop_event.wait(max(0.0, delay - elapsed))
        return 0


def _install_signal_handlers(runtime: MotionRuntime) -> None:
    def _stop(_signum: int, _frame: Any) -> None:
        runtime.request_stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)


def main() -> int:
    runtime = MotionRuntime(MotionRuntimeConfig.from_env())
    _install_signal_handlers(runtime)
    try:
        return runtime.run_forever()
    except AlreadyRunning as exc:
        print(json.dumps({"status": "already_running", "detail": str(exc)}), flush=True)
        return 0


if __name__ == "__main__":  # pragma: no cover - service entrypoint
    raise SystemExit(main())
