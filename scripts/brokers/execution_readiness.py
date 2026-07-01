#!/usr/bin/env python3
"""Central execution-readiness resolver — single source of truth for live-adjacent submit decisions.

LLM output is NEVER a gate unlock. Unknown/missing values are hard blocks.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from typing import Any

REQUIRED_GATES = (
    "global_live_allowed", "broker_policy_enabled", "db_operator_arm_enabled",
    "strategy_enabled", "account_allowlisted", "product_allowed", "proposal_exists",
    "authoritative_trade_plan", "fresh_market_data", "risk_preflight_hard_pass",
    "desk_queue_approved", "operator_2fa_confirmed", "kill_switches_clear",
    "broker_ack_required", "broker_write_fence",
)


def _iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _evidence_hash(snapshots: dict) -> str:
    canonical = json.dumps(snapshots, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _gate(code: str, ok: bool, reason: str, *, severity: str = "hard",
          source: str = "execution_readiness", snapshot: Any = None) -> dict:
    return {
        "ok": ok,
        "code": code,
        "reason": reason,
        "severity": severity,
        "source": source,
        "snapshot": snapshot,
    }


def _global_live_allowed() -> dict:
    """Delegate to execution_guard standing-lock logic (env OR session OR standing DB unlock)."""
    try:
        from brokers.execution_guard import _live_future_unlocked
        ok = bool(_live_future_unlocked())
        import execution_state as es
        snap = es._live_unlock_status()
        return _gate(
            "global_live_allowed", ok,
            "live locked — standing unlock + broker_live_enabled + approval required"
            if not ok else "live enabled via operator unlock — per-order 2FA still required",
            snapshot=snap,
        )
    except Exception as e:
        return _gate("global_live_allowed", False, f"cannot_inspect_db:{e}", snapshot={"fail_closed": True})


def _paper_mode() -> bool:
    try:
        from brokers.execution_guard import _live_future_unlocked
        return not bool(_live_future_unlocked())
    except Exception:
        return True


def _kill_switches_clear(*, broker: str, account_key: str, strategy: str, symbol: str,
                          asset_class: str) -> dict:
    try:
        from brokers.kill_switches import is_blocked
        blocked, reasons = is_blocked(broker=broker, account_key=account_key, strategy=strategy,
                                      symbol=symbol, asset_class=asset_class, live_submit=True)
        return _gate("kill_switches_clear", not blocked,
                     "; ".join(reasons) if blocked else "no active kill switches",
                     snapshot={"reasons": reasons})
    except Exception as e:
        return _gate("kill_switches_clear", False, f"kill_switch_inspect_failed:{e}")


def _operator_2fa(intent_id: str | None) -> dict:
    if not intent_id:
        return _gate("operator_2fa_confirmed", False, "intent_id_missing")
    try:
        from brokers.approval_service import is_fully_approved
        ok = is_fully_approved(intent_id)
        return _gate("operator_2fa_confirmed", ok,
                     "per-trade 2FA not confirmed" if not ok else "2FA confirmed",
                     snapshot={"intent_id": intent_id})
    except Exception as e:
        return _gate("operator_2fa_confirmed", False, f"2fa_inspect_failed:{e}")


def _llm_cannot_unlock(evidence: dict) -> dict:
    """LLM advisory only — never unlocks live path."""
    llm = evidence.get("llm") or evidence.get("model_snapshot") or {}
    if llm.get("unlock_live") or llm.get("override_risk") or llm.get("set_policy"):
        return _gate("llm_advisory_only", False, "llm_attempted_live_unlock_blocked",
                     source="llm_governance")
    return _gate("llm_advisory_only", True, "llm advisory metadata only — no unlock",
                 severity="info", source="llm_governance", snapshot={"llm_present": bool(llm)})


def evaluate_execution_readiness(
    intent_or_proposal: dict | Any,
    *,
    asset_class: str = "equity",
    broker: str = "schwab",
    account_key: str | None = None,
    mode: str = "submit",
) -> dict:
    """Evaluate all gates for a submit/preflight decision. Fail-closed on any unknown.

    Modes (P0-4 — preflight readiness is separated from submit readiness):
      * ``preflight``  — evaluate deterministic gates only; if everything deterministic
                          passes and only operator confirmation remains, return
                          ``operator_required`` WITHOUT marking gates failed. No 2FA hard block.
      * ``submit``     — require ALL deterministic gates AND operator 2FA; missing 2FA is a
                          HARD block. (``live`` is accepted as an alias of ``submit``.)
      * ``dry_run``    — never writes; reports what would block.
      * ``audit``      — no side effects at all (no audit-ledger write); full gate matrix.
    An unknown mode is treated as ``submit`` (strictest / fail-closed).
    """
    raw_mode = mode
    if mode in ("live", "operator_required"):
        mode = "submit" if mode == "live" else "preflight"
    if mode not in ("preflight", "submit", "dry_run", "audit"):
        mode = "submit"
    correlation_id = str(
        getattr(intent_or_proposal, "correlation_id", None)
        or (intent_or_proposal or {}).get("correlation_id")
        or uuid.uuid4()
    )
    intent_id = str(
        getattr(intent_or_proposal, "intent_id", None)
        or (intent_or_proposal or {}).get("intent_id")
        or ""
    )
    if hasattr(intent_or_proposal, "account_key"):
        account_key = account_key or getattr(intent_or_proposal, "account_key", None)
    elif isinstance(intent_or_proposal, dict):
        account_key = account_key or intent_or_proposal.get("account_key")

    ev = {}
    if hasattr(intent_or_proposal, "meta"):
        ev = getattr(getattr(intent_or_proposal, "meta", None), "signal_evidence", None) or {}
    elif isinstance(intent_or_proposal, dict):
        ev = intent_or_proposal.get("signal_evidence") or intent_or_proposal.get("enterprise") or {}

    strategy = str(ev.get("strategy") or intent_or_proposal.get("strategy") if isinstance(intent_or_proposal, dict) else ev.get("strategy") or "unknown")
    symbol = ""
    if hasattr(intent_or_proposal, "instrument"):
        symbol = getattr(getattr(intent_or_proposal, "instrument", None), "symbol", "") or ""
    elif isinstance(intent_or_proposal, dict):
        symbol = intent_or_proposal.get("symbol") or intent_or_proposal.get("underlying") or ""

    hard_blocks: list[dict] = []
    soft_warnings: list[dict] = []
    gate_results: dict[str, dict] = {}
    required_operator_steps: list[str] = []

    def _collect(g: dict) -> None:
        gate_results[g["code"]] = g
        if not g["ok"]:
            if g.get("severity") == "hard" or g.get("severity") is None:
                hard_blocks.append({"code": g["code"], "reason": g["reason"], "source": g.get("source")})
            else:
                soft_warnings.append({"code": g["code"], "reason": g["reason"]})

    # Core gates
    for g in (
        _global_live_allowed(),
        _kill_switches_clear(broker=broker, account_key=account_key or "", strategy=strategy,
                             symbol=symbol, asset_class=asset_class),
        _llm_cannot_unlock({"llm": intent_or_proposal.get("model_snapshot") if isinstance(intent_or_proposal, dict) else {}}),
    ):
        _collect(g)

    # Broker policy
    if asset_class == "option":
        try:
            from brokers import options_execution_policy as oep
            pol_ok = oep.ENABLED
            db_arm = False
            try:
                from db_adapter import _get_conn
                cur = _get_conn().cursor()
                cur.execute("SELECT value FROM system_controls WHERE key='options_execution_enabled'")
                r = cur.fetchone()
                db_arm = bool(r and str(r[0]).lower() == "true")
            except Exception as e:
                _collect(_gate("db_operator_arm_enabled", False, f"cannot_inspect:{e}"))
                pol_ok = False
            _collect(_gate("broker_policy_enabled", pol_ok, "options policy disabled in commit"))
            _collect(_gate("db_operator_arm_enabled", db_arm, "options DB arm disabled"))
            if pol_ok and not db_arm:
                required_operator_steps.append("Run options_pilot_arm.py --approve")
            ev_ok, ev_reasons = oep.evaluate(
                account_key=account_key, strategy=strategy,
                order_type=str(ev.get("order_type") or "LIMIT"),
                contracts=int(ev.get("contracts") or 1),
                notional_usd=float(ev.get("notional_usd") or 0),
                spread_width_pct=ev.get("spread_width_pct"),
                symbol=symbol,
            )
            _collect(_gate("account_allowlisted", ev_ok, "; ".join(ev_reasons) or "policy pass",
                          snapshot={"reasons": ev_reasons}))
        except Exception as e:
            _collect(_gate("broker_policy_enabled", False, f"options_policy_unavailable:{e}"))
    else:
        _collect(_gate("broker_policy_enabled", True, "equity path uses canary/protective policy",
                      severity="info"))

    # Account write fence
    write_ok = False
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("SELECT api_write_enabled FROM broker_accounts WHERE account_key=%s", (account_key,))
        r = cur.fetchone()
        write_ok = bool(r and r[0] is True)
    except Exception as e:
        _collect(_gate("broker_write_fence", False, f"cannot_inspect_api_write:{e}"))
    else:
        _collect(_gate("broker_write_fence", write_ok,
                      "api_write_enabled false — pilot disarmed" if not write_ok else "write fence open for account"))

    # Proposal / trade plan
    proposal_id = ev.get("proposal_id") or (intent_or_proposal.get("id") if isinstance(intent_or_proposal, dict) else None)
    _collect(_gate("proposal_exists", bool(proposal_id or intent_id),
                  "no proposal_id or intent_id bound"))
    _collect(_gate("authoritative_trade_plan", bool(intent_id),
                  "intent must be persisted before live submit"))

    # Options hard risk + desk approval
    if asset_class == "option" and isinstance(intent_or_proposal, dict):
        try:
            import options_desk_enterprise as ent
            # Always evaluate hard risk blocks for an options readiness check, regardless of
            # the readiness mode (preflight/submit/dry_run/audit all surface would-be blocks).
            risk_mode = "submit" if mode in ("submit", "audit") else "preflight"
            blocks = ent.evaluate_hard_risk_blocks(intent_or_proposal, mode=risk_mode)
            for b in blocks:
                _collect(_gate(b["code"], False, b["reason"], source=b.get("source", "options_desk_enterprise"),
                               snapshot=b.get("snapshot")))
            if not blocks:
                _collect(_gate("risk_preflight_hard_pass", True, "no hard risk blocks"))
            pid = proposal_id
            if pid:
                approved = ent.is_desk_queue_approved(str(pid))
                _collect(_gate("desk_queue_approved", approved,
                              "desk queue approval missing or expired" if not approved else "desk approved"))
                if not approved:
                    required_operator_steps.append("Approve proposal in desk queue")
        except AttributeError:
            _collect(_gate("risk_preflight_hard_pass", False, "hard_risk_evaluator_not_installed"))
        except Exception as e:
            _collect(_gate("risk_preflight_hard_pass", False, f"risk_preflight_error:{e}"))

    # Market data freshness (options)
    if asset_class == "option":
        quote_age = ev.get("quote_age_seconds")
        chain_age = ev.get("chain_age_seconds")
        data_src = ev.get("data_source") or (intent_or_proposal.get("data_source") if isinstance(intent_or_proposal, dict) else None)
        max_quote = 120
        max_chain = 300
        if quote_age is None and data_src is None:
            _collect(_gate("fresh_market_data", False, "quote freshness unknown — fail closed"))
        elif quote_age is not None and float(quote_age) > max_quote:
            _collect(_gate("fresh_market_data", False, f"quote stale {quote_age}s > {max_quote}s"))
        elif data_src in ("bs_estimate", "yfinance", "fallback"):
            _collect(_gate("fresh_market_data", False, f"live path requires broker chain not {data_src}"))
        else:
            _collect(_gate("fresh_market_data", True, "market data within tolerance",
                          snapshot={"quote_age": quote_age, "chain_age": chain_age, "source": data_src}))
        if chain_age is not None and float(chain_age) > max_chain:
            _collect(_gate("option_chain_fresh", False, f"chain stale {chain_age}s"))

    # 2FA — operator confirmation gate. Classification is mode-dependent (P0-4):
    #   submit            → missing 2FA is a HARD block (submit readiness)
    #   preflight/dry_run → missing 2FA is an OPERATOR-REQUIRED step, not a safety failure
    #   audit             → recorded in the matrix only
    twofa_gate = _operator_2fa(intent_id)
    gate_results[twofa_gate["code"]] = twofa_gate
    if not twofa_gate["ok"]:
        if mode == "submit":
            hard_blocks.append({"code": twofa_gate["code"], "reason": twofa_gate["reason"],
                                "source": twofa_gate.get("source")})
        else:
            required_operator_steps.append("Complete operator 2FA (type ticker or telegram code)")

    # Broker ack rule (informational at preflight)
    _collect(_gate("broker_ack_required", True,
                  "submit creates SUBMIT_REQUESTED; live state requires broker ack",
                  severity="info"))

    # NOTE: the hashed snapshot MUST be deterministic for the same decision state — this evidence_hash is
    # the like-to-like readiness key that evidence_approval.revalidate_before_submit compares stored-vs-
    # regenerated at submit time. A wall-clock `generated_at` here made the hash change on EVERY call, so
    # revalidation ALWAYS failed with readiness_hash_changed → the operator could never submit an approved
    # stop (orphaned, never-used approvals piled up). generated_at is reported in `out` for display, but is
    # deliberately excluded from the hash. Keep only stable, decision-relevant fields below.
    snapshots = {
        "gate_results": {k: {"ok": v["ok"], "reason": v["reason"]} for k, v in gate_results.items()},
        "correlation_id": correlation_id,
        "intent_id": intent_id,
        "asset_class": asset_class,
        "broker": broker,
        "account_key": account_key,
    }
    evidence_hash = _evidence_hash(snapshots)

    informational_gates = [
        {"code": g["code"], "reason": g["reason"]}
        for g in gate_results.values() if g.get("severity") == "info"
    ]

    deterministic_ok = len(hard_blocks) == 0
    twofa_ok = bool(gate_results.get("operator_2fa_confirmed", {}).get("ok"))
    global_ok = bool(gate_results.get("global_live_allowed", {}).get("ok"))
    paper = _paper_mode()

    if mode == "audit":
        result_mode = "audit"
    elif not deterministic_ok:
        result_mode = "blocked"
    elif mode == "dry_run" or paper:
        result_mode = "dry_run"
    elif not global_ok:
        result_mode = "blocked"
        required_operator_steps.append("Enable global live locks via operator procedure (not autonomous)")
    elif not twofa_ok:
        # Reachable only in preflight (submit makes missing 2FA a hard block above).
        result_mode = "operator_required"
        required_operator_steps.append("Complete operator 2FA (type ticker or telegram code)")
    else:
        result_mode = "ready_after_approval"

    if result_mode == "audit":
        ok_out = deterministic_ok
    else:
        ok_out = deterministic_ok and result_mode in ("dry_run", "ready_after_approval")

    final_submit_ready = bool(
        mode == "submit" and deterministic_ok and global_ok and twofa_ok
        and not paper and result_mode == "ready_after_approval"
    )

    out = {
        "ok": ok_out,
        "mode": result_mode,
        "requested_mode": raw_mode,
        "hard_blocks": hard_blocks,
        "operator_required_steps": list(dict.fromkeys(required_operator_steps)),
        "soft_warnings": soft_warnings,
        "informational_gates": informational_gates,
        "final_submit_ready": final_submit_ready,
        # back-compat alias retained for existing callers/tests
        "required_operator_steps": list(dict.fromkeys(required_operator_steps)),
        "gate_results": gate_results,
        "correlation_id": correlation_id,
        "evidence_hash": evidence_hash,
        "readiness_hash": evidence_hash,  # like-to-like key for evidence_approval revalidation
        "generated_at": _iso(),
        "paper_mode": paper,
        "autonomous_live_submit_allowed": False,
    }
    # ``audit`` mode is strictly side-effect-free — no audit-ledger write.
    if mode != "audit":
        try:
            from audit_ledger import record_event
            record_event(
                "readiness_evaluated" if ok_out else "readiness_blocked",
                decision=result_mode,
                reason=hard_blocks[0]["reason"] if hard_blocks else "pass",
                correlation_id=correlation_id,
                component="execution_readiness",
                snapshot={"evidence_hash": evidence_hash, "ok": ok_out, "mode": result_mode,
                          "requested_mode": raw_mode},
            )
        except Exception:
            pass
    return out


def require_ready(intent_or_proposal, **kwargs) -> None:
    """Raise ExecutionBlocked if not ready."""
    from brokers.execution_guard import ExecutionBlocked
    r = evaluate_execution_readiness(intent_or_proposal, **kwargs)
    if not r["ok"]:
        reasons = "; ".join(b["reason"] for b in r["hard_blocks"][:5])
        raise ExecutionBlocked(f"EXECUTION_READINESS BLOCK: {reasons}")