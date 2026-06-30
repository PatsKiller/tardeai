#!/usr/bin/env python3
"""Dry-run Schwab protective-stop 2FA/evidence preflight.

This proves the evidence-bound approval path without calling Schwab. It builds
the same intent/order JSON used by the live protective STOP / STOP_LIMIT /
TRAILING_STOP flow, simulates a typed-ticker approval row, creates the
evidence-bound approval, revalidates the exact order spec hash, and stops before
any broker transport.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _quote_at_for(account: str, symbol: str):
    """Best-effort quote timestamp for session/freshness classification (read-only): the holdings.json
    reprice time (ET) or the per-holding updated_at. The API/UI normally passes the live quote_at directly."""
    for path in (
        PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json",
        PROJECT_ROOT.parent / "trade-ai-v12-rebuild" / "data" / "portfolios" / "state" / "holdings.json",
    ):
        try:
            d = json.loads(path.read_text())
            for row in d.get("holdings") or []:
                if str(row.get("symbol") or "").upper() == symbol.upper() and str(row.get("account") or "") == account:
                    return d.get("last_repriced") or row.get("updated_at") or row.get("as_of")
            return d.get("last_repriced")
        except Exception:
            pass
    return None


def _holding_truth(account: str, symbol: str) -> tuple[float | None, float | None]:
    try:
        import api_v2
        qty, price = api_v2._protective_holding_truth(account, symbol)
        if qty is not None or price is not None:
            return qty, price
    except Exception:
        pass
    for path in (
        PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json",
        PROJECT_ROOT.parent / "trade-ai-v12-rebuild" / "data" / "portfolios" / "state" / "holdings.json",
    ):
        try:
            d = json.loads(path.read_text())
            for row in d.get("holdings") or []:
                if str(row.get("symbol") or "").upper() != symbol.upper():
                    continue
                if str(row.get("account") or row.get("account_id") or "") != account:
                    continue
                qty = row.get("shares") or row.get("quantity") or row.get("qty")
                price = row.get("current_price") or row.get("price")
                return (float(qty) if qty is not None else None,
                        float(price) if price is not None else None)
        except Exception:
            pass
    return None, None


def _simulate_typed_ticker_approval(intent) -> dict:
    from brokers import approval_service
    conn = _conn()
    if not conn:
        return {"ok": False, "missing_field": "postgres_connection", "error": "db_unavailable"}
    cur = conn.cursor()
    approval_service._ensure_intent_persisted(cur, intent)
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)
    cur.execute("""UPDATE trade_approvals SET status='superseded'
                   WHERE intent_id=%s AND status IN ('pending','confirmed')""", (intent.intent_id,))
    cur.execute("""INSERT INTO trade_approvals
                     (intent_id, correlation_id, channel, code, status, expires_at, confirmed_at)
                   VALUES (%s,%s,'web',%s,'confirmed',%s,NOW())""",
                (intent.intent_id, intent.correlation_id, intent.instrument.symbol.upper(), expires))
    conn.commit()
    return {"ok": True, "channel": "web", "proof": "typed_ticker", "expires_at": expires.isoformat()}


def run_preflight(
    *,
    symbol: str,
    account: str,
    order_kind: str,
    trail_pct: float | None,
    stop_price: float | None,
    limit_price: float | None,
    qty: float | None,
    current_price: float | None,
    dry_run: bool,
    quote_at: str | None = None,
    after_hours_ack: bool = False,
    time_in_force: str = "GTC",
    refresh_quote: bool = False,
    allow_after_hours_gtc: bool = False,
) -> dict:
    if not dry_run:
        return {"ok": False, "error": "preflight_requires_dry_run"}
    from brokers import protective_stop_pilot as psp
    from brokers.evidence_approval import (
        create_order_evidence_approval,
        order_spec_hash,
        protective_order_binding,
        revalidate_before_submit,
        supersede_approval,
    )
    from brokers.execution_readiness import evaluate_execution_readiness
    from brokers.quote_time import parse_quote_ts, classify_session, to_iso, quote_age_seconds, is_fresh

    sym = symbol.upper().strip()
    # ── Quote normalization + session classification. --refresh-quote fetches the latest available quote
    # (read-only) first. Freshness is session-aware (regular 15m / extended 60m). An unparseable quote FAILS
    # with a human message (never a raw isoformat error). After-hours readiness is AFTER_HOURS_GTC only with
    # --allow-after-hours-gtc; otherwise it defers to the next regular session.
    quote_refresh = None
    if refresh_quote:
        try:
            import api_v2
            quote_refresh = api_v2._protective_stop_refresh_quote({"symbol": sym, "account": account})
            if quote_refresh.get("quote_time_normalized"):
                quote_at = quote_refresh["quote_time_normalized"]
        except Exception as e:
            quote_refresh = {"error": str(e)[:80]}
    raw_quote = quote_at if quote_at is not None else _quote_at_for(account, sym)
    parsed_q = parse_quote_ts(raw_quote)
    q_session = classify_session(raw_quote)
    q_age = quote_age_seconds(raw_quote)
    q_fresh = is_fresh(raw_quote)
    if parsed_q is None:
        return {"ok": False, "stage": "quote_validation", "broker_submitted": False, "symbol": sym,
                "quote_raw": raw_quote, "quote_session": "unknown", "quote_freshness_class": "unparseable",
                "error": "Quote timestamp could not be parsed; refresh quote before requesting a live stop."}
    # GTC protective stops are valid 24/7 (rest until triggered). After-hours requires an operator
    # acknowledgement at submit; readiness reflects it as the AFTER_HOURS_GTC state, not a block.
    if q_session == "regular":
        q_class = "regular_session_fresh" if q_fresh else "regular_session_stale"
    elif not q_fresh:
        q_class = "after_hours_stale"
    elif after_hours_ack:
        q_class = "after_hours_gtc_acknowledged"
    else:
        q_class = "after_hours_gtc_ack_required"
    try:
        import api_v2 as _api
        ah_override = _api._after_hours_override_enabled()
    except Exception:
        ah_override = False
    operator_readiness = ("BLOCKED_STALE_QUOTE" if not q_fresh
                          else "READY_FOR_OPERATOR" if q_session == "regular"
                          else "READY_FOR_OPERATOR_AFTER_HOURS_GTC" if (ah_override or allow_after_hours_gtc)
                          else "READY_FOR_OPERATOR_NEXT_REGULAR_SESSION")
    held_qty, broker_price = _holding_truth(account, sym)
    qty = float(qty if qty is not None else held_qty if held_qty is not None else 0)
    current_price = float(current_price if current_price is not None else broker_price if broker_price is not None else 0)
    if qty <= 0:
        return {"ok": False, "missing_field": "qty", "error": "quantity unavailable; pass --qty or refresh holdings DB"}
    whole_qty = math.floor(qty)
    residual_qty = round(qty - whole_qty, 6)
    if whole_qty < 1:
        return {"ok": False, "missing_field": "whole_qty", "error": "Schwab protective stops require at least one whole share"}
    ot = psp.normalize_kind(order_kind)
    if ot not in {"STOP", "STOP_LIMIT", "TRAILING_STOP"}:
        return {"ok": False, "missing_field": "order_kind", "error": f"unsupported order kind {order_kind!r}"}
    if ot in {"STOP", "STOP_LIMIT"} and stop_price is None:
        return {"ok": False, "missing_field": "stop_price", "error": "STOP/STOP_LIMIT preflight requires --stop-price"}
    if ot == "TRAILING_STOP" and trail_pct is None:
        return {"ok": False, "missing_field": "trail_pct", "error": "TRAILING_STOP preflight requires --trail-pct"}

    intent = psp.build_intent(
        account, sym, whole_qty, ot,
        stop_price=stop_price if stop_price is not None else current_price,
        limit_price=limit_price,
        trail_pct=trail_pct,
        advised_stop=stop_price,
        current_price=current_price,
        held_qty=qty,
    )
    # Attach residual evidence without changing the broker order quantity.
    ev = getattr(getattr(intent, "meta", None), "signal_evidence", None) or {}
    ev["residual_qty"] = residual_qty
    order_spec = psp.spec_from_intent(intent)
    binding = protective_order_binding(intent, order_spec)
    submit_hash = order_spec_hash(order_spec, binding=binding)

    approval = _simulate_typed_ticker_approval(intent)
    if not approval.get("ok"):
        return {"ok": False, **approval}

    readiness = evaluate_execution_readiness(
        {"intent_id": intent.intent_id, "correlation_id": intent.correlation_id,
         "account_key": account, "signal_evidence": ev},
        asset_class="equity", broker="schwab", account_key=account, mode="submit",
    )
    if not readiness.get("ok"):
        return {"ok": False, "stage": "execution_readiness", "error": "execution readiness blocked",
                "hard_blocks": readiness.get("hard_blocks"), "broker_submitted": False}

    evidence = create_order_evidence_approval(intent, order_spec, readiness_snapshot=readiness)
    if not evidence.get("ok"):
        return {"ok": False, "stage": "create_evidence", "missing_field": evidence.get("error"),
                "error": evidence.get("error") or evidence.get("reason"), "broker_submitted": False}
    rev = revalidate_before_submit(
        intent.intent_id,
        current_readiness=readiness,
        current_order_spec=order_spec,
        current_binding=binding,
        kill_switch_check=False,
    )
    approved_hash = evidence.get("order_spec_hash") or submit_hash
    # Dry-run cleanup: the simulated evidence-bound approval was only created to revalidate the chain (done
    # above). Supersede it so a dry-run never leaves a lingering "active approval lock" — the operator's real
    # click + per-order 2FA creates a fresh approval. (Previously only trade_approvals was reset, so these
    # evidence_bound_approvals rows accumulated and showed as a false active lock in the readiness panel.)
    superseded = supersede_approval(intent.intent_id, reason="dry_run_preflight")
    return {
        "ok": bool(rev.get("ok") and approved_hash == submit_hash),
        "stage": "preflight",
        "broker_submitted": False,
        "dry_run_evidence_superseded": superseded,
        "active_approval_lock": False,
        "quote_raw": raw_quote,
        "quote_normalized": to_iso(raw_quote),
        "quote_session": q_session,
        "quote_fresh": q_fresh,
        "quote_age_sec": int(q_age) if q_age is not None else None,
        "quote_freshness_class": q_class,
        "operator_readiness": operator_readiness,
        "after_hours_ack": bool(after_hours_ack),
        "after_hours_ack_required": q_session != "regular",
        "requires_after_hours_ack": q_session != "regular",
        "allow_after_hours_gtc": bool(allow_after_hours_gtc),
        "quote_refresh": quote_refresh,
        # Explicit canary target — the evidence-bound order_spec_hash binds account+qty+order_type+trail+TIF, so
        # rollover (201/8.7%) and roth (130/10%) are distinct targets and can never be confused.
        "canary_target": {"symbol": sym, "account": account, "qty": whole_qty, "residual": residual_qty,
                          "order_kind": ot, "trail_pct": trail_pct, "time_in_force": time_in_force,
                          "session": q_session, "quote_at": to_iso(raw_quote)},
        "symbol": sym,
        "account": account,
        "order_type": ot,
        "whole_qty": whole_qty,
        "residual_qty": residual_qty,
        "trail_pct": trail_pct,
        "stop_price": stop_price,
        "time_in_force": order_spec.get("duration"),
        "intent_id": intent.intent_id,
        "evidence_id": evidence.get("evidence_id"),
        "evidence_hash": evidence.get("evidence_hash"),
        "approved_order_spec_hash": approved_hash,
        "submit_order_spec_hash": submit_hash,
        "hashes_match": approved_hash == submit_hash,
        "revalidation": rev,
        "order_spec": order_spec,
        "message": "PASS: evidence-bound approval revalidated; no Schwab broker request sent"
        if rev.get("ok") and approved_hash == submit_hash else
        f"FAIL: {rev.get('reason') or 'order_spec_hash_mismatch'}",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Dry-run Schwab protective stop evidence-bound 2FA preflight.")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--account", required=True)
    ap.add_argument("--order-kind", required=True)
    ap.add_argument("--trail-pct", type=float)
    ap.add_argument("--stop-price", type=float)
    ap.add_argument("--limit-price", type=float)
    ap.add_argument("--qty", type=float)
    ap.add_argument("--current-price", type=float)
    ap.add_argument("--quote-at", help="quote timestamp (ISO / 'YYYY-MM-DD HH:MM:SS ET'); default from holdings")
    ap.add_argument("--after-hours-ack", action="store_true",
                    help="operator after-hours acknowledgement (trigger behavior depends on regular-market conditions)")
    ap.add_argument("--time-in-force", default="GTC", help="order duration (default GTC; protective stops rest until triggered)")
    ap.add_argument("--refresh-quote", action="store_true", help="fetch the latest available quote (read-only) before classifying")
    ap.add_argument("--allow-after-hours-gtc", action="store_true",
                    help="enable the explicit after-hours GTC override (default off; otherwise defers to next regular session)")
    ap.add_argument("--dry-run", action="store_true", required=True)
    args = ap.parse_args()
    out = run_preflight(
        symbol=args.symbol,
        account=args.account,
        order_kind=args.order_kind,
        trail_pct=args.trail_pct,
        stop_price=args.stop_price,
        limit_price=args.limit_price,
        qty=args.qty,
        current_price=args.current_price,
        dry_run=args.dry_run,
        quote_at=args.quote_at,
        after_hours_ack=args.after_hours_ack,
        time_in_force=args.time_in_force,
        refresh_quote=args.refresh_quote,
        allow_after_hours_gtc=args.allow_after_hours_gtc,
    )
    print(json.dumps(out, indent=2, default=str))
    sys.exit(0 if out.get("ok") else 1)


if __name__ == "__main__":
    main()
