"""Route a T1 recovery case to the operator as a P1 page — and never let it be suppressed.

Why this module exists (operator directive 2026-11-03, SPEC_RECOVERY_REENTRY_ENGINE_20261103.md §3.3):
Recovery Watch found re-entry candidates (SCHG/BAH/RTX every run since 2026-10-01) and sent them
with ``priority="P2"``; the router classified them ``P2_DASHBOARD_ONLY`` and the publish path reported
``LEGACY_SHADOWED``. The operator never saw that SPCX — his largest stop-out — was recovering. A
notification that can be suppressed is not a notification.

Policy
------
* **T1 only.** ``resolve_tier`` reads the tier from the recovery case; when the case carries no tier it
  derives one from the case's realized loss / pre-exit weight against ``config/recovery_policy.yaml``.
  Thresholds are NEVER hard-coded here — they live in config (operator decision, §6.1). If the config
  or the case numbers are unavailable, the tier resolves **T1**: an unknown materiality must not be
  quieter than a known one.
* **P1, never P2.** The message is sent with ``priority="P1"``. The router's ``route_intent`` delivers
  every P1 (no quiet-hours hold, no digest fold). The message also carries ``RECOVERY_T1_MARKER`` so the
  legacy message classifier (``telegram_alert_router.classify_alert``) short-circuits to a page before
  any P2 pattern can match.
* **One batching mechanism when present.** If ``lib.telegram_batch`` is importable (it lands on its own
  branch), the message goes through ``batch_text`` + ``nudge_decision`` with the 2 h repeat floor. The
  import is LAZY and FAIL-OPEN: a missing module falls back to the direct P1 send, because loudness
  matters more than batching. Both paths return ``suppressed: False``; there is no code path in this
  module that emits a P2 intent for a T1 case.

No write to the broker, no credential, no order: this module only builds and sends an operator message.
"""
from __future__ import annotations

import base64
import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
POLICY_REL = Path("config") / "recovery_policy.yaml"
NUDGE_STATE_REL = Path("data") / "portfolios" / "state" / "recovery_nudge_state.json"

#: Placed on the first line of every T1 recovery page. ``telegram_alert_router.classify_alert``
#: recognises it and returns a page classification before any P2 rule can run.
RECOVERY_T1_MARKER = "[[RECOVERY_T1]]"

TIERS = ("T1", "T2", "T3")
PRIORITY_P1 = "P1"
DEFAULT_REPEAT_FLOOR_MINUTES = 120


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_policy(path: Path | str | None = None) -> dict:
    """The recovery policy document, or ``{}``. Never raises: a missing/malformed policy is handled by
    the loud T1 default in :func:`resolve_tier`, not by a crash."""
    p = Path(path) if path else PROJECT_ROOT / POLICY_REL
    try:
        raw = p.read_text(encoding="utf-8")
    except (OSError, ValueError):
        # ValueError covers UnicodeDecodeError: a damaged policy encoding is "no policy", which the
        # loud T1 default in resolve_tier handles — never an exception before the page.
        return {}
    try:
        import yaml  # type: ignore

        doc = yaml.safe_load(raw)
    except Exception:  # noqa: BLE001 — no yaml, or malformed: try JSON, else {}
        try:
            doc = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return doc if isinstance(doc, dict) else {}


def _finite(value: Any) -> Optional[float]:
    """A usable finite number, or None. NaN/inf/huge integers are NOT numbers for materiality."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _raw_threshold_present(policy: dict, key: str) -> bool:
    """Whether the policy CONFIGURES a threshold for this dimension — even as null.

    A present-but-null threshold is not an absent one (cx-openai-2 F2): it means the operator has
    configured the dimension without a usable number, which must resolve loud, not delete the check.
    """
    try:
        materiality = policy.get("materiality", {})
        tiers = policy.get("tiers", {})
        if isinstance(materiality, dict) and isinstance(materiality.get("t1"), dict) and key in materiality["t1"]:
            return True
        if isinstance(tiers, dict) and isinstance(tiers.get("T1"), dict) and key in tiers["T1"]:
            return True
        return f"materiality_t1_{key}" in policy
    except (AttributeError, TypeError):
        return False


def _threshold(policy: dict, key: str) -> Optional[float]:
    """Read one T1 threshold from any of the shapes the policy may use, never a built-in number.

    Accepted (first present wins): ``materiality.t1.<key>``, ``tiers.T1.<key>``,
    ``materiality_t1_<key>``. ``None`` means "the policy does not tell us" and the caller goes loud.
    A non-finite configured value (NaN/inf) is unusable and treated the same as absent.
    """
    candidates = []
    try:
        candidates.append(policy.get("materiality", {}).get("t1", {}).get(key))
        candidates.append(policy.get("tiers", {}).get("T1", {}).get(key))
        candidates.append(policy.get(f"materiality_t1_{key}"))
    except (AttributeError, TypeError):
        pass
    for value in candidates:
        number = _finite(value)
        if number is not None and number > 0:
            return number
    return None


def resolve_tier(case: dict, *, policy: Optional[dict] = None) -> tuple[str, str]:
    """``(tier, why)`` for a recovery case. Unknown materiality resolves T1, deliberately.

    The case's own ``materiality_tier`` wins when present (piece A computes it). Otherwise the tier is
    derived from ``realized_loss_usd`` / ``pre_exit_weight_pct`` against the config thresholds. A
    missing policy, a non-finite fact, or an UNKNOWN dimension resolves T1: a below-threshold reading on
    one axis cannot downgrade a case whose other axis is unknown (cx-openai-2 F2).
    """
    if not isinstance(case, dict):
        return "T1", "case is not an object; materiality unknown"
    declared = str(case.get("materiality_tier") or "").strip().upper()
    if declared in TIERS:
        return declared, "tier declared on the case"
    # Common alternative spellings on the event row.
    for key in ("tier", "materiality"):
        alt = str(case.get(key) or "").strip().upper()
        if alt in TIERS:
            return alt, f"tier in {key}"
    loss_raw = case.get("realized_loss_usd", case.get("realized_pnl", case.get("realized")))
    weight_raw = case.get("pre_exit_weight_pct", case.get("weight_pct"))
    loss = _finite(loss_raw) if loss_raw is not None else None
    weight = _finite(weight_raw) if weight_raw is not None else None
    loss = abs(loss) if loss is not None else None
    weight = abs(weight) if weight is not None else None
    if loss is None and weight is None:
        return "T1", "no tier and no finite materiality numbers; unknown resolves loud"
    pol = load_policy() if policy is None else policy
    if not isinstance(pol, dict) or not pol:
        return "T1", "no recovery policy available; unknown resolves loud"
    t1_loss = _threshold(pol, "loss_usd")
    t1_weight = _threshold(pol, "weight_pct")
    if t1_loss is None and t1_weight is None:
        return "T1", "policy carries no usable T1 thresholds; unknown resolves loud"
    # A threshold that the policy DOES provide but that is unusable (inf/NaN) must not silently
    # delete that dimension from the comparison (cx-openai-2 F2 remainder): a finite fact against a
    # deleted dimension is unknown, and unknown is loud.
    if (_raw_threshold_present(pol, "loss_usd") and t1_loss is None) or (
            _raw_threshold_present(pol, "weight_pct") and t1_weight is None):
        return "T1", "a configured T1 threshold is unusable; unknown resolves loud"
    if t1_loss is not None and loss is not None and loss >= t1_loss:
        return "T1", f"realized loss {loss:,.0f} >= config t1_loss_usd {t1_loss:,.0f}"
    if t1_weight is not None and weight is not None and weight >= t1_weight:
        return "T1", f"pre-exit weight {weight:.2f}% >= config t1_weight_pct {t1_weight:.2f}"
    required = []
    if t1_loss is not None:
        required.append(("realized loss", loss))
    if t1_weight is not None:
        required.append(("pre-exit weight", weight))
    unknown = [name for name, value in required if value is None]
    if unknown:
        # A known dimension below threshold cannot make an UNKNOWN one quiet (F2).
        return "T1", f"T1 dimension unknown or non-finite: {', '.join(unknown)}; unknown resolves loud"
    return "T2", "below the configured T1 thresholds"


def _money(value: Any) -> str:
    number = _finite(value)
    return "unknown" if number is None else f"${number:,.0f}"


def _pct(value: Any) -> str:
    number = _finite(value)
    return "unknown" if number is None else f"{number:+.1f}%"


def case_key_for(case: dict) -> str:
    """The stable identity of a recovery case: case id, else symbol+ACCOUNT+exit cluster.

    The account is part of the identity: two accounts recovering the same symbol are two cases and
    must each be able to page (cx-openai-2 F3 — a key without account merged them).
    """
    symbol = str(case.get("symbol") or "UNKNOWN").upper()
    account = str(case.get("account") or case.get("account_key") or case.get("account_id") or "account?")
    cluster = case.get("exit_date") or case.get("exit_cluster") or case.get("state") or "exit?"
    return str(case.get("case_id") or case.get("case_key") or f"{symbol}:{account}:{cluster}")


def case_token_for(case_key: str) -> str:
    """A lossless, URL/base64-safe wire form of the case key.

    The message is parsed back by the router; a plain-id regex truncates anything outside its
    character class, and two ids that differ only in those characters would collide. ``v1:`` +
    url-safe base64 round-trips ANY key (cx-openai-2 F3, encoding half).
    """
    raw = base64.urlsafe_b64encode(str(case_key).encode("utf-8")).decode("ascii").rstrip("=")
    return "v1:" + raw


def parse_case_token(text: str) -> Optional[str]:
    """The case key carried by a recovery message, or None. Handles v1 tokens and legacy plain ids."""
    match = re.search(r"case:(v1:)?([A-Za-z0-9_=-]+)", text or "")
    if not match:
        return None
    body = match.group(2)
    if not match.group(1):
        return body
    try:
        padded = body + "=" * (-len(body) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeError):
        return None


def build_message(case: dict) -> str:
    """The operator page. First line carries the marker and the stable case key."""
    sym = str(case.get("symbol") or "UNKNOWN").upper()
    case_key = case_key_for(case)
    price = case.get("price", case.get("current_price"))
    exit_price = case.get("exit_price", case.get("avg_exit_price"))
    vs_exit = case.get("pct_vs_exit")
    lines = [f"{RECOVERY_T1_MARKER} Recovery: {sym} · case:{case_token_for(case_key)}"]
    facts = []
    if price is not None:
        facts.append(f"now {_money(price)}")
    if exit_price is not None:
        facts.append(f"exit {_money(exit_price)}")
    if vs_exit is not None:
        facts.append(f"vs exit {_pct(vs_exit)}")
    if facts:
        lines.append(" · ".join(facts))
    if case.get("state") or case.get("verdict"):
        state = case.get("state") or case.get("verdict")
        conf = case.get("confidence")
        lines.append(f"State: {state}" + (f" ({_pct(conf)} confidence)" if conf is not None else ""))
    trigger = case.get("next_trigger") or case.get("trigger")
    if trigger:
        lines.append(f"Next trigger: {trigger}")
    if case.get("eligibility"):
        lines.append(f"Eligible: {case['eligibility']}")
    plan = case.get("plan") or case.get("summary")
    if plan:
        lines.append(f"Plan: {plan}")
    if case.get("size_to_restore"):
        lines.append(f"Size to restore: {case['size_to_restore']}")
    if case.get("realized_loss_usd") is not None:
        lines.append(f"Realized loss at exit: {_money(case.get('realized_loss_usd'))}")
    lines.append("No order is placed. Open Home to plan, watch, snooze or close the case.")
    return "\n".join(lines)


def _default_sender():
    def _send(message: str, *, priority: str = PRIORITY_P1, **kwargs):
        from telegram_alert import send_telegram  # noqa: PLC0415 — lazy, keeps import cost out

        # An explicit `priority=` keyword (never a **kwargs passthrough) so the notification-intent
        # ratchet can see that this producer declares its priority (AGENTS.md §24.1).
        return send_telegram(message, priority=priority, **kwargs)

    return _send


def notify_recovery_case(case: dict, *, policy: Optional[dict] = None,
                         sender: Optional[Callable[..., Any]] = None,
                         now: Optional[datetime] = None,
                         state_path: Path | str | None = None,
                         floor_minutes: int = DEFAULT_REPEAT_FLOOR_MINUTES) -> dict:
    """Send a T1 recovery page. Returns a result that always carries ``suppressed: False``.

    T2/T3 cases are not paged here (Home card / digest); the result says so and carries no P1.
    """
    now = now or _utcnow()
    tier, why = resolve_tier(case, policy=policy)
    result: dict[str, Any] = {"tier": tier, "tier_reason": why, "priority": None, "sent": False,
                              "path": None, "suppressed": False, "message": None}
    if tier != "T1":
        result["reason"] = f"not T1 ({why}); Home card / digest handles {tier}"
        return result

    message = build_message(case)
    result["message"] = message
    result["priority"] = PRIORITY_P1  # a T1 case is a page, in every branch below
    send = sender or _default_sender()
    symbol = str(case.get("symbol") or "UNKNOWN").upper()
    key = f"recovery:{case_key_for(case)}:T1:{case.get('state') or 'unknown'}"

    # Lazy, fail-open batching: the v008 batching module may not be on this checkout yet.
    try:
        from lib.telegram_batch import NudgeState, batch_text, nudge_decision  # noqa: PLC0415

        state = NudgeState(state_path or PROJECT_ROOT / NUDGE_STATE_REL)
        decision = nudge_decision(keys=[key], state=state, now=now,
                                  priority=PRIORITY_P1, floor_minutes=floor_minutes)
        if not decision.get("send"):
            # A negative decision is a genuine repeat floor ONLY when our own ledger says this key is
            # not yet due. Quiet-hours or an unknown no-send from a broken/other module must never be
            # read as "already paged" (cx-openai-2 F3) — fall through to the direct P1 send instead.
            if not state.due([key], now, floor_minutes):
                log.warning("recovery T1 page held by the verified repeat floor for %s: %s",
                            symbol, decision.get("reason"))
                result.update({"path": "batch", "reason": f"repeat floor: {decision.get('reason')}",
                               "deduped_by_floor": True})
                return result
            log.warning("batch declined a T1 for a non-floor reason (%s); using the direct P1 send for %s",
                        decision.get("reason"), symbol)
        else:
            body = batch_text(header=f"{RECOVERY_T1_MARKER} Recovery · case:{case_token_for(case_key_for(case))}", items=[
                {"title": f"{symbol} is recovering", "detail": message.split("\n", 1)[1].strip() if "\n" in message else "",
                 "next": "Open Home to plan re-entry"}])
            ok = send(body, priority=PRIORITY_P1, dedupe_minutes=0, producer="recovery_notify")
            result.update({"path": "batch", "sent": bool(ok)})
            if ok:
                state.save(state.note([key], now))
            else:
                log.warning("recovery T1 page was not accepted by the transport for %s", symbol)
            return result
    except Exception:  # noqa: BLE001 — any batching problem must not silence a T1 page
        pass

    ok = send(message, priority=PRIORITY_P1, dedupe_minutes=floor_minutes, producer="recovery_notify")
    result.update({"path": "direct", "sent": bool(ok)})
    if not ok:
        log.warning("recovery T1 page was not accepted by the direct transport for %s", symbol)
    return result


__all__ = ["RECOVERY_T1_MARKER", "TIERS", "DEFAULT_REPEAT_FLOOR_MINUTES",
           "load_policy", "resolve_tier", "build_message", "notify_recovery_case"]
