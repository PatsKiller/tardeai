"""A declared no-op protocol is required before any wrapper can be invoked.

Unknown/business/broker entrypoints are coverage gaps, never probed with --help
or by executing a real job. Caller supplies a captured cron text in fixtures.
"""
from __future__ import annotations

import grp
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

PROTOCOLS = {
    "scripts/safe_flock.sh": "safe_flock_true",
    "scripts/cron_wrapper.sh": "explicit_preflight_before_environment",
    "scripts/effect_claim_cron.sh": "unarmed_child_true",
    "scripts/market_day_gate.sh": "calendar_then_child_true",
    "scripts/llm_priority_guard.sh": "clock_gate_only",
    "scripts/run_with_deepseek_offpeak.sh": "offpeak_then_child_true",
    "scripts/non_trading_hours_gate.sh": "declared_dry_run_child_true",
}


def shell_inventory(cron_text: str) -> list[str]:
    return sorted({name for line in cron_text.splitlines() if not line.lstrip().startswith("#")
                   for name in re.findall(r"(?:scripts|bin)/[\w./-]+\.sh", line)})


def check_layout(current: Path) -> list[str]:
    issues = []
    if not current.is_symlink():
        issues.append("CURRENT_not_symlink")
    logs = current.resolve() / "logs"
    if not logs.is_symlink():
        issues.append("release_logs_not_symlink")
    try:
        st = logs.resolve(strict=True).stat()
        if st.st_mode & 0o777 != 0o775:
            issues.append("persistent_logs_mode_not_775")
        if st.st_gid != os.getegid() or grp.getgrgid(st.st_gid).gr_mem:
            issues.append("persistent_logs_group_not_callers_private_group")
    except (OSError, KeyError):
        issues.append("persistent_logs_unreadable")
    return issues


def _probe_argv(name: str, current: Path, scratch: Path) -> list[str]:
    wrapper = str(current / name)
    if name == "scripts/safe_flock.sh":
        return ["bash", wrapper, str(scratch / "preflight.lock"), "true"]
    if name == "scripts/cron_wrapper.sh":
        return ["bash", wrapper, "--wrapper-preflight", str(current)]
    if name == "scripts/effect_claim_cron.sh":
        return ["bash", wrapper, "preflight-not-an-admitted-lane", "true"]
    if name == "scripts/non_trading_hours_gate.sh":
        return ["bash", wrapper, "--dry-run", "true"]
    if name == "scripts/run_with_deepseek_offpeak.sh":
        return ["bash", wrapper, "--", "true"]
    return ["bash", wrapper] + ([] if name == "scripts/llm_priority_guard.sh" else ["true"])


def inspect(current: Path, scratch: Path, cron_text: str, *, runner=subprocess.run) -> dict:
    inventory = shell_inventory(cron_text)
    # cron_wrapper is a nested generic entrypoint even when not spelled in cron.
    names = sorted(set(inventory) | {"scripts/cron_wrapper.sh"})
    layout_issues = check_layout(current)
    results = []
    scratch.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Deliberately do not inherit credentials, effect-claim switches, proxy/LLM
    # settings, live-state paths or provider variables from the releasing shell.
    env = {"PATH": os.defpath, "HOME": str(scratch), "PROJECT_ROOT": str(current),
           "PY": sys.executable, "VENV_PYTHON": sys.executable,
           "TRADE_AI_CI": "1",
           "TRADEAI_OFFPEAK_PY": str(current / "scripts/lib/deepseek_offpeak.py")}
    for name in names:
        item = {"path": name, "protocol": PROTOCOLS.get(name), "status": "NOT_MEASURED"}
        if name not in PROTOCOLS:
            item["reason"] = "no_reviewed_safe_noop_protocol; producer_never_executed"
        elif layout_issues:
            item["reason"] = "real_release_layout_not_proven"
        elif not (current / name).is_file():
            item["reason"] = "wrapper_missing_from_candidate"
        else:
            try:
                proc = runner(_probe_argv(name, current, scratch), cwd=current, env=env,
                              text=True, capture_output=True, timeout=10)
                deferred = name == "scripts/llm_priority_guard.sh" and proc.returncode == 1 and "DEFERRED" in proc.stdout
                item.update(status="PROVEN" if proc.returncode == 0 or deferred else "FAILED", exit_code=proc.returncode,
                            reason="policy_deferred_no_business_command" if deferred else None)
            except (OSError, subprocess.TimeoutExpired):
                item.update(status="FAILED", reason="noop_probe_unavailable_or_timed_out")
        results.append(item)
    return {"schema": "ReleaseWrapperPreflight@v1", "current": str(current),
            "release": str(current.resolve()), "layout_issues": layout_issues,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "cron_sha256": hashlib.sha256(cron_text.encode()).hexdigest(),
            "captured_shell_path_count": len(inventory), "results": results,
            "ok": not layout_issues and all(row["status"] == "PROVEN" for row in results),
            "coverage_gaps": [row["path"] for row in results if row["status"] != "PROVEN"]}


def receipt_check(release: Path, sha: str, receipt: Path | None, now: datetime) -> dict:
    """Train readback of deploy's exact-release proof; missing evidence never passes an armed gate."""
    config = release / "config/release_wrapper_preflight.json"
    if not config.exists():
        return {"ok": True, "status": "PRE_FEATURE_RELEASE", "enforced": False}
    try:
        cfg_bytes = config.read_bytes()
        cfg = json.loads(cfg_bytes)
        if cfg.get("enabled") is not True:
            return {"ok": True, "status": "PENDING_OPERATOR_ADMISSION", "enforced": False,
                    "reason": "wrapper coverage not accepted; source hook is inactive"}
        if not receipt:
            raise ValueError("missing receipt")
        proof = json.loads(receipt.read_text())
        at = datetime.fromisoformat(str(proof.get("observed_at")).replace("Z", "+00:00"))
        age = (now - at).total_seconds() if at.tzinfo else -1
        valid = (cfg.get("review_status") == "REVIEWED" and bool(cfg.get("approved_by"))
                 and proof.get("ok") is True and proof.get("admission") == "ENFORCED" and 0 <= age <= 120
                 and proof.get("release_sha") == sha and proof.get("release") == str(release.resolve())
                 and proof.get("config_sha256") == hashlib.sha256(cfg_bytes).hexdigest())
        return {"ok": valid, "status": "PROVEN" if valid else "WRAPPER_PREFLIGHT_NOT_PROVEN", "enforced": True}
    except (OSError, ValueError, TypeError, AttributeError):
        return {"ok": False, "status": "WRAPPER_PREFLIGHT_UNREADABLE", "enforced": True}
