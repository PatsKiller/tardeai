#!/usr/bin/env python3
"""finviz_filter_validator.py — prove that a Finviz filter token is actually applied.

Finviz SILENTLY IGNORES filter codes it does not recognize: it returns HTTP 200
with a well-formed CSV covering the entire universe rather than erroring. A
screen built on a bad code therefore looks healthy — correct schema, thousands
of rows, fresh timestamp — while selecting nothing at all.

Confirmed live 2026-07-20: `fa_dividendyield_o5` returns all 11,501 rows (the
full universe), so `high_yield_income` and `covered_call_etf` were applying no
yield filter whatsoever. The valid code is `fa_div_o5`, which returns 0 rows
when combined with cap_mega.

Method: request the token in isolation and compare the row count to an
unfiltered baseline captured in the same run.

  count == baseline  -> IGNORED   (the token does nothing)
  count == 0         -> ZERO      (valid but selects nothing right now)
  0 < count < base   -> APPLIED   (the token filters)

This is the FILTER_IGNORED detector the screen compiler gates on; a definition
containing an IGNORED token must never be promoted.

  finviz_filter_validator.py --tokens cap_mega,fa_div_o5
  finviz_filter_validator.py --from-db          # every token in production
  finviz_filter_validator.py --from-db --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

APPLIED, IGNORED, ZERO, ERROR = "APPLIED", "IGNORED", "ZERO", "ERROR"
_BASE_URL = "https://elite.finviz.com/export?v=152&c=0,1,65"


def _cookie() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("FINVIZ_COOKIE="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def _rows(url: str, cookie: str) -> int:
    """Row count for a screener export, or -1 on a non-CSV/auth failure."""
    import finviz_throttle
    import requests
    finviz_throttle.acquire()
    r = requests.get(url, timeout=45, headers={
        "User-Agent": "Mozilla/5.0", "Cookie": cookie,
        "Referer": "https://elite.finviz.com/screener.ashx"})
    if r.status_code == 429:
        finviz_throttle.cooldown(r.headers.get("Retry-After"))
        raise RuntimeError("HTTP 429 — rate limited")
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    body = r.text.strip()
    if not body.lower().startswith('"no."'):
        # A login page or HTML error masquerading as success.
        raise RuntimeError(f"non-CSV response: {body[:60]!r}")
    return len(body.split("\n")) - 1


def production_tokens() -> dict:
    """{token: [screener_id, ...]} across the executor's rows."""
    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    cur.execute("SELECT screener_id, finviz_url FROM finviz_screeners")
    out: dict[str, list] = {}
    for sid, url in cur.fetchall():
        for raw in parse_qs(urlparse(url or "").query).get("f", []):
            for t in (x.strip() for x in raw.split(",")):
                if t:
                    out.setdefault(t, []).append(sid)
    return out


def validate(tokens, cookie=None) -> dict:
    cookie = cookie or _cookie()
    if not cookie:
        return {"ok": False, "error": "FINVIZ_COOKIE absent — cannot validate"}
    try:
        baseline = _rows(_BASE_URL, cookie)
    except Exception as e:
        return {"ok": False, "error": f"baseline fetch failed: {e}"}
    if baseline <= 0:
        return {"ok": False, "error": f"implausible baseline {baseline}"}

    results = {}
    for t in tokens:
        try:
            n = _rows(f"https://elite.finviz.com/export?v=152&f={t}&c=0,1,65", cookie)
            state = IGNORED if n == baseline else (ZERO if n == 0 else APPLIED)
            results[t] = {"state": state, "rows": n,
                          "pct_of_universe": round(100 * n / baseline, 1)}
        except Exception as e:
            results[t] = {"state": ERROR, "rows": None, "error": str(e)[:100]}
    return {"ok": True, "baseline_universe": baseline, "results": results}


def main() -> int:
    ap = argparse.ArgumentParser(description="Prove Finviz filter tokens are actually applied")
    ap.add_argument("--tokens", default="", help="comma-separated tokens")
    ap.add_argument("--from-db", action="store_true", help="validate every production token")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    used = {}
    if args.from_db:
        used = production_tokens()
        toks = sorted(used)
    else:
        toks = [t.strip() for t in args.tokens.split(",") if t.strip()]
    if not toks:
        print("no tokens given (use --tokens or --from-db)")
        return 2

    rep = validate(toks)
    if not rep.get("ok"):
        print(f"REFUSED: {rep.get('error')}")
        return 1
    if used:
        for t, r in rep["results"].items():
            r["used_by"] = sorted(used.get(t, []))
    if args.json:
        print(json.dumps(rep, indent=1))
        return 0

    print(f"baseline (unfiltered universe): {rep['baseline_universe']} rows\n")
    bad = {t: r for t, r in rep["results"].items() if r["state"] in (IGNORED, ERROR)}
    for t, r in sorted(rep["results"].items(), key=lambda kv: (kv[1]["state"], kv[0])):
        mark = "!!" if r["state"] == IGNORED else ("??" if r["state"] == ERROR else "  ")
        print(f"{mark} {r['state']:<8}{t:<28}rows={str(r['rows']):>7}"
              f"  {r.get('pct_of_universe','')}%"
              f"{'  used_by=' + ','.join(r['used_by']) if r.get('used_by') else ''}")
    if bad:
        print(f"\n{len(bad)} token(s) NOT APPLIED — screens using them do not filter as named:")
        for t, r in sorted(bad.items()):
            print(f"  {t}: {r['state']} {r.get('error','')} "
                  f"-> {','.join(r.get('used_by', [])) or 'n/a'}")
    return 1 if bad else 0



# ── combination-level: a token can be valid alone yet absorbed in context ──

ABSORBED = "ABSORBED"


def validate_combination(tokens: list, cookie=None) -> dict:
    """Detect tokens that change nothing WITHIN a specific filter combination.

    Token-level validation is not sufficient. `ind_exchangetradedfund` and
    `sec_financial` are each APPLIED alone, but combined the sector term is
    absorbed — Finviz ETFs carry no sector — so `bond_etf_income` returned all
    5,557 ETFs rather than bond ETFs (confirmed 2026-07-20).

    Method: drop each token in turn and compare. Same count => that token
    contributes nothing to this combination.
    """
    cookie = cookie or _cookie()
    if not cookie or len(tokens) < 2:
        return {"ok": False, "error": "need a cookie and >=2 tokens"}
    base_f = ",".join(tokens)
    try:
        full = _rows(f"https://elite.finviz.com/export?v=152&f={base_f}&c=0,1,65", cookie)
    except Exception as e:
        return {"ok": False, "error": f"combined fetch failed: {e}"}

    absorbed = {}
    for t in tokens:
        rest = [x for x in tokens if x != t]
        try:
            n = _rows("https://elite.finviz.com/export?v=152&f="
                      f"{','.join(rest)}&c=0,1,65", cookie)
        except Exception as e:
            absorbed[t] = {"state": ERROR, "error": str(e)[:80]}
            continue
        if n == full:
            absorbed[t] = {"state": ABSORBED, "rows_without_it": n,
                           "combined_rows": full}
    return {"ok": True, "combined_rows": full, "absorbed": absorbed}


def check_production_screens(limit: int = 0) -> dict:
    """Run combination validation across every production screen."""
    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    cur.execute("SELECT screener_id, finviz_url FROM finviz_screeners "
                "WHERE active ORDER BY screener_id")
    rows = cur.fetchall()
    if limit:
        rows = rows[:limit]
    out = {}
    for sid, url in rows:
        toks = []
        for raw in parse_qs(urlparse(url or "").query).get("f", []):
            toks.extend(x.strip() for x in raw.split(",") if x.strip())
        if len(toks) < 2:
            continue
        r = validate_combination(toks)
        if r.get("ok") and r["absorbed"]:
            out[sid] = {"tokens": toks, "combined_rows": r["combined_rows"],
                        "absorbed": r["absorbed"]}
    return out


if __name__ == "__main__":
    sys.exit(main())
