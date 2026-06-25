#!/usr/bin/env python3
"""Generate enterprise analyst reports (DOCX + PDF) for every report type with graphics."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from analyst_report_builder import build_report, save_report_json  # noqa: E402
from report_export import _resolve_chart_path, export_report  # noqa: E402

ENTERPRISE_DIR = PROJECT_ROOT / "data" / "portfolios" / "reports" / "analyst" / "enterprise"
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _pick_symbol(holdings: list[dict], min_mv: float = 1000) -> str:
    for h in sorted(holdings, key=lambda x: float(x.get("market_value") or 0), reverse=True):
        if h.get("symbol") and not h.get("is_cash") and float(h.get("market_value") or 0) >= min_mv:
            return str(h["symbol"]).upper()
    return "LDOS"


def _pick_watchlist_symbol(holdings: list[dict]) -> str:
    held = {str(h.get("symbol", "")).upper() for h in holdings}
    try:
        from db_adapter import _execute
        rows = _execute(
            "SELECT symbol FROM watchlist_items WHERE status NOT IN ('removed') ORDER BY score DESC NULLS LAST LIMIT 20",
            fetch="all",
        ) or []
        for r in rows:
            sym = str(r.get("symbol", "")).upper()
            if sym and sym not in held:
                return sym
    except Exception:
        pass
    return "RKLB"


def _pick_sector() -> str:
    try:
        from db_adapter import _execute
        rows = _execute(
            """SELECT sector, COUNT(*) AS n FROM symbol_profiles
               WHERE sector IS NOT NULL GROUP BY sector ORDER BY n DESC LIMIT 1""",
            fetch="one",
        )
        if rows and rows.get("sector"):
            return str(rows["sector"])
    except Exception:
        pass
    return "Healthcare"


def _chart_stats(report: dict) -> tuple[int, int]:
    visuals = report.get("visuals") or []
    charts = [v for v in visuals if v.get("chart_path")]
    resolved = sum(1 for v in charts if _resolve_chart_path(v.get("chart_path")))
    return len(charts), resolved


def _build_cases() -> list[dict]:
    holdings_data = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    holdings = holdings_data.get("holdings") or []
    holding_sym = _pick_symbol(holdings)
    wl_sym = _pick_watchlist_symbol(holdings)
    sector = _pick_sector()

    return [
        {"key": "daily_digest", "label": "Daily Intelligence Digest", "kwargs": {"report_type": "daily_digest"}},
        {"key": "weekly_review", "label": "Weekly Portfolio Review", "kwargs": {"report_type": "weekly_review"}},
        {"key": "symbol_holding", "label": "Portfolio Holding", "kwargs": {"report_type": "symbol_holding", "symbol": holding_sym}},
        {"key": "symbol_watchlist", "label": "Watchlist Item", "kwargs": {"report_type": "symbol_watchlist", "symbol": wl_sym}},
        {"key": "symbol_custom", "label": "Custom Instrument", "kwargs": {"report_type": "symbol_custom", "symbol": "SPY"}},
        {"key": "sector_theme", "label": "Sector & Theme", "kwargs": {"report_type": "sector_theme", "sector": sector}},
        {"key": "intelligence_deep", "label": "Intelligence Deep Dive", "kwargs": {"report_type": "intelligence_deep", "topic": "defense"}},
        {"key": "event_driven", "label": "Event-Driven Alerts", "kwargs": {"report_type": "event_driven", "hours": 48, "event_filter": "all"}},
    ]


def main() -> int:
    ENTERPRISE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest: list[dict] = []
    failures: list[str] = []

    print("Enterprise Analyst Reports — full build")
    print("=" * 60)

    for case in _build_cases():
        key = case["key"]
        label = case["label"]
        stem = f"enterprise_{key}_{ts}"
        print(f"\n▶ {label} ({key})")

        try:
            report = build_report(**case["kwargs"])
            if report.get("error"):
                raise RuntimeError(report["error"])

            sections = len(report.get("sections") or [])
            charts, resolved = _chart_stats(report)
            print(f"  sections={sections} charts={charts} embedded={resolved}")

            json_path = save_report_json(report, stem=stem)
            json_dest = ENTERPRISE_DIR / json_path.name
            json_path.replace(json_dest)

            docx = export_report(report, "docx", output_stem=stem)
            if not docx.get("ok"):
                raise RuntimeError(docx.get("error", "docx export failed"))
            docx_src = Path(docx["path"])
            docx_dest = ENTERPRISE_DIR / docx_src.name
            docx_src.replace(docx_dest)

            pdf = export_report(report, "pdf", output_stem=stem)
            pdf_dest = None
            if pdf.get("ok"):
                pdf_src = Path(pdf["path"])
                pdf_dest = ENTERPRISE_DIR / pdf_src.name
                pdf_src.replace(pdf_dest)

            entry = {
                "key": key,
                "label": label,
                "title": report.get("meta", {}).get("title"),
                "sections": sections,
                "charts": charts,
                "charts_embedded": resolved,
                "json": str(json_dest.relative_to(PROJECT_ROOT)),
                "docx": str(docx_dest.relative_to(PROJECT_ROOT)),
                "docx_url": docx.get("url"),
                "pdf": str(pdf_dest.relative_to(PROJECT_ROOT)) if pdf_dest else None,
                "pdf_url": pdf.get("url") if pdf.get("ok") else None,
                "ok": True,
            }
            manifest.append(entry)
            print(f"  ✓ DOCX {docx_dest.name} ({docx.get('size_kb')} KB)")
            if pdf_dest:
                print(f"  ✓ PDF  {pdf_dest.name} ({pdf.get('size_kb')} KB)")
        except Exception as e:
            failures.append(f"{key}: {e}")
            manifest.append({"key": key, "label": label, "ok": False, "error": str(e)})
            print(f"  ✗ FAILED: {e}")

    manifest_path = ENTERPRISE_DIR / f"enterprise_manifest_{ts}.json"
    manifest_path.write_text(json.dumps({"generated_at": datetime.now().isoformat(), "reports": manifest}, indent=2))

    print("\n" + "=" * 60)
    ok = sum(1 for m in manifest if m.get("ok"))
    print(f"Done: {ok}/{len(manifest)} reports · manifest → {manifest_path.name}")
    if failures:
        print("Failures:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())