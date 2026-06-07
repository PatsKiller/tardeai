#!/usr/bin/env python3
"""audit_hermes_identities.py — inventory + classify all Hermes/Hermit identities (Phase 208B).
Read-only. No secrets printed. Output: data/hermes/hermes_identity_audit_latest.json"""
import os, json, hashlib, subprocess, glob
from pathlib import Path

HOME = Path.home()
HERMES_HOME = HOME / ".hermes"
SIDECAR = Path(__file__).resolve().parent.parent / "hermes_sidecar"
PROFILES = ["default", "tradeai", "tradeai12b", "dev", "serverops"]
# Live research-fleet agents (HermesHub graph; run via systemd timers + scripts/hermes_*.py, NOT profiles)
FLEET = {
    "coordinator": "hermes_coordinator.py", "source_discovery": "hermes_scheduled_source_discovery_dryrun.py",
    "librarian": "hermes_autonomous_librarian_backlog_loop.py", "embedding_curator": "hermes_embedding_promotion_reviewer.py",
    "promotion_review": "hermes_embedding_promotion_reviewer.py", "backlog_manager": "hermes_backlog_health_check.py",
    "autonomous_research": "hermes_autonomous_loop.py",
}


def sh(cmd, t=12, env=None):
    try:
        e = dict(os.environ); e.update(env or {})
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=t, env=e)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def soul_info(p):
    if not p.exists():
        return {"exists": False, "hash": None, "first_line": None, "mtime": None}
    txt = p.read_text(errors="ignore")
    return {"exists": True, "hash": hashlib.sha256(txt.encode()).hexdigest()[:16],
            "first_line": (txt.splitlines() or [""])[0][:120], "mtime": int(p.stat().st_mtime), "bytes": len(txt)}


def prof_model(name):
    sub = "" if name == "default" else f"profiles/{name}"
    cfg = (HERMES_HOME / sub / "config.yaml")
    try:
        import yaml
        return ((yaml.safe_load(cfg.read_text()) or {}).get("model") or {}).get("default")
    except Exception:
        return None


def prof_tools(name):
    out = sh([str(HOME / ".local/bin/hermes"), "-p", name, "tools", "list"])
    import re
    en = [m.group(1) for ln in out.splitlines() if (m := re.match(r"\s*✓ enabled\s\s+([a-z][a-z_]*)", ln))]
    return en


def main():
    ids = []
    # ACTIVE_GLOBAL_PROFILE
    for name in PROFILES:
        sub = "" if name == "default" else f"profiles/{name}"
        d = HERMES_HOME / sub
        soul = soul_info(d / "SOUL.md")
        model = prof_model(name)
        tools = prof_tools(name)
        ids.append({
            "name": name, "classification": "ACTIVE_GLOBAL_PROFILE",
            "path": str(d).replace(str(HOME), "~"), "wrapper": (f"~/.local/bin/{name}" if name != "default" else "~/.local/bin/hermes"),
            "model": model or "unset", "tools_enabled": tools, "tools_count": len(tools),
            "soul_hash": soul["hash"], "soul_first_line": soul["first_line"], "soul_mtime": soul.get("mtime"),
            "purpose": {"default": "general", "tradeai": "Trade AI advisory", "tradeai12b": "experimental 12B advisory",
                        "dev": "Codex/dev (future)", "serverops": "server ops (future)"}[name],
            "safety_policy": "tools 0 / restricted" if name in ("tradeai", "tradeai12b") else
                             ("dangerous tools disabled" if name == "dev" else "general/unconfigured"),
            "recommendation": "keep active",
        })
    # ACTIVE_RESEARCH_FLEET_AGENT
    for fid, script in FLEET.items():
        exists = (Path(__file__).resolve().parent / script).exists()
        ids.append({"name": fid, "classification": "ACTIVE_RESEARCH_FLEET_AGENT",
                    "path": f"scripts/{script}", "runner": "project .venv + systemd timer", "model": "gemma3 (Ollama) where LLM",
                    "tools_enabled": [], "soul_hash": None, "purpose": "Trade AI research workflow",
                    "safety_policy": "reads Trade AI safe views; staging/advisory only; no broker",
                    "recommendation": "keep active" if exists else "investigate orphan",
                    "script_exists": exists})
    # RETIRED artifacts
    for d in sorted(glob.glob(str(SIDECAR / ".hermes.RETIRED_*")) + glob.glob(str(SIDECAR / "install.RETIRED_*"))):
        pd = Path(d)
        cls = "RETIRED_SIDECAR_PROFILE" if ".hermes" in pd.name else "RETIRED_RUNTIME_ARTIFACT"
        ids.append({"name": pd.name, "classification": cls, "path": f"hermes_sidecar/{pd.name}",
                    "model": "n/a", "tools_enabled": [], "soul_hash": soul_info(pd / "SOUL.md")["hash"],
                    "mtime": int(pd.stat().st_mtime), "purpose": "rollback/audit evidence",
                    "safety_policy": "read-only; never executed", "recommendation": "keep retired"})
    # RETIRED_WRAPPER (sidecar wrappers now stubs)
    for w in ("run_hermes_readonly.sh", "run_hermes_gateway.sh"):
        wp = SIDECAR / w
        if wp.exists():
            txt = wp.read_text(errors="ignore")
            ids.append({"name": w, "classification": "RETIRED_WRAPPER", "path": f"hermes_sidecar/{w}",
                        "is_stub": "retired" in txt.lower(), "purpose": "retirement stub (exit 2)",
                        "safety_policy": "prints retirement + exits; never launches sidecar", "recommendation": "keep retired"})

    counts = {}
    for i in ids:
        counts[i["classification"]] = counts.get(i["classification"], 0) + 1
    # conflict detection: duplicate soul hashes among active
    active_souls = {}
    for i in ids:
        if i["classification"] == "ACTIVE_GLOBAL_PROFILE" and i.get("soul_hash"):
            active_souls.setdefault(i["soul_hash"], []).append(i["name"])
    dup = {h: n for h, n in active_souls.items() if len(n) > 1}
    out = {"generated_note": "Phase 208B read-only identity audit", "counts": counts,
           "duplicate_active_soul_hashes": dup, "identities": ids}
    Path("data/hermes").mkdir(parents=True, exist_ok=True)
    Path("data/hermes/hermes_identity_audit_latest.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({"counts": counts, "duplicate_active_souls": dup,
                      "profiles": [(i["name"], i["model"], i["tools_count"]) for i in ids if i["classification"] == "ACTIVE_GLOBAL_PROFILE"],
                      "fleet": [(i["name"], i["script_exists"]) for i in ids if i["classification"] == "ACTIVE_RESEARCH_FLEET_AGENT"]}, indent=2))


if __name__ == "__main__":
    main()
