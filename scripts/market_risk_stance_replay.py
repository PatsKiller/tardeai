#!/usr/bin/env python3
"""Replay the precision layer — sector attribution, shock type and per-position CIO stances with re-entry — over a
date range on the public-data fixtures (or an overlay of extra public bars), for a SYNTHETIC book.

  python3 scripts/market_risk_stance_replay.py --start 2026-10-14 --end 2026-10-30 \\
      --book GROWTH_ETF=fund:SCHG,PROXY=stock:industrials,STAPLE=stock:PG,HEALTH=stock:PFE \\
      [--overlay DIR] [--json]

Book entries are ``NAME=fund:<factsheet symbol>`` (look-through from config/fund_lookthrough.json) or
``NAME=stock:<sector key or listed symbol>``. Synthetic names only; no amounts (§2A). Evaluates each session at the
16:00 close (and at the 09:31 open when the fixture has opens). Read-only: nothing is written or sent.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.market_risk import lookthrough, policy as P, position_stances as ps  # noqa: E402
from scripts.lib.market_risk.fixture_reader import FixtureReader, close_instant  # noqa: E402


def _sma_above(reader: FixtureReader, sym: str, n: int, end: datetime) -> bool | None:
    rows = [r for r in reader.daily_bars([sym], sessions=n + 5, end=end) if r.get("close") is not None]
    if len(rows) < n:
        return None
    closes = [float(r["close"]) for r in rows]
    return closes[-1] >= sum(closes[-n:]) / n


def _exposures(book: dict[str, str], policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    basket = list((policy.get("ai_concentration") or {}).get("basket") or [])
    out = {}
    for name, spec in book.items():
        kind, _, ref = spec.partition(":")
        if kind == "fund":
            ex = lookthrough.exposure_for(ref, ai_basket=basket)
        else:
            sector_key = ref if ref in lookthrough.SECTOR_TO_GROUP.values() else None
            groups = {sector_key: 1.0} if sector_key else {}
            if not groups:
                ex = lookthrough.exposure_for(ref, ai_basket=basket, profiles=_profile_guess(ref))
            else:
                ex = {"symbol": name, "groups": groups, "basis": "synthetic sector", "reporting": []}
        out[name] = ex
    return out


def _profile_guess(sym: str) -> dict[str, dict[str, Any]]:
    known = {"PG": "Consumer Staples", "WMT": "Consumer Staples", "PFE": "Healthcare"}
    return {sym: {"sector": known.get(sym.upper(), "")}}


class CompositeReader:
    """Live database for every category (read-only PgReader) and the public-data fixture for the sector/theme ETF
    and single-name daily bars the database does not carry (``--live``)."""

    def __init__(self, pg: Any, fixture: FixtureReader, fixture_symbols: set[str]):
        self._pg, self._fx, self._syms = pg, fixture, fixture_symbols

    def daily_bars(self, symbols, *, sessions, end):
        symbols = list(symbols)
        fx = [s for s in symbols if s in self._syms]
        rest = [s for s in symbols if s not in self._syms]
        out = list(self._fx.daily_bars(fx, sessions=sessions, end=end)) if fx else []
        if rest:
            out += list(self._pg.daily_bars(rest, sessions=sessions, end=end))
        return out

    def __getattr__(self, name):
        return getattr(self._pg, name)


def run(
    start: date, end: date, book: dict[str, str], overlay: str | None = None, live: bool = False, opens: bool = False
) -> list[dict[str, Any]]:
    from scripts import market_risk_evaluate as mre
    from scripts.lib.market_risk.fixture_reader import open_instant

    policy = P.load_policy()
    fixture = FixtureReader(overlay=overlay) if overlay else FixtureReader()
    reader: Any = fixture
    if live:
        from scripts.lib.market_risk.reader import PgReader

        sec = policy.get("sectors") or {}
        syms = {s for g in sec.get("groups") or [] for s in g.get("symbols") or []} | set(sec.get("factor_symbols") or [])
        reader = CompositeReader(PgReader(), fixture, syms - {"SPY", "QQQ", "^VIX"})
    cfg = policy.get("positions") or {}
    exposures = _exposures(book, policy)
    sessions = [d for d in fixture.sessions(start=start - timedelta(days=10), end=end)]
    instants = []
    for d in sessions:
        if opens and d >= start:
            instants.append((d, open_instant(d) + timedelta(minutes=1), "open"))
        instants.append((d, close_instant(d), "close"))
    prior_doc: dict | None = None
    prior_st: dict[str, dict[str, Any]] = {}
    hist: list[dict[str, Any]] = []
    rows = []
    for d, now, when in instants:
        a = mre.evaluate(now, reader, policy, prior_doc)
        doc = a.to_dict()
        block = doc.get("sectors") or {}
        reentry = ps.reentry_conditions(
            flagged_groups=sorted({g for p in prior_st.values() for g in p.get("flagged_groups") or []}),
            sectors_block=block,
            history=hist,
            index_above_50d=_sma_above(reader, str(cfg.get("reclaim_symbol") or "QQQ"), 50, now),
            vix_below_20d=(None if (v := _sma_above(reader, "^VIX", 20, now)) is None else not v),
            engine_tier=str(doc.get("tier")),
            cfg=cfg,
        )
        st = ps.stances(
            positions=list(book), exposures=exposures, tier=str(doc.get("tier")), shock=doc.get("shock_type") or {},
            sectors_block=block, prior=prior_st, reentry=reentry, stop_distance_pct=None, policy=policy,
            as_of=now.isoformat(),
        )
        if d >= start:
            rows.append({"date": d.isoformat(), "when": when, "tier": doc.get("tier"), "market_tier": doc.get("market_tier"), "score": doc.get("score"),
                         "shock": (doc.get("shock_type") or {}).get("class"),
                         "hit": block.get("stressed"), "holding": block.get("resilient"),
                         "stances": {k: v["stance"] for k, v in st.items()}})
        if when == "close":
            hist.append({"tier": doc.get("tier"), "sectors": block})
        prior_doc, prior_st = doc, st
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--book", required=True)
    ap.add_argument("--overlay")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--live", action="store_true", help="categories from the live DB (read-only), sectors from fixtures")
    ap.add_argument("--opens", action="store_true", help="also evaluate at 09:31 ET each session")
    a = ap.parse_args(argv)
    book = dict(x.split("=", 1) for x in a.book.split(","))
    rows = run(date.fromisoformat(a.start), date.fromisoformat(a.end), book, a.overlay, a.live, a.opens)
    if a.json:
        print(json.dumps(rows, indent=1))
    else:
        for r in rows:
            print(f"{r['date']} {r['when']:5} {r['tier']:7} {r['shock'] or '-':9} hit={r['hit']} " + " ".join(f"{k}:{v}" for k, v in r["stances"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
