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


def canonical_account(raw: Any) -> str:
    """The declared key for an account spelling; unknown spellings pass through unchanged.

    ``config/account_display_names.json`` declares aliases (``schwab_roth`` -> ``schwab_roth_ira``,
    ``schwab_individual`` -> ``schwab_taxable``) and ``account_display.canonical_key`` resolves them.
    Ownership is a question about an ACCOUNT, so both the holding row and the candidate must be
    canonicalized before membership is tested (codex-cloud P1 at account_scope:123, 2026-11-05).
    """
    text = str(raw or "").strip()
    if not text or text == SCOPE_UNSCOPED:
        return text
    try:
        try:
            from lib.account_display import canonical_key
        except ImportError:  # imported as scripts.lib.*
            from scripts.lib.account_display import canonical_key  # type: ignore[no-redef]
        return canonical_key(text) or text
    except Exception:  # noqa: BLE001 — a missing display config never changes an account's identity
        return text


def held_for(held: dict[str, set[str]], symbol: str, account: str | None) -> bool:
    """Is this symbol held — **in this account** when one is stated, in **any** account otherwise?

    The scoped answer is the FQ-096 fix: a residual held in the Individual account does not hold an
    IRA re-entry. The unscoped answer stays true when a NAMED account holds the symbol (claude-lead
    BLOCK on #2603, 2026-11-05): returning False there dropped every real holding — live holdings
    always name an account while no re-entry row does — which took the desk's HELD rows from 14 to 0
    and let a position the book already holds page BUY_READY. An unscoped reader is told *where* the
    position is (``held_in``) as well as that it is held; it is never told the symbol is free while
    an account holds it.
    """
    sym = str(symbol or "").upper().strip()
    accounts = held.get(sym) or set()
    if not accounts:
        return False
    acct = str(account or "").strip()
    if not acct or acct == SCOPE_UNSCOPED:
        return True   # held somewhere; held_in() names where, and a scoped reader narrows it
    wanted = canonical_account(acct)
    return any(canonical_account(a) == wanted for a in accounts)


def held_in(held: dict[str, set[str]], symbol: str) -> list[str]:
    """The accounts holding this symbol, sorted — for the reader, not for a cross-account block."""
    return sorted((held.get(str(symbol or "").upper().strip()) or set()))


#: How sure the ``held`` answer is. Carried beside the boolean so "unknown" never renders as
#: "not held" — the same class as a ``?? 0`` default (cx-openai-3 CX3-S-F4, 2026-11-05).
HELD_CONFIRMED = "CONFIRMED"
HELD_UNKNOWN = "UNKNOWN"
HELD_SCOPE_UNKNOWN = "SCOPE_UNKNOWN"
HELD_FROM_ROW = "ROW"


def holdings_document_known(holdings_doc: Any) -> bool:
    """True only for a holdings document that was actually read and can be enumerated.

    ``{"holdings": []}`` is a valid, **confirmed-empty** portfolio: a named account is genuinely
    absent and the reader may say so. ``{}`` (metadata only), ``{"holdings": null}``, a non-mapping,
    or a failed read is NOT an empty portfolio — unknown is not zero.
    """
    return isinstance(holdings_doc, dict) and isinstance(holdings_doc.get("holdings"), list)


def account_identity_unknown(held: dict[str, set[str]], symbol: str) -> bool:
    """True when a holding for this symbol names no account, so absence cannot be confirmed.

    A holding row without an account is still a holding: it proves the symbol exists in the book,
    but not which account owns it. A named candidate must not read that as "not held in my account".
    """
    return SCOPE_UNSCOPED in (held.get(str(symbol or "").upper().strip()) or set())


def resolve_held(
    held: dict[str, set[str]],
    symbol: str,
    account: str | None,
    *,
    inherited: Any = None,
    evidence_known: bool = True,
) -> tuple[bool, str]:
    """Resolve ``held`` for one row from validated evidence, and say how sure that answer is.

    * An unscoped reader keeps the conservative "held somewhere" answer (and any inherited facts).
    * A scoped reader whose holdings for the symbol all name an account is decided by that account
      ALONE — an inherited symbol-wide flag never widens it (cx-openai-3 CX3-S-F1, cx-openai-2 F1).
    * Unreadable/malformed evidence, or a holding row for the symbol with no account, cannot
      confirm absence: the inherited fact stands and the caller is told UNKNOWN / SCOPE_UNKNOWN
      (cx-openai-3 CX3-S-F4).
    """
    held = held or {}
    sym = str(symbol or "").upper().strip()
    acct = str(account or "").strip()
    base = bool(inherited)
    if not evidence_known:
        return base, HELD_UNKNOWN
    if not acct or acct == SCOPE_UNSCOPED:
        return base or held_for(held, sym, None), HELD_CONFIRMED
    if account_identity_unknown(held, sym):
        return base, HELD_SCOPE_UNKNOWN
    # Canonicalized membership: the holding row and the candidate may spell one account two ways.
    return held_for(held, sym, acct), HELD_CONFIRMED


def evidence_key(symbol: Any, account: Any) -> str:
    """The key an evidence row is stored under: the bare symbol when unscoped, ``SYMBOL|ACCOUNT`` otherwise.

    FQ-096 clearing condition (reviewer handoff 2026-11-04): two rows for the same symbol in different
    accounts must remain separate. A symbol-only key silently overwrote the second row, which is the same
    cross-account collapse in a different place.
    """
    sym = str(symbol or "").upper().strip()
    acct = str(account or "").strip()
    return sym if (not acct or acct == SCOPE_UNSCOPED) else f"{sym}|{acct}"
