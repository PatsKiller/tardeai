"""
generate_reports_hub.py — Generate reports_hub.html
Central index linking all weekly/monthly reports + daily DOCX briefs.
Called after every weekly and monthly report generation.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path


def generate_reports_hub(project_root: str = ".") -> Path:
    root = Path(project_root)
    reports_dir = root / "data" / "portfolios" / "reports"
    weekly_dir = reports_dir / "weekly"
    monthly_dir = reports_dir / "monthly"
    daily_dir = reports_dir  # daily DOCX are in reports/

    # Gather weekly reports
    weeklies = []
    if weekly_dir.exists():
        for f in sorted(weekly_dir.glob("weekly_*.html"), reverse=True)[:8]:
            json_file = f.with_suffix(".json")
            meta = {}
            if json_file.exists():
                try:
                    meta = json.loads(json_file.read_text())
                except Exception:
                    pass
            w_chg = meta.get("1w_change_pct", 0) or 0
            weeklies.append({
                "date": meta.get("date", f.stem.replace("weekly_", "")),
                "total": meta.get("total_value", 0),
                "change_pct": w_chg,
                "action": meta.get("narratives", {}).get("action", "")[:100],
                "url": f"/data/portfolios/reports/weekly/{f.name}",
            })

    # Gather monthly reports
    monthlies = []
    if monthly_dir.exists():
        for f in sorted(monthly_dir.glob("monthly_*.html"), reverse=True)[:6]:
            json_file = f.with_suffix(".json")
            meta = {}
            if json_file.exists():
                try:
                    meta = json.loads(json_file.read_text())
                except Exception:
                    pass
            monthlies.append({
                "date": meta.get("date", f.stem.replace("monthly_", "")),
                "month": meta.get("month", ""),
                "weeks_used": meta.get("weekly_reports_used", 0),
                "url": f"/data/portfolios/reports/monthly/{f.name}",
            })

    # Gather daily DOCX briefs
    daily_briefs = []
    for f in sorted((root / "data" / "portfolios" / "reports").glob("portfolio_brief_*.docx"), reverse=True)[:14]:
        daily_briefs.append({
            "name": f.stem.replace("portfolio_brief_", ""),
            "url": f"/data/portfolios/reports/{f.name}",
        })

    # Build HTML
    weekly_cards = ""
    for w in weeklies:
        color = "#00e676" if (w["change_pct"] or 0) >= 0 else "#ff5252"
        weekly_cards += f"""
      <a href="{w['url']}" class="report-card" target="_blank">
        <div class="rc-date">{w['date']}</div>
        <div class="rc-val" style="color:{color}">{w['change_pct']:+.2f}%</div>
        <div class="rc-total">${w['total']:,.0f}</div>
        <div class="rc-action">{w['action']}</div>
      </a>"""

    monthly_cards = ""
    for m in monthlies:
        monthly_cards += f"""
      <a href="{m['url']}" class="report-card" target="_blank">
        <div class="rc-date">{m['month'] or m['date']}</div>
        <div class="rc-val">Monthly</div>
        <div class="rc-total">{m['weeks_used']} weeks synthesized</div>
        <div class="rc-action">Sonnet synthesis</div>
      </a>"""

    daily_rows = ""
    for d in daily_briefs:
        daily_rows += f'<a href="{d["url"]}" class="daily-link" target="_blank">📄 {d["name"]}</a>\n'

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    hub_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reports Hub — Portfolio Intelligence</title>
<style>
  :root {{
    --bg:#0d0d1a;--bg2:#141428;--bg3:#1a1a30;
    --border:rgba(255,255,255,.08);--text:#e8e8f0;
    --text2:#b0b0c8;--text3:#7070a0;
    --up:#00e676;--dn:#ff5252;--accent:#2979ff;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:24px;max-width:1000px;margin:0 auto}}
  h1{{font-size:22px;margin-bottom:4px}}
  h2{{font-size:12px;text-transform:uppercase;letter-spacing:1px;color:var(--text3);margin:28px 0 14px;padding-bottom:8px;border-bottom:1px solid var(--border)}}
  .meta{{font-size:11px;color:var(--text3);margin-bottom:28px}}
  .report-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:24px}}
  .report-card{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:14px;text-decoration:none;color:var(--text);transition:border-color .2s;display:block}}
  .report-card:hover{{border-color:var(--accent)}}
  .rc-date{{font-size:11px;color:var(--text3);margin-bottom:6px}}
  .rc-val{{font-size:20px;font-weight:700;margin-bottom:2px}}
  .rc-total{{font-size:12px;color:var(--text2);margin-bottom:6px}}
  .rc-action{{font-size:10px;color:var(--text3);line-height:1.4;border-top:1px solid var(--border);padding-top:6px;margin-top:6px}}
  .daily-grid{{display:flex;flex-wrap:wrap;gap:8px}}
  .daily-link{{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:6px 10px;font-size:11px;color:var(--text2);text-decoration:none}}
  .daily-link:hover{{border-color:var(--accent);color:var(--text)}}
  .nav-bar{{display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap}}
  .nav-btn{{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:8px 14px;font-size:12px;color:var(--text2);text-decoration:none}}
  .nav-btn:hover{{border-color:var(--accent)}}
  .empty{{color:var(--text3);font-size:12px;padding:16px;background:var(--bg2);border-radius:10px;border:1px solid var(--border)}}
  .footer{{margin-top:32px;font-size:10px;color:var(--text3);text-align:center}}
</style>
</head>
<body>
<h1>📊 Reports Hub</h1>
<div class="meta">Portfolio Intelligence v1.2 · Last updated {now}</div>

<div class="nav-bar">
  <a href="/reports/command_center.html" class="nav-btn">⚡ Command Center</a>
  <a href="/reports/portfolio_live.html" class="nav-btn">📈 Portfolio Dashboard</a>
  <a href="/reports/dashboard_live.html" class="nav-btn">🎯 Trade AI Dashboard</a>
</div>

<h2>📅 Weekly Reports (Last 8)</h2>
{f'<div class="report-grid">{weekly_cards}</div>' if weeklies else '<div class="empty">No weekly reports yet. Will be generated Sunday 8PM.</div>'}

<h2>📆 Monthly Reports (Last 6)</h2>
{f'<div class="report-grid">{monthly_cards}</div>' if monthlies else '<div class="empty">No monthly reports yet. Will be generated 1st of each month.</div>'}

<h2>📄 Daily Briefs (Last 14)</h2>
{f'<div class="daily-grid">{daily_rows}</div>' if daily_rows else '<div class="empty">No daily briefs found.</div>'}

<div class="footer">
  Reports Hub · Auto-generated after weekly and monthly runs
  <br>Weekly: Ollama qwen3:14b ($0) · Monthly: Claude Sonnet synthesis
</div>
</body>
</html>"""

    # Save to reports/
    hub_path = root / "reports" / "reports_hub.html"
    hub_path.write_text(hub_html)
    print(f"  [reports-hub] Generated: {hub_path}")
    return hub_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    generate_reports_hub(args.project_root)
