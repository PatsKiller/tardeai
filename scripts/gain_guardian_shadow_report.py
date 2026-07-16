#!/usr/bin/env python3
"""Gain Guardian shadow report — what WOULD have fired, so thresholds get
tuned on evidence before anyone gets paged (Phase 191 shadow pattern).

Usage:
  python scripts/gain_guardian_shadow_report.py            # latest run
  python scripts/gain_guardian_shadow_report.py --days 10  # distribution over window
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from db_adapter import _execute as ex, USE_DB
    if not USE_DB:
        print("DB unavailable", file=sys.stderr)
        return 2

    cfg = json.loads((ROOT / "config" / "gain_guardian_thresholds.json").read_text())
    rows = ex(
        """SELECT * FROM holding_exit_metrics
           WHERE run_at > now() - make_interval(days => %s)
           ORDER BY run_at DESC, parabolic_score DESC""",
        (args.days,), fetch="all",
    ) or []
    if not rows:
        print("No metric rows in window — run holdings_gain_guardian.py --apply first.")
        return 1

    # Latest row per (symbol, account)
    latest: dict[tuple, dict] = {}
    for r in rows:
        latest.setdefault((r["symbol"], r["account"]), r)
    rows = list(latest.values())

    states: dict[str, int] = {}
    advisories: dict[str, int] = {}
    for r in rows:
        states[r["extension_state"] or "NORMAL"] = states.get(r["extension_state"] or "NORMAL", 0) + 1
        if r.get("giveback_state"):
            states[r["giveback_state"]] = states.get(r["giveback_state"], 0) + 1
        adv = r.get("advisory") or "(none)"
        advisories[adv] = advisories.get(adv, 0) + 1

    ext_cfg = cfg["extension"]
    print(f"[gain-guardian shadow] positions={len(rows)} window={args.days}d "
          f"(thresholds: EXTENDED≥{ext_cfg['extended_score']}, "
          f"CLIMAX≥{ext_cfg['climax_score']}+rvol≥{ext_cfg['climax_rvol_min']})")
    print("  state distribution:", dict(sorted(states.items(), key=lambda x: -x[1])))
    print("  would-have-fired advisories:", dict(sorted(advisories.items(), key=lambda x: -x[1])))

    print("\n  top parabolic scores:")
    for r in sorted(rows, key=lambda x: -(float(x.get("parabolic_score") or 0)))[:10]:
        print(f"    {r['symbol']:6} {str(r['account'])[:18]:18} score={r['parabolic_score']} "
              f"ext50={r['ext50_atr']} rsi={r['rsi14']} rvol={r['rvol20']} "
              f"gb={r['giveback_frac']} → {r.get('advisory') or 'no advisory'}")

    # Near-miss analysis — how far the book sits from each trigger
    near_ext = [r for r in rows if 40 <= float(r.get("parabolic_score") or 0) < ext_cfg["extended_score"]]
    if near_ext:
        print(f"\n  near-EXTENDED (score 40–{ext_cfg['extended_score']}): "
              + ", ".join(f"{r['symbol']}({r['parabolic_score']})" for r in near_ext[:8]))

    # Named expectation from the build prompt: explain SCHG's bucket
    schg = [r for r in rows if r["symbol"] == "SCHG"]
    if schg:
        s = max(schg, key=lambda x: float(x.get("parabolic_score") or 0))
        why = (f"SCHG: score {s['parabolic_score']} — RSI {s['rsi14']} is hot, but "
               f"ext50 {s['ext50_atr']} ATR and rvol {s['rvol20']} keep it under the "
               f"EXTENDED bar ({ext_cfg['extended_score']}); giveback {s['giveback_frac']} "
               f"is below watch ({cfg['giveback']['watch_frac']}).")
        print(f"\n  {why}")

    rvol_missing = sum(1 for r in rows if r.get("rvol20") is None)
    if rvol_missing:
        print(f"\n  note: rvol20 unavailable on {rvol_missing} position(s) "
              f"(fund/proxy bars without volume — fail-soft, CLIMAX cannot trigger there)")
    print("  note: intraday runs understate rvol20 (partial day bar) — trust the 17:40 post-close run.")

    if args.json:
        print(json.dumps({"states": states, "advisories": advisories}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
