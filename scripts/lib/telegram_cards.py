"""Decision cards for Telegram — the ticker first, the action second, the numbers third (operator 2026-10-08).

Operator review: "Everything blends together … the brain sees a wall of words instead of CRITICAL → DT → CHECK NOW."
Two families move to card layout here; every other rich producer keeps telegram_rich.RichMessage:

  * CIO entry alerts (telegram_rich.cio_entry_alert → EntryCard):
        🟡 HIGH CONVICTION ENTRY          ← what this is
        $SWMR                             ← the ticker, alone, linked
        ━━━━━━━━━━━━━━━━━━
        🟢 STATUS / ⚠️ ACTION REQUIRED      ← what to do
        ━━━━━━━━━━━━━━━━━━
        💰 ENTRY · 🛑 STOP · 🎯 TARGET · R:R  ← the numbers
        ━━━━━━━━━━━━━━━━━━
        🏢 COMPANY · ⚡ CIO VERDICT + reasons
        TTL · buttons (Open Research / TradingView / Review Position) · deep context collapsed
  * Stop health (stop_health_check.py → stop_health_card): "🚨 CRITICAL STOP ALERT / $DT / STOP HEALTH — ORPHANED
    / urgent n · total n / ACTION / TTL" with Open Position + Check Stops buttons.

Routing safety: operator_alert_policy_v2, the daily-budget exemption and the Communications classifier read these
texts (whole-text regexes, no DOTALL). Machine words stay on ONE line ("STOP HEALTH — NEAR TRIGGER"), entry headers
are listed in those matchers, and tests/test_decision_cards_20261008.py proves old and new text route identically.
Advisory only (MBI_BEHAVIOR = 0): levels are references, never orders. Rollback: config/telegram_cards.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

try:
    from scripts.lib.telegram_rich import (MAX_TEXT, _card_money, _card_pct, _card_ratio, _card_text, cc_base,
                                           cc_symbol_url, chart_image_url, esc, link, safe_url)
except ImportError:  # pragma: no cover - flat import layout
    from lib.telegram_rich import (MAX_TEXT, _card_money, _card_pct, _card_ratio, _card_text, cc_base,  # type: ignore
                                   cc_symbol_url, chart_image_url, esc, link, safe_url)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "telegram_cards.yaml"
RULE = "━━━━━━━━━━━━━━━━━━"
# Entry headers — every one is listed in operator_alert_policy_v2 / telegram_alert_router (routing) and in
# config/comms_categories.yaml (category). Keep the three in step.
ENTRY_HEADERS = ("HIGH CONVICTION ENTRY", "ENTRY APPROACHING", "ADD-ON ENTRY", "ENTRY BLOCKED", "ENTRY ALERT")


def enabled(family: str) -> bool:
    try:
        import yaml

        cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    return bool((cfg.get("families") or {}).get(family, {}).get("enabled"))


def ttl_text(category: str) -> Optional[str]:
    """The Communications TTL for the category the classifier gives this card (config/comms_categories.yaml)."""
    try:
        from scripts.lib.comms import classify as cl
    except ImportError:  # pragma: no cover
        from lib.comms import classify as cl  # type: ignore
    try:
        h = float(next((c["ttl_hours"] for c in cl.categories() if c["id"] == category), 0) or 0)
    except Exception:
        return None
    if not h:
        return None
    return f"{h / 24:.0f} days" if h >= 48 else f"{h:.0f} hours"


def tradingview_url(symbol: str) -> str:
    return f"https://www.tradingview.com/chart/?symbol={quote(symbol.upper())}"


def opportunity_url(symbol: str) -> str:
    return f"{cc_base()}/v3/watch?tab=opportunities&opp={quote(symbol.upper())}"


def stops_url(symbol: str) -> str:
    """Portfolio → holdings drawer opened on the symbol's stops (PortfolioHub ?symbol=&drawerTab=stops deep link)."""
    return f"{cc_base()}/v3/portfolio?symbol={quote(symbol.upper())}&drawerTab=stops"


def _block(icon: str, heading: str, lines: list[str]) -> str:
    body = [esc(x) for x in lines if x]
    return "\n".join([f"{icon} <b>{esc(heading)}</b>", *body]) if body else ""


@dataclass
class Card:
    """A rendered-on-demand Telegram card: same render() contract as telegram_rich.RichMessage."""

    header: str
    marker: str
    symbol: str
    blocks: list[list[str]]                 # groups of pre-rendered HTML blocks, separated by RULE
    buttons: list[tuple[str, str]] = field(default_factory=list)
    ttl: Optional[str] = None
    evidence: list[str] = field(default_factory=list)
    chart: bool = True
    authority: str = "READ_ONLY_ADVISORY"
    symbols: list[str] = field(default_factory=list)

    def render(self) -> dict[str, Any]:
        sym = self.symbol.upper()
        head = f"{self.marker + ' ' if self.marker else ''}<b>{esc(self.header)}</b>"
        ticker = f"<b>{link('$' + sym, cc_symbol_url(sym))}</b>" if sym else ""
        parts = [head, "", ticker] if ticker else [head]
        for group in self.blocks:
            group = [g for g in group if g]
            if group:
                parts += ["", RULE, "", "\n\n".join(group)]
        tail = [RULE, f"<i>TTL: {esc(self.ttl)}</i>"] if self.ttl else [RULE]
        text = "\n".join(parts) + "\n\n" + "\n".join(tail)
        ev = [esc(e) for e in self.evidence if e]
        if ev:
            room = MAX_TEXT - len(text) - 64
            kept, used = [], 0
            for e in ev:
                if used + len(e) + 1 > room:
                    kept.append("…")
                    break
                kept.append(e)
                used += len(e) + 1
            if kept and kept != ["…"]:
                text += "\n<blockquote expandable>" + "\n".join(kept) + "</blockquote>"
        if len(text) > MAX_TEXT:
            text = text[: MAX_TEXT - 1] + "…"
        btns = [(label, url) for label, url in self.buttons if safe_url(url)][:3]
        markup = {"inline_keyboard": [[{"text": label, "url": url} for label, url in btns]]} if btns else None
        preview = ({"url": chart_image_url(sym), "prefer_large_media": True, "show_above_text": True}
                   if self.chart and sym else {"is_disabled": True})
        return {"text": text, "parse_mode": "HTML", "reply_markup": markup, "link_preview_options": preview,
                "authority": self.authority}


# ── CIO entry alert ─────────────────────────────────────────────────────────


def entry_card(item: dict[str, Any], *, marker: str, state: str, stance: str, held: Optional[bool],
               review_status: str, next_action: str, hard_block: Any, evidence: list[str]) -> Card:
    sym = str(item.get("symbol") or "").upper()
    if marker == "🔴":
        header = "ENTRY BLOCKED"
    elif held is True:
        header = "ADD-ON ENTRY"
    elif state in {"BUY_READY", "READY"}:
        header = "HIGH CONVICTION ENTRY"
    elif "NEAR" in state:
        header = "ENTRY APPROACHING"
    else:
        header = "ENTRY ALERT"
    price, stop, target = item.get("price"), item.get("stop"), item.get("target")
    low, high = item.get("entry_low", item.get("zone_low")), item.get("entry_high", item.get("zone_high"))
    rr = item.get("rr_at_current_price", item.get("current_rr"))
    ideal_rr = item.get("rr_at_ideal_entry", item.get("rr", item.get("ideal_rr")))
    try:
        risk = float(price) - float(stop) if price is not None and stop is not None else None
    except (TypeError, ValueError):
        risk = None
    status_icon = {"🟢": "🟢", "🔴": "🔴"}.get(marker, "🟡")
    status = [_block(status_icon, "STATUS", [state.replace("_", " ")]),
              _block("⚠️", "ACTION REQUIRED", [next_action])]
    zone = f"Zone: {_card_money(low)} - {_card_money(high)}" if low is not None and high is not None else ""
    note = item.get("price_note") or ("inside entry zone" if state in {"BUY_READY", "READY"} else "")
    levels = [
        _block("💰", "ENTRY", [f"Current: {_card_money(price)}" + (f" · {note}" if note else ""), zone]),
        _block("🛑", "STOP", [_card_money(stop) + (f" · risk to stop {_card_money(risk)}" if risk is not None else "")]),
        _block("🎯", "TARGET", [_card_money(target)]),
        f"<b>R:R {esc(_card_ratio(rr if rr is not None else ideal_rr))}</b>"
        + (f" · ideal-zone {esc(_card_ratio(ideal_rr))}" if rr is not None and ideal_rr is not None else "")
        + (f" · distance {esc(_card_pct(item.get('distance_pct')))}" if item.get("distance_pct") is not None else ""),
    ]
    company = _card_text(item.get("company"), limit=100)
    industry = _card_text(item.get("industry") or item.get("sector"), limit=80)
    reasons = [_card_text(x, limit=140) for x in (item.get("options_reasons") or []) if _card_text(x)][:3]
    kills = _card_text(hard_block, limit=200) or "No hard block recorded — review incomplete"
    verdict = [f"{marker} {stance}", f"Review: {review_status}"]
    if reasons:
        verdict += ["Reason:", *reasons]
    verdict.append(f"What kills the idea: {kills}")
    horizon = _card_text(item.get("time_horizon") or item.get("dte"), limit=60)
    if horizon:
        verdict.append(f"Time horizon: {horizon}")
    context = [_block("🏢", "COMPANY", [company or f"{sym} · identity data unavailable", industry]),
               _block("⚡", "CIO VERDICT", verdict)]
    return Card(
        header=header, marker=marker, symbol=sym, symbols=[sym] if sym else [],
        blocks=[status, levels, context],
        buttons=[("Open Research", cc_symbol_url(sym)), ("Open TradingView", tradingview_url(sym)),
                 ("Review Position", opportunity_url(sym))] if sym else [],
        ttl=ttl_text("high_conviction_opportunity" if header == "HIGH CONVICTION ENTRY" else "reward"),
        evidence=evidence,
    )


# ── Stop health ─────────────────────────────────────────────────────────────

STOP_ACTION = {
    "ORPHANED": "Review stop placement immediately — a stop has no position, or a position has no stop.",
    "OVERSIZED": "Review the stop quantity — it is larger than the position.",
    "TRIGGERED": "Confirm the fill and the position state.",
    "NEAR_TRIGGER": "Review the stop — price is close to it.",
}


def stop_health_card(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    """One card per run. alerts: [{symbol, account, condition, severity: urgent|warning, line}]."""
    urgent = sum(1 for a in alerts if a.get("severity") == "urgent")
    syms: list[str] = []
    for a in alerts:
        s = str(a.get("symbol") or "").upper()
        if s and s not in syms:
            syms.append(s)
    single = len(syms) == 1
    marker = "🚨" if urgent else "⚠️"
    header = ("CRITICAL STOP ALERT" if urgent else "STOP WARNING") + ("" if len(alerts) == 1 else f" · {len(alerts)} alerts")
    blocks: list[list[str]] = []
    if single:
        counts = [f"Urgent alerts: {urgent}", f"Total alerts: {len(alerts)}"]
        issues = []
        for a in alerts:
            cond = str(a.get("condition") or "").upper()
            issues.append(f"STOP HEALTH — {cond.replace('_', ' ')} · {a.get('account') or '—'}")
            if a.get("line"):
                issues.append(f"  {a['line']}")
        blocks.append([_block("🛑", "STOP HEALTH ISSUE", issues), "\n".join(esc(c) for c in counts)])
        first = str(alerts[0].get("condition") or "").upper() if alerts else ""
        blocks.append([_block("👉", "ACTION", [STOP_ACTION.get(first, "Review the stop.")])])
    else:
        rows = []
        for s in syms:
            mine = [a for a in alerts if str(a.get("symbol") or "").upper() == s]
            u = sum(1 for a in mine if a.get("severity") == "urgent")
            conds = ", ".join(sorted({str(a.get("condition") or "").upper().replace("_", " ") for a in mine}))
            rows.append(f"{'🚨' if u else '⚠️'} <b>{link('$' + s, cc_symbol_url(s))}</b> — STOP HEALTH — {esc(conds)}"
                        + (f" · {u} urgent" if u else ""))
            for a in mine[:3]:
                if a.get("line"):
                    rows.append(f"   {esc(a['line'])}")
        blocks.append(["\n".join(rows), esc(f"Urgent alerts: {urgent} · Total alerts: {len(alerts)}")])
        blocks.append([_block("👉", "ACTION", ["Review the flagged stops — urgent ones first."])])
    card = Card(header=header, marker=marker, symbol=syms[0] if single else "", symbols=syms, blocks=blocks,
                buttons=([("Open Position", opportunity_url(syms[0])), ("Check Stops", stops_url(syms[0]))]
                         if single else [("Check Stops", f"{cc_base()}/v3/portfolio?tab={quote('Stop Management')}")]),
                ttl=ttl_text("threat"), chart=False)
    out = card.render()
    out["symbols"] = syms
    return out
