#!/usr/bin/env python3
"""Tiered job-prioritization + GPU/LLM optimization: classifier, guard applier, reaper, cloud-OAuth
monitor, and the health-agent wiring. Pure/deterministic where possible (DB parts degrade safely)."""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
if "dotenv" not in sys.modules:
    _d = types.ModuleType("dotenv"); _d.load_dotenv = lambda *a, **k: None; sys.modules["dotenv"] = _d

import job_schedule_audit as jsa  # noqa: E402
import apply_llm_priority_guard_to_crontab as applier  # noqa: E402
import cloud_oauth_usage_monitor as oauth  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # ---- classifier: tiers ----
    check("finviz scan → T1", jsa.classify("cd $PROJ && $PY scripts/run_finviz_momentum_scalp_scan.py")[0] == "T1")
    check("proposal worker → T1", jsa.classify("$PY scripts/process_watchlist_agent_jobs.py --limit 10")[0] == "T1")
    check("hermes research → T3", jsa.classify("$PY scripts/hermes_directive_discovery.py --apply")[0] == "T3")
    check("inference cycle → T3", jsa.classify("bash linux_launchers/run_inference_cycle.sh cron_midday")[0] == "T3")
    check("watchdog → INFRA", jsa.classify("bash scripts/portfolio_server_watchdog.sh")[0] == "INFRA")
    # ---- hour expansion ----
    check("*/5 6-11 expands to 6..11", jsa._expand_hours("6-11") == [6, 7, 8, 9, 10, 11])
    check("0,30 → [0]", jsa._expand_hours("0") == [0])
    check("* → all 24", len(jsa._expand_hours("*")) == 24)
    # ---- resource class ----
    check("hermes is llm class", jsa._resource_class("$PY scripts/hermes_directive_discovery.py", "cloud_oauth") == "llm")

    # ---- guard applier: only guard T3 LLM jobs that ALSO run outside the window ----
    check("guard a frequent T3 LLM job (*/15 all hours)", applier._should_guard("cd $PROJ && $PY scripts/hermes_watchlist_scorer.py", "*"))
    check("do NOT guard a T3 LLM job that runs ONLY in-window (0 8)",
          applier._should_guard("cd $PROJ && bash linux_launchers/run_inference_cycle.sh", "8") is False)
    check("do NOT guard a T1 job", applier._should_guard("cd $PROJ && $PY scripts/run_finviz_momentum_scalp_scan.py", "6-11") is False)
    check("do NOT double-guard", applier._should_guard("cd $PROJ && bash $PROJ/scripts/llm_priority_guard.sh && $PY scripts/topic_ingestion.py", "*") is False)
    # transform fixes the Monday worker gap
    crontab = "*/5 0-5 * * 2-6 cd $PROJ && $PY scripts/process_watchlist_agent_jobs.py --limit 5\n"
    _new, changes = applier.transform(crontab)
    check("worker-gap fix detected (2-6 → 1-6)", any(c[0] == "worker-gap-fix" for c in changes) and "* * 1-6" in _new)

    # ---- cloud-OAuth monitor: structure + safety ----
    r = oauth.build()
    check("oauth monitor has both lanes", set(r["lanes"].keys()) == {"grok", "chatgpt"})
    check("oauth findings is a list", isinstance(r["findings"], list))
    check("oauth never routes to paid key (note)", "never routes" in r["safety_note"].lower() or "paid" in r["safety_note"].lower())
    check("paid-fallback regex present", oauth._PAID_FALLBACK.search("fell back to paid key") is not None)
    check("markdown renders", "Cloud-OAuth Lane Usage" in oauth.to_markdown(r))

    # ---- health-agent wiring ----
    import health_agent as ha
    check("infra collector registered", ha.collect_infra_optimization_health in ha.COLLECTORS)
    check("infra collector returns list", isinstance(ha.collect_infra_optimization_health(), list))
    src = open(os.path.join(os.path.dirname(__file__), "..", "scripts", "health_agent.py")).read()
    check("reaper on the safe-remediation allowlist", "reset_stuck_agent_jobs.py" in src)
    import json as _json
    pol = _json.load(open(os.path.join(os.path.dirname(__file__), "..", "config", "health_agent_policy.json")))
    check("reaper auto-remediable", "agent_jobs_processing_stuck" in pol["auto_remediate"]["finding_types"])
    check("reaper remediation is the safe reaper script",
          "reset_stuck_agent_jobs.py" in pol["remediation_map"].get("agent_jobs_processing_stuck", ""))

    # ---- dashboard server is now threaded + thread-local DB ----
    ps = open(os.path.join(os.path.dirname(__file__), "..", "scripts", "portfolio_server.py")).read()
    check("server uses ThreadingMixIn", "ThreadingMixIn" in ps)
    check("server bounds concurrency with a semaphore", "BoundedSemaphore" in ps and "DASHBOARD_MAX_CONCURRENCY" in ps)
    check("server closes thread-local conn in finish", "close_thread_conn" in ps)
    da = open(os.path.join(os.path.dirname(__file__), "..", "scripts", "db_adapter.py")).read()
    check("db_adapter is thread-local", "threading.local" in da and "close_thread_conn" in da)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
