#!/usr/bin/env python3
"""catalyst_calibration.py — outcome calibration for the catalyst classifier (self-learning).

ADVISORY-ONLY, READ-ONLY on market data. For settled catalyst_events (older than SETTLE_DAYS, with a symbol
and a stored direction), measure the realized forward return from market_ohlcv_bars and score whether the
catalyst's direction matched the move. Aggregates per catalyst_type → a weight_multiplier (bounded 0.5–1.5)
written to data/runtime/catalyst_calibration.json. The classifier reads this to scale impact_score (only
when samples >= MIN_SAMPLES). NEVER mutates catalyst_events, prices, trading, or scoring config.

  python3 scripts/catalyst_calibration.py            # compute + write calibration JSON
  python3 scripts/catalyst_calibration.py --dry-run  # print, don't write
"""
import os, sys, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "runtime" / "catalyst_calibration.json"
SETTLE_DAYS = 2          # forward window to measure realized move
LOOKBACK_DAYS = 120      # history window of catalysts to calibrate on
MIN_SAMPLES = 10         # per-type minimum before a multiplier is trusted
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
    # settled catalysts with a stored direction; realized fwd return from daily-ish bars
    cur.execute(f"""
        WITH cat AS (
            SELECT id, symbol, catalyst_type, published_at,
                   COALESCE(raw_payload->>'direction','neutral') AS direction
            FROM catalyst_events
            WHERE symbol IS NOT NULL AND published_at < now() - interval '{SETTLE_DAYS} days'
              AND published_at > now() - interval '{LOOKBACK_DAYS} days'
        ),
        entry AS (
            SELECT cat.id, cat.symbol, cat.catalyst_type, cat.direction,
                   (SELECT close_price FROM ticker_prices p WHERE p.symbol=cat.symbol AND p.price_date<=cat.published_at::date
                      ORDER BY p.price_date DESC LIMIT 1) AS p0,
                   (SELECT close_price FROM ticker_prices p WHERE p.symbol=cat.symbol
                      AND p.price_date >= (cat.published_at + interval '{SETTLE_DAYS} days')::date
                      ORDER BY p.price_date ASC LIMIT 1) AS p1
            FROM cat
        )
        -- data-quality guard: require a real (>=$1) entry price to avoid penny-stock %-explosion noise.
        SELECT catalyst_type, direction, p0, p1 FROM entry WHERE p0 IS NOT NULL AND p1 IS NOT NULL AND p0 >= 1.0
    """)
    rows = cur.fetchall(); c.close()

    MAX_CREDIBLE_MOVE = 50.0  # |2-day move| beyond this is treated as a data error, not a catalyst outcome
    agg = {}
    dropped = 0
    for ctype, direction, p0, p1 in rows:
        move = (float(p1) - float(p0)) / float(p0) * 100.0
        if abs(move) > MAX_CREDIBLE_MOVE:
            dropped += 1
            continue
        a = agg.setdefault(ctype, {"n": 0, "hits": 0, "abs_sum": 0.0, "move_sum": 0.0})
        a["n"] += 1; a["abs_sum"] += abs(move); a["move_sum"] += move
        if direction == "bullish" and move > 0: a["hits"] += 1
        elif direction == "bearish" and move < 0: a["hits"] += 1
        elif direction == "neutral" and abs(move) >= 3.0: a["hits"] += 1  # neutral "informative" if it moved

    by_type = {}
    for ctype, a in agg.items():
        n = a["n"]; hit_rate = a["hits"] / n if n else 0.0
        avg_abs = a["abs_sum"] / n if n else 0.0
        # multiplier: 50% hit-rate → ~1.0; higher hit-rate boosts, lower dampens; bounded 0.5..1.5.
        mult = max(0.5, min(1.5, round(0.5 + hit_rate, 3))) if n >= MIN_SAMPLES else 1.0
        by_type[ctype] = {"samples": n, "hit_rate": round(hit_rate, 3),
                          "avg_abs_move_pct": round(avg_abs, 2),
                          "avg_move_pct": round(a["move_sum"] / n, 2) if n else 0.0,
                          "weight_multiplier": mult, "trusted": n >= MIN_SAMPLES}
    out = {"updated_at": datetime.now(timezone.utc).isoformat(),
           "settle_days": SETTLE_DAYS, "lookback_days": LOOKBACK_DAYS, "min_samples": MIN_SAMPLES,
           "total_settled_catalysts": len(rows), "dropped_as_data_error": dropped, "credible_samples": len(rows)-dropped,
           "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1]["samples"]))}
    if dry:
        print(json.dumps(out, indent=2))
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(out, indent=2))
        print(f"wrote {OUT}  ({len(rows)} settled catalysts, {sum(1 for v in by_type.values() if v['trusted'])} trusted types)")


if __name__ == "__main__":
    main()
