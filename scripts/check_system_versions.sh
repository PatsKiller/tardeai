#!/usr/bin/env bash
# Weekly system version check — writes latest versions to a JSON cache
# Cron: Sunday 06:00 via crontab
# Output: data/state/system_versions_latest.json
set -euo pipefail

ROOT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
OUT="$ROOT/data/state/system_versions_latest.json"
LOG="$ROOT/logs/version_check.log"

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $1" >> "$LOG"; }
log "=== version check start ==="

cd "$ROOT"

python3 - << 'PYEOF'
import subprocess, json, re, urllib.request, os, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
OUT = ROOT / "data" / "state" / "system_versions_latest.json"

def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except:
        return None

def ver(raw):
    if not raw: return None
    m = re.search(r'(\d+\.\d+[\.\d]*)', raw)
    return m.group(1) if m else raw[:60]

def pip_latest(pkg):
    raw = run([str(ROOT / ".venv/bin/pip"), "index", "versions", pkg])
    if raw:
        m = re.search(r'\((\S+)\)', raw)
        return m.group(1) if m else None
    return None

def npm_latest(pkg):
    return ver(run(["npm", "view", pkg, "version"]))

def gh_latest(repo):
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                     headers={"Accept": "application/vnd.github+json"})
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read()).get("tag_name", "").lstrip("v")
    except:
        return None

def apt_latest(pkg):
    raw = run(["apt-cache", "policy", pkg])
    if raw:
        m = re.search(r'Candidate:\s*(\S+)', raw)
        return ver(m.group(1)) if m else None
    return None

versions = {
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "packages": {
        "python3": {"latest": apt_latest("python3"), "installed": ver(run(["python3", "--version"]))},
        "nodejs": {"latest": npm_latest("node") or apt_latest("nodejs"), "installed": ver(run(["node", "--version"]))},
        "npm": {"latest": npm_latest("npm"), "installed": ver(run(["npm", "--version"]))},
        "postgresql": {"latest": apt_latest("postgresql-17"), "installed": ver(run(["psql", "--version"]))},
        "git": {"latest": apt_latest("git"), "installed": ver(run(["git", "--version"]))},
        "ollama": {"latest": gh_latest("ollama/ollama"), "installed": ver(run(["ollama", "--version"]))},
        "tailscale": {"latest": gh_latest("tailscale/tailscale"), "installed": ver(run(["tailscale", "version"]))},
        "hermes-agent": {"latest": pip_latest("hermes-agent"), "installed": None},
        "claude-code": {"latest": npm_latest("@anthropic-ai/claude-code"), "installed": ver(run([str(Path.home() / ".local/bin/claude"), "--version"]))},
        "react": {"latest": npm_latest("react")},
        "react-router-dom": {"latest": npm_latest("react-router-dom")},
        "vite": {"latest": npm_latest("vite")},
        "typescript": {"latest": npm_latest("typescript")},
        "chart.js": {"latest": npm_latest("chart.js")},
    }
}

# Hermes installed version (global install; sidecar retired 2026-06-06)
hpip = run([str(Path.home() / ".local/share/hermes-agent-venv/bin/pip"), "show", "hermes-agent"])
if hpip:
    m = re.search(r'Version:\s*(\S+)', hpip)
    versions["packages"]["hermes-agent"]["installed"] = m.group(1) if m else None

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(versions, indent=2))
print(f"Wrote {len(versions['packages'])} packages to {OUT}")
PYEOF

log "=== version check done ==="
