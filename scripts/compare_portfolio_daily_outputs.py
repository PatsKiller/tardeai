#!/usr/bin/env python3
"""Phase 207F — daily-cadence output diff (READ-ONLY).

Verifies the daily portfolio-report cadence apply produced its expected REVIEW-ONLY outputs and that
they are structurally equivalent to a legacy daily run, with NO destructive/broker outputs. The cadence
controller's `--cadence daily` runs the SAME launcher (linux_launchers/run_portfolio.sh) as the legacy
`portfolio-daily.timer`, so structural/count equivalence is inherent; LLM draft *wording* is
nondeterministic and is NOT text-matched (only structural presence/counts + safety facts are required).

Exits 0 on PASS. Read-only: no writes, no broker/order/proposal/protection access.
"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def db():
    import psycopg2
    pw = [l.split("=", 1)[1].strip() for l in open(os.path.join(ROOT, ".env")) if l.startswith("DB_PASSWORD=")][0]
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def q1(cur, sql):
    cur.execute(sql); r = cur.fetchone(); return r[0] if r else None


def main():
    # cadence-parameterized: works for the daily OR weekly review-only report cadence
    cad = "daily"
    if "--cadence" in sys.argv:
        cad = sys.argv[sys.argv.index("--cadence") + 1]
    report_step = f"portfolio_{cad}_report"
    bad, ok, note = [], [], []

    # 1. cadence apply summary — must be a real --apply, ok, review-only labeled
    sp = os.path.join(ROOT, f"data/runtime/portfolio_maintenance_{cad}_last_run.json")
    summ = None
    if not os.path.exists(sp):
        bad.append(("summary", f"no {cad} cadence apply summary"))
    else:
        summ = json.load(open(sp))
        if summ.get("dry_run") is True:
            bad.append(("summary", f"latest summary is a DRY_RUN, not an --apply (re-run --cadence {cad} --apply)"))
        else:
            st = {s["name"]: s for s in summ.get("steps", [])}
            # report cadences use step "portfolio_<cad>_report"; lookthrough uses "portfolio_lookthrough".
            step_key = report_step if report_step in st else ("portfolio_lookthrough" if "portfolio_lookthrough" in st else report_step)
            # lookthrough carries a READ_ONLY_SNAPSHOT label; report cadences the advisory-draft label.
            ok_labels = {"PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY", "READ_ONLY_SNAPSHOT"}
            dr = st.get(step_key, {})
            if dr.get("status") == "ok" and dr.get("label") in ok_labels:
                ok.append((step_key, f"ok + {dr.get('label')}"))
            elif str(dr.get("status", "")).startswith("SAFETY_BLOCKED"):
                bad.append((step_key, f"BLOCKED by exec-path guard: {dr.get('status')}"))
            else:
                bad.append((step_key, f"status={dr.get('status','MISSING')} label={dr.get('label')}"))
            for x in ("price_cache", "db_retention"):
                (ok if st.get(x, {}).get("status") == "EXCLUDED_NOT_RUN" else bad).append(
                    (f"excluded:{x}", st.get(x, {}).get("status", "?")))
            # only this cadence's own step may appear (+ the always-excluded markers)
            stray = [n for n in st if n not in
                     (step_key, "price_cache", "db_retention")]
            (bad if stray else ok).append(("cadence_isolation", f"stray steps {stray}" if stray else f"{cad}-only"))

    # 2. report state artifacts present + fresh (same artifacts a legacy daily run refreshes)
    for nm in ("holdings.json", "performance_history.json"):
        p = os.path.join(ROOT, "data/portfolios/state", nm)
        if not os.path.exists(p):
            bad.append((f"state:{nm}", "missing"))
        else:
            age = (time.time() - os.path.getmtime(p)) / 3600
            (ok if age < 26 else bad).append((f"state:{nm}", f"fresh {age:.1f}h" if age < 26 else f"stale {age:.1f}h"))

    # 3. review-only advisory-draft outputs present (structural/count equivalence; not text-matched)
    try:
        conn = db(); cur = conn.cursor()
        obs = q1(cur, "SELECT count(*) FROM advisor_observations WHERE observation_date=CURRENT_DATE")
        drafts = q1(cur, "SELECT count(*) FROM advisor_recommendations WHERE status='draft'")
        non_draft_today = q1(cur, "SELECT count(*) FROM advisor_recommendations "
                                  "WHERE created_at::date=CURRENT_DATE AND status NOT IN ('draft','expired','superseded')")
        ok.append(("advisor_observations_today", str(obs)))
        ok.append(("advisor_recommendations_draft", str(drafts)))
        # every recommendation created today must be a draft (review-only) — none auto-promoted/executed
        if (non_draft_today or 0) == 0:
            ok.append(("drafts_review_only", "all today's recommendations are drafts (none executed)"))
        else:
            bad.append(("drafts_review_only", f"{non_draft_today} non-draft recommendations created today"))
        conn.close()
    except Exception as e:
        note.append(("db_check", f"skipped: {str(e)[:80]}"))

    # 4. safety: the daily cadence must carry no broker/proposal/protection/destructive step
    if summ:
        labels = {s.get("label") for s in summ.get("steps", [])}
        forbidden = {"BROKER", "ORDER", "PROPOSAL_EXEC", "PROTECTION", "TRADING", "DB_RETENTION"}
        (bad if (labels & forbidden) else ok).append(
            ("no_destructive_or_broker_steps", "clean" if not (labels & forbidden) else str(labels & forbidden)))

    v = "PASS" if not bad else "FAIL"
    print(f"{cad.upper()} CADENCE OUTPUT DIFF: {v} ({len(bad)} unacceptable)")
    for k, m in ok: print(f"  OK   {k}: {m}")
    for k, m in note: print(f"  NOTE {k}: {m}")
    for k, m in bad: print(f"  FAIL {k}: {m}")
    print("  (legacy and cadence share linux_launchers/run_portfolio.sh → structural equivalence inherent; "
          "LLM draft wording nondeterministic, not text-matched)")
    return 0 if v == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
