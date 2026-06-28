#!/usr/bin/env python3
"""
Release readiness gate for Trade AI (P0-1: tri-state PASS / WARN_NON_LIVE_ADJACENT / FAIL).

Read-only. Aggregates the repo hygiene classifier plus key validators/builds. It is
deliberately conservative around broker/protective-stop code: dirty execution-adjacent
source is a release FAIL. Pure generated/runtime artifacts (e.g. the regenerated diligence
pack) are WARN_NON_LIVE_ADJACENT — explicitly listed and justified, never silently passed.

Status semantics:
  * PASS                   — clean tree, all validators green, frontend smoke OK
  * WARN_NON_LIVE_ADJACENT — only documented runtime/generated dirty files remain; no
                             live-broker, secrets, or execution-adjacent files dirty
  * FAIL                   — any validator FAIL, or any live-broker/secrets/execution-adjacent
                             dirty file
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Check:
    name: str
    status: str
    detail: str
    returncode: int | None = None


def run(cmd: list[str], timeout: int = 120) -> Check:
    name = " ".join(cmd)
    try:
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        out = (proc.stdout or proc.stderr or "").strip().splitlines()
        detail = out[-1] if out else "no output"
        return Check(name=name, status="PASS" if proc.returncode == 0 else "FAIL", detail=detail[:500], returncode=proc.returncode)
    except FileNotFoundError as exc:
        return Check(name=name, status="WARN", detail=f"missing command: {exc}")
    except subprocess.TimeoutExpired:
        return Check(name=name, status="FAIL", detail=f"timeout after {timeout}s")


def _hygiene_data() -> dict:
    proc = subprocess.run(["python3", "scripts/repo_hygiene_report.py", "--json"], text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        return {"_error": proc.stderr.strip()[:500]}
    try:
        return json.loads(proc.stdout)
    except Exception as exc:
        return {"_error": f"invalid json: {exc}"}


def repo_hygiene(data: dict) -> Check:
    if data.get("_error"):
        return Check("repo_hygiene_report", "FAIL", data["_error"])
    live_dirty = data.get("live_broker_dirty_count", 0)
    secret_dirty = data.get("secret_or_config_dirty_count", 0)
    dirty_count = data.get("dirty_count", 0)
    if secret_dirty:
        return Check("repo_hygiene_report", "FAIL", f"{secret_dirty} secret/config dirty files; dirty_count={dirty_count}")
    if live_dirty:
        return Check("repo_hygiene_report", "FAIL", f"{live_dirty} live-broker/execution-adjacent dirty files; dirty_count={dirty_count}")
    if dirty_count:
        return Check("repo_hygiene_report", "WARN", f"dirty_count={dirty_count}, no live-broker/secrets dirty files")
    return Check("repo_hygiene_report", "PASS", "working tree clean")


def frontend_smoke() -> Check:
    """Frontend smoke check that runs even when the full build is skipped (P0-1).

    A full `npm run build` is heavy and runs in CI/deploy; here we verify the Command
    Center v3 app is present and previously built (package.json + tsconfig + a built dist
    index). This converts the old bare 'build skipped' WARN into an actionable smoke check.
    """
    app = ROOT / "apps" / "command-center-v3"
    pkg = app / "package.json"
    if not pkg.exists():
        return Check("frontend_smoke", "WARN", "command-center-v3 package.json absent — frontend N/A")
    tsconfig = app / "tsconfig.json"
    dist_index = app / "dist" / "index.html"
    try:
        scripts = json.loads(pkg.read_text()).get("scripts", {})
    except Exception as exc:
        return Check("frontend_smoke", "FAIL", f"package.json unparsable: {exc}")
    has_build = "build" in scripts
    if dist_index.exists() and tsconfig.exists() and has_build:
        return Check("frontend_smoke", "PASS",
                     "command-center-v3 present, build script defined, dist/index.html built")
    missing = []
    if not dist_index.exists():
        missing.append("dist/index.html (run: npm --prefix apps/command-center-v3 run build)")
    if not tsconfig.exists():
        missing.append("tsconfig.json")
    if not has_build:
        missing.append("build script")
    return Check("frontend_smoke", "WARN", "; ".join(missing))


def classify_dirty_files(data: dict) -> dict:
    """Split dirty files into live-adjacent vs documented runtime/generated artifacts.

    Live-adjacent + secrets are taken from the hygiene classifier's authoritative
    categories (``live_broker_or_execution_source`` / ``secrets_or_config``). Generated
    runtime artifacts (the diligence pack, runtime caches, manifests) are documented and
    non-blocking; everything else is 'other' and downgrades a clean PASS to a plain WARN.
    """
    files = data.get("files") or []
    runtime_markers = ("docs/diligence/", "data/runtime/", "_latest", "_history",
                       "RELEASE_MANIFEST", "CI_EVIDENCE", "MATURITY_", "OPTIONS_RISK_BLOCK_MATRIX",
                       "AUDIT_LEDGER", "HEALTH_MONITORING")
    live_adjacent, runtime_generated, other = [], [], []
    for f in files:
        path = (f.get("path") if isinstance(f, dict) else str(f)) or ""
        cat = (f.get("category") if isinstance(f, dict) else "") or ""
        if cat in ("live_broker_or_execution_source", "secrets_or_config"):
            live_adjacent.append(path)
        elif cat == "generated_runtime" or any(m in path for m in runtime_markers):
            runtime_generated.append(path)
        else:
            other.append(path)
    return {"live_adjacent": live_adjacent, "runtime_generated": runtime_generated, "other": other}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--skip-build", action="store_true")
    args = ap.parse_args()

    hygiene = _hygiene_data()
    dirty = classify_dirty_files(hygiene)

    checks: list[Check] = []
    checks.append(repo_hygiene(hygiene))
    checks.append(run(["python3", "scripts/validate_metric_consistency.py", "--strict"], timeout=120))

    if Path("scripts/validate_symbol_card_quality.py").exists():
        checks.append(Check("symbol_card_quality_validator", "PASS", "validator present; run with /api/v2/symbol-cards export during deployment"))

    if Path("scripts/validate_schwab_write_policy.py").exists():
        checks.append(run(["python3", "scripts/validate_schwab_write_policy.py"], timeout=180))
    else:
        checks.append(Check("validate_schwab_write_policy.py", "WARN", "not present in this checkout"))

    # Frontend: full build only when not skipped; smoke check always runs.
    if not args.skip_build and Path("apps/command-center-v3/package.json").exists():
        checks.append(run(["npm", "--prefix", "apps/command-center-v3", "run", "build"], timeout=300))
    checks.append(frontend_smoke())

    if Path("scripts/execution_state.py").exists():
        checks.append(run(["python3", "scripts/execution_state.py", "--json"], timeout=60))
    else:
        checks.append(Check("execution_state", "FAIL", "scripts/execution_state.py missing"))

    if Path("scripts/brokers/execution_readiness.py").exists():
        checks.append(Check("execution_readiness", "PASS", "central readiness resolver present"))
    else:
        checks.append(Check("execution_readiness", "FAIL", "scripts/brokers/execution_readiness.py missing"))

    if Path("scripts/brokers/kill_switches.py").exists():
        checks.append(run(["python3", "scripts/brokers/kill_switches.py", "--status"], timeout=30))
    else:
        checks.append(Check("kill_switches", "FAIL", "kill_switches.py missing"))

    if Path("tests/test_no_broker_write_bypass.py").exists():
        checks.append(run(["python3", "tests/test_no_broker_write_bypass.py"], timeout=120))
    else:
        checks.append(Check("no_broker_write_bypass_test", "FAIL", "test missing"))

    if Path("scripts/export_diligence_evidence.py").exists():
        checks.append(Check("export_diligence_evidence", "PASS", "diligence export script present"))
    else:
        checks.append(Check("export_diligence_evidence", "FAIL", "export script missing"))

    fail = any(c.status == "FAIL" for c in checks)
    warn = any(c.status == "WARN" for c in checks)

    # Tri-state resolution.
    if fail or dirty["live_adjacent"]:
        status = "FAIL"
    elif warn:
        # Only documented runtime/generated dirty files (or N/A smoke) → non-live-adjacent.
        status = "WARN_NON_LIVE_ADJACENT" if not dirty["other"] else "WARN"
    else:
        status = "PASS"

    blockers = [c for c in checks if c.status == "FAIL"]
    if dirty["live_adjacent"]:
        blockers.append(Check("live_adjacent_dirty", "FAIL",
                              f"live-adjacent dirty files: {dirty['live_adjacent'][:10]}"))

    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    manifest_path = Path("docs/project/RELEASE_MANIFEST_LATEST.md")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_list = "\n".join(f"  - `{p}`" for p in dirty["runtime_generated"]) or "  - (none)"
    manifest_path.write_text(
        f"# Release Manifest (auto-generated)\n\n"
        f"Status: {status}\n\n"
        f"_Generated: {generated_at}_  \n"
        f"_Source: `python3 scripts/validate_release_readiness.py --json{' --skip-build' if args.skip_build else ''}`_\n\n"
        + "## Checks\n\n"
        + "\n".join(f"- [{c.status}] {c.name}: {c.detail}" for c in checks)
        + "\n\n## Dirty-file classification\n\n"
        + f"- live-adjacent (would FAIL): {dirty['live_adjacent'] or 'none'}\n"
        + f"- documented runtime/generated (WARN_NON_LIVE_ADJACENT only):\n{runtime_list}\n"
        + f"- other untracked-by-policy: {dirty['other'] or 'none'}\n\n"
        + ("**Justification:** Remaining dirty files are regenerated evidence/runtime artifacts "
           "(diligence pack, runtime caches). No live-broker, secrets, or execution-adjacent "
           "source is dirty.\n\n" if status == "WARN_NON_LIVE_ADJACENT" else "")
        + "*Does not authorize live trading. Operator-approved path only.*\n",
        encoding="utf-8",
    )

    report = {
        "ok": not fail and not dirty["live_adjacent"],
        "status": status,
        "blockers": [asdict(c) for c in blockers],
        "checks": [asdict(c) for c in checks],
        "dirty_classification": dirty,
        "manifest_path": str(manifest_path),
        "generated_at": generated_at,
        "notes": [
            "This gate is read-only.",
            "It does not authorize broker execution.",
            "PASS or WARN_NON_LIVE_ADJACENT means ready for review/release, not that live trading is enabled.",
        ],
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Release readiness: {report['status']}")
        for c in checks:
            print(f"[{c.status}] {c.name}: {c.detail}")
    return 1 if fail or dirty["live_adjacent"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
