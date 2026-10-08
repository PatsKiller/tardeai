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

#: NYSE/Nasdaq single-letter common stocks. Bare single letters in prose are
#: otherwise English (P&L → P,L); these bind only with word boundaries / $cashtag.
SINGLE_LETTER_TICKERS = frozenset({
    "B", "C", "D", "F", "H", "K", "L", "M", "O", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
})


def scope_primary_symbols(symbols: Optional[Iterable[str]]) -> list[str]:
    """Turn-scoped primary tickers only: uppercase, deduped, no residual bleed.

    Callers pass the active turn's ``primary_symbols`` / intent symbols. Prior-turn
    names (e.g. TROW left in message body from subject memory) must not appear here.
    """
    out: list[str] = []
    for raw in symbols or []:
        u = str(raw or "").strip().lstrip("$").upper()
        if not u or not u.isalpha() or not (1 <= len(u) <= 5):
            continue
        if u not in out:
            out.append(u)
    return out


def build_outbound_links(
    symbols: Optional[Iterable[str]],
    *,
    surface: str = "intelligence",
) -> str:
    """Command Center / Finviz / Yahoo links for primary symbols only.

    ``symbols=["S"]`` emits S links alone — never secondary/footer bleed for
    residual names mentioned in the message body.
    """
    syms = scope_primary_symbols(symbols)
    if not syms:
        return ""
    if len(syms) == 1:
        return symbol_links(syms[0], surface=surface)
    return " · ".join(symbol_links(s, surface=surface) for s in syms[:3])


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
    """Canonical symbol dossier (Watch Intelligence). Use for research / material-change."""
    return f"{cc_base()}/v3/watch/intelligence/{quote(symbol.upper())}"


def cc_trading_url(symbol: str, *, tab: str = "Scalp") -> str:
    """Actionable Trading Hub deep-link — GO/scalp facts live here, not on Intelligence."""
    return f"{cc_base()}/v3/trading?tab={quote(tab)}&symbol={quote(symbol.upper())}"


def finviz_url(symbol: str) -> str:
    return f"https://finviz.com/quote.ashx?t={quote(symbol.upper())}"


def yahoo_url(symbol: str) -> str:
    return f"https://finance.yahoo.com/quote/{quote(symbol.upper())}"


def chart_image_url(symbol: str) -> str:
    """Daily candlestick PNG (Finviz). Measured 2026-09-14: HTTP 200 image/png."""
    return f"https://charts2-node.finviz.com/chart.ashx?cs=l&t={quote(symbol.upper())}&tf=d&s=linear&ct=candle_stick"


def symbol_links(symbol: str, *, surface: str = "intelligence") -> str:
    s = symbol.upper()
    href = cc_trading_url(s) if surface == "trading" else cc_symbol_url(s)
    return f"{link(s + ' in Command Center', href)} · {link('Finviz', finviz_url(s))} · {link('Yahoo', yahoo_url(s))}"


@dataclass
class RichMessage:
    """What a message says, in parts. `render()` turns it into Telegram HTML + buttons + preview."""

    title: str  # plain text; rendered bold
    marker: str = ""  # leading emoji (colour by marker, not by text)
    symbols: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)  # one line of key numbers each (plain text)
    sections: list[tuple[str, list[str]]] = field(default_factory=list)
    why: Optional[str] = None  # short reason -> quote
    evidence: list[str] = field(default_factory=list)  # deep context -> expandable quote
    sources: list[tuple[str, str]] = field(default_factory=list)  # (label, https url)
    buttons: list[tuple[str, str]] = field(default_factory=list)  # (label, https url)
    chart_symbol: Optional[str] = None  # chart preview at the top
    pills: list[str] = field(default_factory=list)
    footer: Optional[str] = None
    # intelligence = Watch dossier (default); trading = Scalp/scanner facts on Trading Hub
    primary_surface: str = "intelligence"
    authority: str = AUTHORITY  # kept on the payload for receipts; not printed to the operator

    def _primary_url(self, symbol: str) -> str:
        return cc_trading_url(symbol) if self.primary_surface == "trading" else cc_symbol_url(symbol)

    def render(self) -> dict[str, Any]:
        # 2026-09-15 operator review of GO alerts ("needs polishing"): one symbol -> the title itself links to
        # Command Center and the buttons carry Command Center / Finviz / Yahoo, so no second line repeats the
        # same three links; several symbols keep the per-symbol link line.
        # 2026-09-22: scope to turn primary symbols only (purge residual bleed e.g. TROW).
        symbols = scope_primary_symbols(self.symbols)
        single = len(symbols) == 1
        title_html = esc(self.title)
        if single and safe_url(self._primary_url(symbols[0])):
            title_html = link(self.title, self._primary_url(symbols[0]))
        head = f"{self.marker + ' ' if self.marker else ''}<b>{title_html}</b>"
        parts = [head]
        if symbols and not single:
            parts.append(build_outbound_links(symbols[:3], surface=self.primary_surface))
        parts.extend(esc(f) for f in self.facts if f)
        for heading, lines in self.sections:
            clean_heading = esc(heading).upper()
            rendered = [f"<b>{clean_heading}</b>"]
            for line in lines:
                if not line:
                    continue
                if line.startswith("__CODE__:"):
                    rendered.append(f"<code>{esc(line[9:])}</code>")
                else:
                    rendered.append(esc(line))
            if len(rendered) > 1:
                parts.append("\n".join(rendered))
        if self.why:
            parts.append(f"<blockquote>{esc(self.why)}</blockquote>")
        tail: list[str] = []
        button_urls = {url for _, url in self._buttons()}
        if self.sources:
            srcs = [link(label, url) for label, url in self.sources if safe_url(url) and url not in button_urls]
            if srcs:
                tail.append("Source: " + " · ".join(srcs[:6]))
        meta = [p for p in self.pills if p]
        if self.footer:
            meta.append(self.footer)
        if meta:
            tail.append(f"<i>{esc(' · '.join(meta))}</i>")
        body = "\n".join(parts)
        closing = ("\n" + "\n".join(tail)) if tail else ""
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
        buttons = self._buttons()
        reply_markup = (
            {"inline_keyboard": [[{"text": label, "url": url} for label, url in buttons[:3]]]} if buttons else None
        )
        chart_sym = scope_primary_symbols([self.chart_symbol] if self.chart_symbol else symbols[:1])
        preview = (
            {"url": chart_image_url(chart_sym[0]), "prefer_large_media": True, "show_above_text": True}
            if chart_sym
            else {"is_disabled": True}
        )
        return {"text": text, "parse_mode": "HTML", "reply_markup": reply_markup, "link_preview_options": preview,
                "authority": self.authority}

    def _buttons(self) -> list[tuple[str, str]]:
        buttons = [(label, url) for label, url in self.buttons if safe_url(url)]
        symbols = scope_primary_symbols(self.symbols)
        if not buttons and symbols:
            s = symbols[0]
            label = "📊 Trading" if self.primary_surface == "trading" else "📊 Command Center"
            buttons = [
                (label, self._primary_url(s)),
                ("📈 Finviz", finviz_url(s)),
                ("💹 Yahoo", yahoo_url(s)),
            ]
        return buttons


# ── layouts per message type ────────────────────────────────────────────────


def _num(v: Any, fmt: str) -> str:
    try:
        return fmt.format(float(v))
    except (TypeError, ValueError):
        return "?"


def _scan_note(row: dict[str, Any]) -> str:
    """' · scanned 11:22 ET (10:00 run)' from scanned_at '2026-09-15 11:22' and run_label '1000'."""
    at = str(row.get("scanned_at") or "")
    hhmm = at[11:16] if len(at) >= 16 else ""
    run = str(row.get("run_label") or "")
    run_txt = f"{run[:2]}:{run[2:]} run" if len(run) == 4 and run.isdigit() else (f"{run} run" if run else "")
    if not hhmm and not run_txt:
        return ""
    return " · scanned " + " ".join(x for x in (f"{hhmm} ET" if hhmm else "", f"({run_txt})" if run_txt else "") if x)


def held_pill(held: Optional[bool]) -> list[str]:
    """B3 (2026-09-16): triage label — HELD vs NOT HELD. None = not determined (never guessed)."""
    if held is None:
        return []
    return ["🟢 HELD — in book" if held else "⚪ NOT HELD"]


def go_alert(row: dict[str, Any], *, tier: str, passed: Iterable[str],
             held: Optional[bool] = None) -> RichMessage:
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
            f"Score {_num(row.get('score'), '{:.0f}')}" + _scan_note(row),
        ],
        why=f"Catalyst: {catalyst}" if catalyst else None,
        evidence=[
            "Meets Trade-AI scalp criteria: " + ", ".join(passed),
            "Advisory only — no order, size or stop is placed from this alert.",
        ],
        sources=[(f"{sym} news", row.get("catalyst_url") or ""), ("Finviz", finviz_url(sym))],
        chart_symbol=sym,
        pills=["🟢 Trade-AI data"] + held_pill(held),
        # Scalp score/gap/RVOL/float live on Trading Hub Scalp tab — not Watch Intelligence.
        primary_surface="trading",
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
    if item.get("advice"):
        facts.append(f"Proposal advice: {item['advice']}")
    ladder = [str(x) for x in (item.get("exit_ladder") or [])]
    if item.get("invalidation"):
        ladder.append(f"Invalidation: {item['invalidation']}")
    ladder.append("Advisory only — nothing queued, nothing executed.")
    return RichMessage(
        marker=marker,
        title=f"{state or 'ENTRY'} ENTRY ALERT — {sym} (advisory)",
        symbols=[sym],
        facts=facts,
        why=item.get("why"),
        evidence=ladder,
        chart_symbol=sym,
        pills=["🟢 Trade-AI data"] + held_pill(item.get("held")),
        sources=[(label, url) for label, url in (item.get("sources") or [])],
        # Entry zone/stop/R:R actionable path is Trading (deep-link symbol); dossier stays secondary.
        primary_surface="trading",
    )


def _card_money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _card_ratio(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "—"


def _card_pct(value: Any) -> str:
    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return "—"


def _card_text(value: Any, *, limit: int = 240) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = " · ".join(str(x).strip() for x in value if str(x).strip())
    return " ".join(str(value).split()).strip()[:limit].rstrip("+").rstrip()


def _card_bar(value: Any, *, inverse: bool = False) -> str:
    """Display-only ten-cell gauge; missing facts stay unavailable."""
    try:
        n = max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return "□□□□□□□□□□ unavailable"
    filled = max(0, min(10, round(n * 10)))
    label = "elevated" if inverse and n >= 0.6 else "moderate" if inverse else "attractive" if n >= 0.6 else "limited"
    return f"{'■' * filled}{'□' * (10 - filled)} {label}"


def cio_entry_alert(item: dict[str, Any]) -> RichMessage:
    """Compact CIO decision card shared by entry, watchlist and review producers.

    Values are copied from the supplied packet. This formatter does not calculate
    investment claims beyond deterministic distance/gauge presentation.
    """
    sym = str(item.get("symbol") or "").upper()
    state = str(item.get("state") or item.get("status") or "ENTRY").upper()
    held = item.get("held")
    hard_block = item.get("first_hard_block") or item.get("invalidation")
    stance = str(item.get("cio_stance") or item.get("cio_action") or "HUMAN REVIEW").replace("_", " ").upper()
    if hard_block and state in {"BLOCKED", "INVALIDATED"}:
        marker = "🔴"
    elif held is True:
        marker = "🟡"
    elif state in {"BUY_READY", "READY"} and (item.get("cio_review_id") or item.get("cio_review_status") == "REVIEWED"):
        # Green only when the CIO actually reviewed it (operator 2026-10-05, VCIG: an unreviewed
        # BUY READY rendered green twice). Unreviewed stays amber below.
        marker = "🟢"
    elif "NEAR" in state or "REVIEW" in stance or stance in {"WATCH", "RESEARCH MORE"}:
        marker = "🟡"
    else:
        marker = "⚪"

    price = item.get("price")
    low, high = item.get("entry_low", item.get("zone_low")), item.get("entry_high", item.get("zone_high"))
    stop, target = item.get("stop"), item.get("target")
    ideal_rr = item.get("rr_at_ideal_entry", item.get("rr", item.get("ideal_rr")))
    current_rr = item.get("rr_at_current_price", item.get("current_rr"))
    try:
        risk = (float(price) - float(stop)) if price is not None and stop is not None else None
        reward = (float(target) - float(price)) if price is not None and target is not None else None
        total = risk + reward if risk is not None and reward is not None else None
        risk_fraction = min(1.0, max(0.0, risk / total)) if total and risk is not None else None
        reward_fraction = min(1.0, max(0.0, reward / total)) if total and reward is not None else None
    except (TypeError, ValueError, ZeroDivisionError):
        risk_fraction = reward_fraction = None

    price_note = item.get("price_note") or ("inside entry zone" if state in {"BUY_READY", "READY"} else None)
    position = "Existing position" if held is True else "New position" if held is False else "Position status unavailable"
    next_action = item.get("next_action") or ("Hold existing; decide whether to add or wait" if held is True else "Review before allocating capital")
    catalyst = _card_text(item.get("catalyst")) or "Unavailable — research gap"
    options_status = _card_text(item.get("options_status") or item.get("options_summary")) or "Not evaluated"
    option_reasons = [_card_text(x, limit=180) for x in (item.get("options_reasons") or []) if _card_text(x)]
    if option_reasons:
        options_status += "\nReasons: " + " · ".join(option_reasons[:3])
    review_status = item.get("cio_review_status") or ("REVIEWED" if item.get("cio_review_id") else "UNREVIEWED")
    evidence = [str(x) for x in (item.get("evidence") or []) if x]
    evidence.extend(_card_text(x) for x in (item.get("options_reasons") or []) if _card_text(x))
    evidence.extend(str(x) for x in (item.get("exit_ladder") or []) if x)
    if item.get("invalidation"):
        evidence.append(f"Invalidation: {item['invalidation']}")
    if item.get("thesis"):
        evidence.append(f"Thesis: {_card_text(item['thesis'])}")
    if item.get("opposing_case"):
        evidence.append(f"Strongest opposing line: {item['opposing_case']}")
    evidence.extend(["CIO review id: " + str(item["cio_review_id"])] if item.get("cio_review_id") else ["CIO review: unreviewed"])
    evidence.append("Advisory only — nothing queued, nothing executed; no order, size or stop is created from this alert.")

    company = _card_text(item.get("company"), limit=100)
    sector = _card_text(item.get("sector"), limit=80)
    identity = " · ".join(x for x in (company, sector) if x)
    thesis = _card_text(item.get("thesis"), limit=220)
    hard_block_display = _card_text(hard_block, limit=220) or "No hard block recorded — review incomplete"
    time_horizon = _card_text(item.get("time_horizon") or item.get("dte"), limit=80)
    sections = [
        ("CIO VIEW", [f"{marker} {state.replace('_', ' ')}", f"{marker} {stance}",
                       f"Review: {review_status}", f"Next action: {next_action}"]),
        ("IDENTITY", [identity or f"{sym} · identity data unavailable"]),
        ("PRICE SETUP", [
            f"Price {_card_money(price)}" + (f" · {price_note}" if price_note else ""),
            f"Entry zone {_card_money(low)}–{_card_money(high)} · stop {_card_money(stop)} · target {_card_money(target)}",
            f"R:R current {_card_ratio(current_rr)} · ideal-zone {_card_ratio(ideal_rr)}"
            + (f" · distance {_card_pct(item.get('distance_pct'))}" if item.get("distance_pct") is not None else ""),
            f"__CODE__:STOP  ─  ENTRY ZONE  ─  CURRENT  ─  TARGET\n          {_card_money(stop)}     {_card_money(low)}–{_card_money(high)}     {_card_money(price)}     {_card_money(target)}",
        ]),
        ("RISK / REWARD", [
            f"Risk to stop {_card_money(risk)} · {_card_bar(risk_fraction, inverse=True)}",
            f"Reward to target {_card_money(reward)} · {_card_bar(reward_fraction)}",
            f"Expected value: {_card_text(item.get('expected_value')) or 'not provided'}",
        ]),
        ("POSITION IMPACT", [position, f"Shares / weight: {item.get('shares') or '—'} / {item.get('portfolio_weight') or '—'}",
                              f"Capital impact: {item.get('capital_impact') or 'unavailable'}", "Sizing: not provided"]),
        ("CATALYST", [catalyst]),
        ("THESIS", [thesis or "Not provided — research required"]),
        ("OPTIONS REVIEW", [str(options_status)[:300]]),
        ("CIO VERDICT", [f"{marker} {stance}", f"What kills the idea: {hard_block_display}",
                         f"Time horizon: {time_horizon or 'not provided'}"]),
    ]
    # Decision-card layout (operator 2026-10-08: "the ticker becomes the focus"); rollback = config/telegram_cards.yaml.
    try:
        try:
            from scripts.lib import telegram_cards as _tc
        except ImportError:  # pragma: no cover
            from lib import telegram_cards as _tc  # type: ignore
        if _tc.enabled("cio_entry"):
            return _tc.entry_card(item, marker=marker, state=state, stance=stance, held=held,
                                  review_status=str(review_status), next_action=str(next_action),
                                  hard_block=hard_block, evidence=evidence)
    except Exception:  # noqa: BLE001 — a card problem falls back to the proven layout, never to no alert
        pass
    return RichMessage(
        marker=marker,
        title=f"CIO ENTRY ALERT — {sym} · {position}",
        symbols=[sym] if sym else [],
        sections=sections,
        evidence=evidence,
        sources=[(str(label), str(url)) for label, url in (item.get("sources") or [])],
        chart_symbol=sym or None,
        pills=["🟢 Trade-AI data"] + held_pill(held),
        primary_surface="trading",
    )


def material_change(items: list[dict[str, Any]]) -> RichMessage:
    lines: list[str] = []
    sources: list[tuple[str, str]] = []
    for it in items[:8]:
        sym = str(it.get("symbol") or "").upper()
        lines.append(f"{sym} — {it.get('kind') or 'change'}: {it.get('headline') or ''}".strip())
        if it.get("url"):
            sources.append((f"{sym} source", it["url"]))
    syms = [str(it.get("symbol") or "").upper() for it in items if it.get("symbol")]
    return RichMessage(
        marker="⚡",
        title=f"Material change — {len(items)} name(s) worth a look",
        symbols=syms[:3],
        facts=[", ".join(syms[:10])],
        evidence=lines,
        sources=sources,
        pills=["🟢 Trade-AI data"],
        buttons=[("📊 Command Center", f"{cc_base()}/v3/watch")] if syms else [],
    )


def desk_answer(
    *,
    title: str,
    body_lines: list[str],
    symbols: list[str],
    sources: list[tuple[str, str]],
    pills: list[str],
    evidence: Optional[list[str]] = None,
) -> RichMessage:
    return RichMessage(
        marker="🧠",
        title=title,
        symbols=symbols,
        facts=body_lines,
        evidence=evidence or [],
        sources=sources,
        pills=pills,
        chart_symbol=symbols[0] if len(symbols) == 1 else None,
    )


__all__ = [
    "RichMessage",
    "SINGLE_LETTER_TICKERS",
    "build_outbound_links",
    "cc_symbol_url",
    "cc_trading_url",
    "chart_image_url",
    "cio_entry_alert",
    "desk_answer",
    "entry_alert",
    "finviz_url",
    "go_alert",
    "held_pill",
    "link",
    "material_change",
    "safe_url",
    "scope_primary_symbols",
    "symbol_links",
    "yahoo_url",
]
