#!/usr/bin/env python3
"""hermes_score_alerts.py — H-5: flag meaningful changes in the Hermes watchlist scores.

Compares each symbol's two latest hermes_score_history snapshots and flags:
  - composite score spike / drop (>= SCORE_DELTA)
  - rank surge (moved up >= RANK_JUMP)
  - analyst divergence flip (aligned <-> divergent)
  - setup-quality / sector regime change (factor score moved >= FACTOR_DELTA)
Writes to alert_events (idempotent alert_uid — no re-spam) and, with --send, Telegram (both chat IDs).
Advisory only — never trades.

  python3 scripts/hermes_score_alerts.py [--send]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
from watchlist_priority import rank_alert_worthy, rank_in_scope

SCORE_DELTA = 8.0
RANK_JUMP = 20
FACTOR_DELTA = 20.0
from tg_chat_ids import chat_ids  # no hardcoded chat IDs


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _alert(cur, uid, atype, symbol, severity, text):
    cur.execute("""INSERT INTO alert_events (alert_uid, alert_type, symbol, severity, source_script, raw_text, created_at)
                   VALUES (%s, %s, %s, %s, 'hermes_score_alerts', %s, NOW())
                   ON CONFLICT (alert_uid) DO NOTHING""", (uid, atype, symbol, severity, text))
    return cur.rowcount > 0


def _telegram(msg):
    try:
        import os, requests
        tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not tok:
            for line in (PROJECT_ROOT / ".env").read_text().splitlines():
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    tok = line.split("=", 1)[1].strip()
        if not tok:
            return
        for cid in chat_ids():
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": cid, "text": msg}, timeout=8)
    except Exception:
        pass


def _div(components):
    a = (components or {}).get("analyst") or {}
    d = (a.get("detail") or "")
    return "divergent" if "divergent" in d else "aligned" if "aligned" in d else None


def run(send=False):
    conn = _conn(); cur = conn.cursor()
    cur.execute("""SELECT symbol, composite_score, rank, components, scored_at,
                     ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY scored_at DESC) rn
                   FROM hermes_score_history WHERE scored_at > now() - interval '3 days'""")
    cols = [d[0] for d in cur.description]
    by = {}
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        by.setdefault(d["symbol"], []).append(d)
    new_alerts = []
    for sym, snaps in by.items():
        snaps = [s for s in snaps if s["rn"] <= 2]
        if len(snaps) < 2:
            continue
        cur_s, prev_s = snaps[0], snaps[1]
        ts = cur_s["scored_at"].strftime("%Y%m%d%H%M")
        cur_rank = cur_s.get("rank")
        prev_rank = prev_s.get("rank")
        in_scope = rank_in_scope(cur_rank) or rank_alert_worthy(cur_rank, prev_rank)
        # composite spike/drop (top-N only — tail churn is not actionable)
        if in_scope and cur_s["composite_score"] is not None and prev_s["composite_score"] is not None:
            delta = float(cur_s["composite_score"]) - float(prev_s["composite_score"])
            if abs(delta) >= SCORE_DELTA:
                arrow = "📈" if delta > 0 else "📉"
                txt = f"{arrow} {sym} Hermes score {'spiked' if delta > 0 else 'dropped'} {delta:+.0f} → {float(cur_s['composite_score']):.0f}"
                if _alert(cur, f"hermes_score_{sym}_{ts}", "hermes_score_move", sym, "info" if delta > 0 else "warning", txt):
                    new_alerts.append(txt)
        # rank surge (suppress #2000+ tail noise)
        if rank_alert_worthy(cur_rank, prev_rank) and cur_rank and prev_rank and (prev_rank - cur_rank) >= RANK_JUMP:
            txt = f"⤴ {sym} jumped to Hermes rank #{cur_s['rank']} (from #{prev_s['rank']})"
            if _alert(cur, f"hermes_rank_{sym}_{ts}", "hermes_rank_surge", sym, "info", txt):
                new_alerts.append(txt)
        # analyst divergence flip (top-N only)
        dc, dp = _div(cur_s["components"]), _div(prev_s["components"])
        if in_scope and dc and dp and dc != dp:
            txt = f"⚠ {sym} analyst view flipped {dp} → {dc} vs Street"
            if _alert(cur, f"hermes_divflip_{sym}_{ts}", "hermes_divergence_flip", sym, "warning", txt):
                new_alerts.append(txt)
        # factor regime change (sector_strength / setup_quality)
        for f in ("sector_strength", "setup_quality"):
            cf = (cur_s["components"] or {}).get(f, {}).get("score")
            pf = (prev_s["components"] or {}).get(f, {}).get("score")
            if in_scope and cf is not None and pf is not None and abs(float(cf) - float(pf)) >= FACTOR_DELTA:
                txt = f"↻ {sym} {f.replace('_', ' ')} shifted {float(pf):.0f}→{float(cf):.0f}"
                if _alert(cur, f"hermes_{f}_{sym}_{ts}", "hermes_factor_shift", sym, "info", txt):
                    new_alerts.append(txt)
    conn.commit()
    if new_alerts and send:
        _telegram("🔭 Hermes watchlist alerts:\n" + "\n".join(new_alerts[:12]))
    print(json.dumps({"new_alerts": len(new_alerts), "detail": new_alerts[:15]}, indent=2))
    return {"new_alerts": len(new_alerts)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--send", action="store_true")
    run(send=ap.parse_args().send)


if __name__ == "__main__":
    main()
