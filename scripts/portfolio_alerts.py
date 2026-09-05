"""portfolio_alerts.py — Trade AI v12 Portfolio Intelligence
Sends Telegram alerts for:
  - Upcoming earnings dates (next 7 days)
  - Upcoming ex-dividend dates (next 14 days)
  - Analyst upgrades/downgrades (last 3 days)
  - Strategic portfolio alerts (price drops, concentration, rebalancing)
  - Monthly Roth conversion reminder

Uses FMP + Finnhub APIs (already in .env).
Integrates with existing Trade AI v12 Telegram bot.
"""
from __future__ import annotations

import json
import os
import sys
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Config ────────────────────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    val = os.getenv(key, default).strip()
    if not val:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            val = os.getenv(key, default).strip()
        except Exception:
            pass
    return val

def _load_env_from_file(project_root: Path) -> None:
    env_file = project_root / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip("\"'"))


# ── Telegram sender ───────────────────────────────────────────────────────────

def _send_telegram(message: str, project_root: Path,
                   bundle: Optional[Dict[str, str]] = None, bundle_key: Optional[str] = None) -> bool:
    """Send via central Telegram chokepoint, or defer to morning command bundle."""
    if not message:
        return False
    if bundle is not None and bundle_key:
        try:
            from morning_command_digest import append_section
            append_section(bundle, bundle_key, message)
        except Exception:
            bundle[bundle_key] = message
        return True
    _load_env_from_file(project_root)
    try:
        from telegram_alert import send_telegram
        return send_telegram(message)
    except Exception as e:
        print(f"  [alerts] Telegram send error: {e}")
        return False


# ── Get portfolio tickers ─────────────────────────────────────────────────────

def _get_stock_tickers(portfolio: Dict) -> List[str]:
    """Get list of real stock/ETF tickers (skip funds, cash, loans, revoked)."""
    skip = {"CASH", "401K-LOAN", "SRNE", "CDEX", "LPIH", "628518102"}
    skip_prefixes = ("FID-", "SP500-", "VANG-FTSE", "TRP-", "JPM-LGCG",
                     "SS-", "WM-BLAIR", "AB-DISC", "FID-DIV")
    tickers = set()
    for h in portfolio.get("holdings", []):
        sym = h.get("symbol", "").upper()
        if (sym and sym not in skip
            and not any(sym.startswith(p) for p in skip_prefixes)
            and (h.get("market_value") or 0) > 200
            and not h.get("is_loan") and not h.get("is_cash")):
            tickers.add(sym)
    return sorted(tickers)


# ── Earnings Calendar ─────────────────────────────────────────────────────────

def fetch_earnings_alerts(tickers: List[str], project_root: Path,
                          days_ahead: int = 7) -> List[Dict]:
    """Get upcoming earnings dates for portfolio holdings via FMP."""
    _load_env_from_file(project_root)
    fmp_key = _env("FMP_API_KEY") or _env("FINANCIAL_MODELING_PREP_KEY")
    if not fmp_key:
        return []

    today     = datetime.now()
    end_date  = today + timedelta(days=days_ahead)
    from_str  = today.strftime("%Y-%m-%d")
    to_str    = end_date.strftime("%Y-%m-%d")

    try:
        url = (f"https://financialmodelingprep.com/api/v3/earning_calendar"
               f"?from={from_str}&to={to_str}&apikey={fmp_key}")
        data = requests.get(url, timeout=15).json()
        if not isinstance(data, list):
            return []

        ticker_set = set(tickers)
        results = []
        for item in data:
            sym = item.get("symbol","").upper()
            if sym in ticker_set:
                eps_est  = item.get("epsEstimated")
                rev_est  = item.get("revenueEstimated")
                date_str = item.get("date","")
                time_str = item.get("time","")
                results.append({
                    "symbol":        sym,
                    "date":          date_str,
                    "time":          time_str,  # "amc" = after market close, "bmo" = before open
                    "eps_estimate":  eps_est,
                    "rev_estimate":  rev_est,
                    "days_away":     (datetime.strptime(date_str, "%Y-%m-%d") - today).days
                                     if date_str else 99,
                })
        results.sort(key=lambda x: x.get("days_away", 99))
        return results

    except Exception as e:
        print(f"  [alerts] Earnings fetch error: {e}")
        return []


# ── Dividend Calendar ─────────────────────────────────────────────────────────

def fetch_dividend_alerts(tickers: List[str], project_root: Path,
                          days_ahead: int = 14) -> List[Dict]:
    """Get upcoming ex-dividend dates for portfolio holdings via FMP."""
    _load_env_from_file(project_root)
    fmp_key = _env("FMP_API_KEY") or _env("FINANCIAL_MODELING_PREP_KEY")
    if not fmp_key:
        return []

    today    = datetime.now()
    end_date = today + timedelta(days=days_ahead)
    from_str = today.strftime("%Y-%m-%d")
    to_str   = end_date.strftime("%Y-%m-%d")

    try:
        url = (f"https://financialmodelingprep.com/api/v3/stock_dividend_calendar"
               f"?from={from_str}&to={to_str}&apikey={fmp_key}")
        data = requests.get(url, timeout=15).json()
        if not isinstance(data, list):
            return []

        ticker_set = set(tickers)
        results = []
        for item in data:
            sym = item.get("symbol","").upper()
            if sym in ticker_set:
                ex_date  = item.get("date","")
                pay_date = item.get("paymentDate","")
                dividend = item.get("dividend", 0)
                results.append({
                    "symbol":       sym,
                    "ex_date":      ex_date,
                    "pay_date":     pay_date,
                    "dividend":     dividend,
                    "days_to_exdiv": (datetime.strptime(ex_date, "%Y-%m-%d") - today).days
                                      if ex_date else 99,
                })
        results.sort(key=lambda x: x.get("days_to_exdiv", 99))
        return results

    except Exception as e:
        print(f"  [alerts] Dividend fetch error: {e}")
        return []


# ── Analyst Upgrades/Downgrades ───────────────────────────────────────────────

def fetch_analyst_alerts(tickers: List[str], project_root: Path,
                         days_back: int = 3) -> List[Dict]:
    """Get recent analyst upgrades/downgrades via Finnhub."""
    _load_env_from_file(project_root)
    finnhub_key = _env("FINNHUB_API_KEY")
    if not finnhub_key:
        return []

    today    = datetime.now()
    from_str = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    to_str   = today.strftime("%Y-%m-%d")

    results = []
    # Check top holdings only (avoid rate limits)
    priority = ["V","FCNTX","LMT","NOC","AVAV","KTOS","RKLB","CSWC","PFLT",
                "PFE","RTX","SCHG","SCHD","BND","ARKG","ARKQ"]
    check_tickers = [t for t in priority if t in tickers] + \
                    [t for t in tickers if t not in priority][:10]

    for sym in check_tickers[:15]:  # cap at 15 to avoid rate limits
        try:
            url = (f"https://finnhub.io/api/v1/stock/recommendation"
                   f"?symbol={sym}&token={finnhub_key}")
            data = requests.get(url, timeout=10).json()
            if not isinstance(data, list) or not data:
                continue

            # Most recent recommendation
            latest = data[0]
            rec_date = latest.get("period","")
            if rec_date >= from_str:
                results.append({
                    "symbol":       sym,
                    "date":         rec_date,
                    "strong_buy":   latest.get("strongBuy", 0),
                    "buy":          latest.get("buy", 0),
                    "hold":         latest.get("hold", 0),
                    "sell":         latest.get("sell", 0),
                    "strong_sell":  latest.get("strongSell", 0),
                    "consensus":    _consensus(latest),
                })
        except Exception:
            continue

    return results


def _consensus(rec: Dict) -> str:
    sb = rec.get("strongBuy",0) + rec.get("buy",0)
    ss = rec.get("strongSell",0) + rec.get("sell",0)
    h  = rec.get("hold",0)
    total = sb + ss + h
    if total == 0: return "UNKNOWN"
    buy_pct = sb / total
    sell_pct = ss / total
    if buy_pct >= 0.6:   return "STRONG BUY"
    elif buy_pct >= 0.4: return "BUY"
    elif sell_pct >= 0.4: return "SELL"
    elif sell_pct >= 0.2: return "HOLD/SELL"
    else:                return "HOLD"


# ── Strategic Portfolio Alerts ────────────────────────────────────────────────

def generate_strategic_alerts(portfolio: Dict, analysis: Dict,
                               prev_state_path: Optional[Path] = None) -> List[Dict]:
    """Generate strategic alerts based on portfolio changes and thresholds."""
    alerts = []
    totals  = portfolio.get("portfolio_totals", {})
    flags   = analysis.get("critical_flags", [])
    day_pnl = totals.get("day_change", 0)
    total   = totals.get("total_value", 0)

    # Large day move
    if abs(day_pnl) > 5000:
        direction = "📈 UP" if day_pnl > 0 else "📉 DOWN"
        alerts.append({"type": "DAY_MOVE", "severity": "HIGH",
                        "msg": f"Portfolio {direction} ${abs(day_pnl):,.0f} today ({day_pnl/total*100:+.2f}%)"})

    # V concentration (persistent flag)
    v_holdings = [h for h in portfolio.get("holdings",[]) if h.get("symbol","")=="V"]
    v_mv = sum(h.get("market_value",0) for h in v_holdings)
    v_pct = v_mv / total * 100 if total > 0 else 0
    if v_pct > 25:
        alerts.append({"type": "CONCENTRATION", "severity": "WARNING",
                        "msg": f"V (Visa) = {v_pct:.1f}% of portfolio (${v_mv:,.0f}) — concentration HIGH"})

    # Individual stock drops > 5%
    for h in portfolio.get("holdings", []):
        day_chg_pct = h.get("day_change_pct") or 0
        sym = h.get("symbol","")
        mv  = h.get("market_value",0) or 0
        if day_chg_pct < -5 and mv > 2000:
            alerts.append({"type": "PRICE_DROP", "severity": "HIGH",
                            "msg": f"{sym}: {day_chg_pct:+.1f}% today (${mv:,.0f} position)"})
        elif day_chg_pct > 8 and mv > 2000:
            alerts.append({"type": "PRICE_SPIKE", "severity": "INFO",
                            "msg": f"{sym}: {day_chg_pct:+.1f}% today — consider trimming if target hit"})

    # Monthly Roth conversion reminder (1st of month)
    if datetime.now().day == 1:
        alerts.append({"type": "ROTH_REMINDER", "severity": "INFO",
                        "msg": ("💡 Monthly Roth reminder: Review conversion amount for this month.\n"
                                "Sweet spot: $25K-$51K total 2026. Already done: $35K.\n"
                                "~$16K safe room at 22% bracket. Check AI Analyst tab for full analysis.")})

    # Rebalancing threshold exceeded
    from portfolio_rebalancer import compute_rebalancing
    rebal = compute_rebalancing(portfolio)
    if rebal.get("total_to_rebalance", 0) > 200000:
        alerts.append(build_rebalance_alert(rebal))

    return alerts


def build_rebalance_alert(rebal: Dict) -> Dict:
    """The daily drift-based rebalance alert, verified before it's built.

    Audit finding H1: the weekly gemma3-tier verifier never covers this path
    (different table, different cadence) — this was the platform's one
    unverified recommendation surface an operator actually acts on. Runs the
    same SSDI/IRMAA/tax compliance check inline via
    rebalance_verifier.verify_daily_rebalance_orders before the alert is
    built, not after. A failed/unavailable check (no API key, network error)
    must never suppress the underlying drift alert — it just proceeds
    without a compliance stamp, same as before this fix existed.
    """
    total = rebal.get("total_to_rebalance", 0)
    msg = f"Rebalancing: ${total:,.0f} net to move — check Rebalancing tab"
    severity = "WARNING"
    try:
        from rebalance_verifier import verify_daily_rebalance_orders
        compliance = verify_daily_rebalance_orders(
            rebal.get("rebalance_orders") or [], total_to_rebalance=total)
        critical = compliance.get("critical_flags") or []
        if critical:
            severity = "CRITICAL"
            msg = "⚠️ COMPLIANCE FLAG — " + "; ".join(critical) + "\n" + msg
    except Exception as exc:
        print(f"  [alerts] rebalance compliance check failed (alert still sent): {exc}")
    return {"type": "REBALANCE", "severity": severity, "msg": msg}


# ── Format Telegram Messages ──────────────────────────────────────────────────

def format_earnings_message(earnings: List[Dict]) -> str:
    if not earnings:
        return ""
    lines = ["📊 <b>EARNINGS THIS WEEK — YOUR HOLDINGS</b>"]
    for e in earnings[:8]:
        sym   = e.get("symbol","")
        date  = e.get("date","")
        time  = e.get("time","")
        days  = e.get("days_away", 0)
        eps   = e.get("eps_estimate")
        timing = "🌙 After Close" if time == "amc" else "🌅 Pre-Market" if time == "bmo" else ""
        eps_str = f" | EPS est: ${eps:.2f}" if eps else ""
        day_str = "TODAY" if days == 0 else f"in {days}d" if days > 0 else "TOMORROW" if days == 1 else date
        lines.append(f"  <b>{sym}</b> — {date} ({day_str}) {timing}{eps_str}")
    return "\n".join(lines)


def format_dividend_message(divs: List[Dict]) -> str:
    if not divs:
        return ""
    lines = ["💰 <b>UPCOMING EX-DIVIDEND DATES — YOUR HOLDINGS</b>"]
    for d in divs[:8]:
        sym    = d.get("symbol","")
        ex_dt  = d.get("ex_date","")
        pay_dt = d.get("pay_date","")
        amount = d.get("dividend",0)
        days   = d.get("days_to_exdiv", 0)
        day_str = "TODAY ⚡" if days == 0 else f"in {days}d" if days > 0 else ex_dt
        amt_str = f" | ${amount:.4f}/share" if amount else ""
        pay_str = f" | Pay: {pay_dt}" if pay_dt else ""
        lines.append(f"  <b>{sym}</b> — Ex-div {ex_dt} ({day_str}){amt_str}{pay_str}")
    return "\n".join(lines)


def format_analyst_message(ratings: List[Dict]) -> str:
    if not ratings:
        return ""
    lines = ["🎯 <b>ANALYST RATINGS — YOUR HOLDINGS</b>"]
    for r in ratings[:8]:
        sym  = r.get("symbol","")
        cons = r.get("consensus","")
        sb   = r.get("strong_buy",0) + r.get("buy",0)
        ss   = r.get("strong_sell",0) + r.get("sell",0)
        h    = r.get("hold",0)
        emoji = "🟢" if "BUY" in cons else "🔴" if "SELL" in cons else "🟡"
        lines.append(f"  {emoji} <b>{sym}</b>: {cons} — Buy:{sb} Hold:{h} Sell:{ss}")
    return "\n".join(lines)


def format_strategic_message(alerts: List[Dict], portfolio: Dict) -> str:
    if not alerts:
        return ""
    totals  = portfolio.get("portfolio_totals", {})
    total   = totals.get("total_value",0)
    day_pnl = totals.get("day_change",0)
    sign    = "+" if day_pnl >= 0 else "-"
    pct     = day_pnl / total * 100 if total else 0
    lines   = [
        f"💼 <b>PORTFOLIO INTELLIGENCE — {datetime.now().strftime('%b %d, %Y')}</b>",
        f"Total: ${total:,.0f}  |  Today: {sign}${abs(day_pnl):,.0f} ({pct:+.2f}%)\n",
    ]
    for a in alerts:
        sev = a.get("severity","INFO")
        emoji = "🚨" if sev=="CRITICAL" else "⚠️" if sev=="HIGH" else "💡" if sev=="INFO" else "⚡"
        lines.append(f"{emoji} {a.get('msg','')}")
    return "\n".join(lines)


# ── Daily Alert Coordinator ───────────────────────────────────────────────────

def run_portfolio_alerts(portfolio: Dict, analysis: Dict,
                         project_root: Path,
                         send_earnings: bool = True,
                         send_dividends: bool = True,
                         send_analysts: bool = True,
                         send_strategic: bool = True,
                         bundle: Optional[Dict[str, str]] = None) -> Dict[str, int]:
    """Run all alert checks and send to Telegram. Returns count of alerts sent."""
    _load_env_from_file(project_root)
    tickers = _get_stock_tickers(portfolio)
    sent = {"earnings": 0, "dividends": 0, "analyst": 0, "strategic": 0}

    print(f"  [alerts] Checking {len(tickers)} tickers for alerts...")

    # 1. Strategic alerts (always check)
    if send_strategic:
        strategic = generate_strategic_alerts(portfolio, analysis)
        if strategic:
            msg = format_strategic_message(strategic, portfolio)
            # DB first
            try:
                from alert_event_writer import save_alert_event
                for sa in strategic:
                    sym = None
                    # Extract symbol from PRICE_DROP/SPIKE msgs
                    import re as _re
                    sym_match = _re.match(r'^(\w+):', sa.get("msg", ""))
                    if sym_match:
                        sym = sym_match.group(1)
                    sev = "warning" if sa.get("severity") == "HIGH" else "info"
                    save_alert_event(
                        alert_type="strategic_alert",
                        raw_text=sa.get("msg", "")[:2000],
                        symbol=sym,
                        severity=sev,
                        source_script="portfolio_alerts.py",
                        parsed_payload={"alert_subtype": sa.get("type")},
                        requires_agent_review=sa.get("severity") == "HIGH" and sym is not None,
                    )
            except Exception as e:
                print(f"  [alerts] Alert DB write failed (non-fatal): {e}")
            if msg and _send_telegram(msg, project_root, bundle=bundle, bundle_key="portfolio"):
                sent["strategic"] = len(strategic)
                print(f"  [alerts] ✅ Strategic: {len(strategic)} alerts {'bundled' if bundle else 'sent'}")

    # 2. Earnings (check Mon/Thu or if any within 2 days)
    if send_earnings:
        dow = datetime.now().weekday()  # 0=Mon, 3=Thu
        if dow in (0, 3) or True:  # check daily, filter by days_away
            earnings = fetch_earnings_alerts(tickers, project_root, days_ahead=7)
            if earnings:
                msg = format_earnings_message(earnings)
                if msg and _send_telegram(msg, project_root):
                    sent["earnings"] = len(earnings)
                    print(f"  [alerts] ✅ Earnings: {len(earnings)} upcoming")

    # 3. Dividends (check daily, alert if within 5 days)
    if send_dividends:
        divs = fetch_dividend_alerts(tickers, project_root, days_ahead=14)
        # Only alert if within 5 days
        urgent_divs = [d for d in divs if d.get("days_to_exdiv",99) <= 5]
        if urgent_divs:
            msg = format_dividend_message(urgent_divs)
            if msg and _send_telegram(msg, project_root):
                sent["dividends"] = len(urgent_divs)
                print(f"  [alerts] ✅ Dividends: {len(urgent_divs)} ex-div within 5 days")

    # 4. Analyst ratings (Monday + Thursday)
    if send_analysts:
        dow = datetime.now().weekday()
        if dow in (0, 3):
            ratings = fetch_analyst_alerts(tickers, project_root, days_back=4)
            if ratings:
                msg = format_analyst_message(ratings)
                if msg and _send_telegram(msg, project_root):
                    sent["analyst"] = len(ratings)
                    print(f"  [alerts] ✅ Analyst: {len(ratings)} ratings")

    total_sent = sum(sent.values())
    if total_sent == 0:
        print("  [alerts] No alerts triggered today")
    return sent


if __name__ == "__main__":
    import sys
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.path.insert(0, str(root/"scripts"))
    from portfolio_loader import load_all_portfolios
    from portfolio_analyzer import analyze_portfolio
    p = load_all_portfolios(root)
    a = analyze_portfolio(p)
    run_portfolio_alerts(p, a, root)


def _send_telegram_document(file_path: "Path", caption: str, project_root: "Path") -> bool:
    """Send file via telegram_alert.send_telegram_document chokepoint."""
    if not file_path.exists():
        return False
    sys.path.insert(0, str(project_root / "scripts"))
    try:
        from telegram_alert import send_telegram_document
        ok = bool(send_telegram_document(str(file_path), caption=caption or file_path.name, bypass_router=True))
    except Exception:
        ok = False
    try:
        root = str(project_root)
        if root not in sys.path:
            sys.path.insert(0, root)
        from scripts.lib.comms import CommunicationEvent, publish_communication
        publish_communication(CommunicationEvent(
            direction="OUTBOUND", event_type="alert", message_class="ops",
            producer="portfolio_alerts", subject_key="ops:portfolio_report",
            retention_class="operational", severity="info",
            sanitized_body=(caption or "")[:500], short_summary=(caption or "")[:120],
        ))
    except Exception:
        pass
    return ok


def _docx_to_pdf(docx_path: "Path") -> "Optional[Path]":
    """Convert DOCX to PDF via LibreOffice."""
    import subprocess, shutil as _sh
    pdf_path = docx_path.with_suffix(".pdf")
    if pdf_path.exists():
        return pdf_path
    paths = [
        "soffice", "libreoffice",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
    ]
    for cmd in paths:
        if _sh.which(cmd) or Path(cmd).exists():
            try:
                subprocess.run([cmd, "--headless", "--convert-to", "pdf",
                                "--outdir", str(docx_path.parent), str(docx_path)],
                               timeout=60, capture_output=True)
                if pdf_path.exists():
                    return pdf_path
            except Exception:
                pass
    return None


def send_monthly_report_telegram(docx_path: "Path", portfolio: dict,
                                   ai_analysis: dict, technical: dict,
                                   project_root: "Path") -> None:
    """Send monthly intelligence brief as PDF+DOCX to Telegram."""
    from datetime import datetime as _dt
    total   = portfolio.get("total_value", 0)
    score   = technical.get("portfolio_score", 50)
    changes = len(technical.get("signal_changes",[]))
    crit    = len(technical.get("critical_signals",[]))
    month   = _dt.now().strftime("%B %Y")

    lines = [
        f"<b>Portfolio Intelligence Report — {month}</b>",
        f"Portfolio: <b>${total:,.0f}</b>  |  Tech Score: <b>{score:.0f}/100</b>",
        f"Signal Changes: {changes}  |  Critical: {crit}",
        "",
    ]
    exec_sum = (ai_analysis or {}).get("executive_summary","")
    if exec_sum and len(exec_sum) > 20:
        lines += ["<b>Executive Summary:</b>", exec_sum[:500] + "..."]
    lines.append("Full report attached.")
    _send_telegram("\n".join(lines), project_root)

    pdf_path = _docx_to_pdf(docx_path)
    if pdf_path:
        _send_telegram_document(pdf_path, f"Portfolio Report {month} (PDF)", project_root)
        print(f"  [alerts] PDF sent: {pdf_path.name}")
    if docx_path.exists():
        _send_telegram_document(docx_path, f"Portfolio Report {month} (Word)", project_root)
        print(f"  [alerts] DOCX sent: {docx_path.name}")


def send_technical_alerts(technical: dict, project_root: "Path",
                           is_escalated: bool = False,
                           bundle: Optional[Dict[str, str]] = None) -> int:
    """Send verbose technical signal change alerts to Telegram."""
    if not technical:
        return 0
    changes  = technical.get("signal_changes", [])
    score    = technical.get("portfolio_score", 50)
    grade    = technical.get("portfolio_grade", "yellow")
    if not changes:
        return 0
    ge = {"green":"Green","yellow":"Yellow","red":"Red"}.get(grade,"Yellow")
    header = f"Technical Signal Update\nPortfolio Score: {score:.0f}/100 ({ge})\n{len(changes)} signal changes\n---\n"
    body = ""
    for c in changes[:10]:
        sev = c.get("severity","")
        msg = c.get("msg","")
        mv  = c.get("market_value",0)
        pfx = {"CRITICAL":"CRITICAL","HIGH":"HIGH","WARNING":"NOTE"}.get(sev,"")
        body += f"[{pfx}] {msg}"
        if mv: body += f" (Position: ${mv:,.0f})"
        body += "\n"
    if is_escalated:
        body += "\nEscalated to full analysis — check dashboard."
    sent = _send_telegram(header + body, project_root, bundle=bundle, bundle_key="technical")
    return len(changes) if sent else 0


def send_weekly_digest(portfolio: dict, journal: dict, technical: dict,
                        project_root: "Path") -> None:
    """Send Sunday 8PM weekly brief to Telegram."""
    from datetime import datetime as _dt, timedelta as _td
    import json as _json
    today    = _dt.now()
    week_ago = (today - _td(days=7)).strftime("%Y-%m-%d")
    week_trades = [t for t in journal.get("closed_trades",[])
                   if t.get("close_date","")[:10] >= week_ago]
    week_pnl = sum(t.get("pnl",0) for t in week_trades)
    week_wins = sum(1 for t in week_trades if t.get("pnl",0) > 0)
    week_wr  = round(week_wins/len(week_trades)*100) if week_trades else 0
    total    = portfolio.get("total_value",0)
    score    = technical.get("portfolio_score",50)
    changes  = technical.get("signal_changes",[])

    # v48: Load resolved_sectors + overlap from holdings.json
    _state_dir = Path(project_root) / "data" / "portfolios" / "state"
    _holdings_path = _state_dir / "holdings.json"
    _resolved_sectors = []
    _overlaps = []
    _lookthrough_date = ""
    try:
        _h = _json.loads(_holdings_path.read_text())
        _resolved_sectors = _h.get("resolved_sectors", [])
        _overlaps = _h.get("overlap_analysis", {}).get("overlaps", [])
        _lookthrough_date = _h.get("lookthrough_as_of", "")
    except Exception:
        pass

    # Build sector summary (top 5)
    _sector_lines = ""
    if _resolved_sectors:
        _top5 = _resolved_sectors[:5]
        _sector_lines = "\n".join(
            f"  {s['sector'][:22]:22} {s['pct']:5.1f}%  ${s['value']/1000:.0f}K"
            for s in _top5
        )
        _sector_lines = f"📊 *Sector Exposure* (look-through {_lookthrough_date})\n{_sector_lines}"

    # Build overlap summary
    _overlap_lines = ""
    if _overlaps:
        _ol = "\n".join(
            f"  {o['ticker']}: direct ${o['direct_value']:,.0f} + {o['indirect_via']} ${o['indirect_value']:,.0f}"
            for o in _overlaps[:3]
        )
        _overlap_lines = f"🔁 *Fund Overlaps*\n{_ol}"
    critical = technical.get("critical_signals",[])

    sig_lines = "\n".join(f"  - {c.get('msg','')}" for c in changes[:3])
    if not sig_lines: sig_lines = "  No major technical changes this week"

    action = "Review critical signals before Monday open" if critical else "No immediate action required"

    msg = "\n".join([
        f"Weekly Portfolio Digest — {today.strftime('%A %B %d %Y')}",
        "=" * 40,
        f"Portfolio: ${total:,.0f}",
        f"Technical Score: {score:.0f}/100",
        "=" * 40,
        "Trading Week:",
        f"  Trades: {len(week_trades)} | P&L: ${week_pnl:+,.0f} | Win: {week_wr}%",
        "Technical Changes:",
        sig_lines,
        "Monday Action:",
        f"  {action}",
        "=" * 40,
    ])
    # v48: append sector + overlap to weekly digest
    if _sector_lines:
        msg += f"\n\n{_sector_lines}"
    if _overlap_lines:
        msg += f"\n\n{_overlap_lines}"
    if _send_telegram(msg, project_root):
        print("  [alerts] Weekly digest sent")
