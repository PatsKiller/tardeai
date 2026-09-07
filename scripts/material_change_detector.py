#!/usr/bin/env python3
"""material_change_detector.py — notice when a tracked name stops behaving like itself.

Stage 1 of docs/architecture/MATERIAL_CHANGE_TO_QUESTIONS.md. Advisory only: this
never sizes, orders, stops, or writes to a broker.

WHY THIS EXISTS
---------------
On 2026-09-05 three watchlist names were up 15-40% on the movers board and nothing
told the operator. Every research job on this box is schedule-triggered — */30 4-9,
30 9-15, 0 18,22. A sweep treats every name identically on every pass, so it cannot
notice that THIS name is behaving unlike ITSELF. That is the gap.

DETERMINISTIC AND FREE
----------------------
No model is called, on any row, ever. Detection must stay cheap and explainable so
the expensive judgement step downstream only runs on things that actually moved.

NORMALISED, NOT A FIXED PERCENT
-------------------------------
8% is noise in one name and a five-sigma event in another, so the threshold is the
move divided by the symbol's OWN average daily move.

True ATR needs high/low and ticker_prices carries only close_price. ATR does exist
in indicator_confluence_cache, but it covers 40 of 97 active watchlist symbols — it
could not evaluate more than half the universe. Close-to-close average daily move
covers 88 of 97. So the baseline is named for what it actually is (average daily
move, ADM) rather than borrowing the word ATR for a different calculation.

WHAT IT COULD NOT SEE IS PART OF THE OUTPUT
-------------------------------------------
A symbol with too little price history is NOT_EVALUABLE, counted and reported. A
detector that silently skips what it cannot measure inherits exactly the defect
stage 0 was built to end.

    python3 scripts/material_change_detector.py                 # dry run
    python3 scripts/material_change_detector.py --apply
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SCHEMA = "MaterialChange@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

#: Operator-set 2026-09-06, tunable without a deploy.
K = float(os.getenv("MATERIAL_CHANGE_K", "3.0"))
#: Fewer observations than this and the baseline is not a baseline.
MIN_OBS = int(os.getenv("MATERIAL_CHANGE_MIN_OBS", "20"))
BASELINE_DAYS = int(os.getenv("MATERIAL_CHANGE_BASELINE_DAYS", "90"))
#: Catalyst/news counted as "new" inside this window.
NEW_HOURS = int(os.getenv("MATERIAL_CHANGE_NEW_HOURS", "24"))
#: A news day this many times the symbol's own daily average is a burst.
NEWS_BURST_K = float(os.getenv("MATERIAL_CHANGE_NEWS_BURST_K", "3.0"))

HOLDINGS = ROOT / "data" / "portfolios" / "state" / "holdings.json"

#: MaterialChange@v1 is written and nothing reads it yet. Its consumers are stages
#: 2-4 of docs/architecture/MATERIAL_CHANGE_TO_QUESTIONS.md — the dossier assembler
#: and the single model call that turns a change into a narrative and questions —
#: plus the operator notification. This detector ships first ON PURPOSE: if the
#: thresholds are wrong, everything downstream is noise, and that is far cheaper to
#: discover with a deterministic producer nobody is acting on yet.
NO_CONSUMER_REASON = (
    "detector shipped ahead of its consumers so thresholds can be judged on real "
    "output before any model spend; consumers are stages 2-4 "
    "(docs/architecture/MATERIAL_CHANGE_TO_QUESTIONS.md)"
)

DDL = """
CREATE TABLE IF NOT EXISTS material_changes (
    id                BIGSERIAL PRIMARY KEY,
    change_guid       UUID UNIQUE NOT NULL,
    subject_guid      UUID,
    issuer_guid       UUID,
    symbol            TEXT NOT NULL,
    kind              TEXT NOT NULL,
    magnitude         NUMERIC,
    baseline          NUMERIC,
    observed_value    NUMERIC,
    observed_at       TIMESTAMPTZ NOT NULL,
    universe_reason   TEXT,
    evidence_json     JSONB,
    schema_version    TEXT NOT NULL,
    authority         TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS material_changes_subject_idx ON material_changes (subject_guid);
CREATE INDEX IF NOT EXISTS material_changes_observed_idx ON material_changes (observed_at DESC);
"""


def _db():
    import psycopg2

    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
    return psycopg2.connect(
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))


def change_guid(symbol: str, kind: str, observed_at: str) -> str:
    """Deterministic, minted as the rest of the spine mints.

    The same change observed twice — a re-run, an overlapping window — yields the
    same id and dedupes on the UNIQUE constraint instead of accumulating. A detector
    that re-emits the same finding forever is one nobody can read.
    """
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL,
                          f"tradeai:material_change:{symbol}|{kind}|{observed_at}"))


def universe(cur) -> dict[str, str]:
    """Watchlist + holdings. Returns {symbol: why_it_is_tracked}."""
    out: dict[str, str] = {}
    cur.execute("SELECT DISTINCT symbol FROM watchlist_items "
                "WHERE lower(coalesce(status,'')) = 'active' AND symbol IS NOT NULL")
    for (s,) in cur.fetchall():
        out[str(s).upper()] = "watchlist"
    if HOLDINGS.is_file():
        try:
            data = json.loads(HOLDINGS.read_text(encoding="utf-8"))
            rows = data.get("holdings") if isinstance(data, dict) else data
            for h in rows or []:
                sym = str((h or {}).get("symbol") or "").strip().upper()
                if sym:
                    out[sym] = "held" if sym not in out else "watchlist+held"
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN holdings unreadable ({type(exc).__name__}) — universe is "
                  f"watchlist-only this run", file=sys.stderr)
    return out


def price_excursions(cur, syms: dict[str, str]) -> tuple[list[dict], dict]:
    """|latest move| / the symbol's own average daily move >= K."""
    stats = {"evaluated": 0, "not_evaluable": 0, "fired": 0}
    found: list[dict] = []
    if not syms:
        return found, stats

    cur.execute(
        """
        WITH d AS (
            SELECT symbol, price_date, close_price,
                   lag(close_price) OVER (PARTITION BY symbol ORDER BY price_date) prev
              FROM ticker_prices
             WHERE symbol = ANY(%s) AND price_date > current_date - %s
               -- ticker_prices carries literal NaN in a numeric column (2 rows,
               -- 2026-09-06). Note numeric NaN compares EQUAL to itself in
               -- Postgres, unlike float, so this cannot be written as
               -- close_price = close_price.
               AND close_price IS NOT NULL AND close_price <> 'NaN'::numeric
        ), m AS (
            SELECT symbol, price_date,
                   abs(close_price - prev) / nullif(prev, 0) * 100.0 AS move_pct
              FROM d WHERE prev IS NOT NULL AND prev <> 0
        )
        SELECT symbol,
               count(*)                                   AS n,
               avg(move_pct)                              AS baseline,
               (array_agg(move_pct ORDER BY price_date DESC))[1] AS latest_move,
               (array_agg(price_date ORDER BY price_date DESC))[1] AS latest_date
          FROM m GROUP BY symbol
        """, (list(syms), BASELINE_DAYS))

    for sym, n, baseline, latest, latest_date in cur.fetchall():
        if n is None or n < MIN_OBS or not baseline or float(baseline) <= 0:
            stats["not_evaluable"] += 1
            continue
        stats["evaluated"] += 1
        ratio = float(latest or 0) / float(baseline)
        # Belt and braces. A NaN compares False to EVERY threshold, so
        # `if ratio < K: continue` lets it through and it FIRES — the dangerous
        # direction. Corrupt data must be skipped and counted, never alarmed on.
        if not math.isfinite(ratio):
            stats["evaluated"] -= 1
            stats["not_evaluable"] += 1
            continue
        if ratio < K:
            continue
        stats["fired"] += 1
        found.append({
            "symbol": sym, "kind": "price_excursion",
            "magnitude": round(ratio, 2),
            "baseline": round(float(baseline), 4),
            "observed_value": round(float(latest or 0), 4),
            "observed_at": str(latest_date),
            "universe_reason": syms[sym],
            "evidence": {"source": "ticker_prices", "observations": int(n),
                         "baseline_days": BASELINE_DAYS,
                         "note": "close-to-close average daily move; ticker_prices "
                                 "has no high/low so this is not ATR"},
        })
    return found, stats


def new_catalysts(cur, syms: dict[str, str]) -> tuple[list[dict], dict]:
    """A catalyst filed against a tracked name inside the window."""
    cur.execute(
        """SELECT symbol, count(*), max(published_at), min(id), max(id)
             FROM catalyst_events
            WHERE symbol = ANY(%s) AND published_at > now() - (%s || ' hours')::interval
            GROUP BY symbol""", (list(syms), NEW_HOURS))
    out = []
    for sym, n, latest, lo, hi in cur.fetchall():
        out.append({
            "symbol": sym, "kind": "catalyst_new", "magnitude": float(n),
            "baseline": None, "observed_value": float(n),
            "observed_at": str(latest), "universe_reason": syms.get(sym, "?"),
            "evidence": {"source": "catalyst_events", "count": int(n),
                         "id_range": [int(lo), int(hi)], "window_hours": NEW_HOURS},
        })
    return out, {"fired": len(out)}


def news_bursts(cur, syms: dict[str, str]) -> tuple[list[dict], dict]:
    """Article count over the symbol's own daily average."""
    cur.execute(
        """
        WITH recent AS (
            SELECT symbol, count(*) n, max(published_at) latest
              FROM news_articles
             WHERE symbol = ANY(%s) AND published_at > now() - (%s || ' hours')::interval
             GROUP BY symbol
        ), base AS (
            SELECT symbol, count(*)::numeric / %s AS per_day
              FROM news_articles
             WHERE symbol = ANY(%s) AND published_at > now() - (%s || ' days')::interval
             GROUP BY symbol
        )
        SELECT r.symbol, r.n, b.per_day, r.latest
          FROM recent r JOIN base b USING (symbol)
         WHERE b.per_day > 0 AND r.n >= b.per_day * %s
        """, (list(syms), NEW_HOURS, BASELINE_DAYS, list(syms), BASELINE_DAYS, NEWS_BURST_K))
    out = []
    for sym, n, per_day, latest in cur.fetchall():
        out.append({
            "symbol": sym, "kind": "news_burst",
            "magnitude": round(float(n) / float(per_day), 2),
            "baseline": round(float(per_day), 4), "observed_value": float(n),
            "observed_at": str(latest), "universe_reason": syms.get(sym, "?"),
            "evidence": {"source": "news_articles", "articles": int(n),
                         "window_hours": NEW_HOURS, "baseline_days": BASELINE_DAYS},
        })
    return out, {"fired": len(out)}


def persist(cur, changes: list[dict], *, apply: bool) -> int:
    """Idempotent on change_guid. Returns rows actually written."""
    if not apply:
        return 0
    from scripts.lib.cio_subject_guid import lookup_identity_envelope

    written = 0
    for c in changes:
        env = lookup_identity_envelope(c["symbol"])
        cur.execute(
            """INSERT INTO material_changes
                 (change_guid, subject_guid, issuer_guid, symbol, kind, magnitude,
                  baseline, observed_value, observed_at, universe_reason,
                  evidence_json, schema_version, authority)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (change_guid) DO NOTHING""",
            (change_guid(c["symbol"], c["kind"], c["observed_at"]),
             env.get("subject_guid"), env.get("issuer_guid"), c["symbol"], c["kind"],
             c["magnitude"], c["baseline"], c["observed_value"], c["observed_at"],
             c["universe_reason"], json.dumps(c["evidence"]), SCHEMA, AUTHORITY))
        written += cur.rowcount
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--kind", choices=["price_excursion", "catalyst_new", "news_burst"])
    args = ap.parse_args()

    conn = _db()
    cur = conn.cursor()
    if args.apply:
        cur.execute(DDL)
        conn.commit()

    syms = universe(cur)
    print(f"{SCHEMA} — apply={args.apply} K={K} universe={len(syms)} "
          f"(watchlist+held)")

    changes: list[dict] = []
    stats: dict[str, dict] = {}
    if args.kind in (None, "price_excursion"):
        c, s = price_excursions(cur, syms); changes += c; stats["price_excursion"] = s
    if args.kind in (None, "catalyst_new"):
        c, s = new_catalysts(cur, syms); changes += c; stats["catalyst_new"] = s
    if args.kind in (None, "news_burst"):
        c, s = news_bursts(cur, syms); changes += c; stats["news_burst"] = s

    changes.sort(key=lambda x: -(x["magnitude"] or 0))
    for c in changes[:25]:
        print(f"  {c['symbol']:>6} {c['kind']:<16} x{c['magnitude']:<7} "
              f"observed={c['observed_value']} baseline={c['baseline']} "
              f"({c['universe_reason']}) {c['observed_at'][:19]}")

    written = persist(cur, changes, apply=args.apply)
    if args.apply:
        conn.commit()
    conn.close()

    print("RESULT: " + json.dumps({
        "schema": SCHEMA, "authority": AUTHORITY, "model_calls": 0,
        "universe": len(syms), "K": K,
        "changes_found": len(changes),
        # None when nothing was measured; 0 is a measured zero.
        "rows_produced": written if args.apply else None,
        "by_kind": stats,
        "not_evaluable": stats.get("price_excursion", {}).get("not_evaluable", 0),
    }, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
