# Source Export: scripts/trade_ai_health.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/trade_ai_health.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `1428e240fc9755ea7a40fe2939ce1373a558d4eed486bc45ff8c4c8675fd3836` |
| **File Size** | 11701 bytes |

## Full Source

```py
"""
trade_ai_health.py — Trade AI Pipeline Health Checker
======================================================
Reads run_summary.json files and produces a health report.

Usage:
    python scripts\trade_ai_health.py              # today's runs
    python scripts\trade_ai_health.py --date 2026-04-07
    python scripts\trade_ai_health.py --last 7     # last 7 trading days

Output:
    Console health report
    data/portfolios/state/trade_ai_health.json  (read by portfolio dashboard)
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional


def _find_reports(root: Path, date_str: str) -> List[Dict]:
    """Find all run_summary.json files for a given date."""
    date_dir = root / "reports" / date_str
    if not date_dir.exists():
        return []
    runs = []
    for label_dir in sorted(date_dir.iterdir()):
        if not label_dir.is_dir():
            continue
        summary_file = label_dir / "run_summary.json"
        if summary_file.exists():
            try:
                data = json.loads(summary_file.read_text(encoding="utf-8"))
                data["_label"] = label_dir.name
                data["_date"] = date_str
                runs.append(data)
            except Exception as e:
                runs.append({"_label": label_dir.name, "_date": date_str, "_error": str(e)})
        else:
            # Check if folder exists but no summary = partial run
            files = list(label_dir.iterdir())
            if files:
                runs.append({
                    "_label": label_dir.name,
                    "_date": date_str,
                    "_partial": True,
                    "_files": [f.name for f in files]
                })
    return runs


def _check_api_health(root: Path) -> Dict:
    """
    Check API health by scanning recent log files and run summaries.
    Known issues as of April 2026:
      - Polygon: 404 (discontinued endpoint)
      - FMP: 403 (legacy endpoint discontinued post-Aug 2025)
      - Finnhub: 422 (missing date params)
    """
    apis = {
        "finviz_token": {"status": "unknown", "note": "Primary screener — API token"},
        "finnhub":      {"status": "unknown", "note": "Catalyst news source 1"},
        "newsapi":      {"status": "unknown", "note": "Catalyst news source 2"},
        "polygon":      {"status": "unknown", "note": "Market context + halt detection"},
        "fmp":          {"status": "unknown", "note": "Economic calendar"},
        "anthropic":    {"status": "unknown", "note": "Haiku scoring + Sonnet trade plans"},
        "telegram":     {"status": "unknown", "note": "Alert delivery"},
    }

    # Check .env for key presence
    env_file = root / "assets" / ".env"
    if not env_file.exists():
        env_file = root / ".env"

    if env_file.exists():
        env_content = env_file.read_text(encoding="utf-8", errors="replace")
        key_checks = {
            "finviz_token": "FINVIZ_API_TOKEN",
            "finnhub":      "FINNHUB_API_KEY",
            "newsapi":      "NEWSAPI_KEY",
            "polygon":      "POLYGON_API_KEY",
            "fmp":          "FMP_API_KEY",
            "anthropic":    "ANTHROPIC_API_KEY",
            "telegram":     "TELEGRAM_BOT_TOKEN",
        }
        for api, key in key_checks.items():
            if f"{key}=" in env_content and f"{key}=\n" not in env_content:
                apis[api]["key_present"] = True
            else:
                apis[api]["key_present"] = False
                apis[api]["status"] = "no_key"

    # Scan log files for known errors
    logs_dir = root / "logs"
    if logs_dir.exists():
        for log_file in sorted(logs_dir.glob("pipeline_errors_*.json"), reverse=True)[:10]:
            try:
                errors = json.loads(log_file.read_text(encoding="utf-8"))
                for err in (errors if isinstance(errors, list) else [errors]):
                    msg = str(err).lower()
                    if "polygon" in msg and ("404" in msg or "403" in msg):
                        apis["polygon"]["status"] = "error"
                        apis["polygon"]["last_error"] = "HTTP 404/403"
                    # FMP /api/v3/ endpoints replaced with /stable/ — no longer flag 403
                    # if "fmp" in msg and ("403" in msg or "discontinued" in msg):
                    #     apis["fmp"]["status"] = "error"
                    if "finnhub" in msg and "422" in msg:
                        apis["finnhub"]["status"] = "error"
                        apis["finnhub"]["last_error"] = "HTTP 422 — missing date params"
            except Exception:
                pass

    # Apply known-broken status from documentation
    known_broken = {
        "polygon": "HTTP 404 — endpoint discontinued (post-Aug 2025)",
        "fmp":     "HTTP 403 — legacy endpoint discontinued (post-Aug 2025)",
        "finnhub": "HTTP 422 — missing date params (needs fix in catalyst_enrichment.py)",
    }
    for api, note in known_broken.items():
        if apis[api]["status"] == "unknown" and apis[api].get("key_present", True):
            apis[api]["status"] = "degraded"
            apis[api]["known_issue"] = note

    # Mark working APIs
    for api in ["finviz_token", "newsapi", "anthropic", "telegram"]:
        if apis[api]["status"] == "unknown" and apis[api].get("key_present", True):
            apis[api]["status"] = "ok"

    return apis


def _grade_run(summary: Dict) -> str:
    """Grade a run: healthy / degraded / failed / partial."""
    if summary.get("_error"):
        return "failed"
    if summary.get("_partial"):
        return "partial"
    go_count = summary.get("go_count", summary.get("go", 0))
    total = summary.get("total_tickers", summary.get("total", 0))
    stages_ok = summary.get("stages_completed", 0)
    if total == 0:
        return "no_tickers"
    if stages_ok < 15:
        return "degraded"
    return "healthy"


def run_health_check(root_path: str = ".", date_str: str = None, last_days: int = 1) -> Dict:
    root = Path(root_path)
    today = datetime.now().strftime("%Y-%m-%d")
    if not date_str:
        date_str = today

    # Collect runs for requested date(s)
    all_runs = []
    for d in range(last_days):
        check_date = (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
        all_runs.extend(_find_reports(root, check_date))

    # API health
    api_health = _check_api_health(root)

    # Build report
    report = {
        "generated_at": datetime.now().isoformat(),
        "date_checked": date_str,
        "runs": all_runs,
        "run_count": len(all_runs),
        "api_health": api_health,
        "alerts_broken_apis": [k for k, v in api_health.items()
                                if v["status"] in ("error", "degraded")],
        "summary": {}
    }

    # Aggregate stats across runs
    total_go = 0
    total_wait = 0
    total_avoid = 0
    total_tickers = 0
    for run in all_runs:
        total_go    += run.get("go_count", run.get("go", 0))
        total_wait  += run.get("wait_count", run.get("wait", 0))
        total_avoid += run.get("avoid_count", run.get("avoid", 0))
        total_tickers += run.get("total_tickers", run.get("total", 0))

    report["summary"] = {
        "total_runs_today": len([r for r in all_runs if r.get("_date") == today]),
        "total_go_tickers":    total_go,
        "total_wait_tickers":  total_wait,
        "total_avoid_tickers": total_avoid,
        "total_tickers_scanned": total_tickers,
        "broken_api_count": len(report["alerts_broken_apis"]),
        "catalyst_enrichment_degraded": any(
            api_health.get(a, {}).get("status") in ("error", "degraded")
            for a in ["polygon", "fmp", "finnhub"]
        ),
        "alert_delivery_ok": api_health.get("telegram", {}).get("status") == "ok",
        "screener_ok": api_health.get("finviz_token", {}).get("status") == "ok",
    }

    return report


def print_health_report(report: Dict):
    print("\n" + "="*60)
    print(f"  TRADE AI HEALTH CHECK — {report['date_checked']}")
    print("="*60)

    summary = report["summary"]
    print(f"\n📊 TODAY'S RUNS: {summary['total_runs_today']}")
    print(f"   GO: {summary['total_go_tickers']}  "
          f"WAIT: {summary['total_wait_tickers']}  "
          f"AVOID: {summary['total_avoid_tickers']}  "
          f"TOTAL: {summary['total_tickers_scanned']}")

    # Per-run details
    for run in report["runs"]:
        label = run.get("_label", "?")
        date  = run.get("_date", "?")
        go    = run.get("go_count", run.get("go", 0))
        wait  = run.get("wait_count", run.get("wait", 0))
        total = run.get("total_tickers", run.get("total", 0))
        grade = _grade_run(run)
        icon  = "✅" if grade == "healthy" else ("⚠️" if grade in ("degraded","no_tickers","partial") else "❌")
        print(f"\n   {icon} {date} {label}: {total} tickers | GO={go} WAIT={wait} | {grade}")
        if run.get("_partial"):
            print(f"      Files: {', '.join(run.get('_files', []))}")
        if run.get("_error"):
            print(f"      Error: {run['_error']}")

    # API health
    print(f"\n🔌 API HEALTH:")
    icons = {"ok": "✅", "degraded": "⚠️", "error": "❌", "no_key": "🔑", "unknown": "❓"}
    for api, info in report["api_health"].items():
        status = info.get("status", "unknown")
        icon = icons.get(status, "❓")
        note = info.get("known_issue") or info.get("last_error") or info.get("note", "")
        print(f"   {icon} {api:15} {status:10} {note[:55]}")

    # Alert assessment
    print(f"\n📱 ALERT ASSESSMENT:")
    if summary["total_go_tickers"] == 0:
        print("   ℹ️  No GO tickers today — market conditions or screener criteria not met")
        print("      Normal on heavy sell-off days (all RVOL=0 or prices out of range)")
    else:
        print(f"   ⚡ {summary['total_go_tickers']} GO tickers found — alerts should have fired")

    if summary["catalyst_enrichment_degraded"]:
        print("   ⚠️  Catalyst enrichment DEGRADED — Polygon/FMP/Finnhub broken")
        print("      Tickers still scored but catalyst pillar = 0 pts for most")
        print("      Fix: Replace with Finviz News API (already token-auth'd)")

    if not summary["alert_delivery_ok"]:
        print("   ❌ Telegram delivery may be broken — check TELEGRAM_BOT_TOKEN")
    else:
        print("   ✅ Telegram delivery: OK")

    print("\n" + "="*60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    parser.add_argument("--last", type=int, default=1)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = parser.parse_args()

    report = run_health_check(args.project_root, args.date, args.last)

    # Save for portfolio dashboard to read
    root = Path(args.project_root)
    state_dir = root / "data" / "portfolios" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "trade_ai_health.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_health_report(report)
```
