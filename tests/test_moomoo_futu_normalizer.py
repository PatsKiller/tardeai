from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from moomoo.futu_normalizer import (
    normalize_order_book_payload,
    normalize_quote_payload,
    normalize_ticker_payload,
)


def test_quote_preserves_provider_and_receive_times():
    rows = [{"code": "US.AAPL", "last_price": 101.2, "bid_price": 101.1, "ask_price": 101.3, "data_date": "2026-07-28", "data_time": "10:00:01"}]
    result = normalize_quote_payload(rows, "2026-07-28T14:00:01.100+00:00")
    assert len(result) == 1
    assert result[0].symbol == "AAPL"
    assert result[0].tick.provider_at == "2026-07-28T10:00:01"
    assert result[0].tick.received_at.endswith("+00:00")


def test_order_book_preserves_bid_and_ask_provider_times_and_labels_local_sequence():
    raw = {
        "code": "US.NUAI",
        "Bid": [(4.31, 1000, 3)],
        "Ask": [(4.33, 800, 2)],
        "svr_recv_time_bid": "2026-07-28 10:01:00.100",
        "svr_recv_time_ask": "2026-07-28 10:01:00.120",
    }
    result = normalize_order_book_payload(raw, "2026-07-28T14:01:00.150+00:00", sequence_id=7, sequence_source="gateway_monotonic_per_reconnect_epoch")
    assert result is not None
    assert result.symbol == "NUAI"
    assert result.bid_provider_at.endswith(".100")
    assert result.ask_provider_at.endswith(".120")
    assert result.snapshot.sequence_id == 7
    assert result.sequence_source.startswith("gateway_monotonic")
    assert result.snapshot.bids[0] == (4.31, 1000.0)


def test_ticker_preserves_provider_sequence_and_direction():
    rows = [
        {"code": "US.AAPL", "time": "10:00:01.001", "price": 101.2, "volume": 10, "ticker_direction": "BUY", "sequence": 10},
        {"code": "US.AAPL", "time": "10:00:01.002", "price": 101.21, "volume": 5, "ticker_direction": "SELL", "sequence": 11},
    ]
    result = normalize_ticker_payload(rows, "2026-07-28T14:00:01.010+00:00")
    assert len(result) == 1
    assert result[0].provider_sequence == 11
    assert [print_.side for print_ in result[0].prints] == ["BUY", "SELL"]
    assert result[0].prints[-1].received_at.endswith("+00:00")
