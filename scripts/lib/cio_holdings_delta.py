"""Verified holdings snapshot delta — new-position / transfer detection.

Never calls a transfer a purchase without evidence.
Does not hard-code SCHG.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
MATERIAL_VALUE_USD = 500.0
MATERIAL_WEIGHT_PCT = 0.25


def _norm_symbol(row: dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("ticker") or "").strip().upper()


def _norm_account(row: dict[str, Any]) -> str:
    return str(row.get("account") or row.get("account_id") or "").strip().lower()


def _value(row: dict[str, Any]) -> float:
    for k in ("market_value", "current_value_usd", "broker_market_value", "value"):
        try:
            return float(row.get(k) or 0)
        except (TypeError, ValueError):
            continue
    return 0.0


def _shares(row: dict[str, Any]) -> float:
    for k in ("shares", "quantity", "qty", "broker_actual_shares"):
        try:
            return float(row.get(k) or 0)
        except (TypeError, ValueError):
            continue
    return 0.0


def index_holdings(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        sym = _norm_symbol(row)
        if not sym or sym in {"CASH", "USD"}:
            continue
        key = (sym, _norm_account(row))
        out[key] = row
    return out


def extract_rows(snapshot: Any) -> list[dict[str, Any]]:
    if isinstance(snapshot, list):
        return [r for r in snapshot if isinstance(r, dict)]
    if not isinstance(snapshot, dict):
        return []
    for k in ("holdings", "positions", "items"):
        v = snapshot.get(k)
        if isinstance(v, list):
            return [r for r in v if isinstance(r, dict)]
    return []


def diff_holdings(
    previous: Any,
    current: Any,
    *,
    material_usd: float = MATERIAL_VALUE_USD,
) -> list[dict[str, Any]]:
    prev = index_holdings(extract_rows(previous))
    curr = index_holdings(extract_rows(current))
    events: list[dict[str, Any]] = []
    prev_syms = {k[0] for k in prev}
    curr_syms = {k[0] for k in curr}

    for key, row in curr.items():
        if key not in prev:
            # Same symbol appeared on another account and vanished here → transfer
            other_prev = [k for k in prev if k[0] == key[0] and k[1] != key[1]]
            other_gone = [k for k in other_prev if k not in curr]
            if other_gone:
                events.append({
                    "event": "ACCOUNT_TRANSFER_DETECTED",
                    "symbol": key[0],
                    "to_account": key[1],
                    "from_accounts": [k[1] for k in other_gone],
                    "value_usd": _value(row),
                    "shares": _shares(row),
                    "purchase_claimed": False,
                    "authority": AUTHORITY,
                })
            elif key[0] not in prev_syms:
                events.append({
                    "event": "POSITION_OPENED",
                    "symbol": key[0],
                    "account": key[1],
                    "value_usd": _value(row),
                    "shares": _shares(row),
                    "authority": AUTHORITY,
                })
            else:
                events.append({
                    "event": "ACCOUNT_TRANSFER_DETECTED",
                    "symbol": key[0],
                    "to_account": key[1],
                    "from_accounts": [],
                    "value_usd": _value(row),
                    "shares": _shares(row),
                    "purchase_claimed": False,
                    "note": "new_account_sleeve_same_symbol",
                    "authority": AUTHORITY,
                })
        else:
            dv = abs(_value(row) - _value(prev[key]))
            if dv >= float(material_usd):
                events.append({
                    "event": "POSITION_SIZE_CHANGED_MATERIAL",
                    "symbol": key[0],
                    "account": key[1],
                    "prior_value_usd": _value(prev[key]),
                    "value_usd": _value(row),
                    "delta_usd": _value(row) - _value(prev[key]),
                    "authority": AUTHORITY,
                })

    for key, row in prev.items():
        if key not in curr and key[0] not in curr_syms:
            events.append({
                "event": "POSITION_CLOSED",
                "symbol": key[0],
                "account": key[1],
                "prior_value_usd": _value(row),
                "authority": AUTHORITY,
            })
    return events
