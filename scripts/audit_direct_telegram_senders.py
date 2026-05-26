#!/usr/bin/env python3
"""audit_direct_telegram_senders.py — Scan scripts for direct Telegram usage.

Produces JSON + markdown reports of files that send Telegram messages directly
(bypassing or alongside the central alert router).

Usage:
    python scripts/audit_direct_telegram_senders.py [--fail-on-new]

P0.5B control hardening — observability only, does not modify any sender files.
"""
import argparse, json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

PATTERNS = [
    ("api.telegram.org", re.compile(r"api\.telegram\.org")),
    ("TELEGRAM_BOT_TOKEN", re.compile(r"TELEGRAM_BOT_TOKEN")),
    ("send_telegram", re.compile(r"send_telegram\s*\(")),
    ("def send_telegram", re.compile(r"def\s+send_telegram")),
    ("bypass_router", re.compile(r"bypass_router")),
    ("requests.post.*telegram", re.compile(r"requests\.post.*telegram", re.IGNORECASE)),
]

# Central/approved components that are expected to reference Telegram
APPROVED_CENTRAL = {
    "scripts/telegram_alert.py",
    "scripts/telegram_alert_router.py",
    "scripts/telegram_alert_routing_policy.py",
    "scripts/telegram_callback_handler.py",
    "scripts/telegram_callback_policy.py",
    "scripts/telegram_command_handler.py",
    "scripts/telegram_reply_processor.py",
    "scripts/telegram_proposal_alert_policy.py",
    "scripts/telegram_smart_alerts.py",
    "scripts/telegram_agent_router_bridge.py",
    "scripts/telegram_cio_summary.py",
    "scripts/telegram_poller_watchdog.sh",
    "scripts/run_telegram_callback_poller.py",
    "scripts/discover_telegram_chat_id.py",
    "scripts/set_telegram_proposal_channel_env.py",
}


def scan_file(filepath):
    """Scan a single file for Telegram patterns. Returns list of findings."""
    findings = []
    try:
        with open(filepath, "r", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return findings

    for i, line in enumerate(lines, 1):
        for label, pattern in PATTERNS:
            if pattern.search(line):
                findings.append({
                    "line": i,
                    "pattern": label,
                    "text": line.strip()[:120],
                })
    return findings


def run_audit():
    """Scan all scripts for direct Telegram usage."""
    results = []
    py_files = sorted(SCRIPTS_DIR.rglob("*.py"))
    sh_files = sorted(SCRIPTS_DIR.rglob("*.sh"))

    for fp in py_files + sh_files:
        findings = scan_file(fp)
        if not findings:
            continue

        rel_path = str(fp.relative_to(PROJECT_ROOT))
        is_approved = rel_path in APPROVED_CENTRAL
        has_bypass = any(f["pattern"] == "bypass_router" for f in findings)
        has_direct_api = any(f["pattern"] == "api.telegram.org" for f in findings)
        has_send = any(f["pattern"] == "send_telegram" for f in findings)

        if is_approved:
            recommendation = "central_component"
        elif has_bypass:
            recommendation = "review_bypass_usage"
        elif has_direct_api and not has_send:
            recommendation = "migrate_to_send_telegram"
        elif has_send and not has_direct_api:
            recommendation = "ok_uses_central_api"
        else:
            recommendation = "review_for_migration"

        results.append({
            "file": rel_path,
            "findings": findings,
            "finding_count": len(findings),
            "approved_central": is_approved,
            "bypass_risk": has_bypass and not is_approved,
            "direct_api": has_direct_api,
            "recommendation": recommendation,
        })

    return results


def write_reports(results):
    """Write JSON and markdown reports."""
    timestamp = datetime.now(timezone.utc).isoformat()

    # Summary stats
    total_files = len(results)
    bypass_files = [r for r in results if r["bypass_risk"]]
    direct_api_files = [r for r in results if r["direct_api"] and not r["approved_central"]]
    approved_files = [r for r in results if r["approved_central"]]
    migration_needed = [r for r in results if r["recommendation"] in ("migrate_to_send_telegram", "review_for_migration")]

    report = {
        "timestamp": timestamp,
        "summary": {
            "total_files_with_telegram_refs": total_files,
            "approved_central_components": len(approved_files),
            "bypass_risk_files": len(bypass_files),
            "direct_api_non_central": len(direct_api_files),
            "migration_candidates": len(migration_needed),
        },
        "files": results,
    }

    # JSON report
    json_path = PROJECT_ROOT / "reports" / "direct_telegram_sender_audit.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"JSON report: {json_path}")

    # Markdown report
    md_path = PROJECT_ROOT / "docs" / "atm_audit_2026_05_26" / "designer_review" / "alert_routing_direct_sender_audit.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Direct Telegram Sender Audit",
        "",
        f"**Generated:** {timestamp}",
        f"**Total files with Telegram references:** {total_files}",
        f"**Approved central components:** {len(approved_files)}",
        f"**Bypass risk files:** {len(bypass_files)}",
        f"**Direct API (non-central):** {len(direct_api_files)}",
        f"**Migration candidates:** {len(migration_needed)}",
        "",
        "## Bypass Risk Files",
        "",
    ]
    if bypass_files:
        for r in bypass_files:
            lines.append(f"- `{r['file']}` — {r['finding_count']} refs, recommendation: {r['recommendation']}")
    else:
        lines.append("None.")

    lines += ["", "## Direct API (Non-Central)", ""]
    if direct_api_files:
        for r in direct_api_files:
            lines.append(f"- `{r['file']}` — {r['finding_count']} refs, recommendation: {r['recommendation']}")
    else:
        lines.append("None.")

    lines += ["", "## Migration Candidates", ""]
    if migration_needed:
        for r in migration_needed:
            lines.append(f"- `{r['file']}` — {r['recommendation']}")
    else:
        lines.append("None.")

    lines += ["", "## All Files", "", "| File | Refs | Central | Bypass | Direct API | Recommendation |",
              "|------|------|---------|--------|------------|----------------|"]
    for r in results:
        lines.append(f"| `{r['file']}` | {r['finding_count']} | {'yes' if r['approved_central'] else ''} | "
                     f"{'YES' if r['bypass_risk'] else ''} | {'yes' if r['direct_api'] else ''} | {r['recommendation']} |")

    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Markdown report: {md_path}")

    return report


def main():
    p = argparse.ArgumentParser(description="Audit direct Telegram senders in scripts/")
    p.add_argument("--fail-on-new", action="store_true",
                   help="Exit non-zero if any non-central direct API senders found (not enabled in cron)")
    args = p.parse_args()

    results = run_audit()
    report = write_reports(results)

    s = report["summary"]
    print(f"\nAudit complete: {s['total_files_with_telegram_refs']} files, "
          f"{s['approved_central_components']} central, "
          f"{s['bypass_risk_files']} bypass risk, "
          f"{s['direct_api_non_central']} direct API, "
          f"{s['migration_candidates']} migration candidates")

    if args.fail_on_new and s["direct_api_non_central"] > 0:
        print(f"FAIL: {s['direct_api_non_central']} non-central direct API senders found")
        sys.exit(1)


if __name__ == "__main__":
    main()
