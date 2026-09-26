"""Turn a CIO run's actions into one readable operator message, or none.

2026-09-26 (operator): the CIO Desk chat was a stream of "CIO Advisory Action
cio-action-f0b9... / CIO run <uuid> produced action <id>" -- one Telegram per
action, ids only, and the same action re-created every run ("RE_ENTER TDG" 91
times in a week) re-paged every time because the dedupe key held the fresh
action id. The actions themselves carry content ("AVOID NUAI").

Only material actions page, once per repeat window, in plain words. The rest is
already recorded in the hash-chained CIO action ledger and goes to the digest.
Advisory text only: nothing here orders, sizes or changes a recommendation.
"""
from __future__ import annotations

import fcntl
import json
import time
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULTS = {
    "material_title_verbs": ["BUY", "ADD", "RE_ENTER", "TRIM", "SELL", "EXIT", "AVOID", "HEDGE"],
    "material_priorities": ["HIGH", "CRITICAL", "URGENT"],
    "page_when_operator_decision_required": True,
    "repeat_suppress_days": 7,
    "max_lines_per_message": 12,
}


def load_policy(path: Optional[Path] = None) -> dict[str, Any]:
    p = path or (_ROOT / "config" / "cio_notification_policy.json")
    try:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return {k: data.get(k, v) for k, v in _DEFAULTS.items()}


def action_key(a: dict[str, Any]) -> str:
    """Identity of the *advice*, not of the run that re-issued it."""
    title = " ".join(str(a.get("title") or "").upper().split())
    rec = " ".join(str(a.get("recommended_action") or "").upper().split())
    return f"{title}|{rec}"


def is_material(a: dict[str, Any], policy: dict[str, Any]) -> bool:
    atype = str(a.get("action_type") or "").upper()
    if atype == "STATUS":
        return False
    if atype and any(atype == v or atype.startswith(v) for v in list(policy["material_title_verbs"]) + ["HOLD"]):
        return True
    title = str(a.get("title") or "").upper().replace("-", "_")
    first = title.split(" ", 1)[0] if title else ""
    if any(first == v or first.startswith(v) for v in policy["material_title_verbs"]):
        return True
    if str(a.get("priority") or "").upper() in policy["material_priorities"]:
        return True
    if policy["page_when_operator_decision_required"] and a.get("operator_decision_required") and first:
        return first not in ("MARKET",)
    return False


def _why(a: dict[str, Any]) -> str:
    for k in ("recommended_action", "rationale", "description", "recommendation"):
        v = str(a.get(k) or "").strip()
        if v:
            return v[:180]
    refs = [r for r in (a.get("evidence_refs") or []) if r]
    return f"basis: {', '.join(refs[:3])}" if refs else "no rationale recorded"


def select_new(actions: list[dict[str, Any]], policy: dict[str, Any],
               now: Optional[float] = None, state_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Material actions not already sent inside the repeat window; records what it returns.

    ``state_path=None`` means no memory of past sends (every material action is new).
    The run worker passes a path beside the live notification outbox.
    """
    now = now or time.time()
    if state_path is None:
        seen_now, out = set(), []
        for a in actions:
            if is_material(a, policy) and action_key(a) not in seen_now:
                seen_now.add(action_key(a))
                out.append(a)
        return out
    path = Path(state_path)
    window = float(policy["repeat_suppress_days"]) * 86400.0
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "a+", encoding="utf-8") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except Exception:
            state = {}
        out, seen = [], set()
        for a in actions:
            if not is_material(a, policy):
                continue
            k = action_key(a)
            if k in seen or (k in state and now - float(state[k]) < window):
                continue
            seen.add(k)
            out.append(a)
        for a in out:
            state[action_key(a)] = now
        state = {k: v for k, v in state.items() if now - float(v) < window * 4}
        path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    return out


def render(actions: list[dict[str, Any]], policy: dict[str, Any]) -> Optional[dict[str, str]]:
    if not actions:
        return None
    n = len(actions)
    lines = [f"• {str(a.get('title') or 'Action').strip()} — {_why(a)}" for a in actions[: policy["max_lines_per_message"]]]
    if n > len(lines):
        lines.append(f"• …and {n - len(lines)} more in the CIO action ledger")
    needs = sum(1 for a in actions if a.get("operator_decision_required"))
    subject = f"CIO: {n} new recommendation{'s' if n != 1 else ''}" + (f" · {needs} need your decision" if needs else "")
    body = "\n".join(lines + ["", "Advisory only. Nothing is ordered; you decide and execute."])
    return {"subject": subject, "body": body}
