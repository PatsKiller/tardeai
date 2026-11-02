#!/usr/bin/env python3
"""Nightly free security scan: semgrep OSS, pip-audit, npm audit — alert only on NEW findings.

Operator 2026-11-02: "remove CodeQL completely... Semgrep and the package audits run every night and
message you if they find anything." This is the nightly half; `scripts/check_ruff_security.py` (ruff's
flake8-bandit S rules, baseline) and gitleaks inside `secret-scan` are the per-change half.

Every tool is free and local. Versions are RECORDED, never assumed: the receipt stores whatever
``--version`` reports, and a missing tool is reported as ``tool_missing`` with its install command
from config — never silently skipped.

Dedupe: a finding is new only when its id was absent from the previous receipt, so the operator is
messaged once per finding, not every night. A finding that disappears simply stops appearing.

    python3 scripts/nightly_security_scan.py            # dry run: print the receipt, send nothing
    python3 scripts/nightly_security_scan.py --apply    # write the receipt, alert on new findings

AUTHORITY: READ_ONLY_ADVISORY. It never edits code, installs a package or opens a PR.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "nightly_security_scan.json"
RECEIPT_SCHEMA = "NightlySecurityScanReceipt@v1"
Runner = Callable[[list[str], Path], tuple[int, str, str]]


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _default_runner(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        # argv is a list built from config, run without a shell: no word splitting, no injection.
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, check=False)  # noqa: S603
    except FileNotFoundError:
        return 127, "", "not found"
    except (OSError, subprocess.SubprocessError) as exc:
        return 126, "", f"{type(exc).__name__}: {exc}"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _state_dir(root: Path | None) -> Path:
    base = Path(os.environ.get("TRADEAI_STATE_ROOT") or root or (Path.home() / "trade-ai-releases" / "persistent-state"))
    return base / "data" / "runtime" / "security_scan"


def _version(argv0: str, runner: Runner, cwd: Path) -> str | None:
    rc, out, err = runner([argv0, "--version"], cwd)
    text = (out or err or "").strip().splitlines()
    return text[0][:80] if rc == 0 and text else None


# ------------------------------------------------------------------ parsers
def parse_semgrep(out: str) -> list[dict[str, Any]]:
    try:
        doc = json.loads(out or "{}")
    except json.JSONDecodeError:
        return []
    findings = []
    for r in doc.get("results") or []:
        rid = str(r.get("check_id") or "")
        path = str(r.get("path") or "")
        line = ((r.get("start") or {}).get("line"))
        sev = str(((r.get("extra") or {}).get("severity") or "INFO")).upper()
        findings.append({"id": f"semgrep:{rid}:{path}:{line}", "tool": "semgrep", "severity": sev,
                         "where": f"{path}:{line}", "message": str((r.get("extra") or {}).get("message") or rid)[:200]})
    return findings


def parse_pip_audit(out: str) -> list[dict[str, Any]]:
    try:
        doc = json.loads(out or "{}")
    except json.JSONDecodeError:
        return []
    findings = []
    deps = doc.get("dependencies") if isinstance(doc, dict) else doc
    for dep in deps or []:
        if not isinstance(dep, dict):
            continue
        name = str(dep.get("name") or "")
        version = str(dep.get("version") or "")
        for v in dep.get("vulns") or []:
            vid = str(v.get("id") or "")
            fix = ",".join(str(x) for x in (v.get("fix_versions") or []))
            findings.append({"id": f"pip-audit:{name}:{vid}", "tool": "pip-audit", "severity": "HIGH",
                             "where": f"{name}=={version}",
                             "message": f"{vid} (fix: {fix or 'none'}) {str(v.get('description') or '')[:150]}"})
    return findings


def parse_npm_audit(out: str) -> list[dict[str, Any]]:
    try:
        doc = json.loads(out or "{}")
    except json.JSONDecodeError:
        return []
    findings = []
    for name, v in (doc.get("vulnerabilities") or {}).items():
        sev = str((v or {}).get("severity") or "unknown").upper()
        via = (v or {}).get("via") or []
        detail = next((x.get("title") for x in via if isinstance(x, dict) and x.get("title")), "")
        findings.append({"id": f"npm-audit:{name}:{sev}", "tool": "npm-audit", "severity": sev,
                         "where": str(name), "message": str(detail or sev)[:200]})
    return findings


PARSERS = {"semgrep": parse_semgrep, "pip-audit": parse_pip_audit, "npm-audit": parse_npm_audit}


# ------------------------------------------------------------------ the scan
def run_scan(config: Mapping[str, Any], *, runner: Runner | None = None, state_dir: Path | None = None,
             send: Callable[..., Any] | None = None, dry_run: bool = True, cwd: Path | None = None) -> dict[str, Any]:
    run = runner or _default_runner
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
        tools[name] = {"status": "ran", "rc": rc, "version": _version(argv[0], run, where)}
        if out.strip():
            findings.extend(PARSERS.get(name, lambda _o: [])(out))
        elif err.strip():
            tools[name]["stderr"] = err.strip()[:200]

    previous = {}
    try:
        previous = json.loads((sd / "last.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    seen = {str(f.get("id")) for f in (previous.get("findings") or []) if isinstance(f, dict)}
    new = [f for f in findings if str(f.get("id")) not in seen]
    receipt = {"schema": RECEIPT_SCHEMA, "findings": findings, "new": [f["id"] for f in new],
               "tools": tools, "dry_run": bool(dry_run), "alerted": False}
    if new and not dry_run and send is not None:
        lines = [f"[{config.get('alert_priority', 'P1')}] nightly security scan: {len(new)} NEW finding(s)"]
        lines += [f"· {f['id']} ({f['severity']}) — {f['message']}" for f in new[:15]]
        missing = [n for n, t in tools.items() if t.get("status") == "tool_missing"]
        if missing:
            lines.append("tools not installed: " + ", ".join(missing))
        send("\n".join(lines), priority=str(config.get("alert_priority", "P1")))
        receipt["alerted"] = True
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
            from telegram_alert import send_telegram  # type: ignore
        except ImportError:
            from scripts.telegram_alert import send_telegram  # type: ignore
        send = lambda text, priority="P1": send_telegram(text, priority=priority)  # noqa: E731
    receipt = run_scan(cfg, send=send, dry_run=not a.apply)
    if a.json:
        print(json.dumps(receipt, indent=1, sort_keys=True))
    else:
        ran = [n for n, t in receipt["tools"].items() if t.get("status") == "ran"]
        missing = [n for n, t in receipt["tools"].items() if t.get("status") == "tool_missing"]
        print(f"nightly-security-scan: {len(receipt['findings'])} finding(s), {len(receipt['new'])} new; "
              f"ran={ran} missing={missing} dry_run={receipt['dry_run']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
