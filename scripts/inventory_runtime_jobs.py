#!/usr/bin/env python3
"""inventory_runtime_jobs.py — Phase 199B runtime job inventory (READ-ONLY).

Enumerates every runtime job (crontab + systemd user/system timers & services), extracts schedule,
script, lock file, log, and static dependency/classification signals, then writes:
  - data/runtime/runtime_job_inventory_latest.json
  - docs/architecture/PHASE199B_RUNTIME_JOB_INVENTORY.md

Pure read-only: runs `crontab -l` / `systemctl` and reads script files. Mutates NO runtime state.
"""
import json, os, re, subprocess
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_JSON = os.path.join(ROOT, "data", "runtime", "runtime_job_inventory_latest.json")
OUT_MD = os.path.join(ROOT, "docs", "architecture", "PHASE199B_RUNTIME_JOB_INVENTORY.md")

CATEGORIES = ["24_7_SERVICE", "MARKET_PIPELINE", "MARKET_MORNING", "AFTER_CLOSE", "OVERNIGHT_BATCH",
              "HERMES_ADVISORY", "HERMES_RESEARCH", "LLM_QUEUE", "GOVERNANCE",
              "PORTFOLIO_MAINTENANCE", "DATA_FEED", "LEGACY_DUPLICATE", "UNKNOWN"]

# keyword → category rules (first match wins; evaluated against script name + command)
RULES = [
    ("HERMES_ADVISORY", ["advisory-cache", "advisory_cache", "observation-check", "protection_pipeline",
                          "run_protection", "second_opinion", "safe_view"]),
    ("HERMES_RESEARCH", ["hermes_news_bridge", "hermes_topic", "source-discovery", "source_discovery",
                         "librarian", "catalyst_momentum", "momentum-catalyst", "embedding-promotion",
                         "research_insight", "atp2_research", "intel_auto_discovery", "topic_ingestion"]),
    ("LLM_QUEUE", ["deep_overnight_llm", "high_llm", "llm_window", "gemma_pilot", "llm_intelligence",
                   "process_high_llm", "build_deep_overnight"]),
    ("MARKET_MORNING", ["morning", "premarket", "alex_daily", "run_alex"]),
    ("AFTER_CLOSE", ["after_close", "afterhours", "trade_close", "multi_tier_trade_reviewer",
                     "eod_", "outcome", "mfe", "journal", "daily_digest", "send_alert_digest"]),
    ("OVERNIGHT_BATCH", ["overnight_batch", "overnight", "nightly", "calibration"]),
    ("MARKET_PIPELINE", ["quote_refresh", "screener", "finviz", "orchestrator", "proposal",
                         "watchpool", "watchlist_agent", "stale_proposal", "open_trade", "atm_position",
                         "reconcil", "protection", "scalp", "execution_time_reval", "trade_strategy"]),
    ("DATA_FEED", ["external_market_data", "news_ingestion", "news_to_catalyst", "market_regime",
                   "data_gap", "sec_form4", "price_cache", "reprice"]),
    ("GOVERNANCE", ["governance", "operator_readiness", "maturity", "system_facts", "a1a_check",
                    "system_health", "system_freshness", "freshness_watchdog", "job_health",
                    "report_", "state_of_repo", "audit"]),
    ("PORTFOLIO_MAINTENANCE", ["backup", "retention", "rebalance", "tax", "portfolio-backup",
                               "portfolio-daily", "portfolio-monthly", "portfolio-weekly", "lookthrough"]),
    ("24_7_SERVICE", ["gateway", "heartbeat-receiver", "portfolio-server", "continuous", "-server"]),
]


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return ""


def classify(text):
    t = text.lower()
    for cat, kws in RULES:
        if any(k in t for k in kws):
            return cat
    return "UNKNOWN"


def scan_script(rel):
    """Static dependency scan of a script file (best-effort)."""
    path = os.path.join(ROOT, rel)
    info = {"exists": os.path.exists(path), "db_write": False, "llm": False, "telegram": False,
            "broker": False, "api": False, "market_hours_gate": False}
    if not info["exists"]:
        return info
    try:
        src = open(path, errors="ignore").read().lower()
    except Exception:
        return info
    info["db_write"] = any(k in src for k in ("insert into", "update ", "_db_write", "psycopg2", "conn.commit"))
    info["llm"] = any(k in src for k in ("ollama", "local_llm", "gemma", "qwen", "11434", "generate("))
    info["telegram"] = "telegram" in src
    info["broker"] = any(k in src for k in ("alpaca", "schwab", "broker_confirm", "submit_order"))
    info["api"] = any(k in src for k in ("requests.", "urllib.request", "http"))
    info["market_hours_gate"] = "market_day_gate" in src or "is_market_open" in src or "rth" in src
    return info


SCRIPT_RE = re.compile(r"scripts/[A-Za-z0-9_]+\.(?:py|sh)")
LOCK_RE = re.compile(r"/tmp/[A-Za-z0-9_.]+\.lock")
LOG_RE = re.compile(r"logs/[A-Za-z0-9_./-]+\.log")


def parse_cron():
    out = sh("crontab -l 2>/dev/null")
    jobs = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^((?:\S+\s+){5})(.*)$", line)
        if not m:
            continue
        sched, cmd = m.group(1).strip(), m.group(2).strip()
        scripts = SCRIPT_RE.findall(cmd)
        primary = next((s for s in SCRIPT_RE.finditer(cmd)
                        if "safe_flock" not in s.group(0) and "market_day_gate" not in s.group(0)), None)
        primary = primary.group(0) if primary else (scripts[0] if scripts else None)
        locks = LOCK_RE.findall(cmd)
        logs = LOG_RE.findall(cmd)
        market_gate = "market_day_gate" in cmd
        jobs.append({
            "kind": "cron", "schedule": sched, "command": cmd[:300], "script": primary,
            "lock": locks[0] if locks else None, "log": logs[0] if logs else None,
            "market_hours_dependent": market_gate,
            "category": classify(f"{primary or ''} {cmd}"),
            "deps": scan_script(primary) if primary else {},
        })
    return jobs


def parse_systemd():
    jobs = []
    # user + system services
    for scope in ("--user", ""):
        out = sh(f"systemctl {scope} list-units --type=service --all --no-legend --plain 2>/dev/null")
        for line in out.splitlines():
            parts = line.split(None, 4)
            if len(parts) < 4:
                continue
            name = parts[0]
            if not any(k in name for k in ("tradeai", "portfolio", "hermes", "heartbeat", "aegis", "db-retention")):
                continue
            active, sub = parts[2], parts[3]
            desc = parts[4] if len(parts) > 4 else ""
            jobs.append({"kind": f"systemd-service{scope or '-system'}", "name": name,
                         "active": active, "sub": sub, "description": desc[:120],
                         "category": classify(f"{name} {desc}")})
    # user timers
    out = sh("systemctl --user list-timers --all --no-legend 2>/dev/null")
    for line in out.splitlines():
        m = re.search(r"(\S+\.timer)\s+(\S+\.service)", line)
        if m:
            jobs.append({"kind": "systemd-timer", "name": m.group(1), "unit": m.group(2),
                         "category": classify(m.group(1) + " " + m.group(2))})
    return jobs


def analyze(cron, systemd):
    scripts = [j["script"] for j in cron if j["script"]]
    script_counts = {s: scripts.count(s) for s in set(scripts)}
    dup_scripts = {s: n for s, n in script_counts.items() if n > 1}
    lock_map = defaultdict(set)
    for j in cron:
        if j["lock"]:
            lock_map[j["lock"]].add(j["script"])
    lock_collisions = {lk: sorted(s for s in v if s) for lk, v in lock_map.items()
                       if len({s for s in v if s}) > 1}
    cat_counts = defaultdict(int)
    for j in cron + systemd:
        cat_counts[j["category"]] += 1
    return {
        "total_cron_lines": len(cron),
        "total_systemd_services": len([j for j in systemd if "service" in j["kind"]]),
        "total_systemd_timers": len([j for j in systemd if j["kind"] == "systemd-timer"]),
        "unique_scripts": len(set(scripts)),
        "duplicate_scripts": dict(sorted(dup_scripts.items(), key=lambda x: -x[1])),
        "lock_file_collisions": lock_collisions,
        "category_counts": dict(cat_counts),
    }


def main():
    cron = parse_cron()
    systemd = parse_systemd()
    summary = analyze(cron, systemd)
    inv = {"generated_note": "Phase 199B runtime inventory (read-only)", "summary": summary,
           "cron_jobs": cron, "systemd_jobs": systemd}
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(inv, f, indent=2)

    L = []
    L.append("# Phase 199B — Runtime Job Inventory\n")
    L.append("Generated by `scripts/inventory_runtime_jobs.py` (READ-ONLY — mutates no runtime state).\n")
    s = summary
    L.append("## Totals")
    L.append(f"- Cron job lines: **{s['total_cron_lines']}**")
    L.append(f"- systemd services (tradeai/hermes/portfolio): **{s['total_systemd_services']}**")
    L.append(f"- systemd user timers: **{s['total_systemd_timers']}**")
    L.append(f"- Unique cron scripts: **{s['unique_scripts']}**")
    L.append(f"- Duplicate (multi-scheduled) scripts: **{len(s['duplicate_scripts'])}**")
    L.append(f"- Lock-file collisions (same lock, ≥2 scripts): **{len(s['lock_file_collisions'])}**\n")
    L.append("## Category distribution")
    for c in CATEGORIES:
        if s["category_counts"].get(c):
            L.append(f"- {c}: {s['category_counts'][c]}")
    L.append("\n## Duplicate / multi-scheduled scripts (merge candidates)")
    L.append("| script | cron lines | category |")
    L.append("|--------|-----------:|----------|")
    for sc, n in s["duplicate_scripts"].items():
        cat = next((j["category"] for j in cron if j["script"] == sc), "?")
        L.append(f"| `{sc}` | {n} | {cat} |")
    L.append("\n## Lock-file collisions (serialization risk)")
    if s["lock_file_collisions"]:
        for lk, scs in s["lock_file_collisions"].items():
            L.append(f"- `{lk}` shared by: {', '.join('`'+x+'`' for x in scs)}")
    else:
        L.append("- none")
    L.append("\n## Systemd units")
    L.append("| unit | kind | state | category |")
    L.append("|------|------|-------|----------|")
    for j in systemd:
        st = j.get("active", j.get("unit", "—"))
        L.append(f"| `{j.get('name')}` | {j['kind']} | {st} | {j['category']} |")
    L.append("\n## Recommendations (heuristic — operator decides)")
    L.append("- **Can merge:** duplicate scripts above into a single pipeline-owned step.")
    L.append("- **Must stay separate:** 24_7_SERVICE units; market-hours-gated vs after-close jobs.")
    L.append("- **Lock collisions** = jobs already implicitly serialized — natural pipeline groupings.")
    L.append("- **Requires operator decision:** anything touching proposals / protection / LLM queue / Telegram.")
    L.append(f"\n## Provenance\n- JSON: `data/runtime/runtime_job_inventory_latest.json`")
    L.append("- Read-only; no runtime mutation. Classifications are heuristic; see 199C for the target model.")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(L) + "\n")

    print(f"[inventory] cron={s['total_cron_lines']} services={s['total_systemd_services']} "
          f"timers={s['total_systemd_timers']} unique_scripts={s['unique_scripts']} "
          f"dup_scripts={len(s['duplicate_scripts'])} lock_collisions={len(s['lock_file_collisions'])}")
    print(f"[inventory] wrote {OUT_JSON} and {OUT_MD}")


if __name__ == "__main__":
    main()
