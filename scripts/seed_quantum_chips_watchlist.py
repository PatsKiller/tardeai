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
            cur.execute(
                "UPDATE watch_directives SET label=%s, rationale=%s, updated_at=NOW() WHERE id=%s",
                (new_label, RATIONALE, did),
            )
        return did, False
    spec = {"symbol": symbol, "company": CHIPS_PUBLIC.get(symbol, symbol)}
    cur.execute(
        """INSERT INTO watch_directives
               (kind, label, spec, rationale, created_by, priority, trade_ai_enabled, hermes_enabled)
           VALUES ('ticker', %s, %s::jsonb, %s, 'operator', 'high', true, true)
           RETURNING id""",
        (LIST_LABEL, json.dumps(spec), RATIONALE),
    )
    return cur.fetchone()[0], True


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
                    cur.execute(
                        "UPDATE watch_directives SET last_serviced_at=NOW(), updated_at=NOW() WHERE id=%s",
                        (did,),
                    )
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