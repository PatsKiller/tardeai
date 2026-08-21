#!/usr/bin/env python3
"""research_lane_health.py — alarm on RAW research-store failure.

Reads hermes_external_research (and overnight deep_research_local) with NO
`recommendation NOT LIKE '[%'` filter. That filter hid the DeepSeek
lib.llm_lane crash for 8 days.

  python3 scripts/research_lane_health.py           # print JSON
  python3 scripts/research_lane_health.py --alert    # Telegram on firing lanes

READ_ONLY_ADVISORY. No LLM calls. No broker mutation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.research_lane_health import collect_report  # noqa: E402

STATUS_PATH = ROOT / "data" / "runtime" / "research_lane_health.json"
ALERT_DEDUP_SEC = int(os.getenv("RESEARCH_LANE_ALERT_DEDUP_SEC", str(6 * 3600)))


def _load_state() -> dict:
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(state, indent=2, default=str) + "\n", encoding="utf-8")


def _alert(report: dict) -> int:
    firing = [r for r in report.get("lanes") or [] if not r.get("ok")]
    if not firing:
        return 0
    now = int(time.time())
    state = _load_state()
    lines = []
    sent = 0
    for row in firing:
        lane = row["lane"]
        prev = state.get(lane) or {}
        last = int(prev.get("last_alert") or 0)
        if now - last < ALERT_DEDUP_SEC:
            state[lane] = {**row, "last_alert": last, "suppressed": True}
            continue
        reasons = ",".join(row.get("firing") or [])
        lines.append(
            f"  • {lane}: {reasons}  streak={row.get('error_streak')}  "
            f"ok_24h={row.get('non_error_24h')} attempts_24h={row.get('attempts_24h')}"
        )
        state[lane] = {**row, "last_alert": now, "suppressed": False}
        sent += 1
    _save_state({"as_of": report.get("as_of"), "lanes": state})
    if not lines:
        return 0
    msg = (
        "⚠️ *Research lane RAW-store health*\n"
        "Reads hermes_external_research **including** `[ERROR]…` rows "
        "(not last_real). A dead lane must not look like silence.\n\n"
        + "\n".join(lines)
        + "\n\nFix: DeepSeek writer must import `llm_lane` (scripts/llm_lane.py), "
        "not `lib.llm_lane`. ChatGPT overnight is lane `overnight-deep` "
        "(hermes_research_intelligence deep_research_local)."
    )
    try:
        from telegram_alert import send_telegram
        send_telegram(msg, bypass_router=True)
    except Exception as exc:
        print("telegram send failed:", exc, file=sys.stderr)
        print(msg)
        return 2
    return sent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert", action="store_true")
    args = ap.parse_args()
    report = collect_report()
    print(json.dumps(report, indent=2, default=str))
    if args.alert:
        _alert(report)
        return 0 if report.get("ok") else 1
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
