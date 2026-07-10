#!/usr/bin/env python3
"""Cross-audit Ross Cameron daily picks vs TradeAI scans and presentation.

  python3 scripts/warrior_tradeai_audit.py --since 2026-07-06 --until 2026-07-10
  python3 scripts/warrior_tradeai_audit.py --since 2026-07-06 --until 2026-07-10 --csv data/audit/pilot.csv
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    import psycopg2
    import psycopg2.extras
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
    return conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _load_catalog(since: date, until: date) -> list[dict]:
    conn, cur = _get_conn()
    try:
        cur.execute(
            """
            SELECT trade_date, video_id, video_title, symbols_traded, winners, net_pnl_usd
            FROM ross_daily_catalog
            WHERE trade_date BETWEEN %s AND %s
            ORDER BY trade_date, video_id
            """,
            (since, until),
        )
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        conn.close()
        return []
    finally:
        conn.close()


def _resolve_scan_symbol(trade_date: date, symbol: str) -> dict:
    """P2-2: map catalog symbol to scan-universe symbol (e.g. VRX → VRAX)."""
    import sys as _sys_ra
    _lib = PROJECT_ROOT / "scripts" / "lib"
    if str(_lib) not in _sys_ra.path:
        _sys_ra.path.insert(0, str(_lib))
    from ticker_alias import resolve_symbol

    return resolve_symbol(symbol, PROJECT_ROOT, trade_date=trade_date)


def _scan_row(cur, trade_date: date, symbol: str) -> tuple[dict | None, dict]:
    """Return (scan_row, alias_resolution). Tries direct symbol then alias."""
    resolution = _resolve_scan_symbol(trade_date, symbol)
    lookup = resolution.get("resolved_symbol") or symbol.upper()

    cur.execute(
        """
        SELECT symbol, decision, score, rvol, gap_pct, float_m, price, change_pct,
               disqualified, disqualification_reason, scanned_at,
               source, run_label,
               awareness_status, setup_class, symbol_candidate, symbol_alias_confidence,
               manual_review_required, operator_pill, operator_color_token
        FROM trade_ai_scans
        WHERE run_date = %s AND UPPER(symbol) = %s
        ORDER BY score DESC NULLS LAST, scanned_at ASC
        LIMIT 1
        """,
        (trade_date, lookup.upper()),
    )
    r = cur.fetchone()
    if not r:
        return None, resolution
    row = dict(r)
    if resolution.get("symbol_candidate"):
        row.setdefault("symbol_candidate", resolution["symbol_candidate"])
        row.setdefault("symbol_alias_confidence", resolution.get("confidence"))
    return row, resolution


def _any_scan(cur, trade_date: date, symbol: str) -> bool:
    resolution = _resolve_scan_symbol(trade_date, symbol)
    lookup = resolution.get("resolved_symbol") or symbol.upper()
    cur.execute(
        "SELECT 1 FROM trade_ai_scans WHERE run_date=%s AND UPPER(symbol)=%s LIMIT 1",
        (trade_date, lookup.upper()),
    )
    return cur.fetchone() is not None


def _is_top_gainer(trade_date: date, symbol: str) -> bool:
    """True if symbol was #1-3 Finviz prime_setup gainer that day (awareness lane)."""
    pattern = str(PROJECT_ROOT / "data" / "raw" / "finviz" / str(trade_date) / "**" / "prime_setups_*.csv")
    files = sorted(glob.glob(pattern, recursive=True))
    if not files:
        return False
    import csv as csvmod
    sym = symbol.upper()
    try:
        with open(files[-1], newline="", encoding="utf-8", errors="replace") as f:
            for i, row in enumerate(csvmod.DictReader(f)):
                if i >= 3:
                    break
                tick = (row.get("Ticker") or row.get("ticker") or "").strip().upper()
                if tick == sym:
                    return True
    except Exception:
        pass
    return False


def _finviz_row(trade_date: date, symbol: str, scan: dict | None = None) -> dict | None:
    """P5: nearest prime_setups snapshot to scan time; fallback to scan row fields."""
    import sys as _sys_fv
    _lib = PROJECT_ROOT / "scripts" / "lib"
    if str(_lib) not in _sys_fv.path:
        _sys_fv.path.insert(0, str(_lib))
    from finviz_snapshot import lookup_finviz_symbol

    ref = None
    if scan and scan.get("scanned_at"):
        ref = scan["scanned_at"]
        if hasattr(ref, "replace"):
            try:
                ref = ref.replace(tzinfo=None)
            except Exception:
                pass
    return lookup_finviz_symbol(
        PROJECT_ROOT, trade_date, symbol, reference=ref, scan_row=scan,
    )


def _run_summary_go(trade_date: date, symbol: str) -> bool:
    sym = symbol.upper()
    base = PROJECT_ROOT / "reports" / str(trade_date)
    if not base.exists():
        return False
    for p in sorted(base.glob("*/run_summary.json")):
        try:
            d = json.loads(p.read_text())
            for t in d.get("go_tickers") or d.get("tickers") or []:
                if str(t.get("symbol", "")).upper() == sym and (t.get("decision") or "").upper() == "GO":
                    return True
        except Exception:
            continue
    return False


def _top30_presented(cur, trade_date: date, symbol: str) -> bool:
    """Symbol in top-30 by score from trade_ai_scans that day."""
    sym = symbol.upper()
    cur.execute(
        """
        SELECT symbol FROM (
            SELECT UPPER(symbol) AS symbol, MAX(score) AS best_score
            FROM trade_ai_scans WHERE run_date = %s
            GROUP BY UPPER(symbol)
            ORDER BY best_score DESC NULLS LAST
            LIMIT 30
        ) t WHERE symbol = %s
        """,
        (trade_date, sym),
    )
    return cur.fetchone() is not None


def audit(since: date, until: date) -> tuple[list[dict], dict]:
    catalog = _load_catalog(since, until)
    conn, cur = _get_conn()

    rows: list[dict] = []
    ross_symbols: set[tuple[date, str]] = set()

    for cat in catalog:
        td = cat["trade_date"]
        if isinstance(td, datetime):
            td = td.date()
        for sym in cat.get("symbols_traded") or []:
            ross_symbols.add((td, str(sym).upper()))

    # If no catalog yet, fall back to GO symbols from trade_ai as pilot baseline
    if not ross_symbols:
        cur.execute(
            """
            SELECT DISTINCT run_date, UPPER(symbol) AS symbol FROM trade_ai_scans
            WHERE run_date BETWEEN %s AND %s AND decision = 'GO'
            ORDER BY run_date, UPPER(symbol)
            """,
            (since, until),
        )
        for r in cur.fetchall():
            ross_symbols.add((r["run_date"], r["symbol"]))

    for trade_date, symbol in sorted(ross_symbols):
        scan, alias = _scan_row(cur, trade_date, symbol)
        upgraded = _apply_awareness_upgrades(scan) if scan else None
        fv = _finviz_row(trade_date, symbol, scan) or _finviz_row(
            trade_date, alias.get("resolved_symbol") or symbol, scan,
        )
        scanned = _any_scan(cur, trade_date, symbol)
        decision = upgraded.get("decision") if upgraded else None
        rows.append({
            "trade_date": str(trade_date),
            "symbol": symbol,
            "scan_symbol": alias.get("resolved_symbol") if alias.get("symbol_candidate") else symbol,
            "symbol_candidate": alias.get("symbol_candidate") or "",
            "alias_confidence": alias.get("confidence") if alias.get("symbol_candidate") else "",
            "alias_method": alias.get("method") if alias.get("symbol_candidate") else "",
            "ross_in_catalog": any(
                c["trade_date"] == trade_date and symbol in (c.get("symbols_traded") or [])
                for c in catalog
            ),
            "we_scanned": scanned,
            "our_decision": decision,
            "our_score": scan.get("score") if scan else None,
            "our_rvol": scan.get("rvol") if scan else None,
            "our_gap_pct": scan.get("gap_pct") if scan else None,
            "our_change_pct": scan.get("change_pct") if scan else None,
            "disqualified": scan.get("disqualified") if scan else None,
            "dq_reason": (scan.get("disqualification_reason") or "")[:80] if scan else "",
            "top_gainer_awareness": _is_top_gainer(trade_date, symbol),
            "finviz_rvol": fv.get("rvol") if fv else None,
            "finviz_gap": fv.get("gap_pct") if fv else None,
            "finviz_change": fv.get("change_pct") if fv else None,
            "in_run_go": _run_summary_go(trade_date, symbol),
            "presented_top30": _top30_presented(cur, trade_date, symbol),
            "gap_reason": _classify_gap(upgraded, fv),
        })

    conn.close()

    n = len(rows)
    scanned_n = sum(1 for r in rows if r["we_scanned"])
    go_n = sum(1 for r in rows if (r.get("our_decision") or "").upper() == "GO")
    presented_n = sum(1 for r in rows if r["presented_top30"] or r["in_run_go"])
    ross_n = sum(1 for r in rows if r["ross_in_catalog"])

    summary = {
        "since": str(since),
        "until": str(until),
        "catalog_days": len(catalog),
        "symbol_days": n,
        "ross_catalog_hits": ross_n,
        "symbol_recall_pct": round(100 * scanned_n / n, 1) if n else 0,
        "go_recall_pct": round(100 * go_n / n, 1) if n else 0,
        "presentation_pct": round(100 * presented_n / n, 1) if n else 0,
        "gap_breakdown": _gap_counts(rows),
    }
    return rows, summary


def _apply_awareness_upgrades(scan: dict) -> dict:
    """Use persisted awareness fields when present; else mirror API-layer upgrades."""
    if not scan:
        return scan
    row = dict(scan)
    if row.get("awareness_status") and (row.get("decision") or "").upper() == "MANUAL_REVIEW":
        return row
    import sys as _sys_au
    _lib = PROJECT_ROOT / "scripts" / "lib"
    if str(_lib) not in _sys_au.path:
        _sys_au.path.insert(0, str(_lib))
    from squeeze_manual_review import attach_squeeze_manual_tags
    from micro_float_manual_review import attach_micro_float_manual_tags
    from high_rvol_manual_review import attach_high_rvol_manual_tags
    from low_price_manual_review import attach_low_price_manual_tags
    from catalyst_exception import attach_catalyst_exception_tags

    attach_squeeze_manual_tags([row])
    attach_micro_float_manual_tags([row])
    attach_high_rvol_manual_tags([row])
    attach_low_price_manual_tags([row])
    attach_catalyst_exception_tags([row])
    return row


def _classify_gap(scan: dict | None, fv: dict | None) -> str:
    if not scan:
        return "DATA_MISSING"
    scan = _apply_awareness_upgrades(scan)
    dec = (scan.get("decision") or "").upper()
    if dec == "MANUAL_REVIEW":
        if scan.get("awareness_status") == "SQUEEZE" or scan.get("setup_class") == "squeeze":
            return "SQUEEZE_MANUAL_REVIEW"
        if scan.get("awareness_status") == "HIGH_RVOL" or scan.get("setup_class") == "high_rvol_runner":
            return "HIGH_RVOL_MANUAL_REVIEW"
        if scan.get("awareness_status") == "MICRO_FLOAT" or scan.get("setup_class") == "micro_float_runner":
            return "MICRO_FLOAT_MANUAL_REVIEW"
        if scan.get("awareness_status") == "LOW_PRICE" or scan.get("setup_class") == "low_price_runner":
            return "LOW_PRICE_MANUAL_REVIEW"
        if (
            scan.get("awareness_status") == "MOMENTUM_RUNNER"
            or scan.get("setup_class") == "momentum_runner"
        ):
            return "CATALYST_EXCEPTION_MANUAL_REVIEW"
        return "SQUEEZE_MANUAL_REVIEW"
    if scan.get("disqualified"):
        return "DQ_" + (scan.get("disqualification_reason") or "unknown")[:40]
    if dec != "GO":
        return "METHODOLOGY_NO_GO"
    if not fv:
        return "NO_FINVIZ_SNAPSHOT"
    return "ALIGNED"


def _gap_counts(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        g = r.get("gap_reason") or "unknown"
        key = g.split(":")[0][:30] if ":" in g else g[:30]
        counts[key] = counts.get(key, 0) + 1
    return counts


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", default=None)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    since = date.fromisoformat(args.since)
    until = date.fromisoformat(args.until) if args.until else date.today()
    rows, summary = audit(since, until)
    if args.csv:
        write_csv(Path(args.csv), rows)
        print(f"Wrote {len(rows)} rows → {args.csv}")
    print(json.dumps(summary, indent=2))
    if args.json:
        print(json.dumps(rows, indent=2, default=str))


if __name__ == "__main__":
    main()