#!/usr/bin/env python3
"""Read-only host baseline. Writes only to this evidence directory; never reads secret files."""

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
NOW = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def redact(s):
    s = re.sub(
        r"(?i)((?:[A-Z_]*(?:TOKEN|PASSWORD|SECRET|BEARER|API_KEY|HMAC_KEY|CREDENTIAL)[A-Z_]*)\s*[=:]\s*)([^\s,;]+)",
        r"\1[REDACTED]",
        s,
    )
    s = re.sub(r'(?i)(Authorization\s*[:=]\s*|Bearer\s+)[^\s"\']+', r"\1[REDACTED]", s)
    s = re.sub(r"(https?://)[^/@\s:]+:[^/@\s]+@", r"\1[REDACTED]@", s)
    return s


def cmd(args, timeout=20, redact_output=True):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return {
            "command": args,
            "exit": p.returncode,
            "stdout": redact(p.stdout) if redact_output else p.stdout,
            "stderr": redact(p.stderr),
            "as_of": NOW,
        }
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"command": args, "exit": None, "error": type(e).__name__, "evidence_class": "BLOCKED", "as_of": NOW}


def save(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2) + "\n")


def git(*args, cwd=ROOT):
    return cmd(["git", "-C", str(cwd), *args])


pin = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
release = pin.resolve()
identity = {
    "as_of": NOW,
    "evidence_class": "OBSERVED_CURRENT",
    "origin_main": git("rev-parse", "origin/main"),
    "HEAD": git("rev-parse", "HEAD"),
    "merge_base": git("merge-base", "HEAD", "origin/main"),
    "worktree": git("status", "--porcelain=v1"),
    "primary_worktree": git(
        "status", "--porcelain=v1", cwd=Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
    ),
    "CURRENT_release": str(release),
    "CURRENT_SHA": git("rev-parse", "HEAD", cwd=release),
}
pid_result = cmd(["systemctl", "--user", "show", "portfolio-server.service", "--property=MainPID", "--value"])
pid = pid_result.get("stdout", "").strip()
identity["portfolio_server"] = {
    "pid": pid,
    "cwd": str(Path("/proc", pid, "cwd").resolve()) if pid.isdigit() else None,
    "unit": cmd(
        [
            "systemctl",
            "--user",
            "show",
            "portfolio-server.service",
            "--property=ActiveState,SubState,FragmentPath,WorkingDirectory,ExecStart,ActiveEnterTimestamp",
        ]
    ),
}
for key, url in [
    ("api_health", "http://127.0.0.1:7777/api/health"),
    ("command_center_build", "http://127.0.0.1:7777/v3/build-meta.json"),
    ("n8n_health", "http://127.0.0.1:5678/healthz"),
]:
    try:
        with urlopen(url, timeout=8) as response:
            data = json.loads(response.read(128000))
            identity[key] = {"url": url, "status": response.status, "data": data, "as_of": NOW}
    except Exception as e:
        identity[key] = {"url": url, "evidence_class": "BLOCKED", "reason": type(e).__name__}
save("00-identity.json", identity)
commands = {
    "date": ["date", "--iso-8601=seconds"],
    "hostname": ["hostname"],
    "uptime": ["uptime"],
    "disk": ["df", "-h", "/"],
    "memory": ["free", "-m"],
    "docker": ["docker", "ps", "--format", "{{json .}}"],
    "compose_projects": ["docker", "compose", "ls", "--format", "json"],
    "user_units": ["systemctl", "--user", "list-units", "--all", "--no-pager", "--plain"],
    "user_timers": ["systemctl", "--user", "list-timers", "--all", "--no-pager", "--plain"],
    "user_unit_files": ["systemctl", "--user", "list-unit-files", "--no-pager", "--plain"],
    "system_units": ["systemctl", "list-units", "--all", "--no-pager", "--plain"],
    "system_unit_files": ["systemctl", "list-unit-files", "--no-pager", "--plain"],
    "cron": ["crontab", "-l"],
    "ports": ["ss", "-ltnpH"],
    "processes": ["ps", "-eo", "pid,ppid,lstart,etime,comm,args"],
}
host = {k: cmd(v) for k, v in commands.items()}
for key in ("processes", "system_units", "system_unit_files"):
    host[key]["stdout"] = "\n".join(
        x
        for x in host[key].get("stdout", "").splitlines()
        if re.search(r"trade|portfolio|openclaw|hermes|n8n|postgres|ollama|cio|moomoo|Futu|nginx|cron", x, re.I)
    )
save("00-host.json", {"as_of": NOW, "evidence_class": "OBSERVED_HOST", "HOST_RUNTIME_ACCESS": "AVAILABLE", **host})
props = "Id,LoadState,UnitFileState,ActiveState,SubState,FragmentPath,WorkingDirectory,ExecStart,EnvironmentFiles,MemoryMax,MemoryHigh,CPUQuotaPerSecUSec,Restart,RestartUSec,TimeoutStartUSec,TimersCalendar,TimersMonotonic,Persistent,RandomizedDelayUSec,Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp,ActiveEnterTimestamp,LastTriggerUSec,NextElapseUSecRealtime,MainPID,ControlGroup"
unit_names = sorted(
    {
        m.group(1)
        for line in host["user_unit_files"].get("stdout", "").splitlines()
        if (
            m := re.match(
                r"((?:tradeai|portfolio|cio|openclaw|hermes|system-health|telegram|health-agent)[^\s]*\.(?:service|timer))",
                line,
            )
        )
    }
)
units = {}
for name in unit_names:
    v = cmd(["systemctl", "--user", "show", name, "--property=" + props])
    parsed = dict(x.split("=", 1) for x in v.get("stdout", "").splitlines() if "=" in x)
    pid = parsed.get("MainPID", "")
    if pid.isdigit() and pid != "0":
        parsed["process_cwd"] = str(Path("/proc", pid, "cwd").resolve())
        parsed["process_executable"] = str(Path("/proc", pid, "exe").resolve())
    units[name] = {"properties": parsed, "exit": v["exit"], "evidence_class": "OBSERVED_HOST"}
save("04-systemd-units.json", {"as_of": NOW, "units": units})
containers = {}
safe_env = {
    "DB_TYPE",
    "DB_POSTGRESDB_HOST",
    "DB_POSTGRESDB_DATABASE",
    "DB_POSTGRESDB_USER",
    "POSTGRES_USER",
    "POSTGRES_DB",
    "EXECUTIONS_MODE",
    "EXECUTIONS_DATA_SAVE_ON_SUCCESS",
    "EXECUTIONS_DATA_SAVE_ON_ERROR",
    "EXECUTIONS_DATA_PRUNE",
    "EXECUTIONS_DATA_MAX_AGE",
    "EXECUTIONS_DATA_PRUNE_MAX_COUNT",
    "N8N_BLOCK_ENV_ACCESS_IN_NODE",
    "N8N_COMMUNITY_PACKAGES_ENABLED",
    "NODES_EXCLUDE",
    "N8N_PUBLIC_API_DISABLED",
    "N8N_PUBLIC_API_SWAGGERUI_DISABLED",
    "N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS",
    "N8N_DIAGNOSTICS_ENABLED",
    "N8N_METRICS",
    "N8N_LOG_LEVEL",
    "N8N_LOG_OUTPUT",
    "N8N_RUNNERS_ENABLED",
    "N8N_RUNNERS_MODE",
    "N8N_USER_MANAGEMENT_DISABLED",
    "N8N_MFA_ENABLED",
    "N8N_HOST",
    "N8N_PORT",
    "N8N_PROTOCOL",
    "N8N_PROXY_HOPS",
    "GENERIC_TIMEZONE",
    "TZ",
    "N8N_DEFAULT_BINARY_DATA_MODE",
    "OFFLOAD_MANUAL_EXECUTIONS_TO_WORKERS",
    "QUEUE_HEALTH_CHECK_ACTIVE",
}
for name in ("m8m-n8n", "m8m-n8n-db"):
    obs = cmd(["docker", "inspect", name], redact_output=False)
    if obs.get("exit") == 0:
        raw = json.loads(obs["stdout"])[0]
        env = dict(x.split("=", 1) for x in raw["Config"].get("Env", []) if "=" in x)
        containers[name] = {
            "image": raw["Config"]["Image"],
            "image_id": raw["Image"],
            "state": raw["State"],
            "restart_count": raw["RestartCount"],
            "created": raw["Created"],
            "healthcheck": raw["Config"].get("Healthcheck"),
            "ports": raw["NetworkSettings"].get("Ports"),
            "networks": raw["NetworkSettings"].get("Networks"),
            "mounts": raw["Mounts"],
            "compose_files": raw["Config"].get("Labels", {}).get("com.docker.compose.project.config_files"),
            "env_names": sorted(env),
            "safe_config": {k: v for k, v in env.items() if k in safe_env},
            "encryption_key_configured": bool(env.get("N8N_ENCRYPTION_KEY")),
        }
        containers[name]["image_digest"] = cmd(
            ["docker", "image", "inspect", raw["Image"], "--format", "{{json .RepoDigests}}"]
        )
    else:
        containers[name] = {"exit": obs.get("exit"), "evidence_class": "BLOCKED"}
save(
    "06-n8n-container.json",
    {
        "as_of": NOW,
        "evidence_class": "OBSERVED_HOST",
        "containers": containers,
        "version": cmd(["docker", "exec", "m8m-n8n", "n8n", "--version"]),
    },
)
jobs_path = Path.home() / ".openclaw/cron/jobs.json"
openclaw = {"as_of": NOW, "path": str(jobs_path), "evidence_class": "OBSERVED_HOST"}
if jobs_path.exists():
    raw = json.loads(jobs_path.read_text())
    jobs = raw.get("jobs", []) if isinstance(raw, dict) else raw
    openclaw["jobs"] = [
        {
            k: v
            for k, v in j.items()
            if k in ("id", "name", "agentId", "enabled", "schedule", "wakeMode", "createdAtMs", "updatedAtMs", "state")
        }
        | {
            "delivery_mode": j.get("delivery", {}).get("mode"),
            "delivery_channel": j.get("delivery", {}).get("channel"),
            "payload_kind": j.get("payload", {}).get("kind"),
            "payload_omitted": True,
        }
        for j in jobs
    ]
    openclaw["count"] = len(jobs)
else:
    openclaw.update(evidence_class="NOT_MEASURED", reason="jobs.json absent")
save("05-openclaw.json", openclaw)
md = (
    "# Current runtime baseline\n\nStatus: OBSERVED_CURRENT / OBSERVED_HOST\nOwner: platform\nas_of: "
    + NOW
    + "\nMeasured at: "
    + str(ROOT)
    + "\n\nHOST_RUNTIME_ACCESS=AVAILABLE\n\nRead-only measurement. No scheduler edits, restart, deploy, credential read, broker call or policy ratification.\n\n"
)
for k, v in identity.items():
    md += "## " + k + "\n\n```json\n" + json.dumps(v, indent=2) + "\n```\n\n"
md += "Host command outputs: `00-host.json`. Installed unit properties: `04-systemd-units.json`. Selected Docker metadata: `06-n8n-container.json`. OpenClaw scheduling metadata (payloads/destinations omitted): `05-openclaw.json`.\n\nPolicies contain contradictory ACTIVE/PROPOSED n8n authority assertions; no authority inferred. Prior cron counts and workflow exports are STALE_HISTORICAL until re-measured.\n"
(OUT / "00-current-baseline.md").write_text(md)
print(
    json.dumps(
        {
            "evidence": str(OUT),
            "as_of": NOW,
            "CURRENT": str(release),
            "units": len(units),
            "openclaw_jobs": openclaw.get("count"),
            "host_access": "AVAILABLE",
        }
    )
)
