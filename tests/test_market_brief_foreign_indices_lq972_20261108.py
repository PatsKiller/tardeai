"""Foreign index coverage for the market brief — design WU-7, operator decision D3 (LQ-20261107-972).

WU-7's primary source is a moomoo read-only host lane for HSI/HSTECH/N225/SSE; D3 takes the fallback tonight:
US-listed ETF proxies, labelled ``basis: etf_derived``, and NO index level passed off as one. This pins the fallback
so it cannot regress into a silent gap:

  * the brief's international universe carries the Europe proxies EWG EWU EZU VGK alongside the Asia/EM ones, so
    tonight's run covers the European close as well as Asia;
  * every proxy the brief READS is in ``config/market_reference_symbols.json`` — a proxy that is not in the quote
    universe can never produce a row, and the brief would report a gap it created itself;
  * each row is labelled ``etf_derived`` and no row claims to be an index level (the moomoo lane is refused today:
    no broker grant, no entitlement);
  * a proxy with no quote is NAMED in ``missing``, never rendered as a zero or dropped.

Hermetic: a fake ``db_query`` only, no DB, no network, no broker, no state, no schedule. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib import market_brief_inputs as bi  # noqa: E402

NOW = datetime(2026, 11, 8, 20, 0, tzinfo=timezone.utc)
EUROPE = ("EWG", "EWU", "EZU", "VGK")


def _quotes(symbols):
    """A fake db_query answer for INTL_SQL: one fresh quote per symbol in `symbols`."""
    seen = {str(s) for s in symbols}
    at = NOW - timedelta(hours=3)
    rows = []
    for i, sym in enumerate(bi.INTERNATIONAL_ETFS):
        if sym in seen:
            rows.append({"symbol": sym, "source": "schwab", "price": 100.0 + i, "day_change_pct": 0.5,
                         "fetched_at": at})
    return rows


def _db(rows):
    def q(sql, params=None):
        if "FROM market_quotes" in sql:
            return rows
        return []
    return q


def test_the_brief_reads_the_europe_proxies():
    for sym in EUROPE:
        assert sym in bi.INTERNATIONAL_ETFS, f"{sym} missing from the international universe"


def test_every_proxy_the_brief_reads_is_in_the_quote_universe():
    """A proxy absent from the universe is a gap the brief would report as data loss, not as a universe choice."""
    universe = set(json.loads((ROOT / "config" / "market_reference_symbols.json").read_text())["symbols"])
    assert set(bi.INTERNATIONAL_ETFS) <= universe, sorted(set(bi.INTERNATIONAL_ETFS) - universe)


def test_each_proxy_row_is_labelled_etf_derived_in_the_declared_order():
    md = bi.international(_db(_quotes(bi.INTERNATIONAL_ETFS)), now=NOW)
    assert md["state"] == "ok"
    assert [r["symbol"] for r in md["rows"]] == list(bi.INTERNATIONAL_ETFS)
    assert {r["basis"] for r in md["rows"]} == {"etf_derived"}
    assert md["missing"] == []


def test_no_row_claims_to_be_an_index_level():
    """The moomoo index lane is refused today (no grant, no entitlement); nothing here may imply it ran."""
    md = bi.international(_db(_quotes(bi.INTERNATIONAL_ETFS)), now=NOW)
    assert all(r["basis"] == "etf_derived" for r in md["rows"])
    assert "index" not in json.dumps(md).lower().replace("index level", "")


def test_a_proxy_with_no_quote_is_named_never_zero():
    """No rows at all is `empty` with every proxy named in `missing` — never a zero and never a silent absence."""
    md = bi.international(_db(_quotes(set())), now=NOW)
    assert md["state"] == "empty" and md["rows"] == []
    assert md["missing"] == list(bi.INTERNATIONAL_ETFS)
    assert all(r.get("price") is not None for r in md["rows"])  # never a zero for a row that exists


def test_one_missing_proxy_does_not_hide_the_others():
    rows = _quotes(set(bi.INTERNATIONAL_ETFS) - {"EZU"})
    md = bi.international(_db(rows), now=NOW)
    assert "EZU" in md["missing"] and md["missing"] == ["EZU"]
    assert "EWG" in {r["symbol"] for r in md["rows"]}
