#!/usr/bin/env python3
"""Seed CHIPS Act / White House quantum equity-stake names on the operator watchlist.

Commerce/NIST May 21, 2026 LOIs ($2.013B, minority equity stakes). Public tickers only:
  GFS (GlobalFoundries), IBM, QBTS (D-Wave), RGTI (Rigetti)

Creates ticker watch_directives labeled "White House Quantum Computing" and promotes each
symbol into watchlist_items so WatchlistHub List filter surfaces the tag.

  python3 scripts/seed_quantum_chips_watchlist.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.writers.watch_directives_writer import (  # noqa: E402  (the store's single write module)
    touch_watch_directive_serviced, update_watch_directive, write_watch_directives)

LIST_LABEL = "White House Quantum Computing"
RATIONALE = (
    "US CHIPS Act quantum LOI (Commerce/NIST, May 21 2026): minority federal equity stake. "
    "White House quantum innovation EO (Jun 22 2026). Operator macro watch — public names only."
)

# symbol -> company (for provenance detail)
CHIPS_PUBLIC = {
    "GFS": "GlobalFoundries",
    "IBM": "IBM",
    "QBTS": "D-Wave Quantum",
    "RGTI": "Rigetti Computing",
}


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _upsert_directive(cur, symbol: str) -> tuple[int, bool]:
    """Return (directive_id, created). Reuse active ticker directive if present."""
    cur.execute(
        """SELECT id, label FROM watch_directives
           WHERE kind='ticker' AND status='active' AND upper(spec->>'symbol')=%s
           ORDER BY id LIMIT 1""",
        (symbol,),
    )
    row = cur.fetchone()
    if row:
        did, label = row[0], row[1] or ""
        if LIST_LABEL not in label:
            new_label = LIST_LABEL if (not label or label.upper() == symbol) else f"{label} · {LIST_LABEL}"
            update_watch_directive(cur, did, source="seed_quantum_chips_watchlist",
                                   label=new_label, rationale=RATIONALE)
        return did, False
    spec = {"symbol": symbol, "company": CHIPS_PUBLIC.get(symbol, symbol)}
    rc = write_watch_directives(cur, [{
        "kind": "ticker", "label": LIST_LABEL, "spec": spec, "rationale": RATIONALE,
        "created_by": "operator", "priority": "high", "trade_ai_enabled": True, "hermes_enabled": True,
    }], source="seed_quantum_chips_watchlist")
    if rc.directive_id is None:
        raise RuntimeError(f"watch_directives write rejected: {rc.rows_rejected}")
    return rc.directive_id, bool(rc.ids)


def run(apply: bool = False) -> dict:
    import directive_promotion as dp

    report = {"mode": "APPLIED" if apply else "DRY-RUN", "label": LIST_LABEL, "symbols": []}
    conn = _conn()
    try:
        for symbol in CHIPS_PUBLIC:
            entry = {"symbol": symbol, "directive_id": None, "created": False, "promotion": None}
            if apply:
                cur = conn.cursor()
                did, created = _upsert_directive(cur, symbol)
                conn.commit()
                entry["directive_id"] = did
                entry["created"] = created
                try:
                    res = dp.promote_directive_lead(
                        symbol, did, f"seed:{LIST_LABEL}", "operator", conn=conn, auto=True
                    )
                    entry["promotion"] = res.get("status")
                    touch_watch_directive_serviced(cur, did, source="seed_quantum_chips_watchlist")
                    conn.commit()
                except Exception as e:
                    entry["promotion"] = f"ERROR:{e}"
            else:
                cur = conn.cursor()
                cur.execute(
                    """SELECT id, label FROM watch_directives
                       WHERE kind='ticker' AND status='active' AND upper(spec->>'symbol')=%s""",
                    (symbol,),
                )
                ex = cur.fetchone()
                entry["directive_id"] = ex[0] if ex else None
                entry["would_create"] = ex is None
            report["symbols"].append(entry)
    finally:
        conn.close()
    print(json.dumps(report, indent=2))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Persist directives and promote to watchlist")
    run(apply=ap.parse_args().apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())