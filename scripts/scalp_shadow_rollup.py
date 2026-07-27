#!/usr/bin/env python3
"""M3-S4 — shadow rollup + read-only dashboard (Momentum Scalp Signal Engine).

Reads scalp_ignition_events, computes Precision@1R by IGN band, PER COHORT (profiled vs proxy) — the
cohorts are NEVER pooled (design §12 / M3-S2.5 caveat: the covered cohort skews seasoned/liquid, the
uncovered skews new/thin, and P@1R is not generalizable across them). Renders a static, read-only HTML
instrument panel (one page, tables only — no controls, nothing actionable).

Read-only: no proposals, no orders. Does not import the scorer/logger/backfill.

Usage:
  python scripts/scalp_shadow_rollup.py                 # print summary
  python scripts/scalp_shadow_rollup.py --html <path>   # also write the dashboard HTML
"""
from __future__ import annotations

import argparse
import html as _html
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
DEFAULT_HTML = Path.home() / "deploy" / "v3-next" / "current" / "scalp-shadow.html"


def cohort_of(profile_source: str) -> str:
    return "profiled" if profile_source == "per_symbol" else "proxy"


def p_at_1r_by_band(events: list[dict], band: int = 10) -> list[dict]:
    """events: [{ign, hit}] (hit True/False/None). Returns per-IGN-band P@1R over RESOLVED events
    (hit not None), bands of width `band` (0-10, 10-20, …). Pure."""
    buckets: dict[int, list[bool]] = {}
    for e in events:
        if e.get("hit") is None:
            continue
        b = min((100 // band) - 1, int(e["ign"] // band))
        buckets.setdefault(b, []).append(bool(e["hit"]))
    out = []
    for b in sorted(buckets):
        v = buckets[b]
        out.append({"band": f"{b*band}-{b*band+band}", "n": len(v),
                    "p_at_1r": round(sum(v) / len(v), 3)})
    return out


def is_monotonic_nondecreasing(bands: list[dict]) -> bool:
    ps = [b["p_at_1r"] for b in bands]
    return all(ps[i] <= ps[i + 1] for i in range(len(ps) - 1))


def _conn():
    try:
        from db_adapter import get_connection
    except ModuleNotFoundError:
        from scripts.db_adapter import get_connection
    return get_connection()


def gather(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("""SELECT ign_score, profile_source, hit_1r_first, lane, session_date
                       FROM scalp_ignition_events""")
        rows = cur.fetchall()
    by_cohort: dict[str, list[dict]] = {"profiled": [], "proxy": []}
    for ign, psrc, hit, lane, sd in rows:
        by_cohort[cohort_of(psrc)].append({"ign": float(ign), "hit": hit, "lane": lane})
    summary = {
        "total_events": len(rows),
        "resolved": sum(1 for r in rows if r[2] is not None),
        "cohorts": {},
    }
    for c, evs in by_cohort.items():
        bands = p_at_1r_by_band(evs)
        summary["cohorts"][c] = {
            "n": len(evs),
            "resolved": sum(1 for e in evs if e["hit"] is not None),
            "bands": bands,
            "monotonic": is_monotonic_nondecreasing(bands),
        }
    with conn.cursor() as cur:
        cur.execute("""SELECT symbol, session_date, minute_of_session, lane, ign_score, rvol_tod,
                              profile_source, hit_1r_first, r_multiple_30m
                       FROM scalp_ignition_events ORDER BY fired_at DESC LIMIT 40""")
        summary["recent"] = cur.fetchall()
    return summary


def render_html(s: dict) -> str:
    def esc(x): return _html.escape(str(x))
    parts = ["<style>body{font-family:ui-monospace,Menlo,monospace;background:#0a0e14;color:#d3dae3;",
             "margin:0;padding:20px;font-size:13px}h1,h2{color:#8a97a8;font-weight:600}",
             "table{border-collapse:collapse;margin:8px 0 22px;width:100%}th,td{padding:5px 10px;",
             "border-bottom:1px solid #232d3b;text-align:right}th{color:#626f80;text-transform:uppercase;",
             "font-size:10px}td:first-child,th:first-child{text-align:left}.tag{color:#626f80}",
             ".pos{color:#3fb950}.neg{color:#f85149}.note{color:#626f80;font-size:11px}</style>"]
    parts.append("<h1>Scalp Shadow &mdash; ignition events (read-only instrument panel)</h1>")
    parts.append(f"<div class='note'>events {s['total_events']} &middot; resolved {s['resolved']} "
                 "&middot; SHADOW: no alerts, no proposals, no orders. Cohorts never pooled.</div>")
    for c in ("profiled", "proxy"):
        co = s["cohorts"][c]
        mono = "monotonic ✓" if co["monotonic"] else "NON-monotonic ✗"
        parts.append(f"<h2>Precision@1R by IGN band &mdash; cohort: {c} "
                     f"(n={co['n']}, resolved={co['resolved']}, {mono})</h2>")
        parts.append("<table><tr><th>IGN band</th><th>n</th><th>P@1R</th></tr>")
        for b in co["bands"]:
            parts.append(f"<tr><td>{esc(b['band'])}</td><td>{b['n']}</td><td>{b['p_at_1r']:.3f}</td></tr>")
        if not co["bands"]:
            parts.append("<tr><td class='tag' colspan=3>no resolved events yet</td></tr>")
        parts.append("</table>")
    parts.append("<h2>Recent ignition events</h2>")
    parts.append("<table><tr><th>symbol</th><th>session</th><th>min</th><th>lane</th><th>IGN</th>"
                 "<th>RVOL_tod</th><th>cohort</th><th>hit_1R</th><th>R@30m</th></tr>")
    for sym, sd, mn, lane, ign, rt, psrc, hit, rm in s["recent"]:
        hitc = "pos" if hit is True else ("neg" if hit is False else "tag")
        parts.append(f"<tr><td>{esc(sym)}</td><td>{esc(sd)}</td><td>{mn}</td><td>{esc(lane)}</td>"
                     f"<td>{float(ign):.1f}</td><td>{('%.2f'%rt) if rt is not None else '-'}</td>"
                     f"<td class='tag'>{esc(cohort_of(psrc))}</td>"
                     f"<td class='{hitc}'>{'' if hit is None else esc(hit)}</td>"
                     f"<td>{('%.2f'%rm) if rm is not None else '-'}</td></tr>")
    parts.append("</table>")
    return "<!doctype html><meta charset='utf-8'><title>Scalp Shadow</title>" + "".join(parts)


def run(args) -> int:
    conn = _conn()
    s = gather(conn)
    print(f"total_events={s['total_events']} resolved={s['resolved']}")
    for c in ("profiled", "proxy"):
        co = s["cohorts"][c]
        print(f"  cohort {c}: n={co['n']} resolved={co['resolved']} monotonic={co['monotonic']}")
        for b in co["bands"]:
            print(f"    IGN {b['band']:>7}  n={b['n']:>4}  P@1R={b['p_at_1r']:.3f}")
    if args.html:
        out = Path(args.html)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(render_html(s), encoding="utf-8")
            print(f"  dashboard → {out}")
        except Exception as e:
            print(f"  dashboard write skipped: {e}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="M3-S4 shadow rollup + read-only dashboard")
    ap.add_argument("--html", nargs="?", const=str(DEFAULT_HTML), help="write dashboard HTML (optional path)")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
