#!/usr/bin/env python3
"""finviz_sector_research.py — proactive Finviz sector & industry performance research.

Pulls Finviz group performance (grp_export.ashx) for sectors AND industries — the macro/rotation lens the
screeners don't give. Stores a daily snapshot in finviz_group_performance (append-only history) so rotation
and macro research can see which sectors/industries are leading/lagging. Uses the same FINVIZ_API_TOKEN.

  python3 scripts/finviz_sector_research.py [--dry-run]
"""
import argparse
import csv
import io
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(str(ROOT / ".env"))
from db_adapter import _get_conn

TOKEN = os.getenv("FINVIZ_API_TOKEN", "").strip()
BASE = "https://elite.finviz.com/grp_export.ashx"


def _num(s):
    if s is None:
        return None
    s = str(s).strip().replace("%", "").replace(",", "").replace("$", "")
    if s in ("", "-", "—"):
        return None
    mult = 1.0
    if s.endswith("B"): mult, s = 1e9, s[:-1]
    elif s.endswith("M"): mult, s = 1e6, s[:-1]
    elif s.endswith("K"): mult, s = 1e3, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def _fetch(group):
    url = f"{BASE}?g={group}&v=152&auth={TOKEN}"
    try:
        from finviz_throttle import acquire as _a
        _a()
    except Exception:
        pass
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    text = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
    return list(csv.DictReader(io.StringIO(text)))


def _ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS finviz_group_performance (
            id            BIGSERIAL PRIMARY KEY,
            snapshot_date DATE NOT NULL,
            group_type    TEXT NOT NULL,          -- 'sector' | 'industry'
            name          TEXT NOT NULL,
            change_pct    DOUBLE PRECISION,
            pe            DOUBLE PRECISION,
            dividend_yield DOUBLE PRECISION,
            avg_volume    DOUBLE PRECISION,
            volume        DOUBLE PRECISION,
            market_cap    DOUBLE PRECISION,
            stocks        INTEGER,
            created_at    TIMESTAMPTZ DEFAULT now(),
            UNIQUE (snapshot_date, group_type, name)
        )""")


def run(dry_run=False):
    if not TOKEN:
        print("ABORT: FINVIZ_API_TOKEN not set"); return 1
    conn = _get_conn(); cur = conn.cursor()
    _ensure_table(cur); conn.commit()
    today = datetime.now().strftime("%Y-%m-%d")
    total = 0
    for gtype in ("sector", "industry"):
        try:
            rows = _fetch(gtype)
        except Exception as e:
            print(f"  {gtype}: fetch error {str(e)[:60]}"); continue
        print(f"  {gtype}: {len(rows)} groups")
        for r in rows:
            name = (r.get("Name") or "").strip()
            if not name:
                continue
            vals = (today, gtype, name, _num(r.get("Change")), _num(r.get("P/E")),
                    _num(r.get("Dividend Yield")), _num(r.get("Average Volume")),
                    _num(r.get("Volume")), _num(r.get("Market Cap")),
                    int(_num(r.get("Stocks")) or 0))
            if dry_run:
                total += 1; continue
            cur.execute("""INSERT INTO finviz_group_performance
                (snapshot_date, group_type, name, change_pct, pe, dividend_yield,
                 avg_volume, volume, market_cap, stocks)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (snapshot_date, group_type, name) DO UPDATE SET
                  change_pct=EXCLUDED.change_pct, pe=EXCLUDED.pe,
                  dividend_yield=EXCLUDED.dividend_yield, avg_volume=EXCLUDED.avg_volume,
                  volume=EXCLUDED.volume, market_cap=EXCLUDED.market_cap, stocks=EXCLUDED.stocks""",
                vals)
            total += 1
    if not dry_run:
        conn.commit()
    # show leaders/laggards
    if not dry_run:
        cur.execute("""SELECT name, change_pct FROM finviz_group_performance
                       WHERE snapshot_date=%s AND group_type='sector'
                       ORDER BY change_pct DESC NULLS LAST""", (today,))
        secs = cur.fetchall()
        if secs:
            print(f"  sector leaders: {secs[0]}  laggards: {secs[-1]}")
    print(f"{'DRY ' if dry_run else ''}stored {total} group rows for {today}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    raise SystemExit(run(dry_run=ap.parse_args().dry_run))
