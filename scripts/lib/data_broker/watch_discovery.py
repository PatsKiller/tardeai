"""Watch Discovery — Data Broker read model over watch_candidate_events (a DEAD feed).

Registry domain ``watch_discovery`` (class dead_feed, writer none, no_coverage
``declared_gap_no_producer``): 13,093 rows, newest emitted_on 2026-07-16, and no
INSERT anywhere in the repo since. Before Phase 4 scripts/api_v2.py read the table
directly in six places and rendered the rows as a live track record.

Every read here carries the envelope with ``gap.kind == "no_producer"`` and the
last as_of, so the Screener Finds / Directives panels show "no producer since
2026-07-16" rather than a current-looking α table. Nothing is deleted; the
history stays readable. The SQL is the handlers' own, moved verbatim so the
numbers do not change — only their label does.

Zero provider calls. Read-only.
"""
from __future__ import annotations

from typing import Any

from lib.data_broker.envelope import envelope

DOMAIN = "watch_discovery"
TABLE = "watch_candidate_events"

LAST_SQL = "SELECT max(emitted_at) AS last_at, max(emitted_on) AS last_on, count(*) AS n FROM watch_candidate_events"

QUALITY_GATE_SQL = """SELECT source_type,
                                   count(*) AS emitted,
                                   count(*) FILTER (WHERE alpha_21d IS NOT NULL) AS n,
                                   round((percentile_cont(0.5) WITHIN GROUP (ORDER BY alpha_21d)
                                     FILTER (WHERE alpha_21d IS NOT NULL))::numeric, 2) AS alpha_21d_median,
                                   round((percentile_cont(0.5) WITHIN GROUP (ORDER BY alpha_21d)
                                     FILTER (WHERE alpha_21d IS NOT NULL AND proposed))::numeric, 2) AS converted_alpha_21d,
                                   count(*) FILTER (WHERE proposed) AS converted
                            FROM watch_candidate_events
                            WHERE emitted_on > CURRENT_DATE - %s
                            GROUP BY source_type ORDER BY source_type"""

WIDE_FINDS_SQL = """SELECT source_type, symbol, emitted_on, anchor_price, alpha_21d, verdict, proposed
                            FROM watch_candidate_events
                            WHERE source_type IN ('screener_find','ai_discovered')
                              AND emitted_on > CURRENT_DATE - 90
                            ORDER BY emitted_on DESC LIMIT 120"""

TRACK_RECORD_SQL = """SELECT count(*) AS n,
                                count(*) FILTER (WHERE alpha_21d IS NOT NULL) AS scored,
                                round((percentile_cont(0.5) WITHIN GROUP (ORDER BY alpha_21d)
                                  FILTER (WHERE alpha_21d IS NOT NULL))::numeric, 2) AS median_alpha_21d,
                                round((percentile_cont(0.5) WITHIN GROUP (ORDER BY alpha_21d)
                                  FILTER (WHERE alpha_21d IS NOT NULL AND proposed))::numeric, 2) AS converted_alpha_21d,
                                count(*) FILTER (WHERE proposed AND alpha_21d IS NOT NULL) AS converted_scored,
                                count(*) FILTER (WHERE proposed) AS converted
                         FROM watch_candidate_events
                         WHERE source_type IN ('screener_find','ai_discovered')
                           AND emitted_on > CURRENT_DATE - 90"""

DIRECTIVE_ALPHA_SQL = """SELECT symbol, emitted_on, alpha_21d, alpha_63d, verdict, staged, proposed
                                FROM watch_candidate_events
                                WHERE source_type='directive_hit' AND source_id=%s
                                ORDER BY emitted_on DESC LIMIT 60"""

DIRECTIVE_SCORE_SQL = """SELECT source_id::bigint AS did,
                                      count(*) AS events,
                                      count(*) FILTER (WHERE alpha_21d IS NOT NULL) AS scored,
                                      round((percentile_cont(0.5) WITHIN GROUP (ORDER BY alpha_21d)
                                        FILTER (WHERE alpha_21d IS NOT NULL))::numeric, 2) AS alpha_21d_median,
                                      count(*) FILTER (WHERE proposed) AS proposed_n
                               FROM watch_candidate_events
                               WHERE source_type='directive_hit' AND source_id ~ '^[0-9]+$'
                               GROUP BY 1"""


def feed_envelope(db_query, *, now=None, registry=None) -> dict[str, Any]:
    """The envelope for the whole feed: last emitted_at and row count."""
    last = None
    n = None
    try:
        r = db_query(LAST_SQL, fetch="one") or {}
        last = r.get("last_at") or r.get("last_on")
        n = r.get("n")
    except Exception:  # noqa: BLE001
        pass
    env = envelope(DOMAIN, last, now=now, registry=registry, source={"table": TABLE, "rows": n})
    env["provider_calls"] = 0
    return env


def quality_gate_rows(db_query, window_days: int) -> list[dict[str, Any]]:
    return db_query(QUALITY_GATE_SQL, (int(window_days),)) or []


def wide_finds_rows(db_query) -> list[dict[str, Any]]:
    return db_query(WIDE_FINDS_SQL) or []


def track_record_row(db_query) -> dict[str, Any]:
    return db_query(TRACK_RECORD_SQL, fetch="one") or {}


def directive_alpha_events(db_query, directive_id: Any) -> list[dict[str, Any]]:
    return db_query(DIRECTIVE_ALPHA_SQL, (str(directive_id),)) or []


def directive_score_meta(db_query) -> dict[Any, dict[str, Any]]:
    out: dict[Any, dict[str, Any]] = {}
    for r in db_query(DIRECTIVE_SCORE_SQL) or []:
        out[r["did"]] = r
    return out
