"""host_p1_pager.py — the onset / reminder / recovery state machine for host watchers that page P1 without n8n.

Why (AGENTS.md §23.23 "Independence", §23.24 Logging (5) and Alerting (2), §24.1 "The P1 path does not depend on
n8n"; n8n platform hardening packet 2026-10-22, FW-P3 and FW-P6): the n8n workflow-drift watch and the n8n host
dead-man are the two host watchers whose job is to page when n8n is wrong or gone. Neither may page through n8n
(the incident fan-in is an n8n-fired lane), so both page through the SYSTEM ops family —
``scripts/lib/autonomy_watchdog/telegram_system.send_system``, the same host transport the incident notifier and
the autonomy watchdog use (comms editor chokepoint, ops bot, ops chat, SYSTEM_TELEGRAM_ENABLED,
SYSTEM_TELEGRAM_INTERDICT, CI lock). This module only decides; the caller passes the sender.

Decision (pure, ``decide``):

* a bad observation increments ``consecutive_bad``; the first bad one fixes the onset (``bad_since``) and the onset
  key (what is wrong — a drift signature, or "down"). A different key while still bad is a NEW onset.
* at ``consecutive_bad >= threshold`` and no delivered page for this onset → PAGE (identity ``<prefix>:<onset>:p1``);
  after ``reminder_h`` hours with the condition still open → REMIND (``…:p<n>``). An identity is a send_system
  dedupe key, so every page has its own and a held or failed send is retried under the same identity next run.
* a good observation after a delivered page → RECOVER once (``…:recovered``); then the state resets.

Delivery counts only when send_system says delivered (ok, not deduped-without-id, not suppressed/held): a hold is
retried, never marked (the incident-notifier rule, N8N maturity B2 round 2).

AUTHORITY: OPERATOR_NOTIFY_SYSTEM_OPS (through the caller). Stdlib only; no n8n, no relay, no gateway, no broker.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

NO_CONSUMER_REASON = (
    "library: scripts/n8n_drift_watch.py and scripts/n8n_host_deadman.py import it (n8n platform hardening packet "
    "2026-10-22); it defines no versioned contract of its own"
)

PAGE = "PAGE"
REMIND = "REMIND"
RECOVER = "RECOVER"
NONE = "NONE"
P1_PATH = "host:scripts/lib/autonomy_watchdog/telegram_system.send_system (SYSTEM ops family; n8n not involved)"


def _parse(ts: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else None


def _compact(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def fresh_state() -> dict[str, Any]:
    return {
        "onset_key": None,
        "bad_since": None,
        "consecutive_bad": 0,
        "pages_delivered": 0,
        "last_page_at": None,
        "last_status": None,
    }


def decide(
    state: Optional[dict],
    *,
    bad: bool,
    key: str,
    now: datetime,
    prefix: str,
    threshold: int = 2,
    reminder_h: float = 6.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (next_state, action). action = {kind, identity, onset, consecutive_bad}; next_state is what the caller
    persists only in live mode (and, for PAGE/REMIND/RECOVER, only after ``mark_delivered``)."""
    st = {**fresh_state(), **(state or {})}
    if not bad:
        if st.get("pages_delivered"):
            onset = _parse(st.get("bad_since")) or now
            action = {
                "kind": RECOVER,
                "identity": f"{prefix}:{_compact(onset)}:recovered",
                "onset": st.get("bad_since"),
                "consecutive_bad": 0,
            }
            return st, action  # reset happens in mark_delivered (a held recovery is retried)
        nxt = fresh_state()
        nxt["last_status"] = "ok"
        return nxt, {"kind": NONE, "identity": None, "onset": None, "consecutive_bad": 0}
    if st.get("onset_key") != key or not st.get("bad_since"):
        # a new condition (or the first bad run): a new onset; a page delivered for the old key does not cover it
        st = {**fresh_state(), "onset_key": key, "bad_since": now.isoformat()}
    st["consecutive_bad"] = int(st.get("consecutive_bad") or 0) + 1
    st["last_status"] = "bad"
    onset = _parse(st["bad_since"]) or now
    action = {"kind": NONE, "identity": None, "onset": st["bad_since"], "consecutive_bad": st["consecutive_bad"]}
    if st["consecutive_bad"] < max(1, int(threshold)):
        return st, action
    delivered = int(st.get("pages_delivered") or 0)
    if delivered == 0:
        action.update(kind=PAGE, identity=f"{prefix}:{_compact(onset)}:p1")
        return st, action
    last = _parse(st.get("last_page_at"))
    if last is None or (now - last).total_seconds() >= reminder_h * 3600:
        action.update(kind=REMIND, identity=f"{prefix}:{_compact(onset)}:p{delivered + 1}")
    return st, action


def delivered(rec: Optional[dict]) -> bool:
    """True only for a send the transport delivered (a held / suppressed / unconfigured send is retried)."""
    if not isinstance(rec, dict) or not rec.get("ok"):
        return False
    if rec.get("suppressed") or rec.get("held") or str(rec.get("reason") or "").startswith("suppressed"):
        return False
    if rec.get("deduped"):
        return bool(rec.get("message_id"))  # an earlier delivery of this very identity
    return True


def mark_delivered(state: dict, action: dict, *, now: datetime) -> dict[str, Any]:
    if action["kind"] == RECOVER:
        nxt = fresh_state()
        nxt["last_status"] = "ok"
        return nxt
    st = dict(state)
    st["pages_delivered"] = int(st.get("pages_delivered") or 0) + 1
    st["last_page_at"] = now.isoformat()
    return st


Sender = Callable[..., dict]
Previewer = Callable[..., dict]


def default_sender() -> Sender:
    from scripts.lib.autonomy_watchdog.telegram_system import send_system  # noqa: PLC0415

    return send_system


def default_previewer() -> Previewer:
    from scripts.lib.autonomy_watchdog.telegram_system import preview_send  # noqa: PLC0415

    return preview_send


def run_action(
    state: dict,
    action: dict,
    text: str,
    *,
    live: bool,
    now: datetime,
    kind: str,
    sender: Optional[Sender] = None,
    previewer: Optional[Previewer] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Send (live) or preview (dry run) one action. Returns (state to persist, page record for the receipt)."""
    record: dict[str, Any] = {"action": action["kind"], "identity": action.get("identity"), "p1_path": P1_PATH}
    if action["kind"] == NONE:
        return state, record
    if not live:
        try:
            plan = (previewer or default_previewer())(text, identity=action["identity"], kind=kind)
        except Exception as exc:  # noqa: BLE001 — a preview never fails the dry run
            plan = {"would_send": False, "reason": f"preview_failed:{type(exc).__name__}"}
        record["preview"] = {k: plan.get(k) for k in ("would_send", "reason") if k in plan}
        record["text"] = text
        return state, record
    try:
        rec = (sender or default_sender())(text, identity=action["identity"], kind=kind)
    except Exception as exc:  # noqa: BLE001 — a failed send is retried next run, never marked
        rec = {"ok": False, "reason": f"send_failed:{type(exc).__name__}"}
    ok = delivered(rec)
    record["send"] = {k: rec.get(k) for k in ("ok", "deduped", "suppressed", "reason", "message_id") if k in rec}
    record["delivered"] = ok
    return (mark_delivered(state, action, now=now) if ok else state), record
