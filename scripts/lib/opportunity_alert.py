"""Opportunity line for Telegram alerts — the Investment Command Center in every symbol alert.

Operator 2026-10-08: "make sure these changes resonate in telegram alerts also". Called from the single chokepoint
telegram_alert.send_telegram: when an alert's Communications category (scripts/lib/comms/classify.py) is an
opportunity/risk category and it names a symbol curated in CIO memory (data/cio/cio_opportunity_projection.json),
append one line —

    🧭 Conviction 84/100 · #3 of 1,332 · R:R 4.1x · Upside +35% · ADD — Open in Command Center

Read-only. Never raises (returns the message unchanged on any problem). Idempotent (a message that already carries
the line is left alone). Skipped when the projection is stale. Rules in config/opportunity_conviction.yaml
``telegram``. MBI_BEHAVIOR = 0: a stance label and numbers, never an instruction.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

MARK = "🧭 Conviction"
_cache: dict[str, Any] = {"mtime": None, "proj": None}


def _projection(path: Path) -> dict[str, Any]:
    m = path.stat().st_mtime
    if _cache["mtime"] != m:
        _cache["proj"] = json.loads(path.read_text(encoding="utf-8"))
        _cache["mtime"] = m
    return _cache["proj"] or {}


def _cfg() -> dict[str, Any]:
    try:
        from scripts.lib.data_broker.opportunity import load_config
    except ImportError:  # pragma: no cover
        from lib.data_broker.opportunity import load_config  # type: ignore
    return load_config().get("telegram") or {}


#: message classes whose own levels are intraday: the CIO line is labelled as the swing view
SWING_VIEW_CLASSES = ("active_trader_scalp_alert",)


def line_for(a: dict[str, Any], total: Optional[int], base: str) -> str:
    rr = (a.get("risk_reward") or {}).get("rr")
    up = a.get("upside_pct")
    parts = [f"{MARK} {a['conviction']:.0f}/100"]
    if a.get("rank"):
        parts.append(f"#{a['rank']}" + (f" of {total:,}" if total else ""))
    if rr is not None:
        parts.append(f"R:R {rr:.1f}x")
    if up is not None and not (a.get("upside_flag") or "").startswith("implausible"):
        parts.append(f"Upside {up:+.0f}%")
    if a.get("stance"):
        parts.append(str(a["stance"]).replace("_", "-"))
    sym = html.escape(a["symbol"])
    link = f'<a href="{base}/v3/watch?tab=opportunities&amp;opp={sym}">Open in Command Center</a>'
    return " · ".join(parts) + f" — {link}"


def enrich(message: str, *, message_class: str = "operator_alert", projection_path: Optional[Path] = None,
           now: Optional[datetime] = None) -> str:
    try:
        if not message or MARK in message:
            return message
        cfg = _cfg()
        if not cfg.get("enabled"):
            return message
        try:
            from scripts.lib.comms import classify as cl
            from scripts.lib.cio_opportunity_store import PROJECTION_PATH
            from scripts.lib.comms_editor import cc_base
        except ImportError:  # pragma: no cover
            from lib.comms import classify as cl  # type: ignore
            from lib.cio_opportunity_store import PROJECTION_PATH  # type: ignore
            from lib.comms_editor import cc_base  # type: ignore
        c = cl.classify(body=message, direction="OUTBOUND", message_class=message_class)
        if c.get("category") not in set(cfg.get("categories") or []):
            return message
        syms = list(c.get("symbols") or [])[: int(cfg.get("max_symbols") or 2)]
        if not syms:
            return message
        proj = _projection(Path(projection_path or PROJECTION_PATH))
        as_of = datetime.fromisoformat(str(proj.get("as_of")).replace("Z", "+00:00"))
        age_h = ((now or datetime.now(timezone.utc)) - as_of).total_seconds() / 3600
        if age_h > float(cfg.get("max_projection_age_hours") or 26):
            return message
        items = proj.get("items") or {}
        total = sum(1 for v in items.values() if v.get("rank"))
        lines = [line_for(items[s], total, cc_base()) for s in syms
                 if s in items and items[s].get("conviction") is not None]
        if not lines:
            return message
        if message_class in SWING_VIEW_CLASSES:
            # a scalp alert's R is minutes-scale; the CIO line is the multi-week swing view of the same name.
            # Said so, or "R:R 3.8x" beside "R 0.04" reads as a contradiction (operator 2026-10-09, XNDU).
            lines = [ln.replace(MARK, f"{MARK} CIO swing view (not this scalp):", 1) for ln in lines]
        out = message.rstrip() + "\n\n" + "\n".join(lines)
        return out if len(out) <= 4000 else message
    except Exception:  # noqa: BLE001 — an alert is never lost or delayed over an enrichment
        return message
