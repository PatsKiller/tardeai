#!/usr/bin/env python3
"""Dry report: notification routing + council synthesis over open plans.

    python3 scripts/cio_wave3b_report.py --root CURRENT [--json]

Sends nothing. Every decision is recorded with `would_send=false` and delivery
is the shadow adapter; this prints what the policy *would* route and what the
council *would* synthesise. No model is called and no plan is minted.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib import cio_notification_policy as policy  # noqa: E402
from scripts.lib.cio_council_synthesis import synthesize  # noqa: E402
from scripts.lib.cio_specialist_artifact import load as load_artifacts  # noqa: E402

NO_CONSUMER_REASON = (
    "operator-run CLI entry point: Wave3BReport@v1 is the shape this script "
    "prints, and its consumer is a person or an ops note, not another module. "
    "The library schemas it exercises — SpecialistArtifact@v1-lite, "
    "CIOCouncilSynthesis@v1, NotificationPolicy@v1 — are consumed here."
)

OPEN_STATUS = {"draft", "proposed"}


def load_plans(root: Path) -> list[dict]:
    path = root / "data" / "cio" / "cio_plans_projection.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [p for p in (doc.get("plans") or {}).values() if isinstance(p, dict)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("TRADEAI_ROOT") or ".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    now = datetime.now(timezone.utc)
    artifacts = load_artifacts(root)

    seen: set[tuple] = set()
    decisions = []
    for p in load_plans(root):
        if str(p.get("status")) not in OPEN_STATUS:
            continue
        syms = p.get("symbols") or []
        sym = str(syms[0]).upper() if syms else None
        key = (str(p.get("situation_type")), sym)
        dup = key in seen
        seen.add(key)
        mine = [a for a in artifacts if a.get("plan_id") == p.get("plan_id")]
        block = synthesize(artifacts=mine, plan_id=p.get("plan_id"), symbol=sym)
        decisions.append(policy.decide(p, synthesis=block,
                                       duplicate_subject=dup, now=now))

    counts = Counter(d["decision"] for d in decisions)
    reasons = Counter(d["reason"] for d in decisions)
    env = policy.notify_env_state()
    out = {
        "schema": "Wave3BReport@v1",
        "as_of": now.isoformat(),
        "authority": "READ_ONLY_ADVISORY",
        "plans_considered": len(decisions),
        "by_decision": dict(counts),
        "by_reason": dict(reasons.most_common(10)),
        "specialist_artifacts_on_disk": len(artifacts),
        "would_send_any": any(d.get("would_send") for d in decisions),
        "env": env,
    }
    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0

    print(f"Wave 3B dry report — root={root}")
    print(f"  plans considered            : {out['plans_considered']}")
    print(f"  specialist artifacts on disk: {out['specialist_artifacts_on_disk']}")
    print()
    print("  routing:")
    for k, v in counts.most_common():
        print(f"    {k:<22} {v}")
    print()
    print("  top reasons:")
    for k, v in reasons.most_common(6):
        print(f"    {k:<44} {v}")
    print()
    print(f"  WOULD SEND ANY : {out['would_send_any']}")
    print(f"  notify_enabled : {env['notify_enabled']}")
    print(f"  interdicted    : {env['interdicted']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
