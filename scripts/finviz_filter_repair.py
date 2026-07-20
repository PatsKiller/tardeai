#!/usr/bin/env python3
"""finviz_filter_repair.py — replace silently-ignored Finviz filter tokens.

Finviz answers an unrecognized filter code with HTTP 200 and the FULL universe
instead of an error, so a screen built on a bad code looks healthy while
selecting nothing. On 2026-07-20, 16 of 54 production tokens (30%) were in that
state across 14 screens: high_yield_income applied no yield filter at all,
ira_income_friendly neither yield nor payout, quality_compounders no EPS growth.

Every replacement below was proven APPLIED by finviz_filter_validator.py
against an 11,501-row unfiltered baseline. Three have no exact equivalent —
Finviz offers only discrete steps — and are recorded as DEVIATIONS rather than
silently rounded.

  finviz_filter_repair.py             # report the planned rewrite (default)
  finviz_filter_repair.py --apply     # rewrite finviz_screeners URLs
  finviz_filter_repair.py --verify    # re-validate every token after repair
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# broken token -> (validated replacement, selectivity %, note)
# "" as replacement means DROP the token (no equivalent exists).
REPAIRS = {
    # ── fa_dividendyield_* is not a real family; the real one is fa_div_* ──
    "fa_dividendyield_o1": ("fa_div_o1", 42.8, "exact equivalent"),
    "fa_dividendyield_o2": ("fa_div_o2", 32.5, "exact equivalent"),
    "fa_dividendyield_o3": ("fa_div_o3", 30.0, "exact equivalent"),
    "fa_dividendyield_o4": ("fa_div_o4", 18.5, "exact equivalent"),
    "fa_dividendyield_o5": ("fa_div_o5", 14.0, "exact equivalent"),
    "fa_dividendyield_o6": ("fa_div_o6", 11.0, "exact equivalent"),
    # ── decimals are unsupported in this family ──
    "fa_div_o1.5": ("fa_div_o1", 42.8,
                    "DEVIATION: no 1.5% step exists. Chose the LOOSER 1% floor so "
                    "legitimate members are not excluded; downstream gates filter."),
    # ── wrong EPS-growth family name ──
    "fa_epsyoy5_o5": ("fa_eps5years_o5", 18.0, "exact equivalent (EPS growth past 5y)"),
    "fa_epsyoy5_o10": ("fa_eps5years_o10", 15.2, "exact equivalent"),
    # ── stray 'p' suffix ──
    "fa_payoutratio_u60p": ("fa_payoutratio_u60", 20.7, "exact equivalent"),
    "fa_payoutratio_u80p": ("fa_payoutratio_u80", 22.4, "exact equivalent"),
    # ── float/price: requested thresholds have no Finviz step ──
    # Finviz offers no 500M float step or 150 price step. The nearest supported
    # steps (100M / 50) are so much tighter that, combined with this screen's
    # other conditions, they emptied it to ZERO rows — verified. Shipping a
    # screen that selects nothing is worse than the broken token it replaced, so
    # these are DROPPED and the intent is recorded for the operator instead.
    "sh_float_u500": ("", 0.0,
                      "DROPPED: no 500M float step exists; sh_float_u100 over-tightens "
                      "this screen to 0 rows. Float cap now UNENFORCED — operator must "
                      "decide between no cap and a 100M cap."),
    "sh_price_u150": ("", 0.0,
                      "DROPPED: no 150 price step exists; sh_price_u50 over-tightens "
                      "this screen to 0 rows. Upper price cap now UNENFORCED "
                      "(sh_price_o5 floor is retained and working)."),
    # ── period naming: Finviz uses weeks, not months ──
    "ta_perf_1mup": ("ta_perf_4wup", 44.8, "exact equivalent (4 weeks = 1 month)"),
    # ── RSI band codes ──
    "ta_rsi_nos60": ("ta_rsi_ob60", 15.1,
                     "intent preserved: 'not oversold at 60' == RSI above 60 == ob60"),
    "ta_rsi_ob30": ("ta_rsi_os30", 2.5,
                    "the screen is oversold_reversion — it wants RSI BELOW 30; "
                    "'ob30' was a transposition of 'os30'"),
}

DEVIATIONS = {t for t, (_, _, n) in REPAIRS.items() if n.startswith("DEVIATION")}


def rewrite_url(url: str) -> tuple[str, list]:
    """Return (new_url, [(old, new), ...]). Order of surviving tokens preserved."""
    parts = urlparse(url)
    q = parse_qs(parts.query, keep_blank_values=True)
    changed = []
    for key in ("f",):
        if key not in q:
            continue
        new_terms = []
        for raw in q[key]:
            for t in raw.split(","):
                t = t.strip()
                if not t:
                    continue
                if t in REPAIRS:
                    rep = REPAIRS[t][0]
                    changed.append((t, rep or "<dropped>"))
                    if rep:
                        new_terms.append(rep)
                else:
                    new_terms.append(t)
        q[key] = [",".join(dict.fromkeys(new_terms))]   # de-dup, keep order
    if not changed:
        return url, []
    new_q = urlencode({k: v[0] for k, v in q.items()}, safe=",")
    return urlunparse(parts._replace(query=new_q)), changed


def plan() -> list:
    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    cur.execute("SELECT screener_id, finviz_url FROM finviz_screeners ORDER BY screener_id")
    out = []
    for sid, url in cur.fetchall():
        new_url, changed = rewrite_url(url or "")
        if changed:
            out.append({"screener_id": sid, "old_url": url, "new_url": new_url,
                        "changes": changed,
                        "has_deviation": any(o in DEVIATIONS for o, _ in changed)})
    return out


def apply(rows) -> int:
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    n = 0
    for r in rows:
        cur.execute("""UPDATE finviz_screeners
                       SET finviz_url=%s, updated_at=NOW()
                       WHERE screener_id=%s AND finviz_url=%s""",
                    (r["new_url"], r["screener_id"], r["old_url"]))
        n += cur.rowcount
    conn.commit()
    return n


def verify() -> dict:
    """Re-validate every token now present in production."""
    from finviz_filter_validator import validate, production_tokens, IGNORED, ERROR
    toks = production_tokens()
    rep = validate(sorted(toks))
    if not rep.get("ok"):
        return rep
    bad = {t: r for t, r in rep["results"].items() if r["state"] in (IGNORED, ERROR)}
    for t in bad:
        bad[t]["used_by"] = sorted(toks.get(t, []))
    return {"ok": True, "baseline": rep["baseline_universe"],
            "total_tokens": len(toks), "still_bad": bad}


def main() -> int:
    ap = argparse.ArgumentParser(description="Repair silently-ignored Finviz filter tokens")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.verify and not args.apply:
        rep = verify()
        if not rep.get("ok"):
            print(f"REFUSED: {rep.get('error')}")
            return 1
        if rep["still_bad"]:
            print(f"{len(rep['still_bad'])} token(s) STILL not applied "
                  f"of {rep['total_tokens']}:")
            for t, r in sorted(rep["still_bad"].items()):
                print(f"  {t}: {r['state']} -> {','.join(r.get('used_by', []))}")
            return 1
        print(f"VERIFIED — all {rep['total_tokens']} production tokens are applied "
              f"(baseline {rep['baseline']} rows)")
        return 0

    rows = plan()
    if args.json:
        print(json.dumps({"screens": rows, "applied": False}, indent=1))
        return 0

    if not rows:
        print("no broken tokens found in production")
        return 0

    print(f"{len(rows)} screen(s) to repair"
          f"{' — APPLYING' if args.apply else ' (dry run; use --apply)'}\n")
    for r in rows:
        flag = "  [DEVIATION]" if r["has_deviation"] else ""
        print(f"  {r['screener_id']}{flag}")
        for old, new in r["changes"]:
            note = REPAIRS.get(old, ("", 0, ""))[2]
            print(f"      {old:24s} -> {new:22s} {note}")

    if args.apply:
        n = apply(rows)
        print(f"\nupdated {n} row(s)")
        rep = verify()
        if rep.get("ok") and not rep["still_bad"]:
            print(f"VERIFIED — all {rep['total_tokens']} production tokens now applied")
        elif rep.get("ok"):
            print(f"WARNING — {len(rep['still_bad'])} token(s) still not applied: "
                  f"{sorted(rep['still_bad'])}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
