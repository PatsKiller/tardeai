#!/usr/bin/env python3
"""
Repo hygiene classifier for Trade AI.

Read-only. Classifies git dirty files so live-broker-capable releases can
separate real source/docs changes from generated/runtime noise.

Exit codes:
  0 = report generated
  2 = --fail-live-dirty and live broker/source paths are dirty
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

LIVE_BROKER_PREFIXES = (
    "scripts/brokers/",
    "scripts/schwab",
    "scripts/stop_",
    "scripts/grok_stop",
    "scripts/alpaca_stop",
    "apps/command-center-v3/src/components/BrokerOrders",
    "apps/command-center-v3/src/components/OpenTrades",
    "apps/command-center-v3/src/pages/Trading",
    "apps/command-center-v3/src/pages/Portfolio",
)

GENERATED_PREFIXES = (
    "logs/",
    "tmp/",
    "__pycache__/",
    ".pytest_cache/",
    "node_modules/",
    "apps/command-center-v3/dist/",
    "apps/command-center-v2/dist/",
    "data/runtime/",
    "backups/",
)

GENERATED_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".log",
    ".tmp",
    ".tsbuildinfo",
    ".sqlite-shm",
    ".sqlite-wal",
)

SECRET_PATTERNS = (
    ".env",
    "cookie",
    "cookies",
    "secret",
    "secrets",
    "token",
    "credential",
    "credentials",
    "oauth",
)

DOC_PREFIXES = ("docs/",)
SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".sql", ".yaml", ".yml", ".json")


@dataclass
class DirtyFile:
    status: str
    path: str
    category: str
    risk: str
    reason: str


def run_git_status() -> list[tuple[str, str]]:
    proc = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"git status failed: {proc.stderr.strip()}")

    out: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        status = line[:2].strip() or "?"
        path = line[3:] if len(line) > 3 else line[2:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        out.append((status, path))
    return out


def starts_with_any(path: str, prefixes: Iterable[str]) -> bool:
    return any(path.startswith(p) for p in prefixes)


def contains_secret_pattern(path: str) -> bool:
    lower = path.lower()
    return any(p in lower for p in SECRET_PATTERNS)


def classify(path: str) -> tuple[str, str, str]:
    p = Path(path)
    lower = path.lower()

    if contains_secret_pattern(path):
        return "secrets_or_config", "critical", "path name indicates secrets/config/token material"
    if starts_with_any(path, LIVE_BROKER_PREFIXES):
        return "live_broker_or_execution_source", "high", "dirty file touches broker/protective/approval UI or execution-adjacent code"
    if starts_with_any(path, GENERATED_PREFIXES) or lower.endswith(GENERATED_SUFFIXES):
        return "generated_runtime", "low", "generated/runtime/build/cache artifact"
    if starts_with_any(path, DOC_PREFIXES):
        return "documentation", "medium", "documentation change requires A1A/index review if behavior changed"
    if p.suffix.lower() in SOURCE_SUFFIXES:
        return "source", "medium", "source/config/schema change"
    if status_unknown_file(path):
        return "unknown", "medium", "unclassified file type"
    return "other", "low", "non-source file"


def status_unknown_file(path: str) -> bool:
    return Path(path).suffix == ""


def build_report() -> dict:
    rows = []
    for status, path in run_git_status():
        category, risk, reason = classify(path)
        rows.append(DirtyFile(status=status, path=path, category=category, risk=risk, reason=reason))

    by_category = Counter(r.category for r in rows)
    by_risk = Counter(r.risk for r in rows)
    live_dirty = [r for r in rows if r.category == "live_broker_or_execution_source"]
    secret_dirty = [r for r in rows if r.category == "secrets_or_config"]

    return {
        "ok": True,
        "dirty_count": len(rows),
        "by_category": dict(by_category),
        "by_risk": dict(by_risk),
        "live_broker_dirty_count": len(live_dirty),
        "secret_or_config_dirty_count": len(secret_dirty),
        "files": [asdict(r) for r in rows],
    }


def markdown(report: dict) -> str:
    lines = [
        "# Repo Hygiene Report",
        "",
        f"Dirty files: **{report['dirty_count']}**",
        f"Live-broker/execution-adjacent dirty files: **{report['live_broker_dirty_count']}**",
        f"Secrets/config dirty files: **{report['secret_or_config_dirty_count']}**",
        "",
        "## By category",
        "",
    ]
    for key, value in sorted(report["by_category"].items()):
        lines.append(f"- {key}: {value}")
    lines += ["", "## Files", "", "| Risk | Category | Status | Path | Reason |", "|---|---|---:|---|---|"]
    for row in report["files"]:
        lines.append(f"| {row['risk']} | {row['category']} | {row['status']} | `{row['path']}` | {row['reason']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="print JSON report")
    ap.add_argument("--markdown", action="store_true", help="print Markdown report")
    ap.add_argument("--out", help="optional output path")
    ap.add_argument("--fail-live-dirty", action="store_true", help="exit 2 if live broker/source files are dirty")
    args = ap.parse_args()

    report = build_report()
    text = json.dumps(report, indent=2, sort_keys=True) if args.json or not args.markdown else markdown(report)
    if args.out:
        Path(args.out).write_text(text)
    else:
        print(text)

    if args.fail_live_dirty and report["live_broker_dirty_count"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
