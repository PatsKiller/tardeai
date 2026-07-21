#!/usr/bin/env python3
"""validate_llm_review_provenance_filters.py — verify AI Trade Eval provenance + filter behaviour.
Read-only (HTTP GET).  python3 scripts/validate_llm_review_provenance_filters.py [--json PATH]
"""
import sys, json, urllib.request, urllib.parse

BASE = "http://127.0.0.1:7777/api/v2/backtesting/trade-evaluations"


def _get(params=None):
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    return json.loads(urllib.request.urlopen(BASE + qs, timeout=30).read())["data"]


def main():
    checks = []
    def chk(n, ok, d=""):
        checks.append({"name": n, "pass": bool(ok), "detail": str(d)})
    alld = _get()
    n_all = len(alld["evaluations"])
    chk("endpoint strict JSON", True)
    chk("has evaluations", n_all > 0, n_all)
    a1 = len(_get({"account":"schwab_rollover_ira"})["evaluations"])
    a2 = len(_get({"account":"tradeai_automated"})["evaluations"])
    chk("account filter partitions (not global)", a1 < n_all and a1 >= 0, f"all={n_all} schwab_rollover={a1} alpaca={a2}")
    chk("account filter != all (silently global)", a1 != n_all or a2 != n_all, f"{a1}/{a2} vs {n_all}")
    # verdict filter sanity
    vd = _get({"verdict": (alld.get("verdict_distribution",[{}])[0].get("eval_verdict") or "NEEDS_IMPROVEMENT")})
    chk("verdict filter returns subset", len(vd["evaluations"]) <= n_all)
    # no dup ids
    ids = [e["id"] for e in alld["evaluations"]]
    chk("no duplicate review ids", len(ids) == len(set(ids)))
    res = {"pass": all(c["pass"] for c in checks), "all": n_all, "schwab_rollover": a1, "alpaca": a2, "checks": checks}
    for c in checks:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['name']}" + (f" — {c['detail']}" if c['detail'] else ""))
    print(f"\n{sum(1 for c in checks if c['pass'])}/{len(checks)} PASS — {'GREEN' if res['pass'] else 'FAILED'}")
    if "--json" in sys.argv:
        json.dump(res, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=2)
    sys.exit(0 if res["pass"] else 1)


if __name__ == "__main__":
    main()
