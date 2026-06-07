#!/usr/bin/env python3
"""Phase 206B — Read-only inventory of legacy / retired Hermes agents and artifacts.

Scans the retired sidecar directories (and the active global Hermes home, for context) and produces a
classified, REDACTED inventory for the Command Center v3 "Legacy / Retired Agents" audit view.

SAFETY (hard guarantees):
  * READ-ONLY. Never executes any agent/wrapper, never starts/enables a service, never writes outside
    data/hermes/legacy_agent_inventory_latest.json.
  * Never prints or stores secrets: SOUL/config text is scanned only for non-secret fields (model,
    tools, purpose); any line that looks like a key/token/secret/password/env value is REDACTED.
  * Does not migrate, rebuild, or re-home anything.

Classifications: ACTIVE_PROFILE | RETIRED_AGENT | RETIRED_WRAPPER | RETIRED_SOUL | UNKNOWN_LEGACY |
                 UNSAFE_RUNTIME_ARTIFACT
"""
import os, sys, json, re, stat
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()
OUT = ROOT / "data" / "hermes" / "legacy_agent_inventory_latest.json"

SECRET_RE = re.compile(r"(api[_-]?key|secret|token|password|bearer|BWS_ACCESS|client_secret|"
                       r"refresh_token|access_token|cookie)", re.I)
# runtime-state artifacts that must never be revived as live state
UNSAFE_NAMES = {"gateway_state.json", "channel_directory.json"}
UNSAFE_DIRS = {"sandboxes", "sessions", "pairing", "audio_cache", "image_cache"}
WRAPPER_NAMES = {"hermes", "hermes-acp", "hermes-agent", "tirith", "herm"}


def mtime(p):
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()
    except Exception:
        return None


def rel(p):
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p).replace(str(HOME), "~")


def safe_lines(path, limit=120):
    """Read a text file, dropping/redacting any secret-bearing line. Returns list of safe lines."""
    out = []
    try:
        for i, ln in enumerate(path.read_text(errors="replace").splitlines()):
            if i >= limit:
                break
            out.append("<redacted: possible secret>" if SECRET_RE.search(ln) else ln)
    except Exception:
        pass
    return out


def parse_config(cfg_path):
    """Extract model + tool policy from a Hermes config.yaml WITHOUT importing/executing. Redacted."""
    model = tools = None
    try:
        import yaml
        # load but never echo secret values
        d = yaml.safe_load(cfg_path.read_text(errors="replace")) or {}
        m = d.get("model") or {}
        model = m.get("default") if isinstance(m, dict) else None
        ts = d.get("toolsets")
        agent = d.get("agent") or {}
        disabled = agent.get("disabled_toolsets") if isinstance(agent, dict) else None
        tools = {"toolsets": ts, "disabled_toolsets": disabled}
    except Exception:
        pass
    return model, tools


def soul_purpose(soul_path):
    """First non-empty, non-secret sentence of a SOUL.md (identity summary)."""
    for ln in safe_lines(soul_path, limit=30):
        s = ln.strip()
        if s and not s.startswith("#"):
            return (s[:240] + "…") if len(s) > 240 else s
    return None


def item(name, path, source_dir, status, model=None, tools=None, purpose=None,
         safety_note="", migration=""):
    return {"name": name, "path": rel(path), "source_dir": source_dir, "status": status,
            "model": model, "tools": tools, "purpose": purpose,
            "last_modified": mtime(path), "safety_note": safety_note,
            "migration_recommendation": migration}


def scan_retired_home(d, source_label, items):
    # SOUL.md → RETIRED_SOUL
    soul = d / "SOUL.md"
    if soul.exists():
        items.append(item("Legacy sidecar SOUL", soul, source_label, "RETIRED_SOUL",
                          purpose=soul_purpose(soul),
                          safety_note="Un-hardened generic 'Hermes Agent' identity (allows tool actions); "
                                      "do NOT reuse verbatim for a Trade AI profile.",
                          migration="document only"))
    # config.yaml → RETIRED_AGENT
    cfg = d / "config.yaml"
    if cfg.exists():
        model, tools = parse_config(cfg)
        items.append(item("Legacy sidecar profile (config.yaml)", cfg, source_label, "RETIRED_AGENT",
                          model=model, tools=tools,
                          purpose="Old single-home Hermes sidecar profile (pre-v1.8 global-profile migration).",
                          safety_note="Retired config; not loaded by the live global Hermes install. Audit only.",
                          migration="candidate for manual profile rebuild (operator-approved, hardened SOUL)"))
    # wrappers in bin/
    for b in sorted((d / "bin").glob("*")) if (d / "bin").exists() else []:
        if b.is_file() and (b.name in WRAPPER_NAMES or os.access(b, os.X_OK)):
            items.append(item(b.name, b, source_label, "RETIRED_WRAPPER",
                              safety_note="Retired sidecar wrapper — DO NOT EXECUTE. Use the global `hermes`/`tradeai` CLIs.",
                              migration="unsafe/do not use"))
    # unsafe runtime-state artifacts (presence only — contents NOT exposed)
    for nm in UNSAFE_NAMES:
        p = d / nm
        if p.exists():
            items.append(item(nm, p, source_label, "UNSAFE_RUNTIME_ARTIFACT",
                              safety_note="Runtime/gateway state — not agent config; must not be revived. Contents not exposed.",
                              migration="keep retired"))
    for nm in UNSAFE_DIRS:
        p = d / nm
        if p.is_dir():
            items.append(item(nm + "/", p, source_label, "UNSAFE_RUNTIME_ARTIFACT",
                              safety_note="Retired runtime sandbox/session/cache dir — do not revive.",
                              migration="keep retired"))


def scan_retired_install(d, source_label, items):
    binp = d / ".venv" / "bin"
    for nm in WRAPPER_NAMES:
        p = binp / nm
        if p.exists():
            items.append(item(nm, p, source_label, "RETIRED_WRAPPER",
                              safety_note="Retired sidecar install wrapper — DO NOT EXECUTE (rollback/audit only).",
                              migration="unsafe/do not use"))


def scan_active(items):
    # active global home + profiles → ACTIVE_PROFILE (context; the live panel covers these)
    for cfg in [HOME / ".hermes" / "config.yaml"] + sorted((HOME / ".hermes" / "profiles").glob("*/config.yaml")):
        if cfg.exists():
            prof = "default" if cfg.parent == (HOME / ".hermes") else cfg.parent.name
            model, tools = parse_config(cfg)
            items.append(item(prof, cfg, "~/.hermes (active)", "ACTIVE_PROFILE", model=model, tools=tools,
                              safety_note="Active global profile (managed live in System → Hermes).",
                              migration="keep active"))


def main():
    items = []
    # retired sidecar homes
    for d in sorted(ROOT.joinpath("hermes_sidecar").glob(".hermes.RETIRED_*")) if ROOT.joinpath("hermes_sidecar").exists() else []:
        scan_retired_home(d, d.name, items)
    # retired installs
    for d in sorted(ROOT.joinpath("hermes_sidecar").glob("install.RETIRED_*")) if ROOT.joinpath("hermes_sidecar").exists() else []:
        scan_retired_install(d, d.name, items)
    # active (context)
    scan_active(items)

    from collections import Counter
    by_status = dict(Counter(i["status"] for i in items))
    report = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "retired_dirs": sorted([d.name for d in ROOT.joinpath("hermes_sidecar").glob(".hermes.RETIRED_*")] +
                               [d.name for d in ROOT.joinpath("hermes_sidecar").glob("install.RETIRED_*")])
                        if ROOT.joinpath("hermes_sidecar").exists() else [],
        "counts": by_status,
        "total": len(items),
        "warning": "Retired sidecar artifacts are shown for audit only. Do not enable the retired gateway "
                   "or execute retired wrappers. Secrets are redacted; runtime-state contents are not exposed.",
        "items": items,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({"total": report["total"], "counts": by_status,
                      "retired_dirs": report["retired_dirs"], "out": str(rel(OUT))}, indent=2))
    return report


if __name__ == "__main__":
    main()
