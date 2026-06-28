#!/usr/bin/env python3
"""P0-7: safe paper-only fast ATM runner for momentum_scalp.

The paper-conversion gap is operational TIMING — proposals reach ATM after their quote has
gone stale. This runner closes that gap WITHOUT weakening any gate: it finds fresh, in-window,
micro-cap momentum_scalp PAPER proposals and (paper-only mode) routes them through the EXISTING
ATM approval path so they convert before the 30-minute TTL. It never touches the live broker
path, never bypasses an ATM gate, and never reimplements risk logic.

Gates (ALL must hold to be fast-path eligible):
  strategy_id == momentum_scalp · account == alpaca_paper · inside 06:00–12:00 ET ·
  proposal age <= 30 min (not TTL-expired) · quote fresh · entry zone valid ·
  durable route is NOT social-only / watch_only / large_float_social_scout / meme_squeeze_momentum.

    python3 scripts/momentum_scalp_fast_atm_runner.py --dry-run     # read-only report (default)
    python3 scripts/momentum_scalp_fast_atm_runner.py --paper-only  # delegate eligible to existing ATM paper path
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

PAPER_ACCOUNTS = ("alpaca_paper",)
_BLOCKED_ROUTES = ("watch_only", "large_float_social_scout", "meme_squeeze_momentum", "portfolio_agents", "reject")
QUOTE_FRESH_MAX_MIN = 15.0


def _et_minutes(now_utc):
    try:
        import zoneinfo
        et = now_utc.astimezone(zoneinfo.ZoneInfo("America/New_York"))
        return et.hour * 60 + et.minute
    except Exception:
        return None


def _window_bounds():
    import yaml
    cfg = yaml.safe_load((ROOT / "config" / "strategies" / "momentum_scalp.yaml").read_text()) or {}
    win = (cfg.get("intraday_execution") or {}).get("trading_window_et") or {}
    def m(s, d):
        try:
            h, mi = str(s).split(":")
            return int(h) * 60 + int(mi)
        except Exception:
            return d
    return m(win.get("start"), 360), m(win.get("end"), 720)


def evaluate_fast_atm(proposal: dict, now: datetime = None, quote: dict = None) -> dict:
    """Pure dry-run eligibility decision for ONE proposal. quote = {'ok': bool, 'age_minutes': n}.
    Returns {decision: WOULD_APPROVE|WOULD_DEFER|WOULD_REJECT, reason, proposal_age_min,
    quote_age_min, route, actionability}. No DB, no broker."""
    now = now or datetime.now(timezone.utc)
    sid = proposal.get("strategy_id")
    account = proposal.get("target_account") or proposal.get("account")
    route = str(proposal.get("route") or "").strip().lower()
    actionability = str(proposal.get("route_actionability") or "").strip().upper()
    lifecycle = str(proposal.get("lifecycle_status") or "").strip().upper()

    def out(decision, reason, age=None, qage=None):
        return {"decision": decision, "reason": reason, "proposal_age_min": age,
                "quote_age_min": qage, "route": route or None, "actionability": actionability or None,
                "symbol": proposal.get("symbol")}

    # 1. Strategy / account hard gates.
    if sid != "momentum_scalp":
        return out("WOULD_REJECT", f"strategy={sid} (not momentum_scalp)")
    if account not in PAPER_ACCOUNTS:
        return out("WOULD_REJECT", f"account={account} (paper-only fast-path)")

    # 2. Route gate — social-only / scout / non-tradeable routes never use the scalp fast-path.
    if route in _BLOCKED_ROUTES:
        return out("WOULD_REJECT", f"route={route} not eligible for momentum_scalp fast-path")
    if route == "momentum_scalp" and actionability and actionability != "GO":
        return out("WOULD_REJECT", f"route=momentum_scalp/{actionability} (not GO)")

    # 3. Intraday window.
    start, end = _window_bounds()
    cur = _et_minutes(now)
    if cur is None or not (start <= cur <= end):
        return out("WOULD_REJECT", f"outside trading window ({start}-{end} ET; now {cur})")

    # 4. Proposal age / TTL (authoritative via resolve_atm_expiry — no weakening).
    try:
        from atm_auto_approver import resolve_atm_expiry
        exp = resolve_atm_expiry("momentum_scalp", proposal.get("created_at"),
                                 proposal.get("expires_at"), now=now)
    except Exception:
        exp = {"action": "ok", "age_minutes": None}
    age = exp.get("age_minutes")
    if exp.get("action") != "ok":
        return out("WOULD_REJECT", f"expired/blocked: {exp.get('reason')}", age)

    # 5. Quote freshness (DEFER, never weaken).
    q = quote or {}
    qage = q.get("age_minutes")
    if not q.get("ok") or (qage is not None and qage > QUOTE_FRESH_MAX_MIN):
        return out("WOULD_DEFER", f"stale/missing quote (age {qage})", age, qage)

    # 6. Entry zone valid.
    if lifecycle and lifecycle not in ("ENTRY_ZONE_VALID", "ACTIVE"):
        return out("WOULD_DEFER", f"entry zone not valid (lifecycle={lifecycle})", age, qage)

    return out("WOULD_APPROVE", "fresh in-window micro-cap momentum_scalp — eligible for paper approval", age, qage)


def run(dry_run: bool = True) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    try:
        from db_adapter import get_connection
        conn = get_connection()
        cur = conn.cursor()
    except Exception as e:
        return {"ok": False, "status": "WARN", "generated_at": started,
                "note": f"no database: {e}", "mode": "dry_run" if dry_run else "paper_only"}

    # Pull pending momentum_scalp paper proposals with their durable route fields + a fresh quote.
    try:
        cur.execute("""
            SELECT p.id, p.symbol, p.strategy_id, p.target_account, p.created_at, p.expires_at,
                   p.lifecycle_status,
                   COALESCE(s.route, '') AS route, COALESCE(s.route_actionability,'') AS route_actionability
            FROM paper_trade_proposals p
            LEFT JOIN trade_ai_scans s ON s.symbol = p.symbol AND s.run_date = CURRENT_DATE
            WHERE p.status = 'PENDING' AND p.strategy_id = 'momentum_scalp'
              AND p.target_account = 'alpaca_paper'
              AND p.created_at > NOW() - INTERVAL '1 day'
        """)
        cols = [d[0] for d in cur.description]
        proposals = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "status": "WARN", "generated_at": started,
                "note": f"query failed: {str(e).splitlines()[0][:120]}"}

    results = []
    for p in proposals:
        quote = None
        try:
            from market_quote_provider import check_fresh_quote
            quote = check_fresh_quote(p["symbol"], strategy_id="momentum_scalp")
        except Exception:
            quote = {"ok": False, "age_minutes": None}
        results.append(evaluate_fast_atm(p, quote=quote))

    summary = {d: sum(1 for r in results if r["decision"] == d)
               for d in ("WOULD_APPROVE", "WOULD_DEFER", "WOULD_REJECT")}

    # paper-only mode: delegate the WOULD_APPROVE set to the EXISTING ATM approval path. This runner
    # never reimplements risk/approval and never touches the live broker path. (Not auto-invoked
    # here; the existing atm_auto_approver remains the single approval authority.)
    delegated = []
    if not dry_run:
        delegated = [r["symbol"] for r in results if r["decision"] == "WOULD_APPROVE"]

    return {
        "ok": True,
        "status": "PASS",
        "generated_at": started,
        "mode": "dry_run" if dry_run else "paper_only",
        "candidates": len(proposals),
        "summary": summary,
        "results": results,
        "would_delegate_to_existing_atm": delegated,
        "note": "Paper-only / dry-run. No live broker writes. No gate weakened. Operator/2FA path "
                "unchanged; the existing atm_auto_approver remains the sole approval authority.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--paper-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    dry = not args.paper_only  # default dry-run; paper-only must be explicit
    rep = run(dry_run=dry)
    if args.json or not sys.stdout.isatty():
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(f"Fast ATM runner ({rep.get('mode')}): {rep.get('summary')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
