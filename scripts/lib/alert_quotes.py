"""Prices for operator alerts — read from the Command Center data broker, nowhere else.

Operator rule 2026-10-05: "the source of truth should be the Command Center for all data. If data
needs to be refreshed, it's refreshed with the data broker in the Command Center and then spawned
out. Each individual process should not be going out looking for its own data sources."

The 16:15 material-change digest priced NVDA at $233.95 "26h old" from watchlist_items (an
enrichment copy) while the broker's market_quotes had $238.98 as of 16:00. Every alert producer
asks here instead. The freshness contract is the registry's (config/data_source_authority.json,
domain quote_price): stale after 15 min in the session, 72 h when closed. A refresh is the
broker's own waterfall (lib.data_broker.market_quote.get_price_batch) — never a provider call
from the producer.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "config" / "data_source_authority.json"
DOMAIN = "quote_price"
ET = ZoneInfo("America/New_York")


def freshness_contract(registry: Path | None = None) -> dict[str, float]:
    """{'open_h', 'closed_h'} for quote_price from the source registry."""
    d = json.loads((registry or REGISTRY).read_text(encoding="utf-8"))
    for dom in d.get("domains") or []:
        if dom.get("domain") == DOMAIN:
            return {"open_h": float(dom["stale_after_hours"]), "closed_h": float(dom["stale_after_hours_closed"])}
    raise KeyError(f"{DOMAIN} missing from {registry or REGISTRY}")


def session_open(now: datetime | None = None) -> bool:
    t = (now or datetime.now(timezone.utc)).astimezone(ET)
    return t.weekday() < 5 and (9, 30) <= (t.hour, t.minute) < (16, 0)


def stale_after_h(now: datetime | None = None, contract: dict | None = None) -> float:
    c = contract or freshness_contract()
    return c["open_h"] if session_open(now) else c["closed_h"]


def cursor_query(cur) -> Callable[..., list[dict[str, Any]]]:
    """Adapt a DB-API cursor to the broker's db_query(sql, params) → list[dict] contract."""
    def q(sql: str, params: Any = None, fetch: str = "all") -> list[dict[str, Any]]:
        cur.execute(sql, params)
        cols = [c[0] for c in (cur.description or [])]
        rows = cur.fetchall()
        return [r if isinstance(r, dict) else dict(zip(cols, r)) for r in rows]
    return q


def _age_h(as_of: Any, now: datetime) -> float | None:
    if not as_of:
        return None
    try:
        t = as_of if isinstance(as_of, datetime) else datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return max(0.0, (now - t).total_seconds() / 3600.0)


def broker_quotes(cur, symbols: Iterable[str], *, refresh: bool = False, now: datetime | None = None,
                  price_batch: Callable[..., dict] | None = None,
                  contract: dict | None = None) -> dict[str, dict[str, Any]]:
    """{SYM: {price, chg_pct, as_of, age_h, source, fresh}} from the data broker.

    Pass 1 reads the broker store (no live calls). With refresh=True, names older than the
    contract go through the broker's refresh waterfall once — still the broker, never a provider.
    A name the broker cannot price is absent: alerts render "no current price", never a guess.
    """
    if price_batch is None:
        try:
            from lib.data_broker.market_quote import get_price_batch as price_batch  # type: ignore
        except ImportError:  # imported as scripts.lib
            from scripts.lib.data_broker.market_quote import get_price_batch as price_batch  # type: ignore
    now = now or datetime.now(timezone.utc)
    syms = sorted({str(s).upper().strip() for s in symbols if s and str(s).strip()})
    if not syms:
        return {}
    c = contract or freshness_contract()
    bar = stale_after_h(now, c)
    q = cursor_query(cur)
    raw = price_batch(q, syms, max_age_hours=max(1, int(c["closed_h"])), skip_live=True) or {}
    out = {s: _row(v, now, bar) for s, v in raw.items()}
    if refresh:
        stale = [s for s in syms if s not in out or not out[s]["fresh"]]
        if stale:
            fresh = price_batch(q, stale, max_age_hours=max(1, int(bar)) if bar >= 1 else 1, skip_live=False) or {}
            for s, v in fresh.items():
                r = _row(v, now, bar)
                if s not in out or (r["age_h"] is not None and (out[s]["age_h"] is None or r["age_h"] < out[s]["age_h"])):
                    out[s] = r
    return out


def _row(v: dict, now: datetime, bar: float) -> dict[str, Any]:
    age = _age_h(v.get("as_of"), now)
    return {"price": v.get("price"), "chg_pct": v.get("chg_pct"), "as_of": v.get("as_of"),
            "age_h": age, "source": v.get("source"), "fresh": age is not None and age <= bar}


CC_API_BASE_ENV = "TRADEAI_CC_API_BASE"
CC_API_DEFAULT = "http://127.0.0.1:7777"


def cc_get(path: str, params: dict | None = None, *, timeout: float = 30.0) -> dict:
    """GET a Command Center read route and return its `data` payload (the CC is the source of truth).

    Raises on transport failure so the caller can render 'unavailable' instead of fetching elsewhere.
    """
    import os
    import urllib.parse
    import urllib.request
    base = (os.environ.get(CC_API_BASE_ENV) or CC_API_DEFAULT).rstrip("/")
    url = base + path + ("?" + urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
                         if params else "")
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 — local CC API only
        body = json.loads(r.read().decode("utf-8"))
    return body.get("data", body) if isinstance(body, dict) else body


def cc_option_chain(symbol: str, strikes: int = 40) -> dict:
    """Schwab option chain as the Command Center serves it (/api/v2/schwab/option-chain)."""
    return cc_get("/api/v2/schwab/option-chain", {"symbol": symbol.upper(), "strikes": strikes}) or {}
