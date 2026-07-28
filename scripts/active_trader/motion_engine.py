"""Persistent, account-agnostic motion engine for Active Trader.

A tick consumes read models plus local journal observations, restores T2 lease state,
evaluates exit hysteresis for monitored open positions, and writes one aggregate
snapshot. The engine owns no account taxonomy, execution environment, market-data
client, broker client, credential, or order action.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .momentum_exit_policy import (
    MomentumExitPolicy,
    MomentumObservation,
    STATE_SIGNAL,
)
from .motion_journal import JournalIntegrityError, MotionJournal
from .t2_jit_policy import (
    CandidateObservation,
    T2Lease,
    T2LeaseManager,
    T2PolicyConfig,
)

CONTRACT = "active-trader-motion-snapshot-v1"
STATE_CONTRACT = "active-trader-motion-engine-state-v1"

_ZERO_AUTHORITY = {
    "mutation": False,
    "order": False,
    "session_authorize": False,
    "canary": False,
    "financial_action": False,
    "auto_exit": False,
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_snapshot_path() -> Path:
    env = os.environ.get("ACTIVE_TRADER_MOTION_SNAPSHOT", "").strip()
    return (
        Path(env).expanduser()
        if env
        else _repo_root() / "data" / "active_trader" / "motion_snapshot.json"
    )


def default_state_path() -> Path:
    env = os.environ.get("ACTIVE_TRADER_MOTION_STATE", "").strip()
    return (
        Path(env).expanduser()
        if env
        else _repo_root() / "data" / "active_trader" / "motion_state.json"
    )


def _optional_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _event_time(value: Any) -> Optional[float]:
    numeric = _optional_float(value)
    if numeric is not None:
        return numeric
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None
    return None


def _first_time(raw: Mapping[str, Any]) -> Optional[float]:
    for key in (
        "observed_at",
        "observedAt",
        "last_update_at",
        "lastUpdateAt",
        "scanned_at",
        "scannedAt",
        "fired_at",
        "firedAt",
    ):
        timestamp = _event_time(raw.get(key))
        if timestamp is not None:
            return timestamp
    return None


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _explicit_symbols(session: Mapping[str, Any]) -> set[str]:
    values: list[Any] = []
    for container in (
        session,
        session.get("envelope")
        if isinstance(session.get("envelope"), Mapping)
        else {},
        session.get("draft")
        if isinstance(session.get("draft"), Mapping)
        else {},
    ):
        if not isinstance(container, Mapping):
            continue
        for key in ("authorized_symbols", "symbols", "symbol_list"):
            raw = container.get(key)
            if isinstance(raw, (list, tuple, set, frozenset)):
                values.extend(raw)
        raw_rule = container.get("symbol_list_or_universe_rule")
        if isinstance(raw_rule, (list, tuple, set, frozenset)):
            values.extend(raw_rule)
        elif isinstance(raw_rule, str):
            text = raw_rule.strip()
            if text.lower().startswith("symbols:"):
                text = text.split(":", 1)[1]
            # Fail closed on wildcard/rule expressions; accept explicit CSV only.
            if text and not any(
                token in text for token in ("*", "=", ">", "<", "(", ")")
            ):
                values.extend(part.strip() for part in text.split(","))
    return {
        str(value).strip().upper()
        for value in values
        if str(value).strip()
    }


def _session_context(session: Mapping[str, Any] | None) -> dict[str, Any]:
    session = session if isinstance(session, Mapping) else {}
    state = str(session.get("state") or "").strip().upper()
    workflow_label = str(
        session.get("workflow_mode")
        or session.get("mode")
        or session.get("workflow")
        or ""
    ).strip()
    return {
        "session_id": str(session.get("session_id") or ""),
        "state": state,
        "workflow_label": workflow_label,
        "motion_active": state == "ACTIVE",
        "symbols": _explicit_symbols(session),
    }


def _candidate_observation(
    raw: Mapping[str, Any],
    session: Mapping[str, Any] | None,
    *,
    now: float,
    position_open: bool = False,
) -> CandidateObservation:
    context = _session_context(session)
    symbol = str(raw.get("symbol") or "").strip().upper()
    observed_at = _first_time(raw)
    explicit_age = _optional_float(raw.get("baseline_quote_age_s"))
    baseline_age = (
        explicit_age
        if explicit_age is not None
        else (
            max(0.0, now - observed_at)
            if observed_at is not None
            else float("inf")
        )
    )

    state_raw = str(
        raw.get("setup_state")
        or raw.get("setupState")
        or raw.get("state")
        or raw.get("reviewState")
        or ""
    ).strip().upper()
    if position_open:
        setup_state = "IN_POSITION"
    elif state_raw in {"FIRED", "TRIGGERED", "TRIGGER"}:
        setup_state = "FIRED"
    elif state_raw in {"ARMED", "GO", "MANUAL_REVIEW", "NEAR_FIRE"}:
        setup_state = "ARMED"
    else:
        setup_state = state_raw or "WATCH"

    gate = str(
        raw.get("gate_decision")
        or raw.get("gateDecision")
        or raw.get("gate")
        or ""
    ).upper()
    if gate not in {"PASS", "VETO"}:
        gate = "DEFER"

    motion_eligible = bool(
        context["motion_active"]
        and symbol
        and symbol in context["symbols"]
    )
    priority = _optional_float(raw.get("priority_score"))
    if priority is None:
        priority = _optional_float(raw.get("ign"))
    if priority is None:
        priority = _optional_float(raw.get("score"))

    return CandidateObservation(
        symbol=symbol,
        observed_at=float(observed_at or 0.0),
        session_state=str(context["state"]),
        setup_state=setup_state,
        gate_decision="PASS" if position_open else gate,
        motion_eligible=motion_eligible,
        baseline_quote_age_s=float(baseline_age),
        trigger_distance_bps=_optional_float(
            raw.get("trigger_distance_bps")
            if raw.get("trigger_distance_bps") is not None
            else raw.get("triggerDistanceBps")
        ),
        expected_fire_in_s=_optional_float(
            raw.get("expected_fire_in_s")
            if raw.get("expected_fire_in_s") is not None
            else raw.get("expectedFireInS")
        ),
        operator_selected=bool(
            raw.get("operator_selected") or raw.get("operatorSelected")
        ),
        position_open=bool(position_open),
        kill_switch=bool(raw.get("kill_switch") or raw.get("killSwitch")),
        priority_score=float(priority or 0.0),
    )


def _position_key(payload: Mapping[str, Any]) -> str:
    return str(
        payload.get("position_id")
        or payload.get("positionId")
        or payload.get("symbol")
        or ""
    ).strip()


def _position_is_open(payload: Mapping[str, Any]) -> bool:
    if "position_open" in payload:
        return bool(payload.get("position_open"))
    status = str(payload.get("status") or "OPEN").strip().upper()
    return status in {"OPEN", "ACTIVE", "HELD", "IN_POSITION"}


class MotionEngine:
    def __init__(
        self,
        *,
        snapshot_path: str | Path | None = None,
        state_path: str | Path | None = None,
        journal: MotionJournal | None = None,
        t2_config: T2PolicyConfig | None = None,
    ) -> None:
        self.snapshot_path = (
            Path(snapshot_path).expanduser()
            if snapshot_path
            else default_snapshot_path()
        )
        self.state_path = (
            Path(state_path).expanduser()
            if state_path
            else default_state_path()
        )
        self.journal = journal or MotionJournal()
        self.t2_config = t2_config or T2PolicyConfig()

    def _load_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("contract") == STATE_CONTRACT:
                return data
        except Exception:
            pass
        return {}

    def _manager(self) -> T2LeaseManager:
        manager = T2LeaseManager(self.t2_config)
        state = self._load_state()
        leases = state.get("leases") if isinstance(state.get("leases"), list) else []
        restored: dict[str, T2Lease] = {}
        for raw in leases:
            if not isinstance(raw, Mapping):
                continue
            try:
                lease = T2Lease(
                    **{
                        key: raw[key]
                        for key in (
                            "lease_id",
                            "symbol",
                            "admitted_at",
                            "renewed_at",
                            "expires_at",
                            "priority",
                            "position_open",
                        )
                    }
                )
                restored[lease.symbol] = lease
            except Exception:
                continue
        manager._leases = restored
        cooldowns = state.get("cooldown_until")
        manager._cooldown_until = {
            str(key): float(value)
            for key, value in (
                cooldowns.items()
                if isinstance(cooldowns, Mapping)
                else []
            )
            if _optional_float(value) is not None
        }
        return manager

    def _save_state(self, manager: T2LeaseManager, *, now: float) -> None:
        _atomic_write_json(
            self.state_path,
            {
                "contract": STATE_CONTRACT,
                "saved_at": float(now),
                "leases": [lease.to_dict() for lease in manager.leases],
                "cooldown_until": dict(manager._cooldown_until),
            },
        )

    def _latest_candidate_payloads(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for payload in self.journal.payloads("candidate_observation"):
            symbol = str(payload.get("symbol") or "").strip().upper()
            if symbol:
                latest[symbol] = payload
        return latest

    def _position_histories(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for payload in self.journal.payloads("position_observation"):
            key = _position_key(payload)
            if key:
                grouped.setdefault(key, []).append(payload)
        return grouped

    def _evaluate_positions(
        self,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[Mapping[str, Any]],
    ]:
        positions: list[dict[str, Any]] = []
        exit_signals: list[dict[str, Any]] = []
        position_candidates: list[Mapping[str, Any]] = []

        for position_id, history in sorted(self._position_histories().items()):
            if not history or not _position_is_open(history[-1]):
                continue
            policy = MomentumExitPolicy()
            decision = None
            for payload in history:
                try:
                    decision = policy.evaluate(
                        MomentumObservation.from_mapping(payload)
                    )
                except Exception:
                    continue
            if decision is None:
                continue

            latest = dict(history[-1])
            symbol = str(latest.get("symbol") or "").strip().upper()
            row = {
                "position_id": position_id,
                "symbol": symbol,
                "state": decision.state,
                "action": decision.action,
                "reason_code": decision.reason_code,
                "score": decision.score,
                "confirmations": decision.confirmations,
                "drawdown_from_high_r": decision.drawdown_from_high_r,
                "armed_for_s": decision.armed_for_s,
                "fire_for_s": decision.fire_for_s,
                "recovery_for_s": decision.recovery_for_s,
                "refresh_after_s": decision.refresh_after_s,
                "current_price": _optional_float(latest.get("price")),
                "entry_price": _optional_float(latest.get("entry_price")),
                "hard_stop_price": _optional_float(latest.get("hard_stop_price")),
                "high_watermark": _optional_float(latest.get("high_watermark")),
                "observed_at": _first_time(latest),
                "evidence_fresh": decision.state != "PROTECT_ONLY",
                "display_only": True,
            }
            positions.append(row)
            if decision.state == STATE_SIGNAL:
                exit_signals.append(
                    {
                        **row,
                        "signal_only": True,
                        "automatic_order_sent": False,
                        "account_bound": False,
                        "authority": dict(_ZERO_AUTHORITY),
                    }
                )
            position_candidates.append(
                {
                    **latest,
                    "symbol": symbol,
                    "position_open": True,
                    "setup_state": "IN_POSITION",
                    "gate_decision": "PASS",
                    "priority_score": 100000.0,
                }
            )
        return positions, exit_signals, position_candidates

    def tick(
        self,
        candidates: Iterable[Mapping[str, Any]],
        *,
        session: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        now = float(time.time() if now is None else now)
        verification = self.journal.verify()
        if not verification.ok:
            raise JournalIntegrityError(
                verification.error or "motion journal invalid"
            )

        merged: dict[str, dict[str, Any]] = {}
        for raw in candidates:
            if not isinstance(raw, Mapping):
                continue
            symbol = str(raw.get("symbol") or "").strip().upper()
            if symbol:
                merged[symbol] = dict(raw)
        # Explicit local observations override weaker read-model projections.
        merged.update(self._latest_candidate_payloads())

        positions, exit_signals, position_candidates = self._evaluate_positions()
        manager = self._manager()
        observations = [
            _candidate_observation(raw, session, now=now)
            for raw in merged.values()
        ]
        observations.extend(
            _candidate_observation(
                raw,
                session,
                now=now,
                position_open=True,
            )
            for raw in position_candidates
        )
        t2_snapshot = manager.reconcile(observations, now=now)

        decisions = {row.symbol: row for row in t2_snapshot.decisions}
        candidate_rows: list[dict[str, Any]] = []
        for symbol, raw in sorted(merged.items()):
            decision = decisions.get(symbol)
            observed_at = _first_time(raw)
            candidate_rows.append(
                {
                    "symbol": symbol,
                    "tier": decision.tier if decision else "T0",
                    "admitted": bool(decision.admitted) if decision else False,
                    "reason_code": (
                        decision.reason_code if decision else "not_evaluated"
                    ),
                    "refresh_after_s": (
                        decision.refresh_after_s
                        if decision
                        else self.t2_config.idle_refresh_s
                    ),
                    "priority": decision.priority if decision else 0.0,
                    "last_update_age_s": (
                        max(0.0, now - observed_at)
                        if observed_at is not None
                        else None
                    ),
                    "observed_at": observed_at,
                    "price": _optional_float(
                        raw.get("price")
                        if raw.get("price") is not None
                        else raw.get("last")
                    ),
                    "setup_state": (
                        raw.get("setup_state")
                        or raw.get("setupState")
                        or raw.get("state")
                    ),
                    "gate_decision": (
                        raw.get("gate_decision")
                        or raw.get("gateDecision")
                        or raw.get("gate")
                    ),
                    "source": raw.get("source") or "motion_journal",
                }
            )

        refresh = t2_snapshot.ui_refresh_after_s
        if positions:
            refresh = min(refresh, self.t2_config.active_refresh_s)
        context = _session_context(session)
        snapshot = {
            "contract": CONTRACT,
            "generated_at": now,
            "data_state": (
                "LIVE_MOTION"
                if candidate_rows or positions
                else "EMPTY_LIVE_MOTION"
            ),
            "available": True,
            "ui_refresh_after_s": int(refresh),
            "push_primary": bool(t2_snapshot.push_primary),
            "max_pull_fallbacks_per_minute": int(
                t2_snapshot.max_pull_fallbacks_per_minute
            ),
            "session": {
                "session_id": context["session_id"],
                "state": context["state"],
                "workflow_label": context["workflow_label"],
                "motion_ready": bool(context["motion_active"]),
                "authorized_symbol_count": len(context["symbols"]),
                "account_bound": False,
            },
            "t2": {
                "operating_cap": t2_snapshot.operating_cap,
                "provider_hard_cap": t2_snapshot.provider_hard_cap,
                "leases": [lease.to_dict() for lease in t2_snapshot.leases],
                "decisions": [
                    decision.to_dict()
                    for decision in t2_snapshot.decisions
                ],
                "events": [event.to_dict() for event in t2_snapshot.events],
            },
            "candidates": candidate_rows,
            "positions": positions,
            "exit_signals": exit_signals,
            "authority": dict(_ZERO_AUTHORITY),
            "note": (
                "Account-agnostic market-state snapshot. Exit signals are evidence; "
                "no account is selected and no order is sent."
            ),
        }

        self._save_state(manager, now=now)
        self.journal.append("motion_snapshot", snapshot, recorded_at=now)
        final_verification = self.journal.verify()
        snapshot["journal"] = {
            "verified": bool(final_verification.ok),
            "last_sequence": final_verification.last_sequence,
            "last_hash": final_verification.last_hash,
        }
        _atomic_write_json(self.snapshot_path, snapshot)
        return snapshot
