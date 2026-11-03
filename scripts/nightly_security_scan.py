#!/usr/bin/env python3
"""Nightly free security scan: alert on new findings and unresolved delivery retries.

Operator 2026-11-02: "remove CodeQL completely... Semgrep and the package audits run every night and
message you if they find anything." This is the nightly half; `scripts/check_ruff_security.py` (ruff's
flake8-bandit S rules, baseline) and gitleaks inside `secret-scan` are the per-change half.

Free tools execute as local child processes. Versions are RECORDED, never assumed: the receipt stores whatever
``--version`` reports, and a missing tool is reported as ``tool_missing`` with its install command
from config — never silently skipped.

A finding is new only when its id was absent from the previous snapshot. Pending alert ids are
separate: only a structured delivered=true result clears the ids actually included in the message.
False, unknown and accepted-only outcomes retry through normal house controls; a confirmed alert
dedupes. Invalid JSON is a tool error, not a clean scan. Production scans use timeout_s from config
and version queries are bounded to at most ten seconds, including owned descendant processes.

    python3 scripts/nightly_security_scan.py            # dry run: print the receipt, send nothing
    python3 scripts/nightly_security_scan.py --apply    # write the receipt, alert on new findings

AUTHORITY: READ_ONLY_ADVISORY. It never edits code, installs a package or opens a PR.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "nightly_security_scan.json"
#: Dark-contract guard: this module defines a record schema and nothing under scripts/ imports it.
NO_CONSUMER_REASON = (
    "NightlySecurityScanReceipt@v1 is a data receipt, not an imported contract: the NEXT night's run "
    "reads it to dedupe findings and the operator alert carries it; no script imports this module."
)
RECEIPT_SCHEMA = "NightlySecurityScanReceipt@v1"
Runner = Callable[[list[str], Path], tuple[int, str, str]]


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _default_runner(argv: list[str], cwd: Path, *, timeout_s: float = 900) -> tuple[int, str, str]:
    """Bound the owned process group, including descendants retaining output pipes."""
    try:
        # Reviewed config argv, never a shell; retain the prior runner's scoped S603 waiver.
        proc = subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,  # noqa: S603
                                text=True, start_new_session=True)
    except FileNotFoundError:
        return 127, "", "not found"
    except (OSError, subprocess.SubprocessError) as exc:
        return 126, "", type(exc).__name__
    try:
        out, err = proc.communicate(timeout=timeout_s)
        return proc.returncode, out or "", err or ""
    except (subprocess.TimeoutExpired, OSError, UnicodeError) as exc:
        timeout = isinstance(exc, subprocess.TimeoutExpired)
        cleanup_ok = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            cleanup_ok = False
        try:
            proc.communicate(timeout=1)
        except (subprocess.TimeoutExpired, OSError, UnicodeError):
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()
            try:
                proc.wait(timeout=1)
            except (subprocess.TimeoutExpired, OSError):
                cleanup_ok = False
        reason = f"timeout after {timeout_s:g}s" if timeout else type(exc).__name__
        if not cleanup_ok:
            reason += "; process group cleanup unconfirmed"
        return 124 if timeout else 126, "", reason


def _state_dir(root: Path | None) -> Path:
    base = Path(os.environ.get("TRADEAI_STATE_ROOT") or root or (Path.home() / "trade-ai-releases" / "persistent-state"))
    return base / "data" / "runtime" / "security_scan"


def _version(argv0: str, runner: Runner, cwd: Path) -> str | None:
    rc, out, err = runner([argv0, "--version"], cwd)
    text = (out or err or "").strip().splitlines()
    return text[0][:80] if rc == 0 and text else None


# ------------------------------------------------------------------ parsers
def parse_semgrep(out: str) -> list[dict[str, Any]]:
    doc = json.loads(out)
    if not isinstance(doc, dict) or not isinstance(doc.get("results"), list) or doc.get("errors"):
        raise ValueError("semgrep output contract invalid")
    findings = []
    for row in doc["results"]:
        if not isinstance(row, dict) or not isinstance(row.get("start"), dict) or not isinstance(row.get("extra"), dict):
            raise ValueError("semgrep finding shape invalid")
        rid, path = row.get("check_id"), row.get("path")
        if not isinstance(rid, str) or not rid or not isinstance(path, str) or not path:
            raise ValueError("semgrep finding identity invalid")
        line = row["start"].get("line")
        sev = str(row["extra"].get("severity") or "INFO").upper()
        findings.append({"id": f"semgrep:{rid}:{path}:{line}", "tool": "semgrep", "severity": sev,
                         "where": f"{path}:{line}", "message": str(row["extra"].get("message") or rid)[:200]})
    return findings


def parse_pip_audit(out: str) -> list[dict[str, Any]]:
    doc = json.loads(out)
    deps = doc.get("dependencies") if isinstance(doc, dict) else doc
    if not isinstance(deps, list):
        raise ValueError("pip-audit output contract invalid")
    findings = []
    for dep in deps:
        if not isinstance(dep, dict) or not isinstance(dep.get("vulns"), list):
            raise ValueError("pip-audit dependency shape invalid")
        name, version = str(dep.get("name") or ""), str(dep.get("version") or "")
        for vuln in dep["vulns"]:
            if not isinstance(vuln, dict) or not isinstance(vuln.get("id"), str) or not isinstance(vuln.get("fix_versions", []), list):
                raise ValueError("pip-audit vulnerability shape invalid")
            vid = vuln["id"]
            fix = ",".join(str(value) for value in vuln.get("fix_versions", []))
            findings.append({"id": f"pip-audit:{name}:{vid}", "tool": "pip-audit", "severity": "HIGH",
                             "where": f"{name}=={version}",
                             "message": f"{vid} (fix: {fix or 'none'}) {str(vuln.get('description') or '')[:150]}"})
    return findings


def parse_npm_audit(out: str) -> list[dict[str, Any]]:
    doc = json.loads(out)
    if not isinstance(doc, dict) or not isinstance(doc.get("vulnerabilities"), dict) or doc.get("error"):
        raise ValueError("npm audit output contract invalid")
    findings = []
    for name, vuln in doc["vulnerabilities"].items():
        if not isinstance(vuln, dict) or not isinstance(vuln.get("via", []), list):
            raise ValueError("npm audit vulnerability shape invalid")
        sev = str(vuln.get("severity") or "unknown").upper()
        detail = next((item.get("title") for item in vuln.get("via", []) if isinstance(item, dict) and item.get("title")), "")
        findings.append({"id": f"npm-audit:{name}:{sev}", "tool": "npm-audit", "severity": sev,
                         "where": str(name), "message": str(detail or sev)[:200]})
    return findings


PARSERS = {"semgrep": parse_semgrep, "pip-audit": parse_pip_audit, "npm-audit": parse_npm_audit}


# ------------------------------------------------------------------ the scan
def run_scan(config: Mapping[str, Any], *, runner: Runner | None = None, state_dir: Path | None = None,
             send: Callable[..., Any] | None = None, dry_run: bool = True, cwd: Path | None = None) -> dict[str, Any]:
    timeout_s = config.get("timeout_s", 900)
    if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("timeout_s must be positive and finite")
    # Keep the injectable two-argument runner contract. Production calls bound both
    # the scan and its cheap version query; no config or paid work is performed here.
    run = runner or (lambda argv, where: _default_runner(
        argv, where, timeout_s=min(timeout_s, 10) if argv[1:] == ["--version"] else timeout_s))
    where = Path(cwd or ROOT)
    sd = state_dir or _state_dir(None)
    tools_cfg = config.get("tools") or {}
    tools: dict[str, Any] = {}
    findings: list[dict[str, Any]] = []
    for name, spec in tools_cfg.items():
        if not isinstance(spec, dict) or not spec.get("enabled", True):
            continue
        argv = [str(a) for a in (spec.get("argv") or [])]
        if not argv:
            continue
        rc, out, err = run(argv, where)
        if rc == 127:
            tools[name] = {"status": "tool_missing", "install": spec.get("install")}
            continue
        # A tool that exits >=2 or prints no JSON did not run: that is an ERROR, never "ran with
        # zero findings" (which would overwrite the receipt and re-alert old findings tomorrow).
        if rc not in (0, 1) or not out.strip():
            tools[name] = {"status": "error", "rc": rc, "reason": "tool_failed_or_empty_output", "stderr": (err or out).strip()[:300]}
            continue
        try:
            parsed = PARSERS[name](out)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            tools[name] = {"status": "error", "rc": rc, "reason": "output_invalid", "exception_type": type(exc).__name__}
            continue
        tools[name] = {"status": "ran", "rc": rc, "version": _version(argv[0], run, where)}
        findings.extend(parsed)

    previous = {}
    try:
        previous = json.loads((sd / "last.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    previous_by_tool: dict[str, list[dict[str, Any]]] = {}
    for f in (previous.get("findings") or []):
        if isinstance(f, dict):
            previous_by_tool.setdefault(str(f.get("tool")), []).append(f)
    # A tool that could not run this night keeps its previous findings in the receipt, so the next
    # good run does not re-alert them as NEW (the reproduced defect).
    carried: list[dict[str, Any]] = []
    unusable: list[str] = []
    for name, t in tools.items():
        if t.get("status") in ("tool_missing", "error"):
            unusable.append(name)
            carried.extend({**f, "carried": True} for f in previous_by_tool.get(name, []))
    if carried:
        findings = findings + carried
    seen = {str(f.get("id")) for f in (previous.get("findings") or []) if isinstance(f, dict)}
    new = [f for f in findings if str(f.get("id")) not in seen and not f.get("carried")]
    # A finding snapshot proves observation, not alert delivery. Legacy receipts
    # with no confirmed alert preserve their candidates rather than suppressing them.
    previous_pending = previous.get("pending_alert_ids")
    if not isinstance(previous_pending, list):
        previous_pending = [] if previous.get("alerted") is True else list(seen)
    present = {str(f["id"]) for f in findings}
    pending = {value for value in previous_pending if isinstance(value, str) and value in present}
    pending.update(str(f["id"]) for f in new)
    candidates = [f for f in findings if str(f["id"]) in pending and not f.get("carried")]
    retry = [str(f["id"]) for f in candidates if str(f["id"]) in seen]

    def _problem_text() -> list[str]:
        out = []
        for name in unusable:
            t = tools[name]
            if t.get("status") == "tool_missing":
                out.append(f"· {name}: NOT INSTALLED — {t.get('install') or 'install it'}")
            else:
                out.append(f"· {name}: CRASHED rc={t.get('rc')} {str(t.get('stderr') or '')[:120]}")
        return out

    notification = {"status": "dry_run" if dry_run else "not_required", "accepted": False, "delivered": False}
    receipt = {"schema": RECEIPT_SCHEMA, "findings": findings, "new": [f["id"] for f in new], "retry": retry,
               "tools": tools, "unusable": unusable, "dry_run": bool(dry_run), "alerted": False,
               "notification": notification, "pending_alert_ids": sorted(pending)}
    if (candidates or unusable) and not dry_run:
        if send is None:
            notification["status"] = "sender_unavailable"
        else:
            lines = [f"[{config.get('alert_priority', 'P1')}] nightly security scan: "
                     f"{len(new)} NEW finding(s), {len(retry)} delivery retry, {len(unusable)} tool(s) not usable"]
            sent_candidates = candidates[:15]
            lines += [f"· {f['id']} ({f['severity']}) — {f['message']}" for f in sent_candidates]
            lines += _problem_text()
            try:
                outcome = send("\n".join(lines), priority=str(config.get("alert_priority", "P1")))
                delivered = isinstance(outcome, Mapping) and outcome.get("delivered") is True
                accepted = delivered or outcome is True or (isinstance(outcome, Mapping) and outcome.get("accepted") is True)
                notification.update(status="delivered" if delivered else "accepted_unconfirmed" if accepted else "unconfirmed",
                                    accepted=bool(accepted), delivered=bool(delivered))
                receipt["alerted"] = delivered
                if delivered:
                    pending.difference_update(str(f["id"]) for f in sent_candidates)
            except Exception as exc:  # noqa: BLE001 — retain retry state without private sender error text
                notification.update(status="sender_error", error_type=type(exc).__name__)
    receipt["pending_alert_ids"] = sorted(pending)

    if not dry_run:
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "last.json").write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true", help="write the receipt and alert on new findings")
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_config(Path(a.config))
    send = None
    if a.apply:
        try:
            from telegram_alert import send_telegram_outcome  # type: ignore
        except ModuleNotFoundError as exc:
            if exc.name != "telegram_alert":
                raise
            from scripts.telegram_alert import send_telegram_outcome  # type: ignore
        send = lambda text, priority="P1": send_telegram_outcome(text, priority=priority)  # noqa: E731
    receipt = run_scan(cfg, send=send, dry_run=not a.apply)
    if a.json:
        print(json.dumps(receipt, indent=1, sort_keys=True))
    else:
        ran = [n for n, t in receipt["tools"].items() if t.get("status") == "ran"]
        missing = [n for n, t in receipt["tools"].items() if t.get("status") == "tool_missing"]
        print(f"nightly-security-scan: {len(receipt['findings'])} finding(s), {len(receipt['new'])} new; "
              f"ran={ran} missing={missing} dry_run={receipt['dry_run']}")
    return 1 if receipt.get("unusable") or (a.apply and receipt.get("pending_alert_ids")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
