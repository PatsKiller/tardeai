"""tos_exporter.py — ThinkorSwim watchlist export.

Produces two files:
  trade_ai_{run_label}.tst  — ThinkorSwim watchlist import format (plain symbol list)
  trade_ai_{run_label}.csv  — CSV with symbol + score + grade for reference

TOS import: Charts → Watchlists → Import Watchlist → select the .tst file.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def export_tos(
    scored_tickers: List[Dict[str, Any]],
    output_dir: Path,
    run_label: str,
    date_str: str,
    min_decision: str = "WAIT",
) -> Dict[str, str]:
    """Export tickers to ThinkorSwim-importable watchlist.

    Args:
        scored_tickers : list of dicts from scoring.score_all()
        output_dir     : directory to write files into
        run_label      : e.g. "0700"
        date_str       : e.g. "2025-01-15"
        min_decision   : "GO" to include only GO-tier, "WAIT" for GO + WAIT

    Returns dict with file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Filter
    allowed = {"GO"} if min_decision == "GO" else {"GO", "WAIT"}
    filtered = [t for t in scored_tickers if t.get("decision") in allowed]
    filtered.sort(key=lambda x: x.get("score", 0), reverse=True)

    # ── .tst file (plain symbol list — ThinkorSwim format) ───────────────────
    tst_lines = [f"# Trade AI v10 | {date_str} | Run {run_label}", ""]
    for t in filtered:
        tst_lines.append(t["symbol"])
    tst_content = "\n".join(tst_lines) + "\n"
    tst_path = output_dir / f"trade_ai_{run_label}.tst"
    tst_path.write_text(tst_content, encoding="utf-8")

    # ── CSV annotated watchlist ───────────────────────────────────────────────
    csv_lines = ["Symbol,Score,Grade,Decision,RVOL,Price,Change%,Gap%,Float_M,Catalyst"]
    for t in filtered:
        top = t.get("top_catalyst") or {}
        cat_title = (top.get("title") or "")[:80].replace(",", ";")
        csv_lines.append(
            f"{t['symbol']},"
            f"{t['score']},"
            f"{t['grade']},"
            f"{t['decision']},"
            f"{t.get('relative_volume', 0):.1f},"
            f"{t.get('price', 0):.2f},"
            f"{t.get('change_percent', 0):+.1f},"
            f"{t.get('gap_percent', 0):+.1f},"
            f"{t.get('float_m', 0):.1f},"
            f"\"{cat_title}\""
        )
    csv_path = output_dir / f"trade_ai_{run_label}_watchlist.csv"
    csv_path.write_text("\n".join(csv_lines) + "\n", encoding="utf-8")

    return {
        "tst_path": str(tst_path),
        "csv_path": str(csv_path),
        "ticker_count": len(filtered),
    }
