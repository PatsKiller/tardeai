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


def unwrap_lane_map(raw: dict) -> dict:
    """Per-lane alert state. Heal the 2026-08-22 nesting bug.

    `_save_state({"as_of", "lanes": state})` while `_load_state()` returned the
    *whole file* made every 15-min run wrap `lanes` inside `lanes` (63 layers,
    258KB) and never see `last_alert` — Telegram every timer tick.
    """
    if not isinstance(raw, dict):
        return {}
    node = raw
    for _ in range(128):
        lanes = node.get("lanes")
        if not isinstance(lanes, dict):
            break
        # A real per-lane map has lane names or last_alert, not only {as_of, lanes}.
        if any(k not in ("as_of", "lanes") for k in lanes):
            node = lanes
            break
        node = lanes
    out = {}
    for k, v in (node if isinstance(node, dict) else {}).items():
        if k in ("as_of", "lanes") or not isinstance(v, dict):
            continue
        out[k] = v
    return out


def _load_lane_map() -> dict:
    try:
        raw = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return unwrap_lane_map(raw if isinstance(raw, dict) else {})


def _save_state(as_of, lane_map: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    rec = {"as_of": as_of, "lanes": lane_map, "schema": "ResearchLaneHealthAlertState@v1"}
    STATUS_PATH.write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")


def fix_hint(row: dict) -> str:
    """Per-lane operator hint. Do not keep the #440 import line as the only Fix."""
    lane = str(row.get("lane") or "")
    firing = " ".join(str(x) for x in (row.get("firing") or []))
    if lane == "deepseek":
        if "budget_throttled" in firing:
            return (
                "DeepSeek budget_throttled (SKIPPED_BUDGET), not a broken lane. "
                "Named symbols were not researched. Do not raise the cap until "
                "skip-gate + retry-on-cap + extra producers are explained."
            )
        if "error_rate_24h" in firing:
            return (
                "DeepSeek error_rate_24h (not streak). Lane-broken rows only — "
                "COST_CAP is SKIPPED_BUDGET / budget_throttled. "
                "streak=0 after one success still hides a 30%+ true-error rate."
            )
        return (
            "DeepSeek: import is already `llm_lane` (scripts/llm_lane.py). "
            "Live RAW errors are COST_CONFIGURATION_INVALID — cron .env must "
            "export LLM_GLOBAL_DAILY_USD_CAP (restored 0.50 on rebuild 2026-08-22). "
            "Alias `deepseek` is not available(); writer is deepseek-flash. "
            "Weekday scheduler; streak stays until a successful send."
        )
    if lane == "overnight-deep":
        return (
            "Overnight: OnCalendar 22–05:35 ET, ExecStart --model chatgpt --apply "
            "since 2026-08-22 13:20. First US window 22:35 ET 2026-08-22. "
            "Last deep_research_local row 2026-08-20 Flash (two days, not three months). "
            "If 22:35 writes zero non-error rows or still gemma, retarget failed."
        )
    if lane == "drive-sync":
        return (
            "Drive: hourly CURRENT sweep. DEGRADED_STALE_SOURCE when SOURCE_COMMIT "
            "!= origin/main (pin behind #455+). Targeted gog --replace until D4 8/27. "
            "zero_uploaded_with_failures = 404 dead parents. Canonical docs 1BMxbxU9… / ops 1a7vr2gn…"
        )
    if lane == "current-pin":
        return "CURRENT scripts/+docs/ must match SOURCE_COMMIT (git archive hashes). No docs overlay."
    if lane == "process-freshness":
        return (
            "portfolio_server loaded pin or start time disagrees with CURRENT. "
            "Restart after exact-main promote. Do not serve a 2-day in-memory overlay as now."
        )
    if lane == "coverage-stall":
        return (
            "Coverage stall: research flowed, PASS-grade (CURRENT) thesis did not. "
            "THIN rows count toward coverage_pct, not this alarm. Dry-run: "
            "scripts/thesis_mint_from_research.py. Apply after 8/27."
        )
    if firing:
        return firing
    return "see research_lane_health.py JSON"


def _alert(report: dict) -> int:
    firing = [r for r in report.get("lanes") or [] if not r.get("ok")]
    if not firing:
        _save_state(report.get("as_of"), _load_lane_map())
        return 0
    now = int(time.time())
    state = _load_lane_map()
    lines = []
    hints = []
    sent = 0
    for row in firing:
        lane = row["lane"]
        prev = state.get(lane) or {}
        try:
            last = int(prev.get("last_alert") or 0)
        except (TypeError, ValueError):
            last = 0
        if now - last < ALERT_DEDUP_SEC:
            state[lane] = {**prev, **{k: row.get(k) for k in ("ok", "firing", "error_streak")},
                           "last_alert": last, "suppressed": True}
            continue
        reasons = ",".join(row.get("firing") or [])
        extra = ""
        if lane == "drive-sync":
            extra = (f"  uploaded={row.get('uploaded')} failed={row.get('failed')} "
                     f"exit={row.get('exit_code')}")
        extra2 = ""
        if lane == "coverage-stall":
            extra2 = (
                f"  substantive={row.get('thesis_substantive', row.get('thesis_current'))}"
                f"/{row.get('thesis_held')} coverage={row.get('thesis_coverage')}"
            )
        lines.append(
            f"  • {lane}: {reasons}  streak={row.get('error_streak')}  "
            f"ok_24h={row.get('non_error_24h')} attempts_24h={row.get('attempts_24h')}"
            + extra + extra2
        )
        hints.append(f"  {lane}: {fix_hint(row)}")
        state[lane] = {**row, "last_alert": now, "suppressed": False}
        sent += 1
    _save_state(report.get("as_of"), state)
    if not lines:
        return 0
    watched = []
    for row in report.get("lanes") or []:
        if row.get("lane") == "deepseek":
            watched.append(
                f"  • deepseek (watched): ok={row.get('ok')} streak={row.get('error_streak')} "
                f"ok_24h={row.get('non_error_24h')} attempts_24h={row.get('attempts_24h')}"
            )
            break
    msg = (
        "⚠️ *Research lane RAW-store health*\n"
        "Reads RAW stores (research rows **including** `[ERROR]…`, Drive "
        "last-result JSON, CURRENT vs SOURCE_COMMIT). Silence is not health.\n"
        "systemd exit 0 means the *check* ran; alarm state is this JSON/Telegram.\n\n"
        + ("Watched:\n" + "\n".join(watched) + "\n\n" if watched else "")
        + "Firing:\n"
        + "\n".join(lines)
        + "\n\nFix:\n"
        + "\n".join(hints)
    )
    try:
        _deliver_telegram(msg)
    except Exception as exc:
        print("telegram send failed:", exc, file=sys.stderr)
        print(msg)
        return 2
    return sent


def _deliver_telegram(msg: str) -> None:
    from telegram_alert import send_telegram
    send_telegram(msg, bypass_router=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert", action="store_true")
    args = ap.parse_args()
    try:
        report = collect_report()
    except Exception as exc:
        print(f"research_lane_health collect failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, default=str))
    if args.alert:
        rc = _alert(report)
        # 2 = telegram send failed (check ran, notify did not). 0 = check ran.
        return 2 if rc == 2 else 0
    # Alarm state lives in JSON (`ok`, `firing`). Exit 1 is a crashed CHECK,
    # not "alarms found" — otherwise systemd cannot tell them apart.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
