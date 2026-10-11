"""yfinance Info — Data Broker read model over ``yfinance_info_snapshot``.

Operator decision 2026-10-10 ~17:45 ET (CONSOLIDATION_PLAN.md §D.13). Store
``yfinance_info_snapshot`` (``migrations/2026_10_10_yfinance_info_snapshot.sql``); single writer
``scripts/lib/writers/yfinance_info_snapshot_writer.py``. One raw ``.info`` payload per symbol.

A consumer asks for a batch of symbols and gets, per symbol, the stored payload, its ``status``
(``ok`` / ``no_profile`` / ``error`` — the negative cache), ``as_of`` / ``age_hours`` / ``stale``,
and a ``BrokerReadEnvelope@v1`` for the batch. A stale or missing symbol is listed in
``stale_or_missing``; whether to ask the owner to refresh it is the caller's decision. Until the
owner lane exists (§D.12, undecided) the table is empty — or absent where the migration has not
been applied — and the answer is ``gap.kind = no_coverage`` with the declared ``say_so``.

Zero provider calls (this module never imports yfinance). Read-only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from lib.data_broker.envelope import envelope

DOMAIN = "yfinance_info_snapshot"
PROJECTION = "yfinance_info"
TABLE = "yfinance_info_snapshot"
WRITER = "scripts/lib/writers/yfinance_info_snapshot_writer.py"
#: Tier A window in API_OVERLAP_CONSOLIDATION.md §3.4 (held/directive/proposal names: 2 days)
DEFAULT_MAX_AGE_HOURS = 48.0

INFO_SQL = """
SELECT symbol, fetched_at, status, quote_type, payload, payload_keys, error
FROM yfinance_info_snapshot
WHERE symbol = ANY(%s::text[])
"""


def _norm(symbols: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for s in symbols or []:
        sym = str(s or "").upper().strip()
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def _as_utc(v: Any) -> datetime | None:
    if v is None:
        return None
    if not isinstance(v, datetime):
        try:
            v = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


def get_info_batch(
    db_query: Callable[..., Any],
    symbols: Iterable[Any],
    *,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Per-symbol stored ``.info`` with freshness. ``db_query(sql, params)`` returns dict rows."""
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    syms = _norm(symbols)
    per: dict[str, dict[str, Any]] = {}
    fresh: list[str] = []
    stale_or_missing: list[str] = []
    newest: datetime | None = None
    error: str | None = None
    rows: list[Any] = []
    if syms:
        try:
            rows = list(db_query(INFO_SQL, (syms,)) or [])
        except Exception as exc:  # noqa: BLE001 - e.g. the migration not yet applied; reported, never raised
            error = f"{type(exc).__name__}: {str(exc)[:160]}"
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "").upper()
        if sym not in syms:
            continue
        dt = _as_utc(r.get("fetched_at"))
        age = round(max(0.0, (ref - dt).total_seconds() / 3600.0), 3) if dt else None
        payload = r.get("payload")
        per[sym] = {
            "status": r.get("status"),
            "quote_type": r.get("quote_type"),
            "payload": payload if isinstance(payload, dict) else None,
            "payload_keys": r.get("payload_keys"),
            "error": r.get("error"),
            "as_of": dt.isoformat() if dt else None,
            "age_hours": age,
            "stale": age is None or age > float(max_age_hours),
        }
        if dt and (newest is None or dt > newest):
            newest = dt
    for sym in syms:
        rec = per.get(sym)
        (fresh if rec and not rec["stale"] else stale_or_missing).append(sym)
    out: dict[str, Any] = {
        "ok": error is None,
        "provider_calls": 0,
        "symbols": per,
        "fresh": fresh,
        "stale_or_missing": stale_or_missing,
    }
    if error:
        out["error"] = error
    out.update(
        envelope(
            DOMAIN,
            newest,
            now=ref,
            stale_after_hours=float(max_age_hours),
            source={"table": TABLE, "writer": WRITER, "projection": PROJECTION},
        )
    )
    return out
