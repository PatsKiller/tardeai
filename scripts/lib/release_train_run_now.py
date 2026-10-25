"""Ops → Controls bridge for a live canary Run now (AGENTS.md 22.0.0 ACTIVE).

Sets ``TrainConfig.forced_confirmed=True`` after an Ops Controls passkey + typed phrase proof, then runs the
controller. Does not edit ``release_train_controller`` (claimed elsewhere): the CLI path stays TTY-only; this module
is the Command Center path, gated by ``policy_state(required="22.0.0", anchor="release_train.run_now")``.

Until 22.0.0 is ACTIVE every plan/apply refuses ``POLICY_NOT_ACTIVE``. Agents never call this; the host applier does.
Market hours (weekday 09:30–16:00 ET) refuse on apply. Phrase: ``RUN NOW EPOCH n WINDOW HHMM``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from scripts.lib.ops_controls_core import (
    POLICY_ACTIVE,
    ApprovalPasskeyHook,
    Hosts,
    OpsError,
    Plan,
    phrase_matches,
    policy_state,
    sha256_text,
    canonical,
)
from scripts.lib.release_train_controller import (
    TRAIN_CONTROLLER_STATUS,
    TrainConfig,
    build_controller,
    forced_canary_policy,
)
from scripts.lib import release_train_window_view as WV

TZ = ZoneInfo("America/New_York")
POLICY_REQUIRED = "22.0.0"
POLICY_ANCHOR = "release_train.run_now"
KIND = "release_train.run_now"
DEFAULT_SLOT = "1800"
SLOT_RE_OK = frozenset(WV.SLOTS)


def policy_gate(agents_path=None) -> dict:
    """ACTIVE only when AGENTS.md has an ACTIVE row at or above 22.0.0 and the Run-now anchor is present."""
    return policy_state(
        agents_path,
        required=POLICY_REQUIRED,
        anchor=POLICY_ANCHOR,
        or_later=True,
    )


def require_policy_active(agents_path=None) -> dict:
    st = policy_gate(agents_path)
    if st["state"] != POLICY_ACTIVE:
        raise OpsError(
            "POLICY_NOT_ACTIVE",
            f"AGENTS.md {POLICY_REQUIRED} is not ACTIVE ({st['detail']}); Run now stays host-CLI only until "
            f"the operator ratifies it",
            409,
        )
    return st


def run_now_phrase(epoch: Optional[int], slot: str) -> str:
    return f"RUN NOW EPOCH {int(epoch or 0)} WINDOW {slot}"


def market_hours_open(now: Optional[datetime] = None) -> bool:
    """True during weekday 09:30–16:00 America/New_York (regular market hours). Forced live runs refuse then."""
    now = now or datetime.now(TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    local = now.astimezone(TZ)
    if local.weekday() >= 5:
        return False
    mins = local.hour * 60 + local.minute
    return (9 * 60 + 30) <= mins < (16 * 60)


def readiness(*, hosts: Optional[Hosts] = None, agents_path=None, now: Optional[datetime] = None) -> dict:
    """What the Ops / Release-train surfaces show for Run now. Never mutates."""
    st = policy_gate(agents_path)
    pol = forced_canary_policy()
    epoch = None
    mode = None
    latch = None
    try:
        from scripts.lib import release_control as RC

        if hosts is not None:
            v = RC.ReleaseControl(hosts.release_dir).view()
            epoch, mode, latch = v.epoch, v.mode, v.latch_state
    except Exception as exc:  # noqa: BLE001 — readiness never raises
        return {
            "kind": KIND,
            "policy": st,
            "allowed": False,
            "block_reason": f"release control unreadable: {type(exc).__name__}",
            "controller_status": TRAIN_CONTROLLER_STATUS,
            "canary_force_allowed": bool(pol.get("operator_forced_off_window")),
            "slots": list(pol.get("slots") or []),
            "default_slot": DEFAULT_SLOT if DEFAULT_SLOT in (pol.get("slots") or []) else (
                (pol.get("slots") or [None])[0]),
            "epoch": None,
            "mode": None,
            "latch": None,
            "phrase_example": run_now_phrase(0, DEFAULT_SLOT),
            "market_hours_open": market_hours_open(now),
        }
    reasons: list[str] = []
    if st["state"] != POLICY_ACTIVE:
        reasons.append(f"POLICY_NOT_ACTIVE: {st['detail']}")
    if TRAIN_CONTROLLER_STATUS != "ACTIVE":
        reasons.append(f"controller is {TRAIN_CONTROLLER_STATUS}")
    if not pol.get("operator_forced_off_window") or not pol.get("slots"):
        reasons.append("canary.operator_forced_off_window is off or has no slots")
    if market_hours_open(now):
        reasons.append("regular market hours (09:30–16:00 ET); force after the close")
    slot = DEFAULT_SLOT if DEFAULT_SLOT in (pol.get("slots") or []) else ((pol.get("slots") or [DEFAULT_SLOT])[0])
    return {
        "kind": KIND,
        "policy": st,
        "allowed": not reasons,
        "block_reason": "; ".join(reasons) if reasons else None,
        "controller_status": TRAIN_CONTROLLER_STATUS,
        "canary_force_allowed": bool(pol.get("operator_forced_off_window")),
        "slots": list(pol.get("slots") or []),
        "default_slot": slot,
        "epoch": epoch,
        "mode": mode,
        "latch": latch,
        "phrase_example": run_now_phrase(epoch, slot),
        "market_hours_open": market_hours_open(now),
    }


def _slot(p: Mapping[str, Any], pol: dict) -> str:
    raw = str(p.get("force_window") or p.get("window") or "").strip()
    if not raw:
        slots = pol.get("slots") or []
        raw = DEFAULT_SLOT if DEFAULT_SLOT in slots else (slots[0] if slots else "")
    if raw not in SLOT_RE_OK:
        raise OpsError("PARAMS_INVALID", f"force_window must be a known slot ({', '.join(sorted(SLOT_RE_OK))})", 400)
    if raw not in (pol.get("slots") or []):
        raise OpsError("FORCE_NOT_ALLOWED", f"slot {raw} is not in canary.operator_forced_off_window slots", 409)
    return raw


def _forced_n(p: Mapping[str, Any]) -> int:
    raw = p.get("forced_n", 1)
    try:
        n = int(raw)
    except (TypeError, ValueError) as exc:
        raise OpsError("PARAMS_INVALID", "forced_n must be an integer 1..999", 400) from exc
    if isinstance(raw, bool) or not (1 <= n <= 999):
        raise OpsError("PARAMS_INVALID", "forced_n must be an integer 1..999", 400)
    return n


def _reason(p: Mapping[str, Any]) -> str:
    reason = " ".join(str(p.get("reason") or p.get("operator_ref") or "").split())
    if len(reason) < 4 or len(reason) > 400 or any(ord(c) < 32 for c in reason):
        raise OpsError("PARAMS_INVALID", "reason must be 4-400 printable characters (it is recorded)", 400)
    return reason


def plan(params: Mapping[str, Any], hosts: Hosts, *, request_id: str, agents_path=None) -> Plan:
    """Dry-run preview. Refuses POLICY_NOT_ACTIVE; market hours warn but still preview."""
    require_policy_active(agents_path)
    p = dict(params or {})
    pol = forced_canary_policy()
    if not pol.get("operator_forced_off_window") or not pol.get("slots"):
        raise OpsError("FORCE_NOT_ALLOWED", "canary.operator_forced_off_window is off or has no slots", 409)
    if TRAIN_CONTROLLER_STATUS != "ACTIVE":
        raise OpsError("CONTROLLER_BUILD_ONLY", f"TRAIN_CONTROLLER_STATUS={TRAIN_CONTROLLER_STATUS}", 409)
    slot = _slot(p, pol)
    n = _forced_n(p)
    reason = _reason(p)
    from scripts.lib import release_control as RC

    ctl = RC.ReleaseControl(hosts.release_dir)
    v = ctl.view()
    phrase = run_now_phrase(v.epoch, slot)
    warnings: list[str] = [
        "every other §25.3 gate still applies (canary phase, capability, lock, STOP, merge freeze, CI on SHA)",
        "agents never force; this is an operator act with a fresh passkey",
    ]
    if market_hours_open(hosts.clock()):
        warnings.append("APPLY will refuse during regular market hours (09:30–16:00 ET)")
    before = {"mode": v.mode, "epoch": v.epoch, "latch": v.latch_state, "slot": slot, "forced_n": n}
    digest = sha256_text(canonical({
        "mode": v.mode, "epoch": v.epoch, "latch": v.latch_state, "slot": slot, "forced_n": n,
    }))
    return Plan(
        KIND,
        {"reason": reason, "force_window": slot, "forced_n": n, "operator_ref": reason},
        f"force live canary Run now: window {slot} run {n}, epoch {v.epoch} (OPERATOR_FORCED_LIVE)",
        before,
        {"forced": True, "slot": slot, "forced_n": n},
        digest,
        diff=[f"+ force live window {slot} run {n} (ops-controls {request_id})"],
        warnings=warnings,
        undo=None,
        undo_reason="a forced run cannot be undone; STOP latches the train if it is in flight",
        phrase=phrase,
        payload={"force_window": slot, "forced_n": n, "operator_ref": reason, "epoch": v.epoch},
    )


def apply(
    plan_obj: Plan,
    hosts: Hosts,
    *,
    request_id: str,
    actor: str,
    approval: Optional[dict],
    hmac_key: Optional[bytes],
    agents_path=None,
    res: Optional[dict] = None,
) -> dict:
    """Live force after passkey proof. Sets forced_confirmed=True; never reaches the CLI TTY path."""
    from scripts.lib import release_control as RC

    require_policy_active(agents_path)
    if market_hours_open(hosts.clock()):
        raise OpsError(
            "MARKET_HOURS",
            "a live forced run never starts during regular market hours (09:30–16:00 ET)",
            409,
        )
    if not approval or approval.get("request_id") != request_id:
        raise OpsError("PROOF_MISSING", "release_train.run_now is applied only from a signed approval", 409)
    # Recompute phrase from live control so a stale preview cannot force after an epoch bump.
    v = RC.ReleaseControl(hosts.release_dir).view()
    slot = str(plan_obj.payload["force_window"])
    expected = run_now_phrase(v.epoch, slot)
    if not phrase_matches(plan_obj.phrase, expected):
        raise OpsError("STATE_CHANGED", "the release-train epoch changed since the preview; preview again", 409)
    hook = ApprovalPasskeyHook(approval, hmac_key, KIND)
    proof = RC.PasskeyProof(
        request_id=request_id,
        credential_id=str(approval.get("stepup_credential_id") or ""),
        approved_at=str(approval.get("approved_at") or ""),
        confirmation=" ".join(str(approval.get("phrase") or "").split()),
    )
    if not hook.verify(proof, command="run_now", expected_phrase=expected):
        raise OpsError("PROOF_REFUSED", "passkey approval does not match release_train.run_now", 409)

    n = int(plan_obj.payload["forced_n"])
    ref = f"{plan_obj.params['reason']} (ops-controls {request_id})"
    cfg = TrainConfig(
        force_window=slot,
        forced_n=n,
        operator_ref=ref[:120],
        forced_confirmed=True,
    )
    out: dict[str, Any] = res if res is not None else {
        "kind": KIND, "summary": plan_obj.summary, "undo": None, "undo_reason": plan_obj.undo_reason,
    }
    try:
        ctl = build_controller(live=True, config=cfg)
        rec = ctl.run()
    except Exception as exc:  # noqa: BLE001 — surface as FAILED with detail
        out["verify"] = {"error": type(exc).__name__, "detail": str(exc)[:300]}
        out["outcome"] = "FAILED"
        out["detail"] = str(exc)[:300]
        out["code"] = getattr(exc, "code", None) or type(exc).__name__
        return out
    forced = (rec or {}).get("forced") if isinstance(rec, dict) else None
    outcome = (rec or {}).get("outcome") if isinstance(rec, dict) else None
    ok = isinstance(forced, dict) and forced.get("forced_by") == "operator"
    out["verify"] = {
        "forced": forced,
        "outcome": outcome,
        "controller_status": TRAIN_CONTROLLER_STATUS,
        "actor": actor,
        "epoch": v.epoch,
    }
    out["outcome"] = "APPLIED" if ok else "FAILED"
    out["detail"] = (forced or {}).get("forced_key") if isinstance(forced, dict) else outcome
    return out
