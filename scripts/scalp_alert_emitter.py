#!/usr/bin/env python3
"""M3-S7 — scalp ignition alert emitter (design §3.4). ALERTS ONLY — NEVER a proposal.

Maps IGN lanes to notification tiers and routes them through the EXISTING alert_dispatcher (which
supplies cross-invocation dedupe = once/day/symbol, the 15/hour Telegram rate-limit, and fatigue
auto-downgrade). Engine-local controls added on top: a per-run session cap + a single summary line on
cap breach. Every Telegram alert is tagged `UNGATED — NOT A PROPOSAL`.

HARD: this module contains NO proposal path and NO order path. IGN_75 emits an ALERT, not a proposal
(proposals are M3-S9). Gated by `notifications.emit` — off → nothing is sent.
"""
from __future__ import annotations

from typing import Callable, Mapping, Optional, Sequence

# lane → tier. INFO = dashboard only (no Telegram, no cap); ALERT = Telegram.
LANE_TIER = {
    "IGN_45": "INFO",
    "IGN_60": "ALERT",
    "IGN_ACCEL": "ALERT",
    "IGN_75": "ALERT",     # M3-S7: still an ALERT, NOT a proposal (proposals = M3-S9)
    "BELOW": None,
}
NOT_A_PROPOSAL = "UNGATED — NOT A PROPOSAL"


def lane_to_tier(lane: str) -> Optional[str]:
    return LANE_TIER.get(lane)


class AlertBudget:
    """Per-logger-run controls. Cross-invocation dedupe/rate-limit is the dispatcher's job."""
    def __init__(self, session_cap: int = 8):
        self.session_cap = int(session_cap)
        self.telegram_sent = 0
        self.capped = False

    def allow_telegram(self) -> bool:
        return self.telegram_sent < self.session_cap

    def record_telegram(self):
        self.telegram_sent += 1


def build_alert(row: Mapping) -> tuple[str, str]:
    ss = row.get("subscores") or {}
    sig = " ".join(f"{k.replace('v_', '')}={v:.2f}" for k, v in ss.items() if v)
    rt = row.get("rvol_tod")
    title = f"SCALP IGN {row.get('ign', 0):.0f} · {row.get('symbol')} · {row.get('lane')}"
    body = (f"{NOT_A_PROPOSAL}\n{row.get('symbol')} IGN={row.get('ign', 0):.1f} lane={row.get('lane')} "
            f"RVOL_tod={('%.1fx' % rt) if rt is not None else 'n/a'} [{sig}] · shadow, not tradeable")
    return title, body


def emit_alerts(rows: Sequence[Mapping], cfg: Mapping, budget: AlertBudget, *,
                dispatch_fn: Optional[Callable] = None, dry_run: bool = False) -> list[dict]:
    """Emit alerts for the given scored rows. Returns the list of alert DECISIONS (what was/would be
    sent). No send unless notifications.emit AND a dispatch_fn is provided AND not dry_run."""
    notif = cfg.get("notifications", {})
    decisions: list[dict] = []
    if not notif.get("emit", False):
        return decisions                       # gate: disabled → nothing
    cap = int(notif.get("session_cap", budget.session_cap))
    budget.session_cap = cap
    for r in sorted(rows, key=lambda x: x.get("ign", 0), reverse=True):
        tier = lane_to_tier(r.get("lane"))
        if tier is None:
            continue
        if tier == "ALERT":
            if not budget.allow_telegram():
                if not budget.capped:          # one summary line on cap breach, then silence
                    budget.capped = True
                    decisions.append({"symbol": None, "tier": "ALERT", "action": "cap_summary",
                                      "note": f"scalp alert cap {cap}/run reached; suppressing further"})
                    if dispatch_fn and not dry_run:
                        dispatch_fn(alert_type="scalp_ignition_summary", title="Scalp alerts capped",
                                    body=f"{NOT_A_PROPOSAL}: hit {cap} alerts this run", tier="ALERT",
                                    source="scalp_engine", dedupe_scope="global")
                continue
            budget.record_telegram()
        title, body = build_alert(r)
        d = {"symbol": r.get("symbol"), "tier": tier, "lane": r.get("lane"), "ign": r.get("ign"),
             "action": "dispatch", "proposal": False}   # HARD: never a proposal
        if dispatch_fn and not dry_run:
            d["result"] = dispatch_fn(alert_type="scalp_ignition", title=title, body=body, tier=tier,
                                      symbol=r.get("symbol"), source="scalp_engine", dedupe_scope="symbol")
        decisions.append(d)
    return decisions


def load_dispatcher():
    """Return alert_dispatcher.dispatch_alert (the real Telegram sink) or None if unavailable."""
    try:
        try:
            from alert_dispatcher import dispatch_alert
        except ModuleNotFoundError:
            from scripts.alert_dispatcher import dispatch_alert
        return dispatch_alert
    except Exception:
        return None
