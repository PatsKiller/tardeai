#!/usr/bin/env python3
"""Ruff's flake8-bandit (S) rules with a baseline: only NEW findings fail a PR.

Operator 2026-11-02: "remove CodeQL completely. Ruff and Gitleaks run on every change... Semgrep and
the package audits run every night." This is the per-change half that replaces CodeQL's static
analysis; gitleaks already runs per change inside `secret-scan`.

The baseline is a count per (file, rule) taken when the rules were first switched on. A file that
gains a finding, or an existing finding that grows, fails; a fixed finding leaves a stale baseline
line that `--update-baseline` removes. Nothing is auto-ignored by path: the baseline is the only
allowance, and it can only shrink.

    python3 scripts/check_ruff_security.py                  # compare against the baseline
    python3 scripts/check_ruff_security.py --update-baseline
    python3 scripts/check_ruff_security.py --json

Read-only: it runs ruff and reads its own baseline. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "config" / "ruff_security_baseline.json"
SCHEMA = "RuffSecurityBaseline@v1"
RULESET = "S"
#: Production code only: a test's own `assert` is not a security finding, and a new test file would
#: otherwise fail on every assertion it contains.
SCAN_PATHS = tuple(p for p in ("scripts", "apps", "lib") if (ROOT / p).is_dir())
Runner = Callable[[list[str]], tuple[int, str]]


def _default_runner(argv: list[str]) -> tuple[int, str]:
    # stdout only: ruff's human summary on stderr would corrupt the JSON document.
    proc = subprocess.run([sys.executable, "-m", "ruff", *argv], cwd=str(ROOT),
                          capture_output=True, text=True, check=False)
    return proc.returncode, (proc.stdout or "")


def scan(*, runner: Runner | None = None) -> dict[str, dict[str, int]]:
    """{(repo-relative file): {rule code: count}} for every S finding in the tree."""
    run = runner or _default_runner
    rc, out = run(["check", "--select", RULESET, "--output-format", "json", "--no-cache", *SCAN_PATHS])
    # ruff exits 1 when it reports findings; only a parse failure is an error here.
    try:
        rows = json.loads(out) if out.strip() else []
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ruff --select {RULESET} returned non-JSON: {exc}") from exc
    counts: dict[str, Counter[str]] = {}
    for row in rows:
        code = str(row.get("code") or "")
        path = str(row.get("filename") or "")
        if not code.startswith("S") or not path:  # ruff's own parse errors are not S findings
            continue
        try:
            rel = str(Path(path).resolve().relative_to(ROOT))
        except ValueError:
            rel = path
        counts.setdefault(rel, Counter())[code] += 1
    return {f: dict(c) for f, c in counts.items()}


def load_baseline(path: Path = BASELINE) -> dict[str, dict[str, int]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): {str(r): int(n) for r, n in (v or {}).items()} for k, v in (doc.get("findings") or {}).items()}


def compare(current: dict[str, dict[str, int]], baseline: dict[str, dict[str, int]]) -> dict[str, Any]:
    """New findings (fail) and stale baseline lines (report: the debt was paid)."""
    new: list[str] = []
    for path, rules in sorted(current.items()):
        for rule, count in sorted(rules.items()):
            allowed = int((baseline.get(path) or {}).get(rule, 0))
            if count > allowed:
                new.append(f"{path}: {rule} {count} (baseline {allowed})")
    stale: list[str] = []
    for path, rules in sorted(baseline.items()):
        for rule, allowed in sorted(rules.items()):
            if int((current.get(path) or {}).get(rule, 0)) < int(allowed):
                stale.append(f"{path}: {rule} {int((current.get(path) or {}).get(rule, 0))} (baseline {allowed})")
    total = sum(sum(r.values()) for r in current.values())
    return {"ok": not new, "new": new, "stale": stale, "total": total,
            "files": len(current), "schema": SCHEMA}


def render_baseline(current: dict[str, dict[str, int]]) -> str:
    return json.dumps({"schema": SCHEMA, "ruleset": RULESET,
                       "_why": "Baseline of flake8-bandit findings at adoption (2026-11-02). Only NEW "
                               "findings fail; this file can only shrink. Update with "
                               "`python3 scripts/check_ruff_security.py --update-baseline`.",
                       "findings": {p: dict(sorted(r.items())) for p, r in sorted(current.items())}},
                      indent=2, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    current = scan()
    if a.update_baseline:
        BASELINE.write_text(render_baseline(current), encoding="utf-8")
        print(f"baseline written: {sum(sum(r.values()) for r in current.values())} findings in {len(current)} files")
        return 0
    result = compare(current, load_baseline())
    if a.json:
        print(json.dumps(result, indent=2))
    elif result["ok"]:
        print(f"ruff {RULESET}: no new findings ({result['total']} baselined across {result['files']} files)")
        for s in result["stale"][:10]:
            print("  stale (lower the baseline):", s)
    else:
        print("NEW security findings (fix them, or justify and re-baseline deliberately):")
        for n in result["new"][:40]:
            print("  ", n)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
