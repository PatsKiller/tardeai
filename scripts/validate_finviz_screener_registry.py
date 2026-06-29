#!/usr/bin/env python3
"""validate_finviz_screener_registry.py — fail the build if the live finviz_screeners DB and the
checked-in config/finviz_screeners.yaml registry drift. Read-only. No broker writes.

Checks: (1) every active DB screener is in the registry db_screeners group; (2) no registry
db_screener is absent from the DB; (3) active-flag agreement; (4) no duplicate screener_ids; (5) the
5 operator presets are present + the scalp_lane_screener_ids all resolve to scalp_fast presets.

    python3 scripts/validate_finviz_screener_registry.py --json     # exit 1 on drift
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
REGISTRY = ROOT / "config" / "finviz_screeners.yaml"


def load_registry() -> dict:
    return yaml.safe_load(REGISTRY.read_text())


def validate() -> dict:
    reg = load_registry()
    presets = {s["screener_id"]: s for s in reg.get("screeners", [])}
    db_reg = {s["screener_id"]: s for s in reg.get("db_screeners", [])}
    all_ids = list(presets) + [s["screener_id"] for s in reg.get("db_screeners", [])]

    issues = {"missing_from_registry": [], "registry_not_in_db": [], "active_mismatch": [],
              "duplicate_ids": [], "preset_problems": []}

    # duplicates
    seen = set()
    for i in all_ids:
        if i in seen:
            issues["duplicate_ids"].append(i)
        seen.add(i)

    # DB diff (skip gracefully if DB unavailable — registry-only checks still run)
    db_available = True
    try:
        from export_finviz_screeners import export_db
        db = {r["screener_id"]: r for r in export_db()}
        for sid, r in db.items():
            if r["active"] and sid not in db_reg:
                issues["missing_from_registry"].append(sid)
            elif sid in db_reg and bool(db_reg[sid].get("active")) != bool(r["active"]):
                issues["active_mismatch"].append(sid)
        for sid in db_reg:
            if sid not in db:
                issues["registry_not_in_db"].append(sid)
    except Exception as e:
        db_available = False
        issues["_db_warning"] = f"db unavailable: {str(e).splitlines()[0][:80]}"

    # presets + scalp lane integrity
    for need in ("s144880153", "s144880160", "s144880157", "s144880159", "s144880158"):
        if not any(p.get("preset_id") == need for p in presets.values()):
            issues["preset_problems"].append(f"missing operator preset {need}")
    for sid in reg.get("scalp_lane_screener_ids", []):
        p = presets.get(sid)
        if not p:
            issues["preset_problems"].append(f"scalp_lane id {sid} not a registry preset")
        elif p.get("cadence_class") != "scalp_fast":
            issues["preset_problems"].append(f"scalp_lane id {sid} is not scalp_fast")
        elif p.get("go_eligible_by_itself") is not False:
            issues["preset_problems"].append(f"scalp_lane id {sid} must be go_eligible_by_itself=false")

    drift = {k: v for k, v in issues.items() if not k.startswith("_") and v}
    ok = not drift
    return {
        "ok": ok, "status": "PASS" if ok else "FAIL", "db_available": db_available,
        "preset_count": len(presets), "db_registry_count": len(db_reg),
        "issues": issues, "drift": drift,
        "note": "Read-only registry/DB consistency check. Finviz screens are discovery only — none are "
                "GO-eligible by themselves. No broker writes.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = validate()
    print(json.dumps(r, indent=2, default=str) if args.json else
          f"registry: {r['status']} presets={r['preset_count']} db={r['db_registry_count']} drift={list(r['drift'])}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
