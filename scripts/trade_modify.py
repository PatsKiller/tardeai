#!/usr/bin/env python3
"""trade_modify.py — unified queue override + audit helpers (operator 2026-06-19).

Backs the Telegram modify-size / modify-risk flow and writes the append-only queue_decision_audit row
for EVERY approve / deny / modify / route / policy_edit. Also the tiny force-reply pending-state store
(JSON, mirrors the telegram_cmd_state.json pattern — no extra migration). Size/risk re-derivation reuses
account_policy.compute_sizing so a Telegram edit sizes by the SAME engine as the auto pipeline.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn

_ROOT = Path(__file__).resolve().parent.parent
_PENDING = _ROOT / "data" / "runtime" / "telegram_pending_modify.json"


# ── audit (req 10) ─────────────────────────────────────────────────────────────────────────────────
def audit_decision(action: str, *, proposal_id=None, intent_id=None, actor=None, channel=None,
                   before=None, after=None, reason=None) -> None:
    """Append one immutable queue_decision_audit row. Never raises (audit must not break the action)."""
    try:
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO queue_decision_audit (proposal_id, intent_id, action, actor, channel, "
            "before_value, after_value, reason) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (proposal_id, intent_id, action, (actor or "")[:80], (channel or "")[:20],
             json.dumps(before) if before is not None else None,
             json.dumps(after) if after is not None else None, reason))
        conn.commit()
    except Exception:
        try:
            _get_conn().rollback()
        except Exception:
            pass


# ── force-reply pending state ────────────────────────────────────────────────────────────────────
def _load_pending() -> dict:
    try:
        return json.loads(_PENDING.read_text())
    except Exception:
        return {}


def _save_pending(d: dict) -> None:
    _PENDING.parent.mkdir(parents=True, exist_ok=True)
    _PENDING.write_text(json.dumps(d))


def set_pending(chat_id, proposal_id: int, kind: str, symbol: str) -> None:
    """kind = 'size' | 'risk'. Records what the next numeric reply from this chat should modify."""
    d = _load_pending()
    d[str(chat_id)] = {"proposal_id": int(proposal_id), "kind": kind, "symbol": (symbol or "").upper()}
    _save_pending(d)


def pop_pending(chat_id):
    d = _load_pending()
    item = d.pop(str(chat_id), None)
    if item is not None:
        _save_pending(d)
    return item


# ── apply (re-derives via the SAME sizing engine) ─────────────────────────────────────────────────
def _proposal(pid: int) -> dict | None:
    cur = _get_conn().cursor()
    cur.execute("""SELECT id, symbol, proposed_account, target_account, proposed_entry, proposed_stop,
                          proposed_shares, final_shares FROM paper_trade_proposals WHERE id=%s""", (pid,))
    r = cur.fetchone()
    if not r:
        return None
    cols = ("id", "symbol", "proposed_account", "target_account", "entry", "stop", "proposed_shares", "final_shares")
    return dict(zip(cols, r))


def apply_size(pid: int, shares: int, *, actor: str, channel: str = "telegram") -> dict:
    """Operator-set absolute share count. Stores final_shares + override_payload, audits before/after."""
    p = _proposal(pid)
    if not p:
        return {"ok": False, "error": "proposal not found"}
    shares = int(shares)
    if shares < 1:
        return {"ok": False, "error": "shares must be >= 1"}
    before = {"final_shares": p.get("final_shares"), "proposed_shares": p.get("proposed_shares")}
    entry = float(p.get("entry") or 0)
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("""UPDATE paper_trade_proposals
                      SET final_shares=%s, proposed_shares=%s,
                          proposed_dollar_size=%s,
                          override_payload = COALESCE(override_payload,'{}'::jsonb) || %s::jsonb
                    WHERE id=%s""",
                (shares, shares, round(shares * entry, 2),
                 json.dumps({"manual_size_override": shares, "by": actor, "channel": channel}), pid))
    conn.commit()
    audit_decision("modify_size", proposal_id=pid, actor=actor, channel=channel,
                   before=before, after={"shares": shares}, reason="operator size override")
    return {"ok": True, "symbol": p["symbol"], "shares": shares, "dollar_size": round(shares * entry, 2)}


def apply_risk(pid: int, new_stop: float, *, actor: str, channel: str = "telegram") -> dict:
    """Operator-set protective stop. Re-derives risk-capped shares via account_policy.compute_sizing so
    a tighter/wider stop re-sizes consistently with the auto engine. Audits before/after."""
    import account_policy as ap
    p = _proposal(pid)
    if not p:
        return {"ok": False, "error": "proposal not found"}
    entry = float(p.get("entry") or 0)
    new_stop = float(new_stop)
    if entry <= 0 or new_stop <= 0 or new_stop >= entry:
        return {"ok": False, "error": "stop must be > 0 and below entry"}
    acct = p.get("target_account") or p.get("proposed_account") or ap.default_paper_account()
    policy = ap.load_policy(acct)
    equity, _ = ap.equity_for_account(acct)
    s = ap.compute_sizing(policy, equity, entry, new_stop, desired_shares=None)
    if not s.get("valid"):
        return {"ok": False, "error": s.get("reason", "SIZE_TOO_SMALL")}
    before = {"stop": p.get("stop"), "shares": p.get("final_shares") or p.get("proposed_shares")}
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("""UPDATE paper_trade_proposals
                      SET proposed_stop=%s, final_shares=%s, proposed_shares=%s,
                          proposed_dollar_size=%s, proposed_dollar_risk=%s,
                          override_payload = COALESCE(override_payload,'{}'::jsonb) || %s::jsonb
                    WHERE id=%s""",
                (new_stop, s["shares"], s["shares"], s["dollar_size"], s["dollar_risk"],
                 json.dumps({"manual_stop_override": new_stop, "by": actor, "channel": channel}), pid))
    conn.commit()
    audit_decision("modify_risk", proposal_id=pid, actor=actor, channel=channel,
                   before=before, after={"stop": new_stop, "shares": s["shares"], "dollar_risk": s["dollar_risk"]},
                   reason="operator stop/risk override")
    return {"ok": True, "symbol": p["symbol"], "stop": new_stop, "shares": s["shares"],
            "dollar_risk": s["dollar_risk"], "binding": s["binding"]}
