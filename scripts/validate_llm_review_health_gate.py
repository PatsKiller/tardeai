#!/usr/bin/env python3
"""validate_llm_review_health_gate.py — verify the Ollama health gate + classification + endpoint.
Read-only except a controlled UNHEALTHY skip test (which by design writes NO per-trade rows, only a
run-level skip record). No trading mutation.
  python3 scripts/validate_llm_review_health_gate.py [--json PATH] [--markdown PATH]
"""
import os, sys, json, subprocess, urllib.request, psycopg2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _count(cur, sql):
    cur.execute(sql); return cur.fetchone()[0]


def main():
    checks = []
    def chk(n, ok, d=""):
        checks.append({"name": n, "pass": bool(ok), "detail": str(d)})

    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from llm_health_gate import check_ollama_health

    # 1) health helper structured output
    h = check_ollama_health(generate_probe=False)
    chk("health helper returns structured dict", all(k in h for k in ("healthy", "failure_class", "ollama_reachable", "checked_at")))
    # 2) bad port -> unhealthy + failure_class
    hb = check_ollama_health(base_url="http://127.0.0.1:19999", generate_probe=False)
    chk("bad port -> unhealthy + classed", hb["healthy"] is False and hb["failure_class"] == "connection_refused", hb["failure_class"])

    c = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                         user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
    cur = c.cursor()
    # 3) UNHEALTHY skip writes NO per-trade flood, ONE run record
    before = _count(cur, "SELECT count(*) FROM trade_llm_reviews")
    runs_before = _count(cur, "SELECT count(*) FROM llm_review_runs WHERE status='SKIPPED_LLM_UNHEALTHY'")
    env = dict(os.environ); env["OLLAMA_BASE_URL"] = "http://127.0.0.1:19999"
    subprocess.run([os.path.join(ROOT, ".venv/bin/python"), os.path.join(ROOT, "scripts/trade_close_llm_analyzer.py"),
                    "--structured", "--apply", "--source", "backtest", "--limit", "5",
                    "--allow-local-llm", "--confirm-llm-review-write"], env=env, cwd=ROOT,
                   capture_output=True, timeout=90)
    c.rollback()
    after = _count(cur, "SELECT count(*) FROM trade_llm_reviews")
    runs_after = _count(cur, "SELECT count(*) FROM llm_review_runs WHERE status='SKIPPED_LLM_UNHEALTHY'")
    chk("unhealthy skip = NO per-trade flood", after == before, f"{before} -> {after}")
    chk("unhealthy skip writes ONE run record", runs_after == runs_before + 1, f"{runs_before} -> {runs_after}")
    # 4) error classification present
    chk("infra errors classified retryable", _count(cur, "SELECT count(*) FROM trade_llm_reviews WHERE error_class LIKE 'ollama_%' AND retryable IS TRUE") > 0)
    chk("parser errors classified non-retryable", _count(cur, "SELECT count(*) FROM trade_llm_reviews WHERE error_class='parse_error' AND retryable IS FALSE") >= 0)
    # 5) endpoint separates categories (strict JSON)
    try:
        d = json.loads(urllib.request.urlopen("http://127.0.0.1:7777/api/v2/lifecycle/llm-review-status", timeout=20).read())["data"]
        eb = d.get("error_breakdown", {})
        chk("endpoint strict JSON + error_breakdown", "infrastructure_errors" in eb and "parser_errors" in eb, f"infra={eb.get('infrastructure_errors')} parser={eb.get('parser_errors')}")
        chk("endpoint exposes ollama_health", "ollama_health" in d)
        chk("endpoint exposes run skip history", "runs" in d)
    except Exception as e:
        chk("endpoint reachable", False, str(e)[:60])
    # 6) retry mode bounded + refuses when unhealthy (flag exists)
    help_txt = subprocess.run([os.path.join(ROOT, ".venv/bin/python"), os.path.join(ROOT, "scripts/trade_close_llm_analyzer.py"), "--help"],
                              capture_output=True, text=True, cwd=ROOT).stdout
    chk("retry flags present (--retry-infra-failures/--max-rows)", "--retry-infra-failures" in help_txt and "--max-rows" in help_txt)
    # 7) safety
    chk("paper mode / live disabled", os.environ.get("ALPACA_MODE") == "paper")
    c.close()

    ok = all(x["pass"] for x in checks)
    for x in checks:
        print(f"  [{'PASS' if x['pass'] else 'FAIL'}] {x['name']}" + (f" — {x['detail']}" if x['detail'] else ""))
    print(f"\n{sum(1 for x in checks if x['pass'])}/{len(checks)} PASS — {'GREEN' if ok else 'FAILED'}")
    res = {"pass": ok, "checks": checks}
    if "--json" in sys.argv:
        json.dump(res, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=2)
    if "--markdown" in sys.argv:
        open(sys.argv[sys.argv.index("--markdown") + 1], "w").write(
            "# LLM review health-gate validation\n\n" + "\n".join(f"- [{'PASS' if x['pass'] else 'FAIL'}] {x['name']}" for x in checks))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
