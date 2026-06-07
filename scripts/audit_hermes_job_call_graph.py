#!/usr/bin/env python3
"""audit_hermes_job_call_graph.py — map Hermes jobs (systemd + cron) to agents/runtime (Phase 208D).
Read-only. Output: data/hermes/hermes_job_call_graph_latest.json"""
import os, json, glob, subprocess, re
from pathlib import Path

HOME = Path.home()
UNIT_DIR = HOME / ".config/systemd/user"
RETIRED = ["hermes_sidecar/.hermes", "hermes_sidecar/install", "run_hermes_gateway", "run_hermes_readonly",
           "install/.venv/bin/hermes", ".hermes.RETIRED", "install.RETIRED"]
BROKER = ["submit_order", "place_order", "cancel_order", "replace_order", "broker", "/stops", "proposal_execution",
          "go_no_go", "live_trading"]


def sh(cmd, t=8):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=t,
                              env={**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}).stdout
    except Exception:
        return ""


def classify(cmd):
    low = cmd.lower()
    touches_retired = [r for r in RETIRED if r.lower() in low]
    uses_broker = [b for b in BROKER if b in low]
    return {
        "uses_active_runtime": (".venv/bin/python" in cmd or "/.local/share/hermes-agent-venv" in cmd) and not touches_retired,
        "touches_retired_path": touches_retired,
        "uses_llm": ("--apply" in cmd or "ollama" in low or "llm" in low or "challenger" in low or "reviewer" in low),
        "uses_broker_or_trading": uses_broker,
        "reads_safe_views": ("safe" in low or "hermes" in low),
        "telegram_siem": ("telegram" in low or "siem" in low),
        "safety": ("UNSAFE: retired path" if touches_retired else
                   "REVIEW: broker keyword" if uses_broker else "OK: active research/advisory"),
    }


def main():
    jobs = []
    # systemd hermes services (Type=oneshot run by .timer)
    for sp in sorted(glob.glob(str(UNIT_DIR / "hermes-*.service"))):
        txt = Path(sp).read_text(errors="ignore")
        execs = re.findall(r"ExecStart=(.+)", txt)
        cmd = " ; ".join(e.strip() for e in execs)
        name = Path(sp).stem
        jobs.append({"job": name, "source": "systemd", "schedule": "timer", "command": cmd[:300], **classify(cmd)})
    # crontab hermes lines
    cron = sh(["crontab", "-l"])
    for ln in cron.splitlines():
        if ln.strip().startswith("#") or not ln.strip():
            continue
        if re.search(r"hermes|coordinator|librarian|research|embedding|promotion", ln, re.I):
            m = re.match(r"^([\d*/, ]+)\s+(.*)$", ln.strip())
            sched = m.group(1).strip() if m else "?"
            cmd = m.group(2) if m else ln
            jobs.append({"job": "cron:" + cmd[:40], "source": "cron", "schedule": sched, "command": cmd[:300], **classify(cmd)})

    out = {
        "generated_note": "Phase 208D read-only job call graph",
        "job_count": len(jobs),
        "any_job_calls_retired_wrapper": any(j["touches_retired_path"] for j in jobs),
        "any_job_depends_on_retired_gateway": any("gateway" in (str(j["touches_retired_path"]).lower()) for j in jobs),
        "jobs_touching_retired": [j["job"] for j in jobs if j["touches_retired_path"]],
        "jobs_with_broker_keyword": [j["job"] for j in jobs if j["uses_broker_or_trading"]],
        "all_active_use_active_runtime": all(j["uses_active_runtime"] for j in jobs if j["source"] == "systemd"),
        "jobs": jobs,
    }
    Path("data/hermes").mkdir(parents=True, exist_ok=True)
    Path("data/hermes/hermes_job_call_graph_latest.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({k: out[k] for k in ("job_count", "any_job_calls_retired_wrapper",
          "any_job_depends_on_retired_gateway", "jobs_touching_retired", "jobs_with_broker_keyword",
          "all_active_use_active_runtime")}, indent=2))


if __name__ == "__main__":
    main()
