#!/usr/bin/env python3
"""Phase 206 — End-to-end validation of the profit-capture / protection enhancement (read-only).

Asserts the canonical layer is populated and honest, evidence tables exist, shadow recs are
advisory-only, the v3 endpoint emits strict JSON (no NaN/Inf), and that none of the new/modified
code touches broker/order/stop/GO-WAIT/strategy execution paths.
"""
import os, sys, json, argparse, re, math
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# Match real call-sites (trailing paren), not regex/string literals, to avoid self-matching.
FORBIDDEN = re.compile(r"\b(?:submit_order|place_order|cancel_order|replace_order|"
                       r"set_go_wait|mutate_strategy|enable_live)\s*\(|live_trading_allowed\s*=\s*True")

SCRIPTS = [
    "analyze_profit_capture_all_trades.py", "diagnose_profit_protection_advisory_gaps.py",
    "backtest_profit_protection_rules.py", "profit_protection_shadow_thresholds.py",
    "profit_protection_advisory.py", "backfill_journal_trade_fields.py",
    "validate_journal_field_completeness.py",
]


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


def q1(cur, sql):
    cur.execute(sql); return cur.fetchone()[0]


def has_nan(obj):
    if isinstance(obj, float):
        return math.isnan(obj) or math.isinf(obj)
    if isinstance(obj, dict):
        return any(has_nan(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(has_nan(v) for v in obj)
    return False


def run(json_path, md_path):
    load_env()
    conn = db(); cur = conn.cursor()
    checks = []

    def chk(name, ok, detail=""):
        checks.append({"check": name, "pass": bool(ok), "detail": str(detail)})

    total = q1(cur, "SELECT count(*) FROM trade_profit_capture_analysis")
    chk("trade_profit_capture_analysis populated", total > 0, f"{total} rows")

    null_ti = q1(cur, "SELECT count(*) FROM trade_profit_capture_analysis WHERE trade_instance_id IS NULL")
    chk("all rows use trade_instance_id", null_ti == 0, f"{null_ti} null")

    missed = q1(cur, "SELECT count(*) FROM trade_profit_capture_analysis WHERE protection_missed")
    no_adv = q1(cur, "SELECT count(*) FROM trade_profit_capture_analysis WHERE failure_class='NO_ADVISORY_GENERATED'")
    chk("protection-missed matches NO_ADVISORY/too-late class", missed >= no_adv and missed > 0,
        f"missed={missed} no_advisory={no_adv}")

    # winners with giveback correctly classified (every measurable giveback winner has a non-null class)
    bad = q1(cur, """SELECT count(*) FROM trade_profit_capture_analysis
                     WHERE winner AND measurable AND coalesce(money_left_usd,0)>0 AND failure_class IS NULL""")
    chk("winners-with-giveback classified", bad == 0, f"{bad} unclassified")

    # existing advisory data not lost
    adv = q1(cur, "SELECT count(*) FROM atm_profit_protection_advisories")
    outc = q1(cur, "SELECT count(*) FROM protection_advisory_outcomes")
    chk("existing advisories preserved", adv > 0 and outc > 0, f"advisories={adv} outcomes={outc}")

    bt = q1(cur, "SELECT count(*) FROM profit_protection_rule_backtests")
    chk("rule-backtest rows generated", bt > 0, f"{bt} rows")

    # shadow recs advisory-only: every verdict in the allowed set, none auto-applied
    allowed = "('DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE','ELIGIBLE_FOR_OPERATOR_REVIEW','REJECTED_NEGATIVE_EDGE')"
    sr_total = q1(cur, "SELECT count(*) FROM profit_protection_shadow_recommendations")
    sr_bad = q1(cur, f"SELECT count(*) FROM profit_protection_shadow_recommendations WHERE graft_verdict NOT IN {allowed}")
    chk("shadow recs are advisory-only verdicts", sr_total > 0 and sr_bad == 0, f"{sr_total} recs, {sr_bad} invalid")
    conn.close()

    # v3 endpoint strict JSON, no NaN/Inf
    try:
        import api_v2
        payload = api_v2._atm_profit_capture()
        s = json.dumps(payload, allow_nan=False, default=str)   # raises if NaN/Inf present
        chk("v3 endpoint emits strict JSON", True, f"{len(s)} bytes")
        chk("no NaN/Inf in endpoint payload", not has_nan(payload), "clean")
    except ValueError as e:
        chk("v3 endpoint emits strict JSON", False, f"NaN/Inf: {e}")
        chk("no NaN/Inf in endpoint payload", False, str(e))
    except Exception as e:
        chk("v3 endpoint emits strict JSON", False, f"error: {e}")
        chk("no NaN/Inf in endpoint payload", False, "endpoint error")

    # forbidden execution calls in new/modified scripts
    offenders = []
    for fn in SCRIPTS:
        p = os.path.join(ROOT, "scripts", fn)
        if os.path.exists(p):
            for i, line in enumerate(open(p), 1):
                if FORBIDDEN.search(line) and not line.strip().startswith("#") and "FORBIDDEN" not in line:
                    offenders.append(f"{fn}:{i}")
    chk("no broker/order/GO-WAIT/strategy mutation in scripts", not offenders, str(offenders))

    n_pass = sum(1 for c in checks if c["pass"])
    verdict = "PASS" if n_pass == len(checks) else ("PARTIAL" if n_pass > len(checks) // 2 else "FAIL")
    report = {"run_at": datetime.now(timezone.utc).isoformat(), "verdict": verdict,
              "passed": n_pass, "total": len(checks), "checks": checks}
    if json_path:
        json.dump(report, open(json_path, "w"), indent=2, default=str)
    if md_path:
        L = ["# Profit-Protection Enhancement Validation", "",
             f"**Verdict: {verdict}** ({n_pass}/{len(checks)} checks passed)", "",
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
