#!/usr/bin/env python3
"""run_sec_form4_momentum_context.py — P0-2: scheduled SEC/Form 4 momentum catalyst context.

For the momentum-relevant symbols currently in play (recent micro-float scan rows), refresh SEC Form 4
filings (reusing the proven sec_data_ingest) and derive per-symbol insider-context (direction, recent
open-market buy, confidence, evidence URL, lineage). The context is a SUPPORTING catalyst-evidence
input — it can contribute the Social Scout `catalyst_evidence` pillar when recent + relevant, but can
NEVER create GO, bypass route/risk/validation gates, or trigger a trade.

Read-only / source-ingestion only. No broker writes. Default DRY-RUN.

    python3 scripts/run_sec_form4_momentum_context.py --dry-run     # report only (default)
    python3 scripts/run_sec_form4_momentum_context.py --apply       # refresh Form 4 + write context artifact
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sec_form4_source_maturity as sm  # noqa: E402

CONTEXT_ARTIFACT = ROOT / "data" / "runtime" / "sec_form4_momentum_context_latest.json"
MAX_SYMBOLS = 40
LANE_ID = "run-sec-form4-momentum-context"
_LAST_COUNTS = {}


def _momentum_symbols(conn, days: int = 2) -> list:
    """Recent micro-float momentum-relevant symbols from trade_ai_scans (read-only)."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT symbol FROM trade_ai_scans
            WHERE scanned_at > NOW() - INTERVAL '%s days'
              AND (float_m IS NULL OR float_m <= 20)
            ORDER BY symbol LIMIT %s
        """ % (int(days), MAX_SYMBOLS))
        return [r[0] for r in cur.fetchall()]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return []


def _form4_rows(conn, symbol: str) -> list:
    try:
        cur = conn.cursor()
        cur.execute("""SELECT transaction_type, filing_date, total_value, sec_url
                       FROM sec_form4 WHERE symbol=%s ORDER BY filing_date DESC LIMIT 8""", (symbol,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return []


def build_context(conn, symbols: list, refresh: bool) -> dict:
    """Derive per-symbol insider context. refresh=True re-ingests Form 4 first (reuses sec_data_ingest)."""
    refreshed = 0
    if refresh and symbols:
        try:
            from sec_data_ingest import ingest_form4
            res = ingest_form4(symbols[:MAX_SYMBOLS], limit=3)
            refreshed = (res or {}).get("inserted", 0) if isinstance(res, dict) else 0
        except Exception as e:
            refreshed = f"refresh_skipped: {str(e).splitlines()[0][:60]}"
    now = datetime.now(timezone.utc).date()
    contexts = []
    relevant = 0
    for sym in symbols:
        rows = _form4_rows(conn, sym)
        ctx = sm.classify_insider_context(rows, now=now)
        if ctx["catalyst_relevant"]:
            relevant += 1
        contexts.append({
            "symbol": sym,
            "direction": ctx["direction"],
            "recent_insider_buy": ctx["recent_insider_buy"],
            "catalyst_relevant": ctx["catalyst_relevant"],
            "confidence": ctx["confidence"],
            "latest_filing_date": ctx["latest_filing_date"],
            "evidence_url": ctx["evidence_url"],
            # lineage — a stable per-symbol source trace key (no sensitive raw blobs persisted).
            "source_trace_id": f"secf4-{now.isoformat()}-{sym}",
        })
    return {"refreshed": refreshed, "symbols": len(symbols),
            "catalyst_relevant_symbols": relevant, "contexts": contexts}


def main() -> int:
    ap = argparse.ArgumentParser(description="SEC/Form 4 momentum catalyst context (supporting evidence only)", allow_abbrev=False)
    ap.add_argument("--dry-run", action="store_true", help="report only (default)")
    ap.add_argument("--apply", action="store_true", help="refresh Form 4 + write the context artifact")
    ap.add_argument("--limit", type=int, default=MAX_SYMBOLS)
    args = ap.parse_args()
    apply = args.apply and not args.dry_run

    rep = {"tool": "run_sec_form4_momentum_context", "generated_at": datetime.now().isoformat(),
           "dry_run": not apply}
    conn = None
    try:
        from db_adapter import get_connection
        conn = get_connection()
    except Exception as e:
        rep.update(status="WARN", note=f"db unavailable: {str(e).splitlines()[0][:80]}")
        print(json.dumps(rep, default=str))
        return 1

    symbols = _momentum_symbols(conn)[: args.limit]
    body = build_context(conn, symbols, refresh=apply)
    rep.update(body)
    rep["maturity"] = {k: sm.build(30)[k] for k in ("after", "readiness", "before")}
    rep["safety_note"] = ("Read-only / source-ingestion only. SEC/Form 4 contributes catalyst_evidence "
                          "only when a recent open-market insider BUY is relevant; it can NEVER create GO, "
                          "bypass gates, or trigger a trade. No live broker writes. Operator/2FA untouched.")
    if apply:
        try:
            CONTEXT_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
            CONTEXT_ARTIFACT.write_text(json.dumps(rep, indent=2, default=str))
            rep["artifact"] = str(CONTEXT_ARTIFACT.relative_to(ROOT))
        except Exception as e:
            rep["artifact_error"] = str(e)[:80]
    failed = bool(rep.get("artifact_error")) or (apply and isinstance(body.get("refreshed"), str))
    _LAST_COUNTS.update(symbols=body["symbols"], catalyst_relevant_symbols=body["catalyst_relevant_symbols"],
                        refreshed=body["refreshed"] if isinstance(body["refreshed"], int) else 0,
                        refresh_failed=isinstance(body.get("refreshed"), str))
    rep["status"] = "FAIL" if failed else rep.get("status", "PASS")
    print(json.dumps(rep, default=str))
    return 1 if failed else 0


def cli(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="SEC/Form 4 context", allow_abbrev=False)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=MAX_SYMBOLS)
    args = parser.parse_args(argv)
    if args.dry_run:
        print(f"DRY-RUN {LANE_ID}: would read up to {args.limit} momentum symbols, refresh SEC Form 4 "
              "and write supporting context; no DB, provider or writes")
        return 0
    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    _LAST_COUNTS.clear()
    previous = sys.argv
    sys.argv = ["run_sec_form4_momentum_context.py", *argv]
    try:
        rc = main()
    except Exception as exc:
        if args.apply:
            write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                               script="run_sec_form4_momentum_context.py", error=type(exc).__name__)
        raise
    finally:
        sys.argv = previous
    if args.apply:
        write_lane_receipt(LANE_ID, ok=rc == 0, exit_code=rc, started_at=started,
                           script="run_sec_form4_momentum_context.py", summary=_LAST_COUNTS)
    return rc


if __name__ == "__main__":
    raise SystemExit(cli())
