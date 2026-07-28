"""Live current-quote resolver with EXPLICIT source priority — no averaging.

A Moomoo-subscribed symbol is marked from the Moomoo gateway's QUOTE/TICKER observations;
every other symbol falls to the approved current-quote provider. The two are never blended —
each mark carries its source + provider timestamp so the UI can show provenance and freshness.

Read plane only: this reads quotes, never places/routes anything. Providers are injected so
the resolver is deterministic in tests (no live OpenD, no DB required).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

# source labels (must match config live_mark.source_priority tokens)
SRC_MOOMOO = "moomoo_subscribed"
SRC_APPROVED = "approved_current_quote_provider"


@dataclass(frozen=True)
class Mark:
    symbol: str
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    source: Optional[str]
    at: Optional[str]        # provider/observation timestamp (ISO)
    available: bool

    def to_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "bid": self.bid, "ask": self.ask, "last": self.last,
                "source": self.source, "at": self.at, "available": self.available}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LiveMarkResolver:
    """Resolve current marks with a fixed source priority.

    gateway            — the single QuoteGateway (latest_quote / latest_book), or None.
    is_moomoo_marked   — callable(symbol)->bool: is this symbol a live Moomoo QUOTE/TICKER sub?
    approved_provider  — callable(symbol)->dict|None: {bid,ask,last,at,source?} from the approved
                         existing current-quote provider (Alpaca/Schwab current mark, etc.).
    """

    def __init__(self, *, gateway: Any = None,
                 is_moomoo_marked: Optional[Callable[[str], bool]] = None,
                 approved_provider: Optional[Callable[[str], Optional[dict]]] = None,
                 priority: tuple[str, ...] = (SRC_MOOMOO, SRC_APPROVED)):
        self.gateway = gateway
        self.is_moomoo_marked = is_moomoo_marked or (lambda _s: False)
        self.approved_provider = approved_provider
        self.priority = priority

    def _from_moomoo(self, symbol: str) -> Optional[Mark]:
        if self.gateway is None:
            return None
        sym = symbol.upper()
        q = None
        try:
            q = self.gateway.latest_quote(sym)
        except Exception:
            q = None
        if q is not None and (q.last is not None or q.bid is not None or q.ask is not None):
            return Mark(sym, q.bid, q.ask, q.last, SRC_MOOMOO, q.provider_at, True)
        # fall back to the top-of-book from the L2 subscription (still a Moomoo mark)
        try:
            book = self.gateway.latest_book(sym)
        except Exception:
            book = None
        if book is not None and book.bids and book.asks:
            bid = float(book.bids[0][0]); ask = float(book.asks[0][0])
            return Mark(sym, bid, ask, (bid + ask) / 2.0, SRC_MOOMOO, book.provider_at, True)
        return None

    def _from_approved(self, symbol: str) -> Optional[Mark]:
        if self.approved_provider is None:
            return None
        try:
            q = self.approved_provider(symbol)
        except Exception:
            q = None
        if not q:
            return None
        return Mark(symbol.upper(), q.get("bid"), q.get("ask"), q.get("last"),
                    q.get("source") or SRC_APPROVED, q.get("at"), True)

    def resolve(self, symbol: str) -> Mark:
        sym = symbol.upper()
        for src in self.priority:
            if src == SRC_MOOMOO and self.is_moomoo_marked(sym):
                m = self._from_moomoo(sym)
                if m is not None:
                    return m
            elif src == SRC_APPROVED:
                m = self._from_approved(sym)
                if m is not None:
                    return m
        # honest "no mark" — never fabricate a price, never average
        return Mark(sym, None, None, None, None, None, False)
