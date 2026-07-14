"""Route a fully-2FA-approved broker OrderIntent to the correct pilot submit path.

Used by protective-stop/confirm, Telegram bkapprove auto-fire, and Broker Orders confirm.
Fail-closed: returns structured errors; never raises."""
from __future__ import annotations


def cancel_replace_stop_if_needed(intent) -> dict | None:
    """Cancel an existing broker/monitored stop before a replace submit.

    Shared by the web confirm path and Telegram auto-fire so replace mode always
    cancel-then-places — never adds a second live stop. Returns None when no replace
    target is set; otherwise a result dict with ok=True/False."""
    from brokers.execution_guard import FIDELITY_PROTECTIVE_MARKER

    _ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    _replace_id = _ev.get("replace_order_id")
    _replace_stop_id = _ev.get("replace_stop_id")
    acct = intent.account_key
    marker = getattr(getattr(intent, "meta", None), "strategy_id", None)
    sym = (getattr(getattr(intent, "instrument", None), "symbol", None) or "").upper()

    if _replace_stop_id and marker == FIDELITY_PROTECTIVE_MARKER:
        try:
            import fidelity_monitored_stop as _fms
            return _fms.cancel(stop_id=int(_replace_stop_id))
        except Exception as ce:
            return {"ok": False, "error": f"could not cancel monitored stop #{_replace_stop_id}: {str(ce)[:160]}"}
    if not _replace_id or marker == FIDELITY_PROTECTIVE_MARKER:
        return None
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import schwab_transport as _st
        replace_result = _st.cancel_order_for_replace(acct, str(_replace_id), verify=True)
        if not replace_result.get("ok"):
            _err = (replace_result.get("error")
                    or f"could not confirm cancel of existing stop #{_replace_id}")
            try:
                from alert_event_writer import save_alert_event
                save_alert_event(
                    alert_type="strategic_alert", severity="warning",
                    source_script="protective_stop", symbol=sym,
                    raw_text=f"[protective-stop:replace_cancel_failed] {acct} · #{_replace_id} · {_err[:120]}",
                    parsed_payload={"kind": "protective_stop", "phase": "replace_cancel_failed",
                                    "account": acct, "replace_order_id": str(_replace_id),
                                    "result": replace_result})
            except Exception:
                pass
            return {"ok": False, "error": _err, "modify_cancel_result": replace_result}
        return {"ok": True, "modify_cancel_result": replace_result}
    except Exception as ce:
        return {"ok": False, "error": f"could not cancel the existing stop #{_replace_id}: {str(ce)[:160]}"}


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
            # Replace cancel runs inside schwab_transport.place_order (single gate — avoids double-DELETE).
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
