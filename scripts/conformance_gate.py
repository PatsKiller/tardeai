#!/usr/bin/env python3
"""conformance_gate.py — the conformance gate on promotion (Wave 5 O-W5-2; 05 §4, 09 §W5).

Reads the latest PlatformConformance@v1 report and answers whether a promote may proceed:

    TRADEAI_CONFORMANCE_GATE = warn  (default)  → prints the verdict, exit 0 always (receipt only)
                             = block            → exit 1 when any silo is NON_CONFORMANT or the report is stale
                             = 0 | off          → skipped (operator emergency; the skip is a receipt too)
    TRADEAI_CONFORMANCE_GATE_OVERRIDE="<reason>" → block mode passes once, reason recorded

Floor: a silo below DEGRADED (score < 0.80, state NON_CONFORMANT) blocks; DEGRADED warns. A report older
than --max-age-hours (default 36) counts as missing. Every run appends ConformanceGateReceipt@v1 to
data/governance/conformance_gate_receipts.jsonl. Called by cio_phase2_exact_main_deploy.sh before
activate_release; also usable by hand.
"""
NO_CONSUMER_REASON = (
    "ConformanceGateReceipt@v1 rows are read by the maturity re-measurement lane and the closeout; the gate itself "
    "is invoked by cio_phase2_exact_main_deploy.sh cmd_promote (release-write path), not a scheduled lane"
)

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))
sys.path.insert(0, str(PROJ / "scripts"))

SCHEMA = "ConformanceGateReceipt@v1"
FLOOR_STATE = "NON_CONFORMANT"


def governance_dir(env: dict) -> Path:
    try:
        import approval_package as ap  # type: ignore
        return ap.governance_dir(None, env)
    except Exception:  # noqa: BLE001
        return Path(env.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state")) / "data" / "governance"


def evaluate(report: dict | None, *, now: _dt.datetime, max_age_h: float, mode: str, override: str | None) -> dict:
    """Pure verdict: {allow, verdict, reasons[], silos_below[], silos_degraded[], mode}."""
    reasons: list[str] = []
    below: list[str] = []
    degraded: list[str] = []
    stale = False
    if not report:
        reasons.append("NO_REPORT")
    else:
        try:
            as_of = _dt.datetime.fromisoformat(str(report.get("as_of")).replace("Z", "+00:00"))
            if (now - as_of).total_seconds() > max_age_h * 3600:
                stale = True; reasons.append(f"STALE_REPORT:{as_of.isoformat()}")
        except (ValueError, TypeError):
            stale = True; reasons.append("UNPARSEABLE_AS_OF")
        for s in report.get("silos") or []:
            if s.get("silo_id") == "UNASSIGNED":
                continue
            if s.get("state") == FLOOR_STATE:
                below.append(f"{s.get('silo_id')}:{s.get('score')}")
            elif s.get("state") == "DEGRADED":
                degraded.append(f"{s.get('silo_id')}:{s.get('score')}")
    if below:
        reasons.append("SILOS_BELOW_FLOOR:" + ",".join(below))
    blocking = bool(below or stale or not report)
    if mode in ("0", "off", "false"):
        return {"allow": True, "verdict": "SKIPPED", "reasons": reasons, "silos_below": below, "silos_degraded": degraded, "mode": mode}
    if mode == "block" and blocking:
        if override:
            return {"allow": True, "verdict": "OVERRIDDEN", "reasons": reasons, "override": override, "silos_below": below, "silos_degraded": degraded, "mode": mode}
        return {"allow": False, "verdict": "BLOCKED", "reasons": reasons, "silos_below": below, "silos_degraded": degraded, "mode": mode}
    return {"allow": True, "verdict": ("WARN" if (blocking or degraded) else "PASS"), "reasons": reasons, "silos_below": below,
            "silos_degraded": degraded, "mode": mode}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", default="")
    ap.add_argument("--max-age-hours", type=float, default=36.0)
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    env = dict(os.environ)
    now = _dt.datetime.now(_dt.timezone.utc)
    gd = governance_dir(env)
    rp = Path(a.report) if a.report else gd / "platform_conformance_latest.json"
    report = None
    try:
        report = json.loads(rp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report = None
    mode = str(env.get("TRADEAI_CONFORMANCE_GATE", "warn")).lower()
    v = evaluate(report, now=now, max_age_h=a.max_age_hours, mode=mode, override=env.get("TRADEAI_CONFORMANCE_GATE_OVERRIDE") or None)
    row = {"schema": SCHEMA, "ts": now.isoformat(), "sha": a.sha, "report": str(rp), "report_as_of": (report or {}).get("as_of"), **v}
    try:
        gd.mkdir(parents=True, exist_ok=True)
        with (gd / "conformance_gate_receipts.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    except OSError:
        pass
    print(json.dumps(row, indent=1, default=str))
    return 0 if v["allow"] else 1


if __name__ == "__main__":
    sys.exit(main())
