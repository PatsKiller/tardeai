"""Watchlist vs watch_directives membership honesty (OpenClaw parity Stage 5).

A ticker directive add (POST /api/v2/watch/directives) is NOT the same thing as
membership on the ranked combined watchlist (GET /api/v2/watchlist). Consumers
(Maria skill, desk, Command Center) historically treated ``ok`` + ``directive_id``
as "added to watchlist" — which is how directive #1278 / S was claimed as
ranked while `/api/v2/watchlist` omitted it.

Policy for this package: **honest split copy** — report both truths; do not
pretend promote-into-ranked succeeded unless a membership probe confirms it.

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
) -> Dict[str, Any]:
    """Probe whether ``symbol`` is on the ranked/combined watchlist surface.

    Ranked membership is true if ANY of:
      1. ``watchlist_items`` has a non-removed row for the symbol
      2. ``data/portfolios/state/watchlist.json`` (or provided map) keys the symbol

    Returns ``{on_ranked: bool, via: str|None, checked: [...]}``. Fail-closed:
    an unreadable store is a miss for that arm, never a silent True.
    """
    sym = str(symbol or "").strip().upper()
    checked: list[str] = []
    if not sym:
        return {"on_ranked": False, "via": None, "checked": checked, "symbol": None}

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
                return {
                    "on_ranked": True,
                    "via": "watchlist_items",
                    "checked": checked,
                    "symbol": sym,
                    "item_status": row.get("status") if isinstance(row, Mapping) else None,
                    "item_source": row.get("source") if isinstance(row, Mapping) else None,
                }
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

    if isinstance(wl_map, Mapping):
        keys = {str(k).strip().upper() for k in wl_map.keys()}
        if sym in keys:
            return {
                "on_ranked": True,
                "via": "watchlist.json",
                "checked": checked,
                "symbol": sym,
            }

    return {"on_ranked": False, "via": None, "checked": checked, "symbol": sym}


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
) -> Dict[str, Any]:
    """Contract fields every directive-create response must carry for Stage 5.

    ``on_ranked_watchlist`` must be an observed bool (or None when not applicable
    for non-ticker kinds). Never default True.
    """
    kind_l = str(kind or "").strip().lower()
    sym = str(symbol or "").strip().upper() or None
    serviced = dict(serviced or {}) if serviced else None
    promo_status = None
    if serviced:
        promo_status = serviced.get("status")

    if kind_l != "ticker":
        membership = "directive_only" if directive_id is not None else "none"
        on_ranked: Optional[bool] = False if directive_id is not None else None
        honesty = (
            f"Created {kind_l} directive #{directive_id} — sector/trend directives "
            f"are discovery rules, not ranked `/api/v2/watchlist` membership."
            if directive_id is not None
            else "No directive id — nothing was added."
        )
    else:
        if on_ranked_watchlist is True:
            membership = "ranked_watchlist"
            on_ranked = True
            honesty = (
                f"Directive #{directive_id} for {sym}: also present on ranked "
                f"{RANKED_WATCHLIST_PATH}"
                + (f" (via {ranked_via})" if ranked_via else "")
                + "."
            )
        elif on_ranked_watchlist is False:
            membership = "directive_only"
            on_ranked = False
            honesty = (
                f"Directive #{directive_id} for {sym} is on {DIRECTIVES_PATH} only — "
                f"NOT on ranked {RANKED_WATCHLIST_PATH}. Do not claim watchlist "
                f"membership until promote lands or the ranked list includes {sym}."
            )
            if promo_status and promo_status not in _REGISTERED_STATUSES:
                honesty += f" Service status={promo_status}."
        else:
            # Unknown / probe skipped — fail closed: never claim ranked.
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
        "ranked_via": ranked_via if on_ranked else None,
        "ranked_watchlist_path": RANKED_WATCHLIST_PATH,
        "watchlist_items_path": WATCHLIST_ITEMS_PATH,
        "directives_path": DIRECTIVES_PATH,
        "membership": membership,
        "honesty": honesty,
        "policy": "honest_split",  # not auto-promote-into-ranked
    }


def format_operator_copy(honesty: Mapping[str, Any]) -> str:
    """One-line operator / skill copy that never claims ranked unless true."""
    did = honesty.get("directive_id")
    sym = honesty.get("symbol") or honesty.get("label") or "?"
    if honesty.get("on_ranked_watchlist") is True:
        return (
            f"✓ Directive #{did} ({sym}): on directives AND ranked "
            f"{honesty.get('ranked_watchlist_path')}."
        )
    if did is not None:
        return (
            f"✓ Directive #{did} ({sym}): directives-only "
            f"({honesty.get('directives_path')}) — NOT on ranked "
            f"{honesty.get('ranked_watchlist_path')}."
        )
    return str(honesty.get("honesty") or "No directive created.")
