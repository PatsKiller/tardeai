#!/usr/bin/env python3
"""audit_hermes_live_fleet_health.py — live Hermes research-fleet health (Phase 208E). Read-only.
Output: data/hermes/hermes_live_fleet_health_latest.json"""
import os, json, subprocess
from pathlib import Path
import psycopg2

# load .env minimally for DB creds (no secrets printed)
for ln in (Path(__file__).resolve().parent.parent / ".env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip())

TIMERS = ["hermes-autonomous-loop", "hermes-source-discovery-dryrun", "hermes-librarian-backlog-loop",
          "hermes-embedding-promotion-review", "hermes-backlog-health-check", "hermes-shadow-scorer",
          "hermes-observation-check", "hermes-advisory-cache-worker", "hermes-momentum-catalyst-morning"]


def timer_state(name):
    env = {**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
    def show(unit, prop):
        try:
            return subprocess.run(["systemctl", "--user", "show", unit, "-p", prop, "--value"],
                                  capture_output=True, text=True, timeout=6, env=env).stdout.strip()
        except Exception:
            return ""
    return {"timer": name, "timer_enabled": show(name + ".timer", "UnitFileState"),
            "last_trigger": show(name + ".timer", "LastTriggerUSec") or None,
            "service_result": show(name + ".service", "Result") or None,
            "service_exec": show(name + ".service", "ExecMainStatus") or None}


def main():
    c = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                         user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))
    cur = c.cursor()
    def q(s):
        try:
            cur.execute(s); return cur.fetchall()
        except Exception as e:
            c.rollback(); return [("err", str(e)[:80])]
    fleet = {}
    fleet["research_intelligence_total"] = q("SELECT count(*) FROM hermes_research_intelligence")[0][0]
    fleet["last_research_write"] = str(q("SELECT max(created_at) FROM hermes_research_intelligence")[0][0])
    fleet["by_research_type_top"] = [list(r) for r in q(
        "SELECT research_type, count(*) FROM hermes_research_intelligence GROUP BY 1 ORDER BY 2 DESC LIMIT 8")]
    fleet["by_status"] = [list(r) for r in q(
        "SELECT status, count(*) FROM hermes_research_intelligence GROUP BY 1 ORDER BY 2 DESC")]
    fleet["trade_instance_linked"] = q(
        "SELECT count(*) FROM hermes_research_intelligence WHERE trade_instance_id IS NOT NULL")[0][0]
    fleet["writes_last_24h"] = q(
        "SELECT count(*) FROM hermes_research_intelligence WHERE created_at > now()-interval '24 hours'")[0][0]
    fleet["writes_last_7d"] = q(
        "SELECT count(*) FROM hermes_research_intelligence WHERE created_at > now()-interval '7 days'")[0][0]
    for t in ("hermes_alerts", "hermes_validation_findings", "hermes_memory_events", "hermes_embedding_queue"):
        fleet[t + "_count"] = q(f"SELECT count(*) FROM {t}")[0][0]
    timers = [timer_state(t) for t in TIMERS]
    healthy = all((t["service_result"] in ("success", "", None)) for t in timers)
    out = {"generated_note": "Phase 208E read-only live fleet health", "fleet": fleet, "timers": timers,
           "all_timers_last_result_ok": healthy,
           "fleet_writing_recently": fleet["writes_last_7d"] > 0}
    Path("data/hermes").mkdir(parents=True, exist_ok=True)
    Path("data/hermes/hermes_live_fleet_health_latest.json").write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({"research_total": fleet["research_intelligence_total"], "last_write": fleet["last_research_write"],
          "writes_24h": fleet["writes_last_24h"], "writes_7d": fleet["writes_last_7d"],
          "trade_linked": fleet["trade_instance_linked"], "all_timers_ok": healthy,
          "timer_results": [(t["timer"], t["service_result"]) for t in timers]}, indent=2, default=str))
    c.close()


if __name__ == "__main__":
    main()
