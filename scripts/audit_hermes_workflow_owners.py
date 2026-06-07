#!/usr/bin/env python3
"""audit_hermes_workflow_owners.py — map Hermes workflows to owner scripts/timers/cadence/DB (Phase 209C).
Read-only. Output: data/hermes/hermes_workflow_owner_matrix_latest.json"""
import os, json, glob, re, subprocess
from pathlib import Path

HOME = Path.home()
UNIT = HOME / ".config/systemd/user"
SCR = Path(__file__).resolve().parent
HTABLES = ["hermes_research_intelligence", "hermes_alerts", "hermes_validation_findings",
           "hermes_memory_events", "hermes_embedding_queue", "hermes_promotion_audit"]
SAFE_VIEW = re.compile(r"\b(\w*safe\w*view\w*|hermes_v_\w+)\b", re.I)


def sh(cmd, t=6):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=t,
                              env={**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}).stdout
    except Exception:
        return ""


def unit_val(unit, prop):
    return sh(["systemctl", "--user", "show", unit, "-p", prop, "--value"]).strip()


def script_io(path):
    """grep a script for DB table reads/writes + safe views + LLM + telegram."""
    try:
        s = Path(path).read_text(errors="ignore")
    except Exception:
        return {}
    low = s.lower()
    writes = sorted({t for t in HTABLES if re.search(r"insert into\s+" + t + r"|update\s+" + t, low)})
    reads = sorted({t for t in HTABLES if re.search(r"from\s+" + t + r"|join\s+" + t, low)})
    safe_views = sorted(set(m.group(0) for m in SAFE_VIEW.finditer(s)))[:6]
    return {"writes": writes, "reads": reads, "safe_views": safe_views,
            "uses_llm": bool(re.search(r"ollama|/api/chat|/api/generate|llm|gemma", low)),
            "telegram_siem": bool(re.search(r"telegram|siem|alert_event", low)),
            "promotion_embedding": bool(re.search(r"promot|embed", low))}


def main():
    rows = []
    for sp in sorted(glob.glob(str(UNIT / "hermes-*.service"))):
        name = Path(sp).stem
        txt = Path(sp).read_text(errors="ignore")
        execs = re.findall(r"ExecStart=(.+)", txt)
        cmd = " ; ".join(e.strip() for e in execs)
        # owner script
        m = re.search(r"scripts/([a-zA-Z0-9_./-]+\.py)", cmd)
        owner = m.group(1) if m else None
        timer = name + ".timer"
        cadence = unit_val(timer, "TimersCalendar") or unit_val(timer, "TimersMonotonic") or "?"
        last = unit_val(name + ".service", "Result")
        io = script_io(SCR / owner.split("scripts/")[-1].split("/")[-1]) if owner else {}
        # owner is scripts/<file>; resolve path
        opath = SCR / Path(owner).name if owner else None
        io = script_io(opath) if (opath and opath.exists()) else {}
        rows.append({
            "workflow": name.replace("hermes-", ""), "owner_script": ("scripts/" + Path(owner).name) if owner else None,
            "trigger": "systemd timer", "cadence": cadence[:80], "command": cmd[:200],
            "standalone_python": bool(owner), "cli_profile_used": ("-p " in cmd or "/bin/tradeai" in cmd),
            "last_result": last, **io})
    # cron hermes jobs (owner = script)
    for ln in (sh(["crontab", "-l"]) or "").splitlines():
        if ln.strip().startswith("#") or not ln.strip():
            continue
        if re.search(r"hermes|librarian|coordinator|momentum|advisory", ln, re.I):
            m = re.search(r"scripts/([a-zA-Z0-9_./-]+\.py)", ln)
            owner = ("scripts/" + Path(m.group(1)).name) if m else None
            opath = SCR / Path(m.group(1)).name if m else None
            io = script_io(opath) if (opath and opath.exists()) else {}
            sm = re.match(r"^([\d*/, ]+)", ln.strip())
            rows.append({"workflow": "cron:" + (Path(owner).stem if owner else ln[:30]), "owner_script": owner,
                         "trigger": "cron", "cadence": (sm.group(1).strip() if sm else "?"), "command": ln[:200],
                         "standalone_python": bool(owner), "cli_profile_used": False, "last_result": "n/a", **io})
    out = {"generated_note": "Phase 209C workflow owner matrix", "workflow_count": len(rows),
           "all_standalone_python": all(r.get("standalone_python") for r in rows if r["trigger"] == "systemd timer"),
           "any_cli_profile_in_jobs": any(r.get("cli_profile_used") for r in rows),
           "writers": sorted({t for r in rows for t in r.get("writes", [])}),
           "rows": rows}
    Path("data/hermes").mkdir(parents=True, exist_ok=True)
    Path("data/hermes/hermes_workflow_owner_matrix_latest.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({"workflow_count": out["workflow_count"], "all_standalone_python": out["all_standalone_python"],
          "any_cli_profile_in_jobs": out["any_cli_profile_in_jobs"], "writers": out["writers"],
          "owners": [(r["workflow"], r["owner_script"], r.get("writes")) for r in rows if r["trigger"] == "systemd timer"]}, indent=2))


if __name__ == "__main__":
    main()
