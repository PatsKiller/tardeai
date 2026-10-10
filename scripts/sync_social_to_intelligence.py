#!/usr/bin/env python3
"""sync_social_to_intelligence.py — fold social sentiment into the scorer's read path.

Watches the gap found in the 2026-08-19 watchlist audit: the producers
(aegis_social_sentiment.py, hermes_social_sentiment.py) write
`social_sentiment_history`, but the watchlist scorer + scope governor read
`intelligence_entities.social_score` / `social_sentiment` — which are NEVER
written (0 of ~8.4k rows had a non-null social_score at audit time).

This bridge reads the latest social_sentiment_history per tracked symbol and
folds it onto intelligence_entities (via the single-writer intelligence_entity_manager)
so `_f_social` in hermes_watchlist_scorer.py and the scope governor actually see it.

Mapping: sentiment_score (-1..1) -> social_score (0..100) = 50 + 50*score;
social_sentiment string from polarity thresholds.

Liveness: report_source('social', ...) on --apply so the health agent can track
it and the source-aware auto-remediation ladder can re-run it on a stale finding.

Usage:
    python3 scripts/sync_social_to_intelligence.py --dry-run
    python3 scripts/sync_social_to_intelligence.py --apply

Dry run (n8n refactor wave 3, 2026-10-10): ``--dry-run`` WINS over ``--apply``; no ``--apply`` is still a
dry run. It resolves the universe and reads the latest sentiment exactly like a real run, on a session
made READ ONLY at the server first (the db_adapter thread-local connection, which the universe resolver
shares), prints a ``DRY-RUN`` report and returns BEFORE ``upsert_entity`` / ``report_source`` are reachable.
It writes no receipt.

A REAL (``--apply``) run writes LaneRunReceipt@v1 ``<state_root>/data/runtime/sync-social-to-intelligence_last.json``
(``ok_at`` only on success). Exit codes: 0 = ran (an empty universe or no fresh sentiment is a finding,
still 0); 1 = the run failed (universe resolution raised, DB unavailable, or EVERY fold failed when there
were rows to fold); 2 = usage error. A single failed fold is a per-item soft failure.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Load .env
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and v and k not in os.environ:
                os.environ[k] = v

MAX_AGE_HOURS = float(os.getenv("SOCIAL_FOLD_MAX_AGE_HOURS", "168"))  # 7 days
LANE_ID = "sync-social-to-intelligence"
#: set by resolve_universe() when the resolver raised (an empty universe is otherwise a finding, not a failure)
_UNIVERSE_ERROR: list[str] = []


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.sync_social_to_intelligence
        from scripts.lib import lane_last_receipt as lr
    return lr


def _sentiment_to_social(score: float | None) -> tuple[float, str]:
    """Map social_sentiment_history.sentiment_score (-1..1) -> (social_score 0..100, label)."""
    if score is None:
        return 50.0, "neutral"
    s = float(score)
    social_score = max(0.0, min(100.0, 50.0 + s * 50.0))
    if s >= 0.3:
        label = "bullish"
    elif s >= 0.1:
        label = "positive"
    elif s <= -0.3:
        label = "bearish"
    elif s <= -0.1:
        label = "negative"
    else:
        label = "neutral"
    return round(social_score, 1), label


def resolve_universe() -> list[str]:
    """Tracked symbols (same universe the social producers scan)."""
    _UNIVERSE_ERROR.clear()
    try:
        from aegis_nightly_ingestion import resolve_universe as _ru
        return [u["symbol"] for u in _ru()]
    except Exception as e:
        _UNIVERSE_ERROR.append(type(e).__name__)
        print(f"  [social-fold] universe fallback ({e})")
        return []


def latest_sentiment(conn, symbols: list[str]) -> list[dict]:
    """Latest sentiment row per symbol within the freshness window."""
    if not symbols:
        return []
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT ON (symbol) symbol, sentiment_score, mention_count, observed_at
           FROM social_sentiment_history
           WHERE symbol = ANY(%s)
             AND observed_at > NOW() - (%s * INTERVAL '1 hour')
           ORDER BY symbol, observed_at DESC""",
        (symbols, MAX_AGE_HOURS),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return rows


def _fields(r: dict) -> dict:
    social_score, label = _sentiment_to_social(r.get("sentiment_score"))
    return {
        "social_score": social_score,
        "social_sentiment": label,
        "social_mentions": r.get("mention_count"),
        "social_updated": r.get("observed_at") or datetime.now(timezone.utc),
    }


def _dry_run() -> int:
    """Read-only preview. ``upsert_entity`` and ``report_source`` are not reachable from here."""
    lr = _receipt_lib()
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        lr.enforce_readonly(conn)  # before resolve_universe: its _db_query shares this thread-local session
    except Exception as e:
        print(f"  [social-fold] DRY-RUN db unavailable: {type(e).__name__}: {e}")
        return 1
    symbols = resolve_universe()
    if _UNIVERSE_ERROR:
        return 1
    print(f"  Universe: {len(symbols)} symbols")
    try:
        rows = latest_sentiment(conn, symbols)
    except Exception as e:
        print(f"  [social-fold] DRY-RUN read failed: {type(e).__name__}: {e}")
        return 1
    print(f"  Sentiment rows within window: {len(rows)}")
    labels: dict[str, int] = {}
    for r in rows:
        lab = _fields(r)["social_sentiment"]
        labels[lab] = labels.get(lab, 0) + 1
    print(f"  Would fold: {len(rows)} symbols")
    lr.dry_run_report(
        LANE_ID,
        {"universe": len(symbols), "would_fold": len(rows), "labels": labels,
         "max_age_hours": MAX_AGE_HOURS},
        would_write=["intelligence_entities social_* fields via upsert_entity (source=social_sync)",
                     "data_source_health (social)"],
    )
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="read + report only; wins over --apply")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    print(f"[social-fold] folding social_sentiment_history -> intelligence_entities (max_age={MAX_AGE_HOURS:.0f}h)")
    if args.dry_run or not args.apply:
        return _dry_run()

    lr = _receipt_lib()
    started = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    folded = failed = 0
    try:
        symbols = resolve_universe()
        if _UNIVERSE_ERROR:
            raise RuntimeError(f"universe resolution failed ({_UNIVERSE_ERROR[0]})")
        if not symbols:
            print("  [social-fold] empty universe — nothing to do")
        else:
            print(f"  Universe: {len(symbols)} symbols")

            from db_adapter import _get_conn
            conn = _get_conn()
            rows = latest_sentiment(conn, symbols)
            print(f"  Sentiment rows within window: {len(rows)}")

            for r in rows:
                sym = str(r.get("symbol") or "").upper()
                try:
                    from intelligence_entity_manager import upsert_entity
                    if upsert_entity(conn, sym, "market", _fields(r), source="social_sync"):
                        folded += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    print(f"  [social-fold] {sym} fold error: {e}")

            try:
                from lib.data_source_report import report_source
                report_source("social", folded > 0, rows=folded,
                              error=None if folded else "0 symbols folded (no fresh sentiment)")
            except Exception:
                pass
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="sync_social_to_intelligence.py", error=f"{type(exc).__name__}: {exc}")
        raise

    print(f"  Folded: {folded} symbols")
    print("[social-fold] complete (apply=True)")
    rc = 1 if rows and folded == 0 else 0
    lr.write_lane_receipt(LANE_ID, ok=rc == 0, exit_code=rc, started_at=started,
                          script="sync_social_to_intelligence.py",
                          summary={"universe": len(symbols), "rows": len(rows), "folded": folded,
                                   "failed": failed})
    return rc


if __name__ == "__main__":
    sys.exit(main())
