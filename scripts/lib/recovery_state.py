"""Recovery & Re-Entry Engine — piece B: the recovery state machine.

Spec: ``persistent-state/handoffs/SPEC_RECOVERY_REENTRY_ENGINE_20261103.md`` §3.2. Operator's words behind it:
"SpaceX is back up to 141 … Nothing has notified me to get back in."

This module is PURE. It takes one ``recovery_cases`` row (piece A owns the store), a market snapshot and the
policy, and returns the next state, the confidence, which triggers fired, the per-account gate annotations
and the next thing that would change the answer. Nothing here writes a database, a holdings file, a plan or
an order; the callers (``watch_alerts_eval.py`` every 20 minutes, ``recovery_watch_daily.py`` at 07:30) apply
the result through piece A's accessor.

Three rules from the spec that shape the code:

* **A stop-out is an event with a follow-up, never an ending.** A case that has done nothing for 20 sessions
  stays WATCHING (its card moves to the digest); it is never auto-closed while materiality is T2 or worse.
* **Gates annotate; they never silence.** Wash/house-hold, RSI, the entry zone and the residual each become an
  annotation with a *when* and a *what would change it*. A residual is a fact to display, never a disqualifier
  (operator ruling 2026-11-03: the "held" concept is removed, not tuned). Only an account with NO date-open route
  blocks RE_ENTRY_READY; a single failing caveat never hides the card.
* **Recovery is a reclaim, not a pullback.** R1/R2 are reclaim triggers (exit +1%, the stop that fired); R3/R5
  raise confidence but can never advance a state on their own; R4 (SMA20 reclaim) is the ready trigger.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

STOPPED_OUT = "STOPPED_OUT"
WATCHING = "WATCHING"
RECOVERING = "RECOVERING"
RE_ENTRY_READY = "RE_ENTRY_READY"
RE_ENTERED = "RE_ENTERED"
CLOSED = "CLOSED"
SNOOZED = "SNOOZED"

#: States the machine may move a case INTO. Operator-held states are never overwritten by a rule.
OPERATOR_STATES = frozenset({CLOSED, SNOOZED, RE_ENTERED})
MACHINE_STATES = (STOPPED_OUT, WATCHING, RECOVERING, RE_ENTRY_READY)

DEFAULT_POLICY: dict[str, Any] = {
    # R1 / R2: reclaim triggers. SPCX 141.65 vs the 137.19 exit is +3.3%, so R1 fires on the first close.
    "reclaim_exit_pct": 0.010,
    "stop_reclaim_enabled": True,
    # R3: momentum. A cross up THROUGH rsi_level, or two consecutive up sessions on the MACD histogram.
    "rsi_level": 40.0,
    "macd_up_sessions": 2,
    # R4: the ready trigger.
    "sma_reclaim_period": 20,
    # R5: a verified catalyst amplifies confidence; it is never sufficient alone.
    "catalyst_min_confidence": 0.80,
    "catalyst_max_sessions": 5,
    # Confidence = sum of the fired trigger weights (clamped to 1.0).
    "weights": {"R1": 0.35, "R2": 0.45, "R3": 0.10, "R4": 0.25, "R5": 0.15},
    "recovering_floor": 0.30,
    "ready_floor": 0.55,
    # Decay: after this many sessions without a trigger the card is digest-only; the case is NOT closed.
    "decay_sessions": 20,
}


def load_policy(path: str | Path | None = None) -> dict[str, Any]:
    """The reviewed policy, with the code defaults filling any key it does not set.

    An unreadable or malformed file is NOT a reason to weaken the engine silently: the defaults apply and
    the caller is told (``policy_source``) so the receipt can say which rules actually ran.
    """
    policy = json.loads(json.dumps(DEFAULT_POLICY))  # deep copy
    if path is None:
        return {**policy, "policy_source": "defaults"}
    try:
        import yaml  # noqa: PLC0415 — optional at import time, required only to read the reviewed file

        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, ImportError):
        return {**policy, "policy_source": "defaults:policy_unreadable"}
    if not isinstance(doc, Mapping):
        return {**policy, "policy_source": "defaults:policy_not_a_mapping"}
    merged = {**policy, **{k: v for k, v in doc.items() if not str(k).startswith("_")}}
    # Piece A's reviewed file is nested (triggers/confidence/residual/eligibility). Read ITS dialect and map
    # it onto the flat names the engine uses; never fork a threshold that lives in that file.
    trig = doc.get("triggers") if isinstance(doc.get("triggers"), Mapping) else {}
    conf = doc.get("confidence") if isinstance(doc.get("confidence"), Mapping) else {}
    resid = doc.get("residual") if isinstance(doc.get("residual"), Mapping) else {}
    def _pick(dst, *names, src=trig):
        for name in names:
            if name in src and src[name] is not None:
                dst[name if name in dst else next(iter(dst))] = src[name]
                return True
        return False
    mapping = {
        "reclaim_exit_pct": ("r1_reclaim_exit_pct",),
        "stop_reclaim_enabled": ("r2_reclaim_stop",),
        "rsi_level": ("r3_rsi_cross",),
        "macd_up_sessions": ("r3_macd_histogram_sessions",),
        "catalyst_min_confidence": ("r5_catalyst_min_confidence",),
        "catalyst_max_sessions": ("r5_catalyst_window_sessions",),
        "decay_sessions": ("decay_sessions",),
    }
    for flat, (nested,) in mapping.items():
        if nested in trig and trig[nested] is not None:
            value = trig[nested]
            if flat == "rsi_level" and isinstance(value, bool):
                continue  # a boolean switch is not a level; keep the reviewed default
            merged[flat] = value
    if isinstance(conf.get("weights"), Mapping):
        merged["weights"] = {**policy["weights"], **{str(k).upper(): v for k, v in conf["weights"].items()}}
    if conf.get("ready_floor") is not None:
        merged["ready_floor"] = conf["ready_floor"]
    if conf.get("recovering_floor") is not None:
        merged["recovering_floor"] = conf["recovering_floor"]
    merged["policy_source"] = str(doc.get("schema") or "recovery_policy")
    return merged


def _num(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def exit_price(case: Mapping[str, Any]) -> float | None:
    """The exit price the recovery is measured against: the largest cluster exit, else the row's own field."""
    direct = _num(case.get("exit_price") or case.get("last_exit_price"))
    if direct is not None:
        return direct
    raw = case.get("exits_json")
    rows: Iterable[Any] = []
    if isinstance(raw, str):
        try:
            rows = json.loads(raw or "[]")
        except ValueError:
            rows = []
    elif isinstance(raw, (list, tuple)):
        rows = raw
    prices = [p for p in (_num((r or {}).get("exit_price")) for r in rows if isinstance(r, Mapping)) if p]
    return max(prices) if prices else None


def residual_fact(case: Mapping[str, Any]) -> dict | None:
    """The residual as a FACT TO DISPLAY, never a silencer (operator ruling 2026-11-03).

    Piece A carries ``residual_pct_of_pre_exit`` and a plain-language ``residual_note``; this module renders the
    note and does not re-derive a percentage or decide held/not-held. The earlier "held" concept is removed, not
    tuned: 200 of 1,200 shares is 14.3% while 200 of 1,000 is 20%, and a threshold on it suppressed SPCX either way.
    """
    note = str(case.get("residual_note") or "").strip()
    pct = _num(case.get("residual_pct_of_pre_exit"))
    residual = _num(case.get("residual_shares"))
    if not note and pct is None and not residual:
        return None
    detail = note or (f"{residual:g} shares remain after the exit ({pct:g}%)" if residual and pct is not None
                      else f"{residual:g} shares remain after the exit" if residual else f"{pct:g}% of the position remains")
    return {"gate": "residual", "account": case.get("account"), "until": None, "detail": detail,
            "would_change_it": "a later exit or a re-entry; this is information, not a blocker",
            "blocks_ready": False}


def _eligibility(case: Mapping[str, Any]) -> dict[str, Any]:
    """Piece A emits ``[{account, eligible, eligible_from, reason}]``; an older mapping is accepted too."""
    raw = case.get("eligibility_json") or case.get("eligibility") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            raw = {}
    if isinstance(raw, (list, tuple)):
        rows = {}
        for item in raw:
            if not isinstance(item, Mapping) or not item.get("account"):
                continue
            rows[str(item["account"])] = {
                "eligible": bool(item.get("eligible")),
                "until": item.get("eligible_from"),
                "gate": item.get("gate") or (None if item.get("eligible") else "house_hold"),
                "would_change_it": item.get("would_change_it") or item.get("reason"),
            }
        return rows
    return dict(raw) if isinstance(raw, Mapping) else {}


def gate_annotations(case: Mapping[str, Any], snapshot: Mapping[str, Any], policy: Mapping[str, Any],
                     now: datetime) -> list[dict]:
    """Every caveat as an annotation with a *when* and a *what would change it* — never a silencer.

    ``blocks_ready`` is True only when the caveat removes the last eligible account; every other caveat is
    information the operator should see beside the recovery ("RSI 39.1 — a close above 40 lifts it").
    """
    out: list[dict] = []
    elig = _eligibility(case)

    # Per-account eligibility: wash sale / house hold with an explicit date.
    for account, row in sorted(elig.items()):
        row = row if isinstance(row, Mapping) else {"eligible": bool(row)}
        until = row.get("until") or row.get("eligible_from")
        if row.get("eligible"):
            # The date gate is open; whether to re-enter is the operator's call, so the card says that and
            # never turns an open gate into a recommendation.
            out.append({"gate": "pending_operator_decision", "account": account, "until": None,
                        "would_change_it": "your decision on the recovery card",
                        "blocks_ready": False})
            continue
        out.append({
            "gate": str(row.get("gate") or "house_hold"),
            "account": account,
            "until": until,
            "would_change_it": str(row.get("would_change_it")
                                   or (f"the date {until} is reached" if until else "the hold is lifted")),
            "blocks_ready": False,  # recomputed below, once we know whether ANY account is date-open
        })
    any_eligible = any((r.get("eligible") if isinstance(r, Mapping) else bool(r)) for r in elig.values()) \
        if elig else True  # no eligibility data: do not invent a blocker
    if not any_eligible:
        for row in out:
            row["blocks_ready"] = True

    # Residual: shown, never used to suppress (operator ruling 2026-11-03).
    fact = residual_fact(case)
    if fact:
        out.append(fact)

    # The entry zone: a price above it is not a blocker, only a stale plan to re-derive.
    plan = case.get("plan_json") if isinstance(case.get("plan_json"), Mapping) else {}
    zone_high = _num(snapshot.get("entry_high") or (plan or {}).get("entry_high"))
    close = _num(snapshot.get("close"))
    if zone_high and close and close > zone_high:
        out.append({"gate": "above_entry_zone", "account": None, "until": None,
                    "would_change_it": f"a pullback to {zone_high:.2f} or a re-derived zone",
                    "blocks_ready": False})

    # RSI: below the level is information, never a blocker while the reclaim triggers are firing.
    rsi = _num(snapshot.get("rsi"))
    if rsi is not None and rsi < float(policy.get("rsi_level") or 40.0):
        out.append({"gate": "rsi_below_level", "account": None, "until": None,
                    "would_change_it": f"RSI crosses up through {float(policy['rsi_level']):.0f}",
                    "blocks_ready": False})
    return out


def _trigger_flags(case: Mapping[str, Any], snapshot: Mapping[str, Any], policy: Mapping[str, Any]) -> dict:
    close = _num(snapshot.get("close"))
    ep = exit_price(case)
    stop = _num(snapshot.get("stop_level") or case.get("stop_level"))
    sma20 = _num(snapshot.get("sma20"))
    rsi = _num(snapshot.get("rsi"))
    rsi_prev = _num(snapshot.get("rsi_prev"))
    macd_up = int(snapshot.get("macd_up_sessions") or 0)
    catalyst_conf = _num(snapshot.get("catalyst_confidence")) or 0.0
    catalyst_age = snapshot.get("catalyst_sessions_ago")

    reclaim_exit = bool(close and ep and close >= ep * (1.0 + float(policy.get("reclaim_exit_pct") or 0.01)))
    reclaim_stop = bool(policy.get("stop_reclaim_enabled", True) and close and stop and close >= stop)
    rsi_cross = bool(rsi is not None and rsi >= float(policy.get("rsi_level") or 40.0)
                     and (rsi_prev is None or rsi_prev < float(policy.get("rsi_level") or 40.0)))
    momentum = bool(rsi_cross or macd_up >= int(policy.get("macd_up_sessions") or 2))
    sma_reclaim = bool(close and sma20 and close >= sma20)
    catalyst = bool(catalyst_conf >= float(policy.get("catalyst_min_confidence") or 0.8)
                    and (catalyst_age is None
                         or int(catalyst_age) <= int(policy.get("catalyst_max_sessions") or 5)))
    return {"R1": reclaim_exit, "R2": reclaim_stop, "R3": momentum, "R4": sma_reclaim, "R5": catalyst}


def next_trigger(case: Mapping[str, Any], snapshot: Mapping[str, Any], policy: Mapping[str, Any],
                 flags: Mapping[str, bool]) -> str:
    """The one line the operator's card shows for what would change the answer."""
    if flags.get("R4"):
        return "already reclaiming the 20-day mean; confirm eligibility"
    sma20 = _num(snapshot.get("sma20"))
    close = _num(snapshot.get("close"))
    ep = exit_price(case)
    if not flags.get("R1") and ep and close:
        return f"a close at {ep * (1.0 + float(policy.get('reclaim_exit_pct') or 0.01)):.2f} reclaims the exit"
    if sma20:
        return f"a close at {sma20:.2f} reclaims the 20-day mean"
    if not flags.get("R3"):
        return f"RSI crossing up through {float(policy.get('rsi_level') or 40):.0f}"
    return "no mechanical trigger left; the next session's close"


@dataclass
class Decision:
    """What the callers apply. No side effects were performed to produce it."""

    state: str
    previous_state: str
    confidence: float
    triggers: dict[str, bool] = field(default_factory=dict)
    annotations: list[dict] = field(default_factory=list)
    next_trigger: str = ""
    changed: bool = False
    reason: str = ""
    eligible_accounts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"state": self.state, "previous_state": self.previous_state, "confidence": round(self.confidence, 4),
                "triggers": dict(self.triggers), "annotations": list(self.annotations),
                "next_trigger": self.next_trigger, "changed": self.changed, "reason": self.reason,
                "eligible_accounts": list(self.eligible_accounts)}


def evaluate(case: Mapping[str, Any], snapshot: Mapping[str, Any] | None,
             policy: Mapping[str, Any] | None = None, *, now: datetime | None = None) -> Decision:
    """One case → the next state. Pure: same inputs, same answer.

    An operator-held case (closed, snoozed, already re-entered) is returned untouched: a rule never overrides
    the operator. A missing snapshot returns the case's own state with a reason, never a guess.
    """
    policy = policy or DEFAULT_POLICY
    now = now or datetime.now(timezone.utc)
    prev = str(case.get("state") or STOPPED_OUT).upper()
    if prev in OPERATOR_STATES:
        return Decision(state=prev, previous_state=prev, confidence=0.0, reason="operator decision holds")
    if not snapshot:
        return Decision(state=prev, previous_state=prev, confidence=0.0,
                        reason="no market snapshot; state unchanged rather than guessed")

    flags = _trigger_flags(case, snapshot, policy)
    weights = policy.get("weights") or DEFAULT_POLICY["weights"]
    confidence = min(1.0, sum(float(weights.get(k) or 0.0) for k, fired in flags.items() if fired))
    annotations = gate_annotations(case, snapshot, policy, now)
    eligible = [a for a, r in _eligibility(case).items()
                if (r.get("eligible") if isinstance(r, Mapping) else bool(r))]
    if not _eligibility(case):
        eligible = [str(case.get("account") or "unknown")]
    blocked = any(a.get("blocks_ready") for a in annotations)

    if flags["R4"] and confidence >= float(policy.get("ready_floor") or 0.55) and eligible and not blocked:
        state, reason = RE_ENTRY_READY, "reclaims the 20-day mean with confidence over the floor"
    elif (flags["R1"] or flags["R2"] or confidence >= float(policy.get("recovering_floor") or 0.30)) and not blocked:
        state, reason = RECOVERING, "a reclaim trigger fired above the exit"
    else:
        state, reason = WATCHING, ("gates block re-entry until they lift" if blocked
                                   else "no reclaim trigger yet")
    # A case starts STOPPED_OUT on day 0; the first evaluation moves it to WATCHING or better.
    if prev == STOPPED_OUT and state == WATCHING:
        reason = "first evaluation after the stop-out; watching from here"

    return Decision(state=state, previous_state=prev, confidence=confidence, triggers=flags,
                    annotations=annotations,
                    next_trigger=next_trigger(case, snapshot, policy, flags),
                    changed=state != prev, reason=reason, eligible_accounts=eligible)


def session_decay(case: Mapping[str, Any], policy: Mapping[str, Any] | None = None) -> dict:
    """Is this case past the decay window? Digest-only, never auto-closed while materiality is T2 or worse."""
    policy = policy or DEFAULT_POLICY
    sessions = _num(case.get("sessions_since_trigger"))
    window = int(policy.get("decay_sessions") or 20)
    tier = str(case.get("materiality_tier") or "T3").upper()
    decayed = bool(sessions is not None and sessions >= window)
    return {"decayed": decayed, "digest_only": decayed,
            "auto_close": bool(decayed and tier == "T3"),
            "sessions_since_trigger": sessions, "decay_sessions": window, "materiality_tier": tier}


# ── the thin caller both evaluators share (piece A owns the store) ────────────────────────────────────────
def store_accessor(conn=None, policy: Mapping[str, Any] | None = None):
    """Piece A's case store, or None when this build does not carry it yet.

    Piece A owns the store (``lib.recovery_engine.cases.CaseStore``): ``list()`` / ``set_state(case_key, state)``.
    A missing store is reported by the callers as "recovery store not present", never as an empty store — an
    empty read and an absent store must not look the same.
    """
    if conn is None:
        return None
    try:
        from lib.recovery_engine.cases import CaseStore  # noqa: PLC0415
    except ImportError:
        return None
    try:
        return CaseStore(conn, policy or load_policy())
    except Exception:  # noqa: BLE001 — a store that cannot start is absent, and the caller says so
        return None


def run_pass(store, snapshot_for, *, policy: Mapping[str, Any] | None = None,
             now: datetime | None = None, dry_run: bool = True, limit: int = 200) -> dict:
    """Evaluate every open case once. Pure per case; the only write is piece A's ``update_state``.

    ``snapshot_for(case)`` returns the market fields (close, sma20, rsi, rsi_prev, stop_level,
    macd_up_sessions, catalyst_confidence, catalyst_sessions_ago, entry_high) or None. A snapshot that is
    missing leaves the case's state untouched and says why — this pass never guesses a price.
    """
    if store is None:
        return {"store": "absent", "considered": 0, "changed": 0, "decisions": []}
    policy = policy or load_policy()
    now = now or datetime.now(timezone.utc)
    try:
        if hasattr(store, "list_open"):
            cases = list(store.list_open(limit=limit) or [])
        else:
            cases = list(store.list() or [])
        cases = [c.to_dict() if hasattr(c, "to_dict") else dict(c) for c in cases]
    except Exception as exc:  # noqa: BLE001 — a broken store is reported, never rendered as "no cases"
        return {"store": "unreadable", "error": f"{type(exc).__name__}: {exc}", "considered": 0,
                "changed": 0, "decisions": []}
    decisions, changed = [], 0
    for case in cases:
        try:
            snapshot = snapshot_for(case) if snapshot_for else None
        except Exception as exc:  # noqa: BLE001
            snapshot = None
            decisions.append({"case_key": case.get("case_key"), "store_error": f"{type(exc).__name__}: {exc}"})
        decision = evaluate(case, snapshot, policy, now=now)
        row = {"case_key": case.get("case_key"), "symbol": case.get("symbol"),
               "snapshot": "present" if snapshot else "absent", **decision.as_dict()}
        decisions.append(row)
        if decision.changed:
            changed += 1
            if not dry_run:
                try:
                    if hasattr(store, "set_state"):
                        store.set_state(str(case.get("case_key")), decision.state)
                    else:
                        store.update_state(str(case.get("case_key")), state=decision.state,
                                           state_since=now.isoformat(), annotations=decision.annotations,
                                           confidence=round(decision.confidence, 4),
                                           next_trigger=decision.next_trigger)
                except Exception as exc:  # noqa: BLE001 — one case failing never stops the pass
                    row["write_error"] = f"{type(exc).__name__}: {exc}"
    return {"store": "ok", "considered": len(cases), "changed": changed, "decisions": decisions,
            "dry_run": bool(dry_run), "policy_source": policy.get("policy_source")}
