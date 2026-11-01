"""The reads behind the Home market-risk dollar join (design home/v005). Called by GET /api/v2/market-risk/latest.

Reads only: the holdings store (``portfolio_positions.load_store``), last-known resting stops (``last_known_stops``),
account display names (``account_display``), the market-risk policy, and — read-only — the trade ledger for the
data-conflict item and the loss a wash sale deferred. Every read fails soft: a missing input drops that part of the
card, never the projection. Nothing is written.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _import(name: str):
    import importlib

    for mod in (f"lib.{name}", f"scripts.lib.{name}"):
        try:
            return importlib.import_module(mod)
        except ImportError:
            continue
    raise ImportError(name)


def _ro_conn():
    """A DEDICATED connection (session13_db.get_conn, the engine reader's), made read-only before its first query and
    closed after — never the API thread's shared db_adapter connection."""
    try:
        from session13_db import get_conn  # type: ignore
    except ImportError:  # pragma: no cover
        from scripts.session13_db import get_conn
    conn = get_conn()
    if hasattr(conn, "set_session"):
        conn.set_session(readonly=True)
    elif hasattr(conn, "read_only"):
        conn.read_only = True
    else:
        conn.close()
        raise RuntimeError("connection cannot be made read-only")
    return conn


def _built_at(store: dict) -> datetime | None:
    raw = str(store.get("positions_built_at") or "").replace(" ET", "").strip()
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=ET)
    except ValueError:
        return None


def _assessment_budgets(projection: dict[str, Any]) -> list[dict[str, Any]]:
    """Budget breaches WITH their numbers, read from the engine's own assessment file (local), not from the snapshot:
    the snapshot every consumer (CIO, Ask-the-CIO) reads keeps budget names only (review of #2383, M3)."""
    import json
    import os
    from pathlib import Path

    root = Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")
    name = "shadow_latest.json" if projection.get("mode") == "shadow" else "latest.json"
    try:
        doc = json.loads((root / "data" / "runtime" / "market_risk" / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if str(doc.get("as_of") or "") != str(projection.get("as_of") or ""):
        return []  # a different evaluation than the one shown: never mix numbers across runs
    return [
        {**b, "scope_id": b.get("scope")}
        for b in ((doc.get("portfolio") or {}).get("budget_breaches") or [])
        if isinstance(b, dict) and b.get("breached", True)
    ]


def join(
    projection: dict[str, Any], *, now: datetime | None = None, budgets: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """The projection with ``book_exposure``, ``review``, ``scope_labels``, ``budgets_detail`` and ``reentry_detail``
    added (or ``book_exposure_error`` with the reason)."""
    if projection.get("state") not in ("evaluated", "stale"):
        return projection
    now = now or datetime.now(timezone.utc)
    bd = _import("market_risk_book_dollars")
    try:
        pp = _import("portfolio_positions")
        store = pp.load_store()
        if not store:
            return {**projection, "book_exposure_error": "holdings store unreadable"}
        ad = _import("account_display")
        pol_mod = _import("market_risk.policy")
        policy = pol_mod.load_policy()
    except Exception as exc:  # noqa: BLE001
        return {**projection, "book_exposure_error": f"{type(exc).__name__}: {exc}"}
    stops: list[dict[str, Any]] | None = None
    try:
        lks = _import("last_known_stops")
        stops = [
            {"account": r.get("account"), "symbol": r.get("symbol"), "stop_price": r.get("stop_price")}
            for r in lks.load_last_known(brokers=("schwab",), now=now)
        ]
    except Exception:  # noqa: BLE001 — without stops, no stop column and no stop items (said in the card)
        stops = None
    ledger_sells: list[dict[str, Any]] = []
    ledger_error: str | None = None
    deferred_cache: dict[tuple[str, str], list[tuple[str, float]]] = {}
    conn = None
    try:
        conn = _ro_conn()
        built = _built_at(store)
        with conn.cursor() as cur:
            if built is not None:
                cur.execute(
                    "SELECT s.symbol, s.account, s.trade_date FROM trade_transactions s "
                    "WHERE lower(s.action) LIKE 'sell%%' AND s.trade_time > %s AND NOT EXISTS ("
                    " SELECT 1 FROM trade_transactions b WHERE b.symbol = s.symbol AND b.account = s.account "
                    " AND lower(b.action) LIKE 'buy%%' AND b.trade_time > s.trade_time)",
                    (built,),
                )
                ledger_sells = [{"symbol": r[0], "account": r[1], "date": str(r[2])[:10]} for r in cur.fetchall()]
            cur.execute(
                "SELECT symbol, account, close_date, pnl FROM trade_closed WHERE close_date >= %s::date - 45 AND pnl < 0",
                (now.date(),),
            )
            for sym, acct, d, pnl in cur.fetchall():
                deferred_cache.setdefault((str(sym).upper(), str(d)[:10]), []).append((str(acct), float(pnl)))
    except Exception as exc:  # noqa: BLE001 — no ledger: no data-conflict item and no deferred-loss amount
        ledger_error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:  # noqa: BLE001
            pass

    def deferred_loss(sym: str, scope: str, date: str) -> float | None:
        rows = [
            pnl for acct, pnl in deferred_cache.get((sym.upper(), str(date)[:10]), [])
            if scope in (bd.opaque_account(acct), bd.opaque_account(ad.canonical_key(acct)))
        ]
        return round(-sum(rows), 2) if rows else None

    proj_for_join = {**projection, "book": {**(projection.get("book") or {}),
                                            "budgets": budgets if budgets is not None else _assessment_budgets(projection)}}
    try:
        out = bd.build(
            proj_for_join, store, stops=stops, policy=policy, label_fn=ad.account_label, canon_fn=ad.canonical_key,
            ledger_sells=ledger_sells, deferred_loss=deferred_loss,
        )
    except Exception as exc:  # noqa: BLE001
        return {**projection, "book_exposure_error": f"{type(exc).__name__}: {exc}"}
    be = out["book_exposure"]
    be["stops_known"] = stops is not None
    be["ledger_error"] = ledger_error
    return {
        **projection,
        "book_exposure": be,
        "review": out["review"],
        "scope_labels": out["scope_labels"],
        "budgets_detail": out["budgets"],
        "reentry_detail": out["reentry"],
        "reentry_card": (policy.get("reentry_watch") or {}).get("card") or {},
    }
