#!/usr/bin/env python3
"""recommendation_intelligence_engine.py — unify every ticker that originated from an internal recommendation
source into a single, attributable, auditable lineage layer.

This does NOT duplicate the sources — it UNIFIES them. Each source already carries attribution; this engine
ingests them into `rec_ticker_attribution` (per ticker x source, with earliest/most-recent source + executed
flag), records rotation edges into `rec_rotation_links` (AAPL->NVDA->AVGO chains), and appends lifecycle
events to the existing immutable `lifecycle_events` spine. Read-only re: trading — no broker, no orders.

Sources ingested:
  watchlist_items, watch_directives (ticker), paper_trade_proposals, trade_ai_scans (GO/WAIT),
  rotation_pairs + rotation feedback, hermes_research_intelligence, cio_decisions,
  holdings.json (held positions), paper_trades (executions).

Usage:
  python3 scripts/recommendation_intelligence_engine.py [--dry-run] [--no-events]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
from db_adapter import _get_conn

DDL = """
CREATE TABLE IF NOT EXISTS rec_ticker_attribution (
  id            bigserial PRIMARY KEY,
  symbol        text NOT NULL,
  source_type   text NOT NULL,            -- watchlist|directive|proposal|scan|rotation|hermes_research|cio|holding|execution
  source_ref_table text,
  source_ref_id text,
  source_detail jsonb NOT NULL DEFAULT '{}',
  rationale     text,
  account       text,
  first_seen_at timestamptz NOT NULL,
  last_seen_at  timestamptz NOT NULL,
  occurrences   int NOT NULL DEFAULT 1,
  executed      boolean NOT NULL DEFAULT false,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (symbol, source_type, source_ref_table, source_ref_id)
);
CREATE INDEX IF NOT EXISTS idx_rta_symbol ON rec_ticker_attribution(symbol);
CREATE INDEX IF NOT EXISTS idx_rta_source ON rec_ticker_attribution(source_type);
CREATE INDEX IF NOT EXISTS idx_rta_executed ON rec_ticker_attribution(executed);

CREATE TABLE IF NOT EXISTS rec_rotation_links (
  id              bigserial PRIMARY KEY,
  account         text,
  from_symbol     text NOT NULL,
  to_symbol       text NOT NULL,
  rotation_pair_id bigint,
  source_type     text,                   -- rotation_idea|rotation_acted|execution
  executed        boolean NOT NULL DEFAULT false,
  rationale       text,
  occurred_at     timestamptz NOT NULL,
  metadata        jsonb NOT NULL DEFAULT '{}',
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (from_symbol, to_symbol, account, occurred_at)
);
CREATE INDEX IF NOT EXISTS idx_rrl_from ON rec_rotation_links(from_symbol);
CREATE INDEX IF NOT EXISTS idx_rrl_to ON rec_rotation_links(to_symbol);
"""

UPSERT = """
INSERT INTO rec_ticker_attribution
  (symbol, source_type, source_ref_table, source_ref_id, source_detail, rationale, account,
   first_seen_at, last_seen_at, occurrences, executed)
VALUES (%(symbol)s,%(source_type)s,%(source_ref_table)s,%(source_ref_id)s,%(detail)s,%(rationale)s,
        %(account)s,%(first_seen_at)s,%(last_seen_at)s,%(occurrences)s,%(executed)s)
ON CONFLICT (symbol, source_type, source_ref_table, source_ref_id) DO UPDATE SET
  last_seen_at = GREATEST(rec_ticker_attribution.last_seen_at, EXCLUDED.last_seen_at),
  first_seen_at = LEAST(rec_ticker_attribution.first_seen_at, EXCLUDED.first_seen_at),
  occurrences = EXCLUDED.occurrences,
  executed = rec_ticker_attribution.executed OR EXCLUDED.executed,
  source_detail = EXCLUDED.source_detail,
  rationale = COALESCE(EXCLUDED.rationale, rec_ticker_attribution.rationale),
  account = COALESCE(EXCLUDED.account, rec_ticker_attribution.account),
  updated_at = now();
"""

RE_TICKER = r"^[A-Z]{1,5}$"


def _rows(cur, sql, args=None):
    try:
        cur.execute(sql, args or ())
        return cur.fetchall()
    except Exception as e:
        cur.connection.rollback()
        print(f"  query skipped: {str(e)[:90]}")
        return []


def _upsert(cur, dry, **kw):
    # Skip rows that lack a timestamp (NOT NULL columns) — e.g. cancelled trades / cash rows.
    if not kw.get("first_seen_at") or not kw.get("last_seen_at"):
        return False
    kw.setdefault("source_ref_table", None)
    kw.setdefault("source_ref_id", None)
    kw.setdefault("rationale", None)
    kw.setdefault("account", None)
    kw.setdefault("occurrences", 1)
    kw.setdefault("executed", False)
    kw["detail"] = json.dumps(kw.pop("detail", {}) or {})
    if dry:
        return True
    cur.execute(UPSERT, kw)
    return True


def ingest(cur, dry):
    import re
    counts = {}

    def tag(src, n):
        counts[src] = counts.get(src, 0) + n
        if not dry:
            try:
                cur.connection.commit()  # commit each source independently (blast-radius isolation)
            except Exception:
                cur.connection.rollback()

    # 1) WATCHLIST — aggregate per symbol (earliest first_seen, latest last_seen, count)
    n = 0
    for sym, src, origin, rank, first, last, occ in _rows(cur, """
        SELECT upper(symbol), max(source) , max(origin_system), min(hermes_rank),
               min(first_seen_at), max(last_seen_at), count(*)
        FROM watchlist_items WHERE symbol ~ %s AND status <> 'removed'
        GROUP BY upper(symbol)""", (RE_TICKER,)):
        _upsert(cur, dry, symbol=sym, source_type="watchlist", source_ref_table="watchlist_items",
                source_ref_id=sym, first_seen_at=first, last_seen_at=last, occurrences=occ,
                detail={"source": src, "origin_system": origin, "hermes_rank": rank})
        n += 1
    tag("watchlist", n)

    # 2) DIRECTIVES (ticker kind)
    n = 0
    for did, label, spec, rationale, created, updated in _rows(cur, """
        SELECT id, label, spec, rationale, created_at, COALESCE(updated_at, created_at)
        FROM watch_directives WHERE kind='ticker' AND status <> 'archived'"""):
        sym = (spec or {}).get("symbol") if isinstance(spec, dict) else None
        sym = (sym or label or "").upper().strip()
        if not re.match(RE_TICKER, sym):
            continue
        _upsert(cur, dry, symbol=sym, source_type="directive", source_ref_table="watch_directives",
                source_ref_id=str(did), rationale=rationale, first_seen_at=created, last_seen_at=updated,
                detail={"label": label})
        n += 1
    tag("directive", n)

    # 3) PROPOSALS — one per proposal; executed if it produced a trade
    n = 0
    for pid, sym, strat, status, dsrc, pby, created, exec_at, otid, verdict, pnlpct in _rows(cur, """
        SELECT id, upper(symbol), strategy_id, status, discovery_source, proposed_by, created_at,
               executed_at, outcome_trade_id, outcome_verdict, outcome_pnl_pct
        FROM paper_trade_proposals WHERE symbol ~ %s""", (RE_TICKER,)):
        executed = bool(exec_at or otid)
        _upsert(cur, dry, symbol=sym, source_type="proposal", source_ref_table="paper_trade_proposals",
                source_ref_id=str(pid), first_seen_at=created, last_seen_at=(exec_at or created),
                executed=executed,
                detail={"strategy_id": strat, "status": status, "discovery_source": dsrc,
                        "proposed_by": pby, "outcome_verdict": verdict,
                        "outcome_pnl_pct": float(pnlpct) if pnlpct is not None else None,
                        "outcome_trade_id": otid})
        n += 1
    tag("proposal", n)

    # 4) SCANS — aggregate per symbol over GO/WAIT decisions
    n = 0
    for sym, dec, src, first, last, occ in _rows(cur, """
        SELECT upper(symbol), max(decision), max(source), min(scanned_at), max(scanned_at), count(*)
        FROM trade_ai_scans WHERE symbol ~ %s AND decision IN ('GO','WAIT')
        GROUP BY upper(symbol)""", (RE_TICKER,)):
        _upsert(cur, dry, symbol=sym, source_type="scan", source_ref_table="trade_ai_scans",
                source_ref_id=sym, first_seen_at=first, last_seen_at=last, occurrences=occ,
                detail={"decision": dec, "source": src})
        n += 1
    tag("scan", n)

    # 5) HERMES RESEARCH — aggregate per symbol
    n = 0
    for sym, rtype, agent, first, last, occ in _rows(cur, """
        SELECT upper(symbol), max(research_type), max(hermes_agent_name), min(created_at), max(created_at), count(*)
        FROM hermes_research_intelligence WHERE symbol ~ %s GROUP BY upper(symbol)""", (RE_TICKER,)):
        _upsert(cur, dry, symbol=sym, source_type="hermes_research", source_ref_table="hermes_research_intelligence",
                source_ref_id=sym, first_seen_at=first, last_seen_at=last, occurrences=occ,
                detail={"research_type": rtype, "agent": agent})
        n += 1
    tag("hermes_research", n)

    # 6) CIO DECISIONS — aggregate per symbol
    n = 0
    for sym, action, first, last, occ in _rows(cur, """
        SELECT upper(symbol), max(action), min(created_at), max(created_at), count(*)
        FROM cio_decisions WHERE symbol ~ %s GROUP BY upper(symbol)""", (RE_TICKER,)):
        _upsert(cur, dry, symbol=sym, source_type="cio", source_ref_table="cio_decisions",
                source_ref_id=sym, first_seen_at=first, last_seen_at=last, occurrences=occ,
                detail={"action": action})
        n += 1
    tag("cio", n)

    # 7) ROTATION pairs (if any persisted)
    n = 0
    for rid, ssym, dsym, sacc, dacc, score, rationale, status, created in _rows(cur, """
        SELECT id, upper(source_symbol), upper(destination_symbol), source_account, destination_account,
               rotation_score, rationale, status, created_at FROM rotation_pairs"""):
        for sym in (ssym, dsym):
            if sym and re.match(RE_TICKER, sym):
                _upsert(cur, dry, symbol=sym, source_type="rotation", source_ref_table="rotation_pairs",
                        source_ref_id=str(rid), rationale=rationale, first_seen_at=created, last_seen_at=created,
                        detail={"from": ssym, "to": dsym, "score": float(score) if score is not None else None,
                                "status": status})
        if ssym and dsym and not dry:
            cur.execute("""INSERT INTO rec_rotation_links (account, from_symbol, to_symbol, rotation_pair_id,
                             source_type, rationale, occurred_at, metadata)
                           VALUES (%s,%s,%s,%s,'rotation_idea',%s,%s,%s)
                           ON CONFLICT (from_symbol,to_symbol,account,occurred_at) DO NOTHING""",
                        (sacc or dacc, ssym, dsym, rid, rationale, created, json.dumps({"status": status})))
        n += 1
    tag("rotation_pairs", n)

    # 8) ROTATION feedback that was ACTED on (operator executed a from->to swap)
    n = 0
    for created, notes, meta in _rows(cur, """
        SELECT created_at, notes, metadata_json FROM llm_feedback_observations
        WHERE workflow='rotation_review' AND decision_action ILIKE '%%act%%'"""):
        frm = to = None
        if isinstance(meta, dict):
            frm = (meta.get("from_symbol") or "").upper() or None
            to = (meta.get("to_symbol") or "").upper() or None
        if (not frm or not to) and notes and "->" in notes:
            parts = notes.split("->")
            frm = frm or parts[0].strip().upper()
            to = to or parts[1].strip().upper()
        if frm and to and re.match(RE_TICKER, frm) and re.match(RE_TICKER, to) and not dry:
            cur.execute("""INSERT INTO rec_rotation_links (from_symbol, to_symbol, source_type, executed,
                             occurred_at, metadata) VALUES (%s,%s,'rotation_acted',true,%s,%s)
                           ON CONFLICT (from_symbol,to_symbol,account,occurred_at) DO NOTHING""",
                        (frm, to, created, json.dumps(meta if isinstance(meta, dict) else {})))
            n += 1
    tag("rotation_acted", n)

    # 9) HOLDINGS (currently held = executed positions)
    n = 0
    try:
        hj = json.loads((ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
        seen = {}  # (symbol, account) -> latest
        for h in hj.get("holdings", []):
            sym = (h.get("symbol") or "").upper()
            if not re.match(RE_TICKER, sym) or h.get("is_cash") or float(h.get("market_value") or 0) <= 0:
                continue
            acct = h.get("account")
            asof = h.get("as_of") or h.get("updated_at")
            _upsert(cur, dry, symbol=sym, source_type="holding", source_ref_table="holdings",
                    source_ref_id=f"{sym}:{acct}", account=acct, executed=True,
                    first_seen_at=asof, last_seen_at=asof,
                    detail={"shares": h.get("shares"), "market_value": h.get("market_value"),
                            "gain_loss_pct": h.get("gain_loss_pct")})
            n += 1
    except Exception as e:
        print("  holdings skipped:", str(e)[:90])
    tag("holding", n)

    # 10) EXECUTIONS (paper_trades) — flag executed + carry realized pnl
    n = 0
    for tid, sym, acct, status, pnl, pnlpct, entry, exit_t, pid in _rows(cur, """
        SELECT id, upper(symbol), account, status, pnl, pnl_pct, entry_time, exit_time, proposal_id
        FROM paper_trades WHERE symbol ~ %s""", (RE_TICKER,)):
        _upsert(cur, dry, symbol=sym, source_type="execution", source_ref_table="paper_trades",
                source_ref_id=str(tid), account=acct, executed=True,
                first_seen_at=entry, last_seen_at=(exit_t or entry),
                detail={"status": status, "pnl": float(pnl) if pnl is not None else None,
                        "pnl_pct": float(pnlpct) if pnlpct is not None else None, "proposal_id": pid})
        n += 1
    tag("execution", n)

    return counts


def analytics(cur):
    """Reporting metrics over the lineage layer — coverage, multi-source attribution, return-by-origin,
    return-after-execution, holding period, and rotation chains. Read-only."""
    a = {}
    cur.execute("""SELECT source_type, count(DISTINCT symbol), count(*) FILTER (WHERE executed)
                   FROM rec_ticker_attribution GROUP BY source_type ORDER BY 2 DESC""")
    a["by_source"] = [{"source": r[0], "tickers": r[1], "executed": r[2]} for r in cur.fetchall()]
    cur.execute("SELECT count(DISTINCT symbol), count(*) FILTER (WHERE executed) FROM rec_ticker_attribution")
    tot, execd = cur.fetchone()
    a["total_tickers"], a["executed_attributions"] = tot, execd
    cur.execute("SELECT count(*) FROM (SELECT symbol FROM rec_ticker_attribution GROUP BY symbol HAVING count(DISTINCT source_type)>1) x")
    a["multi_source_count"] = cur.fetchone()[0]
    cur.execute("""SELECT symbol, count(DISTINCT source_type) ns,
                     (array_agg(source_type ORDER BY first_seen_at))[1] earliest,
                     (array_agg(source_type ORDER BY last_seen_at DESC))[1] latest,
                     min(first_seen_at), max(last_seen_at), bool_or(executed)
                   FROM rec_ticker_attribution GROUP BY symbol HAVING count(DISTINCT source_type) > 1
                   ORDER BY ns DESC, max(last_seen_at) DESC LIMIT 40""")
    a["multi_source_examples"] = [{"symbol": r[0], "n_sources": r[1], "earliest_source": r[2],
                                   "latest_source": r[3], "first_seen": str(r[4]), "last_seen": str(r[5]),
                                   "executed": r[6]} for r in cur.fetchall()]
    # Return by ORIGIN source: executed closed trades grouped by the proposal's discovery_source.
    cur.execute("""
      SELECT COALESCE(NULLIF(p.discovery_source,''), CASE WHEN pt.proposal_id IS NULL THEN '(direct/manual)'
             ELSE '(proposal/other)' END) src,
             count(*) trades, count(*) FILTER (WHERE pt.pnl>0) wins,
             round(avg(pt.pnl_pct)::numeric,2) avg_pnl_pct, round(sum(pt.pnl)::numeric,0) total_pnl,
             round(avg(EXTRACT(EPOCH FROM (pt.exit_time-pt.entry_time))/86400.0)::numeric,1) avg_hold_days
      FROM paper_trades pt LEFT JOIN paper_trade_proposals p ON pt.proposal_id=p.id
      WHERE pt.status='closed' AND pt.pnl IS NOT NULL
      GROUP BY 1 ORDER BY trades DESC""")
    a["performance_by_source"] = [{"source": r[0], "closed_trades": r[1], "wins": r[2],
        "win_rate_pct": round(r[2] / r[1] * 100, 1) if r[1] else None,
        "avg_return_pct": float(r[3]) if r[3] is not None else None,
        "total_pnl": float(r[4]) if r[4] is not None else None,
        "avg_hold_days": float(r[5]) if r[5] is not None else None} for r in cur.fetchall()]
    # Strategy-level outcomes from proposals that resolved.
    cur.execute("""SELECT strategy_id, count(*) FILTER (WHERE outcome_verdict IS NOT NULL) resolved,
                     count(*) FILTER (WHERE outcome_verdict='WIN') wins,
                     round(avg(outcome_pnl_pct)::numeric,2) FROM paper_trade_proposals
                   WHERE strategy_id IS NOT NULL GROUP BY strategy_id HAVING count(*) FILTER (WHERE outcome_verdict IS NOT NULL)>0
                   ORDER BY 2 DESC LIMIT 15""")
    a["performance_by_strategy"] = [{"strategy": r[0], "resolved": r[1], "wins": r[2],
        "win_rate_pct": round(r[2] / r[1] * 100, 1) if r[1] else None,
        "avg_return_pct": float(r[3]) if r[3] is not None else None} for r in cur.fetchall()]
    cur.execute("SELECT from_symbol, to_symbol, executed, occurred_at, source_type FROM rec_rotation_links ORDER BY occurred_at DESC LIMIT 100")
    a["rotation_links"] = [{"from": r[0], "to": r[1], "executed": r[2], "at": str(r[3]), "via": r[4]} for r in cur.fetchall()]
    a["rotation_link_count"] = len(a["rotation_links"])
    return a


def main():
    if "--analytics" in sys.argv:
        print(json.dumps(analytics(_get_conn().cursor()), indent=2, default=str))
        return 0
    dry = "--dry-run" in sys.argv
    conn = _get_conn()
    cur = conn.cursor()
    if not dry:
        cur.execute(DDL)
        conn.commit()
    counts = ingest(cur, dry)
    if not dry:
        conn.commit()
        cur.execute("SELECT count(DISTINCT symbol), count(*) , count(*) FILTER (WHERE executed) FROM rec_ticker_attribution")
        usyms, total, execd = cur.fetchone()
        cur.execute("SELECT count(*) FROM rec_rotation_links")
        rlinks = cur.fetchone()[0]
    else:
        usyms = total = execd = rlinks = "(dry-run)"
    out = {"ok": True, "dry_run": dry, "ingested_by_source": counts,
           "distinct_symbols": usyms, "attribution_rows": total, "executed_rows": execd,
           "rotation_links": rlinks}
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
