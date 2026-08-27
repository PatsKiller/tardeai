"""OutcomeResolution@v1 — turn due checkpoints into recorded outcomes.

`process_due_checkpoint` and `persist_observation` have existed in
`cio_institutional_learning` since the learning loop landed, and nothing ever
called them. So 183 checkpoints accumulated, 102 of them carrying a `due_at`,
50 already past it, and **0 were ever resolved** — the loop's whole purpose is
to compare what was decided against what happened, and that comparison had
never run once.

This module is the missing caller. It is deliberately split from the runner
script so the selection and comparison logic can be tested without a database.

Two rules it will not break:

*   **Never invent a realized state.** If the price history cannot supply both
    ends of the comparison, the checkpoint is recorded as OUTCOME_PENDING_DATA
    and stays due. A fabricated outcome is worse than a missing one: it teaches
    the system something untrue and there is no later signal that it was wrong.
*   **Append, never rewrite.** Resolving a checkpoint appends a new version
    carrying the outcome link. The original row stays exactly as written.

AUTHORITY: READ_ONLY_ADVISORY. Observational only; no trading, no authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

SCHEMA = "OutcomeResolution@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

STATUS_SCHEDULED = "SCHEDULED"
STATUS_RESOLVED = "RESOLVED"
STATUS_PENDING_DATA = "OUTCOME_PENDING_DATA"
# Structurally not a price comparison — distinct from "waiting for data", which
# would keep the checkpoint churning through every future run forever.
STATUS_NOT_PRICE_RESOLVABLE = "NOT_PRICE_RESOLVABLE"

# Recommendations about the portfolio's cash, not about a security. `HOLD_CASH`
# with symbol "CASH" is the trap: CASH is also a real listed equity (Pathward
# Financial, CUSIP 59100U108) and IS in the identity registry as CONFIRMED, so
# neither the symbol string nor the registry can tell the two apart. The
# recommendation can. Pricing a cash-sleeve decision against a same-named
# ticker would have written 37 confident wrong outcomes into the learning loop.
NON_SECURITY_RECOMMENDATIONS = frozenset({"HOLD_CASH", "RAISE_CASH", "DEPLOY_CASH"})

# entity_type values that are explicitly not a tradable security.
NON_SECURITY_ENTITY_TYPES = frozenset({"PORTFOLIO_CASH", "GOAL", "PORTFOLIO"})

# A price lookup returns (close, as_of_date) or None.
PriceLookup = Callable[[str, str], "tuple[float, str] | None"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: Any) -> datetime | None:
    """Unreadable is None, never now — a bad timestamp must not read as due."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def latest_checkpoints(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fold the append-only store to the live version of each checkpoint.

    Counting raw rows would re-resolve a checkpoint every run, because the
    resolution itself appends a row.
    """
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        cid = row.get("checkpoint_id")
        if cid:
            latest[str(cid)] = row
    return latest


def due_checkpoints(
    rows: list[dict[str, Any]], now: datetime | None = None
) -> list[dict[str, Any]]:
    """Checkpoints past their due_at that have not been resolved.

    A checkpoint with no `due_at` is not due — it is unscheduled. Treating a
    missing deadline as "now" would resolve the entire backlog on first run.
    """
    at = now or _now()
    out = []
    for cp in latest_checkpoints(rows).values():
        if str(cp.get("status") or "") != STATUS_SCHEDULED:
            continue
        due = _parse(cp.get("due_at"))
        if due and due <= at:
            out.append(cp)
    return sorted(out, key=lambda c: str(c.get("due_at")))


def checkpoint_symbol(cp: dict[str, Any]) -> str | None:
    original = cp.get("original_decision_state") or {}
    for candidate in (original.get("symbol"), cp.get("subject_id")):
        sym = str(candidate or "").strip().upper()
        # A subject_id may be a goal-wake reference, not a ticker.
        if sym and sym.isalpha() and 1 <= len(sym) <= 5:
            return sym
    return None


def price_resolvable(cp: dict[str, Any], registry_lookup: Callable[[str], bool] | None = None) -> tuple[bool, str | None]:
    """Whether comparing this decision against price history is meaningful.

    Returns (resolvable, reason_when_not). A checkpoint that fails here is not
    waiting for data — no future run will make it price-comparable — so it is
    recorded with its reason rather than left due forever.
    """
    entity_type = str(cp.get("entity_type") or "").upper()
    if entity_type in NON_SECURITY_ENTITY_TYPES:
        return False, f"entity_type_{entity_type.lower()}"

    original = cp.get("original_decision_state") or {}
    rec = str(original.get("recommendation") or "").upper()
    if rec in NON_SECURITY_RECOMMENDATIONS:
        return False, f"portfolio_cash_decision_{rec.lower()}"

    symbol = checkpoint_symbol(cp)
    if not symbol:
        return False, "no_security_subject"
    if registry_lookup is not None and not registry_lookup(symbol):
        # A pseudo-symbol such as REENTRY is a lane marker, not an instrument.
        return False, "subject_not_a_registered_security"
    return True, None


def realized_state(
    cp: dict[str, Any],
    price_lookup: PriceLookup,
    now: datetime | None = None,
) -> tuple[bool, dict[str, Any], list[str]]:
    """Compare the decision-time price against the price at the horizon.

    Returns (source_available, realized_state, source_refs). The decision state
    records no price of its own, so both ends come from price history; if either
    end is missing the comparison is not available and nothing is guessed.
    """
    at = now or _now()
    symbol = checkpoint_symbol(cp)
    if not symbol:
        return False, {}, []

    original = cp.get("original_decision_state") or {}
    decided_at = _parse(original.get("as_of")) or _parse(cp.get("created_at"))
    if not decided_at:
        return False, {}, []

    then = price_lookup(symbol, decided_at.date().isoformat())
    now_px = price_lookup(symbol, at.date().isoformat())
    if not then or not now_px:
        return False, {}, []

    then_px, then_date = then
    end_px, end_date = now_px
    if not then_px:
        return False, {}, []

    change_pct = round((end_px - then_px) / then_px * 100.0, 4)
    return (
        True,
        {
            "symbol": symbol,
            "price_at_decision": then_px,
            "price_at_horizon": end_px,
            "change_pct": change_pct,
            "decision_price_date": then_date,
            "horizon_price_date": end_date,
            "recommendation": original.get("recommendation"),
        },
        [f"ticker_prices:{symbol}:{then_date}", f"ticker_prices:{symbol}:{end_date}"],
    )


def resolution_row(
    cp: dict[str, Any],
    outcome_id: str | None,
    status: str,
    reason: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """A new version of the checkpoint carrying its outcome link.

    Every field of the original is preserved. The store is append-only, so this
    supersedes rather than edits, and the original row remains readable.
    """
    row = dict(cp)
    row["status"] = status
    row["resolved_at"] = (now or _now()).replace(microsecond=0).isoformat()
    row["outcome_id"] = outcome_id
    if reason:
        row["resolution_reason"] = reason
    row["schema"] = cp.get("schema") or "OutcomeCheckpoint@v1"
    row["authority"] = AUTHORITY
    row["memory_behavior_influence"] = MBI
    row["observational_only"] = True
    row["trading"] = False
    return row
