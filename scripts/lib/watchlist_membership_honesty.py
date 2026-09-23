"""Watchlist vs watch_directives membership honesty (OpenClaw parity Stage 5).

Consumers historically treated ``ok`` + ``directive_id`` as "added to watchlist"
while GET /api/v2/watchlist omitted the symbol (directive #1278 / S).

As of PR #1196, GET /api/v2/watchlist **unions** ACTIVE ticker directives into the
combined list (``source=directive``). Honesty therefore reports:

* whether the symbol is on ``/api/v2/watchlist`` (union surface), and **via** which arm
* whether it is also on the legacy ``watchlist_items`` table (promote/service path)
* ``subject_guid`` from the writer receipt (table still has no identity column)

Policy: **honest_via** — never invent membership; stamp the via arm. Do not equate
a staged promote failure with absence from the union watchlist when an active
directive exists.

MBI_BEHAVIOR = 0. No broker. Read-only probes only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

RANKED_WATCHLIST_PATH = "/api/v2/watchlist"
DIRECTIVES_PATH = "/api/v2/watch-directives"
WATCHLIST_ITEMS_PATH = "/api/v2/watchlist/items"

# Promotion statuses that mean the symbol was written onto watchlist_items.
_REGISTERED_STATUSES = frozenset({
    "PROMOTED",
    "MONITORED_NO_QUALIFY",
    "REGISTERED_NO_TECH",
})


def subject_identity_from_receipt(receipt: Any) -> Dict[str, Any]:
    """Pull subject_guid / identity fields from a watch_directives WriteReceipt.

    The directives table has no identity column (phase-9 notes); the GUID travels
    on the receipt only. Prefer ``details`` (fresh insert) then ``reused``.
    """
    bags = []
    if receipt is None:
        return {"subject_guid": None, "identity_source": None, "symbol": None}
    for attr in ("details", "reused"):
        val = getattr(receipt, attr, None)
        if val:
            bags.extend(list(val))
    for bag in bags:
        if not isinstance(bag, Mapping):
            continue
        if any(k in bag for k in ("subject_guid", "identity_source", "identity_reason",
                                  "identity_lookup_failed", "symbol")):
            return {
                "subject_guid": bag.get("subject_guid"),
                "identity_source": bag.get("identity_source"),
                "identity_status": bag.get("identity_status"),
                "identity_reason": bag.get("identity_reason"),
                "identity_lookup_failed": bag.get("identity_lookup_failed"),
                "symbol": bag.get("symbol"),
            }
    return {"subject_guid": None, "identity_source": None, "symbol": None}


def symbol_on_ranked_watchlist(
    symbol: str,
    *,
    db_query: Optional[Callable[..., Any]] = None,
    watchlist_json: Optional[Mapping[str, Any]] = None,
    state_dir: Optional[Path] = None,
    active_directive_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Probe whether ``symbol`` appears on GET /api/v2/watchlist (union surface).

    Membership is true if ANY of:
      1. ``watchlist_items`` has a non-removed row for the symbol
      2. ``watchlist.json`` keys the symbol
      3. an ACTIVE ticker directive exists (PR #1196 union) — pass
         ``active_directive_id`` after create, or probe via ``db_query`` /
         ``active_ticker_directives``

    Returns ``{on_ranked, via, on_watchlist_items, checked, ...}``. Fail-closed.
    """
    sym = str(symbol or "").strip().upper()
    checked: list[str] = []
    if not sym:
        return {
            "on_ranked": False,
            "via": None,
            "on_watchlist_items": False,
            "checked": checked,
            "symbol": None,
        }

    on_items = False
    via_items = None
    if db_query is not None:
        checked.append("watchlist_items")
        try:
            row = db_query(
                """SELECT symbol, status, source FROM watchlist_items
                   WHERE upper(symbol)=%s AND status <> 'removed'
                   ORDER BY updated_at DESC NULLS LAST LIMIT 1""",
                (sym,),
                fetch="one",
            )
            if row:
                on_items = True
                via_items = "watchlist_items"
        except Exception as e:  # noqa: BLE001 — probe must never break create
            checked.append(f"watchlist_items_error:{type(e).__name__}")

    wl_map = watchlist_json
    if wl_map is None and state_dir is not None:
        checked.append("watchlist.json")
        try:
            import json
            p = Path(state_dir) / "watchlist.json"
            if p.is_file():
                raw = json.loads(p.read_text(encoding="utf-8"))
                wl_map = raw if isinstance(raw, dict) else {}
        except Exception as e:  # noqa: BLE001
            checked.append(f"watchlist.json_error:{type(e).__name__}")
            wl_map = None
    elif wl_map is not None:
        checked.append("watchlist.json")

    on_json = False
    if isinstance(wl_map, Mapping):
        keys = {str(k).strip().upper() for k in wl_map.keys()}
        if sym in keys:
            on_json = True

    on_directive = False
    directive_id = None
    if active_directive_id is not None:
        checked.append("active_ticker_directive")
        on_directive = True
        directive_id = int(active_directive_id)
    else:
        checked.append("active_ticker_directive")
        try:
            from lib.data_broker.watch_intelligence import active_ticker_directives
            for d in active_ticker_directives() or []:
                if str(d.get("symbol") or "").strip().upper() == sym:
                    on_directive = True
                    directive_id = d.get("id")
                    break
        except Exception as e:  # noqa: BLE001
            checked.append(f"active_ticker_directive_error:{type(e).__name__}")
            if db_query is not None:
                try:
                    row = db_query(
                        """SELECT id FROM watch_directives
                           WHERE kind='ticker' AND status='active'
                             AND UPPER(spec->>'symbol')=%s
                           ORDER BY id DESC LIMIT 1""",
                        (sym,),
                        fetch="one",
                    )
                    if row:
                        on_directive = True
                        directive_id = row.get("id") if isinstance(row, Mapping) else None
                except Exception as e2:  # noqa: BLE001
                    checked.append(f"directive_sql_error:{type(e2).__name__}")

    if on_items:
        via = via_items
    elif on_json:
        via = "watchlist.json"
    elif on_directive:
        via = "active_ticker_directive"
    else:
        via = None

    return {
        "on_ranked": bool(on_items or on_json or on_directive),
        "via": via,
        "on_watchlist_items": on_items,
        "on_watchlist_json": on_json,
        "on_active_directive": on_directive,
        "directive_id": directive_id,
        "checked": checked,
        "symbol": sym,
    }


def build_directive_add_honesty(
    *,
    directive_id: Optional[int],
    kind: str,
    label: str,
    symbol: Optional[str] = None,
    subject_guid: Optional[str] = None,
    identity_source: Optional[str] = None,
    identity_status: Optional[str] = None,
    reused: bool = False,
    serviced: Optional[Mapping[str, Any]] = None,
    on_ranked_watchlist: Optional[bool] = None,
    ranked_via: Optional[str] = None,
    on_watchlist_items: Optional[bool] = None,
) -> Dict[str, Any]:
    """Contract fields every directive-create response must carry for Stage 5."""
    kind_l = str(kind or "").strip().lower()
    sym = str(symbol or "").strip().upper() or None
    serviced = dict(serviced or {}) if serviced else None
    promo_status = serviced.get("status") if serviced else None

    if kind_l != "ticker":
        membership = "directive_only" if directive_id is not None else "none"
        on_ranked: Optional[bool] = False if directive_id is not None else None
        honesty = (
            f"Created {kind_l} directive #{directive_id} — sector/trend directives "
            f"are discovery rules, not ranked `{RANKED_WATCHLIST_PATH}` membership."
            if directive_id is not None
            else "No directive id — nothing was added."
        )
        return {
            "directive_id": directive_id,
            "kind": kind_l,
            "label": label,
            "symbol": sym,
            "subject_guid": subject_guid,
            "identity_source": identity_source,
            "identity_status": identity_status,
            "reused": bool(reused),
            "serviced": serviced,
            "on_ranked_watchlist": on_ranked,
            "on_watchlist_items": False,
            "ranked_via": None,
            "ranked_watchlist_path": RANKED_WATCHLIST_PATH,
            "watchlist_items_path": WATCHLIST_ITEMS_PATH,
            "directives_path": DIRECTIVES_PATH,
            "membership": membership,
            "honesty": honesty,
            "policy": "honest_via",
        }

    if on_ranked_watchlist is True:
        membership = "ranked_watchlist"
        on_ranked = True
        via_bit = f" (via {ranked_via})" if ranked_via else ""
        honesty = (
            f"Directive #{directive_id} for {sym}: on {RANKED_WATCHLIST_PATH}{via_bit}."
        )
        if on_watchlist_items is False:
            honesty += (
                f" Not yet on {WATCHLIST_ITEMS_PATH}"
                + (f" (service={promo_status})" if promo_status else "")
                + "."
            )
    elif on_ranked_watchlist is False:
        membership = "directive_only"
        on_ranked = False
        honesty = (
            f"Directive #{directive_id} for {sym} is on {DIRECTIVES_PATH} only — "
            f"NOT on {RANKED_WATCHLIST_PATH}."
        )
        if promo_status and promo_status not in _REGISTERED_STATUSES:
            honesty += f" Service status={promo_status}."
    else:
        membership = "directive_only" if directive_id is not None else "none"
        on_ranked = False
        honesty = (
            f"Directive #{directive_id} for {sym} recorded; ranked membership "
            f"was not verified — treat as directives-only until confirmed."
        )

    if reused and directive_id is not None:
        honesty = f"Reused existing directive #{directive_id}. " + honesty

    return {
        "directive_id": directive_id,
        "kind": kind_l,
        "label": label,
        "symbol": sym,
        "subject_guid": subject_guid,
        "identity_source": identity_source,
        "identity_status": identity_status,
        "reused": bool(reused),
        "serviced": serviced,
        "on_ranked_watchlist": on_ranked,
        "on_watchlist_items": bool(on_watchlist_items) if on_watchlist_items is not None else None,
        "ranked_via": ranked_via if on_ranked else None,
        "ranked_watchlist_path": RANKED_WATCHLIST_PATH,
        "watchlist_items_path": WATCHLIST_ITEMS_PATH,
        "directives_path": DIRECTIVES_PATH,
        "membership": membership,
        "honesty": honesty,
        "policy": "honest_via",
    }


def format_operator_copy(honesty: Mapping[str, Any]) -> str:
    """One-line operator / skill copy that names the via arm."""
    did = honesty.get("directive_id")
    sym = honesty.get("symbol") or honesty.get("label") or "?"
    if honesty.get("on_ranked_watchlist") is True:
        via = honesty.get("ranked_via") or "union"
        return (
            f"✓ Directive #{did} ({sym}): on {honesty.get('ranked_watchlist_path')} "
            f"(via {via})."
        )
    if did is not None:
        return (
            f"✓ Directive #{did} ({sym}): directives-only "
            f"({honesty.get('directives_path')}) — NOT on "
            f"{honesty.get('ranked_watchlist_path')}."
        )
    return str(honesty.get("honesty") or "No directive created.")
