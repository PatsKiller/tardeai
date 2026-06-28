#!/usr/bin/env python3
"""P0-4: diagnose the PAPER-ONLY momentum_scalp conversion path.

Walks signal → proposal → approval → paper-trade and identifies the FIRST bottleneck stage
and its dominant reason, so we can see why valid momentum_scalp candidates do (or do not)
become confirmed paper trades. Read-only — NO broker writes, no live calls. Missing tables
degrade to WARN.

    python3 scripts/diagnose_momentum_scalp_paper_path.py --days 30 --json
    python3 scripts/diagnose_momentum_scalp_paper_path.py --days 30 --markdown > docs/diligence/current/MOMENTUM_SCALP_PAPER_PATH_DIAGNOSIS.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STRAT = "momentum_scalp"


def build(days: int = 30) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    warnings: list[str] = []
    try:
        from db_adapter import get_connection
        conn = get_connection()
        cur = conn.cursor()
    except Exception as e:
        return {"ok": False, "status": "WARN", "generated_at": started,
                "warnings": [f"no database: {e}"], "note": "Read-only diagnosis. No broker writes."}

    since = f"NOW() - INTERVAL '{int(days)} days'"

    def scalar(sql, params=None):
        try:
            cur.execute(sql, params or [])
            r = cur.fetchone()
            return (r[0] if r else 0)
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            warnings.append(str(e).splitlines()[0][:120])
            return None

    def breakdown(sql, params=None):
        try:
            cur.execute(sql, params or [])
            return {str(r[0]): r[1] for r in cur.fetchall()}
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            warnings.append(str(e).splitlines()[0][:120])
            return {}

    signals = scalar(f"SELECT COUNT(*) FROM strategy_signals WHERE fired_at > {since} AND strategy_id=%s", [STRAT])
    proposals = scalar(f"SELECT COUNT(*) FROM paper_trade_proposals WHERE created_at > {since} AND strategy_id=%s", [STRAT])
    prop_status = breakdown(f"SELECT status, COUNT(*) FROM paper_trade_proposals WHERE created_at > {since} "
                            f"AND strategy_id=%s GROUP BY status ORDER BY 2 DESC", [STRAT])
    prop_lifecycle = breakdown(f"SELECT lifecycle_status, COUNT(*) FROM paper_trade_proposals WHERE created_at > {since} "
                               f"AND strategy_id=%s GROUP BY lifecycle_status ORDER BY 2 DESC", [STRAT])
    auto_decisions = breakdown(f"SELECT decision, COUNT(*) FROM auto_proposal_decisions WHERE created_at > {since} "
                               f"AND strategy_id=%s GROUP BY decision ORDER BY 2 DESC", [STRAT])
    atm_decisions = breakdown(f"SELECT decision, COUNT(*) FROM atm_decision_log WHERE decided_at > {since} "
                              f"AND strategy_id=%s GROUP BY decision ORDER BY 2 DESC", [STRAT])
    atm_gates = breakdown(
        f"SELECT gate, COUNT(*) FROM (SELECT jsonb_array_elements(rejection_reasons)->>'gate' AS gate "
        f"FROM atm_decision_log WHERE decided_at > {since} AND strategy_id=%s "
        f"AND rejection_reasons IS NOT NULL) t GROUP BY gate ORDER BY 2 DESC", [STRAT])
    # Dominant approval-failure detail (e.g. stale quote at approval time).
    approval_fail_sample = scalar(
        f"SELECT atm_last_failure_reason FROM paper_trade_proposals WHERE created_at > {since} "
        f"AND strategy_id=%s AND atm_last_failure_reason ILIKE 'approve_proposal_failed%%' "
        f"ORDER BY created_at DESC LIMIT 1", [STRAT])
    pt_status = breakdown(f"SELECT status, COUNT(*) FROM paper_trades WHERE entry_time > {since} "
                          f"AND strategy_id=%s GROUP BY status ORDER BY 2 DESC", [STRAT])

    # Confirmed paper trades via the shared conservative attributor (all-time + windowed).
    try:
        import scalp_trade_attribution as attr_mod
        attr = attr_mod.attribute(conn)
        confirmed = attr.get("confirmed_opened")
        non_executed = attr.get("non_executed_count")
    except Exception as e:
        confirmed = non_executed = None
        warnings.append(f"attribution: {str(e).splitlines()[0][:80]}")

    approved = sum(v for k, v in (prop_status or {}).items()
                   if k in ("APPROVED_FOR_PAPER_TEST", "BROKER_SUBMITTED"))
    expired = sum(v for k, v in (prop_status or {}).items() if "EXPIRED" in (k or ""))
    pending = (prop_status or {}).get("PENDING", 0)

    # ── First bottleneck heuristic ──
    bottleneck, detail = None, None
    _approve_fail = (atm_gates or {}).get("approve_proposal_failed", 0)
    _atm_approved = (atm_decisions or {}).get("approved", 0)
    if signals == 0:
        bottleneck = "no_signals"
        detail = "No momentum_scalp strategy_signals in window — discovery/sync produced no candidates."
    elif proposals == 0:
        top = max(auto_decisions.items(), key=lambda kv: kv[1])[0] if auto_decisions else "unknown"
        bottleneck = "no_proposals_from_signals"
        detail = f"Signals exist but no proposals created; dominant auto-proposal decision: {top}."
    elif _approve_fail and _approve_fail >= max(1, _atm_approved):
        bottleneck = "approval_fails_on_stale_quote"
        detail = (f"Legacy ATM approval failed {_approve_fail}× (gate=approve_proposal_failed); dominant "
                  f"cause: {str(approval_fail_sample)[:80]}. The freshness gate is working correctly. "
                  f"Operator decision 2026-06-28: momentum_scalp paper testing does NOT require human "
                  f"approval — the fix is to run the deterministic paper FAST-PATH "
                  f"(momentum_scalp_paper_fast_path.py) immediately after a proposal is created or "
                  f"becomes ENTRY_ZONE_VALID, NOT to 'approve faster'. Do NOT weaken freshness.")
    elif approved == 0 and pending and pending == proposals:
        bottleneck = "proposals_stuck_pending"
        detail = "Proposals created but none approved — all PENDING (ATM not approving / not running)."
    elif approved == 0 and expired:
        bottleneck = "proposals_expired_before_approval"
        detail = f"{expired} proposals expired (intraday TTL) before approval — fast-path/cadence too slow."
    elif (confirmed in (0, None)) and (pt_status.get("cancelled", 0) or 0) > 0:
        bottleneck = "approved_but_cancelled_before_fill"
        detail = (f"Proposals approved and paper_trades created, but {pt_status.get('cancelled',0)} are "
                  f"'cancelled' (never filled) and 0 confirmed — the break is at paper submission/fill, "
                  f"not proposal generation.")
    elif confirmed and confirmed < 30:
        bottleneck = "converting_but_insufficient_sample"
        detail = f"{confirmed} confirmed paper trades — path works but sample << 30 (needs time)."
    else:
        bottleneck = "unknown"
        detail = "Could not localize a single bottleneck from available data."

    status = "PASS" if not warnings else "WARN"
    return {
        "ok": True,
        "status": status,
        "generated_at": started,
        "window_days": days,
        "stages": {
            "strategy_signals": signals,
            "proposals_created": proposals,
            "proposals_by_status": prop_status,
            "proposals_by_lifecycle": prop_lifecycle,
            "proposals_approved_for_paper": approved,
            "proposals_expired": expired,
            "proposals_pending": pending,
            "auto_proposal_decisions": auto_decisions,
            "atm_decisions": atm_decisions,
            "atm_rejection_gates": atm_gates,
            "approval_failure_sample": approval_fail_sample,
            "paper_trades_by_status": pt_status,
            "confirmed_paper_trades": confirmed,
            "non_executed_rows": non_executed,
        },
        "first_bottleneck": bottleneck,
        "bottleneck_detail": detail,
        "recommended_fix": ("Run the deterministic paper FAST-PATH immediately after proposal "
                            "creation / ENTRY_ZONE_VALID (momentum_scalp_paper_fast_path.py, paper-only, "
                            "no human approval). Do NOT weaken quote freshness, TTL, window, or liquidity."),
        "paper_approval_required": False,
        "valid_candidates_present": bool(signals),
        "warnings": warnings,
        "note": "Read-only diagnosis. No broker writes. Paper-only. Operator/2FA path unchanged.",
    }


def to_markdown(r: dict) -> str:
    L = ["# Momentum Scalp Paper-Path Diagnosis", "",
         f"**Status: {r['status']}** | window: {r.get('window_days')}d  ",
         f"_Generated: {r['generated_at']}_  ",
         "_Source: `python3 scripts/diagnose_momentum_scalp_paper_path.py --days N --json`_  ", ""]
    if not r.get("ok"):
        return "\n".join(L + ["> WARN: " + "; ".join(r.get("warnings", ["no data"]))])
    L += [f"## First bottleneck: `{r['first_bottleneck']}`", "", f"> {r['bottleneck_detail']}", "",
          "## Stage counts", "", "| Stage | Value |", "|-------|-------|"]
    for k, v in r["stages"].items():
        if isinstance(v, dict):
            v = ", ".join(f"{kk}={vv}" for kk, vv in v.items()) or "—"
        L.append(f"| {k} | {v} |")
    if r.get("warnings"):
        L += ["", "## Warnings", ""] + [f"- {w}" for w in r["warnings"]]
    L += ["", "> " + r["note"]]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    r = build(args.days)
    if args.markdown:
        print(to_markdown(r))
    elif args.json:
        print(json.dumps(r, indent=2, default=str))
    else:
        print(f"Paper-path diagnosis: bottleneck={r.get('first_bottleneck')} ({r.get('status')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
