#!/usr/bin/env python3
"""audit_health_schedule_drift.py — declared component schedules vs the real crontab.

system_health_agent judges a component STALE by comparing its last output to its
DECLARED schedule (MONITORED_COMPONENTS[].schedule). That is the right design —
a flat wall-clock threshold false-alarms every weekend, which is how the options
monitor_freshness, screener zero-float and paper-sync checks all misfired
(2026-07-20). But it only works while the declaration matches reality.

Drift direction matters:
  actual runs MORE often than declared  -> SAFE (data arrives fresher than
                                           expected; the check under-alarms)
  actual runs LESS often than declared  -> DANGEROUS (the check expects output
                                           that is never produced -> false STALE)

This reports both, flagging only the dangerous direction as a failure, and
normalizes equivalent spellings (7-17 == 7,8,...,17) so cosmetic differences do
not read as drift.

  audit_health_schedule_drift.py          # human report
  audit_health_schedule_drift.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

FIELD = r"[\d*/,\-]+"
CRON = re.compile(rf"^\s*({FIELD})\s+({FIELD})\s+({FIELD})\s+({FIELD})\s+({FIELD})\s+(.*)$")


def _expand(field: str, lo: int, hi: int) -> set:
    """Expand one cron field to the set of values it fires on."""
    out = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s or 1)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = b = int(part)
        out |= {v for v in range(a, b + 1) if (v - a) % step == 0}
    return out


def fire_set(spec: str):
    """(minutes, hours, dows) a cron spec fires on — comparable across spellings."""
    f = spec.split()
    if len(f) < 5:
        return None
    return (_expand(f[0], 0, 59), _expand(f[1], 0, 23), _expand(f[4], 0, 7))


def crontab_lines():
    out = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if l.strip() and not l.strip().startswith("#")]


def audit() -> dict:
    import system_health_agent as H
    lines = crontab_lines()

    def actual_for(script):
        found = []
        for l in lines:
            m = CRON.match(l)
            if m and script in m.group(6):
                found.append(" ".join(m.groups()[:5]))
        return found

    equivalent, safe, dangerous, no_cron = [], [], [], []
    for e in H.MONITORED_COMPONENTS:
        comp = e.get("component")
        raw = e.get("schedule")
        decls = [raw] if isinstance(raw, str) else list(raw or [])
        decls = [d.strip() for d in decls if isinstance(d, str)]
        found = actual_for(f"{comp}.py")
        if not found:
            no_cron.append({"component": comp, "declared": decls})
            continue

        # Union of everything the real crontab fires for this component.
        act_m, act_h, act_d = set(), set(), set()
        for a in found:
            fs = fire_set(a)
            if fs:
                act_m |= fs[0]; act_h |= fs[1]; act_d |= fs[2]
        dec_m, dec_h, dec_d = set(), set(), set()
        for d in decls:
            fs = fire_set(d)
            if fs:
                dec_m |= fs[0]; dec_h |= fs[1]; dec_d |= fs[2]

        rec = {"component": comp, "declared": decls, "actual": found}
        if (dec_m, dec_h, dec_d) == (act_m, act_h, act_d):
            equivalent.append(rec)
        elif dec_h <= act_h and dec_d <= act_d and dec_m <= act_m:
            rec["note"] = "actual runs at least as often as declared — check under-alarms"
            safe.append(rec)
        else:
            missing_h = sorted(dec_h - act_h)
            rec["note"] = (f"declared expects runs the crontab does not provide "
                           f"(hours {missing_h or 'n/a'}) — risks FALSE STALE")
            dangerous.append(rec)
    return {"equivalent": equivalent, "safe_direction": safe,
            "dangerous_drift": dangerous, "no_cron_line": no_cron}


def main() -> int:
    ap = argparse.ArgumentParser(description="Health component schedule drift audit")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = audit()
    if a.json:
        print(json.dumps(r, indent=1, default=str)); return 0
    print("HEALTH COMPONENT SCHEDULE DRIFT")
    print(f"  equivalent to crontab        : {len(r['equivalent'])}")
    print(f"  safe direction (runs more)   : {len(r['safe_direction'])}")
    print(f"  no cron line (wrapper/alias) : {len(r['no_cron_line'])}")
    print(f"  DANGEROUS drift              : {len(r['dangerous_drift'])}")
    for rec in r["safe_direction"]:
        print(f"\n  ~ {rec['component']}: {rec['note']}")
        print(f"      declared {rec['declared']}\n      actual   {rec['actual']}")
    for rec in r["dangerous_drift"]:
        print(f"\n  !! {rec['component']}: {rec['note']}")
        print(f"      declared {rec['declared']}\n      actual   {rec['actual']}")
    return 1 if r["dangerous_drift"] else 0


if __name__ == "__main__":
    sys.exit(main())
