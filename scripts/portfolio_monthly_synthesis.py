"""
portfolio_monthly_synthesis.py — Monthly portfolio intelligence synthesis
Version: 1.0 | April 16, 2026

Runs 1st of month via run_portfolio_monthly.sh
Uses Claude Sonnet to synthesize last 4 weekly Ollama reports
Outputs: HTML + DOCX + Telegram summary

Sonnet sees 4 weeks of context — much richer than blind monthly snapshot.
Adds: Roth conversion progress, Golden Window update, tax optimization.
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
WEEKLY_DIR = PROJECT_ROOT / "data" / "portfolios" / "reports" / "weekly"
MONTHLY_DIR = PROJECT_ROOT / "data" / "portfolios" / "reports" / "monthly"
MONTHLY_DIR.mkdir(parents=True, exist_ok=True)


def _get_env(key: str) -> str:
    val = os.getenv(key, "")
    if val:
        return val
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def _load_weekly_reports(n: int = 4) -> List[Dict]:
    """Load last N weekly JSON reports."""
    if not WEEKLY_DIR.exists():
        return []
    reports = sorted(WEEKLY_DIR.glob("weekly_*.json"))[-n:]
    result = []
    for r in reports:
        try:
            result.append(json.loads(r.read_text()))
        except Exception:
            pass
    return result


def _load_current_state() -> Dict:
    """Load current portfolio state for context."""
    h_path = STATE_DIR / "holdings.json"
    ph_path = STATE_DIR / "performance_history.json"
    data = {}
    if h_path.exists():
        data["holdings"] = json.loads(h_path.read_text())
    if ph_path.exists():
        data["perf"] = json.loads(ph_path.read_text())
    return data


def _sonnet_DEPRECATED(prompt: str, max_tokens: int = 1500) -> str:
    """Deprecated — migrated to llm_lane.generate(lane='deepseek-v4')."""
    try:
        import anthropic
        api_key = _get_env("ANTHROPIC_API_KEY")
        if not api_key:
            return "[Sonnet unavailable — no API key]"
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text.strip()
    except Exception as e:
        return f"[Sonnet error: {e}]"


def _sonnet(prompt: str, max_tokens: int = 1500) -> str:
    """Generate monthly synthesis using DeepSeek v4 (CIO-level reasoning)."""
    try:
        from llm_lane import generate
        return generate(prompt, lane="deepseek-v4", timeout=120)
    except Exception as e:
        return f"[DeepSeek v4 error: {e}]"


def _build_weekly_context(weeklies: List[Dict]) -> str:
    """Build context string from weekly reports for Sonnet."""
    if not weeklies:
        return "No weekly reports available."
    lines = []
    for w in weeklies:
        date = w.get("date", "?")
        total = w.get("total_value", 0)
        w1 = w.get("1w_change_pct", 0) or 0
        ytd = w.get("ytd_change_pct", 0) or 0
        cash = w.get("cash_pct", 0) or 0
        ob = w.get("overbought", [])
        journal_pnl = w.get("journal_pnl", 0) or 0
        lines.append(
            f"Week of {date}: Portfolio ${total:,.0f} | "
            f"1W {w1:+.2f}% | YTD {ytd:+.2f}% | Cash {cash:.1f}% | "
            f"Journal P&L ${journal_pnl:+,.2f} | "
            f"Overbought: {ob if ob else 'none'}"
        )
        # Include narrative if available
        narr = w.get("narratives", {}).get("performance", "")
        if narr:
            lines.append(f"  → {narr[:200]}")
    return "\n".join(lines)


def _generate_synthesis(weeklies: List[Dict], current: Dict) -> Dict:
    """Generate all monthly synthesis sections using Sonnet."""
    weekly_context = _build_weekly_context(weeklies)
    holdings = current.get("holdings", {})
    totals = holdings.get("portfolio_totals", {})
    total_val = totals.get("total_value", 0) or 0
    perf = current.get("perf", {})
    periods = perf.get("periods", {})
    p1m = periods.get("1M", {})
    pytd = periods.get("YTD", {})
    p1y = periods.get("1Y", {})

    # Cash analysis
    CASH_SYMS = {"CASH", "--", "SNSXX", "SWVXX", "SPRXX"}
    cash_total = sum(
        h.get("market_value", 0) or 0
        for h in holdings.get("holdings", [])
        if h.get("symbol") in CASH_SYMS
    )

    month = datetime.now().strftime("%B %Y")
    narratives = {}

    # Section 1: Monthly synthesis
    prompt1 = f"""You are analyzing John's investment portfolio for {month}.

WEEKLY PERFORMANCE (last 4 weeks):
{weekly_context}

CURRENT STATE:
Total: ${total_val:,.0f}
1M: {p1m.get('change_pct', 0) or 0:+.2f}% (${p1m.get('change', 0) or 0:+,.0f})
YTD: {pytd.get('change_pct', 0) or 0:+.2f}% (${pytd.get('change', 0) or 0:+,.0f})
1Y: {p1y.get('change_pct', 0) or 0:+.2f}% (${p1y.get('change', 0) or 0:+,.0f})
Cash: ${cash_total:,.0f}

Write a 4-5 sentence monthly portfolio synthesis. Cover:
1. Overall monthly performance and trend across the 4 weeks
2. What drove the results (positive and negative)
3. Key risk observations
4. One specific opportunity or concern for next month
Be direct and specific. No generic disclaimers."""
    narratives["synthesis"] = _sonnet(prompt1, max_tokens=600)

    # Section 2: Rebalancing
    prompt2 = f"""Portfolio context for {month}:
Total: ${total_val:,.0f}
Monthly change: {p1m.get('change_pct', 0) or 0:+.2f}%
Cash: ${cash_total:,.0f} ({cash_total/total_val*100 if total_val else 0:.1f}%)

Account breakdown from weekly data:
{weekly_context}

Write 2-3 sentences on rebalancing priority for next month.
Should John deploy cash, protect gains, or stay course? Be specific."""
    narratives["rebalancing"] = _sonnet(prompt2, max_tokens=400)

    # Section 3: Roth conversion (Golden Window context)
    prompt3 = f"""John's Roth conversion strategy context:
- Age: 58 (turns 59 August 2026)
- SSDI income: $3,800/month
- Schedule C income: ~$20K/year gross
- MFS (married filing separately) tax status
- 2026 conversion done: $35K already
- Sweet spot: ~$25K/yr = ~$3,547 tax OR ~$50K/yr = ~$15,027 tax
- Golden Window: ages 68.5-73 (disability stops, before RMDs begin)
- Target: Zero RMD Roth
- Rollover IRA: ~$550K (SCHD-heavy)
- Roth IRA current: ~$42K
- Current month: {month}
- YTD portfolio: {pytd.get('change_pct', 0) or 0:+.2f}%

Write 2-3 sentences on Roth conversion guidance for this month.
Should he convert more, wait, or stay at current pace? Be specific about tax bracket."""
    narratives["roth"] = _sonnet(prompt3, max_tokens=400)

    # Section 4: Tax optimization
    prompt4 = f"""Portfolio tax context for {month}:
- Filing: MFS (married filing separately, lived apart)
- SSDI: non-taxable at current income level
- Schedule C: ~$20K gross
- Portfolio YTD: {pytd.get('change_pct', 0) or 0:+.2f}%
- Cash available: ${cash_total:,.0f}
- V (Visa) concentration: ~26% of portfolio, held since IPO 2008

Write 2 sentences on tax optimization opportunity this month.
Any tax-loss harvesting, gain deferral, or timing considerations?"""
    narratives["tax"] = _sonnet(prompt4, max_tokens=300)

    return narratives


def _generate_html(date_str: str, weeklies: List[Dict],
                   current: Dict, narratives: Dict) -> str:
    """Generate monthly HTML report."""
    holdings = current.get("holdings", {})
    totals = holdings.get("portfolio_totals", {})
    total_val = totals.get("total_value", 0) or 0
    perf = current.get("perf", {})
    periods = perf.get("periods", {})
    p1m = periods.get("1M", {})
    pytd = periods.get("YTD", {})
    p1y = periods.get("1Y", {})
    m_chg = p1m.get("change_pct", 0) or 0
    m_color = "#00e676" if m_chg >= 0 else "#ff5252"

    weekly_rows = ""
    for w in weeklies:
        wc = w.get("1w_change_pct", 0) or 0
        color = "#00e676" if wc >= 0 else "#ff5252"
        weekly_rows += f"""
        <tr>
          <td>{w.get('date', '?')}</td>
          <td>${w.get('total_value', 0):,.0f}</td>
          <td style="color:{color}">{wc:+.2f}%</td>
          <td>{w.get('ytd_change_pct', 0) or 0:+.2f}%</td>
          <td>${w.get('journal_pnl', 0) or 0:+,.2f}</td>
        </tr>"""

    month_name = datetime.now().strftime("%B %Y")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monthly Portfolio Report — {month_name}</title>
<style>
  :root {{ --bg:#0d0d1a;--bg2:#141428;--border:rgba(255,255,255,.08);--text:#e8e8f0;--text2:#b0b0c8;--text3:#7070a0;--up:#00e676;--dn:#ff5252;--accent:#2979ff; }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:24px;max-width:900px;margin:0 auto}}
  h1{{font-size:24px;margin-bottom:4px}}
  h2{{font-size:13px;text-transform:uppercase;letter-spacing:1px;color:var(--text3);margin:24px 0 12px}}
  .meta{{font-size:12px;color:var(--text3);margin-bottom:24px}}
  .kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}}
  .kpi{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:16px}}
  .kpi .label{{font-size:10px;text-transform:uppercase;letter-spacing:.7px;color:var(--text3);margin-bottom:6px}}
  .kpi .value{{font-size:20px;font-weight:700}}
  .narrative{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:16px;font-size:13px;line-height:1.7;color:var(--text2)}}
  .highlight{{background:rgba(41,121,255,.08);border:1px solid rgba(41,121,255,.2);border-radius:10px;padding:16px;margin-bottom:16px;font-size:13px;line-height:1.7}}
  .roth-box{{background:rgba(0,230,118,.06);border:1px solid rgba(0,230,118,.2);border-radius:10px;padding:16px;margin-bottom:16px;font-size:13px;line-height:1.7}}
  .section{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:16px}}
  table{{width:100%;border-collapse:collapse;font-size:12px}}
  th{{text-align:left;padding:8px 10px;color:var(--text3);font-weight:400;border-bottom:1px solid var(--border);font-size:10px;text-transform:uppercase}}
  td{{padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.04)}}
  .footer{{margin-top:32px;font-size:10px;color:var(--text3);text-align:center}}
</style>
</head>
<body>
<h1>📈 Monthly Portfolio Report</h1>
<div class="meta">{month_name} · Claude Sonnet synthesis of {len(weeklies)} weekly reports · Trade AI v12</div>

<div class="kpi-grid">
  <div class="kpi"><div class="label">Total Value</div><div class="value">${total_val:,.0f}</div></div>
  <div class="kpi"><div class="label">1 Month</div><div class="value" style="color:{m_color}">{m_chg:+.2f}%</div></div>
  <div class="kpi"><div class="label">YTD</div><div class="value" style="color:{'#00e676' if (pytd.get('change_pct',0) or 0)>=0 else '#ff5252'}">{pytd.get('change_pct',0) or 0:+.2f}%</div></div>
  <div class="kpi"><div class="label">1 Year</div><div class="value" style="color:{'#00e676' if (p1y.get('change_pct',0) or 0)>=0 else '#ff5252'}">{p1y.get('change_pct',0) or 0:+.2f}%</div></div>
</div>

<h2>Monthly Synthesis</h2>
<div class="narrative">{narratives.get('synthesis','—')}</div>

<h2>Weekly Performance Breakdown</h2>
<div class="section">
  <table>
    <tr><th>Week</th><th>Total</th><th>1W Change</th><th>YTD</th><th>Journal P&amp;L</th></tr>
    {weekly_rows if weekly_rows else '<tr><td colspan="5" style="color:var(--text3)">No weekly data available yet</td></tr>'}
  </table>
</div>

<h2>Rebalancing</h2>
<div class="highlight">{narratives.get('rebalancing','—')}</div>

<h2>Roth Conversion — Golden Window Progress</h2>
<div class="roth-box">{narratives.get('roth','—')}</div>

<h2>Tax Optimization</h2>
<div class="narrative">{narratives.get('tax','—')}</div>

<div class="footer">
  Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · Claude Sonnet · Synthesized {len(weeklies)} weekly reports
  <br><a href="/reports/reports_hub.html" style="color:var(--accent)">← Back to Reports Hub</a>
</div>
</body>
</html>"""


def _send_telegram(message: str) -> None:
    from telegram_alert import send_telegram
    ok = send_telegram(message, bypass_router=True)
    if ok:
        print("  [monthly-synthesis] Telegram sent")
    else:
        print("  [monthly-synthesis] Telegram not sent")


def run_monthly_synthesis(project_root: str = ".") -> Optional[Path]:
    """Main entry point."""
    global PROJECT_ROOT, STATE_DIR, WEEKLY_DIR, MONTHLY_DIR
    PROJECT_ROOT = Path(project_root)
    STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
    WEEKLY_DIR = PROJECT_ROOT / "data" / "portfolios" / "reports" / "weekly"
    MONTHLY_DIR = PROJECT_ROOT / "data" / "portfolios" / "reports" / "monthly"
    MONTHLY_DIR.mkdir(parents=True, exist_ok=True)

    print("[monthly-synthesis] Starting monthly portfolio synthesis...")
    date_str = datetime.now().strftime("%Y-%m-%d")
    month_name = datetime.now().strftime("%B %Y")

    weeklies = _load_weekly_reports(4)
    print(f"[monthly-synthesis] Loaded {len(weeklies)} weekly reports")

    current = _load_current_state()
    print("[monthly-synthesis] Generating Sonnet synthesis (4 sections)...")
    narratives = _generate_synthesis(weeklies, current)

    html = _generate_html(date_str, weeklies, current, narratives)
    html_path = MONTHLY_DIR / f"monthly_{date_str}.html"
    html_path.write_text(html)
    print(f"[monthly-synthesis] HTML saved: {html_path}")

    # Save JSON for future reference
    json_path = MONTHLY_DIR / f"monthly_{date_str}.json"
    json_path.write_text(json.dumps({
        "date": date_str,
        "month": month_name,
        "weekly_reports_used": len(weeklies),
        "narratives": narratives,
        "html_path": str(html_path),
    }, indent=2))

    # Cleanup old monthly HTMLs (keep last 6)
    old_reports = sorted(MONTHLY_DIR.glob("monthly_*.html"))
    for old in old_reports[:-6]:
        old.unlink()
        print(f"[monthly-synthesis] Cleaned up {old.name}")

    # Telegram
    holdings = current.get("holdings", {})
    totals = holdings.get("portfolio_totals", {})
    total_val = totals.get("total_value", 0) or 0
    perf = current.get("perf", {})
    p1m = perf.get("periods", {}).get("1M", {})
    m_chg = p1m.get("change_pct", 0) or 0

    tg_msg = (
        f"📈 <b>Monthly Report — {month_name}</b>\n\n"
        f"<b>${total_val:,.0f}</b> | 1M: {m_chg:+.2f}%\n\n"
        f"{narratives.get('synthesis','')[:400]}\n\n"
        f"<i>Roth:</i> {narratives.get('roth','')[:200]}\n\n"
        f"<a href='https://ms01-openclaw.tail163d14.ts.net/data/portfolios/reports/monthly/monthly_{date_str}.html'>📄 Full Report</a>"
    )
    _send_telegram(tg_msg)
    print(f"[monthly-synthesis] Done. Report: {html_path}")
    return html_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    run_monthly_synthesis(args.project_root)
