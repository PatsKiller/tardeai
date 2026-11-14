"""GET /api/v2/home/priorities-live -> ``HomePrioritiesLive@v1`` (LQ-20261107-2644): the server's ranking of "Today's priorities".

Pure ranking over three reads the Home page already makes -- open incidents (``HomeIncidents@v1``), the stop advice in
the since-close brief, and the approvals summary -- so the page no longer says "No server ranking in this build".

Order (stated here, repeated in the body as ``order``; no weights, no score a reader cannot reproduce):

  1. P0 incident that blocks trading     4. approvals waiting (one row, with its urgent count)
  2. other P0 incident                   5. P1 incident that blocks trading
  3. stop advice: ADD_STOP, FIX_QTY,     6. other P1 incident
     RAISE (in that order)               7. UNCLASSIFIED incident (shown, never dropped)

Inside a tier the oldest first (an item that has waited longest). A stale incident (not re-observed inside its ttl) is
kept and labelled ``stale: true``; it does not move tier. An input that could not be read is named in ``unread`` and
the state is ``PARTIAL`` (or ``UNKNOWN`` when none could be read): a ranking over fewer inputs is never presented as a
complete one, and an empty list is only ever returned with ``state: OK`` (every input read, nothing to do).

``inputs`` (CAMPAIGN-8H Home item 4) is the population that claim stands on: one entry per input with ``read`` (bool),
``rows`` (how many rows that read returned, or null when it was not read) and ``reason``. It is what lets the page say
"0 ranked over incidents 12 rows / stop advice 3 rows / approvals 0 rows" instead of an unbacked "nothing needs you".
Writes nothing, never reaches a broker.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

SCHEMA = "HomePrioritiesLive@v1"
OK, PARTIAL, UNKNOWN = "OK", "PARTIAL", "UNKNOWN"
ORDER = ("P0 blocks trading", "P0", "stop advice", "approvals waiting", "P1 blocks trading", "P1", "unclassified")
STOP_RANK = {"ADD_STOP": 0, "FIX_QTY": 1, "RAISE": 2}
MAX_ITEMS = 50


def _incident_tier(i: dict) -> Optional[int]:
    pr = i.get("priority")
    if pr == "P0":
        return 0 if i.get("blocks_trading") else 1
    if pr == "P1":
        return 4 if i.get("blocks_trading") else 5
    if pr == "UNCLASSIFIED":
        return 6
    return None  # INFO etc.: not a priority


def _incident_items(body: Any) -> tuple[Optional[list[dict]], Optional[str]]:
    if not isinstance(body, dict) or body.get("state") != "OK" or not isinstance(body.get("items"), list):
        why = (body or {}).get("reason") if isinstance(body, dict) else None
        return None, str(why or "incidents not read")
    out = []
    for i in body["items"]:
        tier = _incident_tier(i)
        if tier is None:
            continue
        cause = i.get("cause")
        out.append({
            "tier": tier, "kind": "INCIDENT", "id": f"inc-{i.get('incident_id')}",
            "title": " · ".join(str(x) for x in (i.get("category") or i.get("alert_type"), i.get("symbol"),
                                                 i.get("account_label")) if x),
            "why": cause if cause and cause != "UNKNOWN" else "cause not recorded",
            "priority": i.get("priority"), "blocks_trading": bool(i.get("blocks_trading")),
            "since": i.get("first_seen_at"), "stale": bool(i.get("stale_condition")),
            "source": "alert_incidents", "owner": i.get("owner"), "goto": "card-action",
        })
    return out, None


def _stop_items(body: Any) -> tuple[Optional[list[dict]], Optional[str]]:
    brief = body.get("cio_brief") if isinstance(body, dict) else None
    if not isinstance(body, dict) or body.get("status") != "ok" or not isinstance(brief, dict) \
            or brief.get("status") != "available" or not isinstance(brief.get("stop_advice"), list):
        return None, "stop advice not read"
    read = brief.get("stop_read")
    if isinstance(read, dict) and read.get("status") == "unread":
        return None, "stop read failed"
    out = []
    for row in brief["stop_advice"]:
        if not isinstance(row, dict):
            continue
        kind = str(next((row[k] for k in ("answer", "verdict", "action", "recommendation") if row.get(k)), "")).upper()
        if kind not in STOP_RANK:
            continue
        sym = str(row.get("symbol") or row.get("ticker") or "").upper()
        if not sym:
            continue
        out.append({
            "tier": 2, "sub": STOP_RANK[kind], "kind": "STOP", "id": f"stop-{kind}-{sym}-{row.get('account') or ''}",
            "title": " · ".join(x for x in (kind.replace("_", " ").title(), sym, row.get("account")) if x),
            "why": str(row.get("reason") or row.get("what_happened") or row.get("event_summary") or "no reason recorded"),
            "priority": None, "blocks_trading": False, "since": brief.get("generated_at"), "stale": False,
            "source": "since_close.cio_brief.stop_advice", "owner": "risk", "goto": "card-action",
        })
    return out, None


def _approvals_items(body: Any) -> tuple[Optional[list[dict]], Optional[str]]:
    data = body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), dict) else body
    n = data.get("count") if isinstance(data, dict) else None
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        return None, "approvals count not read"
    if n == 0:
        return [], None
    urgent = data.get("urgent_count")
    urgent = urgent if isinstance(urgent, int) and not isinstance(urgent, bool) else None
    return [{
        "tier": 3, "kind": "APPROVALS", "id": "approvals", "count": n, "urgent_count": urgent,
        "title": f"{n} approval{'s' if n != 1 else ''} waiting",
        "why": f"{urgent} urgent (expire inside 2 h)" if urgent else "awaiting your decision",
        "priority": None, "blocks_trading": False, "since": None, "stale": False,
        "source": "home_approvals", "owner": "operator", "goto": "card-action",
    }], None


def rank(incidents: Any, stops: Any, approvals: Any, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """The ranked body over the three reads (each the endpoint's own body, or ``None``/garbage when unreadable)."""
    now = now or datetime.now(timezone.utc)
    items: list[dict] = []
    unread: list[dict] = []
    inputs: list[dict] = []
    for name, fn, body in (("incidents", _incident_items, incidents), ("stop advice", _stop_items, stops),
                           ("approvals", _approvals_items, approvals)):
        got, why = fn(body)
        if got is None:
            unread.append({"input": name, "reason": why})
            inputs.append({"input": name, "read": False, "rows": None, "reason": why})
        else:
            items.extend(got)
            inputs.append({"input": name, "read": True, "rows": len(got), "reason": None})
    items.sort(key=lambda x: (x["tier"], x.get("sub", 0), x.get("since") or "9", x["id"]))
    truncated = len(items) > MAX_ITEMS
    ranked = [{"rank": n + 1, **{k: v for k, v in it.items() if k not in ("sub",)}, "tier_label": ORDER[it["tier"]]}
              for n, it in enumerate(items[:MAX_ITEMS])]
    state = UNKNOWN if len(unread) == 3 else PARTIAL if unread else OK
    return {"schema": SCHEMA, "served_at": now.isoformat(), "state": state, "order": list(ORDER), "items": ranked,
            "count": len(items), "truncated": truncated, "unread": unread, "inputs": inputs,
            "reason": None if state == OK else "; ".join(f"{u['input']}: {u['reason']}" for u in unread)}


def build(read_incidents: Callable[[], Any], read_stops: Callable[[], Any], read_approvals: Callable[[], Any],
          *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Run the three reads; a read that raises is that input's ``unread`` entry, never a 500 and never an empty list."""
    def safe(fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            return {"state": UNKNOWN, "reason": f"{type(exc).__name__}"}
    return rank(safe(read_incidents), safe(read_stops), safe(read_approvals), now=now)
