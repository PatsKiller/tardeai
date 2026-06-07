#!/usr/bin/env python3
"""build_hermes_canonical_status.py — merge live Hermes state into ONE canonical snapshot (Phase 217).

Read-only. Fetches the live /api/v2/hermes/* endpoints + systemd timer status and writes a normalized
snapshot to data/runtime/hermes_canonical_status_latest.json. Portal labels, the matrix Markdown, and the
Word doc are all regenerated FROM this single source so portal/state/docs agree. No secrets are stored.

  python3 scripts/build_hermes_canonical_status.py
"""
import os, sys, json, subprocess, urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("HERMES_API_BASE", "http://127.0.0.1:7777/api/v2/hermes")
OUT = ROOT / "data" / "runtime" / "hermes_canonical_status_latest.json"
XDG = {"XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}", **os.environ}


def api(ep):
    try:
        with urllib.request.urlopen(f"{BASE}/{ep}", timeout=20) as r:
            return json.loads(r.read()).get("data", {})
    except Exception as e:
        return {"_error": str(e)[:120]}


def sysd(cmd):
    try:
        return subprocess.run(["systemctl", "--user"] + cmd, capture_output=True, text=True,
                              timeout=10, env=XDG).stdout.strip()
    except Exception:
        return ""


def timer(name):
    return {"enabled": sysd(["is-enabled", f"{name}.timer"]) or "unknown",
            "active": sysd(["is-active", f"{name}.timer"]) or "unknown"}


def main():
    wf = api("workflow-matrix"); auth = api("llm-auth-status"); sll = api("self-learning-loops")
    rmx = api("researcher-matrix"); leg = api("legacy-agents"); health = api("health"); ps = api("profiles-status")
    db = {d.get("table"): d for d in (wf.get("db_lineage") or []) if isinstance(d, dict)}

    deep_timer = timer("hermes-deep-research-local")
    codex = next((l for l in auth.get("lanes", []) if l.get("provider") == "openai-codex"), {})
    serverops = next((p for p in (ps.get("profiles") or []) if p.get("profile") == "serverops"), {})
    so_tools = serverops.get("tools", "")
    so_count = int(so_tools.split(" ")[0]) if so_tools and so_tools.split(" ")[0].isdigit() else None

    snap = {
        "portal_snapshot_timestamp": datetime.now().isoformat(),
        "hermes_version": "v0.16.0",
        "timers_count": 38, "crons_count": 209, "services_count": 2, "llm_jobs_count": 6,  # System-page header scope
        "workflows_count": wf.get("workflow_count"),
        "graph_nodes_count": len(wf.get("graph_nodes") or []),
        "db_tables_count": len(wf.get("db_lineage") or []),
        "safe_views_count": wf.get("safe_views_count"),
        "cli_profile_used_by_automation": wf.get("any_cli_profile_in_jobs"),
        "db_writes_24h": {"research_intelligence": (db.get("hermes_research_intelligence") or {}).get("writes_24h"),
                          "memory_events": (db.get("hermes_memory_events") or {}).get("writes_24h")},
        "profiles": [{"profile": p.get("profile"), "model": p.get("model"),
                      "tools": p.get("tools"), "soul_hash": p.get("soul_hash")} for p in (ps.get("profiles") or [])],
        "llm_lanes": [{"lane": l.get("lane"), "provider": l.get("provider"), "authed": l.get("authed"),
                       "usable": l.get("usable"), "headless_status": l.get("headless_status"),
                       "reason_code": l.get("reason_code")} for l in auth.get("lanes", [])],
        "self_learning_loops": {"count": sll.get("loop_count"), "advisory_only": sll.get("advisory_only_loops"),
                                "feed_prompts": sll.get("loops_affecting_prompts"),
                                "mutate_scoring": sll.get("loops_affecting_scoring_directly"),
                                "closed_loop_status": (sll.get("closed_loop_status") or "").split("—")[0].strip(),
                                "gaps": sll.get("highest_priority_gaps"),
                                "loops": [{"loop": l["loop"], "rows": l.get("rows"),
                                           "feeds_prompts": l.get("affects_future_prompts"),
                                           "mutates_scoring": l.get("affects_scoring")} for l in sll.get("loops", [])]},
        "graph_nodes": [{"id": n.get("id"), "name": n.get("name"), "owner": n.get("owner_hint")} for n in (wf.get("graph_nodes") or [])],
        "retired_agents": leg.get("count") or len(leg.get("items", [])),
        "gateway_status": sysd(["is-active", "hermes-gateway.service"]) + "/" + sysd(["is-enabled", "hermes-gateway.service"]),
        "kill_switch": {"active": health.get("kill_switch_active"),
                        "canonical_path": (health.get("kill_switch") or {}).get("canonical_path", "data/runtime/HERMES_DISABLED")},
        "deep_research_lane": {
            "design_status": "designed", "runner_built": True,
            "runner_script": "scripts/hermes_deep_research_local.py",
            "timer_enabled": deep_timer["enabled"] == "enabled",
            "timer_active": deep_timer["active"] == "active",
            "next_run": "daily 02:30 local (overnight-gated)",
            "model": "gemma3:27b / gemma3-overnight", "writes_to": "hermes_research_intelligence (staging)",
            "safety": "advisory/staging-only; kill-switch + health-gate; --apply self-gated to overnight"},
        "codex_lane": {
            "auth_ready": codex.get("authed"), "interactive_ready": True,
            "headless_available": codex.get("headless_status") == "ready",
            "headless_reason": codex.get("reason_code"), "runtime_enabled": False,
            "usage": "hermes -p dev chat (interactive only on Hermes 0.16.0)"},
        "serverops": {"tool_count": so_count, "tools": so_tools,
                      "risk_status": "UNSAFE — terminal/code_execution/computer_use enabled",
                      "p1_hardening_required": True},
        "canonical_docs": {
            "markdown_path": "docs/hermes/HERMES_AGENTS_WORKFLOWS_SOULS_AND_SELF_LEARNING_MATRIX.md",
            "word_path": "docs/hermes/HERMES_AGENTS_WORKFLOWS_SOULS_AND_SELF_LEARNING_MATRIX.docx",
            "status_json": "data/runtime/hermes_canonical_status_latest.json"},
        "open_gates": ["P1: harden serverops dangerous tools (terminal/code_execution/computer_use)",
                       "self-learning: dedicated research_backlog table",
                       "shadow-efficacy < graft sample (keep advisory)",
                       "Codex headless: blocked on Hermes 0.16.0 (auto-recovers on newer build)",
                       "Claude: add Anthropic credits; Nous: complete OAuth; gemma4: deferred"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snap, indent=2, default=str))
    print(json.dumps({k: snap[k] for k in ("workflows_count", "graph_nodes_count", "db_tables_count",
          "safe_views_count", "retired_agents", "gateway_status")}, indent=2))
    print("deep_research timer_enabled:", snap["deep_research_lane"]["timer_enabled"])
    print("codex headless_available:", snap["codex_lane"]["headless_available"], "reason:", snap["codex_lane"]["headless_reason"])
    print("serverops tools:", snap["serverops"]["tool_count"], "p1:", snap["serverops"]["p1_hardening_required"])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
