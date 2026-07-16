"""
generate_reports_hub.py — Generate reports_hub.html
Central index linking all weekly/monthly reports + daily DOCX briefs.
Called after every weekly and monthly report generation.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

# ── Reports Desk v1 (WS-A): the report-type registry ─────────────────────────
# One entry per report family the system actually produces. Globs are relative to
# project root; latest file per glob family wins. Types whose dirs are empty appear
# as never-generated rows — honest, not hidden. EXTENDS this indexer (the prompt's
# rule: no parallel indexer).
REPORT_TYPES = [
    {"key": "morning_brief", "title": "Morning Brief (DOCX + dashboard)", "cadence": "daily",
     "generator": "portfolio_orchestrator (07:30 controller)", "max_age_h": 72,
     "globs": {"docx": "data/portfolios/reports/portfolio_brief_*_morning.docx",
               "html": "data/portfolios/reports/portfolio_dashboard_*_morning.html"}},
    {"key": "aegis_morning_brief", "title": "Aegis Morning Brief (Telegram + md)", "cadence": "daily",
     "generator": "aegis_morning_brief_delivery.py", "max_age_h": 72,
     "globs": {"md": "data/portfolios/reports/aegis_morning_brief_*.md",
               "json": "data/portfolios/reports/aegis_morning_brief_*.json"}},
    {"key": "weekly_review", "title": "Weekly Portfolio Review", "cadence": "weekly",
     "generator": "generate_weekly_portfolio_review (Sun 20:30 controller)", "max_age_h": 216,
     "globs": {"docx": "data/portfolios/reports/weekly/weekly_*.docx",
               "html": "data/portfolios/reports/weekly/weekly_*.html",
               "json": "data/portfolios/reports/weekly/weekly_*.json"}},
    {"key": "monthly_review", "title": "Monthly Portfolio Report", "cadence": "monthly",
     "generator": "portfolio monthly synthesis (day-1 07:35 controller)", "max_age_h": 24 * 35,
     "globs": {"docx": "data/portfolios/reports/monthly/monthly_*.docx",
               "html": "data/portfolios/reports/monthly/monthly_*.html",
               "json": "data/portfolios/reports/monthly/monthly_*.json"}},
    {"key": "manual_brief", "title": "Manual Brief (operator-triggered)", "cadence": "on-event",
     "generator": "portfolio_orchestrator --manual", "max_age_h": None,
     "globs": {"docx": "data/portfolios/reports/portfolio_brief_*_manual.docx",
               "html": "data/portfolios/reports/portfolio_dashboard_*_manual.html"}},
    {"key": "analyst_reports", "title": "Analyst Reports (sell-side DOCX)", "cadence": "weekly",
     "generator": "generate_analyst_reports_autonomous (Sun 21:15)", "max_age_h": 216,
     "registry": "data/portfolios/reports/analyst/registry.json"},
    {"key": "enterprise_reports", "title": "Enterprise Report Set (DOCX + PDF)", "cadence": "on-event",
     "generator": "generate_enterprise_reports.py", "max_age_h": None,
     "globs": {"docx": "data/portfolios/reports/analyst/enterprise/enterprise_*.docx",
               "pdf": "data/portfolios/reports/analyst/enterprise/enterprise_*.pdf"}},
    {"key": "live_readiness", "title": "Live Automation Readiness", "cadence": "on-event",
     "generator": "generate_live_readiness_report.py", "max_age_h": None,
     "globs": {"md": "docs/governance/LIVE_AUTOMATION_READINESS_REPORT_latest.md"}},
    {"key": "live_dashboard", "title": "Live Portfolio Dashboard (rolling)", "cadence": "daily",
     "generator": "portfolio_orchestrator", "max_age_h": 72,
     "globs": {"html": "data/portfolios/reports/portfolio_live.html"}},
]


def build_report_catalog(project_root: str = ".") -> dict:
    """WS-A catalog: one row per report type — latest artifacts, freshness status,
    history (last 8). Persisted to data/runtime/report_catalog.json; served through
    the existing /api/v2/reports endpoint."""
    root = Path(project_root)
    now = datetime.now(timezone.utc)
    rows = []
    for t in REPORT_TYPES:
        row = {"key": t["key"], "title": t["title"], "cadence": t["cadence"],
               "generator": t["generator"], "artifacts": {}, "history": [],
               "last_generated_at": None, "status": "never-generated"}
        newest_ts = None
        if t.get("registry"):
            try:
                reg = json.loads((root / t["registry"]).read_text())
                reps = reg.get("reports") or []
                gen_ts = sorted((r.get("generated_at") or "" for r in reps), reverse=True)
                row["artifacts"] = {"registry": "/" + t["registry"]}
                row["count"] = len(reps)
                if gen_ts and gen_ts[0]:
                    row["last_generated_at"] = gen_ts[0]
                    try:
                        newest_ts = datetime.fromisoformat(gen_ts[0].replace("Z", "+00:00"))
                        if newest_ts.tzinfo is None:
                            newest_ts = newest_ts.replace(tzinfo=timezone.utc)
                    except ValueError:
                        newest_ts = None
            except Exception:
                pass
        else:
            hist: dict = {}
            for kind, pattern in (t.get("globs") or {}).items():
                files = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
                if not files:
                    continue
                f = files[0]
                mt = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                row["artifacts"][kind] = "/" + str(f.relative_to(root))
                if newest_ts is None or mt > newest_ts:
                    newest_ts = mt
                for h in files[:8]:
                    hist.setdefault(h.stem, {"name": h.name, "mtime": datetime.fromtimestamp(
                        h.stat().st_mtime, tz=timezone.utc).isoformat(), "paths": {}})
                    hist[h.stem]["paths"][kind] = "/" + str(h.relative_to(root))
            row["history"] = sorted(hist.values(), key=lambda x: x["mtime"], reverse=True)[:8]
        if newest_ts is not None:
            row["last_generated_at"] = row["last_generated_at"] or newest_ts.isoformat()
            age_h = (now - newest_ts).total_seconds() / 3600
            row["age_hours"] = round(age_h, 1)
            if t.get("max_age_h") is None:
                row["status"] = "on-event"
            else:
                row["status"] = "fresh" if age_h <= t["max_age_h"] else "overdue"
        rows.append(row)
    catalog = {"generated_at": now.isoformat(), "types": rows,
               "note": "extends generate_reports_hub — one indexer, no parallel registry"}
    out = root / "data" / "runtime" / "report_catalog.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, indent=1))
    return catalog


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
