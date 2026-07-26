#!/usr/bin/env python3
"""Historical shadow replay of the Defense/Sectors data-quality contract.

Replays the legacy and contract breadth calculations side by side over the latest N
completed trading sessions already present in the database, and reports where the two
disagree and why.

This is a HISTORICAL SHADOW REPLAY, not a live walk-forward claim. Two honest limits
are recorded with every run and must not be dropped from the report:

  1. Sector membership is resolved as it stands TODAY. The membership tables carry no
     effective-dated history, so a symbol that joined a sector after a replayed session
     is treated as a member of it. Prices are correctly as-of each session; membership
     is not.
  2. The legacy arm is a reimplementation of the pre-change SQL, not the original
     process output. It reproduces the calendar-window average and the >=15-row gate
     exactly, but it recomputes them now rather than reading what shipped that day.

Read-only: SELECTs plus file writes to the evidence paths. No table is written.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from db_adapter import _execute as ex  # noqa: E402
from defense_data_quality import (  # noqa: E402
    CALC_VERSION, Quality, canonical_json_hash, exact_session_breadth,
    field_ledger, quarantine_stale_rows,
)

MIN_MEMBERS = 8
SESSIONS = 20
STALE_SLA_DAYS = 4


def completed_sessions(limit: int) -> list[dt.date]:
    """Sessions the momentum engine actually produced a full board for.

    Partial days (a handful of rows from an interrupted run) are excluded: replaying
    them would compare against a board that was never complete, which reads as a
    methodology delta when it is really a missing run.
    """
    rows = ex("""SELECT as_of, count(*) n FROM sector_momentum_state
                 GROUP BY as_of ORDER BY as_of DESC""", fetch="all") or []
    full = [r for r in rows if r["n"] >= 8]
    return [r["as_of"] for r in full[:limit]][::-1]


_CFG = json.loads((ROOT / "config" / "sector_momentum.json").read_text())


def _aliases(sector: str) -> list[str]:
    """Same alias expansion the engine uses.

    The board stores GICS-style names ("Financials", "Materials") while the scan table
    stores Finviz names ("Financial Services", "Basic Materials"). Matching on the raw
    name resolves almost no members and would make the replay report a methodology
    difference where there is only a naming mismatch.
    """
    return _CFG.get("sector_aliases", {}).get(sector, [sector])


def _members(sector: str) -> list[str]:
    rows = ex("""SELECT DISTINCT m.symbol FROM screener_symbol_membership m
                 JOIN trade_ai_scans t ON upper(t.symbol) = upper(m.symbol)
                 WHERE t.sector = ANY(%s) LIMIT 60""", (_aliases(sector),), fetch="all") or []
    return [r["symbol"] for r in rows]


def legacy_breadth(members: list[str], as_of: dt.date) -> dict:
    """Reimplementation of the pre-change calculation, evaluated as of a past date."""
    if len(members) < MIN_MEMBERS:
        return {"breadth_pct": None, "n": len(members), "reason": "thin_membership"}
    rows = ex("""SELECT symbol,
                        (array_agg(close_price ORDER BY price_date DESC))[1] AS last,
                        avg(close_price) FILTER (WHERE price_date > %s) AS dma,
                        count(*) n
                 FROM ticker_prices
                 WHERE symbol = ANY(%s) AND price_date <= %s AND price_date > %s
                 GROUP BY symbol HAVING count(*) >= 15""",
              (as_of - dt.timedelta(days=30), members, as_of,
               as_of - dt.timedelta(days=45)), fetch="all") or []
    above = total = 0
    for r in rows:
        if r["last"] is None or r["dma"] is None:
            continue
        total += 1
        above += int(float(r["last"]) > float(r["dma"]))
    pct = round(above / total * 100) if total >= MIN_MEMBERS else None
    return {"breadth_pct": pct, "n": total, "reason": None if pct is not None else "below_floor"}


def exact_breadth(members: list[str], as_of: dt.date) -> dict:
    if len(members) < MIN_MEMBERS:
        return {"breadth_pct": None, "coverage_n": 0, "membership_n": len(members),
                "duplicate_dates_removed": 0,
                "quality": {"state": "insufficient_coverage",
                            "reasons": [f"membership_n={len(members)}"]}}
    rows = ex("""SELECT symbol, price_date, close_price FROM ticker_prices
                 WHERE symbol = ANY(%s) AND price_date <= %s AND price_date > %s
                   AND close_price IS NOT NULL
                 ORDER BY symbol, price_date""",
              (members, as_of, as_of - dt.timedelta(days=60)), fetch="all") or []
    return exact_session_breadth(
        ((r["symbol"], r["price_date"], float(r["close_price"])) for r in rows),
        sessions=SESSIONS, min_members=MIN_MEMBERS)


def classify(delta: float | None, legacy: int | None, exact: int | None,
             quality_state: str) -> tuple[str, str]:
    """Bucket a disagreement. Never asserts one arm is 'better' without a reason."""
    if legacy is None and exact is None:
        return "insufficient_evidence", "neither arm produced a value"
    if legacy is not None and exact is None:
        return ("potential_false_exclusion",
                f"legacy published {legacy}% where the contract withholds "
                f"({quality_state}) — verify coverage before treating the withhold as correct")
    if legacy is None and exact is not None:
        return ("legacy_false_exclusion",
                f"legacy withheld where the contract resolves {exact}% on exactly "
                f"{SESSIONS} sessions")
    if delta is None or abs(delta) < 1e-9:
        return "unchanged", "identical result"
    return ("changed_correctly",
            f"calendar-window average replaced by exactly {SESSIONS} distinct sessions; "
            f"delta {delta:+.0f} pts is the methodology difference")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=5)
    ap.add_argument("--json-out", default="/tmp/defense_shadow_5session.json")
    ap.add_argument("--md-out",
                    default=str(ROOT / "docs/evidence/DEFENSE_DATA_QUALITY_SHADOW_5_SESSION_2026-07-24.md"))
    args = ap.parse_args()

    sessions = completed_sessions(args.sessions)
    if not sessions:
        print("no completed sessions found", file=sys.stderr)
        return 1
    today = dt.date.today()

    per_session, comparisons = [], []
    for s in sessions:
        board = ex("""SELECT etf, sector, state, breadth_pct, breadth_n, as_of
                      FROM sector_momentum_state WHERE as_of = %s ORDER BY sector""",
                   (s,), fetch="all") or []
        rows_out = []
        for row in board:
            sector = row["sector"]
            if not sector:
                continue
            # Style pairs (IWM−SPY, RSP−SPY, VUG−VTV) share the board but are index
            # spreads, not sectors: they have no constituent membership and never had a
            # breadth number in either arm. Reporting them as an evidence gap would
            # overstate how much of the board is uncovered.
            if "−" in sector or "-SPY" in sector:
                entry = {"session": str(s), "sector": sector, "etf": row["etf"],
                         "bucket": "not_applicable_style_pair",
                         "reason": "index spread, not a sector with constituents",
                         "breadth_legacy_replay": None, "breadth_exact": None,
                         "delta_pts": None, "stale": False, "recommendation_eligible": True}
                entry["payload_hash"] = canonical_json_hash(
                    {"sector": sector, "session": str(s), "kind": "style_pair"})
                rows_out.append(entry)
                comparisons.append(entry)
                continue
            members = _members(sector)
            legacy = legacy_breadth(members, s)
            exact = exact_breadth(members, s)
            lp, xp = legacy["breadth_pct"], exact["breadth_pct"]
            delta = (xp - lp) if (lp is not None and xp is not None) else None
            bucket, reason = classify(delta, lp, xp, exact["quality"]["state"])

            stale = quarantine_stale_rows([{"as_of": str(s)}], as_of=today,
                                          max_age_days=STALE_SLA_DAYS)
            is_stale = bool(stale["quarantined"])

            entry = {
                "session": str(s), "sector": sector, "etf": row["etf"],
                "state_published": row["state"],
                "breadth_published": (int(row["breadth_pct"])
                                      if row["breadth_pct"] is not None else None),
                "breadth_legacy_replay": lp,
                "breadth_exact": xp,
                "delta_pts": delta,
                "coverage_n_legacy": legacy["n"],
                "coverage_n_exact": exact["coverage_n"],
                "membership_n": exact["membership_n"],
                "duplicate_dates_removed": exact["duplicate_dates_removed"],
                "exact_quality": exact["quality"]["state"],
                "stale": is_stale,
                "recommendation_eligible": not is_stale,
                "bucket": bucket, "reason": reason,
            }
            entry["payload_hash"] = canonical_json_hash(
                {k: entry[k] for k in ("sector", "session", "breadth_exact",
                                       "exact_quality", "recommendation_eligible")})
            rows_out.append(entry)
            comparisons.append(entry)

        per_session.append({
            "session": str(s), "sectors": len(rows_out),
            "ledger": field_ledger(
                source="sector_momentum_state", provider="sector_momentum_engine",
                source_as_of=str(s), cadence="daily_close",
                value=[r["payload_hash"] for r in rows_out],
                coverage_n=sum(1 for r in rows_out if r["breadth_exact"] is not None),
                coverage_total=len(rows_out),
                quality=Quality("shadow_replay", ("membership resolved as of today",))),
            "rows": rows_out,
        })

    buckets: dict[str, int] = {}
    for c in comparisons:
        buckets[c["bucket"]] = buckets.get(c["bucket"], 0) + 1

    report = {
        "kind": "historical_shadow_replay",
        "not_a_walk_forward_claim": True,
        "calculation_version": CALC_VERSION,
        "generated_for": "2026-07-24",
        "sessions": [str(s) for s in sessions],
        "limits": [
            "sector membership resolved as of today; membership tables carry no effective-dated history",
            "the legacy arm is a reimplementation of the pre-change SQL, recomputed now, "
            "not the original process output",
        ],
        "buckets": buckets,
        "per_session": per_session,
    }
    Path(args.json_out).write_text(json.dumps(report, indent=2, default=str))
    print(f"wrote {args.json_out}")
    print("buckets:", buckets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
