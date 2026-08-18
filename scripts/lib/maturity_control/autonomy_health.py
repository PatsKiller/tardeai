"""Intelligence-loop autonomy panel (observe only; no remediation)."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.maturity_control.store import resolve_root

UNITS = (
    ("agent-runtime-producer", "tradeai-agent-runtime-producer.service", "tradeai-agent-runtime-producer.timer"),
    ("agent-runtime-health", "tradeai-agent-runtime-health.service", "tradeai-agent-runtime-health.timer"),
    ("nightly-reflection", "tradeai-cio-nightly-reflection.service", "tradeai-cio-nightly-reflection.timer"),
    ("material-scanner", "tradeai-cio-material-scan.service", "tradeai-cio-material-scan.timer"),
    ("notification-delivery", "tradeai-cio-delivery.service", "tradeai-cio-delivery.timer"),
    ("defer-revisit", "tradeai-cio-defer-revisit.service", "tradeai-cio-defer-revisit.timer"),
    ("reactive-cio", "tradeai-cio-reactive.service", "tradeai-cio-reactive.timer"),
    ("provider-cost", "tradeai-provider-cost-reconcile.service", "tradeai-provider-cost-reconcile.timer"),
)

FILE_PROBES = (
    ("AgentRunTrace", Path("data/cio/agent_run_traces.jsonl"), 6 * 3600),
    ("FinancialSenses", Path("data/cio/agent_tool_traces.jsonl"), 12 * 3600),
    ("reflection-history", Path("data/cio/cio_reflection_candidates.jsonl"), 36 * 3600),
    ("notification-state", Path("data/cio/cio_notification_state.jsonl"), 6 * 3600),
    ("provider-cost-events", Path("data/runtime/provider_cost/events.jsonl"), 36 * 3600),
)


def _show(unit: str) -> dict[str, str]:
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "show", unit,
             "-p", "ActiveState", "-p", "Result", "-p", "ExecMainStatus",
             "-p", "InactiveExitTimestamp", "-p", "ExecMainStartTimestamp",
             "-p", "NRestarts", "-p", "SubState"],
            capture_output=True, text=True, timeout=3,
        )
    except Exception as e:
        return {"error": type(e).__name__}
    out: dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k] = v
    return out


def _age_s(path: Path) -> float | None:
    try:
        return datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    except OSError:
        return None


def _freshness(age: float | None, max_s: float) -> str:
    if age is None:
        return "missing"
    return "fresh" if age <= max_s else "stale"


def collect_autonomy_health(*, root: Path | str | None = None) -> dict[str, Any]:
    base = resolve_root(root)
    components = []
    for name, svc, timer in UNITS:
        s = _show(svc)
        t = _show(timer)
        result = s.get("Result") or ""
        status = int(s.get("ExecMainStatus") or 0) if s.get("ExecMainStatus") else None
        classify = "unknown"
        if result == "success" and status == 0:
            classify = "expected_success"
        elif result == "success":
            classify = "expected_no_work"
        elif result in {"failed", "timeout", "exit-code"}:
            classify = "unexpected_failure"
        components.append({
            "id": name,
            "service": svc,
            "timer": timer,
            "timer_active": t.get("ActiveState"),
            "last_result": result,
            "last_exit": status,
            "last_success": s.get("InactiveExitTimestamp") if result == "success" else None,
            "last_failure": s.get("InactiveExitTimestamp") if result not in {"success", ""} else None,
            "consecutive_restarts": int(s.get("NRestarts") or 0),
            "classification": classify,
        })

    files = []
    for name, rel, max_s in FILE_PROBES:
        p = base / rel
        age = _age_s(p)
        files.append({
            "id": name,
            "path": str(rel),
            "age_seconds": None if age is None else round(age, 1),
            "freshness": _freshness(age, max_s),
        })

    current = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
    sha = ""
    try:
        sha = (current / "SOURCE_COMMIT").read_text(encoding="utf-8").strip()
    except OSError:
        sha = ""

    timers = []
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "list-timers", "--no-pager", "tradeai-agent-runtime@*"],
            capture_output=True, text=True, timeout=4,
        )
        timers = [ln.strip() for ln in (proc.stdout or "").splitlines() if "tradeai-agent-runtime@" in ln][:40]
    except Exception:
        pass

    return {
        "authority": "READ_ONLY_ADVISORY",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "current_sha": sha,
        "current_path": str(current.resolve()) if current.exists() else None,
        "components": components,
        "artifacts": files,
        "enabled_agent_timers": timers,
        "unexpected_failures": sum(1 for c in components if c["classification"] == "unexpected_failure"),
    }
