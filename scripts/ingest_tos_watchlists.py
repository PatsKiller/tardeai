#!/usr/bin/env python3
"""ingest_tos_watchlists.py — ingest thinkorswim (ToS) watchlist exports.

Schwab's Trader API has NO watchlist endpoint (confirmed live 2026-06-10) — this is the fallback route.
Drop ToS-exported watchlist CSV/TXT files into imports/tos_watchlists/. Each file = one watchlist (name from
the filename). Reconciles membership with add/remove DATE tracking (tos_watchlist_members + tos_watchlist_events)
and mirrors active members into watchlist_items (source='tos_watchlist', bucket = watchlist name). Idempotent.

Management (rename / match-strategy / notes) is via /api/v2/tos-watchlists (api_v2). Read-only of the files.

  python3 scripts/ingest_tos_watchlists.py [--apply]
"""

import sys as _f09_sys

if __name__ == "__main__" and "--dry-run" in _f09_sys.argv[1:]:
    # n8n onboarding F09 (operator N8N Cutover Decision 2026-10-15; staged under AGENTS.md §23.14 until 12.0.0 is
    # ratified): --dry-run is OFFLINE and wins over every live flag. It returns here, before any .env load, DB,
    # broker, LLM, network or sender import and before any file write, and it makes NO broker call, not even a read.
    # It prints the plan and one LaneOutput@v1 line on stderr: produced 0, empty_reason dry_run
    # (offline plan; the live work's inputs are not read). Proof: tests/test_onboard_f09_b5_20261015.py.
    import os as _f09_os

    _f09_sys.path.insert(0, _f09_os.path.dirname(_f09_os.path.abspath(__file__)))
    from lib.lane_output import emit as _f09_emit, output_block as _f09_block

    _f09_lane = "ingest-tos-watchlists"
    _f09_would = (
        "read thinkorswim watchlist exports from imports/tos_watchlists/ and, with --apply, reconcile "
        "membership into tos_watchlist_members / tos_watchlist_events"
    )
    print(f"DRY-RUN {_f09_lane}: would {_f09_would}; argv={_f09_sys.argv[1:]!r}; dry-run wins over live flags; "
          "offline plan only; "
          "nothing read from env/DB/broker/network, no model call, no send, no file write")
    _f09_emit(_f09_lane, "dry_run", _f09_block(produced=0, attempted=0, empty_reason="dry_run",
                                               unit="ToS watchlist files ingested"))
    raise SystemExit(0)
import argparse, csv, json, re, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
INBOUND = PROJECT_ROOT / "imports" / "tos_watchlists"
SYM_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}(\.[A-Z]{1,2})?$")
SKIP = {"SYMBOL", "DESCRIPTION", "LAST", "NET", "CHNG", "CHANGE", "VOLUME", "BID", "ASK", "NA", "CASH",
        "OPEN", "HIGH", "LOW", "CLOSE", "MARK", "QTY"}


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _parse_file(p):
    """Extract uppercase symbols from a ToS watchlist export (CSV with a Symbol column, or a flat list)."""
    try:
        rows = list(csv.reader(p.read_text(errors="ignore").splitlines()))
    except Exception:
        return []
    sym_col = None
    for r in rows[:6]:
        for i, cell in enumerate(r):
            if cell.strip().lower() == "symbol":
                sym_col = i
                break
        if sym_col is not None:
            break
    out, seen = [], set()
    for r in rows:
        cells = [r[sym_col]] if (sym_col is not None and len(r) > sym_col) else r
        for cell in cells:
            tok = (cell or "").strip().upper()
            if SYM_RE.match(tok) and tok not in SKIP and tok not in seen:
                seen.add(tok); out.append(tok)
    return out


def run(apply=False):
    conn = _conn(); cur = conn.cursor()
    files = sorted(list(INBOUND.glob("*.csv")) + list(INBOUND.glob("*.txt")))
    report = {"mode": "APPLIED" if apply else "DRY-RUN", "files": len(files), "watchlists": []}
    for p in files:
        name = p.stem
        syms = _parse_file(p)
        if not syms:
            continue
        entry = {"name": name, "file": p.name, "symbols": len(syms), "added": 0, "removed": 0}
        if apply:
            cur.execute("""INSERT INTO tos_watchlists (name, source_file, symbol_count, last_imported_at)
                           VALUES (%s,%s,%s,NOW())
                           ON CONFLICT (name) DO UPDATE SET source_file=EXCLUDED.source_file,
                             symbol_count=EXCLUDED.symbol_count, last_imported_at=NOW(), updated_at=NOW()
                           RETURNING id""", (name, p.name, len(syms)))
            wid = cur.fetchone()[0]
            cur.execute("SELECT symbol FROM tos_watchlist_members WHERE watchlist_id=%s AND removed_at IS NULL", (wid,))
            active = {r[0] for r in cur.fetchall()}
            newset = set(syms)
            for s in newset - active:                 # ADDED
                cur.execute("""INSERT INTO tos_watchlist_members (watchlist_id, symbol, added_at, removed_at)
                               VALUES (%s,%s,NOW(),NULL)
                               ON CONFLICT (watchlist_id, symbol) DO UPDATE SET removed_at=NULL, added_at=NOW()""", (wid, s))
                cur.execute("INSERT INTO tos_watchlist_events (watchlist_id, symbol, event) VALUES (%s,%s,'added')", (wid, s))
                entry["added"] += 1
            for s in active - newset:                 # REMOVED (date tracked)
                cur.execute("UPDATE tos_watchlist_members SET removed_at=NOW() WHERE watchlist_id=%s AND symbol=%s AND removed_at IS NULL", (wid, s))
                cur.execute("INSERT INTO tos_watchlist_events (watchlist_id, symbol, event) VALUES (%s,%s,'removed')", (wid, s))
                entry["removed"] += 1
            for s in syms:                            # mirror active members into the canonical watchlist
                cur.execute("""INSERT INTO watchlist_items (symbol, source, bucket, status, origin_system,
                                 updated_at, first_seen_at, last_seen_at)
                               VALUES (%s,'tos_watchlist',%s,'active','tos',NOW(),NOW(),NOW())
                               ON CONFLICT (symbol, source, COALESCE(bucket, '__none__')) DO UPDATE
                                 SET last_seen_at=NOW(), status='active'""", (s, name))
            conn.commit()
        report["watchlists"].append(entry)
    print(json.dumps(report, indent=2))
    return report


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    run(apply=ap.parse_args().apply)


if __name__ == "__main__":
    main()
