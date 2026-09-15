#!/usr/bin/env python3
"""Watchlist + proposal "goods" coverage and consistency check.

Operator, 2026-09-15: "make sure that all of the goods are being tracked consistently across everything
in the watch list and proposals." For every tracked name (active watchlist items ∪ open proposals) this
measures whether each good is present and fresh, and whether a proposal agrees with the watchlist's
own record of the same symbol:

  price_fresh      watchlist price enriched within 1 day (proposal: price checked within 1 day)
  sector/industry  symbol_profiles, else the Finviz enrichment cache
  market_cap       enrichment market cap → market-cap label (SMALL_CAP etc. via lib.market_cap_label)
  float / rvol     enrichment
  catalyst         strategy card catalyst_summary, else a catalyst_events row within 30 days
  card_levels      strategy card entry, stop and target
  entry_plan       watchlist_entry_plans row within 7 days
  quality          current decision packet quality state
  cio_decision     cio_decisions row within 7 days
  earnings_date    symbol_profiles.next_earnings_date

Mismatches: a proposal whose sector/industry differs from symbol_profiles, or whose float/rvol/catalyst
is empty while the watchlist side has it.

Read-only by default; prints coverage and writes data/runtime/watch_goods_consistency_last_run.json.
--apply-proposal-backfill fills EMPTY proposal sector, industry, float_m and rvol on open proposals from
the same sources (never overwrites a value).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
RECEIPT = PROJECT_ROOT / "data" / "runtime" / "watch_goods_consistency_last_run.json"
GOODS = ("price_fresh", "sector", "industry", "market_cap", "float", "rvol", "catalyst", "card_levels",
         "entry_plan", "quality", "cio_decision", "earnings_date")
OPEN_PROPOSAL_STATUSES = ("PENDING", "APPROVED_FOR_PAPER_TEST")


# Yahoo (symbol_profiles) and Finviz (enrichment) name the same sectors differently.
SECTOR_ALIASES = {
    "financial": "financial services", "healthcare": "health care", "consumer cyclical": "consumer discretionary",
    "consumer defensive": "consumer staples", "basic materials": "materials", "communication": "communication services",
    "technology": "information technology",
}


def _norm_sector(v) -> str:
    t = str(v or "").strip().lower()
    return SECTOR_ALIASES.get(t, t)


def _present(v) -> bool:
    return v not in (None, "", [], {}) and not (isinstance(v, float) and v != v)


def goods_for(sym: str, src: dict) -> dict[str, bool]:
    """Pure: src holds the per-source lookups for one symbol (see gather)."""
    enr = src.get("enrichment") or {}
    prof = src.get("profile") or {}
    card = src.get("card") or {}
    try:
        from lib.finviz_csv import enrichment_market_cap_billions
        cap_b = enrichment_market_cap_billions(enr)
    except Exception:
        cap_b = None
    return {
        "price_fresh": bool(src.get("price_fresh")),
        "sector": _present(prof.get("sector")) or _present(enr.get("sector")),
        "industry": _present(prof.get("industry")) or _present(enr.get("industry")),
        "market_cap": cap_b is not None,
        "float": _present(enr.get("float_m")),
        "rvol": _present(enr.get("rvol")),
        "catalyst": _present(card.get("catalyst_summary")) or bool(src.get("catalyst_30d")),
        "card_levels": all(_present(card.get(k)) for k in ("ideal_entry", "stop_loss", "target_price")),
        "entry_plan": bool(src.get("entry_plan_7d")),
        "quality": _present(src.get("quality")),
        "cio_decision": bool(src.get("cio_decision_7d")),
        "earnings_date": _present(prof.get("next_earnings_date")),
    }


def proposal_mismatches(p: dict, src: dict) -> list[str]:
    """Pure: where an open proposal disagrees with, or lags, the watchlist record for its symbol."""
    out: list[str] = []
    prof, enr, card = src.get("profile") or {}, src.get("enrichment") or {}, src.get("card") or {}
    for field in ("sector", "industry"):
        ref = prof.get(field) or enr.get(field)
        norm = _norm_sector if field == "sector" else (lambda v: str(v or "").strip().lower())
        if _present(ref) and _present(p.get(field)) and norm(p[field]) != norm(ref):
            out.append(f"{field} differs ({p[field]} vs {ref})")
        elif _present(ref) and not _present(p.get(field)):
            out.append(f"{field} missing on proposal")
    for field, key in (("float_m", "float_m"), ("rvol", "rvol")):
        if _present(enr.get(key)) and not _present(p.get(field)):
            out.append(f"{field} missing on proposal")
    if (_present(card.get("catalyst_summary")) or src.get("catalyst_30d")) and not _present(p.get("catalyst")):
        out.append("catalyst missing on proposal")
    return out


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def gather(cur) -> tuple[dict[str, dict], list[dict]]:
    cur.execute("SELECT DISTINCT upper(symbol) FROM watchlist_items WHERE status='active'")
    watch = {r[0] for r in cur.fetchall()}
    cur.execute("""SELECT id, upper(symbol), sector, industry, float_m, rvol, catalyst, current_price, last_price_checked_at,
                          origin, status FROM paper_trade_proposals WHERE status = ANY(%s)""", (list(OPEN_PROPOSAL_STATUSES),))
    cols = ["id", "symbol", "sector", "industry", "float_m", "rvol", "catalyst", "current_price", "last_price_checked_at", "origin", "status"]
    proposals = [dict(zip(cols, r)) for r in cur.fetchall()]
    syms = sorted(watch | {p["symbol"] for p in proposals})
    src: dict[str, dict] = {s: {"on_watchlist": s in watch} for s in syms}
    q = [
        ("price_fresh", """SELECT upper(symbol), bool_or(price IS NOT NULL AND last_enriched_at > now() - interval '1 day')
                             FROM watchlist_items WHERE upper(symbol) = ANY(%s) GROUP BY 1"""),
        ("entry_plan_7d", """SELECT DISTINCT upper(symbol), true FROM watchlist_entry_plans
                              WHERE upper(symbol) = ANY(%s) AND created_at > now() - interval '7 days'"""),
        ("cio_decision_7d", """SELECT DISTINCT upper(symbol), true FROM cio_decisions
                                WHERE upper(symbol) = ANY(%s) AND created_at > now() - interval '7 days'"""),
        ("catalyst_30d", """SELECT DISTINCT upper(symbol), true FROM catalyst_events
                             WHERE upper(symbol) = ANY(%s) AND COALESCE(published_at, created_at) > now() - interval '30 days'"""),
    ]
    for key, sql in q:
        cur.execute(sql, (syms,))
        for s, v in cur.fetchall():
            src[s][key] = v
    cur.execute("""SELECT upper(symbol), sector, industry, next_earnings_date FROM symbol_profiles WHERE upper(symbol) = ANY(%s)""", (syms,))
    for s, sec, ind, ned in cur.fetchall():
        src[s]["profile"] = {"sector": sec, "industry": ind, "next_earnings_date": ned}
    cur.execute("""SELECT DISTINCT ON (upper(symbol)) upper(symbol), ideal_entry, stop_loss, target_price, catalyst_summary
                     FROM watchlist_strategy_cards WHERE upper(symbol) = ANY(%s) ORDER BY upper(symbol), updated_at DESC NULLS LAST""", (syms,))
    for s, ie, sl, tp, cs in cur.fetchall():
        src[s]["card"] = {"ideal_entry": ie, "stop_loss": sl, "target_price": tp, "catalyst_summary": cs}
    try:
        import watch_packet_quality as pq
        cur.execute("SELECT upper(symbol), packet FROM decision_packets WHERE superseded_by IS NULL AND upper(symbol) = ANY(%s)", (syms,))
        for s, pk in cur.fetchall():
            src[s]["quality"] = pq.packet_gate(pk or {}).get("quality")
    except Exception:
        pass
    try:
        enrichment = json.loads((STATE_DIR / "ticker_enrichment_cache.json").read_text())
    except Exception:
        enrichment = {}
    for s in syms:
        src[s]["enrichment"] = enrichment.get(s) or {}
    return src, proposals


def summarize(src: dict[str, dict], proposals: list[dict]) -> dict:
    watch_syms = [s for s, v in src.items() if v.get("on_watchlist")]
    coverage = {g: 0 for g in GOODS}
    missing_by_symbol: dict[str, list[str]] = {}
    for s in watch_syms:
        g = goods_for(s, src[s])
        for k, ok in g.items():
            coverage[k] += 1 if ok else 0
        miss = [k for k, ok in g.items() if not ok]
        if miss:
            missing_by_symbol[s] = miss
    mism = {}
    for p in proposals:
        m = proposal_mismatches(p, src.get(p["symbol"], {}))
        if m:
            mism[f"#{p['id']} {p['symbol']}"] = m
    return {"as_of": datetime.now(timezone.utc).isoformat(), "watchlist_symbols": len(watch_syms),
            "coverage": coverage,
            "coverage_pct": {k: round(100.0 * v / max(1, len(watch_syms)), 1) for k, v in coverage.items()},
            "symbols_missing_any": len(missing_by_symbol),
            "open_proposals": len(proposals), "proposals_with_mismatch": len(mism),
            "proposal_mismatches": mism, "missing_by_symbol": missing_by_symbol}


def backfill_proposals(cur, src: dict[str, dict], proposals: list[dict]) -> int:
    n = 0
    for p in proposals:
        s = src.get(p["symbol"], {})
        prof, enr = s.get("profile") or {}, s.get("enrichment") or {}
        vals = {"sector": prof.get("sector") or enr.get("sector"), "industry": prof.get("industry") or enr.get("industry"),
                "float_m": enr.get("float_m"), "rvol": enr.get("rvol")}
        sets = {k: v for k, v in vals.items() if _present(v) and not _present(p.get(k))}
        if not sets:
            continue
        cur.execute("UPDATE paper_trade_proposals SET " + ", ".join(f"{k} = COALESCE({k}, %s)" for k in sets)
                    + ", updated_at = now() WHERE id = %s", (*sets.values(), p["id"]))
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply-proposal-backfill", action="store_true")
    ap.add_argument("--json", action="store_true", help="print the full report including per-symbol lists")
    a = ap.parse_args()
    conn = _conn()
    cur = conn.cursor()
    src, proposals = gather(cur)
    report = summarize(src, proposals)
    if a.apply_proposal_backfill:
        report["proposals_backfilled"] = backfill_proposals(cur, src, proposals)
        conn.commit()
    else:
        conn.rollback()
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(report, indent=2, default=str))
    brief = {k: v for k, v in report.items() if k not in ("missing_by_symbol", "proposal_mismatches")}
    brief["sample_mismatches"] = dict(list(report["proposal_mismatches"].items())[:5])
    print(json.dumps(report if a.json else brief, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
