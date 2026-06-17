#!/usr/bin/env python3
"""
Rotation LLM Advisor

Ask account-aware rotation questions against real holdings + optional symbol-card
context. Safe by design: advisory only, no broker calls, no broker action, no
account changes.

The script includes a deterministic grounding answer and a post-check for local
LLM overreach. If the model invents trim percentages, tax effects, account
locations, or "no missing data" when the evidence disagrees, the user-facing
answer is replaced with the grounded answer and the raw model answer is preserved.
"""
from __future__ import annotations

import argparse
import json
import os
import re
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
DEFAULT_ETF_OVERRIDES = ROOT / "config" / "etf_classification_overrides.json"
DEFAULT_FUND_MAP = ROOT / "config" / "fidelity_fund_code_map.json"

SAFETY_BLOCK = """
NON-NEGOTIABLE SAFETY RULES:
- Advisory only. Do not say any broker action has been taken or should be automatic.
- Give review ranges only when supported by evidence. Otherwise say range unavailable.
- If rotation_summary has zero trim_review, zero add_review, and zero rotation_ideas, do not invent a trim percentage.
- If data is missing, state exactly what is missing and downgrade confidence.
- Only mention account types that actually hold the symbol or are explicitly being compared.
- For taxable accounts, tax impact is UNKNOWN unless cost basis or gain/loss data is present.
- For Roth/IRA accounts, tax treatment is account-dependent but still requires account-specific evidence.
- For Fidelity/401k manual funds, treat as manual review only.
""".strip()

SECTOR_WORDS = {
    "materials", "industrials", "technology", "energy", "healthcare", "financials",
    "utilities", "real estate", "communication services", "consumer staples",
    "consumer discretionary", "broad market", "fixed income", "space", "private growth",
}

# Uppercase words that often appear in natural-language questions but are not symbols.
SYMBOL_STOPWORDS = {
    "THE", "AND", "FOR", "HOW", "MUCH", "SHOULD", "WHICH", "FUNDS", "ETFS", "ETF",
    "HEAVY", "TRIM", "TRIMMING", "REDUCE", "ADD", "ROTATE", "ROTATION", "REVIEW", "HELP",
    "SOME", "WHAT", "WHEN", "WHERE", "WHY", "WITH", "FROM", "INTO", "OUT", "OF", "MY",
    "MAG", "MAG7", "SEVEN", "LOCAL", "OAUTH", "LLM",
}

ACCOUNT_ALIASES = {
    "taxable": ("taxable", "schwab taxable"),
    "roth": ("roth", "roth ira", "schwab roth"),
    "rollover": ("rollover", "rollover ira", "traditional ira", "schwab rollover"),
    "401k": ("401k", "401(k)", "fidelity", "manual-only", "manual only"),
}


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "—"):
            return default
        return float(value)
    except Exception:
        return default


def first(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if d.get(k) not in (None, "", [], {}):
            return d.get(k)
    return None


def load_symbol_overrides(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    symbols = data.get("symbols", {}) if isinstance(data, dict) else {}
    return {str(k).upper(): v for k, v in symbols.items() if isinstance(v, dict)}


def load_fund_codes(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    codes = data.get("codes", {}) if isinstance(data, dict) else {}
    return {str(k).upper(): v for k, v in codes.items() if isinstance(v, dict)}


def rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("holdings", "positions", "rows", "data"):
            if isinstance(payload.get(key), list):
                return [x for x in payload[key] if isinstance(x, dict)]
        if all(isinstance(v, dict) for v in payload.values()):
            return [dict(v, symbol=v.get("symbol") or k) for k, v in payload.items() if isinstance(v, dict)]
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def symbol_of(row: dict[str, Any]) -> str:
    return str(first(row, "symbol", "ticker") or "UNKNOWN").upper()


def cards_from_payload(payload: Any) -> dict[str, dict[str, Any]]:
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
            rows = [dict(v, symbol=v.get("symbol") or k) for k, v in data.items() if isinstance(v, dict)]
    elif isinstance(payload, list):
        rows = [x for x in payload if isinstance(x, dict)]
    return {symbol_of(r): r for r in rows if symbol_of(r) != "UNKNOWN"}


def extract_symbols(question: str, known_symbols: set[str] | None = None) -> list[str]:
    tokens = re.findall(r"\b[A-Z0-9]{2,6}\b", question.upper())
    raw = {t for t in tokens if t not in SYMBOL_STOPWORDS}
    if known_symbols:
        known = {s.upper() for s in known_symbols}
        raw = {t for t in raw if t in known or re.fullmatch(r"[A-Z]{1,5}|[0-9]{3,6}", t)}
    return sorted(raw)


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


def account_rows_for_symbols(holdings_payload: Any, symbols: list[str]) -> dict[str, list[dict[str, Any]]]:
    rows = rows_from_payload(holdings_payload)
    out: dict[str, list[dict[str, Any]]] = {s: [] for s in symbols}
    for row in rows:
        sym = symbol_of(row)
        if sym in out:
            out[sym].append(row)
    return out


def card_fact(symbol: str, cards: dict[str, dict[str, Any]], sym_overrides: dict[str, dict[str, Any]], fund_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    card = cards.get(symbol, {})
    ov = sym_overrides.get(symbol, {})
    fund = fund_map.get(symbol, {})
    analyst = first(card, "analyst", "analyst_consensus") or {}
    return {
        "symbol": symbol,
        "sector": first(card, "sector", "sector_name", "gics_sector") or ov.get("sector") or fund.get("sector"),
        "asset_class": first(card, "asset_class", "instrument_type", "security_type") or ov.get("asset_class") or fund.get("asset_class"),
        "analyst_upside_pct": first(card, "analyst_upside_pct", "upside_pct", "target_upside_pct") or (analyst.get("upside_pct") if isinstance(analyst, dict) else None),
        "analyst_required": ov.get("analyst_required", fund.get("analyst_required", True)),
        "mapping_status": fund.get("mapping_status"),
        "manual_only": fund.get("manual_only"),
    }


def _known_symbols(holdings_payload: Any, cards_payload: Any, sym_overrides: dict[str, dict[str, Any]], fund_map: dict[str, dict[str, Any]]) -> set[str]:
    known = {symbol_of(r) for r in rows_from_payload(holdings_payload) if symbol_of(r) != "UNKNOWN"}
    known.update(cards_from_payload(cards_payload).keys())
    known.update(sym_overrides.keys())
    known.update(fund_map.keys())
    return known


def grounding_report(question: str, holdings_payload: Any, cards_payload: Any, rotation_report: dict[str, Any]) -> dict[str, Any]:
    cards = cards_from_payload(cards_payload)
    sym_overrides = load_symbol_overrides(DEFAULT_ETF_OVERRIDES)
    fund_map = load_fund_codes(DEFAULT_FUND_MAP)
    symbols = extract_symbols(question, _known_symbols(holdings_payload, cards_payload, sym_overrides, fund_map))
    account_rows = account_rows_for_symbols(holdings_payload, symbols)
    summary = rotation_report.get("summary", {}) if isinstance(rotation_report, dict) else {}
    data_quality = rotation_report.get("data_quality", {}) if isinstance(rotation_report, dict) else {}
    candidate_rows = rotation_report.get("top_candidates", []) if isinstance(rotation_report, dict) else []

    missing_flags = []
    if data_quality.get("rows_with_sector", 0) < data_quality.get("holding_rows", 0):
        missing_flags.append("some holdings are missing sector")
    if any((c.get("evidence") or {}).get("missing_or_neutral_analyst_upside") for c in candidate_rows if isinstance(c, dict)):
        missing_flags.append("some holdings have missing or neutral analyst upside")
    if any((c.get("evidence") or {}).get("missing_sector") for c in candidate_rows if isinstance(c, dict)):
        missing_flags.append("some scored candidates are missing sector")

    facts = []
    for sym in symbols:
        rows = account_rows.get(sym, [])
        held_accounts = [first(r, "account_key", "account") for r in rows]
        facts.append({
            **card_fact(sym, cards, sym_overrides, fund_map),
            "held_accounts": held_accounts,
            "held_account_aliases": [_account_alias_for(a) for a in held_accounts if a],
            "held_market_value_total": round(sum(as_float(first(r, "market_value", "current_value", "value")) for r in rows), 2),
            "holding_row_count": len(rows),
        })
        fact = facts[-1]
        if fact.get("holding_row_count") == 0:
            missing_flags.append(f"{sym} is not currently present in holdings context")
        if not fact.get("sector"):
            missing_flags.append(f"{sym} sector is missing")
        if fact.get("analyst_required") is not False and not fact.get("analyst_upside_pct"):
            missing_flags.append(f"{sym} analyst upside is missing")

    no_actionable = not summary.get("trim_review") and not summary.get("add_review") and not summary.get("rotation_ideas")
    return {
        "symbols_in_question": symbols,
        "symbol_facts": facts,
        "rotation_summary": summary,
        "data_quality": data_quality,
        "missing_flags": sorted(set(missing_flags)),
        "no_model_supported_action": bool(no_actionable),
    }


def _account_alias_for(account_name: Any) -> str | None:
    text = str(account_name or "").lower()
    if "taxable" in text:
        return "taxable"
    if "roth" in text:
        return "roth"
    if "rollover" in text or "ira" in text:
        return "rollover"
    if "401" in text or "fidelity" in text:
        return "401k"
    return None


def deterministic_answer(question: str, report: dict[str, Any]) -> str:
    symbols = ", ".join(report.get("symbols_in_question") or []) or "the requested symbols"
    lines = [
        "Grounded advisory answer:",
        f"- Question reviewed: {question}",
        f"- Symbols detected: {symbols}",
    ]
    if report.get("no_model_supported_action"):
        lines.append("- The rotation engine does not currently show a model-supported TRIM_REVIEW, ADD_REVIEW, or ROTATE_REVIEW for this question.")
        lines.append("- Therefore, no numeric trim amount is supported by the current evidence pack.")
    for fact in report.get("symbol_facts", []):
        lines.append(
            f"- {fact.get('symbol')}: sector={fact.get('sector') or 'UNKNOWN'}, "
            f"asset_class={fact.get('asset_class') or 'UNKNOWN'}, held_value=${fact.get('held_market_value_total', 0):,.2f}, "
            f"accounts={fact.get('held_accounts') or []}, analyst_upside={fact.get('analyst_upside_pct') or 'n/a'}, "
            f"mapping_status={fact.get('mapping_status') or 'n/a'}"
        )
    if report.get("missing_flags"):
        lines.append("- Missing data warnings: " + "; ".join(report["missing_flags"]))
    lines += [
        "- Account notes: tax impact is UNKNOWN unless cost basis / realized gain-loss data is present. Do not assume positive or negative tax impact.",
        "- Recommended class: RESEARCH_MORE if you need a dollar/percent trim range; WATCH if you only want to monitor the pair.",
    ]
    return "\n".join(lines)


def compact_holdings(payload: Any, max_rows: int = 80) -> dict[str, Any]:
    rows = rows_from_payload(payload)[:max_rows]
    return {
        "available": isinstance(payload, dict),
        "portfolio_totals": payload.get("portfolio_totals", {}) if isinstance(payload, dict) else {},
        "row_count": len(rows_from_payload(payload)),
        "sample_rows": [
            {
                "symbol": symbol_of(r),
                "account_key": first(r, "account_key", "account"),
                "market_value": first(r, "market_value", "current_value", "value"),
                "sector": first(r, "sector", "sector_type"),
                "asset_class": first(r, "asset_class", "instrument_type"),
                "yield": first(r, "yield", "dividend_yield", "income_yield"),
                "protection_state": first(r, "protection_state", "stop_health"),
            }
            for r in rows
        ],
    }


def compact_symbol_cards(payload: Any, max_rows: int = 80) -> dict[str, Any]:
    cards = cards_from_payload(payload)
    compact = []
    for r in list(cards.values())[:max_rows]:
        analyst = first(r, "analyst", "analyst_consensus") or {}
        compact.append({
            "symbol": symbol_of(r),
            "sector": first(r, "sector", "sector_name", "gics_sector"),
            "asset_class": first(r, "asset_class", "instrument_type"),
            "analyst_upside_pct": first(r, "analyst_upside_pct", "upside_pct") or (analyst.get("upside_pct") if isinstance(analyst, dict) else None),
            "analyst_rating": first(r, "analyst_rating") or (analyst.get("rating") if isinstance(analyst, dict) else None),
            "news_score": first(r, "news_score", "sentiment_score"),
            "top_news_count": len(first(r, "news", "top_news") or []),
        })
    return {"available": payload is not None, "card_count": len(cards), "sample_cards": compact}


def build_prompt(question: str, holdings_payload: Any, cards_payload: Any, rotation_report: dict[str, Any], grounding: dict[str, Any]) -> str:
    context = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user_question": question,
        "grounding_report": grounding,
        "holdings_context": compact_holdings(holdings_payload),
        "symbol_card_context": compact_symbol_cards(cards_payload),
        "rotation_engine_report": rotation_report,
    }
    return f"""
You are the Trade AI Rotation Advisor for a single owner/operator portfolio.

{SAFETY_BLOCK}

FACTS YOU MUST OBEY:
- Only these are symbols from the question: {', '.join(grounding.get('symbols_in_question') or [])}.
- If grounding_report.no_model_supported_action is true, say no evidence-supported trim amount is available.
- If any grounding_report.missing_flags exist, do not say "no missing data".
- If a symbol fact says sector=Materials, do not call it Industrials.
- If a symbol fact says tax impact is not available, do not claim a positive tax impact.
- If a symbol is not held in an account type, do not say the recommendation applies to that account type.

User question:
{question}

Use the JSON context below. Answer with:
1. Direct answer in plain English.
2. What to reduce, if anything, and why.
3. What to add, if anything, and why.
4. Suggested review amount or percent range. If unsupported, say range unavailable.
5. Account-specific notes only for accounts supported by the data.
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


def validate_llm_answer(answer: str, grounding: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    lower = answer.lower()
    if grounding.get("no_model_supported_action"):
        issues.append("no_model_supported_action_requires_grounded_answer")
        if re.search(r"\b\d{1,2}\s*[-–]\s*\d{1,2}\s*%", answer) or re.search(r"\b\d{1,2}\s*%", answer):
            issues.append("numeric_range_without_model_supported_action")
    if grounding.get("missing_flags") and "no missing data" in lower:
        issues.append("claimed_no_missing_data_despite_missing_flags")
    if "positive tax impact" in lower or "would have a positive tax" in lower:
        issues.append("claimed_tax_impact_without_cost_basis")

    allowed_symbols = set(grounding.get("symbols_in_question") or [])
    for token in re.findall(r"\b[A-Z0-9]{2,6}\b", answer.upper()):
        if token in SYMBOL_STOPWORDS:
            continue
        if token not in allowed_symbols and token in {"TRIM", "REVIEW"}:
            issues.append(f"answer_treated_action_word_as_symbol_{token}")

    for fact in grounding.get("symbol_facts", []):
        sym = str(fact.get("symbol") or "")
        sector = str(fact.get("sector") or "").lower()
        if sym and sector and sym.lower() in lower:
            for wrong in SECTOR_WORDS:
                if wrong != sector and wrong in lower and sector not in lower:
                    issues.append(f"possible_wrong_sector_for_{sym}: expected {sector}")
                    break
        held_aliases = {a for a in (fact.get("held_account_aliases") or []) if a}
        if sym and sym.lower() in lower:
            for alias, words in ACCOUNT_ALIASES.items():
                if alias not in held_aliases and any(w in lower for w in words):
                    issues.append(f"claimed_{sym}_applies_to_unheld_account_{alias}")
    return {"ok": not issues, "issues": sorted(set(issues))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", required=True, help="Rotation/allocation question to ask")
    ap.add_argument("--holdings", default=str(DEFAULT_HOLDINGS))
    ap.add_argument("--cards", default=str(DEFAULT_CARDS))
    ap.add_argument("--backend", choices=["local", "auto", "oauth_prompt", "prompt_only"], default="local")
    ap.add_argument("--min-pair-score", type=float, default=35.0)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow-ungrounded-llm", action="store_true", help="return raw LLM answer even if validation flags issues")
    args = ap.parse_args()

    holdings_path = Path(args.holdings)
    cards_path = Path(args.cards) if args.cards else None
    holdings_payload = load_json(holdings_path)
    cards_payload = load_json(cards_path) if cards_path and cards_path.exists() else None
    rotation_report = run_rotation_engine(holdings_path, cards_path if cards_path and cards_path.exists() else None, args.min_pair_score)
    grounding = grounding_report(args.question, holdings_payload, cards_payload, rotation_report)
    grounded_answer = deterministic_answer(args.question, grounding)
    prompt = build_prompt(args.question, holdings_payload, cards_payload, rotation_report, grounding)

    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    slug = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prompt_path = PROMPT_DIR / f"rotation_prompt_{slug}.md"
    prompt_path.write_text(prompt)

    result: dict[str, Any] = {
        "ok": True,
        "advisory_only": True,
        "backend": args.backend,
        "prompt_path": str(prompt_path),
        "rotation_summary": rotation_report.get("summary", {}) if isinstance(rotation_report, dict) else {},
        "data_quality": rotation_report.get("data_quality", {}) if isinstance(rotation_report, dict) else {},
        "grounding_report": grounding,
        "grounded_answer": grounded_answer,
    }

    if args.backend in {"prompt_only", "oauth_prompt"}:
        result["answer"] = None
        result["answer_mode"] = "prompt_only"
        result["instructions"] = "Send prompt_path content to the OAuth/cloud LLM channel for external review. No broker action is authorized."
    else:
        raw_answer = call_local_llm(prompt, timeout=args.timeout, fallback=(args.backend == "auto"))
        validation = validate_llm_answer(raw_answer, grounding)
        result["answer_validation"] = validation
        result["llm_answer_raw"] = raw_answer
        if validation["ok"] or args.allow_ungrounded_llm:
            result["answer"] = raw_answer
            result["answer_mode"] = "llm_raw"
        else:
            result["answer"] = grounded_answer + "\n\nLocal LLM answer was withheld because validation flagged: " + ", ".join(validation["issues"])
            result["answer_mode"] = "grounded"

    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result.get("answer") or json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
