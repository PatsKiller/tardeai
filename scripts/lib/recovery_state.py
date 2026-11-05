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
* **Recovery is a reclaim, not a pullback.** R1/R2 are reclaim triggers (exit +1%, the stop that fired); R4 (SMA20
  reclaim) is the ready trigger. R3/R5 raise confidence and are *not* reclaims. Under the default weights they cannot
  reach `recovering_floor` on their own (0.10+0.15 = 0.25 < 0.30) — but that is arithmetic, not a guard: a policy that
  reweights them or lowers the floor will move a case to RECOVERING with no reclaim. When it does, the reason now says
  "without a reclaim", so the card never claims one fired. (This sentence used to claim they "can never advance a state
  on their own", which held only for the default numbers and was never enforced anywhere.)
"""
from __future__ import annotations

import contextlib
import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[2]

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
            if nested.endswith("_pct"):
                # Piece A's reviewed field NAMES the unit: ``r1_reclaim_exit_pct: 1.0`` means ONE PERCENT
                # (A computes exit*(1+pct/100)). The engine's internal unit is a fraction, so the loader
                # converts here — the silent 100x error codex's A->B probe found (2026-11-03) was a 1.0
                # loaded as 100% and a trivial residual made "fully held".
                try:
                    value = float(value) / 100.0
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(value):
                    continue  # an infinite threshold is not a reviewed rule
            elif flat in {"rsi_level", "macd_up_sessions", "catalyst_min_confidence",
                          "catalyst_max_sessions", "decay_sessions"}:
                # A malformed numeric threshold keeps the reviewed default instead of crashing or passing.
                number = _num(value)
                if number is None:
                    continue
                value = number
            merged[flat] = value
    if isinstance(conf.get("weights"), Mapping):
        validated: dict[str, float] = {}
        for key, raw in conf["weights"].items():
            number = _num(raw)
            if number is not None and number >= 0:
                validated[str(key).upper()] = number
        merged["weights"] = {**policy["weights"], **validated}
    for floor_key in ("ready_floor", "recovering_floor"):
        if conf.get(floor_key) is not None:
            number = _num(conf[floor_key])
            if number is not None:
                merged[floor_key] = number
    merged["policy_source"] = str(doc.get("schema") or "recovery_policy")
    return merged


def _num(value) -> float | None:
    """A finite number, or None. A boolean is NOT a number, and neither is infinity or NaN.

    ``float(True)`` is 1.0 and ``float("inf")`` passes every ``> threshold`` test, so accepting either let a
    malformed quote fire a reclaim trigger (cx-openai-3's F5 on #2557). Any value the caller cannot show on a
    screen as a real number comes back as ``None`` — unavailable, never a confident figure.
    """
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _price(value) -> float | None:
    """A finite, strictly positive price/reference. Zero, negative and non-finite are unavailable."""
    number = _num(value)
    return number if number is not None and number > 0 else None


def _int(value) -> int | None:
    """A finite whole number, or None. Rejects booleans, fractions and infinity rather than truncating them."""
    number = _num(value)
    if number is None or number != int(number):
        return None
    return int(number)


def _parse_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def exit_price(case: Mapping[str, Any]) -> float | None:
    """The exit price the recovery is measured against: the largest cluster exit, else the row's own field.

    Piece A's ``RecoveryCase.to_dict()`` names the fill price ``price`` inside ``exits`` (``ExitFill.price``);
    an older/looser row may carry ``exit_price`` there. Both are read so B consumes A's shape rather than
    asking A to rename a field for it.
    """
    direct = _price(case.get("exit_price") if case.get("exit_price") is not None else case.get("last_exit_price"))
    if direct is not None:
        return direct
    rows: Iterable[Any] = []
    for key in ("exits", "exits_json"):
        raw = case.get(key)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw or "[]")
            except ValueError:
                raw = []
        if isinstance(raw, (list, tuple)):
            rows = raw
            break
    # Piece A's canonical reference is the FINAL exit: its ``reclaim_exit_trigger`` compares against
    # ``case.exits[-1].price``. B used the MAX cluster exit, so with exits 120 then 100 the two sides
    # disagreed at any price between them (codex A->B probe, 2026-11-03). Follow the owner's semantics:
    # the last exit in the row's own chronological order, falling back to the latest by date, and only
    # then to any usable price.
    usable = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        price = _price(row.get("exit_price")) if row.get("exit_price") is not None else _price(row.get("price"))
        if price is None:
            continue
        when = row.get("exit_date") or row.get("date")
        usable.append((index, when, price))
    if not usable:
        return None
    dates = [w for _i, w, _p in usable if w]
    if len(dates) == len(usable):
        ordered = sorted(usable, key=lambda item: (str(item[1]), item[0]))
        return ordered[-1][2]
    return usable[-1][2]


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


def _unknown_eligibility(detail: str) -> dict[str, Any]:
    """One account whose eligibility could not be established. Explicitly unknown, never a quiet default."""
    return {"eligible": None, "unknown": True, "detail": detail, "until": None, "gate": "eligibility_unknown",
            "would_change_it": "piece A supplies a valid eligibility row (a boolean eligible and a parseable, "
                               "non-contradictory eligible_from)",
            "pending_operator_decision": False}


def _normalise_eligibility_row(value, *, now: datetime) -> dict[str, Any]:
    """Validate ``eligible`` and ``eligible_from`` as ONE contract.

    A boolean is the only answer ``eligible`` may carry: ``bool("false")`` is True, so a string is malformed,
    not false. The date must parse, and the pair must agree — ``eligible=True`` with a future date, or
    ``eligible=False`` with a date already passed, is internally contradictory. Every such row is explicit
    unknown; readiness is withheld, while the recovery evidence stays visible on the card (F4 on #2557).
    """
    if isinstance(value, bool):
        row: dict[str, Any] = {"eligible": value}
    elif isinstance(value, Mapping):
        row = dict(value)
    else:
        return _unknown_eligibility(f"eligibility value {value!r} is neither a boolean nor an object")
    if "eligible" not in row:
        return _unknown_eligibility("the eligibility row does not say whether the account is eligible")
    eligible = row.get("eligible")
    if not isinstance(eligible, bool):
        return _unknown_eligibility(f"eligible={eligible!r} is not a boolean")
    raw_until = row.get("eligible_from")
    if raw_until is None or raw_until == "":
        raw_until = row.get("until")
    until_text = None
    until_dt = None
    if raw_until is not None and raw_until != "":
        until_dt = _parse_dt(raw_until)
        if until_dt is None:
            return _unknown_eligibility(f"eligible_from={raw_until!r} is not a date")
        until_text = str(raw_until)
    if eligible and until_dt is not None and until_dt.date() > now.date():
        return _unknown_eligibility(f"eligible=true but eligible_from={until_text} is in the future; "
                                    "the row contradicts itself")
    if not eligible and until_dt is not None and until_dt.date() <= now.date():
        return _unknown_eligibility(f"eligible=false but eligible_from={until_text} has already passed; "
                                    "the row contradicts itself")
    return {
        "eligible": eligible,
        "unknown": False,
        "detail": None,
        "until": until_text,
        "gate": str(row.get("gate") or ("pending_operator_decision" if eligible else "house_hold")),
        "would_change_it": str(row.get("would_change_it") or row.get("reason")
                               or (f"the date {until_text} is reached" if until_text else "the hold is lifted")),
        "pending_operator_decision": bool(row.get("pending_operator_decision")),
    }


def _eligibility(case: Mapping[str, Any], *, now: datetime | None = None) -> dict[Any, dict[str, Any]]:
    """Piece A emits ``[{account, eligible, eligible_from, reason}]``; an older mapping is accepted too.

    Every row is normalised through the same contract. An unreadable blob is no rows — which the caller already
    renders as ``eligibility_unknown`` — never an implicit pass.
    """
    now = now or datetime.now(timezone.utc)
    raw = case.get("eligibility_json")
    if raw is None or raw == "":
        raw = case.get("eligibility")
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    if isinstance(raw, Mapping):
        rows: dict[Any, dict[str, Any]] = {}
        for account, value in raw.items():
            name = str(account).strip() if account is not None else ""
            rows[name or None] = _normalise_eligibility_row(value, now=now)
        return rows
    if isinstance(raw, (list, tuple)):
        rows = {}
        unattributed = False
        for item in raw:
            if not isinstance(item, Mapping) or not str(item.get("account") or "").strip():
                unattributed = True
                continue
            rows[str(item["account"]).strip()] = _normalise_eligibility_row(item, now=now)
        if unattributed:
            rows[None] = _unknown_eligibility("an eligibility row does not name its account")
        return rows
    return {}


def gate_annotations(case: Mapping[str, Any], snapshot: Mapping[str, Any], policy: Mapping[str, Any],
                     now: datetime) -> list[dict]:
    """Every caveat as an annotation with a *when* and a *what would change it* — never a silencer.

    ``blocks_ready`` is True only when the caveat removes the last eligible account; every other caveat is
    information the operator should see beside the recovery ("RSI 39.1 — a close above 40 lifts it").
    """
    out: list[dict] = []
    elig = _eligibility(case, now=now)

    # Per-account eligibility: wash sale / house hold with an explicit date.
    for account, row in sorted(elig.items(), key=lambda item: str(item[0])):
        if row.get("unknown"):
            # Malformed or self-contradictory: say unknown, block readiness, never read as an eligible account.
            out.append({"gate": "eligibility_unknown", "account": account, "until": None,
                        "detail": str(row.get("detail") or "eligibility unknown"),
                        "would_change_it": str(row.get("would_change_it") or "a valid eligibility row"),
                        "blocks_ready": True})
            continue
        if row.get("eligible") is True:
            # The date gate is open; whether to re-enter is the operator's call, so the card says that and
            # never turns an open gate into a recommendation.
            out.append({"gate": "pending_operator_decision", "account": account, "until": None,
                        "would_change_it": "your decision on the recovery card",
                        "blocks_ready": False})
            continue
        out.append({
            "gate": str(row.get("gate") or "house_hold"),
            "account": account,
            "until": row.get("until"),
            "would_change_it": str(row.get("would_change_it")
                                   or (f"the date {row.get('until')} is reached" if row.get("until")
                                       else "the hold is lifted")),
            "blocks_ready": False,  # recomputed below, once we know whether ANY account is date-open
        })
    any_eligible = any(r.get("eligible") is True and not r.get("unknown") for r in elig.values())
    if not elig:
        # Missing data is not a pass. Without the account split the engine cannot know whether an account is
        # inside a house hold, so it cannot honestly say "ready" — the case still shows, the card still appears.
        out.append({"gate": "eligibility_unknown", "account": None, "until": None,
                    "detail": "eligibility unknown — nothing to re-enter until the account split exists",
                    "would_change_it": "piece A supplies the account eligibility",
                    "blocks_ready": True})
    elif not any_eligible:
        for row in out:
            row["blocks_ready"] = True

    # Residual: shown, never used to suppress (operator ruling 2026-11-03).
    fact = residual_fact(case)
    if fact:
        out.append(fact)

    # The entry zone: a price above it is not a blocker, only a stale plan to re-derive.
    plan = case.get("plan_json") if isinstance(case.get("plan_json"), Mapping) else {}
    zone_high = _price(snapshot.get("entry_high") if snapshot.get("entry_high") is not None
                       else (plan or {}).get("entry_high"))
    close = _price(snapshot.get("close"))
    if zone_high is not None and close is not None and close > zone_high:
        out.append({"gate": "above_entry_zone", "account": None, "until": None,
                    "would_change_it": f"a pullback to {zone_high:.2f} or a re-derived zone",
                    "blocks_ready": False})

    # RSI: below the level is information, never a blocker while the reclaim triggers are firing.
    rsi = _num(snapshot.get("rsi"))
    rsi_level = _num(policy.get("rsi_level"))
    rsi_level = 40.0 if rsi_level is None else rsi_level
    if rsi is not None and rsi < rsi_level:
        out.append({"gate": "rsi_below_level", "account": None, "until": None,
                    "would_change_it": f"RSI crosses up through {rsi_level:.0f}",
                    "blocks_ready": False})
    return out


def _trigger_flags(case: Mapping[str, Any], snapshot: Mapping[str, Any], policy: Mapping[str, Any]) -> dict:
    """Only finite, positive market numbers may fire a trigger.

    A price of ``inf`` used to satisfy every ``>=`` test and manufacture a reclaim (F5 on #2557). Prices and
    references go through ``_price``, counts through ``_int``, and a field that is present but unusable is
    treated as UNAVAILABLE — its trigger does not fire — rather than silently repaired to a passing value.
    """
    close = _price(snapshot.get("close"))
    ep = exit_price(case)
    raw_stop = snapshot.get("stop_level") if snapshot.get("stop_level") is not None else case.get("stop_level")
    stop = _price(raw_stop)
    sma20 = _price(snapshot.get("sma20"))
    rsi = _num(snapshot.get("rsi"))
    raw_rsi_prev = snapshot.get("rsi_prev")
    rsi_prev = _num(raw_rsi_prev)
    macd_up = _int(snapshot.get("macd_up_sessions"))
    catalyst_conf = _num(snapshot.get("catalyst_confidence"))
    catalyst_conf = 0.0 if catalyst_conf is None else catalyst_conf
    raw_age = snapshot.get("catalyst_sessions_ago")
    catalyst_age = _int(raw_age)

    reclaim_pct = _num(policy.get("reclaim_exit_pct"))
    reclaim_pct = 0.01 if reclaim_pct is None else reclaim_pct
    rsi_level = _num(policy.get("rsi_level"))
    rsi_level = 40.0 if rsi_level is None else rsi_level
    macd_needed = _int(policy.get("macd_up_sessions"))
    macd_needed = 2 if macd_needed is None else macd_needed
    catalyst_min = _num(policy.get("catalyst_min_confidence"))
    catalyst_min = 0.8 if catalyst_min is None else catalyst_min
    catalyst_window = _int(policy.get("catalyst_max_sessions"))
    catalyst_window = 5 if catalyst_window is None else catalyst_window

    reclaim_exit = bool(close is not None and ep is not None and close >= ep * (1.0 + reclaim_pct))
    # Only an explicit True enables R2; a malformed policy value must not manufacture a reclaim.
    reclaim_stop = bool(policy.get("stop_reclaim_enabled", True) is True
                        and close is not None and stop is not None and close >= stop)
    # A missing previous RSI is "first observation" (a cross may fire). A PRESENT but unusable previous RSI
    # means the direction is unknown, so no cross is claimed.
    prev_known_below = raw_rsi_prev is None or raw_rsi_prev == "" or (
        rsi_prev is not None and rsi_prev < rsi_level)
    rsi_cross = bool(rsi is not None and rsi >= rsi_level and prev_known_below)
    momentum = bool(rsi_cross or (macd_up is not None and macd_up >= macd_needed))
    sma_reclaim = bool(close is not None and sma20 is not None and close >= sma20)
    age_usable = raw_age is None or raw_age == "" or (
        catalyst_age is not None and catalyst_age <= catalyst_window)
    catalyst = bool(catalyst_conf >= catalyst_min and age_usable)
    return {"R1": reclaim_exit, "R2": reclaim_stop, "R3": momentum, "R4": sma_reclaim, "R5": catalyst}


def next_trigger(case: Mapping[str, Any], snapshot: Mapping[str, Any], policy: Mapping[str, Any],
                 flags: Mapping[str, bool]) -> str:
    """The one line the operator's card shows for what would change the answer."""
    if flags.get("R4"):
        return "already reclaiming the 20-day mean; confirm eligibility"
    sma20 = _price(snapshot.get("sma20"))
    close = _price(snapshot.get("close"))
    ep = exit_price(case)
    reclaim_pct = _num(policy.get("reclaim_exit_pct"))
    reclaim_pct = 0.01 if reclaim_pct is None else reclaim_pct
    if not flags.get("R1") and ep is not None and close is not None:
        return f"a close at {ep * (1.0 + reclaim_pct):.2f} reclaims the exit"
    if sma20 is not None:
        return f"a close at {sma20:.2f} reclaims the 20-day mean"
    if not flags.get("R3"):
        rsi_level = _num(policy.get("rsi_level"))
        rsi_level = 40.0 if rsi_level is None else rsi_level
        return f"RSI crossing up through {rsi_level:.0f}"
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


def _quote_problem(snapshot: Mapping[str, Any] | None) -> str | None:
    """Why the snapshot cannot support trigger evaluation, or None when its close is a usable price.

    Only ``close`` is mandatory; an optional field that is absent or unusable simply cannot fire its trigger.
    """
    if not isinstance(snapshot, Mapping):
        return "snapshot is not an object"
    raw_close = snapshot.get("close")
    if _price(raw_close) is None:
        return f"close={raw_close!r} is not a finite positive number"
    return None


def _weight(value) -> float:
    """A confidence weight; a malformed or non-finite weight contributes nothing, never NaN confidence."""
    number = _num(value)
    if number is None or number < 0:
        return 0.0
    return number


def _floor(value, default: float) -> float:
    """A policy floor. Zero is a real floor, not an absent one; a malformed value keeps the reviewed default."""
    number = _num(value)
    return default if number is None else number


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
    freshness, session = snapshot_freshness(snapshot, now=now)
    if freshness not in FRESH_QUOTE_STATES:
        # The guard runs on the guard's own terms, before any trigger sees the price.
        return Decision(state=prev, previous_state=prev, confidence=0.0,
                        reason=f"quote not current ({freshness}{', ' + str(session) if session else ''}); "
                               "a stale or unattributed price cannot move a case")
    quote_problem = _quote_problem(snapshot)
    if quote_problem:
        # A fresh timestamp on a number that is not a price (inf, NaN, a boolean, zero, missing) establishes
        # nothing: refuse to evaluate triggers and say exactly which input was unusable (F5 on #2557).
        return Decision(state=prev, previous_state=prev, confidence=0.0,
                        reason=f"market input unavailable ({quote_problem}); state unchanged, no trigger evaluated")

    flags = _trigger_flags(case, snapshot, policy)
    weights = policy.get("weights") if isinstance(policy.get("weights"), Mapping) else DEFAULT_POLICY["weights"]
    confidence = min(1.0, sum(_weight(weights.get(k)) for k, fired in flags.items() if fired))
    annotations = gate_annotations(case, snapshot, policy, now)
    # A date-open account is required for readiness; ``pending_operator_decision`` rows are date-open but the card
    # still says "pending your decision" — the engine reports the split, it never answers whether to re-enter.
    # A malformed or contradictory row never becomes an eligible account (F4 on #2557).
    eligible = [a for a, r in _eligibility(case, now=now).items()
                if a is not None and r.get("eligible") is True and not r.get("unknown")]
    blocked = any(a.get("blocks_ready") for a in annotations)
    ready_floor = _floor(policy.get("ready_floor"), 0.55)
    recovering_floor = _floor(policy.get("recovering_floor"), 0.30)

    reclaim = flags["R1"] or flags["R2"] or flags["R4"]
    if flags["R4"] and confidence >= ready_floor and eligible and not blocked:
        state, reason = RE_ENTRY_READY, "reclaims the 20-day mean with confidence over the floor"
    elif reclaim and confidence >= recovering_floor:
        # A reclaim is shown even when eligibility is unknown or every date gate is shut: the case still shows.
        # The reason names what actually fired, so the card cannot claim a reclaim that did not happen.
        which = "+".join(k for k in ("R1", "R2", "R4") if flags[k])
        state, reason = RECOVERING, f"a reclaim fired ({which}); confidence {confidence:.2f}"
    elif confidence >= recovering_floor:
        # R3/R5 raise confidence but are not reclaims. Reaching RECOVERING on confidence alone is allowed — the
        # card still has to show the case — but the sentence must not assert a reclaim that never fired.
        state, reason = RECOVERING, f"confidence {confidence:.2f} crossed the floor without a reclaim"
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
    window = _int(policy.get("decay_sessions"))
    window = 20 if window is None else window
    tier = str(case.get("materiality_tier") or "T3").upper()
    decayed = bool(sessions is not None and sessions >= window)
    return {"decayed": decayed, "digest_only": decayed,
            "auto_close": bool(decayed and tier == "T3"),
            "sessions_since_trigger": sessions, "decay_sessions": window, "materiality_tier": tier}


# ── the thin caller both evaluators share (piece A owns the store) ────────────────────────────────────────
def store_accessor(conn=None, policy: Mapping[str, Any] | None = None):
    """Piece A's case store, or None when this build does not carry it yet.

    Piece A owns the store (``lib.recovery_engine.cases.CaseStore``): ``list()`` and a compare-and-set
    ``set_state(case_key, state, expect={"state", "operator_decision"})``. The expectations are the row the pass
    READ; a store that cannot express them is refused rather than written unconditionally (F1 on #2557).
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


# ── the market inputs both scheduled adapters assemble ────────────────────────────────────────────────────
def technical_symbols(rows) -> list[str]:
    """The upper-case symbols in a store listing, for ONE batch technical read."""
    out = []
    for row in rows or []:
        if hasattr(row, "to_dict"):
            row = row.to_dict()
        try:
            symbol = str(row.get("symbol") or "").upper().strip()
        except AttributeError:
            continue
        if symbol and symbol not in out:
            out.append(symbol)
    return sorted(out)


def technical_inputs(symbols) -> dict[str, dict]:
    """The registered technical projection for these symbols, keyed by upper-case symbol.

    ``market_quotes`` is an append-only QUOTE ledger: its one writer
    (``scripts/lib/writers/market_quotes_writer.py``) accepts no ``sma20``/``sma_20`` column, so R4 — the SMA20
    reclaim, the only trigger that can make a case RE_ENTRY_READY — could never fire while both scheduled
    adapters searched that row for the level. The level comes from its registered projection instead: data-broker
    catalog id ``indicator_snapshot`` (domain ``technicals``), per ``AGENTS.md`` §24.3.

    ONE batch call, so a pass does not rebuild (and overwrite) the projection's shared cache once per case. A
    projection that is absent or unreadable is an empty map: R4 stays unfired, never guessed. Only a field whose
    trigger semantics the projection can honestly support is exposed; RSI is not copied because R3 is a CROSS
    through the level and a level with no previous reading would manufacture a cross on every pass.
    """
    wanted: list[str] = []
    for value in symbols or []:
        symbol = str(value or "").upper().strip()
        if symbol and symbol not in wanted:
            wanted.append(symbol)
    wanted.sort()
    if not wanted:
        return {}
    try:
        from lib.data_broker.indicator_snapshot import get_indicator_snapshot  # noqa: PLC0415
    except ImportError:
        try:
            from scripts.lib.data_broker.indicator_snapshot import (  # type: ignore[no-redef]  # noqa: PLC0415
                get_indicator_snapshot,
            )
        except ImportError:
            return {}
    try:
        snapshot = get_indicator_snapshot(wanted) or {}
    except Exception:  # noqa: BLE001 — a broken projection is an absent input, not a pass-through failure
        return {}
    by_symbol = snapshot.get("by_symbol") if isinstance(snapshot, Mapping) else None
    if not isinstance(by_symbol, Mapping):
        return {}
    return {str(key).upper(): value for key, value in by_symbol.items() if isinstance(value, Mapping)}


def quote_snapshot(quote_row: Mapping[str, Any] | None, technical: Mapping[str, Any] | None = None) -> dict | None:
    """The snapshot the state machine consumes: the quote's close, its OWN timestamp, plus the projection's SMA20.

    Only the close is required; a row without a usable price returns None so the state machine leaves the case
    untouched and says why, rather than inventing a price. The timestamp travels with the price because the
    engine refuses a price of unknown or stale age.
    """
    if not isinstance(quote_row, Mapping):
        return None
    raw_close = quote_row.get("price")
    if raw_close in (None, ""):
        raw_close = quote_row.get("close")   # legacy rows name the last price ``close``
    close = _price(raw_close)
    if close is None:
        return None
    snap: dict[str, Any] = {"close": close, "fetched_at": quote_row.get("fetched_at")}
    if isinstance(technical, Mapping):
        sma20 = _price(technical.get("sma_20"))
        if sma20 is not None:
            snap["sma20"] = sma20
    return snap


#: Quote freshness states the engine will act on. ``derive_freshness`` (scripts/lib/watch_canonical_quote.py) is
#: the existing, session-aware authority: RTH is tight, premarket/afterhours have their own windows, a closed
#: market holds the last print for a bounded time. Anything else — including a snapshot with NO fetch time — is
#: not current, and a price of unknown age must not move a case (codex's scheduled stale-quote BLOCK, 2026-11-03:
#: the guard existed, and the snapshot threw its input away).
FRESH_QUOTE_STATES = frozenset({"CURRENT", "PREMARKET_CURRENT", "AFTER_HOURS_CURRENT"})


def snapshot_freshness(snapshot: Mapping[str, Any] | None, *, now: datetime | None = None) -> tuple[str, str | None]:
    """(state, session) for a snapshot's quote. Missing provenance is NOT fresh.

    Delegates to the one freshness authority so the recovery lane cannot disagree with the alert lane about
    what "current" means. An unavailable helper fails closed (UNVERIFIED).
    """
    if not isinstance(snapshot, Mapping):
        return "DATA_UNAVAILABLE", None
    fetched = snapshot.get("fetched_at") or snapshot.get("quote_at") or snapshot.get("as_of")
    if not fetched:
        return "DATA_UNAVAILABLE", None
    try:
        from lib.watch_canonical_quote import derive_freshness  # noqa: PLC0415
    except ImportError:
        try:
            from scripts.lib.watch_canonical_quote import derive_freshness  # noqa: PLC0415
        except ImportError:
            return "UNVERIFIED", None
    try:
        return derive_freshness(fetched, now=now)
    except Exception:  # noqa: BLE001 — an unreadable timestamp is not a fresh one
        return "DATA_UNAVAILABLE", None


#: States that are worth telling the operator about. A transition INTO one of these hands the case to
#: piece C; a case that merely stays there is not re-handed (C's own floor and per-case/day bound also apply).
PAGING_STATES = (RECOVERING, RE_ENTRY_READY)


PENDING_REL = Path("data") / "runtime" / "recovery_notify_pending.json"


def _pending_path() -> Path:
    """Durable record of a paging transition whose delivery has not been confirmed.

    A failed send used to be lost: the state advanced to RECOVERING, the next pass saw no change, and C was
    never called again (codex's failure probe, 2026-11-03). Pending work survives across scheduled passes
    until it is delivered or C says the tier is not pageable.
    """
    try:
        from lib.persistent_state_root import resolve_durable_dir  # noqa: PLC0415
        return resolve_durable_dir(str(PENDING_REL), PROJECT_ROOT)
    except Exception:  # noqa: BLE001
        return PROJECT_ROOT / PENDING_REL


def _read_pending(target: str | Path) -> dict:
    """Read the queue strictly. A missing file is empty; an unreadable one raises instead of reading as empty.

    Reading a corrupt queue as ``{}`` is how a retry responsibility disappears: the next write would replace the
    file with only the keys this pass knows about. The caller refuses the transition instead (F2 on #2557).
    """
    path = Path(target)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"pending store {path} is unreadable: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"pending store {path} is not an object")
    return doc


def load_pending(path: str | Path | None = None) -> dict:
    """Best-effort read for the retry check. An unreadable file reads as empty HERE; every WRITE is strict."""
    try:
        return _read_pending(path or _pending_path())
    except (OSError, ValueError):
        return {}


@contextlib.contextmanager
def _pending_lock(target: str | Path):
    """Serialise the read-merge-replace so two overlapping evaluators cannot clobber each other's entries."""
    lock_path = Path(str(target) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+", encoding="utf-8")  # noqa: SIM115 — closed in the finally block
    fcntl = None
    try:
        try:
            import fcntl as _fcntl  # noqa: PLC0415 — POSIX only; the lock is an optimisation there
            fcntl = _fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except ImportError:
            fcntl = None
        yield
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def save_pending(doc: Mapping[str, Any], path: str | Path | None = None) -> None:
    """Atomically replace the queue. Faults PROPAGATE: a silent failure is a lost page (F2 on #2557)."""
    target = Path(path or _pending_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(doc), indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, target)


def merge_pending(updates: Mapping[str, Any], path: str | Path | None = None) -> dict:
    """Apply single-key updates under an exclusive lock, re-reading the queue first.

    ``None`` deletes a key. Returns the merged document. Raises OSError/ValueError when the responsibility
    cannot be recorded — the caller must not pretend it was.
    """
    target = Path(path or _pending_path())
    with _pending_lock(target):
        doc = _read_pending(target)
        for key, value in updates.items():
            if value is None:
                doc.pop(key, None)
            else:
                doc[key] = value
        save_pending(doc, target)
        return doc


def _delivery_confirmed(result: Mapping[str, Any] | None) -> bool:
    """Did this handoff end the need for a retry?

    ``sent: true`` is delivery. ``deduped_by_floor`` means C's own ledger says this page already reached the
    operator. A T2/T3 refusal ("not T1 …") is C's decision that the tier is not pageable — not a failure. A
    bare ``sent: false`` (transport refused) is NOT confirmed and must stay pending.
    """
    if not isinstance(result, Mapping):
        return False
    if result.get("sent") is True or result.get("deduped_by_floor"):
        return True
    reason = str(result.get("reason") or "")
    return reason.startswith("not T1")


def _default_notify():
    """Piece C's notifier, loaded lazily so B stays importable without it."""
    try:
        from lib.recovery_notify import notify_recovery_case  # noqa: PLC0415
    except ImportError:
        try:
            from scripts.lib.recovery_notify import notify_recovery_case  # noqa: PLC0415
        except ImportError:
            return None
    return notify_recovery_case


PENDING_ERRORS = (OSError, ValueError)


def _cas_write(store, case: Mapping[str, Any], decision: Decision, now: datetime) -> tuple[bool, str, str | None]:
    """Compare-and-set at the durable store boundary: (applied, status, refusal).

    The expectations are the state, operator decision and (when the row carries one) version this pass READ. A
    store that cannot express them is refused — never written unconditionally, which is exactly how a decision
    taken after ``list()`` was overwritten and paged (F1 on #2557).
    """
    key = str(case.get("case_key"))
    expect: dict[str, Any] = {
        "state": str(case.get("state") or STOPPED_OUT).upper(),
        "operator_decision": str(case.get("operator_decision") or "none"),
    }
    version = case.get("version", case.get("row_version"))
    if version is not None and version != "":
        expect["version"] = version
    setter = getattr(store, "set_state", None)
    if not callable(setter):
        return False, "cas_unsupported", "store exposes no compare-and-set set_state"
    try:
        result = setter(key, decision.state, expect=expect)
    except TypeError as exc:
        return False, "cas_unsupported", (
            f"store set_state cannot express expected state/operator_decision/version "
            f"({type(exc).__name__}: {exc}); refusing an unconditional write")
    except Exception as exc:  # noqa: BLE001 — one case failing never stops the pass
        return False, "write_error", f"{type(exc).__name__}: {exc}"
    if isinstance(result, tuple) and result:
        applied = result[0] == 1 if isinstance(result[0], int) else bool(result[0])
        refusal = str(result[1]) if len(result) > 1 and result[1] is not None else None
        return applied, ("applied" if applied else "cas_miss"), (None if applied else (refusal or "state_changed"))
    if result is True:
        return True, "applied", None
    if result is False or result == 0:
        return False, "cas_miss", "refused"
    return False, "cas_unconfirmed", (
        f"store returned {type(result).__name__}, not an applied/refused verdict; responsibility retained")


#: Operator decisions that settle a pending page even when the row's ``state`` column lags behind them.
OPERATOR_DECISION_STATES = frozenset({"closed", "snoozed", "re-entered", "reentered"})


def _dispatch_gate(case: Mapping[str, Any], snapshot: Mapping[str, Any] | None, decision: Decision,
                   now: datetime, pageable: tuple[str, ...] = PAGING_STATES) -> tuple[bool, str, bool]:
    """The last check before piece C: (send, reason, settle_pending).

    Applied to RETRIES as well as new transitions (F3 on #2557). An operator-held case never pages and its
    obligation is settled; a non-pageable state settles a stale obligation; a quote that is not current, or
    whose close is not a usable price, does not page and KEEPS the obligation, so it survives honestly until a
    usable quote exists. ``evaluate()`` already refuses such a close; without the same test here a pending
    retry paged on ``inf``/NaN/zero/missing data and cleared the obligation (cx-cloud CX2 on #2557).
    """
    operator_decision = str(case.get("operator_decision") or "none").strip().lower()
    if decision.state in OPERATOR_STATES or operator_decision in OPERATOR_DECISION_STATES:
        return False, "operator decision holds; not paging", True
    if decision.state not in tuple(pageable):
        return False, f"state {decision.state} is not pageable; pending obligation settled", True
    freshness, session = snapshot_freshness(snapshot, now=now)
    if freshness not in FRESH_QUOTE_STATES:
        suffix = f", {session}" if session else ""
        return False, (f"quote not current ({freshness}{suffix}); retry responsibility retained until a usable "
                       "quote exists"), False
    quote_problem = _quote_problem(snapshot)
    if quote_problem:
        return False, (f"market input unavailable ({quote_problem}); retry responsibility retained until a usable "
                       "price supports evaluation"), False
    return True, "", False


def _as_case_dict(row) -> dict | None:
    """One store row as a plain dict, or None when it cannot be read as one."""
    if row is None:
        return None
    if hasattr(row, "to_dict"):
        try:
            row = row.to_dict()
        except Exception:  # noqa: BLE001 — an unreadable row is reported as unreadable, never guessed
            return None
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _reread_durable(store, case: Mapping[str, Any], *, limit: int = 200) -> tuple[dict | None, str | None]:
    """Re-read this case's DURABLE row at dispatch time: ``(row, None)`` or ``(None, problem)``.

    The row the pass listed is a detached object; an operator decision taken after ``list()`` never reaches it.
    ``evaluate()`` already refuses a held case, but a retry of an unchanged RECOVERING case runs no
    compare-and-set, so the held row was paged from the stale copy (cx-cloud CX3 on #2557). A store getter is
    preferred; otherwise the pass's own listing is re-read. ``(None, None)`` means the store no longer carries
    the case at all — an open-only listing omits a closed/snoozed row, and either way there is nothing to page.

    ``(None, reason)`` means the row could not be re-read: the caller must not page and must KEEP the retry
    responsibility, so an unreadable store never silently drops a page.
    """
    key = str(case.get("case_key") or "").strip()
    if not key:
        return None, "the case carries no case_key, so its durable row cannot be re-read"
    getter = getattr(store, "get", None)
    if callable(getter):
        try:
            row = getter(key)
        except TypeError:
            pass  # a getter this module cannot call: fall through to the listing the pass itself used
        except Exception as exc:  # noqa: BLE001 — reported as unreadable, never as "no row"
            return None, f"{type(exc).__name__}: {exc}"
        else:
            return _as_case_dict(row), None
    try:
        if hasattr(store, "list_open"):
            rows = store.list_open(limit=limit)
        else:
            rows = store.list()
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"
    for row in rows or []:
        current = _as_case_dict(row)
        if current is not None and str(current.get("case_key") or "") == key:
            return current, None
    return None, None


def _durable_moved(case: Mapping[str, Any], durable: Mapping[str, Any], decision: Decision,
                   state_written: bool) -> bool:
    """Did the row move between the listing and dispatch, beyond the state this pass itself wrote?

    Only the state and the operator decision can invalidate a page; a version/residual/plan change cannot.
    When this pass's compare-and-set applied, its own new state is the expected one.
    """
    expected_state = str(decision.state).upper() if state_written else str(case.get("state") or STOPPED_OUT).upper()
    if str(durable.get("state") or STOPPED_OUT).upper() != expected_state:
        return True

    def _operator_decision(row: Mapping[str, Any]) -> str:
        return str(row.get("operator_decision") or "none").strip().lower()

    return _operator_decision(durable) != _operator_decision(case)


def _drop_pending(key: str, pending_path, row: dict, pending: dict) -> None:
    """Remove one obligation under the lock. A failed removal stays visible and the entry stays in memory."""
    try:
        merge_pending({key: None}, pending_path)
        pending.pop(key, None)
    except PENDING_ERRORS as exc:
        row["pending_store_error"] = f"{type(exc).__name__}: {exc}"


def run_pass(store, snapshot_for, *, policy: Mapping[str, Any] | None = None,
             now: datetime | None = None, dry_run: bool = True, limit: int = 200,
             notify=None, notify_states: tuple[str, ...] = PAGING_STATES,
             pending_path: str | Path | None = None) -> dict:
    """Evaluate every open case once: write the state change AND hand a paging transition to piece C.

    ``snapshot_for(case)`` returns the market fields (close, sma20, rsi, rsi_prev, stop_level,
    macd_up_sessions, catalyst_confidence, catalyst_sessions_ago, entry_high) or None. A snapshot that is
    missing leaves the case's state untouched and says why — this pass never guesses a price.

    ``notify`` is piece C's ``notify_recovery_case`` by default. This is the PRODUCTION handoff: codex's
    scheduled-shape probe (2026-11-03) found the pass wrote a T1 RECOVERING case and made **zero** notifier
    calls — a case that exists and never pages is the exact failure the row exists to fix.

    The order is deliberate (F2 on #2557):

    1. **Persist the retry responsibility** for a paging transition, durably and under a lock, BEFORE the state
       write makes the transition invisible. If it cannot be persisted, the state is not advanced, so the
       transition stays visible and the next pass tries again.
    2. **Compare-and-set the state** against the row this pass read. A miss changes nothing and pages nothing.
    3. **Revalidate at dispatch** — re-read the DURABLE row, then check operator decision, quote freshness and
       the usability of the close — for retries as well as transitions.
    4. **Send, then clear** the obligation on confirmed delivery; a failure keeps it for the next pass.
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
    notifier = notify if notify is not None else _default_notify()
    pending = load_pending(pending_path)
    decisions, changed, attempted, notifier_calls, pending_errors = [], 0, 0, 0, 0
    for case in cases:
        try:
            snapshot = snapshot_for(case) if snapshot_for else None
        except Exception as exc:  # noqa: BLE001
            snapshot = None
            decisions.append({"case_key": case.get("case_key"), "store_error": f"{type(exc).__name__}: {exc}"})
        decision = evaluate(case, snapshot, policy, now=now)
        row = {"case_key": case.get("case_key"), "symbol": case.get("symbol"),
               "snapshot": "present" if snapshot else "absent", **decision.as_dict(),
               # Read-only: reports the decay window on the row. It never closes a case, and materiality T2 or
               # worse keeps it digest-only. Without this the rule was tested and called by nothing, which is
               # how a documented policy quietly stops being a policy.
               "decay": session_decay(case, policy)}
        decisions.append(row)
        key = str(case.get("case_key"))
        # Lead contract (2026-11-03): notify on a TRANSITION into a paging state, or to retry pending work.
        # A case that merely stays RECOVERING is not re-handed on every pass — C's day bound is the backstop,
        # not the reason to call it.
        wants_page = bool(decision.changed and decision.state in tuple(notify_states))
        retrying = key in pending
        write_ok = True
        state_written = False

        # (1) Retry responsibility is durable BEFORE the state change can hide the transition.
        responsibility_ok = True
        if not dry_run and wants_page:
            entry = {"first_failed_at": now.isoformat(), "attempts": 0, "state": decision.state,
                     "last_error": None}
            try:
                merge_pending({key: entry}, pending_path)
                pending[key] = entry
            except PENDING_ERRORS as exc:
                responsibility_ok = False
                pending_errors += 1
                row["pending_store_error"] = f"{type(exc).__name__}: {exc}"

        # (2) Compare-and-set the state against the row this pass read.
        if decision.changed:
            attempted += 1
            if dry_run:
                changed += 1
            elif not responsibility_ok:
                write_ok = False
                row["write_error"] = "retry responsibility could not be persisted; state not advanced"
                row["notify"] = {"sent": False, "reason": "pending store failed; transition left visible and "
                                                          "not written"}
            else:
                applied, status, refusal = _cas_write(store, case, decision, now)
                if applied:
                    changed += 1
                    state_written = True
                else:
                    write_ok = False
                    row["write_error"] = refusal or status
                    row["cas"] = {"status": status, "refusal": refusal}

        # (3) Dispatch gate — revalidated for retries as well as new transitions.
        if not (wants_page or retrying):
            continue
        if not write_ok:
            # The transition is not durable. Do not page it; any responsibility persisted above is revalidated
            # on the next pass (it is settled by the gate if the case did not actually advance).
            if key in pending:
                row["notify_pending"] = True
            row["notify"] = {"sent": False, "reason": f"state write did not apply ({row.get('write_error')}); "
                                                      "not notifying"}
            continue
        # (3) Re-read the DURABLE row: the gate must judge the operator's current decision, not the detached
        # case this pass listed. An unreadable store keeps the obligation; a row that moved for any reason this
        # pass did not itself write defers to the next pass rather than paging a stale decision.
        durable, reread_problem = _reread_durable(store, case, limit=limit)
        if reread_problem:
            if key in pending:
                row["notify_pending"] = True
            row["notify"] = {"sent": False,
                             "reason": f"durable case could not be re-read ({reread_problem}); no page and the "
                                       "retry responsibility is retained"}
            continue
        if durable is None:
            # The store no longer carries this case (a closed/snoozed row drops out of an open-only listing):
            # there is nothing left to page, so the obligation settles here.
            if not dry_run:
                _drop_pending(key, pending_path, row, pending)
            row["notify"] = {"sent": False,
                             "reason": "the case is no longer in the durable store; pending obligation settled"}
            continue
        send, gate_reason, settle = _dispatch_gate(durable, snapshot, decision, now, tuple(notify_states))
        if send and _durable_moved(case, durable, decision, state_written):
            send = False
            settle = False
            gate_reason = ("the durable row changed after this pass listed it (state or operator decision); "
                           "nothing dispatched and the retry responsibility is retained, so the next pass "
                           "evaluates the current row")
        if not send:
            if settle and not dry_run:
                _drop_pending(key, pending_path, row, pending)
            if key in pending:
                row["notify_pending"] = True
            row["notify"] = {"sent": False, "reason": gate_reason}
            continue
        if dry_run:
            row["notify"] = {"sent": False, "reason": "dry_run"}
            continue
        if notifier is None:
            # The obligation is already durable, so a later pass with piece C present will deliver it.
            row["notify_pending"] = key in pending
            row["notify"] = {"sent": False, "reason": "notifier unavailable (piece C absent); retry "
                                                      "responsibility retained"}
            continue
        handoff = {**case, **durable, "state": decision.state,
                   "confidence": round(decision.confidence, 4),
                   "next_trigger": decision.next_trigger,
                   "price": (snapshot or {}).get("close"),
                   "exit_price": exit_price(case)}
        try:
            result = notifier(handoff)
            notifier_calls += 1
            row["notify"] = {k: v for k, v in (result or {}).items() if k != "message"}
        except Exception as exc:  # noqa: BLE001 — a notifier fault never aborts the pass
            notifier_calls += 1
            result = {"sent": False, "error": f"{type(exc).__name__}: {exc}"}
            row["notify"] = result
        if _delivery_confirmed(result):
            _drop_pending(key, pending_path, row, pending)
        else:
            entry = pending.get(key) or {"first_failed_at": now.isoformat(), "attempts": 0}
            entry["state"] = decision.state
            entry["attempts"] = int(entry.get("attempts") or 0) + 1
            entry["last_error"] = (result or {}).get("error") or (result or {}).get("reason") or "sent false"
            try:
                merge_pending({key: entry}, pending_path)
                pending[key] = entry
            except PENDING_ERRORS as exc:
                # The entry written before the send still stands; never report a responsibility we did not keep.
                pending[key] = entry
                pending_errors += 1
                row["pending_store_error"] = f"{type(exc).__name__}: {exc}"
            row["notify_pending"] = True
    return {"store": "ok", "considered": len(cases), "changed": changed, "attempted_changes": attempted,
            "notifier_calls": notifier_calls, "pending": len(pending),
            "pending_store_errors": pending_errors, "decisions": decisions,
            "dry_run": bool(dry_run), "policy_source": policy.get("policy_source")}
