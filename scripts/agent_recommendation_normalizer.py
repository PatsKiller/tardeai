#!/usr/bin/env python3
"""agent_recommendation_normalizer.py — Normalize agent recommendations into registry.

Extracts recommendations from watchlist_agent_results, cio_decisions, agent_debate_log,
and other agent output tables into a unified agent_recommendation_registry.

Usage:
    .venv/bin/python scripts/agent_recommendation_normalizer.py --dry-run --json
    .venv/bin/python scripts/agent_recommendation_normalizer.py --apply --json
    .venv/bin/python scripts/agent_recommendation_normalizer.py --agent Maria --dry-run --json

Refactor shard 08 (source proposal, 2026-10-11):
- Explicit ``--dry-run`` returns an offline plan before env loading or a DB connection.
- Without ``--apply``, the existing READ ONLY database preview remains available.
- A real ``--apply`` run writes data/runtime/agent_recommendation_normalizer_last.json
  and agent-recommendation-normalizer_last.json (LaneRunReceipt@v1, ok_at only on success).
  Any exception still exits non-zero; the underscore name preserves existing consumers.
"""
import argparse, hashlib, json, os, sys
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
LANE_ID = "agent-recommendation-normalizer"
_ENV_KEYS = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")


def _load_env():
    from lib.env_bootstrap import load_env

    return load_env(names=_ENV_KEYS)


def _write_run_receipts(**kwargs):
    from lib.lane_last_receipt import write_receipt

    # Keep the legacy spelling for its existing readers and expose the registry lane id.
    write_receipt("agent_recommendation_normalizer", **kwargs)
    write_receipt(LANE_ID, **kwargs)

SECRET_KEYS = {"password", "token", "secret", "api_key", "cookie", "credential", "private_key"}

def _f(v):
    return float(v) if isinstance(v, Decimal) else v

def _get_conn():
    _load_env()
    from session13_db import get_conn
    return get_conn()

def _recommendation_id(source_table: str, source_id: str) -> str:
    """Stable id so a second run hits ON CONFLICT DO NOTHING instead of inserting again.

    A fresh UUID per row inserted the same ~6,500 source rows on every run
    (watchlist limit 5000 + cio 1000 + debates 500). The unique key is
    recommendation_id, so the id has to be a function of the source row.
    """
    digest = hashlib.sha256(f"{source_table}:{source_id}".encode("utf-8")).hexdigest()[:20]
    return f"AREC_{digest}"

def _redact(payload):
    if not isinstance(payload, dict):
        return payload
    return {k: "***" if any(s in k.lower() for s in SECRET_KEYS) else v
            for k, v in payload.items()}

def _conf01(v):
    """Confidence on the registry's 0..1 scale (2026-10-18).

    agent_recommendation_registry.confidence is a 0..1 column (single_scale
    contract: 464,089 rows in (0,1], 18 above 1). Source values above 1 or below
    0 are clamped; NaN/unparseable becomes None (unknown), never a number.
    """
    if v is None:
        return None
    try:
        c = float(v)
    except (TypeError, ValueError):
        return None
    if c != c or c in (float("inf"), float("-inf")):
        return None
    return max(0.0, min(1.0, c))


def _confidence_bucket(conf):
    if conf is None:
        return "unknown"
    c = float(conf)
    if c >= 0.8: return "very_high"
    if c >= 0.6: return "high"
    if c >= 0.4: return "medium"
    return "low"

def _map_recommendation(rec_text):
    if not rec_text:
        return "hold", "hold"
    r = rec_text.upper().strip()
    mapping = {
        "BUY": ("buy", "buy"), "STRONG BUY": ("buy", "buy"),
        "SELL": ("sell", "sell"), "STRONG SELL": ("sell", "sell"),
        "HOLD": ("hold", "hold"), "MAINTAIN": ("hold", "hold"),
        "TRIM": ("trim", "trim"), "ADD": ("add", "add"),
        "AVOID": ("avoid", "avoid"), "WAIT": ("wait", "wait"),
        "RESEARCH": ("research_more", "research_more"),
        "APPROVE": ("approve_trade", "approve_trade"),
        "REJECT": ("reject_trade", "reject_trade"),
    }
    for key, val in mapping.items():
        if key in r:
            return val
    return "hold", rec_text.lower()[:50]


def normalize_watchlist_results(conn, agent_filter=None, symbol_filter=None):
    """Extract from watchlist_agent_results."""
    cur = conn.cursor()
    sql = "SELECT id, agent, symbol, recommendation, confidence, created_at FROM watchlist_agent_results WHERE 1=1"
    params = []
    if agent_filter:
        sql += " AND agent ILIKE %s"
        params.append(f"%{agent_filter}%")
    if symbol_filter:
        sql += " AND symbol = %s"
        params.append(symbol_filter)
    sql += " ORDER BY created_at DESC LIMIT 5000"
    cur.execute(sql, params)

    recs = []
    for row in cur.fetchall():
        rec_type, rec_action = _map_recommendation(row[3])
        recs.append({
            "recommendation_id": _recommendation_id("watchlist_agent_results", str(row[0])),
            "agent_name": row[1] or "unknown",
            "agent_role": "watchlist_analyst",
            "source_table": "watchlist_agent_results",
            "source_id": str(row[0]),
            "symbol": row[2],
            "strategy_id": None,
            "recommendation_type": rec_type,
            "recommendation_action": rec_action,
            "confidence": _conf01(row[4]),
            "confidence_bucket": _confidence_bucket(_conf01(row[4])),
            "time_horizon": "swing",
            "recommendation_time": row[5],
        })
    return recs


def normalize_cio_decisions(conn, agent_filter=None, symbol_filter=None):
    """Extract from cio_decisions."""
    cur = conn.cursor()
    sql = "SELECT decision_id, symbol, action, confidence_raw, agent_votes, created_at FROM cio_decisions WHERE 1=1"
    params = []
    if symbol_filter:
        sql += " AND symbol = %s"
        params.append(symbol_filter)
    sql += " ORDER BY created_at DESC LIMIT 1000"
    cur.execute(sql, params)

    recs = []
    for row in cur.fetchall():
        if agent_filter:
            continue  # CIO decisions are system-level
        rec_type, rec_action = _map_recommendation(row[2])
        recs.append({
            "recommendation_id": _recommendation_id("cio_decisions", str(row[0])),
            "agent_name": "cio_engine",
            "agent_role": "decision_maker",
            "source_table": "cio_decisions",
            "source_id": str(row[0]),
            "symbol": row[1],
            "recommendation_type": rec_type,
            "recommendation_action": rec_action,
            "confidence": _conf01(row[3]),
            "confidence_bucket": _confidence_bucket(_conf01(row[3])),
            "time_horizon": "swing",
            "recommendation_time": row[5],
        })
    return recs


def normalize_debates(conn, agent_filter=None, symbol_filter=None):
    """Extract from agent_debate_log."""
    cur = conn.cursor()
    sql = "SELECT id, symbol, participants, consensus_recommendation, consensus_score, created_at FROM agent_debate_log WHERE 1=1"
    params = []
    if symbol_filter:
        sql += " AND symbol = %s"
        params.append(symbol_filter)
    sql += " ORDER BY created_at DESC LIMIT 500"
    cur.execute(sql, params)

    recs = []
    for row in cur.fetchall():
        participants = row[2] or []
        if agent_filter and not any(agent_filter.lower() in (p or "").lower() for p in participants):
            continue
        rec_type, rec_action = _map_recommendation(row[3])
        agent_name = ", ".join(participants[:3]) if participants else "debate_group"
        recs.append({
            "recommendation_id": _recommendation_id("agent_debate_log", str(row[0])),
            "agent_name": agent_name,
            "agent_role": "debate_consensus",
            "source_table": "agent_debate_log",
            "source_id": str(row[0]),
            "symbol": row[1],
            "recommendation_type": rec_type,
            "recommendation_action": rec_action,
            "confidence": _conf01(row[4]),
            "confidence_bucket": _confidence_bucket(_conf01(row[4])),
            "time_horizon": "swing",
            "recommendation_time": row[5],
        })
    return recs


def save_recommendations(conn, recs, dry_run=True):
    """Upsert into agent_recommendation_registry."""
    if dry_run:
        return len(recs)
    cur = conn.cursor()
    inserted = 0
    for r in recs:
        cur.execute("""
            INSERT INTO agent_recommendation_registry
                (recommendation_id, agent_name, agent_role, source_table, source_id,
                 symbol, strategy_id, recommendation_type, recommendation_action,
                 confidence, confidence_bucket, time_horizon, recommendation_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (recommendation_id) DO NOTHING
        """, [r["recommendation_id"], r["agent_name"], r["agent_role"],
              r["source_table"], r["source_id"], r["symbol"], r.get("strategy_id"),
              r["recommendation_type"], r["recommendation_action"],
              r.get("confidence"), r.get("confidence_bucket"),
              r.get("time_horizon"), r.get("recommendation_time")])
        wrote = cur.rowcount
        inserted += wrote
        if wrote:
            _tag_recommendation(cur, r)
    conn.commit()
    return inserted


def _tag_recommendation(cur, r: dict) -> None:
    """Attach subject identity to one normalized recommendation.

    462,902 rows carried no subject identity, so "what has this agent said about
    this sector" and "which strategy produced this call" were both unanswerable
    despite every input being present in the row.

    Tagged only when the INSERT actually wrote. The statement is
    ON CONFLICT DO NOTHING over a table that is re-scanned daily, so tagging
    unconditionally would re-resolve identity for hundreds of thousands of
    already-tagged rows on every run for no gain.

    No DDL on this table -- 462,902 rows with a live reader path; the link table
    exists so tagging never takes an ACCESS EXCLUSIVE lock here.
    Fail-safe: a tagging failure must never lose a recommendation.
    """
    try:
        from scripts.lib.cio_narrative_write import (
            load_symbol_profiles, subjects_for_symbol, write_narrative)
        load_symbol_profiles(cur)
        write_narrative(cur, source_table="agent_recommendation_registry",
                        source_id=r["recommendation_id"],
                        subjects=subjects_for_symbol(
                            r.get("symbol"), strategy_id=r.get("strategy_id")),
                        author_agent_id="cio", composed=False)
    except Exception:
        return


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agent Recommendation Normalizer", allow_abbrev=False)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--agent", help="Filter by agent name")
    parser.add_argument("--symbol", help="Filter by symbol")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.dry_run:
        print(f"DRY-RUN {LANE_ID}: would normalize agent recommendations and write a run receipt")
        return 0

    dry_run = not args.apply  # implicit database preview remains READ ONLY
    started_at = None
    if not dry_run:
        from lib.lane_last_receipt import now_iso

        started_at = now_iso()
    conn = None
    try:
        _load_env()
        conn = _get_conn()
        if dry_run:
            from lib.lane_last_receipt import enforce_readonly

            enforce_readonly(conn)  # the server refuses any write (AGENTS.md §6)
        all_recs = []
        all_recs.extend(normalize_watchlist_results(conn, args.agent, args.symbol))
        all_recs.extend(normalize_cio_decisions(conn, args.agent, args.symbol))
        all_recs.extend(normalize_debates(conn, args.agent, args.symbol))

        # Dedup by source_table+source_id
        seen = set()
        unique = []
        for r in all_recs:
            key = f"{r['source_table']}:{r['source_id']}:{r['agent_name']}"
            if key not in seen:
                seen.add(key)
                unique.append(r)

        count = save_recommendations(conn, unique, dry_run=dry_run)

        by_agent = {}
        for r in unique:
            by_agent[r["agent_name"]] = by_agent.get(r["agent_name"], 0) + 1

        out = {
            "mode": "dry_run" if dry_run else "applied",
            "total_extracted": len(unique),
            "inserted": count if not dry_run else 0,
            "would_write": ({"table": "agent_recommendation_registry", "rows": count} if dry_run else None),
            "by_agent": by_agent,
            "sources": {"watchlist": sum(1 for r in unique if r["source_table"] == "watchlist_agent_results"),
                        "cio": sum(1 for r in unique if r["source_table"] == "cio_decisions"),
                        "debate": sum(1 for r in unique if r["source_table"] == "agent_debate_log")},
        }
        if args.json:
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"Normalizer: {out['total_extracted']} recommendations ({out['mode']})")
    except Exception as exc:
        if not dry_run:
            _write_run_receipts(ok=False, exit_code=1, started_at=started_at,
                                error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception as exc:
                if not dry_run:
                    _write_run_receipts(ok=False, exit_code=1, started_at=started_at,
                                        error=f"{type(exc).__name__}: {exc}")
                raise
    if not dry_run:
        _write_run_receipts(ok=True, exit_code=0, started_at=started_at,
                            summary={"extracted": out["total_extracted"], "inserted": out["inserted"],
                                     "sources": out["sources"]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
