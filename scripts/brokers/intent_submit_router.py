"""Route a fully-2FA-approved broker OrderIntent to the correct pilot submit path.

Used by protective-stop/confirm, Telegram bkapprove auto-fire, and Broker Orders confirm.
Fail-closed: returns structured errors; never raises."""
from __future__ import annotations


def submit_fully_approved(intent_id: str) -> dict:
    """Submit a persisted intent once is_fully_approved() is true. Consumes 2FA on successful transport."""
    from brokers import approval_service
    from brokers.execution_guard import FIDELITY_PROTECTIVE_MARKER, PROTECTIVE_STOP_MARKER, QUEUE_ENTRY_MARKER

    iid = str(intent_id or "").strip()
    if not iid:
        return {"ok": False, "error": "intent_id required"}
    if not approval_service.is_fully_approved(iid):
        return {"ok": True, "stage": "confirm", "fully_approved": False,
                "note": "channel confirmed; waiting on approval"}

    intent = approval_service._load_intent_any(iid)
    if intent is None:
        return {"ok": False, "error": "no persisted intent for that id (expired?)"}

    marker = getattr(getattr(intent, "meta", None), "strategy_id", None)
    acct = intent.account_key
    sym = (getattr(getattr(intent, "instrument", None), "symbol", None) or "").upper()

    try:
        if marker == FIDELITY_PROTECTIVE_MARKER:
            from brokers import snaptrade_protective_stop_pilot as _fpsp
            res = _fpsp.route_after_2fa(acct, intent)
            res = {"status": "monitored_armed" if res.get("ok") else "rejected", **res}
        elif marker == PROTECTIVE_STOP_MARKER:
            from brokers import protective_stop_pilot as _psp
            from brokers.execution_readiness import evaluate_execution_readiness
            from brokers.evidence_approval import create_order_evidence_approval
            order_spec = _psp.spec_from_intent(intent)
            ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
            readiness = evaluate_execution_readiness(
                {"intent_id": intent.intent_id, "correlation_id": intent.correlation_id,
                 "account_key": acct, "signal_evidence": ev},
                asset_class="equity", broker="schwab", account_key=acct, mode="submit",
            )
            if not readiness.get("ok"):
                blocks = "; ".join(b.get("reason", "") for b in readiness.get("hard_blocks", [])[:3])
                return {"ok": False, "stage": "submit", "error": f"EXECUTION_READINESS BLOCK: {blocks}"}
            eb = create_order_evidence_approval(intent, order_spec, readiness_snapshot=readiness)
            if not eb.get("ok"):
                return {"ok": False, "stage": "submit",
                        "error": f"could not bind evidence approval: {eb.get('error') or eb.get('reason')}"}
            res = _psp.submit(acct, order_spec, intent)
        elif marker == QUEUE_ENTRY_MARKER:
            from brokers import broker_entry_pilot as _bep
            return _bep.confirm_and_submit(iid)
        else:
            # Options and other Schwab live intents use their own pilots when wired.
            try:
                from brokers import options_order_pilot as oop
                ointent = oop.load_intent(iid)
                if ointent is not None:
                    order_spec = oop.spec_from_intent(ointent)
                    res = oop.submit(acct, order_spec, ointent)
                else:
                    return {"ok": False, "error": f"unsupported intent type for auto-submit (strategy_id={marker!r})"}
            except Exception:
                return {"ok": False, "error": f"unsupported intent type for auto-submit (strategy_id={marker!r})"}
    except Exception as e:
        msg = str(e)[:240]
        if "EVIDENCE_REVALIDATION BLOCK:" in msg:
            reason = msg.split("EVIDENCE_REVALIDATION BLOCK:", 1)[1].strip() or "evidence_revalidation_failed"
            return {
                "ok": False,
                "mode": "blocked",
                "stage": "evidence_revalidation",
                "broker_submitted": False,
                "reason": reason,
                "error": f"Trade AI blocked submit before Schwab: {reason}. No broker order was sent.",
            }
        if "EXECUTION_READINESS BLOCK:" in msg:
            return {
                "ok": False,
                "mode": "blocked",
                "stage": "execution_readiness",
                "broker_submitted": False,
                "reason": msg.split("EXECUTION_READINESS BLOCK:", 1)[1].strip() or "execution_readiness_block",
                "error": f"Trade AI blocked submit before Schwab: {msg}. No broker order was sent.",
            }
        return {"ok": False, "stage": "submit", "broker_submitted": False, "error": msg}

    ok_status = res.get("status") in ("submitted", "filled", "monitored_armed")
    if ok_status and marker == PROTECTIVE_STOP_MARKER:
        try:
            import open_trades_intelligence as _oti
            _oti._BSTOP_CACHE["ts"] = 0.0
        except Exception:
            pass
        try:
            from alert_event_writer import save_alert_event
            save_alert_event(alert_type="strategic_alert", severity="warning",
                             source_script="protective_stop", symbol=sym,
                             raw_text=f"[protective-stop:submit] {acct} · {res.get('status')} · {res.get('broker_order_id')}",
                             parsed_payload={"kind": "protective_stop", "phase": "submit",
                                             "account": acct, "result": res, "intent_id": iid})
        except Exception:
            pass

    return {"ok": ok_status, "stage": "submit", "result": res,
            "broker_order_id": res.get("broker_order_id"), "status": res.get("status"),
            "account": acct, "symbol": sym}
