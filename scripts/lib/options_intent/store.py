"""Operator options intents — standing memory of what the operator wants to do with options on a name.

Operator 2026-10-05 (SPCX via Telegram): "this should be in [persistent] memory right now. And in the
command center, it should be working on pulling particular contracts that meet what I'm asking for."

Where it lives: the operator's ticker directive for the symbol, as `spec.options_intent`. One
directive per subject (watch_directives dedups ticker rows by symbol, and its kind CHECK allows only
ticker/sector/trend), so the intent rides on the subject the operator already watches instead of a
second row the dedup rule would fold. All writes go through lib/writers/watch_directives_writer —
the one writer for that store.

Intent shape (spec.options_intent):
  {symbol, status: active|paused|archived, thesis_target, thesis_source, goals: [...],
   plays: {cash_secured_put: {dte:[lo,hi], strike_max, delta:[lo,hi], max_contracts, accounts},
           covered_call:     {dte:[lo,hi], min_strike | keep_upside_pct, delta:[lo,hi], accounts, max_contracts},
           leap_call:        {min_dte, min_delta}},
   avoid_earnings_cross, earnings_estimate, rationale, created_at, updated_at, created_by}
Advisory only. Nothing here sizes, orders or touches a broker (MBI_BEHAVIOR = 0).
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from lib.writers import watch_directives_writer as wdw
except ModuleNotFoundError:  # imported as scripts.lib...
    from scripts.lib.writers import watch_directives_writer as wdw  # type: ignore

INTENT_KEY = "options_intent"
STATUSES = ("active", "paused", "archived")
PLAYS = ("cash_secured_put", "covered_call", "leap_call")
_SYM = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

SELECT_SQL = ("SELECT id, label, spec, status FROM watch_directives "
              "WHERE kind = 'ticker' AND status = 'active' AND spec ? 'options_intent' ORDER BY id")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _range(v: Any, name: str) -> Optional[List[float]]:
    if v is None:
        return None
    if isinstance(v, str):
        a, _, b = v.partition("-")
        v = [a, b or a]
    try:
        lo, hi = float(v[0]), float(v[1])
    except (TypeError, ValueError, IndexError):
        raise ValueError(f"{name} must be [lo, hi]")
    if not math.isfinite(lo) or not math.isfinite(hi):
        raise ValueError(f"{name}: finite numbers required")
    if lo > hi:
        raise ValueError(f"{name}: lo > hi")
    return [lo, hi]


def validate_intent(intent: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise and check an intent. Raises ValueError with the first problem found."""
    i = dict(intent or {})
    sym = str(i.get("symbol") or "").strip().upper()
    if not _SYM.match(sym):
        raise ValueError(f"symbol not plausible: {sym!r}")
    i["symbol"] = sym
    i["status"] = str(i.get("status") or "active")
    if i["status"] not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    if i.get("thesis_target") is not None:
        i["thesis_target"] = float(i["thesis_target"])
        if not math.isfinite(i["thesis_target"]) or i["thesis_target"] <= 0:
            raise ValueError("thesis_target must be a finite positive price")
    plays = dict(i.get("plays") or {})
    if not plays:
        raise ValueError("at least one play is required (cash_secured_put / covered_call / leap_call)")
    for name, p in plays.items():
        if name not in PLAYS:
            raise ValueError(f"unknown play {name!r}; known: {PLAYS}")
        p = dict(p or {})
        for k in ("dte", "delta"):
            if k in p:
                p[k] = _range(p[k], f"{name}.{k}")
                if p[k] and (p[k][0] < (1 if k == "dte" else 0) or p[k][1] > (3650 if k == "dte" else 1)):
                    raise ValueError(f"{name}.{k}: range out of bounds")
        for k in ("strike_max", "min_strike", "keep_upside_pct", "min_delta"):
            if p.get(k) is not None:
                p[k] = float(p[k])
                if not math.isfinite(p[k]) or p[k] <= 0 or (k == "min_delta" and p[k] > 1):
                    raise ValueError(f"{name}.{k}: invalid positive value")
        for k in ("max_contracts", "min_dte"):
            if p.get(k) is not None:
                value = float(p[k])
                if not math.isfinite(value) or not value.is_integer() or value <= 0:
                    raise ValueError(f"{name}.{k}: positive whole number required")
                p[k] = int(value)
        if p.get("accounts") is not None and not isinstance(p["accounts"], dict):
            raise ValueError(f"{name}.accounts must map account -> contracts")
        plays[name] = p
    i["plays"] = plays
    i["goals"] = [str(g) for g in (i.get("goals") or [])]
    i["avoid_earnings_cross"] = bool(i.get("avoid_earnings_cross", False))
    i["rationale"] = str(i.get("rationale") or "")[:2000]
    return i


def _spec(row: Any) -> Dict[str, Any]:
    s = row.get("spec") if isinstance(row, dict) else (row[2] if len(row) > 2 else None)
    if isinstance(s, (str, bytes)):
        try:
            s = json.loads(s)
        except ValueError:
            s = {}
    return s if isinstance(s, dict) else {}


def load_intents(cur, *, include_inactive: bool = False) -> List[Dict[str, Any]]:
    """Active operator options intents (directive id attached). Read-only SELECT."""
    cur.execute(SELECT_SQL)
    out = []
    for r in cur.fetchall() or []:
        spec = _spec(r)
        it = spec.get(INTENT_KEY)
        if not isinstance(it, dict):
            continue
        if not include_inactive and it.get("status", "active") != "active":
            continue
        did = r.get("id") if isinstance(r, dict) else r[0]
        out.append({**it, "directive_id": did})
    return out


_UNCHECKED = object()


def upsert_intent(target: Any, intent: Dict[str, Any], *, source: str = "operator",
                  apply: bool = False, expected_updated_at: Any = _UNCHECKED) -> Dict[str, Any]:
    """Attach `intent` to the symbol's ticker directive (create one if none). Dry run by default:
    returns what would be written. With apply=True writes through watch_directives_writer."""
    it = validate_intent(intent)
    it.setdefault("created_at", _now())
    it["updated_at"] = _now()
    it.setdefault("created_by", source)
    found = wdw.find_existing_directive(target, "ticker", f"watch {it['symbol']}", {"symbol": it["symbol"]})
    plan: Dict[str, Any] = {"symbol": it["symbol"], "intent": it, "apply": apply}
    if not found and expected_updated_at not in (_UNCHECKED, None):
        raise ValueError("Standing plan changed since preview; preview again")
    if found:
        t = wdw._Target(target)
        row = t.run("SELECT spec FROM watch_directives WHERE id = %s" + (" FOR UPDATE" if apply else ""), (found["id"],), fetch="one")
        spec = _spec({"spec": (row.get("spec") if isinstance(row, dict) else (row[0] if row else None))})
        prev = spec.get(INTENT_KEY)
        if expected_updated_at is not _UNCHECKED and (prev or {}).get("updated_at") != expected_updated_at:
            raise ValueError("Standing plan changed since preview; preview again")
        if isinstance(prev, dict) and prev.get("created_at"):
            it["created_at"] = prev["created_at"]
        new_spec = {**spec, "symbol": it["symbol"], INTENT_KEY: it}
        plan.update(action="update", directive_id=found["id"], previous_intent=prev)
        if apply:
            rec = wdw.update_watch_directive(target, found["id"], source=source, spec=new_spec,
                                             last_confirmed_at=wdw.NOW,
                                             rationale_append=f" | options intent {it['updated_at'][:10]}")
            plan["receipt"] = rec.as_dict()
        return plan
    row = {"kind": "ticker", "label": f"Options intent · {it['symbol']}",
           "spec": {"symbol": it["symbol"], INTENT_KEY: it},
           "rationale": it["rationale"] or "operator options intent", "created_by": source,
           "priority": "high", "ttl_days": None}
    plan.update(action="insert", row=row)
    if apply:
        rec = wdw.write_watch_directives(target, [row], source=source, on_duplicate="reuse_exact")
        plan["receipt"] = rec.as_dict()
    return plan


def set_intent_status(target: Any, symbol: str, status: str, *, source: str = "operator",
                      apply: bool = False) -> Dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    sym = str(symbol).upper()
    found = wdw.find_existing_directive(target, "ticker", f"watch {sym}", {"symbol": sym})
    if not found:
        return {"symbol": sym, "action": "none", "reason": "no ticker directive for symbol"}
    t = wdw._Target(target)
    row = t.run("SELECT spec FROM watch_directives WHERE id = %s", (found["id"],), fetch="one")
    spec = _spec({"spec": (row.get("spec") if isinstance(row, dict) else (row[0] if row else None))})
    it = spec.get(INTENT_KEY)
    if not isinstance(it, dict):
        return {"symbol": sym, "action": "none", "reason": "no options intent on the directive"}
    it = {**it, "status": status, "updated_at": _now()}
    plan = {"symbol": sym, "action": "status", "directive_id": found["id"], "status": status, "apply": apply}
    if apply:
        rec = wdw.update_watch_directive(target, found["id"], source=source, spec={**spec, INTENT_KEY: it})
        plan["receipt"] = rec.as_dict()
    return plan
