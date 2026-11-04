"""ADVISORY_WATCH_QUOTE_CLOCK_20261104 — cx-openai-3 F2 on #2593.

The WATCH QUOTES stamp read CURRENT with ZERO joined quote timestamps: `join_watch_intelligence` fell back to the
snapshot's generated_at and classified that as a quote clock. A snapshot time is not a quote time; with no quote
joined the freshness must be UNKNOWN and the stamp must say so, while the generated time stays available as
`snapshot_as_of` so the page can qualify it.

The consumers are stubbed at the module boundary this function imports, so no DB, provider or network is touched.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import advisory_desk_operator as A  # noqa: E402


def _stub(monkeypatch, cards, generated_at):
    wl = type(sys)("lib.watchlist_intelligence")
    wl.list_intelligence = lambda **_k: {"cards": cards, "generated_at": generated_at}
    bi = type(sys)("lib.data_broker.watch_intelligence")
    bi.compose_broker_item = lambda sym, card=None: {"ok": True, "card": card or {}}
    bi.CONTRACT_VERSION = "watch_intelligence.broker.v1"
    monkeypatch.setitem(sys.modules, "lib.watchlist_intelligence", wl)
    monkeypatch.setitem(sys.modules, "lib.data_broker.watch_intelligence", bi)


def test_no_joined_quote_is_unknown_and_never_a_snapshot_time(monkeypatch):
    now = datetime.now(timezone.utc)
    _stub(monkeypatch, [{"symbol": "NVDA", "company": "NVIDIA"}], now.isoformat())  # no price_as_of anywhere
    out = A.join_watch_intelligence(["NVDA"])
    assert out["as_of"] is None, "a snapshot generated time was passed off as a quote clock"
    assert out["freshness"] == A.FRESH_UNKNOWN
    assert out["freshness_basis"] == "no joined quote timestamp"
    assert out["snapshot_as_of"] == now.isoformat(), "the generated time must stay available, qualified"


def test_a_joined_quote_still_sets_the_clock(monkeypatch):
    now = datetime.now(timezone.utc)
    _stub(monkeypatch, [{"symbol": "NVDA", "price_as_of": (now - timedelta(minutes=5)).isoformat()}], now.isoformat())
    out = A.join_watch_intelligence(["NVDA"])
    assert out["as_of"] is not None
    assert out["freshness"] == A.FRESH_CURRENT
    assert out["freshness_basis"] == "newest joined quote"
