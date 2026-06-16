"""alerting.py — Email, Slack, and WhatsApp alert delivery.

WhatsApp format:
  ⚡ Trade AI [0700] | 2025-01-15
  GO: ACME (46) RVOL 8.2x 🔥 FDA approval
  GO: WXYZ (42) RVOL 5.1x 📈 Earnings beat
  GO: MNOP (40) RVOL 3.4x 🚀 RVOL threshold
  ─────────────
  🆕 3 new | 📈 2 grade up | 👻 1 faded
"""
from __future__ import annotations
import os, smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Utilities ─────────────────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()

def _enabled(key: str) -> bool:
    return _env(key, "true").lower() == "true"

def _catalyst_emoji(tier: str) -> str:
    return {"high_impact": "🔥", "medium_impact": "⚡", "low_impact": "📰"}.get(tier, "•")


# ── Message builders ──────────────────────────────────────────────────────────

def _build_whatsapp_body(
    scored_tickers: List[Dict[str, Any]],
    delta: Dict[str, Any],
    run_label: str,
    date_str: str,
    market_snapshot: Optional[Dict[str, Any]] = None,
    options_summary: Optional[Dict[str, Any]] = None,
) -> str:
    """Concise, actionable WhatsApp message with full v11 market context."""
    go_tickers = [t for t in scored_tickers if t.get("decision") == "GO"]
    events     = delta.get("events", [])
    new_count  = len(delta.get("new_tickers", []))
    fade_count = len(delta.get("faded", []))
    grade_up   = sum(1 for e in events if e.get("event") == "GRADE_UP")

    lines = [f"\u26a1 *Trade AI v11 [{run_label}]* | {date_str}", ""]

    if market_snapshot:
        indices = market_snapshot.get("indices", {})
        vix     = market_snapshot.get("vix", {})
        breadth = market_snapshot.get("breadth_label", "Neutral")
        leader  = market_snapshot.get("sector_leader", {})
        laggard = market_snapshot.get("sector_laggard", {})
        spy_pct = indices.get("SPY", {}).get("change_percent", 0)
        spy_arr = indices.get("SPY", {}).get("trend_arrow", "\u2192")
        vix_val = vix.get("price", 0)
        vix_dir = vix.get("direction", "flat")
        b_emoji = {"Bullish": "\U0001f7e2", "Neutral": "\U0001f7e1", "Bearish": "\U0001f534"}.get(breadth, "\U0001f7e1")
        v_emoji = "\U0001f4c8" if "rising" in vix_dir or "spik" in vix_dir else "\U0001f4c9"
        lines.append("*\U0001f4ca Market Context:*")
        lines.append(f"  SPY {spy_arr} {spy_pct:+.2f}%  \u00b7  VIX {v_emoji} {vix_val:.1f} ({vix_dir})")
        lines.append(f"  Breadth: {b_emoji} {breadth}")
        if leader.get("symbol"):
            lines.append(f"  \u25b2 Leader: {leader['symbol']} {leader.get('change_percent', 0):+.2f}%")
        if laggard.get("symbol"):
            lines.append(f"  \u25bc Laggard: {laggard['symbol']} {laggard.get('change_percent', 0):+.2f}%")
        lines.append("")

    if go_tickers:
        lines.append("*\U0001f3af GO-Tier Picks:*")
        for t in go_tickers[:5]:
            sym   = t["symbol"]
            score = t["score"]
            rvol  = t.get("relative_volume", 0)
            s_arr = t.get("score_arrow", "\u2192")
            r_arr = t.get("rvol_arrow", "\u2192")
            top   = t.get("top_catalyst") or {}
            cat   = (top.get("title") or "No catalyst")[:55]
            emoji = _catalyst_emoji(t.get("catalyst_tier", "none"))
            lines.append(f"  {emoji} *{sym}* ({score} {s_arr}) RVOL {rvol:.1f}x {r_arr} \u2014 {cat}")
        lines.append("")
    else:
        lines.append("_No GO-tier setups this run._")
        lines.append("")

    if options_summary and options_summary.get("total_sweeps", 0) > 0:
        lines.append(f"*\u26a1 Options Flow:* {options_summary.get('sweep_summary_text', '')}")
        lines.append("")

    delta_parts = []
    if new_count:  delta_parts.append(f"\U0001f195 {new_count} new")
    if grade_up:   delta_parts.append(f"\U0001f4c8 {grade_up} grade \u2191")
    if fade_count: delta_parts.append(f"\U0001f47b {fade_count} faded")
    if delta_parts:
        lines.append("\u2500" * 20)
        lines.append("  ".join(delta_parts))

    return "\n".join(lines)


def _build_email_body(
    scored_tickers: List[Dict[str, Any]],
    delta: Dict[str, Any],
    run_label: str,
    date_str: str,
) -> tuple[str, str]:
    """Returns (plain_text, html) for email."""
    go_tickers = [t for t in scored_tickers if t.get("decision") == "GO"]
    events = delta.get("events", [])

    # Plain text
    lines = [
        f"Trade AI v10 — Run {run_label} — {date_str}",
        "=" * 50,
        "",
        f"Total scanned: {len(scored_tickers)}",
        f"GO-tier: {len(go_tickers)}",
        f"Delta events: {len(events)}",
        "",
        "GO-TIER PICKS",
        "-" * 30,
    ]
    for t in go_tickers[:5]:
        top = t.get("top_catalyst") or {}
        cat = top.get("title", "—")[:70]
        lines.append(
            f"  {t['symbol']:6s}  Score:{t['score']:2d}  RVOL:{t.get('relative_volume',0):.1f}x  "
            f"${t.get('price',0):.2f}  {t.get('change_percent',0):+.1f}%  — {cat}"
        )
    lines += ["", "DELTA", "-" * 30]
    for evt in events[:15]:
        etype = evt.get("event", "")
        sym   = evt.get("symbol", "")
        if etype == "NEW_TICKER":
            lines.append(f"  NEW    {sym}  score={evt.get('score')}  {evt.get('decision')}")
        elif etype in ("GRADE_UP", "GRADE_DOWN"):
            lines.append(f"  {etype:8s} {sym}  {evt.get('prev_score')}→{evt.get('score')}")
        elif etype == "NEW_CATALYST":
            titles = (evt.get("titles") or [])
            lines.append(f"  CAT    {sym}  {titles[0][:60] if titles else '?'}")
        elif etype == "RVOL_THRESHOLD_CROSS":
            lines.append(f"  RVOL   {sym}  crossed {evt.get('threshold')}x (now {evt.get('rvol'):.1f}x)")
        elif etype == "TICKER_FADED":
            lines.append(f"  FADED  {sym}")
    plain = "\n".join(lines)

    # Minimal HTML
    go_rows = ""
    for t in go_tickers[:5]:
        top = t.get("top_catalyst") or {}
        cat = (top.get("title") or "—")[:60]
        dec_color = {"GO": "#0F9D58", "WAIT": "#F4B400"}.get(t["decision"], "#DB4437")
        go_rows += (
            f"<tr>"
            f"<td style='font-weight:bold;color:{dec_color}'>{t['symbol']}</td>"
            f"<td>{t['score']}</td><td>{t['grade']}</td>"
            f"<td style='font-weight:bold;color:{dec_color}'>{t['decision']}</td>"
            f"<td>{t.get('relative_volume',0):.1f}x</td>"
            f"<td>${t.get('price',0):.2f}</td>"
            f"<td>{t.get('change_percent',0):+.1f}%</td>"
            f"<td>{cat}</td>"
            f"</tr>"
        )
    html = f"""
<html><body style="background:#1E1E2E;color:#fff;font-family:monospace;padding:20px">
<h2 style="color:#1A73E8">⚡ Trade AI v10 — Run {run_label} — {date_str}</h2>
<table border="1" cellpadding="5" style="border-collapse:collapse;font-size:12px">
<tr style="background:#2C2C44;color:#9A9AB0">
<th>Symbol</th><th>Score</th><th>Grade</th><th>Decision</th>
<th>RVOL</th><th>Price</th><th>Change</th><th>Catalyst</th>
</tr>
{go_rows}
</table>
<p style="color:#9A9AB0;font-size:11px">Trade AI v10 — Local Python pipeline</p>
</body></html>
"""
    return plain, html


# ── Delivery functions ────────────────────────────────────────────────────────

def send_email(
    subject: str,
    text: str,
    html: str = "",
    attachments: Optional[List[str]] = None,
) -> None:
    if not _enabled("ENABLE_EMAIL"):
        return
    text, html = _norm_urls(text), _norm_urls(html)   # FQDN/v3 normalization chokepoint
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"]    = _env("REPORT_EMAIL_FROM")
    msg["To"]      = _env("REPORT_EMAIL_TO")
    msg.set_content(text or "See attached report.")
    if html:
        msg.add_alternative(html, subtype="html")
    for file in attachments or []:
        p = Path(file)
        if p.exists():
            msg.add_attachment(p.read_bytes(), maintype="application",
                               subtype="octet-stream", filename=p.name)
    with smtplib.SMTP(_env("SMTP_HOST"), int(_env("SMTP_PORT", "587")), timeout=30) as s:
        if _env("SMTP_USE_TLS", "true").lower() == "true":
            s.starttls()
        if _env("SMTP_USERNAME"):
            s.login(_env("SMTP_USERNAME"), _env("SMTP_PASSWORD"))
        s.send_message(msg)


def _norm_urls(text):
    """FQDN/v3 normalization for any outbound notification body (internal IPs + legacy /v2/ -> FQDN /v3/)."""
    try:
        from notification_url_builder import publicize_message
        return publicize_message(text)
    except Exception:
        return text


def send_slack(message: str) -> None:
    if not _enabled("ENABLE_SLACK"):
        return
    url = _env("SLACK_WEBHOOK_URL")
    if not url:
        return
    message = _norm_urls(message)
    try:
        import requests
        requests.post(url, json={"text": message}, timeout=20)
    except Exception as e:
        print(f"[alerting] Slack error: {e}")


def send_whatsapp(message: str) -> None:
    if not _enabled("ENABLE_WHATSAPP"):
        return
    sid   = _env("TWILIO_SID")
    token = _env("TWILIO_AUTH_TOKEN")
    from_ = _env("TWILIO_WHATSAPP_FROM")
    to_   = _env("TWILIO_WHATSAPP_TO")
    if not all([sid, token, from_, to_]):
        print("[alerting] WhatsApp skipped — Twilio credentials incomplete")
        return
    message = _norm_urls(message)
    try:
        from twilio.rest import Client
        client = Client(sid, token)
        client.messages.create(body=message, from_=from_, to=to_)
    except Exception as e:
        print(f"[alerting] WhatsApp error: {e}")


# ── Main dispatcher ───────────────────────────────────────────────────────────

def send_all_alerts(
    scored_tickers: List[Dict[str, Any]],
    delta: Dict[str, Any],
    run_label: str,
    date_str: str,
    attachments: Optional[List[str]] = None,
    market_snapshot: Optional[Dict[str, Any]] = None,
    options_summary: Optional[Dict[str, Any]] = None,
    halt_data: Optional[Dict[str, Any]] = None,
    trade_plans: Optional[Dict[str, Any]] = None,
    short_summary: Optional[Dict[str, Any]] = None,
    social_data: Optional[Dict[str, Any]] = None,
) -> None:
    """Send WhatsApp, Telegram, email, and Slack alerts for a completed run (v12)."""
    whatsapp_body = _build_whatsapp_body(
        scored_tickers, delta, run_label, date_str,
        market_snapshot=market_snapshot,
        options_summary=options_summary,
    )
    send_whatsapp(whatsapp_body)

    # Telegram (v12) — richer format with trade plans + halt data
    try:
        from telegram_alert import build_telegram_message, send_telegram
        tg_body = build_telegram_message(
            scored_tickers, delta, run_label, date_str,
            market_snapshot=market_snapshot,
            options_summary=options_summary,
            halt_data=halt_data,
            trade_plans=trade_plans,
            short_summary=short_summary,
        )
        send_telegram(tg_body)
    except Exception as e:
        print(f"[alerting] Telegram error: {e}")

    # Halt-specific WhatsApp burst (v12)
    if halt_data:
        halted  = halt_data.get("halted_tickers", [])
        resumed = halt_data.get("resumed_tickers", [])
        if halted:
            halt_syms = ", ".join(h["symbol"] for h in halted[:5])
            send_whatsapp(f"🚨 *HALT ALERT* — {halt_syms} trading halted")
        if resumed:
            res_syms = ", ".join(r["symbol"] for r in resumed[:5])
            send_whatsapp(f"✅ *RESUME ALERT* — {res_syms} trading resumed")

    subject = f"Trade AI v12 [{run_label}] {date_str}"
    plain, html = _build_email_body(scored_tickers, delta, run_label, date_str)
    send_email(subject, plain, html, attachments=attachments)

    send_slack(whatsapp_body)
