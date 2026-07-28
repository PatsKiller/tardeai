"""Deterministic just-in-time T2 admission for Active Trader.

This module is intentionally pure policy. It owns no market-data client, performs no
network I/O, and cannot submit, modify, or cancel an order. It decides which symbols
may consume scarce T2 capacity and publishes UI refresh hints.

T2 is an execution resource, not a scanner resource:

* broad discovery remains T0;
* near-fire candidates remain T1 until an ACTIVE, execution-eligible paper/shadow
  session can act on them;
* T2 is leased only for near-fire candidates or an already-open position;
* push delivery is primary; pull is a bounded hydration/recovery fallback;
* leases are released on invalidation, staleness, kill switch, expiry, or completion.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Optional

CONTRACT = "active-trader-t2-jit-policy-v1"

TIER_T0 = "T0"
TIER_T1 = "T1"
TIER_T2 = "T2"

MODE_SIMULATION = "SIMULATION"
MODE_SHADOW = "SHADOW"
MODE_PAPER = "PAPER"
ALLOWED_MODES = frozenset({MODE_SIMULATION, MODE_SHADOW, MODE_PAPER})

SETUP_ARMED = "ARMED"
SETUP_FIRED = "FIRED"
SESSION_ACTIVE = "ACTIVE"
GATE_PASS = "PASS"

R_ADMITTED = "admitted"
R_CONTINUED = "continued"
R_POSITION_PRIORITY = "open_position_priority"
R_SESSION_INACTIVE = "session_not_active"
R_MODE_INELIGIBLE = "mode_not_paper_or_shadow"
R_EXECUTION_INELIGIBLE = "account_not_execution_eligible"
R_SETUP_INELIGIBLE = "setup_not_armed_or_fired"
R_GATE_VETO = "gate_not_pass"
R_BASELINE_STALE = "baseline_quote_stale"
R_NOT_NEAR_FIRE = "not_near_fire"
R_KILL_SWITCH = "kill_switch_engaged"
R_CAPACITY = "t2_capacity_full"
R_COOLDOWN = "t2_cooldown"
R_EXPIRED = "lease_expired"
R_INVALIDATED = "candidate_invalidated"
R_EVICTED = "evicted_for_higher_priority"
R_NOT_OBSERVED = "candidate_not_observed"


@dataclass(frozen=True)
class T2PolicyConfig:
    """Configurable, conservative defaults for shadow/paper evaluation.

    ``provider_hard_cap`` is an absolute safety ceiling. ``max_concurrent_leases``
    is the normal operating cap and should remain materially lower.
    """

    provider_hard_cap: int = 8
    max_concurrent_leases: int = 2
    prefire_distance_bps: float = 12.0
    prefire_window_s: float = 30.0
    baseline_max_age_s: float = 15.0
    lease_ttl_s: float = 20.0
    min_dwell_s: float = 10.0
    cooldown_s: float = 15.0
    active_refresh_s: int = 5
    near_fire_refresh_s: int = 10
    idle_refresh_s: int = 30
    max_pull_fallbacks_per_minute: int = 2

    def __post_init__(self) -> None:
        if self.provider_hard_cap <= 0:
            raise ValueError("provider_hard_cap must be positive")
        if not 0 < self.max_concurrent_leases <= self.provider_hard_cap:
            raise ValueError("max_concurrent_leases must be within provider_hard_cap")
        for name in (
            "prefire_distance_bps",
            "prefire_window_s",
            "baseline_max_age_s",
            "lease_ttl_s",
            "min_dwell_s",
            "cooldown_s",
        ):
            if float(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")
        if min(self.active_refresh_s, self.near_fire_refresh_s, self.idle_refresh_s) <= 0:
            raise ValueError("refresh intervals must be positive")
        if self.max_pull_fallbacks_per_minute < 0:
            raise ValueError("max_pull_fallbacks_per_minute must be non-negative")


@dataclass(frozen=True)
class CandidateObservation:
    symbol: str
    observed_at: float
    session_state: str
    mode: str
    setup_state: str
    gate_decision: str
    execution_eligible: bool
    baseline_quote_age_s: float
    trigger_distance_bps: Optional[float] = None
    expected_fire_in_s: Optional[float] = None
    operator_selected: bool = False
    position_open: bool = False
    kill_switch: bool = False
    priority_score: float = 0.0

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CandidateObservation":
        return cls(
            symbol=str(raw.get("symbol") or "").strip().upper(),
            observed_at=float(raw.get("observed_at") or 0.0),
            session_state=str(raw.get("session_state") or "").strip().upper(),
            mode=str(raw.get("mode") or "").strip().upper(),
            setup_state=str(raw.get("setup_state") or "").strip().upper(),
            gate_decision=str(raw.get("gate_decision") or "").strip().upper(),
            execution_eligible=bool(raw.get("execution_eligible")),
            baseline_quote_age_s=float(raw.get("baseline_quote_age_s") or 0.0),
            trigger_distance_bps=_optional_float(raw.get("trigger_distance_bps")),
            expected_fire_in_s=_optional_float(raw.get("expected_fire_in_s")),
            operator_selected=bool(raw.get("operator_selected")),
            position_open=bool(raw.get("position_open")),
            kill_switch=bool(raw.get("kill_switch")),
            priority_score=float(raw.get("priority_score") or 0.0),
        )


@dataclass(frozen=True)
class T2Lease:
    lease_id: str
    symbol: str
    admitted_at: float
    renewed_at: float
    expires_at: float
    priority: float
    position_open: bool
    contract: str = CONTRACT

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateDecision:
    symbol: str
    tier: str
    admitted: bool
    reason_code: str
    refresh_after_s: int
    priority: float
    contract: str = CONTRACT

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class T2Event:
    kind: str
    symbol: str
    reason_code: str
    at: float
    lease_id: Optional[str] = None
    contract: str = CONTRACT

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class T2Snapshot:
    generated_at: float
    leases: tuple[T2Lease, ...]
    decisions: tuple[CandidateDecision, ...]
    events: tuple[T2Event, ...]
    ui_refresh_after_s: int
    provider_hard_cap: int
    operating_cap: int
    push_primary: bool
    max_pull_fallbacks_per_minute: int
    contract: str = CONTRACT

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "leases": [lease.to_dict() for lease in self.leases],
            "decisions": [decision.to_dict() for decision in self.decisions],
            "events": [event.to_dict() for event in self.events],
        }


def _optional_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _lease_id(symbol: str, admitted_at: float) -> str:
    raw = f"{symbol}|{admitted_at:.6f}|{CONTRACT}".encode("utf-8")
    return "t2_" + hashlib.sha256(raw).hexdigest()[:16]


def _near_fire(obs: CandidateObservation, cfg: T2PolicyConfig) -> bool:
    if obs.setup_state == SETUP_FIRED:
        return True
    by_distance = (
        obs.trigger_distance_bps is not None
        and 0.0 <= obs.trigger_distance_bps <= cfg.prefire_distance_bps
    )
    by_window = (
        obs.expected_fire_in_s is not None
        and 0.0 <= obs.expected_fire_in_s <= cfg.prefire_window_s
    )
    return by_distance or by_window


def _priority(obs: CandidateObservation, cfg: T2PolicyConfig) -> float:
    value = float(obs.priority_score)
    if obs.position_open:
        value += 100_000.0
    if obs.setup_state == SETUP_FIRED:
        value += 10_000.0
    if obs.operator_selected:
        value += 2_000.0
    if obs.trigger_distance_bps is not None:
        value += max(0.0, cfg.prefire_distance_bps - max(0.0, obs.trigger_distance_bps)) * 10.0
    if obs.expected_fire_in_s is not None:
        value += max(0.0, cfg.prefire_window_s - max(0.0, obs.expected_fire_in_s))
    return round(value, 6)


def _eligibility(obs: CandidateObservation, cfg: T2PolicyConfig) -> tuple[bool, str]:
    if not obs.symbol:
        return False, R_SETUP_INELIGIBLE
    if obs.kill_switch:
        return False, R_KILL_SWITCH
    if obs.session_state != SESSION_ACTIVE:
        return False, R_SESSION_INACTIVE
    if obs.mode not in ALLOWED_MODES:
        return False, R_MODE_INELIGIBLE
    if not obs.execution_eligible:
        return False, R_EXECUTION_INELIGIBLE
    if obs.baseline_quote_age_s < 0 or obs.baseline_quote_age_s > cfg.baseline_max_age_s:
        return False, R_BASELINE_STALE
    if obs.position_open:
        return True, R_POSITION_PRIORITY
    if obs.setup_state not in {SETUP_ARMED, SETUP_FIRED}:
        return False, R_SETUP_INELIGIBLE
    if obs.gate_decision != GATE_PASS:
        return False, R_GATE_VETO
    if not _near_fire(obs, cfg):
        return False, R_NOT_NEAR_FIRE
    return True, R_ADMITTED


class T2LeaseManager:
    """Stateful lease reconciler with deterministic admission and eviction.

    Existing open-position leases are never evicted by a pre-fire candidate. Normal
    leases cannot be evicted before ``min_dwell_s``. Every reconcile call is pure with
    respect to external systems: only this in-memory state changes.
    """

    def __init__(self, config: T2PolicyConfig | None = None) -> None:
        self.config = config or T2PolicyConfig()
        self._leases: dict[str, T2Lease] = {}
        self._cooldown_until: dict[str, float] = {}

    @property
    def leases(self) -> tuple[T2Lease, ...]:
        return tuple(sorted(self._leases.values(), key=lambda lease: lease.symbol))

    def _release(self, symbol: str, now: float, reason: str, events: list[T2Event]) -> None:
        lease = self._leases.pop(symbol, None)
        if lease is None:
            return
        self._cooldown_until[symbol] = now + self.config.cooldown_s
        events.append(T2Event("released", symbol, reason, now, lease.lease_id))

    def _admit(self, obs: CandidateObservation, now: float, priority: float, events: list[T2Event]) -> None:
        lease = T2Lease(
            lease_id=_lease_id(obs.symbol, now),
            symbol=obs.symbol,
            admitted_at=now,
            renewed_at=now,
            expires_at=now + self.config.lease_ttl_s,
            priority=priority,
            position_open=obs.position_open,
        )
        self._leases[obs.symbol] = lease
        events.append(T2Event("admitted", obs.symbol, R_ADMITTED, now, lease.lease_id))

    def reconcile(
        self,
        observations: Iterable[CandidateObservation | Mapping[str, Any]],
        *,
        now: float,
    ) -> T2Snapshot:
        cfg = self.config
        observed: dict[str, CandidateObservation] = {}
        for item in observations:
            obs = item if isinstance(item, CandidateObservation) else CandidateObservation.from_mapping(item)
            if obs.symbol:
                observed[obs.symbol] = obs

        events: list[T2Event] = []
        decisions_by_symbol: dict[str, CandidateDecision] = {}

        self._cooldown_until = {
            symbol: until for symbol, until in self._cooldown_until.items() if until > now
        }

        for symbol, lease in list(self._leases.items()):
            obs = observed.get(symbol)
            if obs is None:
                if now >= lease.expires_at:
                    self._release(symbol, now, R_NOT_OBSERVED, events)
                continue
            eligible, reason = _eligibility(obs, cfg)
            if not eligible:
                self._release(symbol, now, R_INVALIDATED if reason != R_KILL_SWITCH else reason, events)
                decisions_by_symbol[symbol] = CandidateDecision(
                    symbol, TIER_T0, False, reason, cfg.idle_refresh_s, _priority(obs, cfg)
                )
                continue
            renewed = T2Lease(
                lease_id=lease.lease_id,
                symbol=symbol,
                admitted_at=lease.admitted_at,
                renewed_at=now,
                expires_at=now + cfg.lease_ttl_s,
                priority=_priority(obs, cfg),
                position_open=obs.position_open,
            )
            self._leases[symbol] = renewed
            events.append(T2Event("renewed", symbol, R_CONTINUED, now, lease.lease_id))
            decisions_by_symbol[symbol] = CandidateDecision(
                symbol,
                TIER_T2,
                True,
                R_POSITION_PRIORITY if obs.position_open else R_CONTINUED,
                cfg.active_refresh_s,
                renewed.priority,
            )

        eligible_candidates: list[tuple[float, str, CandidateObservation]] = []
        for symbol, obs in observed.items():
            if symbol in self._leases:
                continue
            eligible, reason = _eligibility(obs, cfg)
            priority = _priority(obs, cfg)
            if not eligible:
                tier = TIER_T1 if reason == R_NOT_NEAR_FIRE else TIER_T0
                refresh = cfg.near_fire_refresh_s if tier == TIER_T1 else cfg.idle_refresh_s
                decisions_by_symbol[symbol] = CandidateDecision(
                    symbol, tier, False, reason, refresh, priority
                )
                continue
            if self._cooldown_until.get(symbol, 0.0) > now and not obs.position_open:
                decisions_by_symbol[symbol] = CandidateDecision(
                    symbol, TIER_T1, False, R_COOLDOWN, cfg.near_fire_refresh_s, priority
                )
                continue
            eligible_candidates.append((priority, symbol, obs))

        eligible_candidates.sort(key=lambda row: (-row[0], row[1]))
        operating_cap = min(cfg.max_concurrent_leases, cfg.provider_hard_cap)

        for priority, symbol, obs in eligible_candidates:
            if len(self._leases) < operating_cap:
                self._admit(obs, now, priority, events)
                decisions_by_symbol[symbol] = CandidateDecision(
                    symbol, TIER_T2, True, R_ADMITTED, cfg.active_refresh_s, priority
                )
                continue

            evictable = [
                lease
                for lease in self._leases.values()
                if not lease.position_open
                and (now - lease.admitted_at) >= cfg.min_dwell_s
                and priority > lease.priority
            ]
            evictable.sort(key=lambda lease: (lease.priority, lease.admitted_at, lease.symbol))
            if evictable:
                victim = evictable[0]
                self._release(victim.symbol, now, R_EVICTED, events)
                victim_obs = observed.get(victim.symbol)
                if victim_obs is not None:
                    decisions_by_symbol[victim.symbol] = CandidateDecision(
                        victim.symbol,
                        TIER_T1,
                        False,
                        R_EVICTED,
                        cfg.near_fire_refresh_s,
                        victim.priority,
                    )
                self._admit(obs, now, priority, events)
                decisions_by_symbol[symbol] = CandidateDecision(
                    symbol, TIER_T2, True, R_ADMITTED, cfg.active_refresh_s, priority
                )
            else:
                decisions_by_symbol[symbol] = CandidateDecision(
                    symbol, TIER_T1, False, R_CAPACITY, cfg.near_fire_refresh_s, priority
                )

        decisions = tuple(sorted(decisions_by_symbol.values(), key=lambda row: row.symbol))
        refresh = min((decision.refresh_after_s for decision in decisions), default=cfg.idle_refresh_s)
        return T2Snapshot(
            generated_at=float(now),
            leases=self.leases,
            decisions=decisions,
            events=tuple(events),
            ui_refresh_after_s=refresh,
            provider_hard_cap=cfg.provider_hard_cap,
            operating_cap=operating_cap,
            push_primary=True,
            max_pull_fallbacks_per_minute=cfg.max_pull_fallbacks_per_minute,
        )
