#!/usr/bin/env python3
"""
validate_strategy_yamls.py
==========================
Replacement for the broken audit script. Walks nested YAML keys
and accepts either schema dialect (v1.0 TESTING vs v1.0.0 UNVALIDATED).

Usage:
    cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
    python3 scripts/validate_strategy_yamls.py
    python3 scripts/validate_strategy_yamls.py --json    # JSON output for tooling
    python3 scripts/validate_strategy_yamls.py --md      # markdown report

Author: Trade AI v12 Session 33 patch package
Date: 2026-05-13
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml --break-system-packages")
    sys.exit(1)

# -----------------------------------------------------------------------------
# Required keys with nested fallback paths
# -----------------------------------------------------------------------------

# Each key maps to a list of acceptable paths. If ANY path is non-null, it counts as present.
REQUIRED_KEYS = {
    "strategy_id": ["strategy_id"],
    "display_name": ["display_name"],
    "version": ["version"],
    "purpose": ["purpose"],
    "eligible_accounts": ["eligible_accounts"],
    "timeframe": ["timeframe", "timeframe_class"],
    "max_hold_days": [
        "lifecycle.max_hold_days",
        "live_trade_rules.max_hold_days",
        "paper_trade_rules.max_hold_days",
        "max_hold_days",
    ],
    "entry_criteria": ["entry_criteria", "setup_qualification"],
    "auto_disqualifiers": ["auto_disqualifiers"],
    "exit_rules": ["exit_rules", "live_trade_rules"],
    "agent_responsibilities": ["agent_responsibilities"],
    "technical_indicators_required": ["technical_indicators_required"],
    "co_enables": ["co_enables"],
    "vix_rules": ["vix_rules"],
    "risk_parameters": ["risk", "risk_parameters"],
    "performance_context": ["performance_context"],
}

# Minimum counts for list fields
MIN_COUNTS = {
    "entry_criteria": 4,
    "auto_disqualifiers": 3,
}

# Required agent roles in agent_responsibilities
REQUIRED_AGENT_ROLES = ["maria", "risk", "steph"]


def get_nested(d, dotted_path):
    """Walk a dotted path (e.g. 'lifecycle.max_hold_days') and return the value or None."""
    cur = d
    for part in dotted_path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def count_items(value):
    """Return a count for either a list or a dict (dict counted by key count)."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return 0


def audit_one(yaml_path: Path) -> dict:
    """Audit a single YAML file. Returns issues list and metadata."""
    result = {
        "strategy": yaml_path.stem,
        "file": yaml_path.name,
        "issues": [],
        "score": None,
        "metadata": {},
    }

    try:
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        result["issues"].append(f"YAML PARSE ERROR: {e}")
        return result

    if data is None:
        result["issues"].append("EMPTY YAML")
        return result

    result["metadata"]["version"] = data.get("version", "?")
    result["metadata"]["status"] = data.get("status", "?")
    result["metadata"]["timeframe_class"] = data.get("timeframe_class", "?")

    # Check required keys with nested fallbacks
    for key, paths in REQUIRED_KEYS.items():
        found_value = None
        for p in paths:
            v = get_nested(data, p)
            if v is not None and v != [] and v != {}:
                found_value = v
                break
        if found_value is None:
            result["issues"].append(f"MISSING: {key}")
            continue

        # Check minimum counts
        if key in MIN_COUNTS:
            count = count_items(found_value)
            required = MIN_COUNTS[key]
            if count < required:
                result["issues"].append(
                    f"INSUFFICIENT {key}: {count} (need {required})"
                )

    # Check agent_responsibilities has required roles
    agents = data.get("agent_responsibilities", {}) or {}
    if isinstance(agents, dict):
        missing_agents = [a for a in REQUIRED_AGENT_ROLES if a not in agents]
        if missing_agents:
            result["issues"].append(
                f"MISSING agent_responsibilities roles: {', '.join(missing_agents)}"
            )

    # Score: 10 - (issues count * 0.5), floor 1
    issue_count = len(result["issues"])
    result["score"] = max(1, round(10 - (issue_count * 0.5), 1))

    return result


def render_text(results, total_files):
    """Plain text console output."""
    lines = []
    lines.append("=" * 80)
    lines.append(f"Trade AI v12 — Strategy YAML Validation")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Files scanned: {total_files}")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"{'Strategy':<32} {'Score':<7} {'Issues':<8} {'Status'}")
    lines.append("-" * 80)

    clean = 0
    for r in results:
        status = "OK" if not r["issues"] else f"{len(r['issues'])} issues"
        if not r["issues"]:
            clean += 1
        lines.append(f"{r['strategy']:<32} {r['score']:<7} {len(r['issues']):<8} {status}")
    lines.append("-" * 80)
    lines.append(f"Clean files: {clean}/{total_files}")
    lines.append("")

    # Detailed issues
    files_with_issues = [r for r in results if r["issues"]]
    if files_with_issues:
        lines.append("DETAILED ISSUES")
        lines.append("=" * 80)
        for r in files_with_issues:
            lines.append(f"\n{r['strategy']} (score {r['score']}, version {r['metadata'].get('version')}, status {r['metadata'].get('status')})")
            for issue in r["issues"]:
                lines.append(f"  - {issue}")
    return "\n".join(lines)


def render_markdown(results, total_files):
    """Markdown report output."""
    lines = []
    lines.append("# Trade AI v12 — Strategy YAML Validation Report")
    lines.append(f"\nGenerated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"\nFiles scanned: {total_files}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Strategy | Version | Status | Score | Issues |")
    lines.append("|----------|---------|--------|-------|--------|")
    for r in results:
        lines.append(
            f"| {r['strategy']} | {r['metadata'].get('version', '?')} | "
            f"{r['metadata'].get('status', '?')} | {r['score']} | {len(r['issues'])} |"
        )

    files_with_issues = [r for r in results if r["issues"]]
    if files_with_issues:
        lines.append("\n## Detailed Issues\n")
        for r in files_with_issues:
            lines.append(f"### {r['strategy']}")
            lines.append(f"- **Score:** {r['score']}/10")
            lines.append(f"- **Version:** {r['metadata'].get('version')}")
            lines.append(f"- **Status:** {r['metadata'].get('status')}")
            lines.append(f"- **Issues:**")
            for issue in r["issues"]:
                lines.append(f"  - {issue}")
            lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Validate strategy YAML files.")
    parser.add_argument(
        "--config-dir",
        default="config/strategies",
        help="Path to strategy YAML directory (default: config/strategies)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--md", action="store_true", help="Output Markdown report")
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output file path (default: stdout)",
    )
    args = parser.parse_args()

    config_dir = Path(args.config_dir)
    if not config_dir.exists():
        print(f"ERROR: config dir not found: {config_dir}")
        sys.exit(1)

    yaml_files = sorted(config_dir.glob("*.yaml"))
    yaml_files = [
        f for f in yaml_files
        if not f.stem.startswith("_")
        and f.stem not in ("shared_risk_rules",)
    ]

    results = [audit_one(p) for p in yaml_files]

    if args.json:
        output = json.dumps(results, indent=2, default=str)
    elif args.md:
        output = render_markdown(results, len(yaml_files))
    else:
        output = render_text(results, len(yaml_files))

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Wrote report to: {args.output}")
    else:
        print(output)

    # Exit non-zero if any file has issues
    any_issues = any(r["issues"] for r in results)
    sys.exit(1 if any_issues else 0)


if __name__ == "__main__":
    main()
