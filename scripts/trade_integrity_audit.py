#!/usr/bin/env python3
"""trade_integrity_audit.py — Dual audit + validation of EVERY trade.

Two independent signers must sign off on each trade:

  1. Trade AI (deterministic, this script): rule-based integrity checks against the
     broker-as-source-of-truth model — broker confirmation, no phantom, protection
     present, P&L integrity, lineage, data freshness.
  2. Hermes (agent/LLM, paper_trade_multi_reviews): thesis/research validation by the
     agent fleet.

A trade is GREEN only when Trade AI passes AND Hermes has reviewed it. Anything else is
surfaced (WARN/FAIL/UNREVIEWED) and, for hard failures, pushed to SIEM. This is the
"audit and validate every trade" layer — it runs over 100% of trades, not a sample.

The Trade AI side is READ-ONLY except for writing its own audit rows; it never mutates
trade records. Phantom *remediation* stays in paper_trade_monitor; this engine only
reports. Use --enqueue-hermes to request agent reviews for trades Hermes hasn't seen.

Usage:
    .venv/bin/python scripts/trade_integrity_audit.py                 # audit all, write rows
    .venv/bin/python scripts/trade_integrity_audit.py --open-only     # only open trades
    .venv/bin/python scripts/trade_integrity_audit.py --json          # machine output
    .venv/bin/python scripts/trade_integrity_audit.py --enqueue-hermes # request missing reviews
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

DDL = """
CREATE TABLE IF NOT EXISTS trade_integrity_audit (
    id              bigserial PRIMARY KEY,
    paper_trade_id  bigint NOT NULL,
    symbol          text,
    account         text,
    broker          text,
    trade_state     text,              -- open / closed
    trade_ai_verdict text NOT NULL,    -- PASS / WARN / FAIL
    trade_ai_checks  jsonb,            -- {check: pass/fail/na, ...}
    trade_ai_reasons text[],           -- failed/warned check reasons
    hermes_verdict   text NOT NULL,    -- REVIEWED / UNREVIEWED
    hermes_review_count int DEFAULT 0,
    hermes_last_review_at timestamptz,
    dual_status      text NOT NULL,    -- GREEN / YELLOW / RED
    remediated       boolean DEFAULT false,  -- a resolved historical issue (e.g. voided phantom)
    audited_at       timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE trade_integrity_audit ADD COLUMN IF NOT EXISTS remediated boolean DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_tia_trade ON trade_integrity_audit(paper_trade_id);
CREATE INDEX IF NOT EXISTS idx_tia_audited ON trade_integrity_audit(audited_at DESC);
CREATE INDEX IF NOT EXISTS idx_tia_dual ON trade_integrity_audit(dual_status);
"""


def _conn():
    from db_adapter import get_connection
    return get_connection()


def _broker_state():
    """Live broker state (source of truth): (held_symbols, stop_symbols).
    held = symbols currently held; stop = symbols with a live protective stop order.
    Returns (None, None) if the broker can't be reached, so we never false-flag."""
    try:
        from alpaca_paper_adapter import AlpacaPaperAdapter
        a = AlpacaPaperAdapter()
        if not a.enabled:
            return None, None
        held = {p.get("symbol") for p in (a.get_positions() or []) if p.get("symbol")}
        stops = {o.get("symbol") for o in (a.get_open_orders() or [])
                 if o.get("type") in ("stop", "stop_limit") and o.get("side") == "sell"}
        return held, stops
    except Exception:
        return None, None


def audit_trade(t, broker_syms, broker_stop_syms, reviews_by_trade):
    """Run Trade AI deterministic checks + Hermes coverage for one trade row (dict)."""
    checks, reasons = {}, []
    state = "open" if (t.get("status") == "open" or t.get("lifecycle_state") == "open") else "closed"
    is_open = state == "open"

    def fail(key, msg):
        checks[key] = "fail"; reasons.append(msg)

    def warn(key, msg):
        checks[key] = "warn"; reasons.append(msg)

    # 1. Broker confirmation — every real trade must be broker-confirmed (broker is truth)
    if t.get("broker_confirmed"):
        checks["broker_confirmed"] = "pass"
    elif is_open:
        fail("broker_confirmed", "open trade not broker-confirmed")
    else:
        checks["broker_confirmed"] = "na"

    # 2. Phantom. An ACTIVE phantom (open in DB but not held at broker) is a hard failure.
    #    A phantom that is already closed + voided is REMEDIATED — a resolved historical issue,
    #    not a live one, so it must not drown out active failures.
    is_flagged_phantom = (t.get("outcome_verdict") == "PHANTOM"
                          or t.get("close_reason") == "phantom_no_alpaca_position")
    if is_open and broker_syms is not None and t.get("symbol") not in broker_syms:
        fail("not_phantom", f"open but {t.get('symbol')} not held at broker")
    elif is_flagged_phantom and not is_open:
        checks["not_phantom"] = "remediated"  # closed+voided — resolved, informational
    else:
        checks["not_phantom"] = "pass"

    # 3. Protection — open trades must carry a stop. The BROKER is the source of truth: a live
    #    sell-stop at the broker (or a recorded stop_order_id) IS protection, even if the DB's
    #    stop_loss_price display column is stale/NULL. Only fall back to DB columns when broker
    #    state is unavailable, so we never false-flag a protected position.
    if is_open:
        has_broker_stop = (broker_stop_syms is not None and t.get("symbol") in broker_stop_syms)
        has_recorded_stop = bool(t.get("stop_order_id")) and (t.get("broker_stop_status") not in (None, "canceled", "expired", "rejected"))
        has_db_stop = bool(t.get("stop_loss_price") or t.get("planned_stop"))
        if has_broker_stop or has_recorded_stop:
            checks["has_protection"] = "pass"
        elif broker_stop_syms is None and has_db_stop:
            checks["has_protection"] = "pass"  # broker unreachable — trust DB
        else:
            fail("has_protection", "open trade has no stop at broker")
    else:
        checks["has_protection"] = "na"

    # 4. P&L integrity — closed trades must have P&L recorded (phantoms voided to 0 are fine)
    if not is_open:
        if is_flagged_phantom:
            checks["pnl_integrity"] = "na"
        elif t.get("pnl") is None:
            warn("pnl_integrity", "closed trade missing P&L")
        else:
            checks["pnl_integrity"] = "pass"
    else:
        checks["pnl_integrity"] = "na"

    # 5. Lineage — a trade should trace to a strategy and/or a proposal
    if t.get("strategy_id") or t.get("proposal_id"):
        checks["has_lineage"] = "pass"
    else:
        warn("has_lineage", "no strategy_id/proposal_id lineage")

    # 6. Data freshness — open trades should have a recent broker sync
    if is_open:
        ls = t.get("last_synced_at")
        if ls is None:
            warn("data_fresh", "open trade never synced")
        else:
            age_h = (datetime.now(timezone.utc) - ls).total_seconds() / 3600 if ls.tzinfo else None
            if age_h is not None and age_h > 24:
                warn("data_fresh", f"last sync {age_h:.0f}h ago")
            else:
                checks["data_fresh"] = "pass"
    else:
        checks["data_fresh"] = "na"

    # 7. Fill verification — surface the two-source verdict so a broker-refuted fill or a qty/price
    #    MISMATCH is SEEN, not buried. (fill_verified_ok: TRUE=confirmed, FALSE=broker refutes,
    #    NULL=couldn't verify — fall-back, not a failure.)
    if t.get("fill_verified_ok") is False:
        fail("fill_verification", "broker refuted the fill (terminal not-filled)")
    elif t.get("_fill_verdict") == "MISMATCH":
        warn("fill_verification", "fill qty/price mismatch vs broker — review (still counted)")
    elif t.get("fill_verified_ok") is True:
        checks["fill_verification"] = "pass"
    else:
        checks["fill_verification"] = "na"   # unverified / couldn't-run — not a failure

    # Trade AI verdict
    if any(v == "fail" for v in checks.values()):
        ai_verdict = "FAIL"
    elif any(v == "warn" for v in checks.values()):
        ai_verdict = "WARN"
    else:
        ai_verdict = "PASS"

    # Hermes coverage
    rv = reviews_by_trade.get(t["id"], {})
    h_count = rv.get("cnt", 0)
    hermes_verdict = "REVIEWED" if h_count > 0 else "UNREVIEWED"

    # Dual status: GREEN only if Trade AI PASS and Hermes reviewed
    if ai_verdict == "FAIL":
        dual = "RED"
    elif ai_verdict == "WARN" or hermes_verdict == "UNREVIEWED":
        dual = "YELLOW"
    else:
        dual = "GREEN"

    return {
        "paper_trade_id": t["id"], "symbol": t.get("symbol"), "account": t.get("account"),
        "broker": t.get("broker"), "trade_state": state,
        "trade_ai_verdict": ai_verdict, "trade_ai_checks": checks, "trade_ai_reasons": reasons,
        "hermes_verdict": hermes_verdict, "hermes_review_count": h_count,
        "hermes_last_review_at": rv.get("latest"),
        "dual_status": dual,
        "remediated": checks.get("not_phantom") == "remediated",
    }


def run_audit(open_only=False, enqueue_hermes=False, write=True):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(DDL)
    conn.commit()

    # cancelled orders never became a real round-trip — they are not trades and are excluded
    # from the audit entirely (they don't need protection checks or Hermes review).
    if open_only:
        where = "WHERE status='open' OR lifecycle_state='open'"
    else:
        where = ("WHERE COALESCE(status,'') NOT IN ('cancelled','canceled') "
                 "AND COALESCE(lifecycle_state,'') NOT IN ('cancelled','canceled')")
    cur.execute(f"""
        SELECT id, symbol, account, broker, shares, entry_price, stop_loss_price, planned_stop,
               target_1, status, lifecycle_state, broker_confirmed, broker_status, broker_order_id,
               pnl, outcome_verdict, close_reason, closed_via, current_price, last_synced_at,
               strategy_id, proposal_id, stop_order_id, broker_stop_status,
               fill_verified_ok, confirmation_state
        FROM paper_trades {where} ORDER BY id
    """)
    cols = [d[0] for d in cur.description]
    trades = [dict(zip(cols, r)) for r in cur.fetchall()]

    # Hermes review coverage in one query
    cur.execute("""
        SELECT paper_trade_id, COUNT(*) AS cnt, MAX(created_at) AS latest
        FROM paper_trade_multi_reviews GROUP BY paper_trade_id
    """)
    reviews_by_trade = {r[0]: {"cnt": r[1], "latest": r[2]} for r in cur.fetchall()}

    # Latest fill-verification verdict per trade — so a broker-refuted / qty-price MISMATCH is
    # visible in the audit (and on the v3 Brokers tab), not buried in the staging table.
    try:
        cur.execute("""
            SELECT DISTINCT ON (paper_trade_id) paper_trade_id, verdict
            FROM hermes_fill_verifications ORDER BY paper_trade_id, checked_at DESC
        """)
        fill_verdict = {r[0]: r[1] for r in cur.fetchall()}
    except Exception:
        fill_verdict = {}
    for t in trades:
        t["_fill_verdict"] = fill_verdict.get(t["id"])

    broker_syms, broker_stop_syms = _broker_state()

    results = [audit_trade(t, broker_syms, broker_stop_syms, reviews_by_trade) for t in trades]

    if write:
        for r in results:
            cur.execute("""
                INSERT INTO trade_integrity_audit
                    (paper_trade_id, symbol, account, broker, trade_state, trade_ai_verdict,
                     trade_ai_checks, trade_ai_reasons, hermes_verdict, hermes_review_count,
                     hermes_last_review_at, dual_status, remediated)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, [r["paper_trade_id"], r["symbol"], r["account"], r["broker"], r["trade_state"],
                  r["trade_ai_verdict"], json.dumps(r["trade_ai_checks"]), r["trade_ai_reasons"],
                  r["hermes_verdict"], r["hermes_review_count"], r["hermes_last_review_at"],
                  r["dual_status"], r["remediated"]])
        conn.commit()

    # Surface hard failures to SIEM (best-effort)
    reds = [r for r in results if r["dual_status"] == "RED"]
    if reds and write:
        try:
            for r in reds:
                cur.execute("""
                    INSERT INTO system_health_events (component, event_type, severity, message, created_at)
                    VALUES ('trade_integrity_audit', 'TRADE_INTEGRITY_RED', 'P1', %s, now())
                """, [f"Trade #{r['paper_trade_id']} {r['symbol']} RED: {'; '.join(r['trade_ai_reasons'])}"])
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"trade_integrity_audit: SIEM insert failed: {e}", file=sys.stderr)

    # Optionally request Hermes reviews for unreviewed trades
    enqueued = 0
    if enqueue_hermes:
        unreviewed = [r["paper_trade_id"] for r in results if r["hermes_verdict"] == "UNREVIEWED"]
        enqueued = _enqueue_hermes_reviews(conn, unreviewed)

    summary = {
        "total": len(results),
        "green": sum(1 for r in results if r["dual_status"] == "GREEN"),
        "yellow": sum(1 for r in results if r["dual_status"] == "YELLOW"),
        "red": sum(1 for r in results if r["dual_status"] == "RED"),
        "trade_ai_pass": sum(1 for r in results if r["trade_ai_verdict"] == "PASS"),
        "trade_ai_warn": sum(1 for r in results if r["trade_ai_verdict"] == "WARN"),
        "trade_ai_fail": sum(1 for r in results if r["trade_ai_verdict"] == "FAIL"),
        "hermes_reviewed": sum(1 for r in results if r["hermes_verdict"] == "REVIEWED"),
        "hermes_unreviewed": sum(1 for r in results if r["hermes_verdict"] == "UNREVIEWED"),
        # coverage measured over REVIEWABLE trades only (closed) — open trades can't be reviewed
        "closed_total": sum(1 for r in results if r["trade_state"] == "closed"),
        "closed_reviewed": sum(1 for r in results if r["trade_state"] == "closed" and r["hermes_verdict"] == "REVIEWED"),
        "broker_truth_available": broker_syms is not None,
        "hermes_enqueued": enqueued,
    }
    ct, cr = summary["closed_total"], summary["closed_reviewed"]
    summary["hermes_coverage_pct"] = round(100 * cr / ct, 1) if ct else 0.0
    return summary, results


def _enqueue_hermes_reviews(conn, trade_ids):
    """Generate the missing Hermes agent reviews by invoking the REAL reviewer
    (multi_tier_trade_reviewer.py, realtime tier / gemma3:4b). Only CLOSED trades are
    reviewable — open trades are skipped. Runs sequentially to avoid saturating the local
    LLM. Returns the count successfully reviewed.

    (The old agent_jobs queue path was a no-op — that table does not exist; reviews are
    produced by the multi-tier reviewer, not an agent_jobs consumer.)"""
    if not trade_ids:
        return 0
    import subprocess
    cur = conn.cursor()
    cur.execute("SELECT id FROM paper_trades WHERE id = ANY(%s) AND status='closed'", [list(trade_ids)])
    closed_ids = [r[0] for r in cur.fetchall()]
    reviewer = str(PROJECT_ROOT / "scripts" / "multi_tier_trade_reviewer.py")
    reviewed = 0
    for tid in closed_ids:
        try:
            r = subprocess.run(
                [sys.executable, reviewer, "--tier", "realtime", "--trade-id", str(tid)],
                capture_output=True, text=True, timeout=180, cwd=str(PROJECT_ROOT))
            if r.returncode == 0:
                reviewed += 1
        except Exception:
            pass
    return reviewed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--open-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--enqueue-hermes", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    summary, results = run_audit(open_only=args.open_only,
                                 enqueue_hermes=args.enqueue_hermes,
                                 write=not args.no_write)
    if args.json:
        print(json.dumps({"summary": summary, "results": results}, indent=2, default=str))
        return 0

    print("Trade Integrity Audit — Trade AI + Hermes dual sign-off")
    print("=" * 72)
    for r in results:
        icon = {"GREEN": "✓", "YELLOW": "◐", "RED": "✗"}.get(r["dual_status"], "?")
        line = f"{icon} #{r['paper_trade_id']:<4} {r['symbol'] or '?':<6} {r['trade_state']:<6} " \
               f"AI={r['trade_ai_verdict']:<4} Hermes={r['hermes_verdict']:<10} -> {r['dual_status']}"
        print(line)
        if r["trade_ai_reasons"]:
            print(f"      {'; '.join(r['trade_ai_reasons'])}")
    print("=" * 72)
    s = summary
    print(f"{s['total']} trades | GREEN {s['green']}  YELLOW {s['yellow']}  RED {s['red']}")
    print(f"Trade AI: PASS {s['trade_ai_pass']} / WARN {s['trade_ai_warn']} / FAIL {s['trade_ai_fail']}")
    print(f"Hermes:   {s['closed_reviewed']}/{s['closed_total']} closed reviewed "
          f"({s['hermes_coverage_pct']}%)"
          + (f" | enqueued {s['hermes_enqueued']}" if args.enqueue_hermes else ""))
    if not s["broker_truth_available"]:
        print("NOTE: broker positions unavailable this run — phantom checks limited to flagged records.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
