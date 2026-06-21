#!/usr/bin/env python3
"""Inference Layers — Telegram digest.

Pushes a prioritized, confidence-tagged summary of a cycle's highest-value
inferences to Telegram via the existing telegram_alert.send_telegram helper.
Advisory only; never an actionable order.
"""
from __future__ import annotations

import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

log = logging.getLogger("inference_telegram")

_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_SEV_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}
_TYPE_ICON = {"regional_impact": "🌏", "journal_pattern": "📓", "nav_signal": "💰",
              "opportunity": "🎯", "risk": "⚠️", "sizing": "📐",
              "market_regime": "🌡️", "data_gap": "🕳️"}


def _collect(ctx) -> list:
    infs = []
    for r in ctx.store.values():
        infs.extend(r.inferences)
    return infs


def build_digest(ctx, run_id=None) -> str:
    cfg = ctx.cfg.get("telegram", {}) or {}
    min_sev = cfg.get("min_severity", "medium")
    max_items = int(cfg.get("max_items", 6))
    floor = _SEV_RANK.get(min_sev, 2)

    infs = [i for i in _collect(ctx) if _SEV_RANK.get(i.severity, 3) <= floor]
    infs.sort(key=lambda i: (_SEV_RANK.get(i.severity, 3), -float(i.confidence or 0)))
    infs = infs[:max_items]

    lines = [f"🧠 *Inference Cycle* — regime *{ctx.regime}*"]
    if not infs:
        lines.append("_No medium+ inferences this cycle._")
    for i in infs:
        icon = _TYPE_ICON.get(i.inference_type, "•")
        sev = _SEV_ICON.get(i.severity, "")
        title = i.title.replace("*", "")
        body = (i.body or "").strip().split("\n")[0][:180]
        lines.append(f"\n{sev}{icon} *{title}*  _(conf {float(i.confidence or 0):.0%})_")
        if body:
            lines.append(body)
    url = cfg.get("dashboard_url")
    if url:
        lines.append(f"\n🔗 {url}")
    return "\n".join(lines)


def send_inference_digest(ctx, run_id=None) -> bool:
    msg = build_digest(ctx, run_id)
    try:
        from telegram_alert import send_telegram
        return send_telegram(msg)
    except Exception as e:
        log.warning("send_telegram failed: %s", e)
        return False
