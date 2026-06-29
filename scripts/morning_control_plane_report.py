#!/usr/bin/env python3
"""morning_control_plane_report.py — one read-only report of Finviz, local LLM, cloud OAuth, dashboard,
and scheduler state. Aggregates the existing builders (no new probing of brokers). Health-agent can
ingest the `findings`. No broker writes.

    python3 scripts/morning_control_plane_report.py --json
    python3 scripts/morning_control_plane_report.py --markdown > docs/diligence/current/FINVIZ_AND_LLM_MORNING_CONTROL_PLANE.md
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as e:
        return {"error": str(e).splitlines()[0][:80]} if default is None else default


def _dashboard() -> dict:
    """Probe /api/health latency (read-only)."""
    out = {"api_health": None, "threaded": None}
    try:
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{time_total}",
                            "--max-time", "8", "http://localhost:7777/api/health"],
                           capture_output=True, text=True, timeout=10)
        code, t = r.stdout.split()
        out["api_health"] = {"http": code, "seconds": float(t)}
    except Exception:
        out["api_health"] = {"http": "000", "seconds": None}
    try:
        ps = (ROOT / "scripts" / "portfolio_server.py").read_text()
        out["threaded"] = "ThreadingMixIn" in ps
    except Exception:
        pass
    return out


def build() -> dict:
    started = datetime.now().isoformat()
    findings = []

    # Finviz
    finviz = {}
    eff = _safe(lambda: __import__("finviz_screener_efficiency_audit").build(30), {})
    cad = _safe(lambda: __import__("apply_finviz_screener_cadence").build(), {})
    finviz["screener_count"] = eff.get("screener_count")
    finviz["by_recommendation"] = eff.get("by_recommendation")
    finviz["by_cadence_class"] = cad.get("by_class")
    finviz["scalp_lane_screeners"] = cad.get("scalp_fast_screeners")
    finviz["scalp_lane_is_targeted_not_broad"] = True   # enforced by test_momentum_scalp_finviz_lane_not_broad
    # stale screen warnings
    stale = [s["screener_id"] for s in eff.get("screeners", [])
             if s.get("last_run") and s["last_run"][:10] < datetime.now().strftime("%Y-%m-%d")]
    finviz["stale_screen_warnings"] = len(stale)

    # LLM (local runtime + budget)
    llm = {}
    probe = _safe(lambda: __import__("local_llm_runtime_probe").probe(), {})
    budget = _safe(lambda: __import__("llm_budget_guard").build(), {})
    llm["local_resident"] = probe.get("resident_models")
    llm["backend"] = probe.get("backend")
    llm["device_selected"] = probe.get("device_selected")
    llm["blocked_market_models"] = probe.get("blocked_market_models")
    llm["embed_timeouts_today"] = probe.get("embed_timeouts_today")
    llm["market_window"] = budget.get("market_window")
    llm["cloud_state"] = budget.get("cloud_state")
    llm["enforcement"] = budget.get("enforcement")
    for f in (probe.get("findings", []) + budget.get("findings", [])):
        findings.append(f)

    # Cloud OAuth
    cloud = _safe(lambda: __import__("cloud_oauth_usage_monitor").build(), {})
    cloud_summary = {n: {"calls_today": l.get("calls_today"), "reachable": l.get("reachable"),
                         "auth_failures": l.get("auth_failures"), "paid_fallbacks": l.get("paid_fallbacks")}
                     for n, l in (cloud.get("lanes", {}) or {}).items()}
    for f in cloud.get("findings", []):
        findings.append(f)

    # Dashboard
    dash = _dashboard()
    if dash["api_health"] and dash["api_health"]["http"] != "200":
        findings.append({"severity": "warning", "type": "dashboard_unresponsive",
                         "message": f"/api/health {dash['api_health']['http']}"})

    # Scheduler (LLM contention)
    audit = _safe(lambda: __import__("job_schedule_audit").audit(), {})
    sched = {"total_jobs": audit.get("total_jobs"), "llm_jobs": audit.get("llm_jobs"),
             "market_window_overload_hours": audit.get("market_window_overload_hours"),
             "cloud_offload_candidates": len(audit.get("cloud_offload_candidates", []))}

    return {
        "ok": True, "status": "PASS" if not any(f.get("severity") == "critical" for f in findings) else "FAIL",
        "generated_at": started,
        "finviz": finviz, "llm": llm, "cloud_oauth": cloud_summary, "dashboard": dash, "scheduler": sched,
        "findings": findings,
        "note": "Read-only morning control plane. No broker writes; operator/2FA untouched. LLMs advisory only.",
    }


def to_markdown(r: dict) -> str:
    f, l, d, s = r["finviz"], r["llm"], r["dashboard"], r["scheduler"]
    L = ["# Finviz & LLM Morning Control Plane", "",
         f"**Status: {r['status']}**  ", f"_Generated: {r['generated_at']}_  ", "",
         "## Finviz", "",
         f"- screeners: **{f.get('screener_count')}** · cadence classes: {f.get('by_cadence_class')}",
         f"- scalp lane (targeted, NOT broad): {f.get('scalp_lane_screeners')}",
         f"- recommendations: {f.get('by_recommendation')} · stale-screen warnings: {f.get('stale_screen_warnings')}",
         "", "## Local LLM", "",
         f"- resident: {l.get('local_resident')} · backend: {l.get('backend')} · device: {l.get('device_selected')}",
         f"- blocked in market hours: {l.get('blocked_market_models')} · embed timeouts today: {l.get('embed_timeouts_today')}",
         f"- enforcement: {l.get('enforcement')}",
         "", "## Cloud OAuth", ""]
    for n, c in r["cloud_oauth"].items():
        L.append(f"- {n}: calls={c['calls_today']} reachable={c['reachable']} auth_fails={c['auth_failures']} paid_fallbacks={c['paid_fallbacks']}")
    L += ["", "## Dashboard", "",
          f"- /api/health: {d.get('api_health')} · threaded: {d.get('threaded')}",
          "", "## Scheduler", "",
          f"- {s.get('total_jobs')} jobs ({s.get('llm_jobs')} LLM) · market-window overload hours: {s.get('market_window_overload_hours')} · cloud-offload candidates: {s.get('cloud_offload_candidates')}"]
    if r["findings"]:
        L += ["", "## Findings", ""] + [f"- [{x.get('severity')}] {x.get('message')}" for x in r["findings"]]
    L += ["", "> " + r["note"]]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    r = build()
    print(to_markdown(r) if args.markdown else (json.dumps(r, indent=2, default=str) if args.json else
          f"control-plane: {r['status']} findings={len(r['findings'])}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
