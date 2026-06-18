#!/usr/bin/env python3
"""rerun_cio_dual_consensus.py — re-run the Grok+ChatGPT dual-consensus on the watchlist's CIO verdicts and
store per-model verdicts + agreement on watchlist_final_synthesis. Uses each name's EXISTING CIO analysis
(committee recommendation + synthesis_narrative) as context so the cross-check is grounded, not a thin prompt.

Scope: top-N active/researched real-ticker names by hermes_rank (the actionable watchlist). Free OAuth only
(Grok + ChatGPT proxies); no metered API. Advisory — never touches trading.

  CIO_DUAL_CHATGPT_CAP=250 python3 scripts/rerun_cio_dual_consensus.py [N]   # default N=200
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("CIO_DUAL_CHATGPT_CAP", "300")  # don't let the per-run ChatGPT cap throttle this job
import process_watchlist_agent_jobs as p
from db_adapter import _get_conn


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT s.symbol, s.recommendation, s.confidence,
                          COALESCE(s.synthesis_narrative,''), COALESCE(s.action,''), min(w.hermes_rank)
                   FROM watchlist_final_synthesis s
                   JOIN watchlist_items w ON upper(w.symbol)=upper(s.symbol)
                   WHERE w.status IN ('active','researched') AND s.symbol ~ '^[A-Z]{1,5}$'
                   GROUP BY s.symbol, s.recommendation, s.confidence, s.synthesis_narrative, s.action
                   ORDER BY min(w.hermes_rank) ASC NULLS LAST LIMIT %s""", (n,))
    rows = cur.fetchall()
    print(f"re-running dual-consensus on {len(rows)} names (top {n} by hermes_rank)…", flush=True)
    agree = disagree = onelane = 0
    t0 = time.time()
    for i, (sym, rec, conf, narr, action, hr) in enumerate(rows, 1):
        prompt = (f"You are the final CIO arbiter for {sym}. The committee (Maria/Steph/Risk + local CIO) "
                  f"concluded: recommendation={rec} (confidence {conf}). Rationale: {narr[:900]} "
                  f"Action: {action[:200]}\n\nIndependently confirm or revise the FINAL verdict given this "
                  "analysis. Reply ONLY JSON: {\"recommendation\":\"BUY|ADD|ADD_ON_PULLBACK|HOLD|RESEARCH_MORE"
                  "|AVOID|IGNORE|TRIM|SELL\",\"confidence\":0.0-1.0,\"synthesis_narrative\":\"one line\"}")
        try:
            _raw, meta = p._synthesis_dual(prompt)
        except Exception as e:
            print(f"  [{i}] {sym} ERR {str(e)[:60]}", flush=True)
            continue
        g = (meta.get("grok") or {}).get("recommendation")
        ch = (meta.get("chatgpt") or {}).get("recommendation")
        cur.execute("""UPDATE watchlist_final_synthesis SET grok_recommendation=%s, chatgpt_recommendation=%s,
                         models_agree=%s, dual_consensus_json=%s WHERE upper(symbol)=%s""",
                    (g, ch, meta.get("agree"), json.dumps(meta), sym.upper()))
        conn.commit()
        if meta.get("agree") is True:
            agree += 1
        elif meta.get("agree") is False:
            disagree += 1
        else:
            onelane += 1
        if i % 20 == 0:
            print(f"  …{i}/{len(rows)}  agree={agree} disagree={disagree} single-lane={onelane}  "
                  f"({(time.time()-t0)/60:.1f}m)", flush=True)
    summary = {"processed": len(rows), "agree": agree, "disagree": disagree, "single_lane": onelane,
               "minutes": round((time.time() - t0) / 60, 1)}
    print(json.dumps(summary), flush=True)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from telegram_alert import send_telegram
        send_telegram(f"✅ CIO dual-consensus re-run done: {len(rows)} names · {agree} agree · {disagree} "
                      f"disagree · {onelane} single-lane · {summary['minutes']}m")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
