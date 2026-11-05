"""Inverse-hedge stoplight notifications (DSN-20261031-market-risk-engine P0-T7, design §11 item 4).

The defense desk's stoplight state machine (scripts/defense_inverse_stoplights.py) ran in SHADOW from
2026-07-18 with ``notify=False``: PSQ went THESIS GREEN on 10-23, ENTRY GREEN on 10-27 and GREEN again at
17:55 ET on 10-29, the evening before the 2026-10-30 selloff, and nobody was told (RCA finding 4,
docs/audits/MARKET_SELLOFF_ALERT_RCA_2026-10-30.md). The operator promoted the desk on 2026-10-31.

Single-source rule (AGENTS.md §4): this module fetches nothing. It receives the transition the desk has just
persisted and sends ONE intent through telegram_alert.send_telegram. Which transitions send, the priority and
the dedupe window live in config/defense_stoplight_notify.json (no hardcoded values). A dry run renders the
card and sends nothing. Errors are returned on the result, never swallowed. Advisory only: no size, order or
stop value exists here (MBI_BEHAVIOR = 0).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CFG_PATH = ROOT / "config" / "defense_stoplight_notify.json"
REQUIRED = ("enabled", "priority", "dedupe_minutes", "producer", "message_class", "transitions")
#: words that would turn an advisory card into a behaviour — a card containing one is a defect
BEHAVIOR_WORDS = ("shares", "qty", "size", "order", "stop price", "notional", "buy ", "sell ")


class StoplightNotifyConfigError(RuntimeError):
    pass


def load_config(path: Path | None = None) -> dict:
    """Read and validate the delivery policy. A missing or malformed file fails closed (no send)."""
    p = path or CFG_PATH
    try:
        c = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StoplightNotifyConfigError(f"{p}: {type(e).__name__}: {e}") from e
    missing = [k for k in REQUIRED if k not in c]
    if missing:
        raise StoplightNotifyConfigError(f"{p}: missing {missing}")
    if not isinstance(c["transitions"], list) or not all(
        isinstance(t, dict) and t.get("light") and t.get("state") for t in c["transitions"]
    ):
        raise StoplightNotifyConfigError(f"{p}: transitions must be a list of {{light, state}}")
    if str(c["priority"]) not in ("P1", "P2", "P3"):
        raise StoplightNotifyConfigError(f"{p}: priority must be P1, P2 or P3")
    int(c["dedupe_minutes"])
    return c


def should_notify(light: str, state: str, cfg: dict) -> bool:
    """True only for a transition the operator listed. Disabled policy → never."""
    if not cfg.get("enabled"):
        return False
    return any(t["light"] == light and t["state"] == state for t in cfg["transitions"])


def render(t: dict, when_et: str) -> str:
    """The phone-length card. Every number comes from the persisted transition; nothing is computed here."""
    why = next(
        (x.get("why") for x in t.get("_cfg_transitions", []) if x["light"] == t["light"] and x["state"] == t["state"]),
        None,
    )
    lines = [
        f"🚦 HEDGE STOPLIGHT {t['inverse']}/{t['bench']} — {t['light']} {t['state']}: {t['label']}",
        str(t.get("reason") or "")[:300],
    ]
    if why:
        lines.append(f"Meaning: {why}.")
    lines.append(f"as_of {t.get('as_of') or 'unknown'} · evaluated {when_et}")
    lines.append("Advisory. The desk's existing staging → approval path applies; no order, size or stop is implied.")
    return "\n".join(x for x in lines if x)


def emit(transition: dict, *, cfg: dict | None = None, dry_run: bool, now=None) -> dict:
    """Send ONE intent for a persisted stoplight transition when the policy lists it.

    ``transition``: inverse, bench, light, state, label, reason, as_of. Returns {sent, accepted, message, error}.
    """
    cfg = cfg or load_config()
    out = {"light": transition["light"], "state": transition["state"], "sent": False, "accepted": None, "error": None}
    if not should_notify(transition["light"], transition["state"], cfg):
        return out
    when_et = (now or datetime.now(timezone.utc)).astimezone().strftime("%a %m-%d %H:%M %Z")
    message = render({**transition, "_cfg_transitions": cfg["transitions"]}, when_et)
    out["message"] = message
    if dry_run:
        print(
            f"[stoplight-notify] DRY RUN would send {cfg['priority']} dedupe {int(cfg['dedupe_minutes'])}:\n{message}"
        )
        return out
    try:
        from telegram_alert import send_telegram

        out["sent"] = True
        out["accepted"] = bool(
            send_telegram(
                message,
                priority=str(cfg["priority"]),
                dedupe_minutes=int(cfg["dedupe_minutes"]),
                producer=str(cfg["producer"]),
                message_class=str(cfg["message_class"]),
            )
        )
    except Exception as e:  # noqa: BLE001 — surfaced on the result and stderr, never swallowed
        out["accepted"] = False
        out["error"] = f"{type(e).__name__}: {e}"
        print(f"[stoplight-notify] WARNING send failed: {out['error']}", file=sys.stderr)
    return out
