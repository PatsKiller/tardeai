"""telegram_rich.py — one rich Telegram layout for every Trade-AI message.

WHY
---
Operator, 2026-09-14: "we're still not getting rich, deep HTML context in the Telegram ... no emphasis
in links on everything that can go back to the command center or to the source ... install the bot API
and let's make this happen."

Measured the same day:
- producers wrote flat text or legacy Markdown;
- the CIO desk bot sent plain text;
- the Comms Editor (shadow) only converted Markdown and appended one footer line, and it guessed tickers
  from text (it tagged AP, TROW and F in an ARMP alert).

OpenClaw's Telegram channel already uses the Bot API features below, so they work on this bot too.

WHAT THE BOT API SUPPORTS (and what it does not)
------------------------------------------------
- **HTML parse mode:** <b> <i> <u> <s> <tg-spoiler> <a href> <code> <pre> <blockquote> and
  <blockquote expandable> (collapsible deep context). Nothing else is allowed, so every value is escaped.
- **URL buttons** under a message (reply_markup.inline_keyboard).
- **Link previews:** link_preview_options with a chart image URL and prefer_large_media shows the chart at
  the top of the message. There is no 1,024-character caption limit, as there would be with sendPhoto.
- **No text colour.** Colour comes from emoji markers only.

CONTRACT
--------
- A layout receives its symbols from the producer. It never guesses them from text.
- Every symbol gets a Command Center link, a Finviz link and a Yahoo link.
- Every source is a real link.
- Text stays under Telegram's 4,096 limit. Evidence goes in an expandable quote and is trimmed first.

READ_ONLY_ADVISORY. Formatting only: nothing here sizes, orders or stops.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional
from urllib.parse import quote

MAX_TEXT = 4096
AUTHORITY = "READ_ONLY_ADVISORY"
_SAFE_URL = re.compile(r"^https://[^\s<>\"']+$")


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def safe_url(url: Optional[str]) -> Optional[str]:
    """Only absolute https URLs survive (Telegram rejects others; javascript:/http: never ship)."""
    u = (url or "").strip()
    return u if _SAFE_URL.match(u) else None


def link(label: str, url: Optional[str]) -> str:
    u = safe_url(url)
    return f'<a href="{html.escape(u, quote=True)}">{esc(label)}</a>' if u else esc(label)


def cc_base() -> str:
    try:
        from scripts.lib.comms_editor import cc_base as _cc  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        from lib.comms_editor import cc_base as _cc  # type: ignore  # noqa: PLC0415
    return _cc()


def cc_symbol_url(symbol: str) -> str:
    return f"{cc_base()}/v3/watch/intelligence/{quote(symbol.upper())}"


def finviz_url(symbol: str) -> str:
    return f"https://finviz.com/quote.ashx?t={quote(symbol.upper())}"


def yahoo_url(symbol: str) -> str:
    return f"https://finance.yahoo.com/quote/{quote(symbol.upper())}"


def chart_image_url(symbol: str) -> str:
    """Daily candlestick PNG (Finviz). Measured 2026-09-14: HTTP 200 image/png."""
    return f"https://charts2-node.finviz.com/chart.ashx?cs=l&t={quote(symbol.upper())}&tf=d&s=linear&ct=candle_stick"


def symbol_links(symbol: str) -> str:
    s = symbol.upper()
    return f"{link(s + ' in Command Center', cc_symbol_url(s))} · {link('Finviz', finviz_url(s))} · {link('Yahoo', yahoo_url(s))}"


@dataclass
class RichMessage:
    """What a message says, in parts. `render()` turns it into Telegram HTML + buttons + preview."""
    title: str                                   # plain text; rendered bold
    marker: str = ""                             # leading emoji (colour by marker, not by text)
    symbols: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)            # one line of key numbers each (plain text)
    why: Optional[str] = None                                  # short reason -> quote
    evidence: list[str] = field(default_factory=list)          # deep context -> expandable quote
    sources: list[tuple[str, str]] = field(default_factory=list)   # (label, https url)
    buttons: list[tuple[str, str]] = field(default_factory=list)   # (label, https url)
    chart_symbol: Optional[str] = None                             # chart preview at the top
    pills: list[str] = field(default_factory=list)
    footer: Optional[str] = None
    authority: str = AUTHORITY

    def render(self) -> dict[str, Any]:
        head = f"{self.marker + ' ' if self.marker else ''}<b>{esc(self.title)}</b>"
        parts = [head]
        if self.symbols:
            parts.append(" · ".join(symbol_links(s) for s in self.symbols[:3]))
        parts.extend(esc(f) for f in self.facts if f)
        if self.why:
            parts.append(f"<blockquote>{esc(self.why)}</blockquote>")
        tail: list[str] = []
        if self.sources:
            srcs = [link(label, url) for label, url in self.sources if safe_url(url)]
            if srcs:
                tail.append("Sources: " + " · ".join(srcs[:6]))
        meta = [p for p in self.pills if p]
        if self.footer:
            meta.append(self.footer)
        meta.append(self.authority)
        tail.append(f"<i>{esc(' · '.join(meta))}</i>")
        body = "\n".join(parts)
        closing = "\n" + "\n".join(tail)
        evidence = [e for e in self.evidence if e]
        text = body + closing
        if evidence:
            room = MAX_TEXT - len(text) - len("\n<blockquote expandable></blockquote>") - 16
            kept: list[str] = []
            used = 0
            for line in evidence:
                piece = esc(line)
                if used + len(piece) + 1 > room:
                    kept.append("…")
                    break
                kept.append(piece)
                used += len(piece) + 1
            if kept and kept != ["…"]:
                text = body + "\n<blockquote expandable>" + "\n".join(kept) + "</blockquote>" + closing
        if len(text) > MAX_TEXT:
            text = text[: MAX_TEXT - 1] + "…"
        buttons = [(label, url) for label, url in self.buttons if safe_url(url)]
        if not buttons and self.symbols:
            s = self.symbols[0].upper()
            buttons = [("📊 Command Center", cc_symbol_url(s)), ("📈 Finviz", finviz_url(s)), ("💹 Yahoo", yahoo_url(s))]
        reply_markup = ({"inline_keyboard": [[{"text": label, "url": url} for label, url in buttons[:3]]]}
                        if buttons else None)
        preview = ({"url": chart_image_url(self.chart_symbol), "prefer_large_media": True, "show_above_text": True}
                   if self.chart_symbol else {"is_disabled": True})
        return {"text": text, "parse_mode": "HTML", "reply_markup": reply_markup, "link_preview_options": preview}


# ── layouts per message type ────────────────────────────────────────────────

def _num(v: Any, fmt: str) -> str:
    try:
        return fmt.format(float(v))
    except (TypeError, ValueError):
        return "?"


def go_alert(row: dict[str, Any], *, tier: str, passed: Iterable[str]) -> RichMessage:
    sym = str(row.get("symbol") or "").upper()
    gap = row.get("gap_pct") if row.get("gap_pct") is not None else row.get("change_pct")
    catalyst = str(row.get("catalyst") or "").strip()
    return RichMessage(
        marker="🔥" if tier == "A+" else "✅",
        title=f"{'A+' if tier == 'A+' else 'GO'} {sym} — momentum scalp setup",
        symbols=[sym],
        facts=[
            f"Price {_num(row.get('price'), '${:.2f}')} · gap {_num(gap, '{:+.1f}%')} · RVOL {_num(row.get('rvol'), '{:.1f}x')}"
            f" · float {_num(row.get('float_m'), '{:.1f}M')} · volume {_num(row.get('volume'), '{:,.0f}')}",
            f"Score {_num(row.get('score'), '{:.0f}')} · scan {row.get('run_label') or ''} {str(row.get('scanned_at') or '')[:16]}",
        ],
        why=f"Catalyst: {catalyst}" if catalyst else None,
        evidence=["Meets Trade-AI scalp criteria: " + ", ".join(passed),
                  "Advisory only — no order, size or stop is placed from this alert."],
        sources=[(f"{sym} news", row.get("catalyst_url") or ""), ("Finviz", finviz_url(sym))],
        chart_symbol=sym,
        pills=["🟢 Trade-AI data"],
    )


def entry_alert(item: dict[str, Any]) -> RichMessage:
    sym = str(item.get("symbol") or "").upper()
    state = str(item.get("state") or "").upper()
    marker = "🟢" if state == "READY" else "🟡" if "NEAR" in state else "⚪"
    facts = [
        f"Setup {item.get('setup') or '—'} · now {_num(item.get('price'), '${:.2f}')}"
        f" · zone {_num(item.get('zone_low'), '${:.2f}')}–{_num(item.get('zone_high'), '${:.2f}')}",
        f"Stop {_num(item.get('stop'), '${:.2f}')} · target {_num(item.get('target'), '${:.2f}')} · R:R {_num(item.get('rr'), '{:.1f}')}",
    ]
    ladder = [str(x) for x in (item.get("exit_ladder") or [])]
    return RichMessage(marker=marker, title=f"{state or 'ENTRY'} — {sym} (advisory)", symbols=[sym], facts=facts,
                       why=item.get("why"), evidence=ladder, chart_symbol=sym, pills=["🟢 Trade-AI data"],
                       sources=[(label, url) for label, url in (item.get("sources") or [])])


def material_change(items: list[dict[str, Any]]) -> RichMessage:
    lines: list[str] = []
    sources: list[tuple[str, str]] = []
    for it in items[:8]:
        sym = str(it.get("symbol") or "").upper()
        lines.append(f"{sym} — {it.get('kind') or 'change'}: {it.get('headline') or ''}".strip())
        if it.get("url"):
            sources.append((f"{sym} source", it["url"]))
    syms = [str(it.get("symbol") or "").upper() for it in items if it.get("symbol")]
    return RichMessage(marker="⚡", title=f"Material change — {len(items)} name(s) worth a look", symbols=syms[:3],
                       facts=[", ".join(syms[:10])], evidence=lines, sources=sources, pills=["🟢 Trade-AI data"],
                       buttons=[("📊 Command Center", f"{cc_base()}/v3/watch")] if syms else [])


def desk_answer(*, title: str, body_lines: list[str], symbols: list[str], sources: list[tuple[str, str]],
                pills: list[str], evidence: Optional[list[str]] = None) -> RichMessage:
    return RichMessage(marker="🧠", title=title, symbols=symbols, facts=body_lines, evidence=evidence or [],
                       sources=sources, pills=pills, chart_symbol=symbols[0] if len(symbols) == 1 else None)


__all__ = ["RichMessage", "cc_symbol_url", "chart_image_url", "desk_answer", "entry_alert", "finviz_url",
           "go_alert", "link", "material_change", "safe_url", "symbol_links", "yahoo_url"]
