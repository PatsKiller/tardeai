"""ACCOUNT SCOPE — a position fact belongs to (symbol, account), never to "all accounts".

SPEC_ONE_POSITION_VERDICT_20261104.md §1b rule 3 (operator, 2026-11-04): "Everything is keyed by
(symbol, account). No cross-account blocking." Rule 4: aggregation is allowed only where total
position weight or exposure is shown.

FQ-096: `canonical_observation.py` defaulted `account_scope="ALL_ACCOUNTS"`, so a residual held in an
Individual account could be read as held everywhere and block an IRA re-entry. This module makes the
unscoped case explicit and gives consumers the per-account view instead of one symbol-wide boolean.
"""

from __future__ import annotations

from typing import Any, Iterable

#: The honest value for "nobody said which account". It is NOT "all accounts" — a reader must not be
#: able to mistake an unstated scope for a cross-account fact.
SCOPE_UNSCOPED = "UNSCOPED"


def account_of(row: dict[str, Any] | None) -> str:
    """The account a fact is about, or SCOPE_UNSCOPED. Never 'ALL_ACCOUNTS'."""
    if not isinstance(row, dict):
        return SCOPE_UNSCOPED
    value = row.get("account") or row.get("account_key") or row.get("account_id")
    text = str(value or "").strip()
    return text or SCOPE_UNSCOPED


def held_accounts(holdings_doc: dict[str, Any] | None) -> dict[str, set[str]]:
    """symbol -> the accounts that actually hold it (cash rows and loans excluded)."""
    out: dict[str, set[str]] = {}
    for row in (holdings_doc or {}).get("holdings") or []:
        if not isinstance(row, dict) or row.get("is_cash") or row.get("is_loan"):
            continue
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym:
            continue
        out.setdefault(sym, set()).add(account_of(row))
    return out


def held_for(held: dict[str, set[str]], symbol: str, account: str | None) -> bool:
    """Is this symbol held **in this account**?

    An unscoped reader is not told "held everywhere": it gets True only if the symbol is held
    somewhere, and the caller is expected to surface the accounts (``held_in``) rather than block a
    per-account decision. With an account, only that account's holding counts.
    """
    sym = str(symbol or "").upper().strip()
    accounts = held.get(sym) or set()
    if not accounts:
        return False
    acct = str(account or "").strip()
    if not acct or acct == SCOPE_UNSCOPED:
        return True
    return acct in accounts


def held_in(held: dict[str, set[str]], symbol: str) -> list[str]:
    """The accounts holding this symbol, sorted — for the reader, not for a cross-account block."""
    return sorted((held.get(str(symbol or "").upper().strip()) or set()))
