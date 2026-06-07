#!/usr/bin/env python3
"""Phase 206b — Validate the hardened profit-capture rule backtest quality layer (read-only).

Asserts: schema fields exist; the quality-gated run is present; raw n AND reliable n are reported;
confidence/verdict key off reliable n; premature-exit cost is flagged unknown under single-peak MFE;
shadow recommendations remain blocked; the v3 endpoint emits strict JSON exposing reliable n /
estimate quality / graft status; no NaN/Inf; no execution/strategy mutation in the touched code.
"""
import os, sys, json, argparse, re, math
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

FORBIDDEN = re.compile(r"\b(?:submit_order|place_order|cancel_order|replace_order|"
                       r"set_go_wait|mutate_strategy|enable_live)\s*\(|live_trading_allowed\s*=\s*True")
SCRIPTS = ["backtest_profit_protection_rules.py", "profit_protection_shadow_thresholds.py",
           "validate_profit_capture_rule_quality.py", "ingest_trade_intrabar_bars.py",
           "profit_protection_path_pricer.py"]
RELIABLE_FLOOR = 20


def load_env():
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ.get("DB_PORT", "5432"),
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def has_nan(o):
    if isinstance(o, float):
        return math.isnan(o) or math.isinf(o)
    if isinstance(o, dict):
        return any(has_nan(v) for v in o.values())
    if isinstance(o, (list, tuple)):
        return any(has_nan(v) for v in o)
    return False


def run(json_path, md_path):
    load_env()
    import psycopg2.extras
    conn = db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    checks = []

    def chk(name, ok, detail=""):
        checks.append({"check": name, "pass": bool(ok), "detail": str(detail)})

    # schema fields exist
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_name='profit_protection_rule_backtests'""")
    cols = {r["column_name"] for r in cur.fetchall()}
    need = {"raw_sample_size", "quality_eligible_sample_size", "triggered_sample_size",
            "winner_sample_size", "reliable_sample_size", "excluded_count", "excluded_reasons",
            "premature_exit_cost_known", "premature_exit_cost_method", "premature_exit_cost_warning",
            "estimate_quality", "result_scope", "graft_verdict"}
    chk("hardened schema fields exist", need <= cols, f"missing={sorted(need - cols)}")

    # latest quality-gated run present
    cur.execute("""SELECT run_id FROM profit_protection_rule_backtests ORDER BY created_at DESC LIMIT 1""")
    lr = cur.fetchone(); latest = lr["run_id"] if lr else None
    cur.execute("""SELECT rule_name, raw_sample_size, reliable_sample_size, recommendation_confidence,
                          premature_exit_cost_known, estimate_quality, graft_verdict, net_improvement
                   FROM profit_protection_rule_backtests WHERE run_id=%s""", (latest,))
    rules = [dict(r) for r in cur.fetchall()]
    chk("quality-gated run present", bool(rules), f"run_id={latest}, rows={len(rules)}")

    # raw n AND reliable n both reported (non-null)
    both = all(r["raw_sample_size"] is not None and r["reliable_sample_size"] is not None for r in rules)
    chk("raw n AND reliable n reported", both and bool(rules), f"{len(rules)} rows")

    # confidence uses reliable n: any row with reliable_n < 10 must be 'insufficient'
    conf_ok = all((r["reliable_sample_size"] >= 10) or (r["recommendation_confidence"] == "insufficient")
                  for r in rules)
    chk("confidence keyed to reliable n", conf_ok, "low-reliable rows are 'insufficient'")

    # premature-exit cost is path-measured where a real intrabar path exists (Phase 206c);
    # otherwise honestly flagged single-peak upper bound.
    path_measured = [r for r in rules if (r["estimate_quality"] or "") == "path_measured"]
    pm_ok = all(r["premature_exit_cost_known"] is True for r in path_measured)
    chk("premature cost path-measured where path exists", pm_ok and bool(path_measured),
        f"{len(path_measured)} path_measured rule rows; all known=true={pm_ok}")

    # estimate quality is one of the honest labels; unknown rows still flagged as such
    valid_est = {"path_measured", "partial_path", "upper_bound_single_peak"}
    est_ok = all((r["estimate_quality"] or "") in valid_est for r in rules)
    unknown_flagged = all((r["premature_exit_cost_known"] is True) or
                          ((r["estimate_quality"] or "").startswith(("upper_bound", "partial")))
                          for r in rules)
    chk("estimate quality honestly labelled", est_ok and unknown_flagged and bool(rules), "")

    # intrabar paths ingested + coverage logged honestly
    cur.execute("SELECT count(*) n, count(DISTINCT trade_instance_id) t FROM trade_intrabar_bars")
    _b = cur.fetchone()
    chk("intrabar paths ingested", _b["n"] > 0 and _b["t"] > 0, f"{_b['n']} bars / {_b['t']} trades")

    # all graft verdicts blocked (reliable n below floor / unknown premature)
    blocked = all(r["graft_verdict"].startswith(("DO_NOT_GRAFT", "REJECTED")) for r in rules)
    max_reliable = max((r["reliable_sample_size"] or 0) for r in rules) if rules else 0
    chk("rule graft verdicts blocked", blocked, f"max_reliable_n={max_reliable} (floor {RELIABLE_FLOOR})")

    # shadow recommendations remain blocked
    cur.execute("""SELECT graft_verdict FROM profit_protection_shadow_recommendations
                   WHERE run_id=(SELECT run_id FROM profit_protection_shadow_recommendations
                                 ORDER BY created_at DESC LIMIT 1)""")
    sr = [r["graft_verdict"] for r in cur.fetchall()]
    chk("shadow recommendations blocked", bool(sr) and all(
        v.startswith(("DO_NOT_GRAFT", "REJECTED")) for v in sr), f"{sr}")
    conn.close()

    # endpoint strict JSON + exposes reliable n / estimate / graft
    try:
        import api_v2
        payload = api_v2._atm_profit_capture()
        s = json.dumps(payload, allow_nan=False, default=str)
        chk("endpoint strict JSON", True, f"{len(s)} bytes")
        chk("no NaN/Inf in payload", not has_nan(payload), "clean")
        summ = payload.get("summary", {})
        ui_ok = all(k in summ for k in ("rule_backtest_reliable_n", "rule_backtest_raw_n",
                    "rule_backtest_estimate_quality", "rule_backtest_graft_verdict"))
        ui_ok = ui_ok and ("estimate" in payload.get("labels", {})) and ("graft" in payload.get("labels", {}))
        chk("endpoint exposes reliable n / estimate / graft", ui_ok, "")
    except ValueError as e:
        chk("endpoint strict JSON", False, f"NaN/Inf: {e}"); chk("no NaN/Inf in payload", False, str(e))
        chk("endpoint exposes reliable n / estimate / graft", False, "endpoint error")
    except Exception as e:
        chk("endpoint strict JSON", False, f"error: {e}"); chk("no NaN/Inf in payload", False, "endpoint error")
        chk("endpoint exposes reliable n / estimate / graft", False, "endpoint error")

    # UI panel surfaces reliable n + graft (static source check)
    panel = os.path.join(ROOT, "apps/command-center-v3/src/components/ProtectionOutcomesPanel.tsx")
    psrc = open(panel).read() if os.path.exists(panel) else ""
    chk("UI panel surfaces reliable n + graft", all(t in psrc for t in
        ("rule_backtest_reliable_n", "rule_backtest_graft_verdict", "rule_backtest_estimate_quality")),
        "tsx references present")

    # forbidden execution calls in touched scripts
    offenders = []
    for fn in SCRIPTS:
        p = os.path.join(ROOT, "scripts", fn)
        if os.path.exists(p):
            for i, line in enumerate(open(p), 1):
                if FORBIDDEN.search(line):
                    offenders.append(f"{fn}:{i}")
    chk("no broker/order/GO-WAIT/strategy mutation", not offenders, str(offenders))

    n_pass = sum(1 for c in checks if c["pass"])
    verdict = "PASS" if n_pass == len(checks) else ("PARTIAL" if n_pass > len(checks)//2 else "FAIL")
    report = {"run_at": datetime.now(timezone.utc).isoformat(), "verdict": verdict,
              "passed": n_pass, "total": len(checks), "checks": checks}
    if json_path:
        json.dump(report, open(json_path, "w"), indent=2, default=str)
    if md_path:
        L = ["# Profit-Capture Rule Quality Validation", "",
             f"**Verdict: {verdict}** ({n_pass}/{len(checks)})", "",
             "| check | pass | detail |", "|-------|------|--------|"]
        for c in checks:
            L.append(f"| {c['check']} | {'✅' if c['pass'] else '❌'} | {c['detail']} |")
        open(md_path, "w").write("\n".join(L) + "\n")
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--markdown", default=None)
    a = ap.parse_args()
    run(a.json, a.markdown)
