"""Self-heal Tier-1 runbook engine: a data-driven catalog of deterministic actions for non-code failures.

LQ-20261107-1231 (operator 2026-11-08 ~16:40 ET; scope expanded 16:45 ET): before a non-code failure is escalated to
the lead, a deterministic runbook must try what a code change cannot: release a lock whose recorded owner is dead,
defer a quota/rate-limited lane with a capped retry budget, re-check a late dataset against its health contract and
re-run once. The runbooks are DATA (``config/self_heal_runbook_catalog.json``), not code: one entry per failure
pattern, matched by failure class / reason regex / exception regex, executing one primitive from a fixed whitelist.

Design (see SELFHEAL-BEST-PRACTICE-PLAN-20261108.md, section RUNBOOK CATALOG):

* ``plan_runbook(failure_class, evidence, contract, now)`` is pure: it selects one catalog entry, evaluates every
  precondition and returns ``{action, reason, checks, idempotency_key, ...}``. No I/O beyond the catalog file.
* ``apply_runbook(plan, *, dry_run=True)`` executes only the plan's primitive. Dry run is the default and touches
  nothing. The only primitive that changes the host is ``release_stale_flock`` for an EXISTENCE-based lock, and only
  when the recorded owner pid is dead, the lock age exceeds the lane timeout, and a non-blocking flock probe proves
  no live holder. For flock-kind locks the repository's own audit (scripts/cleanup_stale_locks.sh header,
  audit B_self_healing #7) is binding: a holder-less flock file blocks nothing and removing it races the next run, so
  the primitive reports ``lock_free`` and deletes nothing.
* Every action is rate-limited to one per lane per hour, carries a deterministic idempotency key, and is bounded by
  the entry's ``max_attempts`` and ``cooldown_min``. When a precondition fails, or the budget is spent, the plan says
  so and (when the entry fails) escalates with the entry's FINDING template instead of acting.
* Receipts: ``apply_runbook`` returns a ``SelfHealRunbookReceipt@v1`` for the caller to persist; this module writes no
  DB row, no ledger row and no file other than the one archived stale existence lock during a non-dry apply.

Safety: the action whitelist contains no kill, no DB write, no crontab/systemd/env edit, no broker/order/stop, no
credential read, no push. Lanes whose id names broker/order/stop/options execution are refused every mutating action
before the catalog is consulted (MBI_BEHAVIOR = 0, AGENTS.md §0/§22).

AUTHORITY: READ_ONLY_ADVISORY. Pure except the gated lock-release probe and archive.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

SCHEMA = "SelfHealRunbookCatalog@v1"
PLAN_SCHEMA = "SelfHealRunbookPlan@v1"
RECEIPT_SCHEMA = "SelfHealRunbookReceipt@v1"
ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "config" / "self_heal_runbook_catalog.json"

#: The only executable verbs. Anything outside this tuple is a catalog error (validator) and a refusal (engine).
ACTION_WHITELIST = (
    "noop_wait_recheck",
    "rerun_once_via_gateway",
    "defer_until",
    "release_stale_flock",
    "release_stale_sqlite_wal_lock",
    "open_breaker_cooldown",
    "mark_weekend_expected",
    "escalate_finding",
)
#: Actions that only observe/record and therefore do not consume the lane's hourly action budget.
NON_MUTATING_ACTIONS = ("noop_wait_recheck", "escalate_finding", "mark_weekend_expected",
                        "release_stale_sqlite_wal_lock")
TIERS = ("auto", "auto_notify", "human_only")
CATEGORIES = tuple("ABCDEFGHIJK")
DEFAULT_MAX_ATTEMPTS = 1
DEFAULT_COOLDOWN_MIN = 0
DEFAULT_JITTER_S = 300.0
RATE_LIMIT_S = 3600.0
MATCH_TAIL_CHARS = 4000
#: A mutating action is refused when the lane id names broker/order/stop/options execution (AGENTS.md §0/§22).
NEVER_ACTION_WORDS = (
    "broker", "order", "stop", "options-exec", "options_exec", "option-exec", "execution", "scalp-live",
    "schwab", "alpaca", "moomoo", "fidelity", "snaptrade", "trade-exec", "fill",
)
#: Lock kinds an existence-based release may touch. A kernel flock is released by the kernel when its holder dies.
EXISTENCE_LOCK_KINDS = ("pidfile", "existence", "marker")
#: Even with a dead owner and a free probe, a lock path here is never renamed (AGENTS.md §24.12/§24.13).
NEVER_TOUCH_PATH_PARTS = frozenset({".ssh", "persistent-state", "db_backups", "credentials", ".gnupg"})
NEVER_TOUCH_PATH_ROOTS = ("/etc/", "/usr/", "/bin/", "/sbin/", "/boot/", "/dev/", "/proc/", "/sys/")


class RunbookCatalogError(ValueError):
    """The catalog is missing, unreadable or violates the schema. Never a silent pass."""


class RunbookPlanError(ValueError):
    """A plan handed to apply_runbook is not a plan this engine produced."""


# ---------------------------------------------------------------- catalog


def load_catalog(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """Load and validate the runbook catalog, keyed by entry id.

    Raises RunbookCatalogError on anything a human cannot read: a missing file is an error here (the engine must not
    silently run with no runbooks), unlike a missing optional override file elsewhere in the tree.
    """
    p = Path(path) if path is not None else CATALOG_PATH
    try:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunbookCatalogError(f"runbook_catalog_unreadable: {type(exc).__name__}: {exc}") from exc
    validate_catalog(doc)
    return {str(e["id"]): e for e in doc["runbooks"]}


def validate_catalog(doc: Mapping[str, Any]) -> None:
    """Fail closed on any catalog defect. A runbook nobody can parse is not a runbook."""
    if not isinstance(doc, Mapping) or doc.get("schema") != SCHEMA:
        raise RunbookCatalogError("runbook_catalog_schema")
    entries = doc.get("runbooks")
    if not isinstance(entries, list) or not entries:
        raise RunbookCatalogError("runbook_catalog_empty")
    seen_ids: set[str] = set()
    seen_priorities: set[int] = set()
    for e in entries:
        if not isinstance(e, Mapping):
            raise RunbookCatalogError("runbook_entry_not_object")
        eid = e.get("id")
        if not isinstance(eid, str) or not eid:
            raise RunbookCatalogError("runbook_entry_id")
        if eid in seen_ids:
            raise RunbookCatalogError(f"runbook_entry_duplicate_id:{eid}")
        seen_ids.add(eid)
        cat = e.get("category")
        if cat not in CATEGORIES:
            raise RunbookCatalogError(f"runbook_entry_category:{eid}")
        if not isinstance(e.get("title"), str) or not e["title"]:
            raise RunbookCatalogError(f"runbook_entry_title:{eid}")
        if e.get("tier") not in TIERS:
            raise RunbookCatalogError(f"runbook_entry_tier:{eid}")
        prio = e.get("priority")
        if not isinstance(prio, int) or isinstance(prio, bool):
            raise RunbookCatalogError(f"runbook_entry_priority_must_be_explicit_int:{eid}")
        if prio in seen_priorities:
            raise RunbookCatalogError(f"runbook_entry_duplicate_priority:{eid}")
        seen_priorities.add(prio)
        action = e.get("action")
        if action not in ACTION_WHITELIST:
            raise RunbookCatalogError(f"runbook_action_not_whitelisted:{eid}:{action}")
        match = e.get("match")
        if not isinstance(match, Mapping):
            raise RunbookCatalogError(f"runbook_entry_match:{eid}")
        for key in ("failure_class", "reason_regex", "exception_regex"):
            val = match.get(key, [])
            if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
                raise RunbookCatalogError(f"runbook_entry_match_list:{eid}:{key}")
            if key.endswith("_regex"):
                for pat in val:
                    try:
                        re.compile(pat)
                    except re.error as exc:
                        raise RunbookCatalogError(f"runbook_entry_regex:{eid}:{pat}:{exc}") from exc
        pre = e.get("preconditions", [])
        if not isinstance(pre, list):
            raise RunbookCatalogError(f"runbook_entry_preconditions:{eid}")
        for item in pre:
            name = item if isinstance(item, str) else (item or {}).get("check") if isinstance(item, Mapping) else None
            if not isinstance(name, str) or name not in PRECONDITIONS:
                raise RunbookCatalogError(f"runbook_entry_precondition_unknown:{eid}:{name}")
        for key in ("max_attempts", "cooldown_min"):
            if key in e and (not isinstance(e[key], int) or isinstance(e[key], bool) or e[key] < 0):
                raise RunbookCatalogError(f"runbook_entry_{key}:{eid}")
        if not isinstance(e.get("params", {}), Mapping):
            raise RunbookCatalogError(f"runbook_entry_params:{eid}")
        verify = e.get("verify", {})
        if not isinstance(verify, Mapping):
            raise RunbookCatalogError(f"runbook_entry_verify:{eid}")
        on_fail = e.get("on_fail", {})
        if not isinstance(on_fail, Mapping):
            raise RunbookCatalogError(f"runbook_entry_on_fail:{eid}")
        steps = e.get("human_steps", [])
        if not isinstance(steps, list) or any(not isinstance(s, str) for s in steps):
            raise RunbookCatalogError(f"runbook_entry_human_steps:{eid}")
        tests = e.get("tests", [])
        if not isinstance(tests, list) or any(not isinstance(t, str) for t in tests):
            raise RunbookCatalogError(f"runbook_entry_tests:{eid}")


# ---------------------------------------------------------------- evidence helpers


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


_mapping = _as_mapping  # short internal alias; a non-mapping is always the empty mapping, never an error


def _now(now: Any) -> datetime:
    if isinstance(now, datetime):
        dt = now
    elif isinstance(now, str) and now:
        dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    else:
        dt = datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_ts(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _text(evidence: Mapping[str, Any]) -> str:
    parts = []
    for key in ("reason", "failure_kind", "exception", "detail", "title", "error", "stderr_tail", "stdout_tail"):
        val = evidence.get(key)
        if val:
            parts.append(str(val))
    return "\n".join(parts)[-MATCH_TAIL_CHARS:]


def _signature(failure_class: str, evidence: Mapping[str, Any]) -> str:
    sig = evidence.get("signature")
    if isinstance(sig, str) and sig.strip():
        return sig.strip()
    text = (evidence.get("reason") or evidence.get("failure_kind") or failure_class or "").strip()
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]
    return f"{failure_class or 'unknown'}:{digest}"


def _lane_timeout_s(evidence: Mapping[str, Any], contract: Mapping[str, Any]) -> Optional[float]:
    for value in (evidence.get("lane_timeout_s"), evidence.get("timeout_s"),
                  (contract.get("baseline") or {}).get("timeout_s"), contract.get("timeout_s")):
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value)
    return None


def _freshness_threshold_h(contract: Mapping[str, Any]) -> Optional[float]:
    baseline = _mapping(contract.get("baseline"))
    for key in ("freshness_failed_after_h", "freshness_degraded_after_h"):
        val = baseline.get(key, contract.get(key))
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
            return float(val)
    return None


def _age_h(evidence: Mapping[str, Any], now: datetime) -> Optional[float]:
    for key in ("data_age_h", "receipt_age_h", "age_hours_h"):
        val = evidence.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
    age_s = evidence.get("data_age_s", evidence.get("receipt_age_s"))
    if isinstance(age_s, (int, float)) and not isinstance(age_s, bool):
        return float(age_s) / 3600.0
    for key in ("last_ok_at", "data_mtime", "receipt_ok_at", "output_mtime"):
        ts = _parse_ts(evidence.get(key))
        if ts is not None:
            return max(0.0, (now - ts).total_seconds() / 3600.0)
    return None


def _pid_alive(pid: int) -> Optional[bool]:
    """True/False when the kernel answers, None when it cannot be asked (permission is not death)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def _pid_state(evidence: Mapping[str, Any]) -> tuple[Optional[int], Optional[bool]]:
    raw = evidence.get("owner_pid", evidence.get("lock_owner_pid"))
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        return None, None
    stated = evidence.get("pid_alive")
    if isinstance(stated, bool):
        return raw, stated
    return raw, _pid_alive(raw)


def _int_field(evidence: Mapping[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        val = evidence.get(key)
        if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
            return val
    return None


def _refusal_lane(lane: str) -> bool:
    low = (lane or "").lower()
    return any(word in low for word in NEVER_ACTION_WORDS)


# ---------------------------------------------------------------- preconditions
#: name -> (entry params, evidence, contract, now) -> (ok, detail). Every precondition is safe to evaluate on a
#: partial evidence dict; a missing fact is a refusal, never an assumption.


def _pc_lane_present(_p, ev, _c, _n):
    lane = ev.get("lane")
    return bool(lane), str(lane or "")


def _pc_not_execution_lane(_p, ev, _c, _n):
    lane = str(ev.get("lane") or "")
    return not _refusal_lane(lane), lane or ""


def _pc_lock_path_recorded(_p, ev, _c, _n):
    p = ev.get("lock_path")
    return bool(isinstance(p, str) and p.strip()), str(p or "")


def _pc_owner_pid_recorded(_p, ev, _c, _n):
    pid, _alive = _pid_state(ev)
    return pid is not None, str(pid if pid is not None else ev.get("owner_pid", ""))


def _pc_owner_pid_dead(_p, ev, _c, _n):
    pid, alive = _pid_state(ev)
    if pid is None:
        return False, "no recorded owner pid"
    if alive is None:
        return False, f"pid {pid}: liveness unknowable"
    return (not alive), f"pid {pid} alive={alive}"


def _pc_lock_age_recorded(_p, ev, _c, _n):
    age = ev.get("lock_age_s")
    return isinstance(age, (int, float)) and not isinstance(age, bool) and age >= 0, str(age)


def _pc_lock_age_gt_lane_timeout(_p, ev, contract, _n):
    age = ev.get("lock_age_s")
    if not isinstance(age, (int, float)) or isinstance(age, bool):
        return False, "no recorded lock age"
    timeout = _lane_timeout_s(ev, contract)
    if timeout is None:
        return False, "no lane timeout recorded"
    return float(age) > timeout, f"age {float(age):.0f}s > timeout {timeout:.0f}s"


def _pc_lock_kind_existence(_p, ev, _c, _n):
    kind = str(ev.get("lock_kind") or "").lower()
    if kind not in EXISTENCE_LOCK_KINDS:
        return False, (f"lock_kind={kind or 'unrecorded'}: a kernel flock is released when its holder dies and a "
                       "holder-less flock file blocks nothing (scripts/cleanup_stale_locks.sh); no file is removed")
    return True, kind


def _pc_retries_under_budget(p, ev, _c, _n):
    used = _int_field(ev, "retries_today", "deferrals_today", "attempts_today")
    if used is None:
        return False, "no retry count recorded (0 is a value, missing is not)"
    max_retries = p.get("max_retries", 3)
    return used < int(max_retries), f"{used}/{int(max_retries)} retries used today"


def _pc_data_age_measured(_p, ev, _c, now):
    age = _age_h(ev, now)
    return age is not None, "unmeasured" if age is None else f"{age:.2f} h"


def _pc_contract_freshness_present(_p, _ev, contract, _n):
    threshold = _freshness_threshold_h(contract)
    return threshold is not None, "no freshness threshold in the health contract" if threshold is None else f"{threshold} h"


def _pc_data_is_late(_p, ev, contract, now):
    age = _age_h(ev, now)
    threshold = _freshness_threshold_h(contract)
    if age is None or threshold is None:
        return False, "late cannot be proven without an age and a contract threshold"
    return age > threshold, f"age {age:.2f} h > threshold {threshold} h"


def _pc_rerun_not_used_today(_p, ev, _c, _n):
    used = _int_field(ev, "reruns_today")
    if used is None:
        used = 0
    return used < 1, f"{used} rerun(s) used today"


PRECONDITIONS = {
    "lane_present": _pc_lane_present,
    "not_execution_lane": _pc_not_execution_lane,
    "lock_path_recorded": _pc_lock_path_recorded,
    "owner_pid_recorded": _pc_owner_pid_recorded,
    "owner_pid_dead": _pc_owner_pid_dead,
    "lock_age_recorded": _pc_lock_age_recorded,
    "lock_age_gt_lane_timeout": _pc_lock_age_gt_lane_timeout,
    "lock_kind_existence": _pc_lock_kind_existence,
    "retries_under_budget": _pc_retries_under_budget,
    "data_age_measured": _pc_data_age_measured,
    "contract_freshness_present": _pc_contract_freshness_present,
    "data_is_late": _pc_data_is_late,
    "rerun_not_used_today": _pc_rerun_not_used_today,
}


# ---------------------------------------------------------------- matching


def _matches(entry: Mapping[str, Any], failure_class: str, evidence: Mapping[str, Any]) -> bool:
    match = _mapping(entry.get("match"))
    classes = {str(c).strip().lower() for c in match.get("failure_class") or []}
    fc = str(failure_class or "").strip().lower()
    if fc and fc in classes:
        return True
    text = _text(evidence)
    reason_text = "\n".join(str(evidence.get(k) or "") for k in ("reason", "failure_kind", "detail"))
    for pat in match.get("reason_regex") or []:
        if re.search(pat, reason_text):
            return True
    for pat in match.get("exception_regex") or []:
        if re.search(pat, text):
            return True
    return False


def match_entry(
    failure_class: str, evidence: Mapping[str, Any], catalog: Mapping[str, Mapping[str, Any]]
) -> tuple[Optional[Mapping[str, Any]], list[str]]:
    """The winning entry (lowest explicit priority, id tiebreak) and the other matching ids, in order."""
    hits = [e for e in catalog.values() if _matches(e, failure_class, evidence)]
    hits.sort(key=lambda e: (int(e["priority"]), str(e["id"])))
    if not hits:
        return None, []
    return hits[0], [str(e["id"]) for e in hits[1:]]


def _is_fallback(entry: Mapping[str, Any]) -> bool:
    match = _mapping(entry.get("match"))
    return not any(match.get(k) for k in ("failure_class", "reason_regex", "exception_regex"))


# ---------------------------------------------------------------- planning


def _idempotency_key(entry: Mapping[str, Any], evidence: Mapping[str, Any], signature: str, now: datetime,
                     attempt: int) -> str:
    material: dict[str, Any] = {
        "entry": entry.get("id"),
        "lane": evidence.get("lane"),
        "signature": signature,
        "day": now.astimezone(timezone.utc).strftime("%Y-%m-%d"),
    }
    action = entry.get("action")
    if action == "release_stale_flock":
        material.update(lock_path=evidence.get("lock_path"), owner_pid=evidence.get("owner_pid"),
                        lock_age_s=evidence.get("lock_age_s"))
    elif action == "defer_until":
        material["attempt"] = attempt
    blob = json.dumps(material, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _jitter(seed: str, jitter_s: float) -> float:
    if jitter_s <= 0:
        return 0.0
    raw = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12], 16)
    return float(raw % (int(jitter_s * 1000) + 1)) / 1000.0


def plan_runbook(
    failure_class: str,
    evidence: Mapping[str, Any],
    contract: Optional[Mapping[str, Any]],
    now: Any,
    *,
    catalog: Optional[Mapping[str, Mapping[str, Any]]] = None,
    state: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Select one runbook and evaluate its checks. Pure; the only I/O is loading the default catalog once.

    ``state`` is the caller's durable per-lane facts (attempts, last action time); ``evidence`` may carry the same
    keys, which take precedence (the fixer already merges the receipt into the incident).
    """
    cat = catalog if catalog is not None else load_catalog()
    ev = dict(_as_mapping(evidence))
    ctr = dict(_as_mapping(contract))
    st = _as_mapping(state)
    for key, val in st.items():
        ev.setdefault(key, val)
    t = _now(now)
    fc = str(failure_class or "")
    signature = _signature(fc, ev)
    lane = str(ev.get("lane") or "")
    entry, alternates = match_entry(fc, ev, cat)
    if entry is None:  # unreachable with a validated catalog holding the catch-all; kept fail-closed
        fallback = next(e for e in cat.values() if _is_fallback(e))
        entry = fallback
        alternates = []
    checks: list[dict[str, Any]] = []
    attempts = _int_field(ev, "attempts") or 0
    max_attempts = int(entry.get("max_attempts", DEFAULT_MAX_ATTEMPTS))
    action = str(entry["action"])
    reason = ""
    tier = str(entry["tier"])
    ambiguous = False
    if alternates:
        second = cat.get(alternates[0])
        if second is not None and int(second["priority"]) == int(entry["priority"]):
            ambiguous = True
    checks.append({"check": "entry_match", "ok": entry is not None,
                   "detail": f"{entry['id']} (priority {entry['priority']})"})
    if ambiguous:
        checks.append({"check": "unambiguous_match", "ok": False,
                       "detail": f"priority {entry['priority']} shared with {alternates[0]}"})
    else:
        checks.append({"check": "unambiguous_match", "ok": True, "detail": ""})
    # budget + cooldown + hourly rate limit come before preconditions: an exhausted runbook never probes further.
    if attempts >= max_attempts and action != "escalate_finding":
        action, reason = "escalate_finding", f"max_attempts_reached ({attempts}/{max_attempts})"
        checks.append({"check": "attempt_budget", "ok": False, "detail": reason})
    else:
        checks.append({"check": "attempt_budget", "ok": True, "detail": f"{attempts}/{max_attempts}"})
    cooldown_min = int(entry.get("cooldown_min", DEFAULT_COOLDOWN_MIN))
    last_attempt = _parse_ts(ev.get("entry_last_attempt_at") or ev.get("last_attempt_at"))
    if cooldown_min and last_attempt is not None and action not in ("escalate_finding", "noop_wait_recheck"):
        gap = (t - last_attempt).total_seconds() / 60.0
        if gap < cooldown_min:
            action, reason = "none", f"cooldown_active ({gap:.1f} < {cooldown_min} min)"
            checks.append({"check": "entry_cooldown", "ok": False, "detail": reason})
        else:
            checks.append({"check": "entry_cooldown", "ok": True, "detail": f"{gap:.1f} min"})
    else:
        checks.append({"check": "entry_cooldown", "ok": True, "detail": "not required"})
    last_action = _parse_ts(ev.get("lane_last_action_at") or ev.get("last_action_at"))
    if last_action is not None and action not in NON_MUTATING_ACTIONS + ("none",):
        gap = (t - last_action).total_seconds()
        if gap < RATE_LIMIT_S:
            action, reason = "none", f"rate_limited ({gap:.0f}s < {RATE_LIMIT_S:.0f}s since the lane's last action)"
            checks.append({"check": "lane_rate_limit", "ok": False, "detail": reason})
        else:
            checks.append({"check": "lane_rate_limit", "ok": True, "detail": f"{gap:.0f}s"})
    else:
        checks.append({"check": "lane_rate_limit", "ok": True, "detail": "not required"})
    # the execution-lane rail is global: no catalog entry can opt out of it
    if action not in ("none", "escalate_finding", "noop_wait_recheck") and _refusal_lane(lane):
        action, reason = "none", f"refused_execution_lane ({lane})"
        checks.append({"check": "not_execution_lane", "ok": False, "detail": lane})
    elif action not in ("none", "escalate_finding"):
        checks.append({"check": "not_execution_lane", "ok": True, "detail": lane})
    # preconditions, in the entry's declared order; the first failure refuses the action
    entry_params = dict(entry.get("params") or {})
    if action not in ("none", "escalate_finding"):
        for item in entry.get("preconditions") or []:
            name = item if isinstance(item, str) else str((item or {}).get("check"))
            params = dict(entry_params)
            if isinstance(item, Mapping):
                params.update(item)
            ok, detail = PRECONDITIONS[name](params, ev, ctr, t)
            checks.append({"check": name, "ok": bool(ok), "detail": detail})
            if not ok:
                action, reason = "none", f"precondition_failed:{name}"
                break
    if tier == "human_only" and action not in ("escalate_finding", "none"):
        action, reason = "escalate_finding", "tier_human_only"
    attempt = attempts + 1
    key = _idempotency_key(entry, ev, signature, t, attempt)
    params = dict(entry.get("params") or {})
    next_attempt_at = None
    if action == "defer_until":
        delay = float(params.get("delay_s", 300.0))
        jitter_s = float(params.get("jitter_s", DEFAULT_JITTER_S))
        next_attempt_at = (t + timedelta(seconds=delay + _jitter(key, jitter_s))).isoformat()
    elif action == "rerun_once_via_gateway":
        next_attempt_at = (t + timedelta(seconds=float(params.get("delay_s", 0.0)))).isoformat()
    elif action == "noop_wait_recheck":
        next_attempt_at = (t + timedelta(seconds=float(params.get("wait_s", 300.0)))).isoformat()
    elif action == "open_breaker_cooldown":
        next_attempt_at = (t + timedelta(seconds=float(params.get("cooldown_s", 900.0)))).isoformat()
    on_fail = dict(entry.get("on_fail") or {})
    plan = {
        "schema": PLAN_SCHEMA,
        "at": t.isoformat(),
        "lane": lane,
        "failure_class": fc,
        "signature": signature,
        "entry": str(entry["id"]),
        "entry_title": str(entry["title"]),
        "category": str(entry["category"]),
        "tier": tier,
        "fallback": _is_fallback(entry),
        "ambiguous": ambiguous,
        "alternates": alternates,
        "action": action,
        "entry_action": str(entry["action"]),
        "reason": reason or "ok",
        "checks": checks,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "cooldown_min": cooldown_min,
        "next_attempt_at": next_attempt_at,
        "verify": dict(entry.get("verify") or {}),
        "on_fail": on_fail,
        "human_steps": list(entry.get("human_steps") or []),
        "idempotency_key": key,
    }
    if action in ("rerun_once_via_gateway", "defer_until"):
        plan["next_attempt_at"] = plan["next_attempt_at"] or (t + timedelta(
            seconds=float(params.get("delay_s", 300.0)))).isoformat()
    plan["_apply"] = {
        "params": params,
        "lock_path": ev.get("lock_path"),
        "lock_kind": str(ev.get("lock_kind") or "").lower(),
        "owner_pid": ev.get("owner_pid"),
    }
    return plan


# ---------------------------------------------------------------- applying


def _render(text: str, plan: Mapping[str, Any]) -> str:
    try:
        return str(text).format(**{k: plan.get(k) for k in
                                   ("lane", "entry", "entry_title", "failure_class", "signature", "reason",
                                    "attempt", "max_attempts", "category")})
    except (KeyError, ValueError):
        return str(text)


def _finding_text(plan: Mapping[str, Any]) -> str:
    on_fail = _mapping(plan.get("on_fail"))
    title = _render(str(on_fail.get("title") or f"self-heal runbook exhausted: {plan.get('entry_title')}"), plan)
    body = str(on_fail.get("text") or "The runbook's preconditions or its attempt budget refused every action.")
    steps = plan.get("human_steps") or []
    lines = [f"# FINDING — {title}", "",
             f"- lane: {plan.get('lane') or '(unknown)'}",
             f"- class: {plan.get('failure_class') or '(unknown)'}",
             f"- runbook: {plan.get('entry')} ({plan.get('category')})",
             f"- plan reason: {plan.get('reason')}",
             f"- attempts: {plan.get('attempt')}/{plan.get('max_attempts')}",
             "", _render(body, plan), ""]
    if steps:
        lines.append("## Human steps")
        lines.extend(f"- `{s}`" for s in steps)
    return "\n".join(lines) + "\n"


def _forbidden_lock_path(path: Path) -> Optional[str]:
    """A reason to refuse an archive of this path, or None. The plan is a claim; this is the last gate."""
    if not path.is_absolute():
        return "lock path is not absolute"
    if NEVER_TOUCH_PATH_PARTS & set(path.parts):
        return "lock path is inside a never-touch path"
    text = str(path)
    if any(text.startswith(root) for root in NEVER_TOUCH_PATH_ROOTS):
        return "lock path is a system path"
    if path.name.startswith(".env") or "credential" in path.name.lower() or "token" in path.name.lower():
        return "lock path looks like a credential"
    return None


def _probe_lock(path: Path) -> str:
    """A non-blocking exclusive probe: 'free' when no live holder exists, 'held' otherwise.

    The kernel releases a flock when its holder exits, so for a flock-kind file 'free' means there is nothing to
    release; for an existence lock it means the pidfile is genuinely orphaned and may be archived.
    """
    import fcntl  # local import: the module stays importable and pure on non-POSIX test hosts

    try:
        fd = os.open(str(path), os.O_RDONLY)
    except FileNotFoundError:
        return "absent"
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            return "held"
        return "free"
    finally:
        os.close(fd)


def apply_runbook(plan: Mapping[str, Any], *, dry_run: bool = True, now: Any = None) -> dict[str, Any]:
    """Execute only the plan's primitive. Dry run (the default) touches nothing and says what it would do.

    Returns a SelfHealRunbookReceipt@v1 for the caller to persist. The only host mutation is archiving an
    existence-based lock whose recorded owner is dead, whose age exceeds the lane timeout, and whose non-blocking
    probe is free; a plan that fails those checks is refused again here (the plan is a claim, not an authority).
    """
    if not isinstance(plan, Mapping) or plan.get("schema") != PLAN_SCHEMA:
        raise RunbookPlanError("not a SelfHealRunbookPlan@v1")
    t = _now(now)
    action = str(plan.get("action") or "none")
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "at": t.isoformat(),
        "lane": plan.get("lane"),
        "entry": plan.get("entry"),
        "category": plan.get("category"),
        "action": action,
        "reason": plan.get("reason"),
        "dry_run": bool(dry_run),
        "idempotency_key": plan.get("idempotency_key"),
        "action_taken": "none",
        "wrote": False,
        "verify": dict(plan.get("verify") or {}),
        "human_steps": list(plan.get("human_steps") or []),
        "finding_text": None,
    }
    if action == "none":
        return receipt
    if dry_run:
        receipt["action_taken"] = f"would_{action}"
        if action in ("defer_until", "rerun_once_via_gateway", "noop_wait_recheck"):
            receipt["next_attempt_at"] = plan.get("next_attempt_at")
        return receipt
    if action == "release_stale_flock":
        info = _mapping(plan.get("_apply"))
        path = Path(str(info.get("lock_path") or ""))
        if not path.name:
            receipt.update(action_taken="refused", reason="no lock path in the plan")
            return receipt
        forbidden = _forbidden_lock_path(path)
        if forbidden:
            receipt.update(action_taken="refused", reason=forbidden)
            return receipt
        probe = _probe_lock(path)
        receipt["lock_probe"] = probe
        if probe == "absent":
            receipt["action_taken"] = "lock_absent"
            return receipt
        if probe == "held":
            receipt.update(action_taken="lock_held_refused",
                           reason="a live holder exists now; the stale-lock claim is no longer true")
            return receipt
        kind = str(info.get("lock_kind") or "").lower()
        if kind not in EXISTENCE_LOCK_KINDS:
            receipt.update(action_taken="lock_free",
                           reason="flock-kind lock: no live holder and nothing to remove; a holder-less flock file "
                                  "blocks nothing (scripts/cleanup_stale_locks.sh)")
            return receipt
        stamp = t.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archived = path.with_name(f"{path.name}.stale-{stamp}")
        try:
            os.replace(path, archived)
        except OSError as exc:
            receipt.update(action_taken="refused", reason=f"archive_failed: {type(exc).__name__}")
            return receipt
        receipt.update(action_taken="stale_lock_archived", wrote=True, archived_to=str(archived))
        return receipt
    if action == "release_stale_sqlite_wal_lock":
        receipt.update(action_taken="sqlite_lock_reported",
                       reason="reported only: this primitive never removes a WAL/SHM file; the human step names "
                              "the risk")
        return receipt
    if action == "defer_until":
        receipt.update(action_taken="deferred", next_attempt_at=plan.get("next_attempt_at"))
        return receipt
    if action == "rerun_once_via_gateway":
        receipt.update(action_taken="rerun_requested", via="coordination_gateway",
                       next_attempt_at=plan.get("next_attempt_at"))
        return receipt
    if action == "noop_wait_recheck":
        receipt.update(action_taken="noop", next_attempt_at=plan.get("next_attempt_at"))
        return receipt
    if action == "open_breaker_cooldown":
        receipt.update(action_taken="cooldown", next_attempt_at=plan.get("next_attempt_at"))
        return receipt
    if action == "mark_weekend_expected":
        receipt.update(action_taken="expected_window_marked")
        return receipt
    if action == "escalate_finding":
        receipt.update(action_taken="escalation_rendered", finding_text=_finding_text(plan))
        return receipt
    receipt.update(action_taken="refused", reason=f"unreachable action {action}")
    return receipt
