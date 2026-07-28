"""Pure normalization of Futu quote, order-book, and ticker callback payloads.

Provider timestamps are preserved separately from the UTC receive timestamp. Order-book
callbacks do not expose an exchange sequence in the documented payload; the gateway service
supplies and labels a reconnect-epoch-local monotonic sequence instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

try:
    from .quote_gateway import BookSnapshot, QuoteTick, TapePrint
except ImportError:  # pragma: no cover
    from quote_gateway import BookSnapshot, QuoteTick, TapePrint  # type: ignore


@dataclass(frozen=True)
class NormalizedBook:
    symbol: str
    snapshot: BookSnapshot
    bid_provider_at: Optional[str]
    ask_provider_at: Optional[str]
    received_at: str
    sequence_source: str


@dataclass(frozen=True)
class NormalizedQuote:
    symbol: str
    tick: QuoteTick
    received_at: str


@dataclass(frozen=True)
class NormalizedTape:
    symbol: str
    prints: tuple[TapePrint, ...]
    sequences: tuple[Optional[int], ...]
    provider_sequence: Optional[int]
    provider_at: Optional[str]
    received_at: str


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        try:
            records = value.to_dict("records")
            if isinstance(records, list):
                return [dict(row) for row in records if isinstance(row, Mapping)]
        except Exception:
            pass
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, (list, tuple)):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _float(value: Any) -> Optional[float]:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _symbol(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return raw[3:] if raw.startswith("US.") else raw


def _provider_time(row: Mapping[str, Any]) -> Optional[str]:
    for key in ("data_time", "time", "timestamp", "update_time", "svr_recv_time"):
        if row.get(key) not in (None, ""):
            date_value = row.get("data_date")
            return f"{date_value}T{row[key]}" if date_value else str(row[key])
    return None


def normalize_quote_payload(data: Any, received_at: str) -> list[NormalizedQuote]:
    output: list[NormalizedQuote] = []
    for row in _records(data):
        symbol = _symbol(row.get("code") or row.get("symbol"))
        if not symbol:
            continue
        tick = QuoteTick(
            bid=_float(row.get("bid_price") if "bid_price" in row else row.get("bid")),
            ask=_float(row.get("ask_price") if "ask_price" in row else row.get("ask")),
            last=_float(row.get("last_price") if "last_price" in row else row.get("price")),
            provider_at=_provider_time(row),
            received_at=received_at,
        )
        output.append(NormalizedQuote(symbol, tick, received_at))
    return output


def _pairs(rows: Any, levels: int) -> list[tuple[float, float]]:
    output: list[tuple[float, float]] = []
    for row in list(rows or [])[:levels]:
        try:
            if isinstance(row, Mapping):
                price = row.get("price")
                size = row.get("volume", row.get("size"))
            else:
                price, size = row[0], row[1]
            p, s = float(price), float(size)
            if p == p and s == s and p > 0 and s >= 0:
                output.append((p, s))
        except (TypeError, ValueError, IndexError, KeyError):
            continue
    return output


def normalize_order_book_payload(
    data: Any,
    received_at: str,
    *,
    sequence_id: Optional[int],
    sequence_source: str,
    levels: int = 10,
) -> Optional[NormalizedBook]:
    rows = _records(data)
    if not rows:
        return None
    row = rows[0]
    symbol = _symbol(row.get("code") or row.get("symbol"))
    if not symbol:
        return None
    bids = _pairs(row.get("Bid", row.get("bids")), levels)
    asks = _pairs(row.get("Ask", row.get("asks")), levels)
    bid_at = row.get("svr_recv_time_bid") or row.get("bid_provider_at")
    ask_at = row.get("svr_recv_time_ask") or row.get("ask_provider_at")
    provider_at = str(max(str(bid_at or ""), str(ask_at or ""))) or row.get("ts")
    snapshot = BookSnapshot(
        symbol=symbol,
        bids=bids,
        asks=asks,
        provider_at=str(provider_at) if provider_at else None,
        received_at=received_at,
        sequence_id=sequence_id,
    )
    return NormalizedBook(
        symbol=symbol,
        snapshot=snapshot,
        bid_provider_at=str(bid_at) if bid_at else None,
        ask_provider_at=str(ask_at) if ask_at else None,
        received_at=received_at,
        sequence_source=sequence_source,
    )


def _side(value: Any) -> Optional[str]:
    text = str(value or "").upper()
    if any(token in text for token in ("BUY", "BID", "UP")):
        return "BUY"
    if any(token in text for token in ("SELL", "ASK", "DOWN")):
        return "SELL"
    return None


def normalize_ticker_payload(data: Any, received_at: str) -> list[NormalizedTape]:
    grouped: dict[str, list[TapePrint]] = {}
    grouped_sequences: dict[str, list[Optional[int]]] = {}
    sequence: dict[str, Optional[int]] = {}
    provider_at: dict[str, Optional[str]] = {}
    for row in _records(data):
        symbol = _symbol(row.get("code") or row.get("symbol"))
        price = _float(row.get("price") if "price" in row else row.get("last_price"))
        size = _float(row.get("volume") if "volume" in row else row.get("size"))
        if not symbol or price is None or size is None:
            continue
        at = _provider_time(row)
        seq = _int(row.get("sequence"))
        grouped.setdefault(symbol, []).append(TapePrint(price, size, _side(row.get("ticker_direction")), at, received_at))
        grouped_sequences.setdefault(symbol, []).append(seq)
        if seq is not None:
            sequence[symbol] = max(seq, sequence.get(symbol) or seq)
        if at:
            provider_at[symbol] = at
    return [
        NormalizedTape(
            symbol,
            tuple(prints),
            tuple(grouped_sequences.get(symbol, [None] * len(prints))),
            sequence.get(symbol),
            provider_at.get(symbol),
            received_at,
        )
        for symbol, prints in grouped.items()
    ]
