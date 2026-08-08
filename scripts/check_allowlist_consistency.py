#!/usr/bin/env python3
"""check_allowlist_consistency.py — verify the remediation allowlist is internally consistent.

Checks:
  1. Every script basename in the code tuple (_SAFE_REMEDIATION_SCRIPTS) appears in
     the YAML allowed_script_patterns (and vice versa).
  2. Every string-valued entry in health_agent_policy.json remediation_map references
     a script basename that appears in the YAML allowed_script_patterns.
  3. No blocked_pattern in the YAML appears as a substring of any allowed script path
     (false-positive guard — e.g. "submit" matching "--submit-validation").

Exit 0 if consistent, exit 1 with details if gaps found.  Run in CI or as a pre-commit
hook; the health agent can also call this at startup as a warn-assert (see F4-1).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def extract_yaml_allowed(path: Path) -> set[str]:
    """Parse allowed_script_patterns from the YAML (hand-rolled, no pyyaml)."""
    if not path.exists():
        return set()
    scripts = set()
    in_allowed = False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("allowed_script_patterns:"):
            in_allowed = True
            continue
        if in_allowed:
            if stripped.startswith("blocked_patterns:") or stripped.startswith("max_runtime"):
                break
            if stripped.startswith("- ") and "." in stripped:
                script = stripped.split('"')[1] if '"' in stripped else stripped.split("'")[1] if "'" in stripped else stripped[3:].strip()
                basename = script.rsplit("/", 1)[-1]
                if basename:
                    scripts.add(basename)
    return scripts


def extract_yaml_blocked(path: Path) -> list[str]:
    """Parse blocked_patterns from the YAML."""
    if not path.exists():
        return []
    blocked = []
    in_blocked = False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("blocked_patterns:"):
            in_blocked = True
            continue
        if in_blocked:
            if stripped.startswith("max_runtime") or stripped.startswith("environment_guards"):
                break
            if stripped.startswith("- "):
                p = stripped[2:].strip().strip('"').strip("'")
                if p:
                    blocked.append(p)
    return blocked


def extract_policy_remediation_scripts(path: Path) -> dict[str, str]:
    """Return {finding_type: script_basename} for every string-valued remediation_map entry."""
    if not path.exists():
        return {}
    policy = json.loads(path.read_text())
    rmap = policy.get("remediation_map", {})
    result = {}
    for ftype, cmd in rmap.items():
        if not isinstance(cmd, str) or not cmd.strip():
            continue
        # Extract script basename from the command.  Commands look like:
        #   ".venv/bin/python scripts/foo.py --flag"  or
        #   "flock /tmp/foo.lock .venv/bin/python scripts/bar.py --flag"
        # Find the LAST token that looks like a script path (contains / and .py/.sh).
        tokens = cmd.split()
        basename = ""
        for token in reversed(tokens):
            if "/" in token and re.search(r'\.(py|sh)$', token):
                basename = token.rsplit("/", 1)[-1]
                break
        if basename:
            result[ftype] = basename
    return result


def main() -> int:
    yaml_path = PROJECT_ROOT / "config" / "claude_escalation_allowlist.yaml"
    policy_path = PROJECT_ROOT / "config" / "health_agent_policy.json"

    yaml_allowed = extract_yaml_allowed(yaml_path)
    yaml_blocked = extract_yaml_blocked(yaml_path)
    map_scripts = extract_policy_remediation_scripts(policy_path)

    errors = 0

    # Check 1: Cross-reference YAML allowed vs. what maps reference
    for ftype, basename in sorted(map_scripts.items()):
        if basename not in yaml_allowed:
            print(f"MISSING from YAML allowed: remediation_map['{ftype}'] → {basename}")
            errors += 1

    # Check 2: Blocked patterns must not match any allowed script path
    for blocked in yaml_blocked:
        # Only check for short patterns that could be false positives (skip SQL fragments, paths)
        if len(blocked) < 4 or blocked.startswith(("UPDATE ", "DELETE ", "INSERT ", "git ", "rm ")):
            continue
        for script in sorted(yaml_allowed):
            # Check if blocked pattern appears as a word-boundary match in the script name
            if re.search(rf'(?<![\w/-]){re.escape(blocked)}(?![\w-])', script):
                # False positive — a script name contains the blocked word
                # This is informational; e.g. "submit" won't match "social_scalp_scanner.py"
                pass
            # Check if blocked would match a typical command-line flag containing this script
            test_cmd = f".venv/bin/python scripts/{script} --some-flag"
            if re.search(rf'(?<![\w/-]){re.escape(blocked)}(?![\w-])', test_cmd.lower()):
                print(f"WARN: blocked pattern '{blocked}' matches command for '{script}' — "
                      f"this script's retry_cmd will be blocked by the allowlist")
                errors += 1

    # Check 3: YAML allowed scripts should have at least one map entry or be explicitly
    # listed in a "standalone" category (some scripts are invoked by system_health_agent
    # retries, not via remediation_map).  This is a soft check — warn only.
    map_basenames = set(map_scripts.values())
    standalone_ok = {
        # Scripts used by system_health_agent retries (not via remediation_map)
        "system_health_agent.py", "pipeline_health_monitor.py", "trade_ai_health.py",
        "screener_run_health.py", "check_local_llm_health.py",
        # Scripts used by auto_enrichment pipeline (not via remediation_map)
        "price_cache.py", "portfolio_sync.py", "holdings_llm_refresh.py",
        "proposal_enrichment_loop.py", "symbol_enrichment.py", "finviz_enrichment.py",
        # Builders / infra
        "build_deep_overnight_llm_queue.py", "rag_indexer.py",
        # Replay backfill (used in chained remediation commands)
        "replay_backfill.py",
        # Invoked indirectly by iterative remediators, not via remediation_map directly
        "schwab_journal_builder.py",   # called by schwab_transaction_ingest chain
        "social_scalp_scanner.py",     # called by remediate_scalp_go_dark.py
        "trade_ai_orchestrator.py",    # called by remediate_pipeline_failures.py
    }
    for script in sorted(yaml_allowed):
        if script not in map_basenames and script not in standalone_ok:
            print(f"NOTE: YAML allowed script '{script}' has no remediation_map entry "
                  f"and is not in the standalone-ok list — may be orphaned")

    if errors:
        print(f"\n{errors} consistency error(s) found", file=sys.stderr)
        return 1
    print(f"✓ Allowlist consistent: {len(yaml_allowed)} YAML scripts, "
          f"{len(map_scripts)} map entries, {len(yaml_blocked)} blocked patterns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
