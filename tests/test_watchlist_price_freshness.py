#!/usr/bin/env python3
"""One price per card, and it carries its own timestamp.

The BETA card showed $19.09 in its header and "current $19.83" in the Fib block
at the same moment — 4 pct apart on one card. The header served
watchlist_items.price (a cached enrichment snapshot written by a cron at 13:42);
the Fib panel derived its price from the latest OHLC bar. Every percentage in the
header — today's change, distance to stop, distance to target — was computed off
the stale one, and nothing displayed when either was taken.

Two traps were hit while fixing it, both of which these tests pin:

1. A literal '%' in the SQL comment ("4% apart") — psycopg2 reads it as a
   parameter placeholder and the execute dies with IndexError. The identical
   mistake had been made in watchlist_entry_planner hours earlier.

2. `upper(t.symbol) = upper(p.symbol)` in the lateral join. market_quotes has
   3.4M rows and an index on (symbol, fetched_at DESC); the functions made it
   unusable and the endpoint took 142 SECONDS. Both tables are all-uppercase, so
   the upper() calls bought nothing.

Pure: SQL is inspected as text. No database, no network.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "scripts" / "api_v2.py").read_text()
CARD = (ROOT / "apps" / "command-center-v3" / "src" / "components" / "WatchlistCardV4.tsx").read_text()


def _price_block() -> str:
    """The price-overlay SELECT plus its lateral join."""
    start = SRC.index("ONE PRICE PER CARD")
    return SRC[start:SRC.index("LEFT JOIN LATERAL (SELECT * FROM watchlist_strategy_cards", start)]


# ── the overlay exists and prefers live only when genuinely fresher ───────────

def test_live_quote_overlays_the_enrichment_snapshot():
    blk = _price_block()
    assert "market_quotes" in blk
    assert "AS price" in blk and "AS price_as_of" in blk and "AS price_source" in blk


def test_overlay_requires_the_quote_to_be_newer():
    """A stalled quote feed must not make the card go backwards."""
    blk = _price_block()
    assert "mq.fetched_at > p.last_enriched_at" in blk


def test_both_underlying_values_are_exposed():
    """Keeping both is what makes a divergence diagnosable instead of invisible."""
    blk = _price_block()
    assert "AS price_enriched" in blk and "AS price_live" in blk


def test_overlay_column_comes_after_star_so_it_wins():
    """`SELECT p.*` already yields `price`; the override only takes effect
    because it appears later and RealDictRow is last-wins. Verified against a
    live `SELECT 1 AS price, 2 AS price` returning 2."""
    blk = _price_block()
    star = SRC.index("SELECT p.*")
    override = SRC.index("END AS price,")
    assert star < override


# ── the two traps ─────────────────────────────────────────────────────────────

def test_no_literal_percent_in_the_price_sql():
    """psycopg2 reads '%' as a placeholder even inside a SQL comment."""
    for i, line in enumerate(_price_block().splitlines(), 1):
        if line.strip().startswith("#"):
            continue
        for m in re.finditer(r"%", line):
            assert line[m.end():m.end() + 1] == "s", (
                f"literal '%' at relative line {i}: {line.strip()[:110]!r}"
            )


def test_lateral_join_does_not_defeat_the_index():
    """upper() on either side of the join makes
    idx_market_quotes_symbol_fetched_at_desc unusable against 3.4M rows and took
    the endpoint from ~1.0s to 142s."""
    blk = _price_block()
    join = blk[blk.index("FROM market_quotes t"):]
    assert "upper(t.symbol)" not in join and "upper(p.symbol)" not in join, \
        "upper() in the market_quotes join defeats the index — 142s regression"
    assert "t.symbol = p.symbol" in join


def test_join_is_bounded_to_one_row():
    join = _price_block()
    assert "ORDER BY t.fetched_at DESC LIMIT 1" in join


# ── the card surfaces provenance ──────────────────────────────────────────────

def test_card_shows_the_as_of_timestamp():
    assert "price_as_of" in CARD, "the price must carry its own as-of stamp"
    assert "price_source" in CARD


def test_card_flags_a_stale_enrichment_price():
    """An enrichment-sourced price older than 15 minutes must say so rather than
    presenting itself as current."""
    assert "price_source === 'enrichment'" in CARD
    assert "15 * 60_000" in CARD


def test_card_tooltip_surfaces_a_divergence():
    assert "price_live" in CARD and "price_enriched" in CARD


def test_no_sub_ten_pixel_font_added():
    """The design guard rejects fonts below 10; a fontSize: 8 in this block was
    caught at build time."""
    start = CARD.index("ONE PRICE PER CARD") if "ONE PRICE PER CARD" in CARD else CARD.index("price_as_of")
    block = CARD[start:start + 2000]
    for m in re.finditer(r"fontSize:\s*(\d+)", block):
        assert int(m.group(1)) >= 10, f"fontSize {m.group(1)} below the 10px design floor"
