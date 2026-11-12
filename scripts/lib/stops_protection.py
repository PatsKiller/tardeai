"""Stop Management protection logic (LQ-20261107-2166 / 2181, Portfolio G3). Pure functions, no I/O.

ONE position universe and ONE per-row verdict: cio_truth.resolve (LQ-2165) classifies every row PROTECTED | GAP |
UNKNOWN | EXEMPT (``protection_state`` + ``protection``). This module never re-derives a row; it
  * grades the stop_lifecycle snapshot and the per-broker read state (R11 rows),
  * rolls the per-row states up to ``protection_summary`` (GAP beats UNKNOWN beats OK; OK only if every counted row
    is PROTECTED and every source was read).
Exemptions, the $100 floor and "no stop read source" are 2165's (cio_truth._exempt_kind, COUNT_FLOOR_USD,
STOP_READ_BROKERS); nothing here duplicates them.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Iterable, Mapping

SNAPSHOT_MAX_AGE_S = 30 * 60  # stop_health_check runs every 10 min in market hours; 3 missed runs = stale
OWNER = "stop_health_check (cron */10 9-16) / Stop Management"

OK, STALE, UNKNOWN, GAP, PROTECTED, EXEMPT = "OK", "STALE", "UNKNOWN", "GAP", "PROTECTED", "EXEMPT"


def _num(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def snapshot_age_s(snapshot_at: Any, now: _dt.datetime | None = None) -> float | None:
    """Age in seconds of a snapshot timestamp; None when absent/unparseable (never a made-up 0)."""
    if snapshot_at is None or snapshot_at == "":
        return None
    now = now or _dt.datetime.now(_dt.timezone.utc)
    t = snapshot_at
    if isinstance(t, str):
        try:
            t = _dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(t, _dt.datetime):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.timezone.utc)
    return max(0.0, (now - t).total_seconds())


def grade_snapshot(rows: Iterable[Mapping[str, Any]] | None, now: _dt.datetime | None = None,
                   max_age_s: float = SNAPSHOT_MAX_AGE_S) -> dict[str, Any]:
    """Grade the stop_lifecycle snapshot. rows None = the read failed (UNKNOWN); [] = read fine, no rows.
    Age is the NEWEST snapshot_at. Stale or ageless => never broker_verified."""
    if rows is None:
        return {"state": UNKNOWN, "age_s": None, "as_of": None, "broker_verified": False,
                "cause": "stop_lifecycle snapshot unreadable"}
    rows = list(rows)
    ages = [a for a in (snapshot_age_s(r.get("snapshot_at"), now) for r in rows) if a is not None]
    if not ages:
        return {"state": UNKNOWN, "age_s": None, "as_of": None, "broker_verified": False,
                "cause": "stop_lifecycle snapshot has no timestamp" if rows else "stop_lifecycle snapshot is empty"}
    age = min(ages)
    stale = age > max_age_s
    return {"state": STALE if stale else OK, "age_s": round(age), "as_of": None, "broker_verified": not stale,
            "cause": f"stop_lifecycle snapshot is {round(age / 60)} min old (limit {round(max_age_s / 60)})" if stale else None}


def broker_rows(live_meta: Mapping[str, Any], snapshot: Mapping[str, Any], brokers: Iterable[str],
                *, stored_only: bool, fidelity_manual_ok: bool = True) -> list[dict[str, Any]]:
    """Per-broker OK/STALE/UNKNOWN with Cause/Source/Owner (R11). Replaces the page-wide red banner.
    stored_only: the page never reads the broker, so the verdict comes from the snapshot's age.
    Live mode: a failed/degraded live read is UNKNOWN for that broker, with last-good marked STALE."""
    out = []
    for b in sorted(set(brokers)):
        if b == "fidelity":
            st = OK if fidelity_manual_ok else UNKNOWN
            out.append({"broker": b, "state": st, "source": "manual_broker_stops + fidelity_monitored_stops",
                        "cause": None if st == OK else "manual_broker_stops unreadable", "owner": OWNER, "age_s": None})
            continue
        from .cio_truth import has_stop_read_source

        if not has_stop_read_source(b):  # Moomoo/Alpaca: nothing is ever read, so nothing can be verified (never OK)
            out.append({"broker": b, "state": UNKNOWN, "source": "none", "cause": "No Stop Read", "owner": OWNER, "age_s": None})
            continue
        if stored_only:
            st, cause, age, src = snapshot["state"], snapshot.get("cause"), snapshot.get("age_s"), "stop_lifecycle snapshot"
        else:
            read_ok = bool(live_meta.get("live_read_ok")) and not live_meta.get("degraded")
            acct_status = (live_meta.get("read_status") or {})
            bad = [a for a, v in acct_status.items() if str(a).startswith(b) and v not in (True, "ok", "OK", "read_ok")]
            if read_ok and not bad:
                st, cause, age, src = OK, None, 0, "live broker order read"
            else:
                # live read failed: last-good snapshot is shown, flagged STALE, and never broker_verified
                st = UNKNOWN
                cause = live_meta.get("error") or ("live read degraded for " + ", ".join(map(str, bad)) if bad else "live read failed")
                age, src = snapshot.get("age_s"), "live broker order read (failed); last-good snapshot STALE"
        out.append({"broker": b, "state": st, "source": src, "cause": cause, "owner": OWNER, "age_s": age})
    return out


def banner_degraded(rows: Iterable[Mapping[str, Any]], *, stored_only: bool) -> bool:
    """Legacy red-banner flag. True ONLY for a real failed read (UNKNOWN). STALE alone is a quiet row, not a
    banner; a stored-mode view never claims a failed read it did not attempt. "No Stop Read" (a broker with no read
    source at all) is a standing fact shown on its row, not a failed read."""
    return any(r["state"] == UNKNOWN and r.get("cause") != "No Stop Read" for r in rows)


def attach(truth_rows: Iterable[Mapping[str, Any]] | None) -> dict[tuple[str, str], Mapping[str, Any]] | None:
    """cio_truth.resolve()['stops']['rows'] -> {(SYMBOL, canonical account): row}. None = resolve() was unreadable."""
    if truth_rows is None:
        return None
    from .account_display import canonical_key

    return {(str(r.get("symbol") or "").upper(), canonical_key(r.get("account_id"))): r for r in truth_rows}


def row_protection(index: Mapping[tuple[str, str], Mapping[str, Any]] | None, symbol: str, account: str) -> dict[str, Any]:
    """protection_state + protection for a management row, from the shared universe. A row resolve() does not know,
    or a resolve() that failed, is UNKNOWN with a cause: never a made-up GAP or PROTECTED."""
    from .account_display import canonical_key

    if index is None:
        cause, why = "Stop Read Failed", "cio_truth.resolve was unreadable"
    else:
        hit = index.get((str(symbol).upper(), canonical_key(account)))
        if hit is not None and hit.get("protection_state"):
            return {"protection_state": hit["protection_state"], "protection": hit.get("protection")}
        cause, why = "Not In Position Universe", "the row is not in cio_truth.resolve positions"
    return {"protection_state": UNKNOWN, "protection": {"state": UNKNOWN, "reason": why, "cause": cause,
                                                        "source": "none", "as_of": None, "counted": True}}


def summary(truth_rows: Iterable[Mapping[str, Any]] | None, broker_state_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """``protection_summary``: the rollup of 2165's per-row states (one universe).  Never reuses ``protection_state``."""
    broker_state_rows = list(broker_state_rows)
    unverified = [{"broker": r["broker"], "state": r["state"], "age_s": r.get("age_s"), "cause": r.get("cause")}
                  for r in broker_state_rows if r["state"] in (UNKNOWN, STALE)]
    if truth_rows is None:
        return {"verdict": UNKNOWN, "counted": None, "protected": None, "gap": None, "unknown": None,
                "listed_not_counted": None, "unverified_brokers": unverified, "cause": "cio_truth.resolve unreadable"}
    n = {PROTECTED: 0, GAP: 0, UNKNOWN: 0}
    listed = 0
    for r in truth_rows:
        st = r.get("protection_state")
        if st == EXEMPT:
            continue
        if not (r.get("protection") or {}).get("counted", True):
            listed += 1  # under the floor: listed with its real state, not counted, not hidden
            continue
        n[st if st in n else UNKNOWN] += 1
    if n[GAP]:
        verdict = GAP  # a good read showed a counted position with no resting stop: known, so reported
    elif n[UNKNOWN] or unverified:
        verdict = UNKNOWN
    else:
        verdict = OK
    return {"verdict": verdict, "counted": sum(n.values()), "protected": n[PROTECTED], "gap": n[GAP], "unknown": n[UNKNOWN],
            "listed_not_counted": listed, "unverified_brokers": unverified, "cause": None}
