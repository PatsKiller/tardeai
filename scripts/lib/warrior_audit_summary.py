"""Format Ross vs TradeAI audit summaries for Telegram + Command Center."""
from __future__ import annotations

from typing import Any


def format_telegram(summary: dict[str, Any], *, label: str = "Weekly") -> str:
    gaps = summary.get("gap_breakdown") or {}
    top_gaps = sorted(gaps.items(), key=lambda x: -x[1])[:6]
    gap_lines = "\n".join(f"  · {k}: {v}" for k, v in top_gaps) if top_gaps else "  · (none)"
    return (
        f"📊 *Ross {label} Audit* ({summary.get('since')} → {summary.get('until')})\n\n"
        f"*Recall:* {summary.get('symbol_recall_pct', 0)}% scanned "
        f"({summary.get('symbol_days', 0)} sym-days)\n"
        f"*GO matches:* {summary.get('go_recall_pct', 0)}%\n"
        f"*Presentation:* {summary.get('presentation_pct', 0)}%\n\n"
        f"*Gap breakdown (scanned):*\n{gap_lines}\n\n"
        f"_Awareness goal — not auto-GO Ross names_"
    )


def format_panel(summary: dict[str, Any]) -> dict[str, Any]:
    gaps = summary.get("gap_breakdown") or {}
    return {
        "since": summary.get("since"),
        "until": summary.get("until"),
        "symbol_recall_pct": summary.get("symbol_recall_pct"),
        "go_recall_pct": summary.get("go_recall_pct"),
        "presentation_pct": summary.get("presentation_pct"),
        "symbol_days": summary.get("symbol_days"),
        "catalog_days": summary.get("catalog_days"),
        "gap_breakdown": gaps,
        "top_gaps": sorted(gaps.items(), key=lambda x: -x[1])[:8],
        "generated_at": summary.get("generated_at"),
        "csv_path": summary.get("csv_path"),
    }