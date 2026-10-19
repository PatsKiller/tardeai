"""Identity, catalyst and CIO-decision lookups shared by the swing entry alert producers.

Operator 2026-10-19: every ENTRY APPROACHING / HIGH CONVICTION ENTRY alert from
watchlist_entry_planner shipped as "<SYM> · identity data unavailable", "Catalyst: unavailable",
"CIO review: unreviewed" although the facts were in the database. cio_entry_state_runner already
read them (symbol_profiles, watchlist_strategy_cards.catalyst_summary, cio_decisions); the queries
live here so both producers read the same rows the same way. SELECT only; callers own the cursor
and the transaction.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

PROFILE_SQL = """SELECT DISTINCT ON (upper(symbol)) upper(symbol), description_1s, sector, industry
                     FROM symbol_profiles WHERE upper(symbol) = ANY(%s)
                    ORDER BY upper(symbol), updated_at DESC NULLS LAST"""

CARD_CATALYST_SQL = """SELECT DISTINCT ON (upper(symbol)) upper(symbol), catalyst_summary
                     FROM watchlist_strategy_cards WHERE upper(symbol) = ANY(%s)
                    ORDER BY upper(symbol), updated_at DESC NULLS LAST"""

# The runner's own 'entry' rows are excluded: they are this alert, not an independent CIO view.
CIO_SQL = """SELECT DISTINCT ON (upper(symbol)) upper(symbol), action, decision_id, action_class, created_at
                     FROM cio_decisions
                    WHERE upper(symbol) = ANY(%s) AND action_class <> 'entry'
                    ORDER BY upper(symbol), created_at DESC"""

#: action_class written by lib.buy_ready_cio_review for a real CIO review of an entry.
ENTRY_REVIEW_CLASS = "entry_review"


def _syms(symbols: Iterable[Any]) -> list[str]:
    return sorted({str(s).strip().upper() for s in symbols if s and str(s).strip()})


def symbol_profiles(cur, symbols: Iterable[Any]) -> dict[str, tuple]:
    """{SYM: (company description, sector, industry)} from symbol_profiles."""
    syms = _syms(symbols)
    if not syms:
        return {}
    cur.execute(PROFILE_SQL, (syms,))
    return {row[0]: tuple(row[1:4]) for row in cur.fetchall()}


def card_catalysts(cur, symbols: Iterable[Any]) -> dict[str, str]:
    """{SYM: catalyst_summary} from the newest watchlist strategy card (non-empty only)."""
    syms = _syms(symbols)
    if not syms:
        return {}
    cur.execute(CARD_CATALYST_SQL, (syms,))
    return {row[0]: str(row[1]).strip() for row in cur.fetchall() if row[1] and str(row[1]).strip()}


def latest_cio_decisions(cur, symbols: Iterable[Any]) -> dict[str, dict]:
    """{SYM: {action, decision_id, action_class, created_at}} — the newest non-'entry' CIO decision."""
    syms = _syms(symbols)
    if not syms:
        return {}
    cur.execute(CIO_SQL, (syms,))
    out = {}
    for row in cur.fetchall():
        out[row[0]] = {"action": row[1], "decision_id": row[2], "action_class": row[3], "created_at": row[4]}
    return out


def cio_review_fields(decision: Optional[dict]) -> dict:
    """Card fields from the latest CIO decision.

    Only an ``entry_review`` row is a CIO review of the entry itself, so only it sets
    ``cio_review_id`` (which is what turns a BUY READY card green — operator 2026-10-05, VCIG).
    Any other decision is shown as the CIO's stance on record, never as a review.
    """
    if not decision or not decision.get("decision_id"):
        return {}
    action = str(decision.get("action") or "").strip() or None
    if decision.get("action_class") == ENTRY_REVIEW_CLASS:
        return {"cio_review_id": decision["decision_id"], "cio_review_status": "REVIEWED",
                "cio_action": action}
    return {"cio_decision_id": decision["decision_id"], "cio_action": action,
            "cio_review_status": f"CIO {action} on record (no entry review)" if action else "CIO decision on record"}


def entry_alert_context(cur, symbol: str) -> dict:
    """Everything the entry card needs that the plan does not carry, for one symbol. Missing facts
    are simply absent (the card then says so); never invented."""
    sym = str(symbol or "").strip().upper()
    out: dict = {}
    if not sym:
        return out
    prof = symbol_profiles(cur, [sym]).get(sym)
    if prof:
        company, sector, industry = prof
        out.update({k: v for k, v in (("company", company), ("sector", sector), ("industry", industry)) if v})
    cat = card_catalysts(cur, [sym]).get(sym)
    if cat:
        out["catalyst"] = cat
    out.update(cio_review_fields(latest_cio_decisions(cur, [sym]).get(sym)))
    return out


__all__ = ["PROFILE_SQL", "CARD_CATALYST_SQL", "CIO_SQL", "ENTRY_REVIEW_CLASS", "symbol_profiles",
           "card_catalysts", "latest_cio_decisions", "cio_review_fields", "entry_alert_context"]
