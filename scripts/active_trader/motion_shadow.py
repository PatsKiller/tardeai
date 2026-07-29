"""Shadow producer for the Active Trader motion snapshot.

Builds ``CandidateObservation``s from the live near-fire arming ladder and
``MomentumObservation``s from open monitored (paper/shadow) positions, runs the
deterministic ``T2LeaseManager`` + ``MomentumExitPolicy`` policies, assembles the
``active-trader-motion-snapshot-v1`` payload, and appends it to the persistent
shadow observation journal.

This module is invoked SEPARATELY from the read endpoint (a function + a ``__main__``
for manual / future-cron use). NO cron/schedule/service is wired in this change. To
run one shadow cycle manually:

    python -m active_trader.motion_shadow          # from the scripts/ dir on sys.path
    # or
    PYTHONPATH=scripts python scripts/active_trader/motion_shadow.py

Fail-closed posture: missing or stale inputs yield EMPTY observation sets — the
policies then produce an honest idle snapshot. Nothing is ever fabricated. This
producer owns no broker/session/credential/order path and emits ``EXIT_SIGNAL`` only
as EVIDENCE — it never acts on it.

Known live-data gaps (documented, not fabricated):
* motion authorization (``motion_eligible``) comes from an operator opt-in set
  (env ``ACTIVE_TRADER_MOTION_AUTHORIZED_SYMBOLS`` or a fixtures file); absent -> not
  authorized -> no T2 lease. This is the fail-closed default until the session/
  capability layer supplies it.
* the arming ladder does not carry a fresh baseline quote age or trigger-distance bps;
  absent -> treated as stale/not-near-fire (no T2). T2 tier here derives from the JIT
  lease, not a live L2 book (that integration is future work).
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .momentum_exit_policy import (
    MomentumExitPolicy,
    MomentumObservation,
    STATE_SIGNAL,
)
from .motion_api import (
    MOTION_CONTRACT,
    _MAX_PULL_FALLBACKS_PER_MINUTE,
    _ZERO_AUTHORITY,
)
from .motion_journal import DEFAULT_MAX_LINES, append_snapshot
from .t2_jit_policy import (
    CandidateObservation,
    T2LeaseManager,
    T2Snapshot,
    TIER_T1,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# input gathering (best-effort live reads; always fail closed to empty)
# ---------------------------------------------------------------------------
def _authorized_symbols() -> set[str]:
    """Operator opt-in set of symbols with motion authorized in an ACTIVE workflow.
    Absent -> empty (nothing authorized). Never raises."""
    out: set[str] = set()
    env = os.environ.get("ACTIVE_TRADER_MOTION_AUTHORIZED_SYMBOLS", "").strip()
    if env:
        for tok in env.replace(",", " ").split():
            tok = tok.strip().upper()
            if tok:
                out.add(tok)
    fx = os.environ.get("ACTIVE_TRADER_MOTION_AUTHORIZED_FILE", "").strip()
    if fx:
        try:
            data = json.loads(Path(fx).expanduser().read_text(encoding="utf-8"))
            rows = data.get("symbols") if isinstance(data, Mapping) else data
            if isinstance(rows, list):
                for tok in rows:
                    if isinstance(tok, str) and tok.strip():
                        out.add(tok.strip().upper())
        except Exception:
            pass
    return out


def gather_candidate_observations(now: float) -> list[CandidateObservation]:
    """Map the live arming ladder (IGN_45+ / setup ARMED, below TRIGGER) into
    CandidateObservations. Fail-closed to [] when the arming read is unavailable."""
    try:
        from .read_api import _arming_status  # local import: keeps the read path light
        arming = _arming_status()
    except Exception:
        return []
    if not isinstance(arming, Mapping) or not arming.get("available"):
        return []
    session_state = "ACTIVE" if arming.get("market_open") else "CLOSED"
    authorized = _authorized_symbols()
    out: list[CandidateObservation] = []
    for row in arming.get("near_firing") or []:
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        setup_state = str(row.get("setupState") or "").strip().upper()
        # A fired lane maps to the FIRED setup state; otherwise trust the row's state.
        if str(row.get("lane") or "").strip().upper() == "TRIGGER":
            setup_state = "FIRED"
        out.append(
            CandidateObservation.from_mapping(
                {
                    "symbol": symbol,
                    "observed_at": now,
                    "session_state": session_state,
                    "setup_state": setup_state,
                    "gate_decision": str(row.get("gate") or "").strip().upper(),
                    "motion_eligible": symbol in authorized,
                    # arming ladder carries no fresh baseline quote age -> fail closed
                    "baseline_quote_age_s": float("inf"),
                    "trigger_distance_bps": None,
                    "expected_fire_in_s": None,
                    "operator_selected": symbol in authorized,
                    "position_open": False,
                    "kill_switch": False,
                    "priority_score": 0.0,
                }
            )
        )
    return out


def gather_momentum_observations(now: float) -> list[MomentumObservation]:
    """Load open monitored (paper/shadow) position evidence. Fail-closed to [] unless a
    real source supplies the full deterministic momentum inputs (never fabricated).

    Source (optional): env ``ACTIVE_TRADER_MOTION_POSITIONS`` -> a JSON file whose
    ``positions``/``observations`` list holds MomentumObservation-shaped mappings."""
    fx = os.environ.get("ACTIVE_TRADER_MOTION_POSITIONS", "").strip()
    if not fx:
        return []
    try:
        data = json.loads(Path(fx).expanduser().read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = None
    if isinstance(data, Mapping):
        rows = data.get("positions") or data.get("observations")
    elif isinstance(data, list):
        rows = data
    if not isinstance(rows, list):
        return []
    out: list[MomentumObservation] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        raw = dict(row)
        raw.setdefault("observed_at", now)
        obs = MomentumObservation.from_mapping(raw)
        if obs.symbol:
            out.append(obs)
    return out


# ---------------------------------------------------------------------------
# deterministic assembly (pure — easy to unit test)
# ---------------------------------------------------------------------------
def _finite_or_none(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    return v if math.isfinite(v) else None


def _evidence_age_s(obs: MomentumObservation) -> Optional[float]:
    ages = [obs.quote_age_s, obs.book_age_s, obs.tape_age_s]
    finite = [a for a in ages if isinstance(a, (int, float)) and math.isfinite(a)]
    return max(finite) if finite else None


def _motion_refresh_after_s(t2_snap: T2Snapshot, positions: list[dict[str, Any]]) -> int:
    """5 when any T2 lease or open position is active; 10 when near-fire T1 candidates
    exist but no T2/positions; else 30."""
    if t2_snap.leases or positions:
        return 5
    if any(decision.tier == TIER_T1 for decision in t2_snap.decisions):
        return 10
    return 30


def _position_row(policy: MomentumExitPolicy, obs: MomentumObservation) -> dict[str, Any]:
    decision = policy.evaluate(obs)
    row = dict(decision.to_dict())  # exit-policy evidence (state/action/reason/score/...)
    hwm = obs.high_watermark
    if hwm is None or not math.isfinite(hwm):
        hwm = obs.price if math.isfinite(obs.price) else None
    row.update(
        {
            "price": _finite_or_none(obs.price),
            "entry_price": _finite_or_none(obs.entry_price),
            "hard_stop_price": _finite_or_none(obs.hard_stop_price),
            "high_watermark": _finite_or_none(hwm),
            "evidence_age_s": _evidence_age_s(obs),
        }
    )
    return row


def assemble_motion_snapshot(
    candidate_observations: Iterable[CandidateObservation | Mapping[str, Any]],
    momentum_observations: Iterable[MomentumObservation | Mapping[str, Any]],
    *,
    now: float,
    lease_manager: Optional[T2LeaseManager] = None,
    exit_policies: Optional[dict[str, MomentumExitPolicy]] = None,
) -> dict[str, Any]:
    """Run the deterministic policies and build the motion-snapshot contract dict.

    ``lease_manager`` / ``exit_policies`` may be supplied by a long-running producer to
    preserve lease + hysteresis state across cycles; fresh instances are used otherwise
    (single-cycle deterministic).
    """
    lm = lease_manager if lease_manager is not None else T2LeaseManager()
    t2_snap = lm.reconcile(candidate_observations, now=now)

    policies = exit_policies if exit_policies is not None else {}
    positions: list[dict[str, Any]] = []
    exit_signals: list[dict[str, Any]] = []
    for item in momentum_observations:
        obs = (
            item
            if isinstance(item, MomentumObservation)
            else MomentumObservation.from_mapping(item)
        )
        if not obs.symbol:
            continue
        policy = policies.get(obs.symbol)
        if policy is None:
            policy = MomentumExitPolicy()
            policies[obs.symbol] = policy
        row = _position_row(policy, obs)
        positions.append(row)
        if row.get("state") == STATE_SIGNAL:
            # EVIDENCE ONLY — surfaced, never acted upon.
            exit_signals.append(
                {
                    "symbol": obs.symbol,
                    "state": row.get("state"),
                    "reason_code": row.get("reason_code"),
                    "at": float(now),
                }
            )

    t2_dict = t2_snap.to_dict()
    return {
        "contract": MOTION_CONTRACT,
        "generated_at": float(now),
        "ui_refresh_after_s": _motion_refresh_after_s(t2_snap, positions),
        "push_primary": True,
        "max_pull_fallbacks_per_minute": t2_snap.max_pull_fallbacks_per_minute,
        "t2": {
            "operating_cap": t2_snap.operating_cap,
            "provider_hard_cap": t2_snap.provider_hard_cap,
            "leases": t2_dict["leases"],
            "decisions": t2_dict["decisions"],
        },
        "positions": positions,
        "exit_signals": exit_signals,
        "read_only": True,
        "write": False,
        "authority": dict(_ZERO_AUTHORITY),
    }


# ---------------------------------------------------------------------------
# one shadow cycle: gather -> assemble -> append
# ---------------------------------------------------------------------------
def run_shadow_cycle(
    *,
    now: Optional[float] = None,
    path: Any = None,
    lease_manager: Optional[T2LeaseManager] = None,
    exit_policies: Optional[dict[str, MomentumExitPolicy]] = None,
    max_lines: Optional[int] = DEFAULT_MAX_LINES,
    candidate_observations: Optional[Iterable[Any]] = None,
    momentum_observations: Optional[Iterable[Any]] = None,
) -> dict[str, Any]:
    """Gather live inputs (or use injected ones), assemble the snapshot, append it to
    the journal, and return it. This is the ONLY writer of the journal."""
    current = time.time() if now is None else float(now)
    cands = (
        list(candidate_observations)
        if candidate_observations is not None
        else gather_candidate_observations(current)
    )
    poss = (
        list(momentum_observations)
        if momentum_observations is not None
        else gather_momentum_observations(current)
    )
    snapshot = assemble_motion_snapshot(
        cands,
        poss,
        now=current,
        lease_manager=lease_manager,
        exit_policies=exit_policies,
    )
    append_snapshot(snapshot, path=path, max_lines=max_lines)
    return snapshot


def main() -> int:
    snapshot = run_shadow_cycle()
    print(
        json.dumps(
            {
                "appended": True,
                "contract": snapshot["contract"],
                "generated_at": snapshot["generated_at"],
                "ui_refresh_after_s": snapshot["ui_refresh_after_s"],
                "t2_leases": len(snapshot["t2"]["leases"]),
                "t2_decisions": len(snapshot["t2"]["decisions"]),
                "positions": len(snapshot["positions"]),
                "exit_signals": len(snapshot["exit_signals"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - manual/cron entrypoint
    raise SystemExit(main())
