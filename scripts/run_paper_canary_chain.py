#!/usr/bin/env python3
"""run_paper_canary_chain.py — ONE-SHOT first-genuine-Alpaca-paper-option canary.

Operator authorization: John, 2026-07-19 session — "flip alpaca_paper_enabled
and run the paper canary" → "yes do it". The registry gate (deep_itm_call
alpaca_paper_enabled: true) was ALREADY set; this script executes the rest of
the authorized chain at a moment when option chains are live (weekend chains
zero OI/volume, so every liquidity gate fails-closed on Sundays — the 2026-07-06
attempt also proved a stale scan-time premium expires unfilled; therefore scan
and submit must share one fresh session).

Chain (all fail-closed, each step logged to the evidence file):
  1. paper_canary_preflight.py must be 18/18 PASS (read-only).
  2. Idempotency guard: refuse if any Alpaca-lane order was already submitted
     today or any alpaca_paper strategy position is open.
  3. Fresh scan: options_strategy_scanner --run --strategy deep_itm_call.
  4. Pick the highest-edge pending deep_itm_call proposal from THIS scan only
     (created/updated within the freshness window — never a stale row).
  5. mark_ready (operator actor string records the standing authorization).
  6. submit_ready_proposal(confirm=True) — paper-api only, 1 contract, BTO,
     LIMIT at the scan-fresh premium, DAY.
  7. Telegram the outcome either way; write evidence JSON (no secrets).

Zero silent failures: any refused step telegrams the reason and exits nonzero.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Self-load .env so the chain is cron-line-agnostic (absolute paths everywhere;
# no reliance on the caller's cwd or environment).
_env_file = ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

EVIDENCE_DIR = ROOT / "data" / "options_lifecycle"
EVIDENCE_FILE = EVIDENCE_DIR / "paper_canary_evidence.json"
OPERATOR_ACTOR = ("operator:john — standing authorization 2026-07-19 session "
                  "('run the paper canary' / 'yes do it'); executed by canary chain")
FRESHNESS_MINUTES = 30
ET = ZoneInfo("America/New_York")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _telegram(msg: str) -> None:
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
    except Exception as e:  # never let notification failure mask the real result
        print(f"[canary] telegram skipped: {e}")


def _record(evidence: dict) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    existing = []
    if EVIDENCE_FILE.exists():
        try:
            existing = json.loads(EVIDENCE_FILE.read_text())
        except Exception:
            existing = [{"note": "prior evidence file unreadable — preserved as string",
                         "raw": EVIDENCE_FILE.read_text()[:2000]}]
    if not isinstance(existing, list):
        existing = [existing]
    existing.append(evidence)
    EVIDENCE_FILE.write_text(json.dumps(existing, indent=2, default=str))


def _fail(evidence: dict, step: str, why: str) -> int:
    evidence["result"] = {"ok": False, "failed_step": step, "reason": why,
                          "at": _now_iso()}
    _record(evidence)
    _telegram(f"🐤 PAPER CANARY refused at {step}: {why[:300]}")
    print(f"REFUSED at {step}: {why}")
    return 1


def main() -> int:
    evidence = {"chain": "first_alpaca_paper_option_canary",
                "authorization": OPERATOR_ACTOR,
                "started_at": _now_iso(), "steps": []}
    step = evidence["steps"].append

    now_et = datetime.now(ET)
    if now_et.weekday() >= 5:
        return _fail(evidence, "session_window", "weekend — chains zero OI/volume, gates cannot pass")
    if not ((now_et.hour == 9 and now_et.minute >= 45) or 10 <= now_et.hour < 15
            or (now_et.hour == 15 and now_et.minute <= 30)):
        return _fail(evidence, "session_window",
                     f"outside 09:45–15:30 ET submit window (now {now_et:%H:%M} ET)")
    step({"step": "session_window", "ok": True, "at_et": f"{now_et:%Y-%m-%d %H:%M}"})

    # 1. preflight — read-only, must be fully green
    pf = subprocess.run([str(ROOT / ".venv" / "bin" / "python"),
                         str(ROOT / "scripts" / "paper_canary_preflight.py")],
                        cwd=ROOT, capture_output=True, text=True)
    step({"step": "preflight", "ok": pf.returncode == 0,
          "verdict_tail": pf.stdout[-400:]})
    if pf.returncode != 0:
        return _fail(evidence, "preflight", "preflight gates not all green — see evidence")

    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()

    # 2. idempotency — one canary, ever, until the first completes its lifecycle
    cur.execute("""SELECT count(*) FROM options_approval_queue
                   WHERE status IN ('READY_FOR_ALPACA_PAPER','ALPACA_PAPER_SUBMITTED',
                                    'ALPACA_PAPER_FILLED')""")
    inflight = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM options_strategy_positions
                   WHERE broker='tradeai_automated' AND status IN ('open','closing')""")
    open_pos = cur.fetchone()[0]
    step({"step": "idempotency", "inflight_rows": inflight, "open_positions": open_pos})
    if inflight or open_pos:
        return _fail(evidence, "idempotency",
                     f"{inflight} in-flight queue row(s) / {open_pos} open paper position(s) — one canary at a time")

    # 3. fresh scan (same session as submit — the 07-06 stale-premium lesson)
    scan = subprocess.run([str(ROOT / ".venv" / "bin" / "python"),
                           str(ROOT / "scripts" / "options_strategy_scanner.py"),
                           "--run", "--strategy", "deep_itm_call", "--json"],
                          cwd=ROOT, capture_output=True, text=True, timeout=900)
    winners = []
    try:
        out = scan.stdout
        parsed = json.loads(out[out.index("{"):])
        winners = parsed.get("winner_summary") or parsed.get("winners") or []
        step({"step": "scan", "ok": scan.returncode == 0,
              "candidates_passed_gates": parsed.get("candidates_passed_gates"),
              "winners": len(winners),
              "queue_result": parsed.get("queue_result")})
    except Exception as e:
        return _fail(evidence, "scan", f"scan output unparseable: {e}; tail={scan.stdout[-300:]}")
    if not winners:
        return _fail(evidence, "scan", "scan produced zero gate-passing winners this session")

    # 4. pick the freshest highest-edge pending deep_itm_call row from THIS scan
    cur.execute("""SELECT proposal_id, symbol, edge_score,
                          proposal_json->>'premium'      AS premium,
                          proposal_json->>'strike'       AS strike,
                          proposal_json->>'expiration'   AS expiration
                   FROM options_approval_queue
                   WHERE strategy='deep_itm_call' AND status='pending'
                     AND updated_at > now() - interval '%s minutes'
                   ORDER BY edge_score DESC NULLS LAST LIMIT 1""" % FRESHNESS_MINUTES)
    row = cur.fetchone()
    if not row:
        return _fail(evidence, "pick", "no fresh pending deep_itm_call proposal after scan "
                                       "(scan winners may have upserted under a non-pending status)")
    proposal_id, symbol, edge, premium, strike, expiration = row
    step({"step": "pick", "proposal_id": proposal_id, "symbol": symbol,
          "edge_score": float(edge or 0), "premium": premium,
          "strike": strike, "expiration": expiration})

    # 5+6. mark ready, then submit within the same fresh session
    from lib.options_pipeline import alpaca_paper as ap
    try:
        ready = ap.mark_ready(proposal_id, operator_actor=OPERATOR_ACTOR)
    except Exception as e:  # transition() raises on any illegal/failed move
        return _fail(evidence, "mark_ready", str(e)[:300])
    step({"step": "mark_ready", "from": ready.get("from"), "to": ready.get("to")})

    try:
        res = ap.submit_ready_proposal(proposal_id, confirm=True)
    except Exception as e:
        return _fail(evidence, "submit", str(e)[:300])
    step({"step": "submit", "ok": (res or {}).get("ok"),
          "order_id": (res or {}).get("order_id"),
          "order_status": ((res or {}).get("readback") or {}).get("status")})
    if not (res or {}).get("ok"):
        return _fail(evidence, "submit", str((res or {}).get("error"))[:300])

    evidence["result"] = {
        "ok": True, "at": _now_iso(), "proposal_id": proposal_id,
        "symbol": symbol, "order_id": res.get("order_id"),
        "order_status": (res.get("readback") or {}).get("status"),
        "note": "FIRST GENUINE PAPER OPTION ORDER SUBMITTED — paper-api, 1 contract, "
                "BTO LIMIT DAY at scan-fresh premium. Fill pending; reconcile cron "
                "and lifecycle intake own the next steps.",
    }
    _record(evidence)
    _telegram(f"🐤 PAPER CANARY SUBMITTED: {symbol} deep-ITM call, proposal {proposal_id}, "
              f"Alpaca paper order {res.get('order_id')} "
              f"(status {(res.get('readback') or {}).get('status')}). "
              f"Limit at scan-fresh premium {premium}; DAY order. "
              f"Reconcile + lifecycle intake will pick up the fill.")
    print(json.dumps(evidence["result"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
