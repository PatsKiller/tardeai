#!/usr/bin/env python3
"""check_a1a_compliance.py — Read-only A1A documentation compliance check.

No mutations. No secrets exposed. No trading changes.

Usage:
    .venv/bin/python scripts/check_a1a_compliance.py --last-commit --verbose
"""
import argparse, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

UNSAFE_PATTERNS = [".env", "credentials", "cookie", "token", "holdings.json",
                   "tsbuildinfo", ".next", "cache", "model"]
REQUIRED_DOCS = ["docs/project/PROJECT_DOC_INDEX.md", "docs/v4_1_deployment_log.md",
                 "docs/A1A.md", "docs/RESTORE_GUIDE.md"]


def _git(cmd):
    return subprocess.check_output(f"git {cmd}", shell=True, cwd=str(PROJ),
                                   stderr=subprocess.DEVNULL).decode().strip()


def main():
    p = argparse.ArgumentParser(description="A1A compliance check (read-only)")
    p.add_argument("--last-commit", action="store_true")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    findings = []
    now = datetime.now(timezone.utc)

    # Get changed files from last commit
    if args.last_commit:
        changed = _git("diff --name-only HEAD~1 HEAD").splitlines()
    else:
        changed = _git("diff --name-only HEAD").splitlines()

    # Check 1: Unsafe files in commit
    for f in changed:
        for pat in UNSAFE_PATTERNS:
            if pat in f.lower():
                findings.append({"severity": "P0", "check": "unsafe_file",
                                "file": f, "message": f"Unsafe file pattern '{pat}' in commit"})

    # Check 2: Code changed without docs
    code_changed = [f for f in changed if f.endswith((".py", ".ts", ".tsx", ".sh"))]
    docs_changed = [f for f in changed if f.startswith("docs/")]
    if code_changed and not docs_changed:
        findings.append({"severity": "P1", "check": "code_without_docs",
                        "message": f"{len(code_changed)} code files changed, 0 docs updated"})

    # Check 3: Required docs exist
    for rd in REQUIRED_DOCS:
        if not (PROJ / rd).exists():
            findings.append({"severity": "P0", "check": "missing_required_doc",
                            "file": rd, "message": f"Required doc missing: {rd}"})

    # Check 4: System facts freshness
    facts_path = PROJ / "docs" / "generated" / "SYSTEM_FACTS_LATEST.md"
    if not facts_path.exists():
        facts_path = PROJ / "docs" / "project" / "SYSTEM_FACTS_LATEST.md"
    if facts_path.exists():
        age_hours = (now.timestamp() - facts_path.stat().st_mtime) / 3600
        if age_hours > 48:
            findings.append({"severity": "P2", "check": "stale_facts",
                            "message": f"System facts {age_hours:.0f}h old (>48h)"})
    else:
        findings.append({"severity": "P2", "check": "no_facts",
                        "message": "No SYSTEM_FACTS_LATEST found"})

    # Check 5: Deployment log updated for meaningful changes
    if code_changed and "docs/v4_1_deployment_log.md" not in changed:
        findings.append({"severity": "P2", "check": "deployment_log_stale",
                        "message": "Code changed but deployment log not updated"})

    # Summary
    by_sev = {}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1

    status = "healthy" if not findings else "warning" if not by_sev.get("P0") else "attention_required"
    report = {
        "generated_at": now.isoformat(),
        "git_head": _git("rev-parse --short HEAD"),
        "files_checked": len(changed),
        "findings_count": len(findings),
        "by_severity": by_sev,
        "status": status,
        "findings": findings,
    }

    if args.verbose:
        print(f"A1A Compliance: {status} ({len(findings)} findings)")
        for f in findings:
            print(f"  [{f['severity']}] {f['check']}: {f['message']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# A1A Compliance — {status}", f"\nFindings: {len(findings)}", ""]
        for f in findings:
            md.append(f"- **[{f['severity']}]** {f['check']}: {f['message']}")
        if not findings:
            md.append("No findings. Documentation appears compliant.")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
