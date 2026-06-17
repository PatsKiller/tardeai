#!/usr/bin/env python3
"""
Rotation LLM Advisor

Ask account-aware rotation questions against real holdings + optional symbol-card
context. Safe by design: advisory only, no broker calls, no order creation, no
account changes.

Examples:
  python3 scripts/rotation_llm_advisor.py --question "Should I trim XLB for SPCX? How much?" --backend local --cards data/runtime/symbol_cards_latest.json
  python3 scripts/rotation_llm_advisor.py --question "I am heavy in Mag 7. Which funds/ETFs should I trim?" --backend oauth_prompt --cards data/runtime/symbol_cards_latest.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

PROMPT_DIR = ROOT / "data" / "runtime" / "rotation_prompts"
DEFAULT_HOLDINGS = ROOT / "data" / "portfolios" / "state" / "holdings.json"
DEFAULT_CARDS = ROOT / "data" / "runtime" / "symbol_cards_latest.json"

SAFETY_BLOCK = """
NON-NEGOTIABLE SAFETY RULES:
- Advisory only. Do not say an order has been placed or should be placed automatically.
- Do not bypass human approval, broker controls, protective-stop gates, or manual review.
- Give ranges and review steps, not instructions to execute immediately.
- If data is missing, say what is missing and downgrade confidence.
- For 401k/Fidelity manual funds, treat recommendations as manual-ticket review only.
- For taxable accounts, flag tax-impact review before trimming.
""".strip()


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def run_rotation_engine(holdings: Path, cards: Path | None, min_pair_score: float) -> dict[str, Any]:
    cmd = [sys.executable, str(SCRIPTS / "rotation_intelligence_engine.py"), "--input", str(holdings), "--min-pair-score", str(min_pair_score)]
    if cards and cards.exists():
        cmd += ["--cards", str(cards)]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        return {"ok": False, "error": "rotation_engine_failed", "stderr": proc.stderr[-2000:], "stdout": proc.stdout[-2000:]}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": "rotation_engine_invalid_json", "detail": str(exc), "stdout": proc.stdout[-2000:]}


def compact_holdings(payload: Any, max_rows: int = 80) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"available": False}
    rows = []
    raw_rows = payload.get("holdings") or payload.get("positions") or payload.get("rows") or []
    if isinstance(raw_rows, list):
        for r in raw_rows[:max_rows]:
            if not isinstance(r, dict):
                continue
            rows.append({
                "symbol": r.get("symbol") or r.get("ticker"),
                "account_key": r.get("account_key") or r.get("account"),
                "market_value": r.get("market_value") or r.get("current_value") or r.get("value"),
                "sector": r.get("sector") or r.get("sector_type"),
                "asset_class": r.get("asset_class") or r.get("instrument_type"),
                "yield": r.get("yield") or r.get("dividend_yield") or r.get("income_yield"),
                "protection_state": r.get("protection_state") or r.get("stop_health"),
            })
    return {
        "available": True,
        "portfolio_totals": payload.get("portfolio_totals", {}),
        "row_count": len(raw_rows) if isinstance(raw_rows, list) else None,
        "sample_rows": rows,
    }


def compact_symbol_cards(payload: Any, max_rows: int = 80) -> dict[str, Any]:
    if payload is None:
        return {"available": False}
    rows: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        for key in ("cards", "symbols", "items", "results", "rows"):
            value = data.get(key) if isinstance(data, dict) else None
            if isinstance(value, list):
                rows = [x for x in value if isinstance(x, dict)]
                break
            if isinstance(value, dict):
                rows = [dict(v, symbol=v.get("symbol") or k) for k, v in value.items() if isinstance(v, dict)]
                break
        if not rows and isinstance(data, dict) and all(isinstance(v, dict) for v in data.values()):
            rows = [dict(v, symbol=v.get("symbol") or k) for k, v in data.items()]
    elif isinstance(payload, list):
        rows = [x for x in payload if isinstance(x, dict)]

    compact = []
    for r in rows[:max_rows]:
        analyst = r.get("analyst") or r.get("analyst_consensus") or {}
        compact.append({
            "symbol": r.get("symbol") or r.get("ticker"),
            "sector": r.get("sector") or r.get("sector_name") or r.get("gics_sector"),
            "asset_class": r.get("asset_class") or r.get("instrument_type"),
            "analyst_upside_pct": r.get("analyst_upside_pct") or r.get("upside_pct") or (analyst.get("upside_pct") if isinstance(analyst, dict) else None),
            "analyst_rating": r.get("analyst_rating") or (analyst.get("rating") if isinstance(analyst, dict) else None),
            "news_score": r.get("news_score") or r.get("sentiment_score"),
            "top_news_count": len(r.get("news") or r.get("top_news") or []),
        })
    return {"available": True, "card_count": len(rows), "sample_cards": compact}


def build_prompt(question: str, holdings_payload: Any, cards_payload: Any, rotation_report: dict[str, Any]) -> str:
    context = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user_question": question,
        "holdings_context": compact_holdings(holdings_payload),
        "symbol_card_context": compact_symbol_cards(cards_payload),
        "rotation_engine_report": rotation_report,
    }
    return f"""
You are the Trade AI Rotation Advisor for a single owner/operator portfolio.

{SAFETY_BLOCK}

User question:
{question}

Use the JSON context below. Answer with:
1. Direct answer in plain English.
2. What to trim, if anything, and why.
3. What to add, if anything, and why.
4. Suggested review amount or percent range. Use ranges, not order instructions.
5. Account-specific notes: taxable, Roth, rollover IRA, Fidelity/401k manual-only.
6. Missing data / confidence warnings.
7. Final recommendation class: HOLD / WATCH / ADD_REVIEW / TRIM_REVIEW / ROTATE_REVIEW / RESEARCH_MORE.

JSON_CONTEXT:
{json.dumps(context, indent=2, sort_keys=True)}
""".strip()


def call_local_llm(prompt: str, timeout: int, fallback: bool) -> str:
    try:
        from local_llm import generate  # type: ignore
    except Exception as exc:
        return f"LOCAL_LLM_IMPORT_ERROR: {exc}\n\nPrompt was built but not sent."
    old_num_predict = os.environ.get("LOCAL_LLM_NUM_PREDICT")
    os.environ["LOCAL_LLM_NUM_PREDICT"] = os.environ.get("ROTATION_LLM_NUM_PREDICT", "1200")
    try:
        return generate(prompt, timeout=timeout, fallback=fallback, fast=False, caller="rotation_llm_advisor.py", process_type="CRITICAL_CLOUD")
    finally:
        if old_num_predict is None:
            os.environ.pop("LOCAL_LLM_NUM_PREDICT", None)
        else:
            os.environ["LOCAL_LLM_NUM_PREDICT"] = old_num_predict


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", required=True, help="Rotation/allocation question to ask")
    ap.add_argument("--holdings", default=str(DEFAULT_HOLDINGS))
    ap.add_argument("--cards", default=str(DEFAULT_CARDS))
    ap.add_argument("--backend", choices=["local", "auto", "oauth_prompt", "prompt_only"], default="local")
    ap.add_argument("--min-pair-score", type=float, default=35.0)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    holdings_path = Path(args.holdings)
    cards_path = Path(args.cards) if args.cards else None
    holdings_payload = load_json(holdings_path)
    cards_payload = load_json(cards_path) if cards_path and cards_path.exists() else None
    rotation_report = run_rotation_engine(holdings_path, cards_path if cards_path and cards_path.exists() else None, args.min_pair_score)
    prompt = build_prompt(args.question, holdings_payload, cards_payload, rotation_report)

    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    slug = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prompt_path = PROMPT_DIR / f"rotation_prompt_{slug}.md"
    prompt_path.write_text(prompt)

    result: dict[str, Any] = {
        "ok": True,
        "advisory_only": True,
        "backend": args.backend,
        "prompt_path": str(prompt_path),
        "rotation_summary": rotation_report.get("summary", {}),
        "data_quality": rotation_report.get("data_quality", {}),
    }

    if args.backend in {"prompt_only", "oauth_prompt"}:
        result["answer"] = None
        result["instructions"] = "Send prompt_path content to the OAuth/cloud LLM channel for external review. No broker action is authorized."
    else:
        answer = call_local_llm(prompt, timeout=args.timeout, fallback=(args.backend == "auto"))
        result["answer"] = answer

    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result.get("answer") or json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
