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

-- Phase 2: rotation-outcome measurement (did rotating beat holding the original?)
ALTER TABLE rec_rotation_links ADD COLUMN IF NOT EXISTS from_return_pct numeric;
ALTER TABLE rec_rotation_links ADD COLUMN IF NOT EXISTS to_return_pct numeric;
ALTER TABLE rec_rotation_links ADD COLUMN IF NOT EXISTS rotation_alpha_pct numeric;  -- to_return - from_return
ALTER TABLE rec_rotation_links ADD COLUMN IF NOT EXISTS outcome_measured_at timestamptz;

-- Phase 3: per-source learning — realized quality of each ORIGIN source -> a bounded ranking multiplier.
CREATE TABLE IF NOT EXISTS rec_source_quality (
  id            bigserial PRIMARY KEY,
  source_key    text NOT NULL,            -- discovery_source / origin grouping (e.g. screener, incubator)
  sample_size   int NOT NULL,
  wins          int NOT NULL,
  win_rate      numeric,
  avg_return_pct numeric,
  total_pnl     numeric,
  expectancy_pct numeric,
  quality_multiplier numeric NOT NULL,     -- bounded 0.50-1.50; 1.0 until min sample
  basis         text,
  computed_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rsq_key ON rec_source_quality(source_key, computed_at DESC);
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

    # 11) REAL-BROKER EXECUTIONS (trade_transactions) — manual/synced BUYs in real accounts (Schwab,
    #     Fidelity-via-SnapTrade/manual) that NEVER pass through paper_trades. This is what auto-tags an
    #     operator's manual buy of a watchlist/rotation pick as EXECUTED — the rec→execution link that
    #     previously had to be hand-stamped (GCTS 2026-06-18, XAR 2026-06-19). The per-symbol watchlist/
    #     directive/rotation rows (steps 1-8) already carry the ORIGIN; this flips executed=true and joins
    #     the realized buy. Idempotent on (symbol,'execution','trade_transactions', txn id).
    n = 0
    for txid, sym, acct, action, qty, price, amount, src, ts in _rows(cur, """
        SELECT id, upper(symbol), account, action, quantity, price, amount, import_source,
               COALESCE(trade_time, trade_date::timestamptz)
        FROM trade_transactions
        WHERE upper(action) IN ('BUY','BOUGHT','REINVESTMENT') AND symbol ~ %s
          AND COALESCE(trade_time, trade_date::timestamptz) IS NOT NULL""", (RE_TICKER,)):
        _upsert(cur, dry, symbol=sym, source_type="execution", source_ref_table="trade_transactions",
                source_ref_id=str(txid), account=acct, executed=True,
                first_seen_at=ts, last_seen_at=ts,
                detail={"action": action, "quantity": float(qty) if qty is not None else None,
                        "price": float(price) if price is not None else None,
                        "amount": float(amount) if amount is not None else None,
                        "import_source": src, "venue": "real_broker"})
        n += 1
    tag("real_execution", n)

    # 12) DERIVED ROTATION EXECUTIONS — AUTO-link a real buy to its ROTATION origin (no hand-stamping;
    #     replaces the manual XAR/GCTS tags, operator 2026-06-19 "this linkage should be automatic").
    #     A real buy is a rotation execution when the symbol carries a rotation-origin signal:
    #       • a ticker directive whose rationale flags rotation/rotate-in/rebalance/sleeve, OR
    #       • a sector_rotation proposal, OR
    #       • an existing rec_rotation_links.to_symbol edge.
    #     Discriminates correctly: a plain watchlist/scan buy (e.g. HPE, empty-rationale directive) is NOT
    #     tagged rotation. Idempotent on (symbol,'rotation','trade_transactions', txn id).
    n = 0
    for txid, sym, acct, ts, why in _rows(cur, """
        SELECT tt.id, upper(tt.symbol), tt.account,
               COALESCE(tt.trade_time, tt.trade_date::timestamptz),
               COALESCE(
                 (SELECT 'directive: '||left(d.rationale,90) FROM watch_directives d
                    WHERE d.kind='ticker'
                      AND upper(COALESCE(NULLIF(d.spec->>'symbol',''), d.label))=upper(tt.symbol)
                      AND d.rationale ~* 'rotat|rotate-in|rebalance|sleeve' LIMIT 1),
                 (SELECT 'proposal: '||p.strategy_id FROM paper_trade_proposals p
                    WHERE upper(p.symbol)=upper(tt.symbol) AND p.strategy_id ~* 'rotation' LIMIT 1),
                 (SELECT 'rotation_link' FROM rec_rotation_links r WHERE upper(r.to_symbol)=upper(tt.symbol) LIMIT 1)
               )
        FROM trade_transactions tt
        WHERE upper(tt.action) IN ('BUY','BOUGHT') AND tt.symbol ~ %s
          AND COALESCE(tt.trade_time, tt.trade_date::timestamptz) IS NOT NULL""", (RE_TICKER,)):
        if not why:
            continue
        _upsert(cur, dry, symbol=sym, source_type="rotation", source_ref_table="trade_transactions",
                source_ref_id=str(txid), account=acct, executed=True,
                first_seen_at=ts, last_seen_at=ts,
                rationale=f"Auto-derived rotation execution ({why}).",
                detail={"derived": True, "signal": why, "venue": "real_broker"})
        n += 1
    tag("rotation_derived", n)

    return counts


def emit_lifecycle_events(cur):
    """Phase 2: append immutable lineage events to the existing lifecycle_events spine — one per meaningful
    transition (promoted to proposal / executed / rotated). Idempotent via NOT EXISTS on (symbol, event_type,
    source_table='rec_intel', source_pk). Bulk INSERT...SELECT — fast + auditable. Returns counts."""
    out = {}
    # promoted_to_proposal — one per proposal
    cur.execute("""
      INSERT INTO lifecycle_events (lifecycle_id, event_ts, stage, event_type, status, symbol, strategy_id,
                                    proposal_id, source_script, source_table, source_pk, payload)
      SELECT 'lc-rec-'||p.id, p.created_at, 'lineage', 'rec_promoted_to_proposal', p.status, upper(p.symbol),
             p.strategy_id, p.id, 'recommendation_intelligence_engine', 'rec_intel', p.id::text,
             jsonb_build_object('discovery_source', p.discovery_source, 'proposed_by', p.proposed_by)
      FROM paper_trade_proposals p
      WHERE p.symbol ~ '^[A-Z]{1,5}$' AND NOT EXISTS (
        SELECT 1 FROM lifecycle_events e WHERE e.source_table='rec_intel'
          AND e.event_type='rec_promoted_to_proposal' AND e.source_pk=p.id::text)""")
    out["promoted"] = cur.rowcount
    # executed — one per paper_trade
    cur.execute("""
      INSERT INTO lifecycle_events (lifecycle_id, event_ts, stage, event_type, status, symbol, strategy_id,
                                    proposal_id, paper_trade_id, source_script, source_table, source_pk, payload)
      SELECT 'lc-rec-t'||t.id, t.entry_time, 'lineage', 'rec_executed', t.status, upper(t.symbol),
             t.strategy_id, t.proposal_id, t.id, 'recommendation_intelligence_engine', 'rec_intel', 't'||t.id,
             jsonb_build_object('account', t.account, 'pnl', t.pnl, 'pnl_pct', t.pnl_pct)
      FROM paper_trades t
      WHERE t.symbol ~ '^[A-Z]{1,5}$' AND t.entry_time IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM lifecycle_events e WHERE e.source_table='rec_intel'
          AND e.event_type='rec_executed' AND e.source_pk='t'||t.id)""")
    out["executed"] = cur.rowcount
    # rotated — one per rotation link
    cur.execute("""
      INSERT INTO lifecycle_events (lifecycle_id, event_ts, stage, event_type, status, symbol,
                                    source_script, source_table, source_pk, payload)
      SELECT 'lc-rec-r'||r.id, r.occurred_at, 'lineage', 'rec_rotated',
             CASE WHEN r.executed THEN 'executed' ELSE 'advisory' END, r.from_symbol,
             'recommendation_intelligence_engine', 'rec_intel', 'r'||r.id,
             jsonb_build_object('from', r.from_symbol, 'to', r.to_symbol, 'executed', r.executed)
      FROM rec_rotation_links r WHERE NOT EXISTS (
        SELECT 1 FROM lifecycle_events e WHERE e.source_table='rec_intel'
          AND e.event_type='rec_rotated' AND e.source_pk='r'||r.id)""")
    out["rotated"] = cur.rowcount
    cur.connection.commit()
    return out


def detect_rotation_pairs(cur):
    """Phase 2 data: infer rotation edges from the executed trade history — closing position X and opening a
    DIFFERENT position Y in the SAME account shortly after is a rotation (sell X, buy Y). For each close we
    take the single NEAREST qualifying open within the window (1:1, no combinatorial blow-up) and record an
    `executed_pair` edge into rec_rotation_links. Idempotent via the UNIQUE(from,to,account,occurred_at)."""
    cur.execute("""SELECT id, upper(symbol), account, exit_time, exit_price, dollar_size
                   FROM paper_trades WHERE status='closed' AND exit_time IS NOT NULL AND symbol ~ '^[A-Z]{1,5}$'""")
    closes = cur.fetchall()
    cur.execute("""SELECT id, upper(symbol), account, entry_time, entry_price, dollar_size
                   FROM paper_trades WHERE entry_time IS NOT NULL AND symbol ~ '^[A-Z]{1,5}$'""")
    opens = cur.fetchall()
    n = 0
    seen = set()  # dedup one edge per (from, to, account, day)
    for cid, csym, cacct, cexit, cpx, csize in sorted(closes, key=lambda r: r[3]):
        best = None
        for oid, osym, oacct, oentry, opx, osize in opens:
            if oid == cid or oacct != cacct or osym == csym or oentry is None:
                continue
            gap = (oentry - cexit).total_seconds() / 86400.0
            # the open must be AT or AFTER the close (sell X, then buy Y), within 3 days; nearest wins.
            if -0.1 <= gap <= 3.0 and (best is None or gap < best[0]):
                best = (gap, oid, osym, opx)
        if best:
            gap, oid, osym, opx = best
            key = (csym, osym, cacct, str(cexit)[:10])
            if key in seen:
                continue
            seen.add(key)
            cur.execute("""INSERT INTO rec_rotation_links (account, from_symbol, to_symbol, source_type,
                             executed, rationale, occurred_at, metadata)
                           VALUES (%s,%s,%s,'executed_pair',true,%s,%s,%s)
                           ON CONFLICT (from_symbol,to_symbol,account,occurred_at) DO NOTHING""",
                        (cacct, csym, osym, f"closed {csym} then opened {osym} in {cacct} ({gap:+.1f}d)",
                         cexit, json.dumps({"from_trade_id": cid, "to_trade_id": oid, "days_gap": round(gap, 2),
                                            "from_exit_price": float(cpx) if cpx is not None else None,
                                            "to_entry_price": float(opx) if opx is not None else None})))
            n += cur.rowcount
    cur.connection.commit()
    return n


def _price_on_or_before(cur, symbol, when):
    """Latest cached close at/before `when` (price_cache.json history is per-day). Returns float or None."""
    try:
        import json as _j
        pc = _j.loads((ROOT / "data" / "portfolios" / "state" / "price_cache.json").read_text())
        hist = pc.get(symbol.upper())
        if not isinstance(hist, dict):
            return None
        day = str(when)[:10]
        keys = sorted(k for k in hist if k <= day)
        return float(hist[keys[-1]]) if keys else None
    except Exception:
        return None


def measure_rotations(cur):
    """Phase 2: for each executed rotation edge, measure from_return vs to_return since the rotation, so we
    can tell whether rotating beat holding the original. Uses cached prices. Returns count measured."""
    n = 0
    cur.execute("SELECT id, from_symbol, to_symbol, occurred_at, metadata FROM rec_rotation_links WHERE executed=true")
    for rid, frm, to, when, meta in cur.fetchall():
        meta = meta if isinstance(meta, dict) else {}
        # Prefer the ACTUAL trade prices at the rotation (from edge metadata); fall back to cached history.
        fp0 = meta.get("from_exit_price") or _price_on_or_before(cur, frm, when)
        tp0 = meta.get("to_entry_price") or _price_on_or_before(cur, to, when)
        latest = {}
        cur.execute("""SELECT DISTINCT ON (symbol) symbol, price FROM market_quotes
                       WHERE symbol = ANY(%s) ORDER BY symbol, fetched_at DESC""", ([frm, to],))
        for s, p in cur.fetchall():
            latest[s.upper()] = float(p) if p is not None else None
        # current price fallback: latest cached close
        fp1 = latest.get(frm.upper()) or _price_on_or_before(cur, frm, "9999-12-31")
        tp1 = latest.get(to.upper()) or _price_on_or_before(cur, to, "9999-12-31")
        if fp0 and fp1 and tp0 and tp1:
            fr = round((fp1 - fp0) / fp0 * 100, 2)
            tr = round((tp1 - tp0) / tp0 * 100, 2)
            cur.execute("""UPDATE rec_rotation_links SET from_return_pct=%s, to_return_pct=%s,
                             rotation_alpha_pct=%s, outcome_measured_at=now() WHERE id=%s""",
                        (fr, tr, round(tr - fr, 2), rid))
            n += 1
    cur.connection.commit()
    return n


def compute_source_quality(cur):
    """Phase 3 (learning): turn each ORIGIN source's REALIZED outcomes into a bounded ranking multiplier
    (0.50-1.50; 1.0 until a minimum sample). Append-only history in rec_source_quality. Advisory — consumers
    opt in via get_source_quality(). Returns the latest multipliers."""
    MIN_SAMPLE = 5
    cur.execute("""
      SELECT COALESCE(NULLIF(p.discovery_source,''), CASE WHEN pt.proposal_id IS NULL THEN '(direct/manual)'
             ELSE '(proposal/other)' END) src,
             count(*) n, count(*) FILTER (WHERE pt.pnl>0) wins,
             avg(pt.pnl_pct) avg_ret, sum(pt.pnl) total_pnl
      FROM paper_trades pt LEFT JOIN paper_trade_proposals p ON pt.proposal_id=p.id
      WHERE pt.status='closed' AND pt.pnl IS NOT NULL GROUP BY 1""")
    rows = cur.fetchall()
    latest = []
    for src, n, wins, avg_ret, total_pnl in rows:
        wr = (wins / n) if n else 0.0
        ar = float(avg_ret) if avg_ret is not None else 0.0
        expectancy = ar  # avg return per trade is the expectancy proxy
        if n < MIN_SAMPLE:
            mult, basis = 1.0, f"neutral (sample {n} < {MIN_SAMPLE})"
        else:
            # bounded blend of win-rate edge and avg return; clamp 0.5-1.5
            raw = 1.0 + 0.8 * (wr - 0.5) + 0.03 * ar
            mult = round(max(0.5, min(1.5, raw)), 3)
            basis = f"win {round(wr*100,1)}% + avg {round(ar,2)}% over {n} trades"
        cur.execute("""INSERT INTO rec_source_quality
            (source_key, sample_size, wins, win_rate, avg_return_pct, total_pnl, expectancy_pct,
             quality_multiplier, basis) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (src, n, wins, round(wr, 4), round(ar, 2),
                     float(total_pnl) if total_pnl is not None else None, round(expectancy, 2), mult, basis))
        latest.append({"source": src, "sample": n, "win_rate_pct": round(wr * 100, 1),
                       "avg_return_pct": round(ar, 2), "quality_multiplier": mult, "basis": basis})
    cur.connection.commit()
    latest.sort(key=lambda x: -x["quality_multiplier"])
    # Integration contract: write the latest multipliers to a file any ranking/proposal layer can read.
    try:
        f = ROOT / "data" / "runtime" / "rec_source_quality_latest.json"
        f.write_text(json.dumps({"multipliers": {x["source"]: x["quality_multiplier"] for x in latest},
                                 "detail": latest}, indent=2))
    except Exception:
        pass
    return latest


def get_source_quality(source_key):
    """Advisory helper for ranking/proposal consumers: latest learned quality multiplier for a source
    (defaults to 1.0 / neutral if unknown). Bounded 0.5-1.5. Read-only."""
    try:
        cur = _get_conn().cursor()
        cur.execute("""SELECT quality_multiplier FROM rec_source_quality WHERE source_key=%s
                       ORDER BY computed_at DESC LIMIT 1""", (source_key,))
        r = cur.fetchone()
        return float(r[0]) if r else 1.0
    except Exception:
        return 1.0


def build_chains(cur):
    """Phase 2: assemble multi-hop rotation chains (A->B->C) from rec_rotation_links edges."""
    cur.execute("SELECT from_symbol, to_symbol, occurred_at FROM rec_rotation_links ORDER BY occurred_at")
    edges = cur.fetchall()
    nxt = {}
    for f, t, _ in edges:
        nxt.setdefault(f, []).append(t)
    starts = {f for f, _, _ in edges} - {t for _, t, _ in edges}
    chains = []
    for s in sorted(starts):
        chain, cur_sym = [s], s
        while cur_sym in nxt:
            nextsym = nxt[cur_sym][0]
            if nextsym in chain:  # cycle guard — stop on revisit (GCTS<->INFU ping-pong)
                break
            chain.append(nextsym)
            cur_sym = nextsym
        if len(chain) > 1:
            chains.append(chain)
    chains.sort(key=len, reverse=True)
    return chains[:20]


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
    cur.execute("""SELECT from_symbol, to_symbol, executed, occurred_at, source_type,
                          from_return_pct, to_return_pct, rotation_alpha_pct
                   FROM rec_rotation_links ORDER BY occurred_at DESC LIMIT 100""")
    a["rotation_links"] = [{"from": r[0], "to": r[1], "executed": r[2], "at": str(r[3]), "via": r[4],
                            "from_return_pct": float(r[5]) if r[5] is not None else None,
                            "to_return_pct": float(r[6]) if r[6] is not None else None,
                            "rotation_alpha_pct": float(r[7]) if r[7] is not None else None} for r in cur.fetchall()]
    a["rotation_link_count"] = len(a["rotation_links"])
    a["rotation_chains"] = build_chains(cur)
    # Phase 3: latest learned source-quality multipliers (one per source)
    cur.execute("""SELECT DISTINCT ON (source_key) source_key, sample_size, win_rate, avg_return_pct,
                     quality_multiplier, basis, computed_at
                   FROM rec_source_quality ORDER BY source_key, computed_at DESC""")
    a["source_quality"] = sorted([{"source": r[0], "sample": r[1],
        "win_rate_pct": round(float(r[2]) * 100, 1) if r[2] is not None else None,
        "avg_return_pct": float(r[3]) if r[3] is not None else None,
        "quality_multiplier": float(r[4]), "basis": r[5], "computed_at": str(r[6])}
        for r in cur.fetchall()], key=lambda x: -x["quality_multiplier"])
    # rotation outcome summary: did executed rotations beat holding the original?
    cur.execute("""SELECT count(*), avg(rotation_alpha_pct), count(*) FILTER (WHERE rotation_alpha_pct>0)
                   FROM rec_rotation_links WHERE rotation_alpha_pct IS NOT NULL""")
    rc, ralpha, rwin = cur.fetchone()
    a["rotation_outcomes"] = {"measured": rc or 0,
                              "avg_alpha_pct": round(float(ralpha), 2) if ralpha is not None else None,
                              "rotations_that_beat_holding": rwin or 0}
    return a


def lifecycle_performance(cur, limit=300):
    """Auto-detected position lifecycle for REAL closed trades (trade_closed): origin
    (watchlist / proposal / screener / research / directive ...) → purchase → sale (P&L · R · hold) →
    journal. Joins rec_ticker_attribution (the discovery origin) + journal_trade_reviews (the review) to
    each sold position by symbol / account / close-date — no manual tagging. Read-only, advisory."""
    DOWNSTREAM = ('execution', 'holding', 'rotation')      # not discovery origins
    SRC_LABEL = {"scan": "screener", "hermes_research": "research", "cio_decision": "cio"}
    # earliest DISCOVERY origin per symbol
    cur.execute("""SELECT DISTINCT ON (upper(symbol)) upper(symbol), source_type, first_seen_at
                   FROM rec_ticker_attribution WHERE source_type NOT IN %s
                   ORDER BY upper(symbol), first_seen_at ASC""", (DOWNSTREAM,))
    origin = {r[0]: r[1] for r in cur.fetchall()}
    cur.execute("SELECT upper(symbol), bool_or(executed) FROM rec_ticker_attribution GROUP BY 1")
    execd = {r[0]: r[1] for r in cur.fetchall()}
    # journal reviews, grouped by symbol (matched to a trade by account + close-date below)
    jrev = {}
    cur.execute("""SELECT upper(symbol), account, closed_date, realized_r, lesson_learned, setup_family
                   FROM journal_trade_reviews""")
    for sym, acct, cdate, rr, lesson, fam in cur.fetchall():
        jrev.setdefault(sym, []).append({"account": acct, "closed_date": cdate, "realized_r": rr,
                                         "lesson": lesson, "setup_family": fam})
    # spine: real closed (sold) trades. EXCLUDE data artifacts that don't belong in recommendation
    # lineage (2026-06-20): (a) raw broker CUSIPs that never resolved to a ticker (symbol !~ A-Z{1,5}),
    # (b) legacy pre-system holdings with implausibly long holds (>5yr) — e.g. an 18-yr Visa lot showing
    # +2729% — which are real trades but not recommendation outcomes. Underlying trade_closed is untouched.
    cur.execute("""SELECT id, upper(symbol), account, open_date, close_date, shares, buy_price, sell_price,
                          pnl, pnl_pct, r_multiple, hold_days, setup, strategy_id
                   FROM trade_closed
                   WHERE symbol ~ '^[A-Za-z]{1,5}$' AND (hold_days IS NULL OR hold_days <= 1825)
                   ORDER BY close_date DESC NULLS LAST, id DESC LIMIT %s""", (limit,))
    out = []
    for (tid, sym, acct, od, cd, sh, bp, sp, pnl, pnlpct, rmult, hold, setup, strat) in cur.fetchall():
        org = origin.get(sym)
        jr, cd10 = None, str(cd)[:10] if cd else None
        cands = jrev.get(sym, [])
        if cands:
            def _score(j):
                s = 0
                if acct and j["account"] == acct: s += 2
                if cd10 and j["closed_date"] and str(j["closed_date"])[:10] == cd10: s += 3
                return s
            best = max(cands, key=_score)
            jr = best if _score(best) > 0 else None
        out.append({
            "trade_id": tid, "symbol": sym, "account": acct,
            "origin": SRC_LABEL.get(org, org), "origin_raw": org,
            "executed_lineage": bool(execd.get(sym)),
            "open_date": str(od) if od else None, "close_date": str(cd) if cd else None,
            "shares": float(sh) if sh is not None else None,
            "buy_price": float(bp) if bp is not None else None,
            "sell_price": float(sp) if sp is not None else None,
            "pnl": float(pnl) if pnl is not None else None,
            "pnl_pct": float(pnlpct) if pnlpct is not None else None,
            # trade_closed.r_multiple/setup are never populated (2026-07-04 hub audit) —
            # fall back to the matched journal review's realized_r / setup_family.
            "r_multiple": (float(rmult) if rmult is not None
                           else (float(jr["realized_r"]) if jr and jr.get("realized_r") is not None else None)),
            "hold_days": int(hold) if hold is not None else None,
            "setup": setup or (jr.get("setup_family") if jr else None),
            "strategy_id": strat, "journaled": jr is not None,
            "journal": ({"realized_r": float(jr["realized_r"]) if jr.get("realized_r") is not None else None,
                         "lesson": jr.get("lesson"), "setup_family": jr.get("setup_family")} if jr else None),
        })
    return out


def open_positions(cur):
    """Currently-held REAL positions (the 'monitored till sale' phase): cost basis from trade_transactions
    buys, current price from holdings.json, unrealized P&L, held-since date, and discovery origin. The open
    counterpart of lifecycle_performance(). Read-only, advisory."""
    try:
        hj = json.loads((ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
    except Exception:
        return []
    held = [h for h in hj.get("holdings", []) if h.get("symbol") and not h.get("is_cash")
            and not h.get("delisted") and (h.get("shares") or 0) > 0]
    if not held:
        return []
    syms = list({h["symbol"].upper() for h in held})
    # weighted-avg buy cost + earliest acquisition per (symbol, account)
    cur.execute("""SELECT upper(symbol), account,
                     sum(quantity*price) FILTER (WHERE quantity>0 AND price>0) tot,
                     sum(quantity) FILTER (WHERE quantity>0 AND price>0) qty, min(trade_date) first_buy
                   FROM trade_transactions
                   WHERE upper(symbol)=ANY(%s)
                     AND (action ILIKE '%%buy%%' OR action ILIKE '%%bought%%' OR action ILIKE '%%reinvest%%')
                   GROUP BY 1,2""", (syms,))
    cost = {}
    for sym, acct, tot, qty, first in cur.fetchall():
        if qty and tot:
            cost[(sym, acct)] = {"avg": float(tot) / float(qty), "since": first}
    cur.execute("""SELECT DISTINCT ON (upper(symbol)) upper(symbol), source_type FROM rec_ticker_attribution
                   WHERE source_type NOT IN ('execution','holding','rotation') AND upper(symbol)=ANY(%s)
                   ORDER BY upper(symbol), first_seen_at ASC""", (syms,))
    SRC_LABEL = {"scan": "screener", "hermes_research": "research", "cio_decision": "cio"}
    origin = {r[0]: SRC_LABEL.get(r[1], r[1]) for r in cur.fetchall()}
    out = []
    for h in held:
        sym, acct, sh, px = h["symbol"].upper(), h.get("account"), h.get("shares") or 0, h.get("price")
        cb = cost.get((sym, acct)) or next((v for (s2, _a), v in cost.items() if s2 == sym), None)
        avg = cb["avg"] if cb else None
        upnl = (px - avg) * sh if (avg and px) else None
        out.append({"symbol": sym, "account": acct, "shares": float(sh),
                    "avg_cost": round(avg, 4) if avg else None, "current_price": px,
                    "market_value": h.get("market_value"),
                    "unrealized_pnl": round(upnl, 2) if upnl is not None else None,
                    "unrealized_pnl_pct": round((px - avg) / avg * 100, 2) if (avg and px) else None,
                    "held_since": str(cb["since"]) if cb and cb.get("since") else None,
                    "origin": origin.get(sym)})
    out.sort(key=lambda x: (x["unrealized_pnl_pct"] is None, -(x["unrealized_pnl_pct"] or 0)))
    return out


def symbol_outcomes(cur, limit=3000):
    """Per-symbol outcome map — closed (purchase→sale) AND open (held, unrealized) — for flagging
    watchlist / proposal items and enriching journal rows with their discovery origin. Read-only."""
    by = {}
    for r in lifecycle_performance(cur, limit=limit):
        s = by.setdefault(r["symbol"], {"symbol": r["symbol"], "closed_trades": 0, "wins": 0,
                                        "total_pnl": 0.0, "last_pnl_pct": None, "last_close": None,
                                        "origin": r["origin"], "journaled": False})
        s["closed_trades"] += 1
        if (r["pnl"] or 0) > 0:
            s["wins"] += 1
        s["total_pnl"] += r["pnl"] or 0
        if s["last_close"] is None or (r["close_date"] or "") > s["last_close"]:
            s["last_close"], s["last_pnl_pct"] = r["close_date"], r["pnl_pct"]
        if r["journaled"]:
            s["journaled"] = True
        if not s["origin"] and r["origin"]:
            s["origin"] = r["origin"]
    for s in by.values():
        s["win_rate_pct"] = round(s["wins"] / s["closed_trades"] * 100, 1) if s["closed_trades"] else None
        s["total_pnl"] = round(s["total_pnl"], 2)
    # merge currently-held (open / monitoring) state — a symbol can be both sold-before AND held-now,
    # and can be held across multiple accounts/lots: aggregate shares + cost basis → weighted unrealized %.
    for op in open_positions(cur):
        s = by.setdefault(op["symbol"], {"symbol": op["symbol"], "closed_trades": 0, "wins": 0,
                                         "total_pnl": 0.0, "last_pnl_pct": None, "last_close": None,
                                         "origin": op.get("origin"), "journaled": False, "win_rate_pct": None})
        s["held"] = True
        s["held_shares"] = round((s.get("held_shares") or 0) + op["shares"], 4)
        if op["unrealized_pnl"] is not None:
            s["unrealized_pnl"] = round((s.get("unrealized_pnl") or 0) + op["unrealized_pnl"], 2)
        if op.get("avg_cost") and op.get("shares"):
            s["_cost_basis"] = (s.get("_cost_basis") or 0) + op["avg_cost"] * op["shares"]
        if op.get("held_since") and (not s.get("held_since") or op["held_since"] < s["held_since"]):
            s["held_since"] = op["held_since"]
        if not s.get("origin") and op.get("origin"):
            s["origin"] = op["origin"]
    for s in by.values():
        if s.get("held") and s.get("_cost_basis"):
            s["unrealized_pnl_pct"] = round((s.get("unrealized_pnl") or 0) / s["_cost_basis"] * 100, 2)
        s.pop("_cost_basis", None)
    return by


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
    events = rot_measured = sq = None
    if not dry:
        conn.commit()
        # Phase 2: append lineage events + measure rotation outcomes
        try:
            events = emit_lifecycle_events(cur)
        except Exception as e:
            conn.rollback(); print("  lifecycle events skipped:", str(e)[:90])
        try:
            pairs = detect_rotation_pairs(cur)
            print(f"  rotation pairs detected from trade history: {pairs}")
        except Exception as e:
            conn.rollback(); print("  rotation-pair detection skipped:", str(e)[:90])
        try:
            rot_measured = measure_rotations(cur)
        except Exception as e:
            conn.rollback(); print("  rotation measure skipped:", str(e)[:90])
        # Phase 3: learn per-source quality multipliers
        try:
            sq = compute_source_quality(cur)
        except Exception as e:
            conn.rollback(); print("  source quality skipped:", str(e)[:90])
        cur.execute("SELECT count(DISTINCT symbol), count(*) , count(*) FILTER (WHERE executed) FROM rec_ticker_attribution")
        usyms, total, execd = cur.fetchone()
        cur.execute("SELECT count(*) FROM rec_rotation_links")
        rlinks = cur.fetchone()[0]
    else:
        usyms = total = execd = rlinks = "(dry-run)"
    out = {"ok": True, "dry_run": dry, "ingested_by_source": counts,
           "distinct_symbols": usyms, "attribution_rows": total, "executed_rows": execd,
           "rotation_links": rlinks, "lifecycle_events_added": events,
           "rotations_measured": rot_measured, "source_quality": sq}
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
