#!/usr/bin/env python3
"""compare_portfolio_maintenance_outputs.py — Phase 202F output diff (READ-ONLY).

The portfolio-maintenance controller invokes the BYTE-IDENTICAL launchers the legacy timers use
(same linux_launchers/*.sh), so output equivalence is by construction. This tool verifies the
controller's --apply run actually PRODUCED the expected output set — fresh, non-empty, valid — and
that excluded jobs (price_cache, db_retention) did NOT run. Exits 0 on PASS. Mutates nothing.

Acceptable differences: timestamp / run_id / path / formatting. Unacceptable: missing output,
empty/invalid output, an excluded job that ran, or a P0 step not ok.
"""
import json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUMMARY = os.path.join(ROOT, "data", "runtime", "portfolio_maintenance_pipeline_last_run.json")
HOME = os.path.expanduser("~")

# expected outputs produced by the P0-safe launchers
EXPECTED = [
    {"label": "db backup (.sql.gz)", "kind": "newest_glob", "dir": os.path.join(HOME, "db_backups"),
     "suffix": ".sql.gz", "min_bytes": 1000},
    {"label": "portfolio report html", "kind": "file",
     "path": os.path.join(ROOT, "data/portfolios/reports/portfolio_live.html"), "min_bytes": 100},
    {"label": "lookthrough holdings.json", "kind": "json",
     "path": os.path.join(ROOT, "data/portfolios/state/holdings.json"), "min_bytes": 2},
]
EXCLUDED_MUST_NOT_RUN = {"price_cache", "db_retention"}


def newest_in(dirp, suffix):
    if not os.path.isdir(dirp):
        return None
    files = [os.path.join(dirp, f) for f in os.listdir(dirp) if f.endswith(suffix)]
    return max(files, key=os.path.getmtime) if files else None


def main():
    unacceptable, acceptable = [], []
    if not os.path.exists(SUMMARY):
        print("FAIL: no summary JSON — controller apply did not complete")
        return 1
    summ = json.load(open(SUMMARY))
    if summ.get("dry_run"):
        unacceptable.append(("summary", "last run was a DRY_RUN, not --apply"))
    # step statuses
    steps = {s["name"]: s["status"] for s in summ.get("steps", [])}
    p0 = ["portfolio_backup", "portfolio_daily_report", "portfolio_weekly_report",
          "portfolio_monthly_report", "portfolio_lookthrough", "secrets_state_backup"]
    for s in p0:
        st = steps.get(s, "MISSING")
        if st != "ok":
            unacceptable.append((f"step:{s}", f"status={st} (expected ok)"))
    # excluded must NOT have run
    for x in EXCLUDED_MUST_NOT_RUN:
        if steps.get(x) not in (None, "EXCLUDED_NOT_RUN"):
            unacceptable.append((f"excluded:{x}", f"ran with status={steps.get(x)} — MUST be EXCLUDED_NOT_RUN"))
        else:
            acceptable.append((f"excluded:{x}", "correctly EXCLUDED_NOT_RUN"))

    # expected outputs produced, fresh (within 1 day), non-empty/valid
    now = time.time()
    for e in EXPECTED:
        if e["kind"] == "newest_glob":
            p = newest_in(e["dir"], e["suffix"])
            if not p:
                unacceptable.append((e["label"], f"no {e['suffix']} in {e['dir']}")); continue
        else:
            p = e["path"]
            if not os.path.exists(p):
                unacceptable.append((e["label"], f"missing: {p}")); continue
        sz = os.path.getsize(p); age_h = (now - os.path.getmtime(p)) / 3600.0
        if sz < e["min_bytes"]:
            unacceptable.append((e["label"], f"too small ({sz}B < {e['min_bytes']})")); continue
        if e["kind"] == "json":
            try:
                json.load(open(p))
            except Exception as ex:
                unacceptable.append((e["label"], f"invalid JSON: {str(ex)[:50]}")); continue
        if age_h > 26:
            unacceptable.append((e["label"], f"stale ({age_h:.1f}h old) — controller did not refresh")); continue
        acceptable.append((e["label"], f"present {sz}B, fresh {age_h:.2f}h (timestamp diff only)"))

    verdict = "PASS" if not unacceptable else "FAIL"
    print(f"PORTFOLIO-MAINTENANCE OUTPUT DIFF: {verdict} ({len(unacceptable)} unacceptable)")
    print(f"  run_ts={summ.get('run_ts_utc')} dry_run={summ.get('dry_run')} overall={summ.get('overall_status')}")
    for k, d in acceptable:
        print(f"  OK   {k}: {d}")
    for k, d in unacceptable:
        print(f"  FAIL {k}: {d}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
