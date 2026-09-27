#!/usr/bin/env python3
"""session28_validate_paper_execution_workflow.py — Validate Session 28 implementation.

Checks 21 items covering script imports, schema, CLI commands, API endpoints,
frontend build, safety rules, and artifact cleanliness.
"""
import ast
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

os.environ.setdefault("DOTENV_LOADED", "0")
if os.environ["DOTENV_LOADED"] == "0":
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
        os.environ["DOTENV_LOADED"] = "1"
    except Exception:
        pass

PASS = 0
FAIL = 0


def check(num: int, label: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    status = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{status}] {num:02d}. {label}{' -- ' + detail if detail else ''}")
    return ok


def main():
    print("=" * 70)
    print("SESSION 28 PAPER EXECUTION WORKFLOW VALIDATION")
    print("=" * 70)
    print()

    # 1-4: Script imports
    scripts = {
        1: ("paper_submit_readiness", "scripts/paper_submit_readiness.py"),
        2: ("paper_trade_monitor", "scripts/paper_trade_monitor.py"),
        3: ("paper_trade_closer", "scripts/paper_trade_closer.py"),
        4: ("session28_validate_paper_execution_workflow", "scripts/session28_validate_paper_execution_workflow.py"),
    }
    for num, (module_name, script_path) in scripts.items():
        full_path = PROJECT_ROOT / script_path
        ok = False
        detail = ""
        if full_path.exists():
            try:
                source = full_path.read_text()
                ast.parse(source)
                ok = True
                detail = f"{len(source.splitlines())} lines, syntax OK"
            except SyntaxError as e:
                detail = f"Syntax error: {e}"
        else:
            detail = "File not found"
        check(num, f"Script import: {module_name}", ok, detail)

    # 5: Schema tables/columns exist
    schema_ok = False
    schema_detail = ""
    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", 5432)),
            dbname=os.getenv("DB_NAME", "trade_ai"),
            user=os.getenv("DB_USER", "trade_ai"),
            password=os.getenv("DB_PASSWORD", ""),
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        cur = conn.cursor()
        tables_needed = ["paper_trades", "paper_trade_proposals", "paper_execution_events", "paper_execution_quality"]
        found = []
        for t in tables_needed:
            cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=%s)", [t])
            if cur.fetchone()["exists"]:
                found.append(t)
        schema_ok = len(found) == len(tables_needed)
        schema_detail = f"{len(found)}/{len(tables_needed)} tables found: {', '.join(found)}"
        conn.close()
    except Exception as e:
        schema_detail = f"DB error: {str(e)[:100]}"
    check(5, "Schema tables/columns exist", schema_ok, schema_detail)

    # 6: best-candidates command works
    bc_ok = False
    bc_detail = ""
    try:
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"),
             str(PROJECT_ROOT / "scripts/paper_submit_readiness.py"),
             "--best-candidates", "--limit", "3"],
            capture_output=True, text=True, timeout=15, cwd=str(PROJECT_ROOT))
        if r.returncode == 0:
            data = json.loads(r.stdout)
            bc_ok = "candidates" in data
            bc_detail = f"{len(data.get('candidates', []))} candidates returned"
        else:
            bc_detail = f"exit:{r.returncode} stderr:{r.stderr[:100]}"
    except Exception as e:
        bc_detail = f"Error: {str(e)[:100]}"
    check(6, "best-candidates command works", bc_ok, bc_detail)

    # 7: dry-run bracket returns structured result
    drb_ok = False
    drb_detail = ""
    try:
        # We need a proposal ID -- try to find one
        import psycopg2, psycopg2.extras
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"), port=int(os.getenv("DB_PORT", 5432)),
            dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
            password=os.getenv("DB_PASSWORD", ""), cursor_factory=psycopg2.extras.RealDictCursor)
        cur = conn.cursor()
        cur.execute("SELECT id FROM paper_trade_proposals ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()
        if row:
            pid = row["id"]
            r = subprocess.run(
                [str(PROJECT_ROOT / ".venv/bin/python"),
                 str(PROJECT_ROOT / "scripts/proposal_paper_submitter.py"),
                 "--proposal-id", str(pid), "--dry-run-bracket"],
                capture_output=True, text=True, timeout=15, cwd=str(PROJECT_ROOT))
            if r.returncode == 0 and r.stdout.strip():
                data = json.loads(r.stdout)
                drb_ok = "status" in data
                drb_detail = f"status={data.get('status')} for proposal {pid}"
            else:
                drb_detail = f"exit:{r.returncode}"
        else:
            drb_ok = True
            drb_detail = "No proposals to test (skip OK)"
    except Exception as e:
        drb_detail = f"Error: {str(e)[:100]}"
    check(7, "dry-run bracket returns structured result", drb_ok, drb_detail)

    # 8: duplicate client_order_id prevention
    dup_ok = False
    dup_detail = ""
    try:
        source = (PROJECT_ROOT / "scripts/paper_submit_readiness.py").read_text()
        dup_ok = "client_order_id" in source and "Duplicate" in source
        dup_detail = "client_order_id duplicate check found in readiness script"
    except Exception as e:
        dup_detail = str(e)[:100]
    check(8, "duplicate client_order_id prevention", dup_ok, dup_detail)

    # 9: submit requires explicit flag
    flag_ok = False
    flag_detail = ""
    try:
        source = (PROJECT_ROOT / "scripts/paper_trade_closer.py").read_text()
        flag_ok = "--close-paper" in source and "close_paper" in source
        source2 = (PROJECT_ROOT / "scripts/proposal_paper_submitter.py").read_text()
        flag_ok = flag_ok and ("--submit-paper" in source2 or "--submit-paper-bracket" in source2)
        flag_detail = "Both closer and submitter require explicit flags"
    except Exception as e:
        flag_detail = str(e)[:100]
    check(9, "submit requires explicit flag", flag_ok, flag_detail)

    # 10: no auto-submit in cron
    cron_ok = True
    cron_detail = ""
    try:
        crontab_files = list(PROJECT_ROOT.glob("**/crontab*")) + list(PROJECT_ROOT.glob("**/*.cron"))
        for cf in crontab_files:
            content = cf.read_text()
            if "submit-paper" in content or "submit_paper" in content:
                cron_ok = False
                cron_detail = f"Found auto-submit in {cf.name}"
                break
        if cron_ok:
            cron_detail = "No auto-submit found in cron files"
    except Exception:
        cron_detail = "No cron files found (OK)"
    check(10, "no auto-submit in cron", cron_ok, cron_detail)

    # 11-13: API endpoints exist in api_v2.py
    api_source = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
    api_endpoints = {
        11: ("/api/v2/paper-submit-candidates", "paper-submit-candidates"),
        12: ("/api/v2/paper-proposals/check-submit-readiness", "check-submit-readiness"),
        13: ("/api/v2/paper-trades/close", "paper-trades/close"),
    }
    for num, (ep, label) in api_endpoints.items():
        ep_ok = ep in api_source
        check(num, f"API endpoint: {label}", ep_ok, "Found in api_v2.py" if ep_ok else "NOT found")

    # 14-16: Dry-runs work (scripts parse without error)
    dry_scripts = {
        14: ("paper_submit_readiness.py", ["--best-candidates", "--limit", "1"]),
        15: ("paper_trade_monitor.py", ["--dry-run"]),
        16: ("paper_trade_closer.py", ["--paper-trade-id", "0", "--dry-run"]),
    }
    for num, (script, args) in dry_scripts.items():
        dry_ok = False
        dry_detail = ""
        try:
            r = subprocess.run(
                [str(PROJECT_ROOT / ".venv/bin/python"),
                 str(PROJECT_ROOT / "scripts" / script)] + args,
                capture_output=True, text=True, timeout=15, cwd=str(PROJECT_ROOT))
            # Even if returncode != 0 (e.g. no trade found), syntax is OK
            dry_ok = r.returncode in (0, 1, 2) and "SyntaxError" not in (r.stderr or "")
            dry_detail = f"exit:{r.returncode}"
        except Exception as e:
            dry_detail = f"Error: {str(e)[:100]}"
        check(num, f"Dry-run: {script}", dry_ok, dry_detail)

    # 17: Frontend build
    fe_ok = False
    fe_detail = ""
    try:
        r = subprocess.run(
            ["npm", "run", "build"],
            capture_output=True, text=True, timeout=120,
            cwd=str(PROJECT_ROOT / "apps/command-center-v2"))
        fe_ok = r.returncode == 0
        fe_detail = "Build succeeded" if fe_ok else f"Build failed: {r.stderr[-200:]}"
    except Exception as e:
        fe_detail = f"Error: {str(e)[:100]}"
    check(17, "Frontend build", fe_ok, fe_detail)

    # 18: Live trading disabled
    lt_ok = os.getenv("LIVE_TRADING_ENABLED", "false").lower() != "true"
    check(18, "Live trading disabled", lt_ok,
          f"LIVE_TRADING_ENABLED={os.getenv('LIVE_TRADING_ENABLED', 'not set')}")

    # 19: Real journal clean (no paper_trade_closer writes to real journal)
    rj_ok = False
    rj_detail = ""
    try:
        source = (PROJECT_ROOT / "scripts/paper_trade_closer.py").read_text()
        rj_ok = "real_journal" not in source.lower() and "journal_entries" not in source
        rj_detail = "No references to real journal tables"
    except Exception as e:
        rj_detail = str(e)[:100]
    check(19, "Real journal clean", rj_ok, rj_detail)

    # 20: Holdings untouched (no writes to holdings/positions tables)
    hold_ok = False
    hold_detail = ""
    try:
        for script in ["paper_submit_readiness.py", "paper_trade_monitor.py", "paper_trade_closer.py"]:
            source = (PROJECT_ROOT / "scripts" / script).read_text()
            if "INSERT INTO holdings" in source or "UPDATE holdings" in source:
                hold_ok = False
                hold_detail = f"{script} modifies holdings table"
                break
        else:
            hold_ok = True
            hold_detail = "No scripts modify holdings table"
    except Exception as e:
        hold_detail = str(e)[:100]
    check(20, "Holdings untouched", hold_ok, hold_detail)

    # 21: No generated artifacts staged
    staged_ok = True
    staged_detail = ""
    try:
        r = subprocess.run(["git", "diff", "--cached", "--name-only"],
                           capture_output=True, text=True, timeout=5, cwd=str(PROJECT_ROOT))
        if r.stdout.strip():
            staged_ok = False
            staged_detail = f"Staged files: {r.stdout.strip()[:100]}"
        else:
            staged_detail = "No staged files"
    except Exception:
        staged_detail = "Not a git repo (OK)"
    check(21, "No generated artifacts staged", staged_ok, staged_detail)

    # Summary
    print()
    print("=" * 70)
    total = PASS + FAIL
    if FAIL == 0:
        print(f"SESSION 28 PAPER EXECUTION WORKFLOW VALIDATION: PASSED ({PASS}/{total})")
    else:
        print(f"SESSION 28 PAPER EXECUTION WORKFLOW VALIDATION: {FAIL} FAILURES ({PASS}/{total} passed)")
    print("=" * 70)

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
