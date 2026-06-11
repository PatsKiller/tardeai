#!/usr/bin/env python3
"""build_daily_execution_coaching.py — read-only daily execution coaching queue.

Turns trade_execution_quality + Grok reviews + hypothesis aggregates into a RANKED coaching/learning queue:
"what should John study, fix, or test next?". Advisory only — NO live-strategy/GO-WAIT/screener/ATM/broker
changes, NO automatic promotion. Hypotheses surface as shadow-research candidates only.

  python3 scripts/build_daily_execution_coaching.py --days 5
  python3 scripts/build_daily_execution_coaching.py --days 30 --source all
  python3 scripts/build_daily_execution_coaching.py --apply        # dry-run by default
"""
import argparse, json, sys, collections, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _f(x):
    try:
        return float(x)
    except Exception:
        return None


def run(days=30, source="all", apply=False):
    import psycopg2.extras
    conn = _conn(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    src_clause = "" if source == "all" else " AND q.source=%(src)s"
    cur.execute(f"""SELECT q.*, r.grok_execution_label, r.grok_mistakes, r.grok_what_to_do_next_time
                    FROM trade_execution_quality q
                    LEFT JOIN trade_execution_grok_reviews r ON r.trade_key=q.trade_key AND r.source=q.source
                    WHERE q.path_status='OK' AND q.exit_time >= NOW() - (%(d)s || ' days')::interval {src_clause}""",
                {"d": days, "src": ("schwab_round_trip" if source == "schwab" else "paper_trade")})
    rows = cur.fetchall()
    if not rows:
        print(json.dumps({"status": "NO_TRADES_IN_WINDOW", "days": days, "source": source}))
        return {"status": "NO_TRADES_IN_WINDOW"}

    poor = [r for r in rows if r["execution_grade"] == "poor"]
    weak = [r for r in rows if r["execution_grade"] == "weak"]
    good = [r for r in rows if r["execution_grade"] in ("good", "ok")]

    def avg(rs, k):
        vals = [_f(r[k]) for r in rows if r in rs and _f(r[k]) is not None] if False else [_f(r.get(k)) for r in rs if _f(r.get(k)) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    items = []

    # 1) REPEATED MISTAKE — group by Grok primary mistake (normalize the RVOL suffix)
    def _norm(m):
        m = (m or "").split(" (")[0].strip()
        return m or None
    by_mistake = collections.defaultdict(list)
    for r in rows:
        m = _norm((r.get("grok_mistakes") or [None])[0])
        if m and m != "none":
            by_mistake[m].append(r)
    for m, rs in sorted(by_mistake.items(), key=lambda kv: -len(kv[1])):
        if len(rs) < 2:
            continue
        items.append({"item_type": "repeated_mistake", "symbol": None, "strategy_family": None,
                      "source": "all", "trade_keys": [r["trade_key"] for r in rs[:25]], "sample_size": len(rs),
                      "avg_capture_ratio": avg(rs, "capture_ratio"), "avg_missed_pct": avg(rs, "mfe_after_exit_pct"),
                      "severity": "critical" if len(rs) >= 20 else "high" if len(rs) >= 8 else "medium",
                      "lesson": f"Repeated {len(rs)}x: {m.replace('_', ' ')}. " + (
                          "Entries before volume confirms — wait for RVOL >= threshold and a confirming bar." if "volume" in m
                          else "Exits before the move completes — let winners run to a defined signal (VWAP loss / MACD rollover / trailing stop)." if "premature" in m
                          else "Entering below session VWAP — require price above VWAP for momentum entries." if "vwap" in m
                          else "Recurring execution pattern — review the replays."),
                      "operator_action": "Replay 3-5 of these, compare entry to the first volume-confirmed expansion and exit to VWAP/MACD/trailing. Do NOT change live rules from this — it is evidence, not a directive."})

    # 2) GREEN BUT POORLY EXECUTED — profitable + poor/weak (your edge leak)
    green_bad = [r for r in rows if (_f(r.get("realized_pnl")) or 0) > 0 and r["execution_grade"] in ("poor", "weak")]
    if green_bad:
        items.append({"item_type": "premature_exit", "symbol": None, "strategy_family": None, "source": "all",
                      "trade_keys": [r["trade_key"] for r in green_bad[:25]], "sample_size": len(green_bad),
                      "avg_capture_ratio": avg(green_bad, "capture_ratio"), "avg_missed_pct": avg(green_bad, "mfe_after_exit_pct"),
                      "severity": "high",
                      "lesson": f"{len(green_bad)} WINNING trades graded poor/weak execution — profitable but you left money on the table (avg capture {int((avg(green_bad,'capture_ratio') or 0)*100)}% of the in-hold move).",
                      "operator_action": "These won despite execution — the leak is captureable upside, not direction. Replay the highest-P&L ones and study where you exited vs the in-hold high."})

    # 3) SEVERE MISSED RUNNERS — filter implausible % (microcap split/data artifacts, e.g. 900%+ are not real)
    sev = [r for r in rows if r.get("missed_opportunity_grade") == "severe"
           and 25 <= (_f(r.get("mfe_after_exit_pct")) or 0) <= 150]
    for r in sorted(sev, key=lambda r: -(_f(r.get("mfe_after_exit_pct")) or 0))[:5]:
        items.append({"item_type": "missed_runner", "symbol": r["symbol"], "strategy_family": None, "source": r["source"],
                      "trade_keys": [r["trade_key"]], "sample_size": 1, "avg_capture_ratio": _f(r.get("capture_ratio")),
                      "avg_missed_pct": _f(r.get("mfe_after_exit_pct")), "severity": "high",
                      "lesson": f"{r['symbol']}: severe missed runner — price moved another {r.get('mfe_after_exit_pct')}% after you exited.",
                      "operator_action": "Replay: was there a hold signal (above VWAP / MACD still rising) you ignored at exit?"})

    # 4) SYMBOL REVIEW — symbols traded >=2x with majority poor
    by_sym = collections.defaultdict(list)
    for r in rows:
        by_sym[r["symbol"]].append(r)
    for s, rs in sorted(by_sym.items(), key=lambda kv: -len(kv[1])):
        bad = [r for r in rs if r["execution_grade"] in ("poor", "weak")]
        if len(rs) >= 2 and len(bad) >= len(rs) * 0.7:
            items.append({"item_type": "symbol_review", "symbol": s, "strategy_family": None, "source": "all",
                          "trade_keys": [r["trade_key"] for r in rs[:25]], "sample_size": len(rs),
                          "avg_capture_ratio": avg(rs, "capture_ratio"), "avg_missed_pct": avg(rs, "mfe_after_exit_pct"),
                          "severity": "medium",
                          "lesson": f"{s}: {len(bad)}/{len(rs)} trades poorly executed — a recurring per-symbol pattern, not a one-off.",
                          "operator_action": f"Pull all {s} replays side-by-side; the issue repeats so it is behavioral, not random."})

    # 5) STRATEGY-FAMILY REVIEW
    by_fam = collections.defaultdict(list)
    for r in rows:
        by_fam[r.get("bar_interval") or "?"].append(r)
    for fam, rs in by_fam.items():
        bad = [r for r in rs if r["execution_grade"] in ("poor", "weak")]
        if len(rs) >= 5:
            kind = "scalp/day-trade" if fam == "1Min" else "swing"
            items.append({"item_type": "strategy_family_review", "symbol": None, "strategy_family": kind, "source": "all",
                          "trade_keys": [r["trade_key"] for r in rs[:25]], "sample_size": len(rs),
                          "avg_capture_ratio": avg(rs, "capture_ratio"), "avg_missed_pct": avg(rs, "mfe_after_exit_pct"),
                          "severity": "medium",
                          "lesson": f"{kind}: {len(bad)}/{len(rs)} poor/weak — the family's execution issue repeats across names.",
                          "operator_action": f"Review the {kind} playbook for entry-volume + exit-discipline; treat as a pattern to study, not a config change."})

    # 6) HYPOTHESIS CANDIDATES (shadow-research only — never auto-applied)
    cur.execute("""SELECT hypothesis, count(*) n, round(100.0*count(*) FILTER(WHERE improved)/count(*)) imp,
                          round(avg(delta_ps),4) avg_delta FROM trade_execution_hypothesis_results
                   WHERE applicable GROUP BY hypothesis""")
    for h in cur.fetchall():
        items.append({"item_type": "hypothesis_candidate", "symbol": None, "strategy_family": None, "source": "all",
                      "trade_keys": [], "sample_size": h["n"], "avg_capture_ratio": None, "avg_missed_pct": None,
                      "avg_delta_ps": _f(h["avg_delta"]),
                      "severity": "low" if (_f(h["avg_delta"]) or 0) <= 0 else "medium",
                      "lesson": f"Hypothesis '{h['hypothesis']}': improved {h['imp']}% of {h['n']} trades, avg {h['avg_delta']}/sh — "
                                + ("evidence does NOT support it (would have hurt on average)." if (_f(h['avg_delta']) or 0) <= 0 else "promising; SHADOW-TEST ONLY."),
                      "operator_action": "Shadow-research candidate ONLY: minimum-sample gate -> shadow test -> operator review -> A1A -> rollback plan. Never auto-applied to live configs."})

    # severity rank
    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    items.sort(key=lambda it: (sev_rank.get(it["severity"], 9), -it["sample_size"]))
    for i, it in enumerate(items):
        it["rank"] = i + 1

    top_mistakes = [{"mistake": m, "count": len(rs)} for m, rs in sorted(by_mistake.items(), key=lambda kv: -len(kv[1]))[:10] if len(rs) >= 2]
    top_symbols = [{"symbol": s, "trades": len(rs)} for s, rs in sorted(by_sym.items(), key=lambda kv: -len(kv[1]))[:10]]
    summary = (f"{len(rows)} trades graded ({len(poor)} poor / {len(weak)} weak / {len(good)} ok+good). "
               f"Top repeated behavior: {top_mistakes[0]['mistake'].replace('_',' ')} x{top_mistakes[0]['count']}. "
               f"{len(green_bad)} winners poorly executed; {len(sev)} severe missed runners. Advisory only.")

    report = {"mode": "APPLIED" if apply else "DRY-RUN", "days": days, "source": source,
              "trade_count": len(rows), "poor": len(poor), "weak": len(weak), "good": len(good),
              "summary": summary, "items": len(items), "top_mistakes": top_mistakes[:5],
              "top_items": [{"rank": it["rank"], "severity": it["severity"], "type": it["item_type"],
                             "n": it["sample_size"], "lesson": it["lesson"][:90]} for it in items[:10]]}

    if apply:
        wcur = conn.cursor()
        wcur.execute("""INSERT INTO daily_execution_coaching_runs
            (run_date, window_start, window_end, source_filter, trade_count, poor_count, weak_count, good_count,
             top_mistakes_json, top_symbols_json, top_strategy_families_json, summary)
            VALUES (CURRENT_DATE, CURRENT_DATE - %s, CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (days, source, len(rows), len(poor), len(weak), len(good), json.dumps(top_mistakes),
             json.dumps(top_symbols), json.dumps([]), summary))
        run_id = wcur.fetchone()[0]
        for it in items:
            wcur.execute("""INSERT INTO daily_execution_coaching_items
                (run_id, rank, severity, item_type, symbol, strategy_family, source, trade_keys_json, sample_size,
                 avg_capture_ratio, avg_missed_pct, avg_delta_ps, lesson, operator_action, evidence_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (run_id, it["rank"], it["severity"], it["item_type"], it.get("symbol"), it.get("strategy_family"),
                 it["source"], json.dumps(it["trade_keys"]), it["sample_size"], it.get("avg_capture_ratio"),
                 it.get("avg_missed_pct"), it.get("avg_delta_ps"), it["lesson"], it["operator_action"],
                 json.dumps({k: it.get(k) for k in ("avg_capture_ratio", "avg_missed_pct", "avg_delta_ps")})))
        conn.commit()
        report["run_id"] = run_id
    print(json.dumps(report, indent=2, default=str))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--source", default="all")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--brief", action="store_true")
    a = ap.parse_args()
    rep = run(a.days, a.source, a.apply)
    if a.brief and isinstance(rep, dict) and rep.get("top_items"):
        print("\n── EXECUTION BRIEF (manual; advisory; no trade instructions) ──")
        print("Top behaviors to fix:")
        for it in [x for x in rep["top_items"] if x["type"] in ("repeated_mistake", "premature_exit")][:3]:
            print(f"  • {it['lesson']}")
        print("Hypotheses are shadow-research only — no live changes.")


if __name__ == "__main__":
    main()
