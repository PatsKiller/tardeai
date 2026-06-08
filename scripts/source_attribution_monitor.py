#!/usr/bin/env python3
"""source_attribution_monitor.py — track source-attribution health as the news<->trade overlap grows.

READ-ONLY. Snapshots key metrics daily, appends to a time-series, computes deltas, and flags regressions or
a stalled ramp (overlap healthy but still zero attributions after a ramp window). Lets you SEE the source
attribution + calibration loops strengthening. No mutation of trades/scoring/sources.

Metrics: traded_30d, traded_with_news_7d (+ overlap_pct), source rows, sources_with_trades,
sources_outcome_proven, total_attributions. History: data/runtime/source_attribution_history.json (last 90).

  python3 scripts/source_attribution_monitor.py            # snapshot + append + status
  python3 scripts/source_attribution_monitor.py --dry-run  # print, don't append
"""
import os, sys, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "data" / "runtime" / "source_attribution_history.json"
MATURITY = ROOT / "data" / "runtime" / "source_maturity_latest.json"
TIER_RANK = {"demoted": -1, "candidate": 0, "probationary": 1, "trusted": 2, "core": 3}
OVERLAP_OK = 70.0          # % traded symbols with recent news = healthy
RAMP_DAYS = 5              # after this many healthy-overlap days, expect attributions > 0
for ln in (ROOT / ".env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'\""))
import psycopg2


def _db():
    return psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                            dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                            password=os.getenv("DB_PASSWORD"))


def main():
    dry = "--dry-run" in sys.argv
    c = _db(); cur = c.cursor()
    cur.execute("""
        WITH traded AS (SELECT DISTINCT symbol FROM paper_trades WHERE entry_time>now()-interval '30 days')
        SELECT
          (SELECT count(*) FROM traded),
          (SELECT count(*) FROM traded t WHERE EXISTS(SELECT 1 FROM news_articles na WHERE na.symbol=t.symbol AND na.created_at>now()-interval '7 days')),
          (SELECT count(*) FROM source_performance),
          (SELECT count(*) FROM source_performance WHERE trades_matched>0),
          (SELECT count(*) FROM source_performance WHERE win_rate IS NOT NULL),
          (SELECT coalesce(sum(trades_matched),0) FROM source_performance)
    """)
    traded, with_news, src_rows, with_trades, proven, attribs = cur.fetchone()
    c.close()
    overlap_pct = round(with_news / traded * 100, 1) if traded else 0.0
    snap = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "ts": datetime.now(timezone.utc).isoformat(),
            "traded_30d": traded, "traded_with_news_7d": with_news, "overlap_pct": overlap_pct,
            "source_rows": src_rows, "sources_with_trades": int(with_trades),
            "sources_outcome_proven": int(proven), "total_attributions": int(attribs)}

    # tier snapshot + per-source tiers (for movement tracking as outcomes accrue)
    try:
        mat = json.loads(MATURITY.read_text())
        snap["tier_counts"] = mat.get("tier_counts", {})
        snap["source_tiers"] = {s["source"]: s["tier"] for s in mat.get("sources", [])}
    except Exception:
        snap["tier_counts"], snap["source_tiers"] = {}, {}

    hist = []
    try:
        hist = json.loads(HIST.read_text()).get("snapshots", [])
    except Exception:
        pass
    prev = hist[-1] if hist else None

    # tier transitions vs the prior snapshot (promotions ↑ / demotions ↓)
    transitions = []
    if prev and prev.get("source_tiers"):
        for src, tier in snap["source_tiers"].items():
            old = prev["source_tiers"].get(src)
            if old and old != tier:
                direction = "promotion" if TIER_RANK.get(tier, 0) > TIER_RANK.get(old, 0) else "demotion"
                transitions.append({"source": src, "from": old, "to": tier, "direction": direction})
    snap["tier_transitions"] = transitions
    # healthy-overlap streak (for stall detection)
    streak = 0
    for s in reversed(hist + [snap]):
        if s["overlap_pct"] >= OVERLAP_OK:
            streak += 1
        else:
            break

    status, notes = "HEALTHY", []
    if overlap_pct < OVERLAP_OK:
        status = "DEGRADED"; notes.append(f"overlap {overlap_pct}% < {OVERLAP_OK}% target")
    if prev and overlap_pct < prev["overlap_pct"] - 20:
        status = "REGRESSED"; notes.append(f"overlap dropped {prev['overlap_pct']}%→{overlap_pct}%")
    if overlap_pct >= OVERLAP_OK and attribs == 0 and streak >= RAMP_DAYS:
        status = "STALLED"; notes.append(f"overlap healthy {streak}d but 0 attributions — check attribution loop")
    # notable tier movements (demotion of a trusted/core source is worth surfacing)
    promos = [t for t in transitions if t["direction"] == "promotion"]
    demos = [t for t in transitions if t["direction"] == "demotion"]
    notable_demo = [t for t in demos if t["from"] in ("trusted", "core")]
    if notable_demo:
        notes.append("demoted from trusted/core: " + ", ".join(f"{t['source']}({t['from']}→{t['to']})" for t in notable_demo))
    if promos:
        notes.append(f"{len(promos)} promotion(s): " + ", ".join(f"{t['source']}→{t['to']}" for t in promos[:5]))
    if prev:
        snap["delta"] = {"overlap_pct": round(overlap_pct - prev["overlap_pct"], 1),
                         "total_attributions": int(attribs) - prev.get("total_attributions", 0),
                         "sources_with_trades": int(with_trades) - prev.get("sources_with_trades", 0)}
    snap["status"] = status; snap["notes"] = notes; snap["healthy_overlap_streak_days"] = streak

    if not dry:
        hist.append(snap); hist = hist[-90:]
        HIST.parent.mkdir(parents=True, exist_ok=True)
        HIST.write_text(json.dumps({"updated_at": snap["ts"], "snapshots": hist}, indent=2))
    out = {k: snap[k] for k in ("date", "overlap_pct", "traded_with_news_7d", "traded_30d",
          "sources_with_trades", "total_attributions", "healthy_overlap_streak_days", "status", "notes")}
    out["tier_counts"] = snap.get("tier_counts", {})
    out["tier_transitions"] = transitions
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
