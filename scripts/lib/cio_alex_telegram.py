"""cio_alex_telegram.py — Phase 9 Alex Telegram product behavior.

Alex pages the operator like a CIO, not a log stream:

  material InvestmentDecision / CIO NOW card
    → materiality test
    → semantic dedupe on decision_id + material state
    → governed CIO-only transport (never general Telegram)
    → optional DEFER lineage for durable revisit

Non-material events update internal state only — no Telegram.

Live canary is dual-gated:
  AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1
  AND CIO_TELEGRAM_CANARY_APPROVAL=<exact approval phrase>
  AND not under pytest / interdict

Without that approval, prepare_canary_package() is the only path — zero sends.

Authority: READ_ONLY_ADVISORY. No broker / order / stop / 2FA.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib import cio_telegram_transport as tg

ALEX_TELEGRAM_VERSION = "alex_telegram_1.0.0"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEFER_PATH = PROJECT_ROOT / "data" / "cio" / "cio_defer_lineage.jsonl"
DEFAULT_RECEIPT_PATH = PROJECT_ROOT / "data" / "cio" / "cio_telegram_receipts.jsonl"

# Exact phrase required for a real canary send (in addition to P2 live auth).
CANARY_APPROVAL_PHRASE = "I_APPROVE_CIO_CANARY_SEND"
ENV_CANARY_APPROVAL = "CIO_TELEGRAM_CANARY_APPROVAL"
ENV_CANARY_ENABLED = "CIO_TELEGRAM_CANARY_ENABLE"  # must be 1 as well

# Non-material noise classes (never Telegram)
NON_MATERIAL_KINDS = frozenset({
    "thesis_version",
    "thesis_bump",
    "heartbeat",
    "health_ping",
    "log_line",
    "state_tick",
    "watch_noise",
    "fixture",
})


def _env(k: str, default: str = "") -> str:
    return (os.environ.get(k) or default).strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _num(v: Any) -> float:
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _defer_path() -> Path:
    return Path(_env("CIO_DEFER_LINEAGE_PATH", str(DEFAULT_DEFER_PATH)))


def _receipt_path() -> Path:
    return Path(_env("CIO_TELEGRAM_RECEIPT_PATH", str(DEFAULT_RECEIPT_PATH)))


# ─────────────────────────────────────────────────────────────────────────────
# 9.1 Materiality + CIO-speak body
# ─────────────────────────────────────────────────────────────────────────────

def is_material_event(
    *,
    kind: str = "decision",
    decision: Optional[dict[str, Any]] = None,
    body: str = "",
) -> dict[str, Any]:
    """Material backend event → may page; else internal state only."""
    k = (kind or "").lower().strip()
    if k in NON_MATERIAL_KINDS:
        return {"material": False, "reason": f"kind_non_material:{k}"}
    if k in ("thesis", "thesis_publish", "thesis_version"):
        # Thesis proactive remains off unless explicitly material + flag (Phase 1)
        if not tg.thesis_notify_enabled():
            return {"material": False, "reason": "thesis_telegram_disabled_default"}
        if not tg.is_material_thesis_summary(body or (decision or {}).get("why_now") or ""):
            return {"material": False, "reason": "thesis_not_material"}
        return {"material": True, "reason": "thesis_material_enabled"}

    d = decision or {}
    if d:
        # Require a decision_id (Phase 8) and a real operator-facing action
        did = str(d.get("decision_id") or "").strip()
        if not did:
            return {"material": False, "reason": "missing_decision_id"}
        action = str(d.get("action") or d.get("stance") or d.get("stance_code") or "").upper()
        if action in ("", "HOLD", "ACTION") and abs(_num(d.get("delta_usd") or d.get("recommended_delta_usd"))) < 0.01:
            why = str(d.get("why_now") or "")
            if "concentration" not in why.lower() and "breach" not in str(d.get("risk") or "").lower():
                return {"material": False, "reason": "hold_without_material_signal"}
        why = str(d.get("why_now") or "").strip()
        if len(why) < 12 and abs(_num(d.get("delta_usd") or d.get("recommended_delta_usd"))) < 1:
            return {"material": False, "reason": "thin_why_and_delta"}
        return {"material": True, "reason": "material_decision"}

    # Free-form body path
    if len((body or "").strip()) < 40:
        return {"material": False, "reason": "body_too_short"}
    return {"material": True, "reason": "material_body"}


def format_cio_message(decision: dict[str, Any]) -> str:
    """Decision-first CIO card. Buttons are inline, not plaintext actions."""
    sym = decision.get("symbol") or decision.get("scope") or "—"
    action = decision.get("action") or decision.get("stance") or "Review"
    delta = _num(decision.get("delta_usd") if decision.get("delta_usd") is not None
                 else decision.get("recommended_delta_usd"))
    why = (decision.get("why_now") or decision.get("what_changed") or "").strip()
    counter = (decision.get("counter_thesis") or "").strip()
    change = (decision.get("what_changes_call") or "").strip()
    nxt = decision.get("next_review") or "—"
    cash = decision.get("capital") if isinstance(decision.get("capital"), dict) else {}
    free = cash.get("free_investable")
    deploy = cash.get("deploy_now")
    remain = cash.get("remain_cash")

    lines = [
        "Alex · CIO NOW",
        "",
        "WHAT CHANGED",
        why[:280] or f"{action} {sym}",
        "",
        "MY CALL",
        f"{action} {sym}" + (f"  ${delta:+,.0f}" if abs(delta) >= 1 else ""),
        "",
        "CAPITAL",
        f"Free investable: ${float(free):,.0f}" if free is not None else "Free investable: see capital plan",
        f"Deploy now: ${float(deploy):,.0f}" if deploy is not None else "Deploy now: —",
        f"Remain cash: ${float(remain):,.0f}" if remain is not None else "Remain cash: —",
        "",
        "WHY",
        why[:240] or "See evidence in CIO.",
        "",
        "COUNTER-THESIS",
        (counter[:200] if counter else "None on record."),
        "",
        "WHAT CHANGES MY MIND",
        change[:200] or "Material new multi-desk evidence or cash-band breach.",
        "",
        "NEXT REVIEW",
        str(nxt),
        "",
        f"Decision: {decision.get('decision_id') or '—'}",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 9.2 Semantic dedupe on decision_id + material state
# ─────────────────────────────────────────────────────────────────────────────

def material_state_fingerprint(decision: dict[str, Any]) -> str:
    """State that makes a re-send legitimate when it changes."""
    body = {
        "decision_id": str(decision.get("decision_id") or ""),
        "stance": str(decision.get("stance_code") or decision.get("action") or "").upper(),
        "delta": round(_num(decision.get("delta_usd") if decision.get("delta_usd") is not None
                            else decision.get("recommended_delta_usd")), 2),
        "urgency": str(decision.get("urgency") or ""),
        "status": str(decision.get("status") or decision.get("lifecycle") or "open"),
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def decision_dedupe_key(decision: dict[str, Any]) -> str:
    """Dedupe: decision_id + input digest + evidence digest + material state."""
    did = str(decision.get("decision_id") or "none")
    inp = str(decision.get("decision_input_digest") or "")
    evd = str(decision.get("decision_evidence_digest") or "")
    state = material_state_fingerprint(decision)
    return hashlib.sha256(f"alex_dec|{did}|{inp}|{evd}|{state}".encode()).hexdigest()[:32]


def would_duplicate(decision: dict[str, Any]) -> bool:
    return tg.was_recently_sent(decision_dedupe_key(decision))


# ─────────────────────────────────────────────────────────────────────────────
# 9.3 DEFER lineage
# ─────────────────────────────────────────────────────────────────────────────

def record_defer(
    decision: dict[str, Any],
    *,
    revisit_at: Optional[datetime] = None,
    days: int = 7,
    reason: str = "operator_defer",
) -> dict[str, Any]:
    """Durable DEFER: same decision_id lineage reopens on trigger — not new spam."""
    did = str(decision.get("decision_id") or "").strip()
    if not did:
        return {"ok": False, "reason": "missing_decision_id"}
    when = revisit_at or (_now() + timedelta(days=max(1, int(days))))
    rec = {
        "lineage_id": "lin_" + hashlib.sha256(
            f"{did}|{when.isoformat()}|{reason}".encode()
        ).hexdigest()[:16],
        "decision_id": did,
        "symbol": decision.get("symbol"),
        "action": decision.get("action") or decision.get("stance"),
        "material_state": material_state_fingerprint(decision),
        "deferred_at": _now().isoformat(),
        "revisit_at": when.isoformat() if when.tzinfo else when.replace(tzinfo=timezone.utc).isoformat(),
        "reason": reason,
        "status": "deferred",
        "parent_decision_id": did,
        "version": ALEX_TELEGRAM_VERSION,
    }
    path = _defer_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return {"ok": True, **rec}


def list_defer_lineage(*, limit: int = 200) -> list[dict[str, Any]]:
    path = _defer_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def due_defers(now: Optional[datetime] = None) -> list[dict[str, Any]]:
    """Deferred lineages whose revisit_at is due and not yet reopened."""
    now = now or _now()
    due: list[dict[str, Any]] = []
    seen_open: set[str] = set()
    for rec in list_defer_lineage():
        if rec.get("status") not in ("deferred", "open"):
            continue
        try:
            rev = datetime.fromisoformat(str(rec.get("revisit_at")).replace("Z", "+00:00"))
        except Exception:
            continue
        if rev.tzinfo is None:
            rev = rev.replace(tzinfo=timezone.utc)
        if rev <= now and rec.get("decision_id") not in seen_open:
            due.append(rec)
            seen_open.add(str(rec.get("decision_id")))
    return due


def reopen_deferred(lineage: dict[str, Any], decision: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Reopen the same decision lineage for Alex — preserves decision_id."""
    did = lineage.get("decision_id")
    base = dict(decision or {})
    base["decision_id"] = did
    base.setdefault("symbol", lineage.get("symbol"))
    base.setdefault("action", lineage.get("action"))
    base["status"] = "reopened"
    base["lifecycle"] = "reopened_from_defer"
    base["lineage_id"] = lineage.get("lineage_id")
    base["parent_decision_id"] = lineage.get("parent_decision_id") or did
    base["why_now"] = base.get("why_now") or (
        f"Deferred review due ({lineage.get('reason') or 'operator_defer'})."
    )
    # Mark lineage consumed
    path = _defer_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    closed = {
        **lineage,
        "status": "reopened",
        "reopened_at": _now().isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(closed, default=str) + "\n")
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Outbound path (shadow by default)
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_outbound(
    decision: dict[str, Any],
    *,
    kind: str = "decision",
) -> dict[str, Any]:
    """Full product evaluation without sending."""
    mat = is_material_event(kind=kind, decision=decision)
    body = format_cio_message(decision) if decision else ""
    dkey = decision_dedupe_key(decision) if decision.get("decision_id") else tg.semantic_body_key(body)
    dup = tg.was_recently_sent(dkey)
    return {
        "version": ALEX_TELEGRAM_VERSION,
        "material": mat["material"],
        "material_reason": mat["reason"],
        "body": body,
        "dedupe_key": dkey,
        "would_duplicate": dup,
        "decision_id": decision.get("decision_id"),
        "channel": "telegram_cio_only",
        "general_channel_eligible": False,
        "would_send": bool(mat["material"] and not dup),
    }


def deliver_decision(
    decision: dict[str, Any],
    *,
    kind: str = "decision",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Deliver a decision message via CIO transport (dry_run default).

    dry_run=True or interdict/pytest → never HTTP.
    """
    ev = evaluate_outbound(decision, kind=kind)
    out = {
        **ev,
        "delivered": False,
        "dry_run": dry_run,
        "receipt": None,
    }
    if not ev["material"]:
        out["reason"] = ev["material_reason"]
        return out
    if ev["would_duplicate"]:
        out["reason"] = "semantic_dedupe_decision_state"
        out["deduped"] = True
        return out
    if dry_run or tg.network_interdicted() or not tg.live_authorized():
        out["reason"] = "dry_run_or_interdicted"
        # Still mark dry-run as if we would send — do NOT mark_sent unless real send
        return out

    markup = None
    try:
        from scripts.lib.cio_telegram_keyboard import build_decision_inline_keyboard
        markup = build_decision_inline_keyboard(decision)
    except Exception:
        markup = None
    res = tg.send_cio_message(
        ev["body"],
        kind="alex_decision",
        require_live_auth=True,
        reply_markup=markup,
        decision_id=str(decision.get("decision_id") or "") or None,
        dedupe_key=ev.get("dedupe_key"),
    )
    # Prefer decision-state key for future dedupe
    if res.get("delivered"):
        tg.mark_sent(ev["dedupe_key"], meta={
            "decision_id": decision.get("decision_id"),
            "kind": "alex_decision",
        })
        receipt = {
            "decision_id": decision.get("decision_id"),
            "dedupe_key": ev["dedupe_key"],
            "delivered_at": _now().isoformat(),
            "message_ids": res.get("message_ids"),
            "channel": "telegram_cio",
            "general_channel": False,
        }
        _append_receipt(receipt)
        out["receipt"] = receipt
    out["delivered"] = bool(res.get("delivered"))
    out["reason"] = res.get("reason")
    out["interdicted"] = res.get("interdicted")
    out["deduped"] = res.get("deduped")
    return out


def _append_receipt(receipt: dict[str, Any]) -> None:
    path = _receipt_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(receipt, default=str) + "\n")
    except OSError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 9.4 Live canary — dual gate, explicit operator approval only
# ─────────────────────────────────────────────────────────────────────────────

def canary_destination_identity() -> dict[str, Any]:
    """Identity of CIO destination without secret values."""
    chats = tg.cio_chat_ids()
    token = tg.cio_bot_token()
    return {
        "bot": "TELEGRAM_CIO_BOT_TOKEN",
        "bot_configured": bool(token),
        "bot_fingerprint": (
            hashlib.sha256(token.encode()).hexdigest()[:12] if token else None
        ),
        "allowlist_env": "TELEGRAM_CIO_CHAT_IDS / TELEGRAM_CIO_ALLOWLIST",
        "allowlist_count": len(chats),
        "allowlist_id_suffixes": [c[-4:] if len(c) >= 4 else "****" for c in chats],
        "general_bot_env_used": False,
        "general_chat_fallback": False,
        "proof_general_not_used": (
            tg.cio_bot_token() != _env("TELEGRAM_BOT_TOKEN")
            or not _env("TELEGRAM_BOT_TOKEN")
        ),
    }


def prepare_canary_package(
    *,
    decision: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build the pre-send canary package for operator review. NEVER sends."""
    d = decision or {
        "decision_id": "dec_canary_phase9_probe",
        "symbol": "CANARY",
        "action": "Review",
        "stance": "Review",
        "stance_code": "HOLD",
        "delta_usd": 0.0,
        "weight_pct": None,
        "why_now": "Phase 9 CIO Telegram canary — materiality and routing probe only.",
        "counter_thesis": "Canary has no portfolio implication.",
        "what_changes_call": "Canary complete; disable canary env flags.",
        "next_review": "n/a",
        "urgency": "low",
        "status": "canary",
    }
    ev = evaluate_outbound(d, kind="canary")
    dest = canary_destination_identity()
    disable = (
        "unset AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY; "
        "unset CIO_TELEGRAM_CANARY_APPROVAL; "
        "unset CIO_TELEGRAM_CANARY_ENABLE; "
        "or set CIO_TELEGRAM_INTERDICT=1"
    )
    return {
        "version": ALEX_TELEGRAM_VERSION,
        "phase": 9,
        "live_send": False,
        "requires_operator_approval": True,
        "approval_phrase_env": ENV_CANARY_APPROVAL,
        "approval_phrase_required": CANARY_APPROVAL_PHRASE,
        "also_requires": [
            "AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1",
            f"{ENV_CANARY_ENABLED}=1",
            "not under pytest",
            "CIO credentials configured",
        ],
        "destination_identity": dest,
        "message_body": ev["body"],
        "why_material": (
            "Canary proves dedicated CIO routing + receipt + dedupe; "
            "not a portfolio recommendation."
        ),
        "dedupe_key": ev["dedupe_key"],
        "decision_id": d.get("decision_id"),
        "rollback_disable_command": disable,
        "proof_general_cannot_receive": {
            "transport_uses_cio_token_only": True,
            "chat_ids_no_TELEGRAM_CHAT_ID_fallback": True,
            "general_token_not_read_by_cio_transport": True,
            "destination": dest,
        },
        "status": "AWAITING_EXPLICIT_OPERATOR_APPROVAL",
        "REAL_TELEGRAM_SENDS": 0,
    }


def canary_approval_granted() -> bool:
    return (
        _env(ENV_CANARY_APPROVAL) == CANARY_APPROVAL_PHRASE
        and _env(ENV_CANARY_ENABLED) in ("1", "true", "yes", "on")
        and tg.live_authorized()
        and not tg.network_interdicted()
    )


def execute_canary_send(
    *,
    decision: Optional[dict[str, Any]] = None,
    force_approve_in_process: bool = False,
) -> dict[str, Any]:
    """Execute canary only when dual env approval is set.

    force_approve_in_process is intentionally IGNORED for real network —
    only env approval counts (prevents accidental tool-call approval).
    """
    pkg = prepare_canary_package(decision=decision)
    if force_approve_in_process:
        # Still blocked — document that in-process force cannot bypass env gate
        return {
            **pkg,
            "delivered": False,
            "reason": "in_process_force_ignored_env_gate_required",
            "REAL_TELEGRAM_SENDS": 0,
        }
    if not canary_approval_granted():
        return {
            **pkg,
            "delivered": False,
            "reason": "canary_approval_not_granted",
            "REAL_TELEGRAM_SENDS": 0,
        }
    # Live path — still uses CIO-only transport
    d = decision or {
        "decision_id": pkg["decision_id"],
        "symbol": "CANARY",
        "action": "Review",
        "why_now": "Phase 9 CIO Telegram canary — materiality and routing probe only.",
        "what_changes_call": "Canary complete.",
        "counter_thesis": "None.",
        "status": "canary",
    }
    res = deliver_decision(d, kind="canary", dry_run=False)
    return {
        **pkg,
        "live_send": True,
        "delivered": res.get("delivered"),
        "reason": res.get("reason"),
        "receipt": res.get("receipt"),
        "REAL_TELEGRAM_SENDS": 1 if res.get("delivered") else 0,
        "GENERAL_TELEGRAM_RECEIVED": False,
    }


def cycle_without_duplicate(decision: dict[str, Any]) -> dict[str, Any]:
    """Run the same unchanged cycle twice → second must dedupe (dry)."""
    first = evaluate_outbound(decision)
    # Simulate first send marked
    if first["would_send"]:
        tg.mark_sent(first["dedupe_key"], meta={"decision_id": decision.get("decision_id")})
    second = evaluate_outbound(decision)
    return {
        "first_would_send": first["would_send"],
        "second_would_send": second["would_send"],
        "second_deduped": second["would_duplicate"],
        "duplicate_suppressed": first["would_send"] and second["would_duplicate"] and not second["would_send"],
        "dedupe_key": first["dedupe_key"],
    }
