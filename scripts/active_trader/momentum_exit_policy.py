"""Deterministic momentum-exit hysteresis for Active Trader shadow/paper use.

The policy emits a typed signal only. It does not contain a market-data client, broker
client, or order action. A downstream, separately-authorized paper execution component
may consume an EXIT_SIGNAL after its own risk, freshness, capability, and idempotency
checks.

The design deliberately separates:

* immediate hard-stop protection;
* temporary deterioration that should be watched;
* persistent multi-factor momentum failure that may justify an exit;
* stale-data faults, which fall back to already-installed protection rather than
  inventing a momentum exit from missing evidence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional

CONTRACT = "active-trader-momentum-exit-policy-v1"

STATE_HOLD = "HOLD"
STATE_WATCH = "WATCH"
STATE_ARMED = "EXIT_ARMED"
STATE_SIGNAL = "EXIT_SIGNAL"
STATE_PROTECT_ONLY = "PROTECT_ONLY"

ACTION_HOLD = "HOLD"
ACTION_ARM = "ARM_EXIT"
ACTION_SIGNAL = "EMIT_EXIT_SIGNAL"
ACTION_PROTECT_ONLY = "PROTECTIVE_STOP_ONLY"

R_HEALTHY = "momentum_healthy"
R_MIN_HOLD = "minimum_hold_not_met"
R_DETERIORATING = "momentum_deteriorating"
R_ARMED = "persistent_deterioration_armed"
R_PERSISTENT_FAILURE = "persistent_momentum_failure"
R_HARD_STOP = "hard_stop_breached"
R_DATA_STALE = "market_data_stale"
R_RECOVERING = "momentum_recovering"
R_RESET = "hysteresis_reset"
R_PRICE_CONFIRMATION_MISSING = "price_confirmation_missing"


@dataclass(frozen=True)
class MomentumExitConfig:
    arm_threshold: float = 0.58
    fire_threshold: float = 0.72
    reset_threshold: float = 0.38
    arm_persistence_s: float = 10.0
    fire_persistence_s: float = 10.0
    reset_persistence_s: float = 15.0
    minimum_hold_s: float = 20.0
    min_confirmation_dimensions: int = 2
    min_retracement_r: float = 0.35
    max_quote_age_s: float = 5.0
    max_book_age_s: float = 5.0
    max_tape_age_s: float = 10.0
    refresh_after_s: int = 5
    weight_momentum_failure: float = 0.35
    weight_tape_reversal: float = 0.25
    weight_book_weakness: float = 0.20
    weight_structure_failure: float = 0.20

    def __post_init__(self) -> None:
        if not 0 <= self.reset_threshold < self.arm_threshold < self.fire_threshold <= 1:
            raise ValueError("thresholds must satisfy reset < arm < fire within [0, 1]")
        for name in (
            "arm_persistence_s",
            "fire_persistence_s",
            "reset_persistence_s",
            "minimum_hold_s",
            "min_retracement_r",
            "max_quote_age_s",
            "max_book_age_s",
            "max_tape_age_s",
        ):
            if float(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.min_confirmation_dimensions < 1 or self.min_confirmation_dimensions > 4:
            raise ValueError("min_confirmation_dimensions must be between 1 and 4")
        if self.refresh_after_s <= 0:
            raise ValueError("refresh_after_s must be positive")
        weights = (
            self.weight_momentum_failure,
            self.weight_tape_reversal,
            self.weight_book_weakness,
            self.weight_structure_failure,
        )
        if any(weight < 0 for weight in weights) or sum(weights) <= 0:
            raise ValueError("weights must be non-negative with positive total")


@dataclass(frozen=True)
class MomentumObservation:
    symbol: str
    observed_at: float
    entered_at: float
    price: float
    entry_price: float
    hard_stop_price: float
    initial_risk_per_share: float
    momentum_failure: float
    tape_reversal: float
    book_weakness: float
    structure_failure: float
    quote_age_s: float
    book_age_s: float
    tape_age_s: float
    high_watermark: Optional[float] = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "MomentumObservation":
        return cls(
            symbol=str(raw.get("symbol") or "").strip().upper(),
            observed_at=float(raw.get("observed_at") or 0.0),
            entered_at=float(raw.get("entered_at") or 0.0),
            price=float(raw.get("price") or 0.0),
            entry_price=float(raw.get("entry_price") or 0.0),
            hard_stop_price=float(raw.get("hard_stop_price") or 0.0),
            initial_risk_per_share=float(raw.get("initial_risk_per_share") or 0.0),
            momentum_failure=float(raw.get("momentum_failure") or 0.0),
            tape_reversal=float(raw.get("tape_reversal") or 0.0),
            book_weakness=float(raw.get("book_weakness") or 0.0),
            structure_failure=float(raw.get("structure_failure") or 0.0),
            quote_age_s=float(raw.get("quote_age_s") or 0.0),
            book_age_s=float(raw.get("book_age_s") or 0.0),
            tape_age_s=float(raw.get("tape_age_s") or 0.0),
            high_watermark=_optional_float(raw.get("high_watermark")),
        )


@dataclass(frozen=True)
class ExitDecision:
    symbol: str
    state: str
    action: str
    reason_code: str
    score: float
    confirmations: int
    drawdown_from_high_r: float
    armed_for_s: float
    fire_for_s: float
    recovery_for_s: float
    refresh_after_s: int
    contract: str = CONTRACT

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _optional_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


class MomentumExitPolicy:
    """Stateful hysteresis evaluator for one open position."""

    def __init__(self, config: MomentumExitConfig | None = None) -> None:
        self.config = config or MomentumExitConfig()
        self._deterioration_started_at: Optional[float] = None
        self._fire_started_at: Optional[float] = None
        self._recovery_started_at: Optional[float] = None
        self._high_watermark: Optional[float] = None
        self._signaled = False

    def reset(self) -> None:
        self._deterioration_started_at = None
        self._fire_started_at = None
        self._recovery_started_at = None
        self._high_watermark = None
        self._signaled = False

    def _score(self, obs: MomentumObservation) -> float:
        cfg = self.config
        weighted = (
            _clamp01(obs.momentum_failure) * cfg.weight_momentum_failure
            + _clamp01(obs.tape_reversal) * cfg.weight_tape_reversal
            + _clamp01(obs.book_weakness) * cfg.weight_book_weakness
            + _clamp01(obs.structure_failure) * cfg.weight_structure_failure
        )
        total = (
            cfg.weight_momentum_failure
            + cfg.weight_tape_reversal
            + cfg.weight_book_weakness
            + cfg.weight_structure_failure
        )
        return round(weighted / total, 6)

    @staticmethod
    def _confirmations(obs: MomentumObservation, threshold: float = 0.60) -> int:
        return sum(
            value >= threshold
            for value in (
                _clamp01(obs.momentum_failure),
                _clamp01(obs.tape_reversal),
                _clamp01(obs.book_weakness),
                _clamp01(obs.structure_failure),
            )
        )

    def _decision(
        self,
        obs: MomentumObservation,
        *,
        state: str,
        action: str,
        reason: str,
        score: float,
        confirmations: int,
        drawdown_r: float,
        now: float,
    ) -> ExitDecision:
        return ExitDecision(
            symbol=obs.symbol,
            state=state,
            action=action,
            reason_code=reason,
            score=score,
            confirmations=confirmations,
            drawdown_from_high_r=round(drawdown_r, 6),
            armed_for_s=max(0.0, now - self._deterioration_started_at)
            if self._deterioration_started_at is not None
            else 0.0,
            fire_for_s=max(0.0, now - self._fire_started_at)
            if self._fire_started_at is not None
            else 0.0,
            recovery_for_s=max(0.0, now - self._recovery_started_at)
            if self._recovery_started_at is not None
            else 0.0,
            refresh_after_s=self.config.refresh_after_s,
        )

    def evaluate(
        self,
        observation: MomentumObservation | Mapping[str, Any],
    ) -> ExitDecision:
        obs = (
            observation
            if isinstance(observation, MomentumObservation)
            else MomentumObservation.from_mapping(observation)
        )
        cfg = self.config
        now = float(obs.observed_at)
        score = self._score(obs)
        confirmations = self._confirmations(obs)

        supplied_high = obs.high_watermark if obs.high_watermark is not None else obs.price
        self._high_watermark = max(
            value for value in (self._high_watermark, supplied_high, obs.price) if value is not None
        )
        risk = max(float(obs.initial_risk_per_share), 1e-9)
        drawdown_r = max(0.0, (float(self._high_watermark) - obs.price) / risk)

        if obs.hard_stop_price > 0 and obs.price > 0 and obs.price <= obs.hard_stop_price:
            self._signaled = True
            return self._decision(
                obs,
                state=STATE_SIGNAL,
                action=ACTION_SIGNAL,
                reason=R_HARD_STOP,
                score=score,
                confirmations=confirmations,
                drawdown_r=drawdown_r,
                now=now,
            )

        stale = (
            obs.quote_age_s < 0
            or obs.book_age_s < 0
            or obs.tape_age_s < 0
            or obs.quote_age_s > cfg.max_quote_age_s
            or obs.book_age_s > cfg.max_book_age_s
            or obs.tape_age_s > cfg.max_tape_age_s
        )
        if stale:
            self._fire_started_at = None
            return self._decision(
                obs,
                state=STATE_PROTECT_ONLY,
                action=ACTION_PROTECT_ONLY,
                reason=R_DATA_STALE,
                score=score,
                confirmations=confirmations,
                drawdown_r=drawdown_r,
                now=now,
            )

        if self._signaled:
            return self._decision(
                obs,
                state=STATE_SIGNAL,
                action=ACTION_SIGNAL,
                reason=R_PERSISTENT_FAILURE,
                score=score,
                confirmations=confirmations,
                drawdown_r=drawdown_r,
                now=now,
            )

        held_for = max(0.0, now - float(obs.entered_at))
        if held_for < cfg.minimum_hold_s:
            self._deterioration_started_at = None
            self._fire_started_at = None
            self._recovery_started_at = None
            return self._decision(
                obs,
                state=STATE_HOLD,
                action=ACTION_HOLD,
                reason=R_MIN_HOLD,
                score=score,
                confirmations=confirmations,
                drawdown_r=drawdown_r,
                now=now,
            )

        if score <= cfg.reset_threshold:
            self._fire_started_at = None
            if self._recovery_started_at is None:
                self._recovery_started_at = now
            recovered_for = now - self._recovery_started_at
            if recovered_for >= cfg.reset_persistence_s:
                self._deterioration_started_at = None
                self._recovery_started_at = None
                return self._decision(
                    obs,
                    state=STATE_HOLD,
                    action=ACTION_HOLD,
                    reason=R_RESET,
                    score=score,
                    confirmations=confirmations,
                    drawdown_r=drawdown_r,
                    now=now,
                )
            return self._decision(
                obs,
                state=STATE_WATCH,
                action=ACTION_HOLD,
                reason=R_RECOVERING,
                score=score,
                confirmations=confirmations,
                drawdown_r=drawdown_r,
                now=now,
            )

        self._recovery_started_at = None
        if score < cfg.arm_threshold or confirmations < cfg.min_confirmation_dimensions:
            self._fire_started_at = None
            return self._decision(
                obs,
                state=STATE_WATCH if self._deterioration_started_at is not None else STATE_HOLD,
                action=ACTION_HOLD,
                reason=R_DETERIORATING if self._deterioration_started_at is not None else R_HEALTHY,
                score=score,
                confirmations=confirmations,
                drawdown_r=drawdown_r,
                now=now,
            )

        if self._deterioration_started_at is None:
            self._deterioration_started_at = now
        armed_for = now - self._deterioration_started_at
        if armed_for < cfg.arm_persistence_s:
            self._fire_started_at = None
            return self._decision(
                obs,
                state=STATE_WATCH,
                action=ACTION_HOLD,
                reason=R_DETERIORATING,
                score=score,
                confirmations=confirmations,
                drawdown_r=drawdown_r,
                now=now,
            )

        price_confirmed = (
            drawdown_r >= cfg.min_retracement_r
            or obs.price <= obs.entry_price
            or _clamp01(obs.structure_failure) >= 0.75
        )
        if score < cfg.fire_threshold or not price_confirmed:
            self._fire_started_at = None
            return self._decision(
                obs,
                state=STATE_ARMED,
                action=ACTION_ARM,
                reason=R_ARMED if price_confirmed else R_PRICE_CONFIRMATION_MISSING,
                score=score,
                confirmations=confirmations,
                drawdown_r=drawdown_r,
                now=now,
            )

        if self._fire_started_at is None:
            self._fire_started_at = now
        if (now - self._fire_started_at) < cfg.fire_persistence_s:
            return self._decision(
                obs,
                state=STATE_ARMED,
                action=ACTION_ARM,
                reason=R_ARMED,
                score=score,
                confirmations=confirmations,
                drawdown_r=drawdown_r,
                now=now,
            )

        self._signaled = True
        return self._decision(
            obs,
            state=STATE_SIGNAL,
            action=ACTION_SIGNAL,
            reason=R_PERSISTENT_FAILURE,
            score=score,
            confirmations=confirmations,
            drawdown_r=drawdown_r,
            now=now,
        )
