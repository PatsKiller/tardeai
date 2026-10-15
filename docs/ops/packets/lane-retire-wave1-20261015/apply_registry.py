#!/usr/bin/env python3
"""lane-retire-wave1-20261015 — post-install registry flip: retire_pending rows -> RETIRED (repo file only).

Run AFTER install.sh --apply, on a branch, then open the registry PR. The registry stays truthful: a row is flipped
only when the crontab copy shows its line commented with the retire-ld-w1 tag and no live copy (retire_packet.py
verify). Rows whose lines are still live are left ACTIVE with their retire_pending block (tier-B rows the operator
answered NO, or an install that did not happen).

    python3 apply_registry.py --registry config/lane_registry.json --crontab <(crontab -l) --date YYYY-MM-DD \
        --grant <cron grant id> [--write]

Without --write it prints the plan and writes nothing. It never touches the crontab.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import retire_packet as P  # noqa: E402


def plan(reg: dict, crontab_text: str) -> tuple[list[str], list[str]]:
    by_lane = {r["lane_id"]: r for r in P.rows(tier_b=True)}
    flip, keep = [], []
    lines = crontab_text.splitlines()
    for row in reg.get("lanes") or []:
        if not row.get("retire_pending"):
            continue
        r = by_lane.get(row["lane_id"])
        orig = (r or {}).get("original", "").rstrip()
        live = sum(1 for ln in lines if ln.rstrip() == orig)
        tagged = sum(1 for ln in lines if (m := P.TAG_RE.match(ln)) and m.group(3).rstrip() == orig)
        (flip if r and live == 0 and tagged == 1 else keep).append(row["lane_id"])
    return flip, keep


def apply(reg: dict, flip: list[str], date: str, grant: str) -> None:
    for row in reg["lanes"]:
        if row["lane_id"] not in flip:
            continue
        pend = row.pop("retire_pending")
        row["state"] = "RETIRED"
        row["state_since"] = date
        row["state_reason"] = (
            f"lane-retire-wave1-20261015 ({pend['tier']}): crontab line commented in place as "
            f"`# RETIRED {date} retire-ld-w1 {pend['reason']} <original>` (never deleted) under cron grant {grant}. "
            f"{pend['evidence']} Rollback: docs/ops/packets/lane-retire-wave1-20261015/rollback.sh."
        )
        row["reason_confidence"] = "ESTABLISHED"
        row["reason_evidence"] = pend["evidence"]
        row["retire_batch"] = "retire-ld-w1"
        if pend.get("duplicate_of"):
            row["superseded_by"] = pend["duplicate_of"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", required=True)
    ap.add_argument("--crontab", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--grant", required=True)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    path = Path(a.registry)
    reg = json.loads(path.read_text(encoding="utf-8"))
    flip, keep = plan(reg, Path(a.crontab).read_text(encoding="utf-8"))
    print(json.dumps({"flip_to_retired": flip, "kept_active_line_still_live": keep}, indent=1))
    if not a.write:
        print("PLAN ONLY: pass --write to edit the registry file")
        return 0
    apply(reg, flip, a.date, a.grant)
    path.write_text(json.dumps(reg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path}: {len(flip)} row(s) RETIRED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
