"""account_display — the one short human name for each account (operator 2026-10-23).

Operator, verbatim: "you need to actually put which account right here. Like, for example, there are
two SpaceX and two different accounts." and then "just a name, not the account numbers."

Every Command Center row that carries a position, a held or formerly-held name, a fill, a stop, a P/L or
a trade gets two fields from here:

    account_id     the canonical account key (``schwab_rollover_ira``) — an internal key, never a number
    account_label  the short human name (``Schwab Rollover IRA``) — never an account number, never digits

Names live in ``config/account_display_names.json``. A key that is not configured is title-cased from
the key; a key that looks like a broker account number (a run of 3+ digits, or a masked ``...258`` /
``··1234`` form) is never echoed: it becomes ``Unlabelled account``.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

_CONFIG = Path(__file__).resolve().parents[2] / "config" / "account_display_names.json"
UNLABELLED = "Unlabelled account"
_DIGIT_RUN = re.compile(r"\d{3,}")
_MASK = re.compile(r"(\.\.\.|··|…|\*\*|xx)\s*\w*\d", re.I)
ACCOUNT_FIELDS = ("account_id", "account", "account_key", "accountId", "broker_account")


@lru_cache(maxsize=1)
def _load(path: str = str(_CONFIG)) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"aliases": {}, "names": {}}


def looks_like_number(text: str) -> bool:
    """True when text would leak an account number (a 3+ digit run or a masked tail)."""
    s = str(text or "")
    return bool(_DIGIT_RUN.search(s) or _MASK.search(s))


def canonical_key(raw: Any) -> str:
    key = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not key:
        return ""
    return str((_load().get("aliases") or {}).get(key, key))


def account_label(raw: Any) -> str:
    """The short human name for an account key. Never contains an account number."""
    key = canonical_key(raw)
    if not key:
        return UNLABELLED
    entry = (_load().get("names") or {}).get(key)
    name = entry.get("name") if isinstance(entry, Mapping) else None
    if not name:
        if looks_like_number(key):
            return UNLABELLED
        name = re.sub(r"\bIra\b", "IRA", key.replace("_", " ").title())
    return UNLABELLED if looks_like_number(name) else str(name)


def labels_map(keys: Iterable[Any] | None = None) -> dict[str, str]:
    """{account_key: label} for the given keys, or for every configured account."""
    if keys is None:
        keys = list((_load().get("names") or {}).keys())
    return {str(k): account_label(k) for k in keys if str(k or "").strip()}


def row_account(row: Mapping[str, Any]) -> str:
    for f in ACCOUNT_FIELDS:
        v = row.get(f) if isinstance(row, Mapping) else None
        if v not in (None, "") and not looks_like_number(v):
            return canonical_key(v)
    return ""


def label_row(row: dict) -> dict:
    """Add ``account_id`` + ``account_label`` to one row in place (keeps any existing ``account``)."""
    if not isinstance(row, dict):
        return row
    key = row_account(row)
    if key:
        row["account_id"] = key
        row["account_label"] = account_label(key)
    elif any(row.get(f) for f in ACCOUNT_FIELDS):
        row["account_label"] = UNLABELLED
    return row


def label_rows(rows: Iterable[Any]) -> list:
    return [label_row(r) if isinstance(r, dict) else r for r in (rows or [])]


def multi_account_symbols(rows: Iterable[Mapping[str, Any]], symbol_field: str = "symbol") -> dict[str, list[str]]:
    """{SYMBOL: [account keys]} for symbols held in two or more accounts (rows of one per account holding)."""
    seen: dict[str, list[str]] = {}
    for r in rows or []:
        if not isinstance(r, Mapping):
            continue
        sym = str(r.get(symbol_field) or "").strip().upper()
        acct = row_account(r)
        if sym and acct and acct not in seen.setdefault(sym, []):
            seen[sym].append(acct)
    return {s: a for s, a in seen.items() if len(a) >= 2}
