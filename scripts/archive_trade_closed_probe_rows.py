#!/usr/bin/env python3
"""Archive health-probe rows out of trade_closed (reconciliation 2026-10-05). Dry run by default.

Two rows on accounts 'health' / 'journal_check' (2026-08-07, no writer left in the code — a one-off probe)
were counted as trades: TRADING showed 167 trades (real: 166) and REALIZED included +$0.01. The KPI query
now excludes config/portfolio_positions.yaml `closed.test_accounts`; this moves the rows themselves to
trade_closed_archived_probe so no other reader can count them. Never deletes without archiving first:
copy → verify the copy → JSON backup → remove from trade_closed, in one transaction.

  archive_trade_closed_probe_rows.py            # dry run: print what would move
  archive_trade_closed_probe_rows.py --apply    # archive (writes a JSON backup first)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import portfolio_positions as pp  # noqa: E402

ARCHIVE_DDL = """CREATE TABLE IF NOT EXISTS trade_closed_archived_probe
                 (LIKE trade_closed INCLUDING DEFAULTS, archived_at TIMESTAMPTZ DEFAULT NOW(), archive_reason TEXT)"""


def find_rows(cur, accounts: list[str]) -> list[dict]:
    cur.execute("SELECT * FROM trade_closed WHERE account = ANY(%s) ORDER BY id", (accounts,))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    accounts = list(pp.load_closed_config()["test_accounts"])
    from db_adapter import get_connection  # type: ignore
    conn = get_connection()
    cur = conn.cursor()
    rows = find_rows(cur, accounts)
    plan = {"mode": "APPLY" if a.apply else "DRY-RUN", "accounts": accounts, "rows": len(rows),
            "ids": [r["id"] for r in rows],
            "pnl_total": round(sum(float(r.get("pnl") or 0) for r in rows), 2),
            "rows_detail": [{k: str(r.get(k)) for k in ("id", "account", "symbol", "open_date", "close_date",
                                                        "shares", "buy_price", "sell_price", "pnl")} for r in rows]}
    if not a.apply or not rows:
        conn.rollback()
        print(json.dumps(plan, indent=1))
        return 0
    backup = ROOT / "logs" / f"trade_closed_probe_rows_backup_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(json.dumps(rows, default=str, indent=1))
    cur.execute(ARCHIVE_DDL)
    cols = [c for c in rows[0].keys()]
    collist = ", ".join(cols)
    cur.execute(f"""INSERT INTO trade_closed_archived_probe ({collist}, archive_reason)
                    SELECT {collist}, %s FROM trade_closed WHERE id = ANY(%s)""",
                ("health probe row counted as a trade (reconciliation 2026-10-05)", plan["ids"]))
    cur.execute("SELECT count(*) FROM trade_closed_archived_probe WHERE id = ANY(%s)", (plan["ids"],))
    if cur.fetchone()[0] < len(rows):
        conn.rollback()
        print(json.dumps({**plan, "error": "archive copy incomplete — nothing removed"}))
        return 1
    cur.execute("DELETE FROM trade_closed WHERE id = ANY(%s)", (plan["ids"],))
    conn.commit()
    print(json.dumps({**plan, "backup": str(backup), "archived": len(rows)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
