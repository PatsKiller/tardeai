#!/usr/bin/env python3
"""market_regime_collector.py — Collect regime indicators from available local sources.

Usage:
    .venv/bin/python scripts/market_regime_collector.py --dry-run --json
    .venv/bin/python scripts/market_regime_collector.py --apply --json
"""

import argparse, json, os, sys, uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
_ENV_KEYS = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")


def _load_env():
    from dotenv import dotenv_values
    values = dotenv_values(PROJECT_ROOT / ".env")
    for name in _ENV_KEYS:
        if values.get(name) is not None:
            os.environ.setdefault(name, values[name])


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


def _uid(p="IND_"):
    return f"{p}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _get_conn():
    from session13_db import get_conn

    return get_conn()


INDEX_SYMBOLS = ["SPY", "QQQ", "IWM", "DIA"]
SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU"]


def collect_scan_based_indicators(conn, snapshot_id):
    """Use trade_ai_scans as a breadth/activity proxy."""
    cur = conn.cursor()
    indicators = []

    # Scan breadth: how many symbols scanned recently
    cur.execute(
        "SELECT COUNT(DISTINCT symbol), COUNT(*) FROM trade_ai_scans WHERE scanned_at > now() - interval '24 hours'"
    )
    row = cur.fetchone()
    symbols_24h, scans_24h = row[0], row[1]
    indicators.append(
        {
            "indicator_id": _uid(),
            "snapshot_id": snapshot_id,
            "indicator_key": "scan_breadth_24h",
            "indicator_group": "breadth",
            "value": symbols_24h,
            "signal": "broad" if symbols_24h > 50 else ("narrow" if symbols_24h > 10 else "missing"),
            "freshness_seconds": 86400,
            "source_key": "trade_ai_scans",
        }
    )

    # Score distribution as momentum proxy
    cur.execute(
        "SELECT AVG(score), STDDEV(score) FROM trade_ai_scans WHERE scanned_at > now() - interval '24 hours' AND score IS NOT NULL"
    )
    row = cur.fetchone()
    avg_score = _f(row[0]) if row[0] else None
    if avg_score:
        signal = "bullish" if avg_score > 60 else ("bearish" if avg_score < 40 else "neutral")
        indicators.append(
            {
                "indicator_id": _uid(),
                "snapshot_id": snapshot_id,
                "indicator_key": "scan_score_avg",
                "indicator_group": "index",
                "value": round(avg_score, 1),
                "signal": signal,
                "source_key": "trade_ai_scans",
            }
        )

    # Gap distribution as volatility proxy
    cur.execute(
        "SELECT AVG(ABS(gap_pct)), STDDEV(gap_pct) FROM trade_ai_scans WHERE scanned_at > now() - interval '24 hours' AND gap_pct IS NOT NULL"
    )
    row = cur.fetchone()
    avg_gap = _f(row[0]) if row[0] else None
    if avg_gap:
        signal = "high_vol" if avg_gap > 3.0 else ("low_vol" if avg_gap < 1.0 else "neutral")
        indicators.append(
            {
                "indicator_id": _uid(),
                "snapshot_id": snapshot_id,
                "indicator_key": "gap_volatility_proxy",
                "indicator_group": "volatility",
                "value": round(avg_gap, 2),
                "signal": signal,
                "source_key": "trade_ai_scans",
            }
        )

    # Source health as data quality indicator
    cur.execute("SELECT source_key, status, degraded FROM data_source_health WHERE source_key='finviz'")
    row = cur.fetchone()
    if row:
        indicators.append(
            {
                "indicator_id": _uid(),
                "snapshot_id": snapshot_id,
                "indicator_key": "finviz_health",
                "indicator_group": "source_health",
                "value_text": row[1],
                "signal": "risk_on" if row[1] == "healthy" else "risk_off",
                "source_key": "data_source_health",
            }
        )

    # News sentiment proxy
    cur.execute(
        "SELECT AVG(relevance_score) FROM news_articles WHERE created_at > now() - interval '24 hours' AND relevance_score IS NOT NULL"
    )
    row = cur.fetchone()
    if row[0]:
        indicators.append(
            {
                "indicator_id": _uid(),
                "snapshot_id": snapshot_id,
                "indicator_key": "news_sentiment_proxy",
                "indicator_group": "news",
                "value": round(_f(row[0]), 2),
                "signal": "neutral",
                "source_key": "news_articles",
            }
        )

    return indicators


def collect_volatility_complex(conn, snapshot_id, now=None, cfg=None):
    """The volatility complex, read from the stores (LQ-20261107-940/969, design WU-6).

    Replaces the Yahoo chart path entirely: ``^VIX ^VIX9D ^VIX3M ^VVIX ^SKEW ^VXN`` come from the Schwab off-hours
    lane's ``market_quotes_extended`` rows, and FRED's published VIXCLS/VXNCLS closes cover only the keys no Schwab
    row supplied. Returns ``(indicators, missing, summary)``; every absent, stale, banned-source or non-positive
    value is named in ``missing`` and never written as a zero.
    """
    from lib.market_regime import vix_complex

    cfg = cfg or vix_complex.load_config()
    return vix_complex.collect(conn, snapshot_id, now or datetime.now(timezone.utc), cfg, lambda: _uid())


def collect_market_session(snapshot_id):
    """Collect market session indicator."""
    from market_session import current_market_session

    session = current_market_session()
    return {
        "indicator_id": _uid(),
        "snapshot_id": snapshot_id,
        "indicator_key": "market_session",
        "indicator_group": "index",
        "value_text": session,
        "signal": "risk_on" if session == "regular" else "neutral",
        "source_key": "market_session",
    }


def save_indicators(conn, indicators, dry_run=True):
    if dry_run:
        return
    cur = conn.cursor()
    for ind in indicators:
        cur.execute(
            """
            INSERT INTO market_regime_indicators
                (indicator_id, snapshot_id, indicator_key, indicator_group,
                 value, value_text, signal, weight, freshness_seconds, source_key, payload)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (indicator_id) DO NOTHING
        """,
            [
                ind["indicator_id"],
                ind.get("snapshot_id"),
                ind["indicator_key"],
                ind.get("indicator_group"),
                ind.get("value"),
                ind.get("value_text"),
                ind.get("signal"),
                ind.get("weight", 1.0),
                ind.get("freshness_seconds"),
                ind.get("source_key"),
                json.dumps(ind.get("payload", {}), default=str),
            ],
        )
    conn.commit()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Market Regime Collector", allow_abbrev=False)
    parser.add_argument("--dry-run", action="store_true",
                        help="structural plan; never opens the DB, never writes (wins over --apply)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--symbols")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    # Explicit --dry-run is the structural plan the refactor wave 1 train pinned: no DB session at all
    # (tests/test_refactor_w1_regime_collector_20261010.py). The read-only PREVIEW below (no --apply) is the
    # dry run that exercises the real stores, including the rebuilt volatility complex.
    if args.dry_run:
        print("DRY-RUN market-regime-collector: would collect regime indicators and persist "
              "market_regime_indicators; no DB, network or writes performed")
        return 0
    # --dry-run wins: a dispatcher passing both must never write (AGENTS.md §6).
    dry_run = args.dry_run or not args.apply
    started_at = _now_iso()
    snapshot_id = _uid("SNAP_")
    conn = None
    try:
        _load_env()
        conn = _get_conn()
        if dry_run:
            from lib.lane_last_receipt import enforce_readonly

            enforce_readonly(conn)  # legacy preview: the server refuses any write
        indicators = collect_scan_based_indicators(conn, snapshot_id)
        indicators.append(collect_market_session(snapshot_id))
        now = datetime.now(timezone.utc)
        try:
            vol_inds, missing, vol_summary = collect_volatility_complex(conn, snapshot_id, now)
        except Exception as exc:  # noqa: BLE001 — the vol complex is additive; it can never stop the classifier
            print(f"[regime_collector] vol complex failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            vol_inds, missing, vol_summary = [], [f"vol_complex_unavailable:{type(exc).__name__}"], {}
        indicators.extend(vol_inds)

        for sym in INDEX_SYMBOLS:
            missing.append(f"no_direct_quote_{sym}")

        out = {
            "mode": "dry_run" if dry_run else "applied",
            "snapshot_id": snapshot_id,
            "indicators_collected": len(indicators),
            "missing_data": missing,
            "stale_data": len(indicators) < 3,
            "volatility_complex": vol_summary,
        }
        if dry_run:
            out["would_write"] = {"table": "market_regime_indicators", "rows": len(indicators)}
            _emit(args, out, indicators)  # --json stays machine-readable: one JSON document, nothing before it
            return 0  # returns before save_indicators is reachable

        save_indicators(conn, indicators, dry_run=False)
        _receipt(
            ok=True,
            started_at=started_at,
            summary={
                "snapshot_id": snapshot_id,
                "indicators_collected": len(indicators),
                "stale_data": out["stale_data"],
                "missing_data": missing,
                "volatility_complex": {"sources": vol_summary.get("sources"),
                                       "values": vol_summary.get("values")},
            },
        )
        _emit(args, out, indicators)
        return 0
    except Exception as exc:
        if not dry_run:  # a failed real run leaves a failed receipt (ok_at kept), then exits non-zero
            _receipt(
                ok=False,
                started_at=started_at,
                error=f"{type(exc).__name__}: {exc}",
                summary={"snapshot_id": snapshot_id},
            )
        raise
    finally:
        if conn is not None:
            conn.close()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _emit(args, out, indicators):
    if args.json:
        out["indicators"] = [{k: v for k, v in i.items() if k != "payload"} for i in indicators]
        print(json.dumps(out, indent=2, default=str))
    else:
        extra = f" — would write {len(indicators)} rows to market_regime_indicators" if out["mode"] == "dry_run" else ""
        print(f"Collected {out['indicators_collected']} indicators ({out['mode']}){extra}")


def _receipt(**kw):
    """Real-run receipt (data/runtime/market_regime_collector_last.json, ok_at on success only)."""
    from lib.lane_last_receipt import write_receipt

    # Keep the legacy filename for existing consumers and add the canonical lane-id receipt.
    kw.setdefault("exit_code", 0 if kw.get("ok") else 1)
    for name in ("market_regime_collector", "market-regime-collector"):
        write_receipt(name, **kw)


if __name__ == "__main__":
    sys.exit(main())
