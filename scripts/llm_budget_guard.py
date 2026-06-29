#!/usr/bin/env python3
"""llm_budget_guard.py — LLM budget ENFORCEMENT control plane (not just monitoring).

HARD RULES (enforced + tested):
  * Local 31B/27B (gemma3:27b, gemma4-31b) is HARD-BLOCKED during the 06:00-12:00 ET market window.
  * Free-OAuth jobs NEVER fall back to a paid key — a paid fallback is a hard_fail (critical).
  * If the cloud-OAuth lanes are unavailable/over-budget, T3 market-hour jobs DEFER — they NEVER fall
    back to local 31B/27B or a paid key.
  * T1 market-hour LLM is local_fast/local_quality only (no cloud). Budget >=80% throttles T3, >=95% stops it.

Read-only / advisory enforcement (decides lanes; does not itself call any model or broker). No broker writes.

    python3 scripts/llm_budget_guard.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
POLICY = ROOT / "config" / "llm_budget_policy.yaml"
BLOCKED_LOCAL = {"gemma3:27b", "gemma4-31b"}


def _policy() -> dict:
    return yaml.safe_load(POLICY.read_text())


def in_market_window(now=None, pol=None) -> bool:
    pol = pol or _policy()
    try:
        from zoneinfo import ZoneInfo
        et = now or datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        et = now or datetime.now()
    mw = pol.get("market_window", {})
    hhmm = et.strftime("%H:%M")
    return et.weekday() < 5 and mw.get("start", "06:00") <= hhmm < mw.get("end", "12:00")


def _pick_cloud(cloud_state: dict, pol: dict) -> tuple:
    """Return (lane_name, throttled) for the best usable free cloud lane, or (None, reason)."""
    for lane in ("cloud_grok", "cloud_chatgpt_codex"):
        st = cloud_state.get(lane)
        if not st:
            continue                      # no info for this lane → treat as unusable (defer, don't assume up)
        if not st.get("reachable", False):
            continue
        if st.get("in_cooldown"):
            continue
        pct = float(st.get("daily_pct") or 0)
        hard_stop = float(pol["lanes"][lane].get("hard_stop_daily_pct", 95))
        throttle = float(pol["lanes"][lane].get("throttle_daily_pct", 80))
        if pct >= hard_stop:
            continue
        return lane, pct >= throttle
    return None, "no_usable_cloud_lane"


def decide(tier: str, model: str, market: bool, cloud_state: dict | None = None, pol: dict | None = None) -> dict:
    """Pure enforcement decision. Returns {action, selected_lane, reason}.
    action ∈ allow | defer | hard_block | hard_fail."""
    pol = pol or _policy()
    cloud_state = cloud_state or {}
    model = (model or "").strip()

    # 0. paid key is never allowed for these lanes.
    if "paid" in model.lower() or model in ("gpt-4-paid", "claude-paid"):
        return {"action": "hard_fail", "selected_lane": None, "reason": "paid fallback forbidden (free-OAuth only)"}

    # 1. local 31B/27B blocked during the market window.
    if model in BLOCKED_LOCAL and market:
        return {"action": "hard_block", "selected_lane": None,
                "reason": f"{model} (local 31B/27B) hard-blocked during 06:00-12:00 ET market window"}

    tier = (tier or "T3").upper()
    if tier == "T1":
        lane = "local_quality" if model == "gemma3:12b" else "local_fast"
        return {"action": "allow", "selected_lane": lane, "reason": "T1: local_fast/local_quality only (no cloud)"}

    if tier == "T3":
        if not market:
            return {"action": "allow", "selected_lane": "local_quality", "reason": "T3 off-window: local allowed"}
        lane, throttled = _pick_cloud(cloud_state, pol)
        if lane:
            return {"action": "allow", "selected_lane": lane,
                    "reason": "T3 market-hour: cloud" + (" (throttled ≥80%)" if throttled else ""),
                    "throttled": bool(throttled)}
        # cloud unavailable/over-budget → DEFER. Never local-31b, never paid.
        return {"action": "defer", "selected_lane": None,
                "reason": "T3 market-hour: cloud unavailable/over-budget → DEFER (no local-31B/paid fallback)"}

    # T2
    lane, throttled = _pick_cloud(cloud_state, pol)
    if lane:
        return {"action": "allow", "selected_lane": lane, "reason": "T2: cloud", "throttled": bool(throttled)}
    return {"action": "allow", "selected_lane": "local_fast", "reason": "T2: cloud unavailable → local_fast"}


def _cloud_state() -> dict:
    """Snapshot the cloud lanes (reachability + daily budget % + cooldown) from the usage monitor."""
    out = {}
    try:
        from cloud_oauth_usage_monitor import build as _m, DAILY_SOFT_CAP
        r = _m()
        for name, lane in (("grok", "cloud_grok"), ("chatgpt", "cloud_chatgpt_codex")):
            l = r["lanes"].get(name, {})
            out[lane] = {"reachable": l.get("reachable") == "reachable",
                         "daily_pct": round(100.0 * (l.get("calls_today") or 0) / max(1, DAILY_SOFT_CAP), 1),
                         "auth_failures": l.get("auth_failures", 0),
                         "in_cooldown": (l.get("auth_failures", 0) >= 3),
                         "paid_fallbacks": l.get("paid_fallbacks", 0)}
    except Exception:
        pass
    return out


def build() -> dict:
    pol = _policy()
    market = in_market_window(pol=pol)
    cs = _cloud_state()
    findings = []
    # paid fallback anywhere → critical
    for lane, st in cs.items():
        if st.get("paid_fallbacks", 0) > 0:
            findings.append({"severity": "critical", "type": "llm_paid_fallback",
                             "message": f"{lane} used a PAID key {st['paid_fallbacks']}x — hard_fail policy violated"})
        if st.get("daily_pct", 0) >= 95:
            findings.append({"severity": "warning", "type": "llm_cloud_hard_stop",
                             "message": f"{lane} at {st['daily_pct']}% daily budget — T3 stopped/deferred"})
        elif st.get("daily_pct", 0) >= 80:
            findings.append({"severity": "warning", "type": "llm_cloud_throttle",
                             "message": f"{lane} at {st['daily_pct']}% daily budget — T3 throttled"})
        if st.get("in_cooldown"):
            findings.append({"severity": "warning", "type": "llm_cloud_auth_cooldown",
                             "message": f"{lane} in auth-failure cooldown (≥3 failures)"})
    # sample decisions for visibility
    sample = {
        "T1_market": decide("T1", "gemma3:4b", market, cs, pol),
        "T3_market": decide("T3", "gemma3:12b", market, cs, pol),
        "blocked_31b_market": decide("T3", "gemma4-31b", market, cs, pol),
        "paid_attempt": decide("T2", "gpt-4-paid", market, cs, pol),
    }
    return {
        "ok": True, "status": "PASS" if not any(f["severity"] == "critical" for f in findings) else "FAIL",
        "market_window": market, "cloud_state": cs, "findings": findings,
        "sample_decisions": sample,
        "enforcement": {"market_local_31b_27b": "hard_block", "paid_fallback": "hard_fail",
                        "T3_cloud_unavailable": "defer (never local-31B/paid)"},
        "note": "Budget enforcement decisions only — does not call models or brokers. No broker writes.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = build()
    print(json.dumps(r, indent=2, default=str) if args.json else
          f"llm-budget: {r['status']} market={r['market_window']} findings={len(r['findings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
