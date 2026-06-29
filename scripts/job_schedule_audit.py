#!/usr/bin/env python3
"""job_schedule_audit.py — classify every cron job by TIER (market-time-sensitivity), RESOURCE class,
and LLM routing (local vs cloud-OAuth), and compute per-hour contention so overload windows are visible.

Read-only. No broker writes. This is the evidence map behind the tiered-prioritization design
(docs/diligence/current/JOB_SCHEDULE_TIERED_PRIORITIZATION.md).

    python3 scripts/job_schedule_audit.py --json
    python3 scripts/job_schedule_audit.py --markdown > docs/diligence/current/JOB_SCHEDULE_AUDIT.md

Tiers:
  T1 market_critical  — scalp/proposal/validation/orchestrator/protective-stop: must run on time 06:00-12:00 ET.
  T2 supporting       — news/catalyst/SEC/enrichment: run but yield to T1.
  T3 background       — research/hermes/topic/rag/inference/reports: DEFER out of the 06:00-12:00 market window.
  INFRA               — watchdogs/health/monitors/telegram/backups: light, always-on.

LLM routing target:
  local       — fast, low-latency, market-critical advisory (gemma3 small / embeddings) — keep on the GPU.
  cloud_oauth — heavy background research/synthesis — offload to the FREE Grok(:8645)/ChatGPT(:8646) lanes
                to free the local GPU during market hours.
  none        — no LLM.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict

# (regex on the command) -> (tier, llm_backend_now, llm_target). First match wins; order matters.
RULES = [
    # ---- T1 market-critical ----
    (r"run_finviz_momentum_scalp_scan|momentum_scalp_early_lane|momentum_scalp_validation_fast_path",
     "T1", "local", "local"),
    (r"strategy_signal_sync|auto_proposal_generator|social_scalp_scanner|trade_ai_orchestrator",
     "T1", "local", "local"),
    (r"process_watchlist_agent_jobs", "T1", "local", "local"),
    (r"catalyst_momentum_engine.*premarket_scalp", "T1", "local", "local"),
    (r"fidelity_monitored_stop|protective|monitored_stop|send_telegram_proposal_alert|"
     r"run_automated_trade_proposal_revalidation|cleanup_stale_proposals|proposal_lifecycle", "T1", "none", "none"),
    # ---- T2 supporting ----
    (r"news_to_catalyst|hermes_news_bridge|finviz_news", "T2", "local", "local"),
    (r"run_sec_form4_momentum_context|finviz_enrichment|finviz_screener_runner", "T2", "none", "none"),
    (r"proposal_enrichment_loop", "T2", "local", "cloud_oauth"),
    (r"hermes_subject_enhance.*(scalp|proposal)", "T2", "cloud_oauth", "cloud_oauth"),
    # ---- T3 background / research (LLM-heavy → should offload to cloud) ----
    (r"run_deep_overnight_llm_window|build_deep_overnight_llm_queue|run_deep_overnight_llm_queue",
     "T3", "local", "local"),   # overnight batch — intentionally local, but window-gated to 22:00-03:00
    (r"run_inference_cycle|llm_intelligence_enrichment|trade_close_llm_analyzer|holdings_llm_refresh",
     "T3", "local", "cloud_oauth"),
    (r"topic_ingestion|topic_research_synthesizer|hermes_youtube_discovery|hermes_directive_discovery|"
     r"directive_keyword_enhancer|hermes_source_curation|research_scheduler|atp2_research", "T3", "cloud_oauth", "cloud_oauth"),
    (r"hermes_subject_enhance|hermes_watchlist_scorer|hermes_score_alerts|hermes_coordinator|"
     r"hermes_autonomous_self_tune|build_hermes_canonical_status|taxonomy_tagger|register_analyst_sources",
     "T3", "local", "cloud_oauth"),
    (r"rag_indexer|rag_retrieval|embedding|content_scoring", "T3", "local", "local"),  # embeddings stay local (small)
    # ---- INFRA ----
    (r"watchdog|health_agent|system_health|freshness|monitor|reaper|cleanup_stale_locks|"
     r"telegram|poller|siem|log_error|warm_caches|sync-docs|backup|integrity_sweep|memsync|"
     r"oauth_lane_keepalive|llm_retry_monitor|populate_performance_context|strategy_config_loader", "INFRA", "none", "none"),
]

# Resource class by command content.
def _resource_class(cmd: str, llm_now: str) -> str:
    if llm_now in ("local", "cloud_oauth") or re.search(r"ollama|gemma|qwen|llama|11434|8645|8646|llm|rag|embed|hermes_subject", cmd):
        return "llm"
    if re.search(r"orchestrator|screener_runner|finviz_enrichment|repricer|ingest|backtest", cmd):
        return "db_heavy"
    if re.search(r"watchdog|monitor|poller|telegram|health|freshness|reaper|heartbeat", cmd):
        return "light"
    return "cpu"


def classify(cmd: str):
    for pat, tier, now, target in RULES:
        if re.search(pat, cmd):
            return tier, now, target
    return "INFRA", "none", "none"


def _expand_hours(hour_field: str) -> list:
    """Expand a cron hour field (e.g. '6-11', '*/5', '0,30', '9') into the set of hours it fires."""
    out = set()
    if hour_field == "*":
        return list(range(24))
    for part in hour_field.split(","):
        step = 1
        if "/" in part:
            base, step = part.split("/"); step = int(step)
        else:
            base = part
        if base in ("*", ""):
            rng = range(0, 24, step)
        elif "-" in base:
            a, b = base.split("-"); rng = range(int(a), int(b) + 1, step)
        else:
            rng = [int(base)]
        out.update(h for h in rng if 0 <= h <= 23)
    return sorted(out)


def audit(crontab_text: str = None) -> dict:
    if crontab_text is None:
        crontab_text = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    jobs = []
    for line in crontab_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or re.match(r"^[A-Z_]+=", line):
            continue
        m = re.match(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.*)$", line)
        if not m:
            continue
        minute, hour, dom, mon, dow, cmd = m.groups()
        tier, llm_now, llm_target = classify(cmd)
        rc = _resource_class(cmd, llm_now)
        # extract a readable job name
        nm = re.search(r"(scripts/[\w\-]+\.(py|sh)|run_[\w]+\.sh|linux_launchers/[\w\-]+\.sh)", cmd)
        name = (nm.group(1).split("/")[-1] if nm else cmd[:40])
        guarded = ("llm_priority_guard.sh" in cmd)
        jobs.append({"name": name, "schedule": f"{minute} {hour} {dom} {mon} {dow}",
                     "hours": _expand_hours(hour), "dow": dow, "tier": tier,
                     "resource_class": rc, "llm_now": llm_now, "llm_target": llm_target,
                     "market_guarded": guarded})

    # per-hour EFFECTIVE LLM contention: a market-hours-guarded job contributes 0 during 06:00-12:00
    # (it defers), but still counts outside the window.
    contention = {h: 0 for h in range(24)}
    for j in jobs:
        if j["resource_class"] == "llm":
            for h in j["hours"]:
                if j["market_guarded"] and 6 <= h < 12:
                    continue
                contention[h] += 1
    market_hours = list(range(6, 12))
    overload = {h: c for h, c in contention.items() if h in market_hours and c >= 6}

    by_tier = defaultdict(int)
    by_rc = defaultdict(int)
    for j in jobs:
        by_tier[j["tier"]] += 1
        by_rc[j["resource_class"]] += 1

    # LLM routing matrix: jobs whose recommended backend differs from current (offload candidates)
    llm_jobs = [j for j in jobs if j["resource_class"] == "llm"]
    offload = [j for j in llm_jobs if j["llm_now"] == "local" and j["llm_target"] == "cloud_oauth"]

    return {
        "ok": True, "total_jobs": len(jobs),
        "by_tier": dict(by_tier), "by_resource_class": dict(by_rc),
        "llm_contention_by_hour": contention,
        "market_window_overload_hours": overload,
        "llm_jobs": len(llm_jobs),
        "cloud_offload_candidates": [j["name"] for j in offload],
        "jobs": jobs,
        "note": "Read-only schedule audit. T3 LLM jobs should defer during 06:00-12:00 ET (the market "
                "window) and/or offload to the free cloud-OAuth lanes so T1 scalp/proposal work gets the GPU. "
                "No broker writes; operator/2FA untouched.",
    }


def to_markdown(r: dict) -> str:
    L = ["# Job Schedule Audit & Contention Map", "",
         f"**{r['total_jobs']} active cron jobs** · {r['llm_jobs']} LLM-touching  ",
         "_Source: `python3 scripts/job_schedule_audit.py --json`_  ", "",
         "## By tier", "", "| Tier | Jobs |", "|------|-----:|"]
    for t in ("T1", "T2", "T3", "INFRA"):
        L.append(f"| {t} | {r['by_tier'].get(t, 0)} |")
    L += ["", "## LLM contention by hour (jobs that can fire each hour)", "",
          "| Hour (ET) | LLM jobs | |", "|-----------|--------:|--|"]
    for h in range(24):
        c = r["llm_contention_by_hour"][h]
        flag = " ⚠ OVERLOAD (market window)" if h in r["market_window_overload_hours"] else (" ← market window" if 6 <= h < 12 else "")
        bar = "█" * c
        L.append(f"| {h:02d}:00 | {c} | {bar}{flag} |")
    L += ["", "## Cloud-OAuth offload candidates (currently local, should move to free Grok/ChatGPT lanes)", ""]
    for n in r["cloud_offload_candidates"]:
        L.append(f"- `{n}`")
    L += ["", "> " + r["note"]]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    r = audit()
    if args.markdown:
        print(to_markdown(r))
    elif args.json:
        print(json.dumps(r, indent=2, default=str))
    else:
        print(f"jobs={r['total_jobs']} llm={r['llm_jobs']} overload_hours={list(r['market_window_overload_hours'])} "
              f"offload_candidates={len(r['cloud_offload_candidates'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
