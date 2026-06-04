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


def _broker_symbols():
    """Live broker holdings (source of truth) — symbols currently held at the broker.
    Best-effort: if the adapter can't be reached, return None so we don't false-flag."""
    try:
        from alpaca_paper_adapter import AlpacaPaperAdapter
        a = AlpacaPaperAdapter()
        if not a.enabled:
            return None
        return {p.get("symbol") for p in (a.get_positions() or []) if p.get("symbol")}
    except Exception:
        return None


def audit_trade(t, broker_syms, reviews_by_trade):
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

    # 3. Protection — open trades must carry a stop
    if is_open:
        if t.get("stop_loss_price") or t.get("planned_stop"):
            checks["has_protection"] = "pass"
        else:
            fail("has_protection", "open trade has no stop")
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

    where = "WHERE status='open' OR lifecycle_state='open'" if open_only else ""
    cur.execute(f"""
        SELECT id, symbol, account, broker, shares, entry_price, stop_loss_price, planned_stop,
               target_1, status, lifecycle_state, broker_confirmed, broker_status, broker_order_id,
               pnl, outcome_verdict, close_reason, closed_via, current_price, last_synced_at,
               strategy_id, proposal_id
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

    broker_syms = _broker_symbols()

    results = [audit_trade(t, broker_syms, reviews_by_trade) for t in trades]

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
                    INSERT INTO system_health_events (component, status, severity, message, created_at)
                    VALUES ('trade_integrity_audit', 'FAIL', 'P1', %s, now())
                """, [f"Trade #{r['paper_trade_id']} {r['symbol']} RED: {'; '.join(r['trade_ai_reasons'])}"])
            conn.commit()
        except Exception:
            conn.rollback()

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
        "broker_truth_available": broker_syms is not None,
        "hermes_enqueued": enqueued,
    }
    return summary, results


def _enqueue_hermes_reviews(conn, trade_ids):
    """Best-effort: queue agent review jobs for trades Hermes hasn't seen.
    Uses the agent_jobs queue if present; otherwise no-op (reports 0)."""
    if not trade_ids:
        return 0
    cur = conn.cursor()
    try:
        cur.execute("SELECT to_regclass('public.agent_jobs')")
        if not cur.fetchone()[0]:
            return 0
        n = 0
        for tid in trade_ids:
            cur.execute("""
                INSERT INTO agent_jobs (job_type, status, payload, created_at)
                VALUES ('paper_trade_review', 'queued', %s, now())
                ON CONFLICT DO NOTHING
            """, [json.dumps({"paper_trade_id": tid, "source": "trade_integrity_audit"})])
            n += cur.rowcount
        conn.commit()
        return n
    except Exception:
        conn.rollback()
        return 0


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
    print(f"Hermes:   reviewed {s['hermes_reviewed']} / unreviewed {s['hermes_unreviewed']}"
          + (f" | enqueued {s['hermes_enqueued']}" if args.enqueue_hermes else ""))
    if not s["broker_truth_available"]:
        print("NOTE: broker positions unavailable this run — phantom checks limited to flagged records.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
