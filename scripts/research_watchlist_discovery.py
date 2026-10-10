#!/usr/bin/env python3
"""research_watchlist_discovery.py — surface Hermes/social research as watchlist ideas.

Closes the "same sources, curated into ideas" gap (2026-08-19 audit, Gap C): the
watchlist was fed almost exclusively by the Finviz screener, so Hermes forum/web
research and social momentum never became watchlist candidates on their own.

This lane reads the SAME research sources as the day-scalp pipeline
(hermes_research_intelligence = Hermes/SearXNG forum+web; social_sentiment_history =
social) and writes them into watchlist_items as NON-trading research ideas
(status='researched', bucket='research_discovery', source_tier='candidate').

It never auto-promotes to the watchpool or any execution rail — it only surfaces
"here's what's happening in the market for research", exactly like topic_curator's
research_discovery bucket. It is deliberately SEPARATE from the momentum scalp lead
miner (which stages to the incubator + 'active' watchlist for trading).

Usage:
    python3 scripts/research_watchlist_discovery.py --dry-run
    python3 scripts/research_watchlist_discovery.py --apply --max-symbols 60

Dry run (n8n refactor wave 3, 2026-10-10): ``--dry-run`` WINS over ``--apply``; no ``--apply`` is still a
dry run. The dry run reads the same two sources, classifies each surfaced symbol as new vs already listed
with a read-only SELECT, prints a ``DRY-RUN`` report and returns BEFORE ``_upsert`` / commit /
``report_source`` are reachable; its session is READ ONLY at the server. It writes no receipt.

A REAL (``--apply``) run writes LaneRunReceipt@v1 ``<state_root>/data/runtime/research-watchlist-discovery_last.json``
(``ok_at`` only on success). Exit codes: 0 = ran (zero candidates is a finding, still 0); 1 = the run
failed (DB unavailable / a source query raised, or EVERY candidate's upsert failed); 2 = usage error.
A single failed upsert is a per-item soft failure (rolled back, counted, still exit 0).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SOURCE_KEY = "research_discovery"
HORIZON_DAYS = 7
LANE_ID = "research-watchlist-discovery"


def _get_conn():
    from db_adapter import _get_conn as _c
    return _c()


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.research_watchlist_discovery
        from scripts.lib import lane_last_receipt as lr
    return lr


def _research_candidates(conn, limit: int) -> list[dict]:
    """Symbols surfaced by Hermes/SearXNG research in the last N days."""
    cur = conn.cursor()
    cur.execute(
        """SELECT symbol, topic, summary, confidence_score, status
           FROM hermes_research_intelligence
           WHERE symbol IS NOT NULL
             AND status IN ('staged', 'promoted', 'reviewed')
             AND created_at > NOW() - (%s * INTERVAL '1 day')
           ORDER BY confidence_score DESC NULLS LAST
           LIMIT %s""",
        (HORIZON_DAYS, limit),
    )
    out = []
    for sym, topic, summary, conf, status in cur.fetchall():
        thesis = (topic or summary or "").strip()[:140]
        out.append({
            "symbol": sym.upper(),
            "origin_system": "hermes_research",
            "provenance_reason": f"Hermes research: {thesis or status}",
            "detail": {"source": "hermes_research", "thesis": thesis,
                       "confidence": float(conf) if conf else None},
        })
    return out


def _social_candidates(conn, limit: int) -> list[dict]:
    """Symbols with unusual social momentum (spike or strong one-sided sentiment)."""
    cur = conn.cursor()
    cur.execute(
        """SELECT symbol, mention_count, sentiment_score, unusual_spike
           FROM social_sentiment_history
           WHERE observed_at > NOW() - (%s * INTERVAL '1 day')
             AND (unusual_spike = true OR ABS(COALESCE(sentiment_score, 0)) >= 0.5)
           ORDER BY observed_at DESC
           LIMIT %s""",
        (HORIZON_DAYS, limit),
    )
    out = []
    for sym, mentions, score, spike in cur.fetchall():
        out.append({
            "symbol": sym.upper(),
            "origin_system": "social_momentum",
            "provenance_reason": f"Social momentum: {mentions} mentions, sentiment {score}",
            "detail": {"source": "social_momentum", "mentions": mentions,
                       "sentiment_score": float(score) if score is not None else None,
                       "unusual_spike": bool(spike)},
        })
    return out


def _upsert(conn, cand: dict) -> str | None:
    """Insert a new research idea, or mark an existing one as seen again.

    Until 2026-09-15 this was ON CONFLICT DO NOTHING, and the run reported
    "0 research candidates" whenever every surfaced name was already on the list:
    60 candidates a day, 0 written, data_source_health 'error' for 7 days, and the
    771 existing ideas never had last_seen_at refreshed (6 seen in 7 days). A
    re-surfaced idea now refreshes last_seen_at and seen_count. Status is never
    touched, so an idea the operator removed stays removed.
    """
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO watchlist_items
               (symbol, source, status, bucket, origin_system, origin_detail,
                source_tier, in_directive_watch, provenance_reason, seen_count,
                first_seen_at, last_seen_at)
           VALUES (%s, %s, 'researched', 'research_discovery', %s, %s::jsonb,
                   'candidate', false, %s, 1, NOW(), NOW())
           ON CONFLICT (symbol, source, COALESCE(bucket, '__none__')) DO UPDATE
               SET last_seen_at = NOW(),
                   seen_count = COALESCE(watchlist_items.seen_count, 0) + 1
           RETURNING (xmax = 0) AS inserted""",
        (cand["symbol"], SOURCE_KEY, cand["origin_system"],
         json.dumps(cand["detail"], default=str), cand["provenance_reason"]))
    row = cur.fetchone()
    if row is None:
        return None
    inserted = row[0] if not isinstance(row, dict) else row.get("inserted")
    return "inserted" if inserted else "refreshed"


def run_report(candidates: int, written: int, refreshed: int) -> tuple[bool, int, str | None]:
    """(ok, rows, error) for data_source_health. Healthy means research surfaced names."""
    if candidates <= 0:
        return False, 0, "0 research candidates"
    return True, written + refreshed, None


def _collect(conn, max_symbols: int) -> dict[str, dict]:
    """Read both sources (SELECT only) and dedup by symbol (research first, then social)."""
    half = max(1, max_symbols // 2)

    research = _research_candidates(conn, half)
    social = _social_candidates(conn, half)
    print(f"[research-discovery] Hermes research: {len(research)} | social momentum: {len(social)}")

    # Dedup by symbol (research first, then social); merge provenance if both hit.
    by_symbol: dict[str, dict] = {}
    for c in research + social:
        sym = c["symbol"]
        if sym in by_symbol:
            merged = dict(by_symbol[sym]["detail"])
            merged.update(c["detail"])
            by_symbol[sym]["detail"] = merged
            by_symbol[sym]["origin_system"] = "hermes_research+social"
            by_symbol[sym]["provenance_reason"] = (
                by_symbol[sym]["provenance_reason"] + " | " + c["provenance_reason"])
        else:
            by_symbol[sym] = c
    return by_symbol


def _already_listed(conn, symbols: list[str]) -> set[str]:
    """Read-only: which symbols already hold a research_discovery row (an upsert would refresh, not insert)."""
    if not symbols:
        return set()
    cur = conn.cursor()
    cur.execute(
        """SELECT symbol FROM watchlist_items
           WHERE source = %s AND bucket = 'research_discovery' AND symbol = ANY(%s)""",
        (SOURCE_KEY, symbols),
    )
    return {str(r[0]).upper() for r in cur.fetchall()}


def _dry_run(args) -> int:
    """Read-only preview. ``_upsert``, ``commit`` and ``report_source`` are not reachable from here."""
    lr = _receipt_lib()
    try:
        conn = _get_conn()
        lr.enforce_readonly(conn)
        by_symbol = _collect(conn, args.max_symbols)
        listed = _already_listed(conn, list(by_symbol))
    except Exception as e:
        print(f"[research-discovery] DRY-RUN read failed: {type(e).__name__}: {e}")
        return 1
    new = [s for s in by_symbol if s not in listed]
    print(f"[research-discovery] would write {len(new)} new research ideas, "
          f"refresh {len(by_symbol) - len(new)} already listed")
    try:
        conn.close()
    except Exception:
        pass
    lr.dry_run_report(
        LANE_ID,
        {"candidates": len(by_symbol), "would_insert": len(new), "would_refresh": len(by_symbol) - len(new),
         "symbols": sorted(by_symbol)[:20]},
        would_write=["watchlist_items (INSERT/refresh, bucket=research_discovery)",
                     f"data_source_health ({SOURCE_KEY})"],
    )
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="read + report only; wins over --apply")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-symbols", type=int, default=60)
    args = ap.parse_args(argv)

    if args.dry_run or not args.apply:
        return _dry_run(args)

    lr = _receipt_lib()
    started = datetime.now(timezone.utc).isoformat()
    try:
        conn = _get_conn()
        by_symbol = _collect(conn, args.max_symbols)

        written = refreshed = failed = 0
        for sym, cand in by_symbol.items():
            try:
                outcome = _upsert(conn, cand)
                if outcome == "inserted":
                    written += 1
                elif outcome == "refreshed":
                    refreshed += 1
            except Exception as e:
                conn.rollback()
                failed += 1
                print(f"  [research-discovery] {sym} upsert error: {e}")
            else:
                conn.commit()

        ok, rows, error = run_report(len(by_symbol), written, refreshed)
        try:
            from lib.data_source_report import report_source
            report_source(SOURCE_KEY, ok, rows=rows, error=error)
        except Exception:
            pass

        print(f"[research-discovery] wrote {written} new research ideas, "
              f"refreshed {refreshed} already listed, {failed} failed")
        conn.close()
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="research_watchlist_discovery.py", error=f"{type(exc).__name__}: {exc}")
        raise
    rc = 1 if by_symbol and failed == len(by_symbol) else 0
    lr.write_lane_receipt(LANE_ID, ok=rc == 0, exit_code=rc, started_at=started,
                          script="research_watchlist_discovery.py",
                          summary={"candidates": len(by_symbol), "written": written,
                                   "refreshed": refreshed, "failed": failed})
    return rc


if __name__ == "__main__":
    sys.exit(main())
