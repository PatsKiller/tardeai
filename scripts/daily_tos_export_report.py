#!/usr/bin/env python3
import json, zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data/portfolios/state"
EXPORTS = ROOT / "exports/tos_watchlists"
REPORTS = ROOT / "reports/tos"
REPORTS.mkdir(parents=True, exist_ok=True)

def load(name):
    p = STATE / name
    return json.loads(p.read_text()) if p.exists() else {}

summary = load("backtest_summary.json").get("summary", {})
review = load("classification_review_queue.json").get("needs_review", [])
bt = load("backtest_summary.json").get("backtests", [])

leaders = sorted([x for x in bt if x.get("status") == "ok"], key=lambda x: x.get("backtest_score", 0), reverse=True)[:10]
laggards = sorted([x for x in bt if x.get("status") == "ok"], key=lambda x: x.get("backtest_score", 0))[:10]

today = datetime.now().strftime("%Y%m%d")
md = REPORTS / f"tos_export_report_{today}.md"
zip_path = REPORTS / f"tos_watchlists_{today}.zip"

lines = []
lines.append(f"# TOS Export Report — {today}")
lines.append("")
lines.append(f"Generated: {datetime.now().isoformat()}")
lines.append("")
lines.append("## Bucket Counts")
for k, v in summary.get("bucket_counts", {}).items():
    lines.append(f"- {k}: {v}")
lines.append("")
lines.append(f"Classification review queue: {len(review)}")
lines.append("")
lines.append("## Backtest Leaders")
for x in leaders:
    lines.append(f"- {x.get('symbol')}: score {x.get('backtest_score')} | trend {x.get('trend')} | 1M {x.get('return_1m_pct')}% | 12M {x.get('return_12m_pct')}%")
lines.append("")
lines.append("## Backtest Laggards / Review")
for x in laggards:
    lines.append(f"- {x.get('symbol')}: score {x.get('backtest_score')} | trend {x.get('trend')} | drawdown {x.get('max_drawdown_252_pct')}%")
lines.append("")
lines.append("## TOS Import Files")
for f in sorted(EXPORTS.glob("*LATEST.txt")):
    lines.append(f"- {f.name}")
lines.append("")
lines.append("## TOS Steps")
lines.append("1. Download the ZIP to Windows.")
lines.append("2. Extract it in Downloads.")
lines.append("3. In thinkorswim, create/update watchlists named AI_ETFS, AI_DIVIDEND_ETFS, AI_MUTUAL_FUNDS, AI_SWING, AI_COMPILED_ENTRIES, AI_REVIEW_REMOVE.")
lines.append("4. Open each *_LATEST.txt, copy symbols, and paste/import into the matching TOS watchlist.")
lines.append("5. Review AI_REVIEW_REMOVE before deleting anything.")
lines.append("")
md.write_text("\n".join(lines))

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(EXPORTS.glob("*LATEST.txt")):
        z.write(f, f.name)
    z.write(md, md.name)

print(json.dumps({"report": str(md), "zip": str(zip_path)}, indent=2))
