#!/usr/bin/env python3
"""cloud_oauth_usage_monitor.py — usage + health monitor for the FREE cloud-OAuth LLM lanes.

As background/research LLM work is offloaded off the local GPU to the free rolling-OAuth lanes
(Grok xAI :8645, ChatGPT codex :8646), we must watch usage so we don't (a) exhaust a free quota,
(b) silently fall back to a PAID key, or (c) let a rolling token lapse. This aggregates per-lane call
counts + auth-failure markers from the lane logs, probes lane reachability, and emits a health-finding
shape. Read-only. No broker writes. Never routes anything to a paid key.

    python3 scripts/cloud_oauth_usage_monitor.py --json
    python3 scripts/cloud_oauth_usage_monitor.py --markdown
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"

LANES = {
    "grok": {"port": 8645, "logs": ["grok_stop_review_cron.log", "journal_review_grok.log",
                                    "schwab_classify_grok.log", "schwab_classify_grok3.log",
                                    "schwab_classify_grok4.log", "oauth_lane_keepalive.log"]},
    "chatgpt": {"port": 8646, "logs": ["oauth_lane_keepalive.log"]},
}
# Soft free-tier guardrail (per lane/day) — advisory, tune to the actual provider limits.
DAILY_SOFT_CAP = 800
_AUTH_FAIL = re.compile(r"401|403|unauthorized|auth.*fail|token.*expired|invalid_grant|refresh.*fail", re.I)
_PAID_FALLBACK = re.compile(r"fell back to paid|paid key|using paid|OPENAI_API_KEY|ANTHROPIC_API_KEY", re.I)


def _probe(port: int) -> str:
    try:
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "4",
                            f"http://localhost:{port}/v1/models"], capture_output=True, text=True, timeout=6)
        code = r.stdout.strip()
        # A proxy that answers (even 401/404) is reachable; only connection-refused (000) is "down".
        return "reachable" if code and code != "000" else "unreachable"
    except Exception:
        return "unknown"


def _scan_logs(lane: dict) -> dict:
    today = date.today().isoformat()
    calls_today = auth_fails = paid_fallbacks = 0
    for fname in lane["logs"]:
        f = LOGS / fname
        if not f.exists():
            continue
        try:
            for line in f.read_text(errors="replace").splitlines()[-4000:]:
                if today in line:
                    calls_today += 1
                    if _AUTH_FAIL.search(line):
                        auth_fails += 1
                    if _PAID_FALLBACK.search(line):
                        paid_fallbacks += 1
        except Exception:
            pass
    return {"calls_today": calls_today, "auth_failures": auth_fails, "paid_fallbacks": paid_fallbacks}


def build() -> dict:
    lanes = {}
    findings = []
    for name, cfg in LANES.items():
        usage = _scan_logs(cfg)
        reach = _probe(cfg["port"])
        status = "ok"
        if reach == "unreachable":
            status = "lane_unreachable"
            findings.append({"lane": name, "severity": "warning", "type": "cloud_oauth_lane_unreachable",
                             "message": f"{name} OAuth lane (:{cfg['port']}) unreachable"})
        if usage["paid_fallbacks"] > 0:
            status = "paid_fallback"
            findings.append({"lane": name, "severity": "critical", "type": "cloud_oauth_paid_fallback",
                             "message": f"{name} lane fell back to a PAID key {usage['paid_fallbacks']}x today"})
        if usage["auth_failures"] >= 3:
            findings.append({"lane": name, "severity": "warning", "type": "cloud_oauth_auth_failures",
                             "message": f"{name} lane {usage['auth_failures']} auth failures today (token roll?)"})
        if usage["calls_today"] >= DAILY_SOFT_CAP:
            findings.append({"lane": name, "severity": "warning", "type": "cloud_oauth_overuse",
                             "message": f"{name} lane {usage['calls_today']} calls today (soft cap {DAILY_SOFT_CAP})"})
        lanes[name] = {"port": cfg["port"], "reachable": reach, "status": status, **usage,
                       "soft_cap": DAILY_SOFT_CAP}
    return {
        "ok": True, "generated_at": datetime.now().isoformat(), "lanes": lanes,
        "findings": findings,
        "note": "Free rolling-OAuth lanes (Grok :8645, ChatGPT codex :8646). Offload heavy T3 LLM here to "
                "free the local GPU; monitor so we stay in free limits and never silently use a paid key.",
        "safety_note": "Read-only. No broker writes. Never routes free-only requests to a paid key.",
    }


def to_markdown(r: dict) -> str:
    L = ["# Cloud-OAuth Lane Usage", "", f"_Generated: {r['generated_at']}_  ", "",
         "| Lane | Port | Reachable | Calls today | Auth fails | Paid fallbacks | Status |",
         "|------|-----:|-----------|------------:|-----------:|---------------:|--------|"]
    for n, l in r["lanes"].items():
        L.append(f"| {n} | {l['port']} | {l['reachable']} | {l['calls_today']} | {l['auth_failures']} | "
                 f"{l['paid_fallbacks']} | {l['status']} |")
    if r["findings"]:
        L += ["", "## Findings", ""] + [f"- [{f['severity']}] {f['message']}" for f in r["findings"]]
    L += ["", "> " + r["note"], "", "> " + r["safety_note"]]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    r = build()
    if args.markdown:
        print(to_markdown(r))
    elif args.json:
        print(json.dumps(r, indent=2, default=str))
    else:
        print("cloud-oauth: " + " | ".join(
            f"{n}={l['calls_today']}calls/{l['reachable']}" for n, l in r["lanes"].items())
            + f" findings={len(r['findings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
