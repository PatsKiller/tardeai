#!/usr/bin/env python3
"""Live READ-ONLY audit after symbol-thesis integration (no backfill, no enqueue).

Usage:
  .venv/bin/python scripts/symbol_thesis_integration_audit.py \\
    --out evidence/SYMBOL_THESIS_INTEGRATION_AUDIT.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="evidence/SYMBOL_THESIS_INTEGRATION_AUDIT.json")
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args()
    root = Path(args.root)

    from scripts.lib.symbol_thesis_attach import clear_cache, universe_metrics
    from scripts.lib.symbol_thesis_cc import build_symbol_thesis_card, build_universe_theses_projection
    from scripts.lib.symbol_thesis_research import propose_prioritized_research

    clear_cache()
    metrics = universe_metrics(root=root)
    proposed = propose_prioritized_research(root=root, limit=25)
    cards = {s: build_symbol_thesis_card(s, root=root) for s in ("SCHG", "CSCO", "ANET")}
    # Slim cards for evidence
    slim_cards = {}
    for s, c in cards.items():
        slim_cards[s] = {
            "memberships": c.get("memberships"),
            "portfolio_role": c.get("portfolio_role"),
            "portfolio_role_source": c.get("portfolio_role_source"),
            "thesis_state": c.get("thesis_state"),
            "thesis_version": c.get("symbol_thesis_version"),
            "stance": c.get("thesis_stance"),
            "why_owned_or_watched": c.get("why_owned_or_watched"),
            "why_exited": c.get("why_exited"),
            "reentry_state": c.get("reentry_state"),
            "opportunity_rank": c.get("opportunity_rank"),
            "research_gaps": c.get("research_gaps"),
            "proposed_research_questions": [
                r.get("specific_question") for r in (c.get("proposed_research") or [])[:3]
            ],
            "what_would_change": c.get("what_would_change"),
        }

    # Optional: smoke build_product (can be slow) — keep fail-soft
    product_smoke = None
    try:
        from scripts.lib.cio_investment_product import build_product
        prod = build_product(root=root)
        product_smoke = {
            "schema": prod.get("schema"),
            "thesis_universe": prod.get("thesis_universe"),
            "thesis_changes_today_counts": (prod.get("thesis_changes_today") or {}).get("counts"),
            "reentry_thesis_incomplete": (prod.get("reentry_book") or {}).get("thesis_incomplete_count"),
            "holdings_thesis_n": len((prod.get("action_book") or {}).get("CURRENT_HOLDINGS_THESIS") or []),
            "research_next_n": len((prod.get("action_book") or {}).get("RESEARCH_NEXT") or []),
            "authority": prod.get("authority"),
            "financial_action": prod.get("financial_action"),
        }
    except Exception as exc:
        product_smoke = {"error": f"{type(exc).__name__}:{exc}"}

    out = {
        "schema": "SymbolThesisIntegrationAudit@v1",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "authority": "READ_ONLY_ADVISORY",
        "production_mutation": False,
        "backfill_performed": False,
        "research_enqueued": False,
        "live_read_only_coverage": metrics,
        "proposed_prioritized_research": {
            "counts": proposed.get("counts"),
            "top": [
                {
                    "symbol": r["symbol"],
                    "priority": r["priority"],
                    "question": r["specific_question"],
                    "gap": r["research_gap"],
                }
                for r in (proposed.get("requests") or [])[:15]
            ],
        },
        "SCHG": slim_cards["SCHG"],
        "CSCO": slim_cards["CSCO"],
        "ANET": slim_cards["ANET"],
        "product_smoke": product_smoke,
        "note": "No production thesis backfill. Proposed research is DRY.",
    }
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out_path), "metrics": metrics}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
