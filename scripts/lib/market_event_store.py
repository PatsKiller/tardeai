"""market_event_store — read/write market_event_episodes and market_event_candidates (LQ-20261107-332, WP1).

Schema: migrations/2026_11_07_market_event.sql (spec §4.1–4.2 names, plus ``scope`` and ``last_eval``).
Readers work on a read-only connection and return [] when the tables do not exist yet (migration not applied).
Writers are called only by ``scripts/market_event_detect.py --apply``; they never run in a dry run.
Candidate writes preserve WP3/operator fields: ``gates``, ``state`` and ``plan`` are set on insert only, so a
re-rank never resets a READY/ENTERED/INVALIDATED candidate.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Iterable, Mapping

EPISODE_COLS = ("episode_id", "kind", "scope", "state", "opened_at", "closed_at", "trigger", "baseline_date",
                "affected_sectors", "policy_version", "last_eval", "updated_at")


def episode_id(kind: str, scope: str, baseline_date: date | str) -> str:
    b = baseline_date.isoformat() if isinstance(baseline_date, date) else str(baseline_date)
    return f"{kind}:{scope}:{b}"


def tables_exist(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('market_event_episodes') IS NOT NULL AND "
                    "to_regclass('market_event_candidates') IS NOT NULL")
        return bool(cur.fetchone()[0])


def _jsonable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def list_episodes(conn, *, open_only: bool = True) -> list[dict]:
    if not tables_exist(conn):
        return []
    sql = f"SELECT {', '.join(EPISODE_COLS)} FROM market_event_episodes"
    if open_only:
        sql += " WHERE state <> 'CLOSED'"
    sql += " ORDER BY opened_at"
    with conn.cursor() as cur:
        cur.execute(sql)
        return [{k: _jsonable(v) for k, v in zip(EPISODE_COLS, row)} for row in cur.fetchall()]


def upsert_episode(conn, ep: Mapping[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO market_event_episodes
                (episode_id, kind, scope, state, opened_at, closed_at, trigger, baseline_date, affected_sectors,
                 policy_version, last_eval, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, now())
            ON CONFLICT (episode_id) DO UPDATE SET
                state = EXCLUDED.state, closed_at = EXCLUDED.closed_at, trigger = EXCLUDED.trigger,
                affected_sectors = EXCLUDED.affected_sectors, policy_version = EXCLUDED.policy_version,
                last_eval = EXCLUDED.last_eval, updated_at = now()""",
                    (ep["episode_id"], ep["kind"], ep["scope"], ep["state"], ep["opened_at"], ep.get("closed_at"),
                     json.dumps(ep.get("trigger") or {}, default=str), ep["baseline_date"],
                     list(ep.get("affected_sectors") or []), ep["policy_version"],
                     json.dumps(ep.get("last_eval") or {}, default=str)))


def upsert_candidates(conn, eid: str, cands: Iterable[Mapping[str, Any]]) -> int:
    n = 0
    with conn.cursor() as cur:
        for c in cands:
            cur.execute("""
                INSERT INTO market_event_candidates
                    (episode_id, symbol, source, baseline_price, last_price, drawdown_pct, quality_score,
                     discount_score, rank, fell_for_reason, reason_evidence, gates, state, plan, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, now())
                ON CONFLICT (episode_id, symbol) DO UPDATE SET
                    source = EXCLUDED.source, baseline_price = EXCLUDED.baseline_price,
                    last_price = EXCLUDED.last_price, drawdown_pct = EXCLUDED.drawdown_pct,
                    quality_score = EXCLUDED.quality_score, discount_score = EXCLUDED.discount_score,
                    rank = EXCLUDED.rank, fell_for_reason = EXCLUDED.fell_for_reason,
                    reason_evidence = EXCLUDED.reason_evidence, updated_at = now()""",
                        (eid, c["symbol"], list(c["source"]), c["baseline_price"], c["last_price"], c["drawdown_pct"],
                         c["quality_score"], c["discount_score"], c["rank"], bool(c["fell_for_reason"]),
                         json.dumps(c["reason_evidence"], default=str), json.dumps(c.get("gates") or {}),
                         c.get("state") or "WATCH",
                         None if c.get("plan") is None else json.dumps(c["plan"], default=str)))
            n += 1
    return n


def unrank_missing(conn, eid: str, keep: Iterable[str]) -> int:
    """Candidates no longer in the ranked set keep their row (never delete) but lose their rank."""
    with conn.cursor() as cur:
        cur.execute("""UPDATE market_event_candidates SET rank = NULL, updated_at = now()
                        WHERE episode_id = %s AND NOT (symbol = ANY(%s)) AND rank IS NOT NULL""",
                    (eid, sorted(set(keep))))
        return cur.rowcount
