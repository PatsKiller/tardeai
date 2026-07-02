#!/usr/bin/env python3
"""Dry test for Hermes audit remediation (2026-07-02) — static + live contract checks."""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "bin" / "python"
if not PY.exists():
    PY = Path(sys.executable)


def run(cmd: list[str], timeout: int = 180) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def check_static() -> list[str]:
    fails: list[str] = []
    required = [
        "config/hermes_score_weights_scalp.yaml",
        "config/hermes_research_budget.yaml",
        "scripts/hermes_scope_governor.py",
        "scripts/hermes_score_history_retention.py",
        "scripts/backfill_hermes_strategy_tags.py",
        "scripts/hermes_tradeai_handshake.py",
        "scripts/hermes_scalp_shadow_feeder.py",
        "scripts/lib/watchlist_priority.py",
    ]
    for rel in required:
        if not (ROOT / rel).exists():
            fails.append(f"missing file: {rel}")

    wp = (ROOT / "scripts/lib/watchlist_priority.py").read_text()
    if "HERMES_SCORER_ALWAYS_CAP" not in wp or "scoring_top_n" not in wp:
        fails.append("watchlist_priority missing scorer cap helpers")
    if "sql_scoring_priority_exists" not in wp:
        fails.append("watchlist_priority missing narrow scoring priority SQL")

    budget = (ROOT / "config/hermes_research_budget.yaml").read_text()
    if "external_cloud_tiers" not in budget or "max_external_symbols_per_run" not in budget:
        fails.append("hermes_research_budget.yaml missing external cloud caps")

    guard = (ROOT / "scripts/hermes_research_budget_guard.py").read_text()
    if "T2 external cloud -> defer" not in guard:
        fails.append("budget guard missing T2 external selftest")

    proc = (ROOT / "scripts/process_watchlist_agent_jobs.py").read_text()
    if "_effective_job_limit" not in proc:
        fails.append("process_watchlist_agent_jobs missing dynamic limit")

    hub = (ROOT / "apps/command-center-v3/src/pages/HermesHub.tsx").read_text()
    if "scalp_kpis" not in hub:
        fails.append("HermesHub missing scalp_kpis strip")

    mat = (ROOT / "scripts/hermes_maturity_dashboard.py").read_text()
    if "_build_scalp_kpis" not in mat:
        fails.append("hermes_maturity_dashboard missing scalp_kpis builder")

    cron = (ROOT / "crontab_backup.txt").read_text()
    for needle in ("hermes_scope_governor", "HERMES_WEIGHTS_PROFILE=scalp", "backfill_hermes_strategy_tags"):
        if needle not in cron:
            fails.append(f"crontab_backup missing: {needle}")
    return fails


def check_budget_selftest() -> tuple[bool, str]:
    code, out = run([str(PY), "scripts/hermes_research_budget_guard.py", "--selftest"])
    try:
        payload = json.loads(out.strip().split("\n")[-1] if "\n" in out.strip() else out)
        ok = code == 0 and bool(payload.get("ok"))
    except Exception:
        ok = code == 0 and '"ok": true' in out
    return ok, out[-1500:]


def check_script_dry_runs() -> list[str]:
    fails: list[str] = []
    scripts = [
        (["scripts/hermes_scope_governor.py", "--dry-run"], "ok"),
        (["scripts/hermes_score_history_retention.py", "--dry-run"], "ok"),
        (["scripts/backfill_hermes_strategy_tags.py"], "ok"),
        (["scripts/hermes_tradeai_handshake.py"], "ok"),
        (["scripts/hermes_scalp_shadow_feeder.py"], "ok"),
    ]
    for args, needle in scripts:
        code, out = run([str(PY)] + args)
        if code != 0 or needle not in out:
            fails.append(f"{args[0]} dry-run failed (rc={code}): {out[-400:]}")
    return fails


def check_maturity_report() -> tuple[bool, str]:
    code, out = run([str(PY), "scripts/hermes_maturity_dashboard.py"], timeout=60)
    if code != 0:
        return False, out[-600:]
    try:
        data = json.loads(out)
        sk = data.get("scalp_kpis")
        if not sk:
            return False, "build_maturity_report missing scalp_kpis"
        for key in ("watchlist_active", "score_inserts_24h", "strategy_tags_populated_pct", "health", "targets"):
            if key not in sk:
                return False, f"scalp_kpis missing {key}"
        return True, (
            f"scalp_kpis OK — active={sk.get('watchlist_active')} "
            f"inserts24h={sk.get('score_inserts_24h')} tags={sk.get('strategy_tags_populated_pct')}%"
        )
    except Exception as e:
        return False, str(e)


def check_maturity_api() -> tuple[bool, str]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:7777/api/v2/hermes/maturity-dashboard", timeout=30) as resp:
            body = resp.read(500000).decode()
        data = json.loads(body)
        sk = data.get("scalp_kpis") or data.get("data", {}).get("scalp_kpis")
        if sk:
            return True, "API scalp_kpis present"
        return False, "API stale (restart api_v2 to load scalp_kpis) — script path verified separately"
    except Exception as e:
        return False, f"API unreachable: {e}"


def check_unit_tests() -> tuple[bool, str]:
    code, out = run([str(PY), "tests/test_hermes_maturity_dashboard.py"], timeout=60)
    return code == 0, out[-800:]


def main() -> int:
    print("=== Hermes audit remediation dry test ===\n")
    all_fails: list[str] = []

    static = check_static()
    for f in static:
        print(f"STATIC FAIL: {f}")
    all_fails.extend(static)
    if not static:
        print("STATIC OK")

    print("\n--- budget guard selftest ---")
    ok, out = check_budget_selftest()
    print(out)
    print("BUDGET SELFTEST", "OK" if ok else "FAIL")
    if not ok:
        all_fails.append("budget guard selftest failed")

    print("\n--- remediation script dry-runs ---")
    dry_fails = check_script_dry_runs()
    for f in dry_fails:
        print(f"DRY-RUN FAIL: {f}")
    all_fails.extend(dry_fails)
    if not dry_fails:
        print("DRY-RUN OK — scope/retention/tags/handshake/shadow")

    print("\n--- maturity report (script) ---")
    mat_ok, mat_msg = check_maturity_report()
    print(mat_msg)
    if not mat_ok:
        all_fails.append(f"maturity report: {mat_msg}")

    print("\n--- maturity API (best-effort) ---")
    api_ok, api_msg = check_maturity_api()
    print(api_msg)
    if not api_ok:
        print("NOTE: API check non-blocking if script report passed")

    print("\n--- unit tests ---")
    test_ok, test_out = check_unit_tests()
    print(test_out)
    if not test_ok:
        all_fails.append("test_hermes_maturity_dashboard failed")

    passed = not all_fails
    print(f"\n{'PASS' if passed else 'FAIL'} — {len(all_fails)} issue(s)")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())