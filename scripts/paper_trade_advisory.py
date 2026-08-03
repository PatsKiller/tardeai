#!/usr/bin/env python3
"""paper_trade_advisory.py — automated external (Grok + ChatGPT) post-mortem advisory on CLOSED paper
trades, via the FREE OAuth lanes (Grok xAI proxy :8645, ChatGPT codex proxy :8646) through
hermes_external_researcher. Feeds the closed-loop learning engine with an external second opinion + a
one-line lesson per trade. Advisory only — never executes anything. Uses a CURATED post-mortem prompt.

Reuses hermes_external_researcher for OAuth, redaction, capability-cache, and storage — the advisory
lands in table hermes_external_research with trigger_reason='paper_postmortem:<trade_id>', so it's
deduped per (trade, lane) and queryable for the journal/learning loop.

Cron (a few times/day):
    .venv/bin/python scripts/paper_trade_advisory.py --apply --limit 5
    .venv/bin/python scripts/paper_trade_advisory.py            # dry-run (prints the curated prompt)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

DEFAULT_LANES = ["deepseek-flash", "grok", "chatgpt"]

# ── Curated post-mortem prompt ────────────────────────────────────────────────────────────────────
# Specific, no-boilerplate critique that extracts ONE actionable lesson + a trade grade. The
# researcher wraps this in its advisory-only framing and returns structured JSON (incl learning_candidate).
CURATED = """Post-mortem this CLOSED paper trade from a systematic, advisory-only trading system as an elite trading coach. Be specific and concise — NO boilerplate.

TRADE: {symbol} | strategy: {strategy} | {result} {pnl_pct}% ({r:.2f}R) | exited via {exit_reason}
Entry ${entry} (entry score {score}, RVOL {rvol}, catalyst: {catalyst}, regime {regime}, VIX {vix})
Stop ${stop} | Target ${target} | Exit ${exit} after {hold} min hold

Assess each in one line:
1) Entry quality — a good entry, or chasing?
2) Stop placement — too tight / too wide for {strategy}?
3) Strategy fit — was {strategy} the right strategy for this setup?
4) Exit — was '{exit_reason}' the right exit (left money on the table / cut too early)?
5) The single highest-value lesson the system should apply to future {strategy} trades.
End with exactly: LESSON: <one actionable line> | TRADE GRADE: <A-F>"""


def _db(sql, params=None, fetch="all"):
    from db_adapter import _execute
    return _execute(sql, params, fetch=fetch)


def _r_multiple(t) -> float:
    try:
        pnl = float(t.get("pnl") or 0)
        risk = float(t.get("dollar_risk") or 0)
        return round(pnl / risk, 2) if risk else 0.0
    except Exception:
        return 0.0


def build_question(t: dict) -> str:
    pnl = float(t.get("pnl") or 0)
    return CURATED.format(
        symbol=t["symbol"], strategy=t.get("strategy_id") or "unknown",
        result=("WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT"),
        pnl_pct=round(float(t.get("pnl_pct") or 0), 1), r=_r_multiple(t),
        exit_reason=t.get("exit_reason") or "unknown",
        entry=t.get("entry_price"), score=t.get("score_at_entry"), rvol=t.get("rvol_at_entry"),
        catalyst=(str(t.get("catalyst_at_entry") or "none")[:90]),
        regime=t.get("market_regime") or "?", vix=t.get("vix_at_entry"),
        stop=t.get("stop_loss"), target=t.get("target_1"),
        exit=t.get("exit_price"), hold=t.get("hold_time_min"))


def already_advised(trade_id, lane) -> bool:
    r = _db("SELECT 1 FROM hermes_external_research WHERE lane=%s AND trigger_reason=%s LIMIT 1",
            (lane, f"paper_postmortem:{trade_id}"), fetch="one")
    return bool(r)


def main():
    ap = argparse.ArgumentParser(description="External Grok+ChatGPT post-mortem advisory on closed paper trades")
    ap.add_argument("--limit", type=int, default=5, help="max trades to advise this run")
    ap.add_argument("--lanes", default="grok,chatgpt")
    ap.add_argument("--days", type=int, default=10, help="look back this many days for closed trades")
    ap.add_argument("--apply", action="store_true", help="actually call the external lanes (default dry-run)")
    args = ap.parse_args()

    lanes = [l.strip() for l in args.lanes.split(",") if l.strip()]
    trades = _db(
        f"""SELECT id, symbol, strategy_id, entry_price, exit_price, stop_loss, target_1,
                   pnl, pnl_pct, dollar_risk, exit_reason, hold_time_min, score_at_entry,
                   rvol_at_entry, catalyst_at_entry, market_regime, vix_at_entry
            FROM paper_trades
            WHERE status='closed' AND exit_time > now() - interval '{int(args.days)} days'
            ORDER BY exit_time DESC LIMIT %s""",
        (args.limit * 4,), fetch="all") or []

    done = 0
    for t in trades:
        if done >= args.limit:
            break
        pending = [ln for ln in lanes if not already_advised(t["id"], ln)]
        if not pending:
            continue
        q = build_question(t)
        if not args.apply:
            print(f"\n=== DRY RUN · trade #{t['id']} {t['symbol']} ({t.get('strategy_id')}) · lanes {pending} ===")
            print(q)
            done += 1
            continue
        for lane in pending:
            cmd = [sys.executable, str(ROOT / "scripts" / "hermes_external_researcher.py"),
                   "--lane", lane, "--question", q, "--symbol", t["symbol"],
                   "--trigger", f"paper_postmortem:{t['id']}", "--priority", "P2", "--apply"]
            try:
                r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=240)
                ok = r.returncode == 0
                print(f"  [{lane}] {t['symbol']} #{t['id']}: {'ok' if ok else 'rc=' + str(r.returncode)} "
                      f"{(r.stdout or '')[-120:].strip()}")
            except Exception as e:
                print(f"  [{lane}] {t['symbol']} #{t['id']}: error {str(e)[:100]}")
        done += 1

    print(f"\n[paper_advisory] processed {done} trade(s) · lanes={lanes} · apply={args.apply}")


if __name__ == "__main__":
    main()
