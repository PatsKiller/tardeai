#!/usr/bin/env python3
"""report_drive_doc_sync_validation.py — Validate Google Drive doc sync status.

Read-only. No trades. No orders.
"""
import argparse, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

DRIVE_SYNC_LOG = Path("/home/johnclaw/logs/drive-docs-sync.log")

KNOWN_PHASES = [
    "SCREENER-ARCH-3C",
    "SCREENER-ARCH-3D",
    "JOURNAL-UX-1B",
    "OPS-HYGIENE-1",
]

SENSITIVE_EXTENSIONS = [".env", ".cookie", ".token", ".key", ".pem", ".secret"]


def main():
    p = argparse.ArgumentParser(description="Drive doc sync validation (read-only)")
    p.add_argument("--phase", type=str, default="OPS-HYGIENE-1", help="Phase to focus on")
    p.add_argument("--output-json", type=str, help="Path to write JSON report")
    p.add_argument("--output-md", type=str, help="Path to write Markdown report")
    p.add_argument("--verbose", action="store_true", help="Print verbose summary")
    args = p.parse_args()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "focus_phase": args.phase,
        "local_docs_check": {},
        "sync_log": {},
        "sensitive_file_exclusion": {},
    }

    # Check local docs directories
    docs_dir = PROJ / "docs"
    for phase in KNOWN_PHASES:
        phase_lower = phase.lower().replace("-", "_")
        # Check multiple naming conventions
        found = False
        checked = []
        for pattern in [phase, phase_lower, phase.replace("-", "_"), phase.lower()]:
            candidates = list(docs_dir.glob(f"*{pattern}*")) if docs_dir.exists() else []
            checked.append(pattern)
            if candidates:
                found = True
                report["local_docs_check"][phase] = {
                    "exists": True,
                    "files": [str(c.name) for c in candidates[:10]],
                }
                break
        if not found:
            report["local_docs_check"][phase] = {
                "exists": False,
                "checked_patterns": checked,
            }

    # Parse sync log
    if DRIVE_SYNC_LOG.exists():
        try:
            log_text = DRIVE_SYNC_LOG.read_text()
            log_lines = log_text.strip().splitlines()
            report["sync_log"]["present"] = True
            report["sync_log"]["total_lines"] = len(log_lines)

            # Find last sync block
            uploaded = 0
            unchanged = 0
            failed = 0
            last_ts = None
            for line in log_lines:
                ts_match = re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", line)
                if ts_match:
                    last_ts = ts_match.group(0)
                if re.search(r"upload", line, re.IGNORECASE):
                    m = re.search(r"(\d+)\s*upload", line, re.IGNORECASE)
                    if m:
                        uploaded = max(uploaded, int(m.group(1)))
                if re.search(r"unchanged", line, re.IGNORECASE):
                    m = re.search(r"(\d+)\s*unchanged", line, re.IGNORECASE)
                    if m:
                        unchanged = max(unchanged, int(m.group(1)))
                if re.search(r"fail|error", line, re.IGNORECASE):
                    m = re.search(r"(\d+)\s*fail", line, re.IGNORECASE)
                    if m:
                        failed = max(failed, int(m.group(1)))
                    else:
                        failed += 1

            report["sync_log"]["last_timestamp"] = last_ts
            report["sync_log"]["uploaded_count"] = uploaded
            report["sync_log"]["unchanged_count"] = unchanged
            report["sync_log"]["failed_count"] = failed
            report["sync_log"]["last_10_lines"] = log_lines[-10:] if len(log_lines) >= 10 else log_lines
        except Exception as e:
            report["sync_log"]["present"] = True
            report["sync_log"]["parse_error"] = str(e)
    else:
        report["sync_log"]["present"] = False
        report["sync_log"]["expected_path"] = str(DRIVE_SYNC_LOG)

    # Check sensitive file exclusion
    sensitive_found = []
    if docs_dir.exists():
        for ext in SENSITIVE_EXTENSIONS:
            matches = list(docs_dir.rglob(f"*{ext}"))
            if matches:
                sensitive_found.extend([str(m.relative_to(PROJ)) for m in matches])

    report["sensitive_file_exclusion"]["sensitive_in_docs"] = sensitive_found
    report["sensitive_file_exclusion"]["clean"] = len(sensitive_found) == 0

    # Output
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        print(f"JSON written to {args.output_json}")

    if args.output_md:
        md = _to_md(report)
        Path(args.output_md).write_text(md)
        print(f"MD written to {args.output_md}")

    if args.verbose:
        print(json.dumps(report, indent=2, default=str))

    sync_ok = "yes" if report["sync_log"].get("present") else "NO"
    clean = "yes" if report["sensitive_file_exclusion"]["clean"] else "NO"
    print(f"Phase: {args.phase}  |  Sync log present: {sync_ok}  |  Sensitive files excluded: {clean}")


def _to_md(r):
    lines = [
        f"# Drive Doc Sync Validation",
        f"Generated: {r['generated_at']}  |  Focus phase: {r['focus_phase']}\n",
        f"## Local Docs Check\n",
    ]
    for phase, info in r["local_docs_check"].items():
        status = "FOUND" if info.get("exists") else "MISSING"
        lines.append(f"- **{phase}**: {status}")
        if info.get("files"):
            for f in info["files"]:
                lines.append(f"  - {f}")

    lines.append(f"\n## Sync Log\n")
    sl = r["sync_log"]
    lines.append(f"- Present: {sl.get('present', '?')}")
    if sl.get("present"):
        lines.append(f"- Last timestamp: {sl.get('last_timestamp', '?')}")
        lines.append(f"- Uploaded: {sl.get('uploaded_count', '?')}")
        lines.append(f"- Unchanged: {sl.get('unchanged_count', '?')}")
        lines.append(f"- Failed: {sl.get('failed_count', '?')}")

    lines.append(f"\n## Sensitive File Exclusion\n")
    if r["sensitive_file_exclusion"]["clean"]:
        lines.append("- All clean: no .env/.cookie/.token files in docs/")
    else:
        lines.append("- WARNING: sensitive files found:")
        for f in r["sensitive_file_exclusion"]["sensitive_in_docs"]:
            lines.append(f"  - {f}")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
