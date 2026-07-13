#!/usr/bin/env python3
"""remediate_weekly_report_action.py — Fix hallucinated weekly report actions in saved JSON/HTML.

Re-validates narratives.action against current holdings grounding and patches files in place.

  python3 scripts/remediate_weekly_report_action.py --date 2026-07-12 --apply
  python3 scripts/remediate_weekly_report_action.py --date 2026-07-12 --apply --notify
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
WEEKLY_DIR = PROJECT_ROOT / "data" / "portfolios" / "reports" / "weekly"
SERVE_DIR = PROJECT_ROOT / "reports" / "weekly"


def _load_json(name: str) -> dict:
    p = STATE_DIR / name
    return json.loads(p.read_text()) if p.exists() else {}


def remediate(date_str: str, *, apply: bool, notify: bool) -> dict:
    from portfolio_report_llm import build_grounding, sanitize_action_text, validate_action_text

    json_path = WEEKLY_DIR / f"weekly_{date_str}.json"
    html_path = WEEKLY_DIR / f"weekly_{date_str}.html"
    if not json_path.exists():
        return {"ok": False, "error": f"missing {json_path}"}

    report = json.loads(json_path.read_text())
    old_action = (report.get("narratives") or {}).get("action", "")
    holdings = _load_json("holdings.json")
    risk = _load_json("risk_management.json")
    enrichment = _load_json("ticker_enrichment_cache.json")
    grounding = build_grounding(holdings, enrichment, risk, [])
    ok_before, issues = validate_action_text(old_action, grounding)
    new_action = sanitize_action_text(old_action, grounding, monthly=False)

    out = {
        "date": date_str,
        "ok_before": ok_before,
        "issues": issues,
        "old_action": old_action[:200],
        "new_action": new_action[:200],
        "changed": new_action != old_action,
    }

    if not apply:
        out["dry_run"] = True
        return out

    if out["changed"]:
        report.setdefault("narratives", {})["action"] = new_action
        json_path.write_text(json.dumps(report, indent=2))
        if html_path.exists():
            html = html_path.read_text()
            html = re.sub(
                r'(<div class="action-box">🎯 )[^<]*(</div>)',
                lambda m: f"{m.group(1)}{new_action}{m.group(2)}",
                html,
                count=1,
            )
            html_path.write_text(html)
        SERVE_DIR.mkdir(parents=True, exist_ok=True)
        serve_html = SERVE_DIR / html_path.name
        if html_path.exists():
            serve_html.write_text(html_path.read_text())

    if notify and out["changed"]:
        try:
            from dotenv import load_dotenv
            load_dotenv(PROJECT_ROOT / ".env")
        except Exception:
            pass
        from portfolio_weekly_report import _clean_md, _send_telegram
        perf = report.get("total_value", 0)
        w_chg = report.get("1w_change_pct", 0) or 0
        ytd = report.get("ytd_change_pct", 0) or 0
        perf_n = (report.get("narratives") or {}).get("performance", "")
        msg = (
            f"📊 <b>Weekly Report CORRECTION — {date_str}</b>\n\n"
            f"<b>${perf:,.0f}</b> | 1W: <b>{w_chg:+.2f}%</b> | YTD: {ytd:+.2f}%\n\n"
            f"Prior action line was invalid (unheld ticker / bad price). Corrected:\n\n"
            f"🎯 {_clean_md(new_action)[:220]}\n\n"
            f"<a href='https://ms01-openclaw.tail163d14.ts.net/reports/weekly/weekly_{date_str}.html'>📄 Full Report</a>"
        )
        _send_telegram(msg)
        out["telegram_sent"] = True

    out["ok"] = True
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="Report date YYYY-MM-DD")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--notify", action="store_true", help="Send correction Telegram")
    args = ap.parse_args()
    result = remediate(args.date, apply=args.apply, notify=args.notify)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") or result.get("dry_run") else 1


if __name__ == "__main__":
    raise SystemExit(main())