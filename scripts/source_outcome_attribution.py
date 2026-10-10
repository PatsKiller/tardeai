#!/usr/bin/env python3
"""source_outcome_attribution.py — Gate 1 of Hermes source maturity (populates source_performance).

ADVISORY-ONLY. Attributes downstream paper-trade outcomes back to the news SOURCE that surfaced the symbol:
a source "contributed" to a trade if it published news on that symbol within ATTRIB_DAYS before entry. Rolls
up per source: total_signals, go_signals (symbol later GO/WAIT), trades_matched, profitable/wrong,
win_rate, avg_pnl_pct, scar_factor (sum losing $ / sum winning $). Upserts source_performance
(UNIQUE source_type, source_id). NEVER mutates trades/news/holdings/scoring — read-only except the one
source_performance table.

  python3 scripts/source_outcome_attribution.py            # compute + upsert
  python3 scripts/source_outcome_attribution.py --dry-run

The dry run computes on a READ ONLY session and returns BEFORE write_rows() (the only INSERT/commit)
is reachable (AGENTS.md §6). A real run writes data/runtime/source_outcome_attribution_last.json
(LaneRunReceipt@v1; ok_at only on success) under the persistent state root and exits 1 on failure.
scripts/source_maturity_chain.py runs this, source_maturity and source_vetting_ladder as one lane.
"""
import os, sys, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LOOKBACK_DAYS = 90       # news + trade window
ATTRIB_DAYS = 5          # a mention counts if it precedes entry by <= this
RECEIPT_NAME = "source_outcome_attribution"
if (ROOT / ".env").exists():  # absent in a bare checkout/test tree; the served release symlinks it
    for ln in (ROOT / ".env").read_text().splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'\""))
import psycopg2


def _db():
    return psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                            dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                            password=os.getenv("DB_PASSWORD"))


def compute(cur):
    """Read-only: the per-source rollup rows (no write)."""
    # per (source, symbol) first mention + signal count
    cur.execute(f"""SELECT source, symbol, MIN(published_at), COUNT(*)
                    FROM news_articles
                    WHERE published_at > now() - interval '{LOOKBACK_DAYS} days'
                      AND symbol IS NOT NULL AND source IS NOT NULL
                    GROUP BY source, symbol""")
    mentions = cur.fetchall()  # (source, symbol, first_seen, signals)
    # GO/WAIT symbols (for go_signals)
    cur.execute(f"""SELECT DISTINCT symbol FROM trade_ai_scans
                    WHERE scanned_at > now() - interval '{LOOKBACK_DAYS} days' AND decision IN ('GO','WAIT')""")
    go_syms = {r[0] for r in cur.fetchall()}
    # CORRECT attribution: a source gets a trade if it published news on that symbol in the ATTRIB_DAYS
    # window immediately BEFORE entry (one row per source x trade).
    cur.execute(f"""SELECT na.source, pt.id, lower(coalesce(pt.status,'')), pt.pnl, pt.pnl_pct
                    FROM paper_trades pt
                    JOIN news_articles na ON na.symbol = pt.symbol
                      AND na.published_at <= pt.entry_time
                      AND na.published_at >= pt.entry_time - interval '{ATTRIB_DAYS} days'
                    WHERE pt.entry_time > now() - interval '{LOOKBACK_DAYS} days' AND pt.symbol IS NOT NULL
                      AND na.source IS NOT NULL
                    GROUP BY na.source, pt.id, pt.status, pt.pnl, pt.pnl_pct""")
    matches = cur.fetchall()  # (source, trade_id, status, pnl, pnl_pct)

    from collections import defaultdict
    agg = defaultdict(lambda: {"total_signals": 0, "symbols": set(), "go_syms": set(),
                               "matched": set(), "win": 0, "loss": 0, "pnlpct_sum": 0.0, "pnlpct_n": 0,
                               "win_pnl": 0.0, "loss_pnl": 0.0, "last_signal": None})
    for source, symbol, first_seen, signals in mentions:
        a = agg[source]
        a["total_signals"] += signals
        a["symbols"].add(symbol)
        if a["last_signal"] is None or first_seen > a["last_signal"]:
            a["last_signal"] = first_seen
        if symbol in go_syms:
            a["go_syms"].add(symbol)
    for source, tid, st, pnl, pnlpct in matches:
        a = agg[source]
        a["matched"].add(tid)
        if st == "closed" and pnl is not None:
            p = float(pnl)
            if p > 0: a["win"] += 1; a["win_pnl"] += p
            elif p < 0: a["loss"] += 1; a["loss_pnl"] += abs(p)
            if pnlpct is not None:
                a["pnlpct_sum"] += float(pnlpct); a["pnlpct_n"] += 1

    rows_out = []
    for source, a in agg.items():
        closed = a["win"] + a["loss"]
        win_rate = round(a["win"] / closed * 100, 1) if closed else None
        avg_pnl_pct = round(a["pnlpct_sum"] / a["pnlpct_n"], 2) if a["pnlpct_n"] else None
        scar = round(a["loss_pnl"] / a["win_pnl"], 2) if a["win_pnl"] > 0 else (None if a["loss_pnl"] == 0 else 9.99)
        rows_out.append({"source_id": source, "total_signals": a["total_signals"], "go_signals": len(a["go_syms"]),
                         "trades_matched": len(a["matched"]), "profitable_trades": a["win"],
                         "wrong_signal_count": a["loss"], "win_rate": win_rate, "avg_pnl_pct": avg_pnl_pct,
                         "scar_factor": scar, "last_signal_at": a["last_signal"]})
    return rows_out


def write_rows(conn, rows_out):
    """The only writer: upsert source_performance, then commit. Never called by a dry run."""
    cur = conn.cursor()
    upserts = 0
    for r in rows_out:
        cur.execute("""INSERT INTO source_performance
            (source_type, source_id, total_signals, go_signals, trades_matched, profitable_trades,
             win_rate, avg_pnl_pct, scar_factor, wrong_signal_count, last_signal_at, updated_at)
            VALUES ('news',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
            ON CONFLICT (source_type, source_id) DO UPDATE SET
              total_signals=EXCLUDED.total_signals, go_signals=EXCLUDED.go_signals,
              trades_matched=EXCLUDED.trades_matched, profitable_trades=EXCLUDED.profitable_trades,
              win_rate=EXCLUDED.win_rate, avg_pnl_pct=EXCLUDED.avg_pnl_pct, scar_factor=EXCLUDED.scar_factor,
              wrong_signal_count=EXCLUDED.wrong_signal_count, last_signal_at=EXCLUDED.last_signal_at,
              updated_at=now()""",
            (r["source_id"], r["total_signals"], r["go_signals"], r["trades_matched"], r["profitable_trades"],
             r["win_rate"], r["avg_pnl_pct"], r["scar_factor"], r["wrong_signal_count"], r["last_signal_at"]))
        upserts += 1
    conn.commit()
    return upserts


def run(dry_run=False):
    c = _db()
    try:
        if dry_run:
            c.set_session(readonly=True)
        rows_out = compute(c.cursor())
        if dry_run:
            upserts = 0
        else:
            upserts = write_rows(c, rows_out)
    finally:
        c.close()
    top = sorted([r for r in rows_out if r["trades_matched"] > 0], key=lambda r: -(r["win_rate"] or 0))[:8]
    report = {"sources": len(rows_out), "upserted": upserts,
              "with_matched_trades": sum(1 for r in rows_out if r["trades_matched"] > 0),
              "top_by_winrate": [{k: r[k] for k in ("source_id", "trades_matched", "win_rate", "scar_factor")} for r in top]}
    if dry_run:
        report.update(dry_run=True, would_upsert=len(rows_out), table="source_performance")
    print(json.dumps(report, indent=2, default=str))
    return report


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--dry-run" in argv:
        run(dry_run=True)
        return 0
    from lib.lane_last_receipt import now_iso, write_receipt

    started = now_iso()
    try:
        rep = run()
    except Exception as exc:  # noqa: BLE001 -- recorded in the receipt, then a non-zero exit
        write_receipt(RECEIPT_NAME, ok=False, error=f"{type(exc).__name__}: {exc}", started_at=started)
        print(f"source_outcome_attribution FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    write_receipt(RECEIPT_NAME, ok=True, started_at=started,
                  summary={k: rep[k] for k in ("sources", "upserted", "with_matched_trades")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
