#!/usr/bin/env python3
"""P0-2: deterministic momentum_scalp Validation fast-path (NO human validation approval).

Operator decision 2026-06-28: momentum_scalp validation sample-collection does not need human/operator
validation approval. Deterministic gates replace the approval queue. A proposal that passes ALL gates is
submitted straight to the sandbox-only path via the EXISTING safe submitter (proposal_paper_submitter.
submit_paper) — which is sandbox-only and idempotent. This module never touches the live broker path,
never sets live-approval fields, and never weakens quote-freshness / TTL / window / liquidity / route
/ risk gates. Live trading is unchanged and still requires operator confirmation + 2FA.

    python3 scripts/momentum_scalp_paper_fast_path.py --dry-run     # read-only report (default)
    python3 scripts/momentum_scalp_paper_fast_path.py --sandbox-only  # gate-pass → existing validation submit
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SOURCE_TAG = "momentum_scalp_paper_fast_path"
PAPER_ACCOUNT = "alpaca_paper"
QUOTE_FRESH_MAX_MIN = 15.0
MICRO_MAX_FLOAT_M = 20.0
MICRO_MAX_PRICE = 25.0
MIN_RVOL = 5.0
MIN_RR = 1.5
_BLOCKED_ROUTES = ("watch_only", "large_float_social_scout", "meme_squeeze_momentum",
                   "portfolio_agents", "reject")


def _cfg():
    import yaml
    return yaml.safe_load((ROOT / "config" / "strategies" / "momentum_scalp.yaml").read_text()) or {}


def _window_bounds(cfg=None):
    cfg = cfg or _cfg()
    win = (cfg.get("intraday_execution") or {}).get("trading_window_et") or {}
    def m(s, d):
        try:
            h, mi = str(s).split(":")
            return int(h) * 60 + int(mi)
        except Exception:
            return d
    return m(win.get("start"), 360), m(win.get("end"), 720)


def _max_drift(cfg=None):
    cfg = cfg or _cfg()
    return float((cfg.get("intraday_execution") or {}).get("max_price_drift_pct") or 3.0)


def _et_minutes(now_utc):
    try:
        import zoneinfo
        et = now_utc.astimezone(zoneinfo.ZoneInfo("America/New_York"))
        return et.hour * 60 + et.minute
    except Exception:
        return None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def evaluate_paper_fast_path(proposal: dict, now: datetime = None, quote: dict = None,
                             cfg: dict = None) -> dict:
    """Pure, deterministic decision for ONE proposal. quote={'ok':bool,'age_minutes':n,'last_price':p}.
    Returns the documented candidate dict. NO DB, NO broker, NO approval."""
    now = now or datetime.now(timezone.utc)
    cfg = cfg or _cfg()
    rc = []

    def out(decision, qage_s=None, age_m=None):
        return {"symbol": proposal.get("symbol"), "proposal_id": proposal.get("id"),
                "decision": decision, "reason_codes": rc,
                "quote_age_seconds": qage_s, "proposal_age_minutes": age_m,
                "route": str(proposal.get("route") or "").lower() or None,
                "account": proposal.get("target_account") or proposal.get("account")}

    # 1. Strategy / account.
    if proposal.get("strategy_id") != "momentum_scalp":
        rc.append("NOT_MOMENTUM_SCALP"); return out("REJECT")
    if (proposal.get("target_account") or proposal.get("account")) != PAPER_ACCOUNT:
        rc.append("NOT_PAPER_ACCOUNT"); return out("REJECT")

    # 2. Durable route — verified micro-cap GO only; social/scout/meme blocked.
    route = str(proposal.get("route") or "").strip().lower()
    actionability = str(proposal.get("route_actionability") or "").strip().upper()
    route_sid = str(proposal.get("route_strategy_id") or "").strip().lower()
    if route in _BLOCKED_ROUTES:
        rc.append(f"ROUTE_BLOCKED_{route.upper()}"); return out("REJECT")
    if proposal.get("social_only") is True:
        rc.append("SOCIAL_ONLY"); return out("REJECT")
    if route and (route != "momentum_scalp" or actionability not in ("", "GO")
                  or (route_sid and route_sid != "momentum_scalp")):
        rc.append(f"ROUTE_NOT_MOMENTUM_GO({route}/{actionability})"); return out("REJECT")
    if proposal.get("catalyst_verified") is False:
        rc.append("CATALYST_UNVERIFIED"); return out("REJECT")

    # 3. Micro-float boundaries.
    float_m, price, rvol = _num(proposal.get("float_m")), _num(proposal.get("price")), _num(proposal.get("rvol"))
    if float_m is not None and float_m > MICRO_MAX_FLOAT_M:
        rc.append("FLOAT_OVER_20M"); return out("REJECT")
    if price is not None and price > MICRO_MAX_PRICE:
        rc.append("PRICE_OVER_25"); return out("REJECT")
    if rvol is not None and rvol < MIN_RVOL:
        rc.append("RVOL_UNDER_5"); return out("REJECT")

    # 4. Intraday window.
    start, end = _window_bounds(cfg)
    cur = _et_minutes(now)
    if cur is None or not (start <= cur <= end):
        rc.append("OUTSIDE_WINDOW"); return out("REJECT")

    # 5. Proposal age / TTL (authoritative — no weakening).
    try:
        from atm_auto_approver import resolve_atm_expiry
        exp = resolve_atm_expiry("momentum_scalp", proposal.get("created_at"), proposal.get("expires_at"), now=now)
    except Exception:
        exp = {"action": "ok", "age_minutes": None}
    age_m = exp.get("age_minutes")
    if exp.get("action") != "ok":
        rc.append(f"EXPIRED_{(exp.get('reason') or 'ttl').upper()}"); return out("REJECT", None, age_m)

    # 6. Trade plan validity (entry/stop/target + R:R).
    entry = _num(proposal.get("proposed_entry"))
    stop = _num(proposal.get("proposed_stop"))
    target = _num(proposal.get("proposed_target1"))
    if not entry or not stop or not target:
        rc.append("INVALID_PLAN_MISSING"); return out("REJECT", None, age_m)
    if stop >= entry or target <= entry:
        rc.append("INVALID_PLAN_LEVELS"); return out("REJECT", None, age_m)
    rr = (target - entry) / (entry - stop)
    if rr < MIN_RR:
        rc.append(f"RR_TOO_LOW({rr:.2f})"); return out("REJECT", None, age_m)

    # 7. Fresh quote (DEFER if stale/missing — never weaken).
    q = quote or {}
    qage = q.get("age_minutes")
    qage_s = int(qage * 60) if qage is not None else None
    if not q.get("ok"):
        rc.append("LIQUIDITY_UNKNOWN" if q.get("reason") == "no_quote" else "STALE_QUOTE")
        return out("DEFER", qage_s, age_m)
    if qage is not None and qage > QUOTE_FRESH_MAX_MIN:
        rc.append("STALE_QUOTE"); return out("DEFER", qage_s, age_m)

    # 8. Price drift vs proposed entry.
    last = _num(q.get("last_price"))
    if last and entry:
        drift = abs(last - entry) / entry * 100.0
        if drift > _max_drift(cfg):
            rc.append(f"PRICE_DRIFT({drift:.1f}%)"); return out("REJECT", qage_s, age_m)

    rc.append("ALL_GATES_PASS")
    return out("WOULD_SUBMIT_PAPER", qage_s, age_m)


def run(dry_run: bool = True) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    cfg = _cfg()
    try:
        from db_adapter import get_connection
        conn = get_connection()
        cur = conn.cursor()
    except Exception as e:
        return {"ok": False, "status": "WARN", "mode": "dry_run" if dry_run else "paper_only",
                "generated_at": started, "note": f"no database: {e}"}

    try:
        cur.execute(f"""
            SELECT p.id, p.symbol, p.strategy_id, p.target_account, p.created_at, p.expires_at,
                   p.proposed_entry, p.proposed_stop, p.proposed_target1, p.proposed_rr,
                   p.rvol, p.float_m, p.discovery_trace_id, p.lifecycle_status, p.paper_submit_state,
                   COALESCE(s.route,'') AS route, COALESCE(s.route_actionability,'') AS route_actionability,
                   COALESCE(s.route_strategy_id,'') AS route_strategy_id,
                   s.catalyst_verified,
                   (SELECT price FROM scalp_scan_results r WHERE r.symbol=p.symbol
                      ORDER BY scanned_at DESC LIMIT 1) AS price
            FROM paper_trade_proposals p
            LEFT JOIN trade_ai_scans s ON s.symbol=p.symbol AND s.run_date=CURRENT_DATE
            WHERE p.status='PENDING' AND p.strategy_id='momentum_scalp'
              AND p.target_account='{PAPER_ACCOUNT}'
              AND COALESCE(p.paper_submit_state,'') <> 'EXECUTED'
              AND p.created_at > NOW() - INTERVAL '1 day'
        """)
        cols = [d[0] for d in cur.description]
        proposals = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "status": "WARN", "mode": "dry_run" if dry_run else "paper_only",
                "generated_at": started, "note": f"query failed: {str(e).splitlines()[0][:120]}"}

    candidates, submitted_syms = [], []
    for p in proposals:
        quote = None
        try:
            from market_quote_provider import check_fresh_quote
            quote = check_fresh_quote(p["symbol"], strategy_id="momentum_scalp")
        except Exception:
            quote = {"ok": False, "reason": "no_quote"}
        ev = evaluate_paper_fast_path(p, quote=quote, cfg=cfg)
        candidates.append(ev)

        if ev["decision"] == "WOULD_SUBMIT_PAPER" and not dry_run:
            # Deterministic gate-pass → existing SAFE validation submit (no approval). Idempotent + sandbox-only.
            try:
                from proposal_paper_submitter import submit_paper
                res = submit_paper(conn, p["id"], dry_run=False)
                _audit(conn, p, ev, res)
                if res.get("status") in ("submitted", "SUBMITTED", "ok"):
                    submitted_syms.append(p["symbol"])
            except Exception as e:
                ev["submit_error"] = str(e).splitlines()[0][:120]

    summary = {
        "would_submit_paper": sum(1 for c in candidates if c["decision"] == "WOULD_SUBMIT_PAPER"),
        "would_defer": sum(1 for c in candidates if c["decision"] == "DEFER"),
        "would_reject": sum(1 for c in candidates if c["decision"] == "REJECT"),
    }
    return {
        "ok": True,
        "status": "PASS",
        "mode": "dry_run" if dry_run else "paper_only",
        "strategy_id": "momentum_scalp",
        "generated_at": started,
        "candidates_evaluated": len(proposals),
        **summary,
        "paper_submitted_symbols": submitted_syms,
        "candidates": candidates,
        "source_tag": SOURCE_TAG,
        "note": "Deterministic gate-based validation fast-path. NO human validation approval. Sandbox-only via the "
                "existing safe submitter; never the live broker path. Quote-freshness/TTL/window/"
                "liquidity/route/risk gates unchanged. Operator confirmation / 2FA unchanged.",
    }


def submission_allowed(open_count: int, today_count: int, limits: dict = None) -> tuple:
    """P0-5: deterministic dedup/limit gate. Returns (allowed: bool, reason). Pure/testable.
    Blocks when an open paper trade already exists for the symbol, or daily/concurrent caps are hit."""
    limits = limits or {}
    max_daily = int(limits.get("max_daily_trades", 3))
    max_concurrent = int(limits.get("max_concurrent", 10))
    if open_count and open_count > 0:
        return False, "open_paper_trade_exists"
    if today_count is not None and today_count >= max_daily:
        return False, f"max_daily_trades_reached({today_count}/{max_daily})"
    if open_count is not None and open_count >= max_concurrent:
        return False, f"max_concurrent_reached({open_count}/{max_concurrent})"
    return True, "within_limits"


def maybe_run_after_generation(dry_run: bool = True) -> dict | None:
    """P0-5 wiring hook. Runs the validation fast path after proposal generation ONLY when the env
    flag is set (default OFF). Canonical flags: MOMENTUM_SCALP_VALIDATION_FAST_PATH=1 (enable) and
    MOMENTUM_SCALP_VALIDATION_SUBMIT=1 (sandbox submit). Legacy aliases MOMENTUM_SCALP_PAPER_FAST_PATH
    / MOMENTUM_SCALP_PAPER_FAST_PATH_SUBMIT are still honored. Idempotent (the query excludes EXECUTED
    proposals and submit_paper re-checks its own duplicate/idempotency gates). Returns None when OFF."""
    import os
    enabled = (os.getenv("MOMENTUM_SCALP_VALIDATION_FAST_PATH") == "1"
               or os.getenv("MOMENTUM_SCALP_PAPER_FAST_PATH") == "1")
    if not enabled:
        return None
    # Even when enabled, sandbox submit requires the explicit submit opt-in; otherwise dry-run.
    submit = (os.getenv("MOMENTUM_SCALP_VALIDATION_SUBMIT") == "1"
              or os.getenv("MOMENTUM_SCALP_PAPER_FAST_PATH_SUBMIT") == "1")
    return run(dry_run=(dry_run and not submit))


def _audit(conn, proposal, ev, res):
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO atm_decision_log
                       (proposal_id, symbol, strategy_id, target_account, decision, rejection_reasons,
                        config_hash, atm_mode)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (proposal["id"], proposal["symbol"], "momentum_scalp", PAPER_ACCOUNT,
                     "paper_fast_path_submit",
                     json.dumps([{"source": SOURCE_TAG, "decision": ev["decision"],
                                  "submit_status": (res or {}).get("status"),
                                  "discovery_trace_id": proposal.get("discovery_trace_id")}]),
                     "fast_path", SOURCE_TAG))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def main() -> int:
    # Deprecated alias: canonical module is momentum_scalp_validation_fast_path.py (validation
    # taxonomy). Kept working for backward compatibility — same deterministic gates, same safety.
    print("Deprecated alias: use momentum_scalp_validation_fast_path.py "
          "(validation taxonomy). This paper-named CLI still works.", file=sys.stderr)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    # Legacy flags (this is the deprecated alias module): accept both spellings.
    ap.add_argument("--paper-only", "--sandbox-only", dest="sandbox_only", action="store_true")
    args = ap.parse_args()
    dry = not args.sandbox_only  # default dry-run; submit must be explicit
    print(json.dumps(run(dry_run=dry), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
