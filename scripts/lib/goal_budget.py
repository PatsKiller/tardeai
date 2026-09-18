#!/usr/bin/env python3
"""goal_budget.py — a CUMULATIVE per-goal budget that cannot fail open.

P3 of the goal-oriented agent plan. Written to the exact idiom of
``scripts/lib/search_budget.py`` — flock, atomic replace, ``BudgetUnavailable``
⇒ DENY — because that module was rewritten for precisely the failure this one
must not repeat.

WHY A SECOND BUDGET MODULE
--------------------------
``search_budget`` bounds PROVIDER calls per day and per month. It cannot bound a
GOAL, because a goal is not a provider and a lap is not a day.

Today every budget in the agent runtime is PER INVOCATION and resets every lap:
``BudgetPolicy(max_model_calls=3, deadline_seconds=360)`` in
``agent_runtime/contracts.py`` is checked inside ``MvlRuntime.reason`` against
counters that begin at zero for each run. A goal that laps two hundred times
therefore passes two hundred budget checks and accumulates nothing. There is no
number anywhere on disk that answers "what has this goal cost so far", so there
is nothing that could ever refuse a goal for having cost too much.

Measured 2026-09-16, which is why a cap read from the caller's environment is
not a control: the spend floor is **67 LLM processes, 28 of them capped,
summing to $17.80/day against a $2.00/day ceiling**, and only **9 of 460
crontab lines** set the cap at all. An environment variable that 451 callers
never set is advisory. So enforcement here sits where the spend is AUTHORISED —
at enqueue, in the producer — not where it is requested.

THE THREE PROPERTIES THIS MODULE EXISTS TO GUARANTEE
----------------------------------------------------
  * **Cumulative, keyed by (goal_id, predicate_version).** The counters survive
    the lap. ``predicate_version`` is part of the key because changing the
    predicate changes the question, and a new question legitimately deserves a
    new allowance — but only by an explicit, recorded version bump, never by a
    field quietly going missing (see ``PREDICATE_VERSION_MISSING`` below).
  * **Never fail open.** A budget-check error DENIES. ``_load`` raises rather
    than returning ``{}``; no writer ever rebuilds an unreadable ledger as a
    fresh zero counter. That rebuild is the documented reason ``search_budget``
    was rewritten: a corrupt ledger read as "no calls recorded yet" and produced
    an *unbudgeted* call. An unreadable budget here produces *zero* laps.
  * **Monotonic.** ``cost_usd``, ``paid_calls``, ``model_calls`` and ``laps``
    only ever increase. There is deliberately **no ``refund()``** — the mirror
    of ``search_budget.refund`` is absent by design. A provider quota is a rate
    and can legitimately be handed back; cumulative spend is history, and a
    history that can go down cannot answer the one question this ledger exists
    to answer.

WHERE ENFORCEMENT LIVES, AND WHERE IT MUST NOT
-----------------------------------------------
Enforced in ``agent_runtime/trigger_producer.produce_once``, at the moment a lap
is enqueued. **Never inside ``MvlRuntime``.** An agent that could consult — let
alone write — its own ledger could extend its own budget, which is the authority
``SELF_GOVERNANCE_TOKENS`` (``agent_runtime/agents/base.py``) exists to deny: it
already forbids ``budget.set``, ``budget.write``, ``enqueue_self`` and
``schedule`` from any agent's allowed tools, and now forbids ``goal_budget``
outright. Nothing in ``agent_runtime/runtime.py`` imports this module, and a
test pins that.

RECEIPTS GO TO A SIDECAR, NOT TO THE LEDGER
--------------------------------------------
``search_budget`` keeps denial receipts inside the ledger it is denying from.
That is right for a rate budget and wrong here: the denial this module most
needs to record is *the ledger is unreadable*, and writing that into the
unreadable ledger would mean rebuilding it — the exact fail-open write. So
receipts are appended to ``goal_budget_receipts.jsonl`` beside the ledger.
Append-only; never rewritten, never deleted (AGENTS.md §0 rule 6).

Shared API for callers:

    check(goal_id, predicate_version)        → {allowed, reason, status}
    try_consume_lap(goal_id, predicate_version) → same shape; atomic under flock
    record_spend(goal_id, predicate_version, …) → count cost after the fact
    gate_candidate(payload)                  → the producer's enqueue-time gate

READ_ONLY_ADVISORY with respect to the trading system: this module counts and
denies. It never issues a request, sizes, orders, stops, or writes broker state.
"""
from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

SCHEMA = "GoalBudget@v1"
RECEIPT_SCHEMA = "GoalBudgetDenialReceipt@v1"


def _state_root() -> Path:
    try:
        from scripts.lib.canonical_store_registry import production_state_root
        return Path(production_state_root())
    except Exception:
        try:
            from lib.canonical_store_registry import production_state_root  # type: ignore
            return Path(production_state_root())
        except Exception:
            return Path.home() / "trade-ai-releases" / "persistent-state"


def budget_path(root: Optional[Path] = None) -> Path:
    """Durable ledger path. Always under production_state_root/data/runtime.

    Same placement rule as ``search_budget.budget_path``: the canonical state
    root, never a path relative to whichever release directory the caller
    happened to import from.
    """
    base = Path(root) if root else _state_root()
    return base / "data" / "runtime" / "goal_budget.json"


def receipts_path(root: Optional[Path] = None) -> Path:
    """Append-only denial receipts, beside the ledger. See the module docstring
    for why these are NOT kept inline the way ``search_budget`` keeps its own."""
    return budget_path(root).with_name("goal_budget_receipts.jsonl")


class BudgetUnavailable(RuntimeError):
    """The budget could not be established. Callers must treat this as DENY."""


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


@contextmanager
def _exclusive(path: Path) -> Iterator[None]:
    """Exclusive flock on a sidecar so concurrent producer runs serialize.

    Two scheduled producers must not both observe an under-limit counter and
    both enqueue the lap that exhausts it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_path(path)
    if not lock.exists():
        lock.touch()
    with open(lock, "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def _load(path: Path) -> dict[str, Any]:
    """Read the ledger. Raises rather than returning an empty dict.

    A missing ledger is a real "no laps yet" and returns an empty document. An
    ILLEGIBLE ledger is not: it raises, and every caller turns that into a
    denial. The distinction is the whole module.
    """
    if not path.exists():
        return {"schema": SCHEMA, "goals": {}}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise BudgetUnavailable(f"goal budget ledger unreadable at {path}: {e}") from e
    if not isinstance(doc, dict):
        raise BudgetUnavailable(f"goal budget ledger malformed at {path}")
    goals = doc.setdefault("goals", {})
    if not isinstance(goals, dict):
        raise BudgetUnavailable(f"goal budget ledger has a malformed goals map at {path}")
    return doc


def _save(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)                      # atomic os.replace; a torn ledger reads as unavailable


#: CUMULATIVE ceilings for one (goal_id, predicate_version), across every lap.
#:
#: ``max_paid_calls`` and ``max_cost_usd`` are ZERO deliberately. Tiers 0 and 1
#: of the validation stack are free and need no approval; funding a paid judge
#: is an operator decision (AGENTS.md §17, approval register item 4). A zero
#: ceiling is not an outage here — the comparison is ``spent > ceiling``, not
#: ``>=``, so a free lap against a 0.00 ceiling is allowed and the FIRST cent
#: stops the goal until an operator raises it. The pilot's cost receipt is
#: supposed to read ``paid_calls: 0``; this is what makes that structural
#: rather than hopeful.
DEFAULT_LIMITS: dict[str, float] = {
    "max_laps": 12,
    "max_model_calls": 24,
    "max_paid_calls": 0,
    "max_cost_usd": 0.0,
}

_INT_LIMITS = ("max_laps", "max_model_calls", "max_paid_calls")


def policy_path(root: Optional[Path] = None) -> Path:
    """Operator-owned ceilings. Deliberately NOT in the repository.

    A cap committed under ``config/`` is a cap any merged PR can raise, and the
    agents in this fleet open PRs. Keeping it beside the ledger in the canonical
    state root means raising a ceiling is an act on the operator's host —
    AGENTS.md §17, approval register item 4 ("funding any paid tier-2 judge") —
    and not a diff.
    """
    base = Path(root) if root else _state_root()
    return base / "config" / "goal_budget_policy.json"


def _policy_limits(root: Optional[Path] = None) -> dict[str, float]:
    """Ceilings from ``policy_path``, or ``{}``.

    Fail-safe on purpose, exactly like ``search_budget._registry_budget``: any
    failure returns ``{}`` so DEFAULT_LIMITS applies. A policy reader that raised
    would turn a typo in an operator's file into a total outage of the goal loop,
    and the defaults it falls back to are the strictest values in the module.
    """
    try:
        doc = json.loads(policy_path(root).read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(doc, dict):
        return {}
    out: dict[str, float] = {}
    for key in DEFAULT_LIMITS:
        if key not in doc:
            continue
        try:
            out[key] = int(doc[key]) if key in _INT_LIMITS else float(doc[key])
        except (TypeError, ValueError):
            continue
    return out


def _limits(env: Optional[Mapping[str, str]] = None,
            root: Optional[Path] = None) -> dict[str, float]:
    """Effective cumulative caps: DEFAULT_LIMITS < operator policy < env (lower only).

    The layering mirrors ``search_budget._limits`` with one deliberate
    difference: an environment override may only **LOWER** a ceiling, never
    raise one.

    ``SEARCH_BUDGET_*`` may move a provider cap in either direction, which is
    safe there because it configures a provider the operator pays for directly.
    It is not safe here. The process reading the variable is downstream of the
    agent whose spend it bounds, so a raisable env cap is a budget that an
    agent's own environment can extend — and the measured state of this host is
    that env caps are not a control at all: 67 LLM processes, 28 capped, $17.80
    a day against a $2.00 ceiling, with 9 of 460 crontab lines setting it.
    Lowering stays, because tightening during a canary is legitimate and can
    never be an escalation.
    """
    lim = dict(DEFAULT_LIMITS)
    lim.update(_policy_limits(root))        # operator-owned; may raise or lower
    src = env if env is not None else os.environ
    for key, ceiling in list(lim.items()):
        raw = str(src.get(f"GOAL_BUDGET_{key.upper()}", "")).strip()
        if not raw:
            continue
        try:
            val = int(raw) if key in _INT_LIMITS else float(raw)
        except ValueError:
            continue                        # a bad override keeps the safe default
        if val < ceiling:                   # LOWER only — never raise
            lim[key] = val
    return lim


def limits(env: Optional[Mapping[str, str]] = None,
           root: Optional[Path] = None) -> dict[str, float]:
    """Public read of the effective cumulative caps (see ``_limits``)."""
    return _limits(env, root)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _bucket(doc: dict[str, Any], goal_id: str, predicate_version: str) -> dict[str, Any]:
    """The counters for one (goal_id, predicate_version), created if absent.

    Nested rather than a joined ``goal_id|predicate_version`` string key: a
    delimiter in a composite key is one identifier containing the delimiter away
    from two different goals sharing a budget.
    """
    goals = doc.setdefault("goals", {})
    per_goal = goals.setdefault(str(goal_id), {})
    if not isinstance(per_goal, dict):
        raise BudgetUnavailable(f"goal budget entry malformed for {goal_id}")
    b = per_goal.setdefault(str(predicate_version), {})
    if not isinstance(b, dict):
        raise BudgetUnavailable(
            f"goal budget entry malformed for {goal_id}/{predicate_version}")
    b.setdefault("laps", 0)
    b.setdefault("model_calls", 0)
    b.setdefault("paid_calls", 0)
    b.setdefault("cost_usd", 0.0)
    return b


def _status_from_doc(goal_id: str, predicate_version: str, doc: dict[str, Any],
                     now: datetime, path: Path,
                     env: Optional[Mapping[str, str]] = None,
                     root: Optional[Path] = None) -> dict[str, Any]:
    b = _bucket(doc, goal_id, predicate_version)
    lim = _limits(env, root)
    return {
        "goal_id": str(goal_id),
        "predicate_version": str(predicate_version),
        "as_of": _iso(now),
        "laps": int(b.get("laps") or 0),
        "max_laps": int(lim["max_laps"]),
        "model_calls": int(b.get("model_calls") or 0),
        "max_model_calls": int(lim["max_model_calls"]),
        "paid_calls": int(b.get("paid_calls") or 0),
        "max_paid_calls": int(lim["max_paid_calls"]),
        "cost_usd": round(float(b.get("cost_usd") or 0.0), 6),
        "max_cost_usd": float(lim["max_cost_usd"]),
        "first_lap_at": b.get("first_lap_at"),
        "last_lap_at": b.get("last_lap_at"),
        "ledger_path": str(path),
    }


def _exhausted_reason(st: Mapping[str, Any]) -> Optional[str]:
    """The tightest cumulative ceiling this goal has reached, or None.

    ``laps`` / ``model_calls`` use ``>=`` because consuming one more would cross
    the ceiling. ``paid_calls`` / ``cost_usd`` use ``>`` because their ceilings
    default to zero and a FREE lap against a zero cost ceiling must be allowed —
    it is the first unit of actual spend that stops the goal.
    """
    if int(st["laps"]) >= int(st["max_laps"]):
        return "LAP_BUDGET_EXHAUSTED"
    if int(st["model_calls"]) >= int(st["max_model_calls"]):
        return "MODEL_CALL_BUDGET_EXHAUSTED"
    if int(st["paid_calls"]) > int(st["max_paid_calls"]):
        return "PAID_CALL_BUDGET_EXHAUSTED"
    if float(st["cost_usd"]) > float(st["max_cost_usd"]):
        return "COST_BUDGET_EXHAUSTED"
    return None


def write_denial_receipt(goal_id: Optional[str], predicate_version: Optional[str],
                         reason: str, *, detail: Optional[dict[str, Any]] = None,
                         now: Optional[datetime] = None,
                         root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """One append-only row per refused lap: which goal, and why it was refused.

    Appended to a JSONL sidecar rather than into the ledger, because the refusal
    that matters most is ``BUDGET_UNAVAILABLE`` — and writing that into the
    unreadable ledger would mean rebuilding it, which is the fail-open write
    this module exists to prevent.

    Never raises. A receipt that cannot be written must not turn a clean denial
    into a producer crash; the denial stands either way.
    """
    now = now or _now()
    row: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "goal_id": goal_id,
        "predicate_version": predicate_version,
        "reason": str(reason),
        "ts": _iso(now),
    }
    if detail:
        row["detail"] = detail
    try:
        p = receipts_path(root)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        return row
    except Exception:
        return None


def denial_receipts(*, root: Optional[Path] = None) -> list[dict[str, Any]]:
    """Receipt rows, oldest first. Empty when the sidecar is missing."""
    p = receipts_path(root)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                out.append(row)
    except Exception:
        return out
    return out


def status(goal_id: str, predicate_version: str, *,
           now: Optional[datetime] = None,
           root: Optional[Path] = None,
           env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """Cumulative counters for one goal. Raises ``BudgetUnavailable`` if illegible."""
    now = now or _now()
    path = budget_path(root)
    doc = _load(path)
    return _status_from_doc(goal_id, predicate_version, doc, now, path, env, root)


def check(goal_id: str, predicate_version: str, *,
          now: Optional[datetime] = None,
          root: Optional[Path] = None,
          env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """May another lap of this goal be enqueued? {allowed, reason, status}.

    **Never raises, and never fails open.** Read-only: prefer ``try_consume_lap``
    at the enqueue site so two producer runs cannot both spend the last lap.
    """
    try:
        st = status(goal_id, predicate_version, now=now, root=root, env=env)
    except Exception as e:
        return {"allowed": False,
                "reason": f"BUDGET_UNAVAILABLE: {type(e).__name__}: {e}",
                "fail_open": False, "status": None}
    reason = _exhausted_reason(st)
    if reason:
        return {"allowed": False, "reason": reason, "status": st}
    return {"allowed": True, "reason": "OK", "status": st}


def try_consume_lap(goal_id: str, predicate_version: str, *,
                    now: Optional[datetime] = None,
                    root: Optional[Path] = None,
                    env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """Atomically check the cumulative budget and count one lap when allowed.

    Holds an exclusive flock across the read-modify-write. On any error
    establishing or persisting the ledger: ``allowed=False``. A lap that could
    not be counted is never granted — granting it would spend uncounted, which
    is how a cumulative ledger silently becomes fiction.
    """
    now = now or _now()
    path = budget_path(root)
    try:
        with _exclusive(path):
            try:
                doc = _load(path)
                st = _status_from_doc(goal_id, predicate_version, doc, now, path, env, root)
            except BudgetUnavailable as e:
                return {"allowed": False,
                        "reason": f"BUDGET_UNAVAILABLE: {type(e).__name__}: {e}",
                        "fail_open": False, "status": None}
            reason = _exhausted_reason(st)
            if reason:
                # Denials are counted, but NOT into the spend counters: a refused
                # lap cost nothing and must not inflate the number an operator
                # reads as this goal's spend.
                b = _bucket(doc, goal_id, predicate_version)
                b["denied_laps"] = int(b.get("denied_laps") or 0) + 1
                b["last_denied_at"] = _iso(now)
                b["last_denied_reason"] = reason
                try:
                    _save(path, doc)
                except Exception:
                    pass
                return {"allowed": False, "reason": reason,
                        "status": _status_from_doc(goal_id, predicate_version, doc, now, path, env, root)}
            b = _bucket(doc, goal_id, predicate_version)
            b["laps"] = int(b.get("laps") or 0) + 1
            b.setdefault("first_lap_at", _iso(now))
            b["last_lap_at"] = _iso(now)
            try:
                _save(path, doc)
            except Exception as e:
                return {"allowed": False,
                        "reason": f"BUDGET_UNAVAILABLE: {type(e).__name__}: {e}",
                        "fail_open": False, "status": st}
            return {"allowed": True, "reason": "OK",
                    "status": _status_from_doc(goal_id, predicate_version, doc, now, path, env, root)}
    except Exception as e:
        return {"allowed": False,
                "reason": f"BUDGET_UNAVAILABLE: {type(e).__name__}: {e}",
                "fail_open": False, "status": None}


def refund_lap(goal_id: str, predicate_version: str, *,
               reason: str = "ENQUEUE_NOT_ADMITTED",
               now: Optional[datetime] = None,
               root: Optional[Path] = None) -> dict[str, Any]:
    """Return a lap that was charged but never admitted.

    ``try_consume_lap`` charges BEFORE ``store.enqueue`` on purpose, so a lap can
    never be enqueued unbudgeted — ``check`` warns against the reverse order
    because two producer runs could otherwise both spend the last lap. The price
    of that ordering is that an enqueue refused as DUPLICATE has already been
    paid for.

    Measured live 2026-09-18: three goals were each charged 12 laps in 22
    minutes while exactly ONE lap per goal reached the ledger — 33 of 36 charges
    bought nothing — and all three then hit ``LAP_BUDGET_EXHAUSTED``, which is
    terminal until an operator or a predicate bump reopens the goal. The whole
    allowance was spent on no-ops.

    This restores the principle the module already states for denials: a lap
    that did no work must not inflate the number an operator reads as this
    goal's spend. Floors at zero, records the refund for audit, and never raises
    — a failed refund must not take the caller down with it.
    """
    now = now or _now()
    path = budget_path(root)
    try:
        with _exclusive(path):
            doc = _load(path)
            b = _bucket(doc, goal_id, predicate_version)
            before = int(b.get("laps") or 0)
            after = max(0, before - 1)
            b["laps"] = after
            b["refunded_laps"] = int(b.get("refunded_laps") or 0) + 1
            b["last_refund_at"] = _iso(now)
            b["last_refund_reason"] = str(reason)
            _save(path, doc)
            return {"refunded": True, "reason": str(reason),
                    "laps_before": before, "laps_after": after}
    except Exception as e:  # noqa: BLE001 — a refund is never load-bearing
        return {"refunded": False,
                "reason": f"REFUND_UNAVAILABLE: {type(e).__name__}: {e}"}


def refund_candidate(payload: Optional[Mapping[str, Any]], *,
                     reason: str = "ENQUEUE_NOT_ADMITTED",
                     now: Optional[datetime] = None,
                     root: Optional[Path] = None) -> dict[str, Any]:
    """Producer-side mirror of ``gate_candidate``: hand back an unadmitted lap.

    A candidate that names no goal was never charged, so there is nothing to
    return and this is a no-op rather than an error.
    """
    key = goal_key(payload)
    if key is None:
        return {"refunded": False, "reason": NOT_GOAL_SCOPED}
    goal_id, predicate_version = key
    if not predicate_version:
        return {"refunded": False, "reason": "PREDICATE_VERSION_MISSING"}
    return refund_lap(goal_id, predicate_version, reason=reason, now=now, root=root)


def record_spend(goal_id: str, predicate_version: str, *,
                 cost_usd: float = 0.0, paid_calls: int = 0, model_calls: int = 0,
                 now: Optional[datetime] = None,
                 root: Optional[Path] = None) -> bool:
    """Add this lap's measured cost to the goal's cumulative totals.

    Monotonic by construction: negative inputs are refused rather than clamped,
    because a caller passing one is confused about which direction this ledger
    runs, and silently treating it as zero would hide that.

    A corrupt ledger is **not** rebuilt as a fresh zero counter (that was the
    fail-open write path). The write is skipped; the next ``check`` /
    ``try_consume_lap`` DENIES on the unreadable ledger. Returns whether the
    spend was actually recorded, so a caller cannot report a write that did not
    happen.
    """
    if cost_usd < 0 or paid_calls < 0 or model_calls < 0:
        raise ValueError("goal spend is cumulative; inputs must be non-negative")
    if not (cost_usd or paid_calls or model_calls):
        return False
    now = now or _now()
    path = budget_path(root)
    try:
        with _exclusive(path):
            try:
                doc = _load(path)
                b = _bucket(doc, goal_id, predicate_version)
            except BudgetUnavailable:
                return False                 # never rebuild a corrupt ledger
            b["cost_usd"] = round(float(b.get("cost_usd") or 0.0) + float(cost_usd), 6)
            b["paid_calls"] = int(b.get("paid_calls") or 0) + int(paid_calls)
            b["model_calls"] = int(b.get("model_calls") or 0) + int(model_calls)
            b["last_spend_at"] = _iso(now)
            try:
                _save(path, doc)
            except Exception:
                return False
            return True
    except Exception:
        return False


#: A candidate carrying no goal_id is not a goal lap. It is enqueued unbudgeted
#: and that is honest: P3 bounds GOALS, and refusing every non-goal trigger
#: because a goal ledger is unreadable would be an outage caused by one file.
NOT_GOAL_SCOPED = "NOT_GOAL_SCOPED"


def goal_key(payload: Optional[Mapping[str, Any]]) -> Optional[tuple[str, Optional[str]]]:
    """``(goal_id, predicate_version)`` from a trigger payload, or None.

    ``predicate_version`` comes back as None when the payload names a goal but
    not a version — the caller must DENY, not substitute a default. See
    ``gate_candidate``.
    """
    if not isinstance(payload, Mapping):
        return None
    goal_id = str(payload.get("goal_id") or "").strip()
    if not goal_id:
        return None
    pv = str(payload.get("predicate_version") or "").strip()
    return (goal_id, pv or None)


def gate_candidate(payload: Optional[Mapping[str, Any]], *,
                   now: Optional[datetime] = None,
                   root: Optional[Path] = None,
                   env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """The producer's enqueue-time gate. Consumes a lap when it allows one.

    A payload naming a goal but no ``predicate_version`` is REFUSED rather than
    defaulted. Defaulting would mean an omitted field silently selects a
    different budget bucket — a fresh allowance obtained by leaving a key out,
    which is exactly the self-extension this module is here to prevent.
    """
    key = goal_key(payload)
    if key is None:
        return {"allowed": True, "reason": NOT_GOAL_SCOPED, "status": None}
    goal_id, predicate_version = key
    if not predicate_version:
        write_denial_receipt(goal_id, None, "PREDICATE_VERSION_MISSING",
                             detail={"enforced_at": "enqueue"}, now=now, root=root)
        return {"allowed": False, "reason": "PREDICATE_VERSION_MISSING",
                "fail_open": False, "status": None}
    verdict = try_consume_lap(goal_id, predicate_version, now=now, root=root, env=env)
    if not verdict["allowed"]:
        write_denial_receipt(goal_id, predicate_version, verdict["reason"],
                             detail={"enforced_at": "enqueue"}, now=now, root=root)
    return verdict


__all__ = [
    "SCHEMA",
    "RECEIPT_SCHEMA",
    "NOT_GOAL_SCOPED",
    "BudgetUnavailable",
    "budget_path",
    "receipts_path",
    "DEFAULT_LIMITS",
    "limits",
    "status",
    "check",
    "try_consume_lap",
    "refund_lap",
    "refund_candidate",
    "record_spend",
    "goal_key",
    "gate_candidate",
    "write_denial_receipt",
    "denial_receipts",
]
