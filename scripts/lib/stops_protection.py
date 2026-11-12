"""Stop Management protection logic (LQ-20261107-2166, Portfolio G3). Pure functions, no I/O.

Rules (DECISIONS-20261111): unknown beats wrong. A source that could not be read is UNKNOWN, never "no stop".
  * OK      every counted position has a verified resting stop AND every source was read.
  * UNKNOWN any broker/stop source unreadable, or any counted position cannot be verified. Blocks OK.
  * GAP     a good read exists and a counted position has no resting stop.
Exempt by default: cash, money-market funds, sweep vehicles. ETFs/CEFs/mutual funds/stocks are NOT exempt.
Positions under MIN_COUNTED_VALUE are listed, not counted, not hidden.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Iterable, Mapping

MIN_COUNTED_VALUE = 100.0  # the one shared floor (REPORT G14)
SNAPSHOT_MAX_AGE_S = 30 * 60  # stop_health_check runs every 10 min in market hours; 3 missed runs = stale
EXEMPT_SYMBOLS = frozenset({"", "CASH", "USD", "SPAXX", "FDRXX", "FZFXX", "VMFXX", "SWVXX", "SNSXX", "SWEEP"})
OWNER = "stop_health_check (cron */10 9-16) / Stop Management"

OK, STALE, UNKNOWN, GAP, ACTIVE = "OK", "STALE", "UNKNOWN", "GAP", "ACTIVE"
# pending_activation resting GTC stops count as protected (G1); finished orders do not.
RESTING_STATES = frozenset({"working", "open", "accepted", "queued", "pending_activation", "new", "active", "armed", "awaiting_stop_condition"})


def _num(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def is_exempt(h: Mapping[str, Any]) -> bool:
    sym = str(h.get("symbol") or "").upper()
    return bool(h.get("is_cash")) or bool(h.get("is_money_market")) or sym in EXEMPT_SYMBOLS


def counted(h: Mapping[str, Any]) -> bool:
    """True when the position enters the protection rollup (non-exempt, shares>0, value >= floor)."""
    if is_exempt(h) or (_num(h.get("shares")) or 0.0) <= 0:
        return False
    val = _num(h.get("market_value"))
    if val is None:
        px, sh = _num(h.get("current_price")) or _num(h.get("price")), _num(h.get("shares"))
        val = px * sh if px is not None and sh is not None else None
    # an unpriced position cannot be shown to be under the floor: count it (unknown beats hidden)
    return True if val is None else val >= MIN_COUNTED_VALUE


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
    banner; a stored-mode view never claims a failed read it did not attempt."""
    return any(r["state"] == UNKNOWN for r in rows)


def stop_state(has_resting_stop: bool, *, sources_ok: bool) -> str:
    """Per-row: ACTIVE when a resting stop exists; GAP only when the read was good; else UNKNOWN."""
    if has_resting_stop:
        return ACTIVE
    return GAP if sources_ok else UNKNOWN


def rollup(positions: Iterable[Mapping[str, Any]], row_states: Mapping[Any, str], broker_state_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Portfolio protection verdict. row_states maps (symbol, account) -> ACTIVE/GAP/UNKNOWN."""
    n_counted = n_listed_only = n_gap = n_unknown = n_active = 0
    for h in positions:
        if is_exempt(h):
            continue
        if not counted(h):
            n_listed_only += 1
            continue
        n_counted += 1
        s = row_states.get((str(h.get("symbol") or "").upper(), str(h.get("account") or "")), UNKNOWN)
        if s == ACTIVE:
            n_active += 1
        elif s == GAP:
            n_gap += 1
        else:
            n_unknown += 1
    src_bad = [r["broker"] for r in broker_state_rows if r["state"] in (UNKNOWN, STALE)]
    if n_gap:
        verdict = GAP  # a good read showed a position with no resting stop: that is known, report it
    elif n_unknown or src_bad:
        verdict = UNKNOWN  # an unreadable/stale source cannot verify protection
    else:
        verdict = OK
    return {"verdict": verdict, "counted": n_counted, "active": n_active, "gap": n_gap, "unknown": n_unknown,
            "listed_not_counted": n_listed_only, "min_counted_value": MIN_COUNTED_VALUE,
            "unverified_brokers": src_bad}
