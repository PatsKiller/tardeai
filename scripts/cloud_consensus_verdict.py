#!/usr/bin/env python3
"""cloud_consensus_verdict.py — Cloud dual-consensus approval verdicts (ADVISORY ONLY).

Grok + ChatGPT (the free OAuth lanes, via cloud_review.py → :8645 grok / :8646 chatgpt
proxies) each produce an independent formal approval VERDICT on qualifying broker
proposals, using the EXISTING broker_promote_oversight review packet + cloud_review
prompt path ("broker_live_trade_review").

    both lanes AGREE                          → CLOUD_APPROVE
    any split / CAUTION / DISAGREE / lane
    failure / UNKNOWN                         → ESCALATED   (fail-closed)
    qualifying but no reviewable trade
    context (no thesis, no plan)              → BLOCKED_INFO (informational, no lane calls)

HARD GUARANTEES (operator-locked):
  * ADVISORY ONLY. This pipeline approves NOTHING autonomously.
  * NO proposal status change — the only write is an INSERT INTO cloud_consensus_verdicts
    (additive table; never UPDATEs paper_trade_proposals or any queue table).
  * Per-order 2FA and all execution gates untouched. No imports from brokers/,
    approval_service, execution_guard, or protective stop code.
  * Daily cap + enabled/paused kill switch in config/cloud_consensus_policy.json.
  * db_adapter one-statement rule: every read commits immediately (db_adapter._execute),
    and any txn opened by reused oversight helpers is released BEFORE lane calls — a txn
    held through a 3-min LLM generation dies at the 120s idle-in-transaction timeout.

Qualifier (a proposal is scored only when ALL hold):
  * status IN ('PENDING','APPROVED_FOR_PAPER_TEST') and not expired
  * catalyst_verified IS TRUE
  * sized WITHIN policy caps — reuses broker_promote_sizing.evaluate_broker_promote
    (operator_route=True); any "policy cap" / "operator override" warning disqualifies
  * no verdict row already stored for the proposal in the last 24h

Usage:
  --run            score qualifying proposals (lane calls) + weekly do-no-harm check
  --dry-run        qualifier + policy-cap checks only — NO lane calls, NO writes, NO telegram
  --weekly-stats   run only the do-no-harm kill-switch stats (may pause the pipeline)

Suggested cron (NOT installed by this script):
  */30 9-16 * * 1-5 cd <root> && flock -n /tmp/cloud_consensus_verdict.lock \
      .venv/bin/python scripts/cloud_consensus_verdict.py --run >> logs/cloud_consensus_verdict.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "config" / "cloud_consensus_policy.json"

REVIEW_TASK = "broker_live_trade_review"          # same task/prompt path as broker_promote_oversight
REVIEW_SOURCE = "cloud_consensus_verdict"
LANE_TIMEOUT = int(os.getenv("CLOUD_CONSENSUS_LANE_TIMEOUT", "180"))
NOTE_MAX = 400

# Do-no-harm kill-switch thresholds (env-overridable — no hardcoded-values rule).
KILL_WIN_RATE_DELTA_PTS = float(os.getenv("CLOUD_CONSENSUS_KILL_WR_DELTA", "-10"))
KILL_MIN_OUTCOMES = int(os.getenv("CLOUD_CONSENSUS_KILL_MIN_N", "10"))
KILL_DISAGREE_RATIO = float(os.getenv("CLOUD_CONSENSUS_KILL_DISAGREE", "0.60"))
KILL_MIN_DISAGREE_N = int(os.getenv("CLOUD_CONSENSUS_KILL_DISAGREE_MIN_N", "5"))

# Warnings from evaluate_broker_promote(operator_route=True) that mean the saved size is
# OUTSIDE policy caps / operator-overridden — these disqualify a proposal from cloud scoring.
POLICY_WARNING_RE = re.compile(r"policy cap|operator override", re.IGNORECASE)

# Qualifier SQL — active, not expired, verified catalyst, not scored in the last 24h.
# (Policy-cap sizing is checked per-row in Python via the existing evaluate_broker_promote.)
QUALIFIER_SQL = """
    SELECT id, symbol, strategy_id,
           COALESCE(target_account, proposed_account) AS account,
           proposed_entry, proposed_stop, proposed_target1, proposed_shares,
           status, expires_at, catalyst, catalyst_verified
      FROM paper_trade_proposals
     WHERE status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST')
       AND (expires_at IS NULL OR expires_at > NOW())
       AND catalyst_verified IS TRUE
       AND id NOT IN (
             SELECT proposal_id FROM cloud_consensus_verdicts
              WHERE created_at > NOW() - INTERVAL '24 hours')
     ORDER BY created_at DESC
     LIMIT 100
"""


# ── DB (one-statement rule: _execute commits every statement) ────────────────

def _exec(sql, params=None, fetch=None):
    from db_adapter import _execute
    return _execute(sql, params, fetch=fetch)


def _release_read_txn() -> None:
    """Reused oversight helpers (broker_promote_oversight._q) run SELECTs on the shared
    connection WITHOUT committing — release that txn before any lane call so we never hold
    an idle transaction through minutes of LLM generation (the 120s idle-txn reaper)."""
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if conn is not None:
            conn.rollback()
    except Exception:
        pass


# ── Policy json ───────────────────────────────────────────────────────────────

def load_policy() -> dict:
    try:
        pol = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        if isinstance(pol, dict):
            return pol
    except Exception:
        pass
    # Fail-closed: unreadable policy disables scoring.
    return {"daily_cap": 0, "enabled": False, "paused": True,
            "pause_reason": "policy file missing/unreadable"}


def save_policy(pol: dict) -> None:
    POLICY_PATH.write_text(json.dumps(pol, indent=2) + "\n", encoding="utf-8")


# ── Qualifier ─────────────────────────────────────────────────────────────────

def fetch_candidates() -> list[dict]:
    return _exec(QUALIFIER_SQL, fetch="all") or []


def policy_cap_check(prop: dict) -> tuple[bool, str]:
    """Reuse the EXISTING policy-warning computation (broker_promote_sizing.
    evaluate_broker_promote, operator_route=True — the TrustLine 'policy warnings' source).
    Qualified only when the saved size raises no policy-cap / operator-override warning."""
    acct = str(prop.get("account") or "").strip()
    if not acct:
        return False, "no destination account — cannot evaluate policy caps (fail-closed)"
    try:
        sh = int(float(prop.get("proposed_shares") or 0))
        en = float(prop.get("proposed_entry") or 0)
        st = float(prop.get("proposed_stop") or 0)
        tg = float(prop.get("proposed_target1") or 0)
    except Exception:
        return False, "unparseable plan numbers (fail-closed)"
    if sh < 1 or en <= 0:
        return False, "no sized plan (shares/entry missing)"
    try:
        import broker_promote_sizing as bps
        ev = bps.evaluate_broker_promote(
            acct, str(prop.get("strategy_id") or "momentum_scalp"),
            en, st, tg, sh, operator_route=True,
            proposal_id=int(prop["id"]) if prop.get("id") else None,
        )
    except Exception as e:
        return False, f"policy evaluation error: {str(e)[:120]} (fail-closed)"
    hits = [w for w in (ev.get("warnings") or []) if POLICY_WARNING_RE.search(str(w))]
    if hits:
        return False, "outside policy caps: " + "; ".join(str(h)[:120] for h in hits[:2])
    return True, (
        f"status={prop.get('status')} · catalyst_verified · not expired · "
        f"{sh} sh within policy cap {ev.get('policy_max_shares')}"
    )


# ── Consensus rule ────────────────────────────────────────────────────────────

def _lane_verdict(lane: dict | None) -> tuple[str, str]:
    """(verdict, note) for one lane. A lane that did not return ok is LANE_FAILED."""
    lane = lane or {}
    if not lane.get("ok"):
        return "LANE_FAILED", str(lane.get("error") or "lane unavailable")[:NOTE_MAX]
    v = str(lane.get("verdict") or "UNKNOWN").upper()
    note = str(lane.get("assessment") or "")[:NOTE_MAX]
    return v, note


def compute_consensus(lanes: dict) -> dict:
    """Both lanes AGREE → CLOUD_APPROVE; anything else (split, CAUTION, DISAGREE,
    UNKNOWN, lane failure) → ESCALATED. Fail-closed by construction."""
    gv, gn = _lane_verdict((lanes or {}).get("grok"))
    cv, cn = _lane_verdict((lanes or {}).get("chatgpt"))
    consensus = "CLOUD_APPROVE" if (gv == "AGREE" and cv == "AGREE") else "ESCALATED"
    return {"consensus": consensus,
            "grok_verdict": gv, "grok_note": gn,
            "chatgpt_verdict": cv, "chatgpt_note": cn}


# ── Persistence + telegram (throttled) ────────────────────────────────────────

def todays_verdict_count() -> int:
    row = _exec("SELECT COUNT(*) AS n FROM cloud_consensus_verdicts WHERE created_at::date = CURRENT_DATE",
                fetch="one") or {}
    return int(row.get("n") or 0)


def recent_escalation_exists(proposal_id: int) -> bool:
    """Telegram throttle: one split alert per proposal per 24h."""
    row = _exec("""SELECT 1 AS x FROM cloud_consensus_verdicts
                    WHERE proposal_id=%s AND consensus='ESCALATED'
                      AND created_at > NOW() - INTERVAL '24 hours' LIMIT 1""",
                (proposal_id,), fetch="one")
    return bool(row)


def insert_verdict(proposal_id: int, verdict: dict, qualified_reason: str) -> None:
    _exec("""INSERT INTO cloud_consensus_verdicts
                (proposal_id, grok_verdict, grok_note, chatgpt_verdict, chatgpt_note,
                 consensus, qualified_reason)
             VALUES (%s,%s,%s,%s,%s,%s,%s)""",
          (proposal_id,
           verdict.get("grok_verdict"), verdict.get("grok_note"),
           verdict.get("chatgpt_verdict"), verdict.get("chatgpt_note"),
           verdict["consensus"], str(qualified_reason or "")[:500]))


def _send_telegram(msg: str) -> None:
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
    except Exception as e:
        print(f"  [telegram] send failed: {str(e)[:120]}")


def send_split_alert(proposal_id: int, symbol: str, verdict: dict) -> bool:
    """ONE message per proposal per 24h through the central telegram router."""
    if recent_escalation_exists(proposal_id):
        return False
    _send_telegram(
        f"☁️ Cloud consensus split on #{proposal_id} {symbol}: "
        f"grok={verdict.get('grok_verdict')} chatgpt={verdict.get('chatgpt_verdict')} — review"
    )
    return True


# ── Scoring one proposal (existing reviewer prompt/path) ─────────────────────

def score_proposal(prop: dict, timeout: int = LANE_TIMEOUT) -> dict:
    """Build the SAME review packet broker_promote_oversight sends to cloud_review, run
    BOTH lanes, and return the consensus verdict dict. No proposal mutation, ever."""
    pid = int(prop["id"])
    sym = str(prop.get("symbol") or "").upper()
    import broker_promote_oversight as bpo
    local = bpo._fetch_local_llm(pid)
    context = bpo._cloud_review_context(pid, local)
    thesis = bpo._build_cloud_review_subject(local, context).strip()
    has_substance = bool((local.get("thesis") or "").strip() or context.get("planned_entry") is not None)
    _release_read_txn()   # NEVER hold a read txn through LLM generation
    if not thesis or not has_substance:
        return {"consensus": "BLOCKED_INFO",
                "grok_verdict": None, "grok_note": None,
                "chatgpt_verdict": None, "chatgpt_note": None,
                "blocked_reason": "insufficient trade context for cloud review"}
    import cloud_review
    result = cloud_review.review(
        REVIEW_TASK,
        local_output=thesis,
        context=context,
        lanes=("grok", "chatgpt"),
        timeout=timeout,
        persist=True,
        symbol=sym,
        source=REVIEW_SOURCE,
    )
    return compute_consensus(result.get("lanes") or {})


# ── Do-no-harm kill switch (weekly stats) ────────────────────────────────────

def weekly_do_no_harm_check(policy: dict, *, dry_run: bool = False) -> dict:
    """Compare closed outcomes of CLOUD_APPROVE'd proposals vs others (paper_trades join)
    and the 7d lane-disagreement ratio. If degraded, pause the pipeline in the policy json
    + ONE telegram notice. Manual resume = operator edits the json."""
    out = {"checked": True, "degraded": None}
    if policy.get("paused"):
        out.update(checked=False, reason="already paused")
        return out

    # 7d verdict mix (BLOCKED_INFO rows are informational — excluded from disagreement).
    rows = _exec("""SELECT consensus FROM cloud_consensus_verdicts
                     WHERE created_at > NOW() - INTERVAL '7 days'
                       AND consensus <> 'BLOCKED_INFO'""", fetch="all") or []
    n7 = len(rows)
    esc7 = sum(1 for r in rows if str(r.get("consensus")) == "ESCALATED")
    disagree_ratio = (esc7 / n7) if n7 else 0.0
    out.update(verdicts_7d=n7, escalated_7d=esc7, disagree_ratio=round(disagree_ratio, 3))

    # Closed-outcome win rates: CLOUD_APPROVE'd proposals vs all other closed proposals (7d exits).
    wr_rows = _exec("""
        SELECT (v.proposal_id IS NOT NULL) AS cloud_approved,
               COUNT(*) AS n,
               AVG(CASE WHEN t.pnl > 0 THEN 100.0 ELSE 0.0 END) AS win_rate
          FROM paper_trades t
          LEFT JOIN (SELECT DISTINCT proposal_id FROM cloud_consensus_verdicts
                      WHERE consensus = 'CLOUD_APPROVE') v
                 ON t.proposal_id = v.proposal_id
         WHERE t.pnl IS NOT NULL
           AND COALESCE(t.status, '') NOT IN ('open', 'superseded_by_fill', 'cancelled')
           AND t.exit_time > NOW() - INTERVAL '7 days'
         GROUP BY 1""", fetch="all") or []
    wr = {bool(r.get("cloud_approved")): r for r in wr_rows}
    a, b = wr.get(True) or {}, wr.get(False) or {}
    a_n, b_n = int(a.get("n") or 0), int(b.get("n") or 0)
    a_wr = float(a.get("win_rate") or 0.0)
    b_wr = float(b.get("win_rate") or 0.0)
    out.update(approved_outcomes=a_n, other_outcomes=b_n,
               approved_win_rate=round(a_wr, 1), other_win_rate=round(b_wr, 1))

    degraded = None
    if a_n >= KILL_MIN_OUTCOMES and b_n >= KILL_MIN_OUTCOMES and (a_wr - b_wr) < KILL_WIN_RATE_DELTA_PTS:
        degraded = (f"win-rate delta {a_wr - b_wr:+.1f}pts (CLOUD_APPROVE {a_wr:.0f}% n={a_n} "
                    f"vs others {b_wr:.0f}% n={b_n}) < {KILL_WIN_RATE_DELTA_PTS:+.0f}pts")
    elif n7 >= KILL_MIN_DISAGREE_N and disagree_ratio > KILL_DISAGREE_RATIO:
        degraded = (f"lane disagreement {disagree_ratio:.0%} over 7d ({esc7}/{n7} escalated) "
                    f"> {KILL_DISAGREE_RATIO:.0%}")
    out["degraded"] = degraded
    if degraded and not dry_run:
        policy["paused"] = True
        policy["pause_reason"] = f"do-no-harm kill switch: {degraded}"
        save_policy(policy)
        _send_telegram(
            f"⏸️ Cloud consensus verdicts PAUSED (do-no-harm): {degraded}. "
            f"Manual resume: edit config/cloud_consensus_policy.json"
        )
        out["paused_now"] = True
    return out


# ── Runner ────────────────────────────────────────────────────────────────────

def run(*, dry_run: bool = False, timeout: int = LANE_TIMEOUT) -> dict:
    policy = load_policy()
    summary = {"ok": True, "dry_run": dry_run, "scored": 0, "skipped": [], "verdicts": []}
    if not policy.get("enabled", False):
        summary.update(ok=False, reason="disabled in config/cloud_consensus_policy.json")
        return summary
    if policy.get("paused"):
        summary.update(ok=False, reason=f"paused: {policy.get('pause_reason') or 'operator'}")
        return summary

    cap = int(policy.get("daily_cap") or 0)
    used = todays_verdict_count()
    remaining = max(0, cap - used)
    summary.update(daily_cap=cap, used_today=used, remaining=remaining)
    if remaining <= 0:
        summary.update(reason="daily cap reached — no scoring")
        return summary

    candidates = fetch_candidates()
    summary["candidates"] = len(candidates)
    for prop in candidates:
        if summary["scored"] >= remaining:
            summary["reason"] = "daily cap reached mid-run"
            break
        pid = int(prop["id"])
        sym = str(prop.get("symbol") or "").upper()
        ok, reason = policy_cap_check(prop)
        if not ok:
            summary["skipped"].append({"id": pid, "symbol": sym, "reason": reason})
            continue
        if dry_run:
            summary["verdicts"].append({"id": pid, "symbol": sym, "qualified": True,
                                        "qualified_reason": reason, "dry_run": True})
            summary["scored"] += 1
            continue
        verdict = score_proposal(prop, timeout=timeout)
        qualified_reason = verdict.pop("blocked_reason", None) or reason
        # Throttle check BEFORE insert so this run's row doesn't suppress its own alert.
        alert = (verdict["consensus"] == "ESCALATED" and send_split_alert(pid, sym, verdict))
        insert_verdict(pid, verdict, qualified_reason)
        summary["verdicts"].append({"id": pid, "symbol": sym, "alerted": alert, **verdict})
        summary["scored"] += 1

    if not dry_run:
        summary["do_no_harm"] = weekly_do_no_harm_check(policy)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Cloud dual-consensus advisory verdicts (approves nothing)")
    ap.add_argument("--run", action="store_true", help="score qualifying proposals (lane calls)")
    ap.add_argument("--dry-run", action="store_true", help="qualifier only — no lane calls, no writes")
    ap.add_argument("--weekly-stats", action="store_true", help="do-no-harm kill-switch stats only")
    ap.add_argument("--timeout", type=int, default=LANE_TIMEOUT)
    args = ap.parse_args()
    if args.weekly_stats:
        out = weekly_do_no_harm_check(load_policy())
    elif args.run or args.dry_run:
        out = run(dry_run=args.dry_run, timeout=args.timeout)
    else:
        ap.print_help()
        return 2
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
