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
import re
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

#: PRECEDENCE — what gets looked at first when the queue is longer than the budget.
#:
#: Operator instruction 2026-09-06: held names rank very high, an operator request
#: ranks highest, and watchlist / preferred / re-entry outrank an ordinary tracked
#: name. This is not cosmetic ordering: curation and routing are both capped per run,
#: so precedence decides what actually gets researched when more moved than we can
#: afford to look at.
#:
#: Money at risk outranks money considered. A held name that moves is a position
#: behaving unlike itself; a watchlist name that moves is an idea behaving unlike
#: itself. Both are worth knowing, in that order.
PRECEDENCE = {
    "operator": 100,   # the operator asked about it directly
    "held": 80,        # a live position
    "reentry": 70,     # a name we exited and are watching to re-enter
    "preferred": 60,   # core / S0 scope — the curated shortlist
    "watchlist": 40,   # ordinary tracked idea
    "other": 10,
}


def precedence_for(reasons: set[str]) -> tuple[int, str]:
    """Highest tier a symbol qualifies for. Returns (score, label)."""
    best, label = PRECEDENCE["other"], "other"
    for r in reasons:
        if PRECEDENCE.get(r, 0) > best:
            best, label = PRECEDENCE[r], r
    return best, label

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
    precedence        INTEGER,
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
-- CREATE TABLE IF NOT EXISTS does NOT add columns to a table that already exists, so
-- every column added after the first deploy needs its own ALTER. Without this the
-- INSERT fails with UndefinedColumn on exactly the installs that already work.
ALTER TABLE material_changes ADD COLUMN IF NOT EXISTS precedence INTEGER;
CREATE INDEX IF NOT EXISTS material_changes_precedence_idx
    ON material_changes (precedence DESC, magnitude DESC);
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


def universe(cur) -> dict[str, dict]:
    """Everything tracked, with WHY it is tracked and how much it outranks.

    Returns {symbol: {"reasons": {...}, "precedence": int, "tier": str}}.
    A symbol can qualify several ways; the highest tier wins.
    """
    reasons: dict[str, set[str]] = {}

    def add(sym: str, why: str) -> None:
        s = str(sym or "").strip().upper()
        if s:
            reasons.setdefault(s, set()).add(why)

    cur.execute("SELECT DISTINCT symbol FROM watchlist_items "
                "WHERE lower(coalesce(status,'')) = 'active' AND symbol IS NOT NULL")
    for (sym,) in cur.fetchall():
        add(sym, "watchlist")

    # Preferred = the curated shortlist: core source tier, or S0 scope.
    cur.execute("""SELECT DISTINCT symbol FROM watchlist_items
                    WHERE lower(coalesce(status,''))='active' AND symbol IS NOT NULL
                      AND (lower(coalesce(source_tier,''))='core'
                           OR upper(coalesce(scope_tier,''))='S0')""")
    for (sym,) in cur.fetchall():
        add(sym, "preferred")

    # Optional sources, each inside a SAVEPOINT.
    #
    # In Postgres a failed statement aborts the WHOLE transaction, and every later
    # statement then fails with InFailedSqlTransaction. A bare try/except around an
    # optional probe therefore does not make it optional — it hides the failure and
    # poisons everything after it. That is exactly what happened here: a missing
    # column on an optional table took down the price query twenty lines later.
    # (table, tier, time column). The time column is NAMED because guessing it is how
    # the operator tier — the highest one — silently never applied: this used
    # created_at, and inbound_operator_questions calls it received_at. The savepoint
    # caught the error and warned, so nothing broke; it just quietly did nothing.
    for table, why, tcol in (
        ("reentry_directive_hits_staging", "reentry", None),
        ("inbound_operator_questions", "operator", "received_at"),
    ):
        extra = f" AND {tcol} > now() - interval '30 days'" if tcol else ""
        try:
            cur.execute("SAVEPOINT opt_src")
            cur.execute(f"SELECT to_regclass('public.{table}')")
            if cur.fetchall()[0][0] is None:
                cur.execute("RELEASE SAVEPOINT opt_src")
                continue
            cur.execute(f"SELECT DISTINCT symbol FROM {table} "
                        f"WHERE symbol IS NOT NULL{extra}")
            for (sym,) in cur.fetchall():
                add(sym, why)
            cur.execute("RELEASE SAVEPOINT opt_src")
        except Exception as exc:  # noqa: BLE001
            cur.execute("ROLLBACK TO SAVEPOINT opt_src")
            print(f"  WARN optional source {table} unusable "
                  f"({type(exc).__name__}) — precedence tier '{why}' not applied "
                  f"this run", file=sys.stderr)

    if HOLDINGS.is_file():
        try:
            data = json.loads(HOLDINGS.read_text(encoding="utf-8"))
            rows = data.get("holdings") if isinstance(data, dict) else data
            for h in rows or []:
                add((h or {}).get("symbol"), "held")
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN holdings unreadable ({type(exc).__name__}) — universe is "
                  f"watchlist-only this run", file=sys.stderr)

    out = {}
    for sym, why in reasons.items():
        score, tier = precedence_for(why)
        out[sym] = {"reasons": sorted(why), "precedence": score, "tier": tier}
    return out


#: A move must be confirmed by a SECOND source before it is called a change.
#:
#: Measured 2026-09-06. The first live run produced eight excursions and SIX were
#: corrupt prices, faithfully reported:
#:
#:     NOC   528.37 -> 119.32  (-77%)   watchlist_items.change_pct says  -2.44%
#:     SCHG   35.83 ->   8.15  (-77%)                                    +0.28%
#:     JEPI   57.42 ->  22.41  (-61%)                                    -0.08%
#:     BND    71.92 ->  55.64  (-23%)                                    -0.57%
#:     AOUT                     +45.4%                                  +45.44%  <- real
#:
#: The real move agreed with the independent source to four decimal places; every
#: corrupt one disagreed by an order of magnitude. Agreement between two
#: independently-written sources is the discriminator, and it costs nothing.
#:
#: Tolerance is a RATIO, not a percentage-point difference: 2pp is nothing on a 45%
#: move and everything on a 0.5% one.
CORROBORATION_RATIO = float(os.getenv("MATERIAL_CHANGE_CORROBORATION_RATIO", "2.0"))
#: Below this both sources are saying "nothing happened" and the ratio between them
#: is meaningless.
CORROBORATION_FLOOR_PCT = float(os.getenv("MATERIAL_CHANGE_CORROBORATION_FLOOR", "1.0"))


#: CATALYST MATERIALITY — not every catalyst is a reason to look.
#:
#: The first version of catalyst_new fired on ANY catalyst filed against a tracked
#: name in 24h. Measured over 30 days, catalyst_type is dominated by a single value:
#:
#:     other                 27,567     merger_acquisition       880
#:     news_momentum            822     earnings_beat            788
#:     analyst_upgrade          692     geopolitical             295
#:     buyback                  237     analyst_downgrade        229
#:     earnings_miss            220     contract_win             201
#:     insider_buy              192     offering_dilution        152
#:     guidance_raise            86     fda_approval              78
#:
#: 87% of catalysts are `other` — an unclassified bucket. Treating those as equal to
#: an earnings miss is how a trigger becomes noise, and a noisy trigger is one the
#: operator learns to ignore. That is the same failure as a muted alarm, arrived at
#: from the opposite direction.
#:
#: Weight is materiality, not confidence: how much a reasonable analyst would want to
#: re-examine a position on hearing it. `other` is deliberately absent — an
#: unclassified catalyst is not evidence of anything, and admitting it at a low weight
#: would still let 27,567 rows through.
CATALYST_MATERIALITY = {
    "earnings_miss": 3.0,
    "guidance_cut": 3.0,
    "fda_rejection": 3.0,
    "offering_dilution": 2.5,
    "earnings_beat": 2.0,
    "guidance_raise": 2.0,
    "merger_acquisition": 2.5,
    "fda_approval": 2.0,
    "analyst_downgrade": 1.5,
    "analyst_upgrade": 1.2,
    "contract_win": 1.2,
    "insider_buy": 1.2,
    "buyback": 1.0,
    "geopolitical": 1.0,
}
#: PRICE TARGET CHANGES — material, and invisible to catalyst_type.
#:
#: The operator asked directly: "if an analyst target moved to 425, would that be in
#: here?" It would not have been. Measured 2026-09-07: 387 catalyst headlines in 30
#: days mention a price target, and most carry catalyst_type='other' — the
#: unclassified bucket this detector deliberately excludes as noise.
#:
#:     [other]           Capital One Adjusts Price Target on Diamondback to $283 From $272
#:     [analyst_upgrade] NVT -- Price Target Raised to $210
#:
#: So the taxonomy is not sufficient on its own. A target move is a concrete,
#: checkable change in what a covering analyst thinks a name is worth, which is
#: exactly the class of thing worth re-examining a position over. Matched on the
#: headline, and weighted between an upgrade and an earnings beat.
PRICE_TARGET_RE = re.compile(
    r"(price target|\bPT\b)\s*(raised|lowered|cut|increased|reduced|adjust\w*|"
    r"to\s*\$?\d)|(raises|lowers|cuts|boosts|trims)\s+(price\s+)?target", re.I)
PRICE_TARGET_MATERIALITY = float(os.getenv("MATERIAL_CHANGE_PT_MATERIALITY", "1.8"))
#: Postgres POSIX form of the same pattern, for filtering in SQL.
PRICE_TARGET_SQL = ("(price target|\\mPT\\M).*(raise|lower|cut|increase|reduce|adjust|to *\\$?[0-9])""|(raises|lowers|cuts|boosts|trims) +(price +)?target")


#: A catalyst must reach this to be worth the operator's attention at all.
#: Raised from 1.0 to 2.0 on 2026-09-07. At 1.0 the alert carried "NOC: new catalyst
#: (x1.2 vs usual)" and "JEPI: new catalyst (x1.0)" — one analyst note and one
#: insider buy, announced to the operator as though something had changed. The
#: operator's verdict: "what am I supposed to do with these".
#:
#: A single upgrade, a buyback or an insider buy is context, not an event. At 2.0 the
#: bar is an earnings result, guidance, M&A, an FDA decision, dilution, or a price
#: target move — things that change what a name is worth. Two analyst downgrades on
#: one name still clears it (1.5 x 2), which is right: a pattern is an event even when
#: each piece is not.
CATALYST_MIN_MATERIALITY = float(os.getenv("MATERIAL_CHANGE_CATALYST_MIN", "2.0"))


#: SECTOR — assembled from five partial sources, because no single one is enough.
#:
#: Measured 2026-09-06 against 113 active watchlist symbols:
#:
#:     hermes_v_ticker_context        44
#:     intelligence_entities          46
#:     news_articles.gics_sector      29
#:     market_movers                  17
#:     aegis_symbol_snapshot_nightly  11
#:     ---------------------------------
#:     UNION                          64
#:
#: 57%, up from the 26% that news_articles alone provides. Still not complete, which
#: is why what could NOT be resolved is counted and reported rather than quietly
#: dropped: a sector trigger that silently covers half the universe looks exactly
#: like one that covers all of it.
#:
#: Order is by directness, not by row count. intelligence_entities and
#: hermes_v_ticker_context carry a per-symbol sector as a fact about the instrument;
#: news_articles.gics_sector is inferred from an article ABOUT the symbol and is the
#: weakest, so it goes last.
SECTOR_SOURCES = (
    ("intelligence_entities", "entity_id", "sector"),
    ("hermes_v_ticker_context", "symbol", "sector"),
    ("market_movers", "symbol", "sector"),
    ("aegis_symbol_snapshot_nightly", "symbol", "sector"),
    ("news_articles", "symbol", "gics_sector"),
)

#: A sector event: this many tracked names in one sector moving materially the same
#: day. One name moving is a company story; several at once is a sector story, and
#: they want different questions.
SECTOR_MIN_NAMES = int(os.getenv("MATERIAL_CHANGE_SECTOR_MIN_NAMES", "3"))
#: Each contributing name must clear this multiple of its OWN average daily move —
#: lower than K, because the signal is breadth rather than any single excursion.
SECTOR_NAME_K = float(os.getenv("MATERIAL_CHANGE_SECTOR_NAME_K", "1.5"))


def resolve_sectors(cur, symbols: list[str]) -> tuple[dict[str, str], dict]:
    """{SYMBOL: sector} from the first source that knows, plus what was unresolved."""
    out: dict[str, str] = {}
    per_source: dict[str, int] = {}
    if not symbols:
        return out, {"resolved": 0, "unresolved": 0, "per_source": per_source}

    for table, keycol, sectorcol in SECTOR_SOURCES:
        missing = [s for s in symbols if s not in out]
        if not missing:
            break
        try:
            cur.execute("SAVEPOINT sec_src")
            cur.execute(f"SELECT to_regclass('public.{table}')")
            if cur.fetchall()[0][0] is None:
                cur.execute("RELEASE SAVEPOINT sec_src")
                continue
            cur.execute(
                f"SELECT DISTINCT upper({keycol}), {sectorcol} FROM {table} "
                f"WHERE upper({keycol}) = ANY(%s) AND {sectorcol} IS NOT NULL",
                (missing,))
            n = 0
            for sym, sector in cur.fetchall():
                if sym not in out:
                    out[sym] = str(sector).strip()
                    n += 1
            per_source[table] = n
            cur.execute("RELEASE SAVEPOINT sec_src")
        except Exception as exc:  # noqa: BLE001
            cur.execute("ROLLBACK TO SAVEPOINT sec_src")
            print(f"  WARN sector source {table} unusable ({type(exc).__name__})",
                  file=sys.stderr)
    return out, {"resolved": len(out), "unresolved": len(symbols) - len(out),
                 "per_source": per_source}


def sector_moves(cur, syms: dict[str, dict], excursion_stats: list[dict]) -> tuple[list[dict], dict]:
    """Several tracked names in one sector moving materially on the same day.

    Built from the SAME per-symbol baselines the price test already computed, so a
    sector event cannot be manufactured by a different definition of "moved". Only
    names that passed corroboration are counted — a sector story assembled from six
    corrupt prices would be six times as wrong.
    """
    sectors, sstats = resolve_sectors(cur, sorted(syms))
    stats = {"fired": 0, "sector_resolved": sstats["resolved"],
             "sector_unresolved": sstats["unresolved"],
             "sector_sources": sstats["per_source"]}
    if not excursion_stats:
        return [], stats

    by_sector: dict[str, list[dict]] = {}
    for e in excursion_stats:
        sec = sectors.get(str(e["symbol"]).upper())
        if sec:
            by_sector.setdefault(sec, []).append(e)

    out = []
    for sector, members in by_sector.items():
        if len(members) < SECTOR_MIN_NAMES:
            continue
        stats["fired"] += 1
        members.sort(key=lambda m: -m["ratio"])
        best = members[0]
        out.append({
            "symbol": best["symbol"], "kind": "sector_move",
            "magnitude": round(sum(m["ratio"] for m in members) / len(members), 2),
            "baseline": None, "observed_value": float(len(members)),
            "observed_at": best["observed_at"],
            "universe_reason": "+".join((syms.get(best["symbol"]) or {}).get("reasons", ["?"])),
            "precedence": max((syms.get(m["symbol"]) or {}).get("precedence", 10)
                              for m in members),
            "evidence": {"source": "ticker_prices+sector", "sector": sector,
                         "names": [m["symbol"] for m in members],
                         "name_k": SECTOR_NAME_K, "min_names": SECTOR_MIN_NAMES},
            # What this change is ABOUT. `symbol` above is a representative
            # MEMBER, carried so the row stays joinable and the notifier has a
            # ticker to show -- it is NOT the subject. Without this declaration
            # persist() resolved identity from that member and stamped a SECURITY
            # guid onto a SECTOR event: 13 of 14 live sector_move rows carry one.
            # AGENTS.md §17A: "Topics are subjects, not securities."
            "subject": {"entity_type": "SECTOR", "value": sector},
            "mentions": [{"entity_type": "SECURITY", "value": m["symbol"]}
                         for m in members],
        })
    return out, stats


def corroborate(cur, symbols: list[str]) -> dict[str, float]:
    """Independent per-symbol move, written by a different pipeline."""
    if not symbols:
        return {}
    cur.execute(
        """SELECT upper(symbol), max(abs(change_pct))
             FROM watchlist_items
            WHERE symbol = ANY(%s) AND change_pct IS NOT NULL
            GROUP BY 1""", (symbols,))
    return {r[0]: float(r[1]) for r in cur.fetchall()}


def agrees(observed: float, independent: float | None) -> tuple[bool, str]:
    """Do two independently-written sources tell the same story?

    A symbol with NO independent source is NOT corroborated — reported, never
    alarmed on. Firing on a single source is exactly how six corrupt rows became six
    operator alerts.
    """
    if independent is None:
        return False, "no_independent_source"
    if observed < CORROBORATION_FLOOR_PCT and independent < CORROBORATION_FLOOR_PCT:
        return False, "both_below_floor"
    lo, hi = sorted((max(observed, 1e-9), max(independent, 1e-9)))
    if hi / lo > CORROBORATION_RATIO:
        return False, f"disagree_{observed:.2f}_vs_{independent:.2f}"
    return True, "corroborated"


def price_excursions(cur, syms: dict[str, str]) -> tuple[list[dict], dict]:
    """|latest move| / the symbol's own average daily move >= K."""
    stats = {"evaluated": 0, "not_evaluable": 0, "fired": 0, "uncorroborated": 0}
    found: list[dict] = []
    candidates: list[tuple] = []
    contributors: list[dict] = []
    if not syms:
        return found, stats, contributors

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
            # Below the individual bar, but it may still contribute to a
            # sector story — that decision needs corroboration too, so it
            # is made after the second-source check below, not here.
            candidates.append((sym, ratio, baseline, latest, latest_date, n, False))
            continue
        stats["fired"] += 1
        candidates.append((sym, ratio, baseline, latest, latest_date, n, True))

    # Second source, one query for all candidates.
    independent = corroborate(cur, [c[0] for c in candidates])
    for sym, ratio, baseline, latest, latest_date, n, fires in candidates:
        ok, why = agrees(float(latest or 0), independent.get(sym))
        if not ok:
            if fires:
                stats["fired"] -= 1
            if fires:
                stats["uncorroborated"] += 1
                stats.setdefault("uncorroborated_detail", []).append(f"{sym}:{why}")
            continue
        # Corroborated and above the (lower) sector bar — eligible to contribute to a
        # sector story even when it does not clear K on its own.
        if ratio >= SECTOR_NAME_K:
            contributors.append({"symbol": sym, "ratio": round(ratio, 2),
                                 "observed_at": str(latest_date)})
        if not fires:
            continue
        found.append({
            "symbol": sym, "kind": "price_excursion",
            "magnitude": round(ratio, 2),
            "baseline": round(float(baseline), 4),
            "observed_value": round(float(latest or 0), 4),
            "observed_at": str(latest_date),
            "universe_reason": "+".join(syms[sym]["reasons"]),
            "precedence": syms[sym]["precedence"],
            "evidence": {"source": "ticker_prices", "observations": int(n),
                         "baseline_days": BASELINE_DAYS,
                         "independent_pct": independent.get(sym),
                         "note": "close-to-close average daily move; ticker_prices "
                                 "has no high/low so this is not ATR. Confirmed "
                                 "against watchlist_items.change_pct."},
        })
    return found, stats, contributors


def new_catalysts(cur, syms: dict[str, dict]) -> tuple[list[dict], dict]:
    """A MATERIAL catalyst filed against a tracked name inside the window.

    Materiality-weighted, so an earnings miss outranks a buyback and an unclassified
    `other` never fires at all.
    """
    cur.execute(
        """SELECT symbol, catalyst_type, count(*), max(published_at),
                  min(id), max(id),
                  bool_or(headline ~* %s) AS is_price_target
             FROM catalyst_events
            WHERE symbol = ANY(%s)
              AND published_at > now() - (%s || ' hours')::interval
              AND (catalyst_type = ANY(%s) OR headline ~* %s)
            GROUP BY symbol, catalyst_type""",
        (PRICE_TARGET_SQL, list(syms), NEW_HOURS,
         [k for k, v in CATALYST_MATERIALITY.items() if v >= CATALYST_MIN_MATERIALITY],
         PRICE_TARGET_SQL))

    by_symbol: dict[str, dict] = {}
    stats = {"fired": 0, "below_materiality": 0, "types_seen": {}}
    for sym, ctype, n, latest, lo, hi, is_pt in cur.fetchall():
        weight = CATALYST_MATERIALITY.get(ctype, 0.0)
        if is_pt:
            # A price-target move is material even when the taxonomy says `other`.
            weight = max(weight, PRICE_TARGET_MATERIALITY)
            ctype = f"{ctype}+price_target" if ctype else "price_target"
        stats["types_seen"][ctype] = stats["types_seen"].get(ctype, 0) + int(n)
        if weight < CATALYST_MIN_MATERIALITY:
            stats["below_materiality"] += int(n)
            continue
        cur_best = by_symbol.get(sym)
        score = weight * min(int(n), 3)          # more of the same matters, but not linearly
        if cur_best is None or score > cur_best["magnitude"]:
            by_symbol[sym] = {
                "symbol": sym, "kind": "catalyst_new",
                "magnitude": round(score, 2), "baseline": None,
                "observed_value": float(n), "observed_at": str(latest),
                "universe_reason": "+".join((syms.get(sym) or {}).get("reasons", ["?"])),
                "precedence": (syms.get(sym) or {}).get("precedence", 10),
                "evidence": {"source": "catalyst_events", "catalyst_type": ctype,
                             "materiality": weight, "count": int(n),
                             "id_range": [int(lo), int(hi)], "window_hours": NEW_HOURS},
            }
    stats["fired"] = len(by_symbol)
    return list(by_symbol.values()), stats


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
            "observed_at": str(latest),
            "universe_reason": "+".join((syms.get(sym) or {}).get("reasons", ["?"])),
            "precedence": (syms.get(sym) or {}).get("precedence", 10),
            "evidence": {"source": "news_articles", "articles": int(n),
                         "window_hours": NEW_HOURS, "baseline_days": BASELINE_DAYS},
        })
    return out, {"fired": len(out)}


def persist(cur, changes: list[dict], *, apply: bool) -> int:
    """Idempotent on change_guid. Returns rows actually written."""
    if not apply:
        return 0
    from scripts.lib.cio_narrative_subjects import build_links, resolve_subject
    from scripts.lib.cio_subject_guid import lookup_identity_envelope

    written = 0
    links_written = 0
    for c in changes:
        env = lookup_identity_envelope(c["symbol"])
        declared = c.get("subject")
        if declared:
            # A change that knows what it is about overrides the symbol lookup.
            # Falling back on a miss is deliberate: a sector we cannot resolve is
            # better recorded against its member than dropped, and the link rows
            # below still say SECTOR so the mis-stamp stays visible rather than
            # silently becoming truth.
            ref = resolve_subject(declared["entity_type"], declared["value"])
            if ref:
                env = dict(env)
                env["subject_guid"] = ref["entity_guid"]
                env["issuer_guid"] = None  # a sector has no issuer. §7: never invent one.
        cur.execute(
            """INSERT INTO material_changes
                 (change_guid, subject_guid, issuer_guid, symbol, kind, magnitude,
                  baseline, observed_value, observed_at, universe_reason, precedence,
                  evidence_json, schema_version, authority)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (change_guid) DO NOTHING""",
            (change_guid(c["symbol"], c["kind"], c["observed_at"]),
             env.get("subject_guid"), env.get("issuer_guid"), c["symbol"], c["kind"],
             c["magnitude"], c["baseline"], c["observed_value"], c["observed_at"],
             c["universe_reason"], c.get("precedence", 10),
             json.dumps(c["evidence"]), SCHEMA, AUTHORITY))
        written += cur.rowcount

        cg = change_guid(c["symbol"], c["kind"], c["observed_at"])
        subjects = []
        if declared:
            subjects.append({**declared, "relationship": "subject"})
        else:
            subjects.append({"entity_type": "SECURITY", "value": c["symbol"],
                             "relationship": "subject"})
        subjects += [{**m, "relationship": "mentioned"} for m in (c.get("mentions") or [])]
        links, _misses = build_links(row_guid=cg, source_table="material_changes",
                                     source_id=cg, subjects=subjects)
        for link in links:
            cur.execute(
                """INSERT INTO narrative_subjects
                     (link_guid, row_guid, source_table, source_id, entity_type,
                      subject_guid, semantic_subject, relationship, confidence,
                      author_agent_id, schema_version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (link_guid) DO NOTHING""",
                (link["link_guid"], link["row_guid"], link["source_table"],
                 link["source_id"], link["entity_type"], link["subject_guid"],
                 link["semantic_subject"], link["relationship"], link["confidence"],
                 link["author_agent_id"], link["schema_version"]))
            links_written += cur.rowcount
    if links_written:
        print(f"  narrative_subjects links written: {links_written}")
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--kind", choices=["price_excursion", "catalyst_new",
                                       "news_burst", "sector_move"])
    args = ap.parse_args()

    conn = _db()
    cur = conn.cursor()
    if args.apply:
        # ddl_guard: see scripts/lib/ddl_guard.py — this ran every 30 minutes and
        # collided with the notifier's UPDATE at :00 and :30.
        from scripts.lib.ddl_guard import apply_ddl
        apply_ddl(cur, DDL)
        conn.commit()

    syms = universe(cur)
    print(f"{SCHEMA} — apply={args.apply} K={K} universe={len(syms)} "
          f"(watchlist+preferred+reentry+held+operator)")

    changes: list[dict] = []
    stats: dict[str, dict] = {}
    contributors: list[dict] = []
    if args.kind in (None, "price_excursion"):
        c, s, contributors = price_excursions(cur, syms)
        changes += c; stats["price_excursion"] = s
    if args.kind in (None, "catalyst_new"):
        c, s = new_catalysts(cur, syms); changes += c; stats["catalyst_new"] = s
    if args.kind in (None, "sector_move") and contributors:
        c, s = sector_moves(cur, syms, contributors); changes += c; stats["sector_move"] = s
    if args.kind in (None, "news_burst"):
        c, s = news_bursts(cur, syms); changes += c; stats["news_burst"] = s

    changes.sort(key=lambda x: (-(x.get("precedence") or 0), -(x["magnitude"] or 0)))
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
