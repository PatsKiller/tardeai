#!/usr/bin/env python3
"""apply_snaptrade_fund_map.py — (re)apply the SnapTrade 401k fund-code classifications.

The SnapTrade Fidelity 401k positions use opaque internal codes (OG51, 3905, O7Z6 …) with no public
ticker, so the look-through (phase3) leaves them "Other / Unclassified". This maps each code to its
Morningstar category (manual_sector_map.json) AND copies a same-fund proxy's GICS sector_weights into
fund_lookthrough.json so the code decomposes into real sectors. Source of truth:
config/snaptrade_401k_fund_map.json — durable + committed, so the mapping survives a runtime rebuild of
the state files. Idempotent. Run after a sync that adds/repoints 401k codes, then phase3 reclassifies.

  python3 scripts/apply_snaptrade_fund_map.py        # apply + run phase3
  python3 scripts/apply_snaptrade_fund_map.py --no-resolve
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "portfolios" / "state"
CFG = ROOT / "config" / "snaptrade_401k_fund_map.json"


def _load(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def apply() -> dict:
    cfg = _load(CFG, {}).get("codes", {})
    if not cfg:
        return {"ok": False, "error": f"no codes in {CFG}"}
    mm_path = STATE / "manual_sector_map.json"
    lt_path = STATE / "fund_lookthrough.json"
    mm = _load(mm_path, {})
    lt = _load(lt_path, {})

    cat_to_sector = {  # Morningstar category → manual_sector_map label
        "US Large Growth": "US Large Growth", "US Large Blend": "US Large Blend",
        "US Large Value": "US Large Value", "US Small/Mid Cap": "US Small/Mid Cap",
        "International": "International",
    }
    applied_mm = applied_lt = 0
    for code, info in cfg.items():
        cat = info.get("category", "")
        mm[code] = {"sector": cat_to_sector.get(cat, "Other / Unclassified"),
                    "industry": "Mutual Fund", "note": info.get("fund", "")}
        applied_mm += 1
        src = info.get("lookthrough_source")
        if src and isinstance(lt.get(src), dict):
            e = dict(lt[src])
            e["fund_name"] = info.get("fund", code)
            e["note"] = f"GICS weights aliased from {src} (same/equivalent fund) — SnapTrade 401k code"
            lt[code] = e
            applied_lt += 1

    mm_path.write_text(json.dumps(mm, indent=2))
    lt_path.write_text(json.dumps(lt, indent=2))
    return {"ok": True, "manual_map": applied_mm, "lookthrough": applied_lt}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-resolve", action="store_true", help="skip running phase3 afterwards")
    a = ap.parse_args()
    res = apply()
    print(json.dumps(res, indent=2))
    if not res.get("ok"):
        return 1
    if not a.no_resolve:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "phase3_lookthrough_resolver.py"),
                        "--project-root", str(ROOT)], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
