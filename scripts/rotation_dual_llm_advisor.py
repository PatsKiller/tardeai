#!/usr/bin/env python3
"""
Rotation Dual LLM Advisor

Runs the grounded rotation advisor context through:
1) the local LLM, and then
2) a free/OAuth Grok prompt file for manual paste into the Grok web/app channel.

No API keys. No paid xAI API call. No outbound HTTP request.

Final answer is still safety-gated by deterministic grounding rules. Grok is a
manual second-opinion reviewer, not an execution authority.

JSON mode captures noisy local-LLM console output so stdout remains valid JSON.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rotation_llm_advisor import (  # type: ignore
    DEFAULT_CARDS,
    DEFAULT_HOLDINGS,
    PROMPT_DIR,
    build_prompt,
    call_local_llm,
    deterministic_answer,
    grounding_report,
    load_json,
    run_rotation_engine,
    validate_llm_answer,
)

SUPPORTED_ACTION_CLASSES = {"ADD_REVIEW", "TRIM_REVIEW", "ROTATE_REVIEW"}
PAIR_INTENT_WORDS = ("trim", "reduce", "rotate", "swap", "replace", "for", "into")


def build_grok_oauth_prompt(question: str, local_answer: str, grounded_answer: str, grounding: dict[str, Any]) -> str:
    return f"""
You are Grok acting as a free/OAuth second-opinion reviewer for my personal, advisory-only portfolio rotation workflow.

Rules:
- Do not provide broker instructions. Do not say an order should be placed/bought/sold.
- Do not invent a specific trim amount, position size, tax figure, or analyst upside that is not in the
  grounding report. If there is no model-supported trim/add/rotation signal, do not state a numeric review
  range — say a specific range is unavailable and set the class to WATCH or RESEARCH_MORE.
- BUT do give a genuinely useful qualitative second opinion (this is the whole point of a second opinion):
  using ONLY the facts already in the grounding report, compare the two names and tell the operator what to
  weigh. Never invent facts; if a fact is missing, say it is missing.
- Final class must be one of: HOLD, WATCH, ADD_REVIEW, TRIM_REVIEW, ROTATE_REVIEW, RESEARCH_MORE.

User question:
{question}

Grounding report you must obey:
{json.dumps(grounding, indent=2, sort_keys=True)}

Deterministic grounded answer:
{grounded_answer}

Local LLM draft answer to review:
{local_answer}

Your task (be substantive — not just "unavailable"):
1. Note in one line whether the local draft overreaches beyond the grounding report.
2. Give a SUBSTANTIVE qualitative read of the pair from the grounding facts ONLY: their sectors / asset
   classes, the analyst upside that IS present (and call out where it is missing or negative), each name's
   portfolio concentration, and account-type considerations (e.g. taxable vs tax-deferred). Tell the operator
   what factors argue for and against the move and what to check next.
3. Do NOT give a numeric trim amount; if there is no model-supported signal, say a specific review range is
   unavailable and keep the class WATCH or RESEARCH_MORE.
4. Keep it concise and operator-ready (4-7 sentences).
""".strip()


def call_local_llm_captured(prompt: str, timeout: int) -> tuple[str, str]:
    """Return (answer, captured_console_output). Keeps --json stdout parseable."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        answer = call_local_llm(prompt, timeout=timeout, fallback=False)
    return answer, buf.getvalue().strip()


def rotation_summary(rotation_report: dict[str, Any]) -> dict[str, Any]:
    summary = rotation_report.get("summary", {}) if isinstance(rotation_report, dict) else {}
    return summary if isinstance(summary, dict) else {}


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _symbols_from_row(row: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for key in ("symbol", "ticker", "from_symbol", "to_symbol", "candidate_symbol", "held_symbol", "trim_symbol", "add_symbol"):
        val = row.get(key)
        if isinstance(val, str) and re.fullmatch(r"[A-Z0-9]{1,8}", val.upper()):
            out.add(val.upper())
    return out


def _action_class(row: dict[str, Any]) -> str:
    return str(row.get("action_class") or row.get("class") or row.get("recommendation_class") or "").upper()


def _iter_action_rows(rotation_report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(rotation_report, dict):
        return rows
    for key in (
        "top_rotation_ideas",
        "top_pairs",
        "research_rotation_ideas",
        "rotation_ideas",
        "trim_review",
        "add_review",
        "top_candidates",
        "research_candidates",
        "etf_candidates",
    ):
        value = rotation_report.get(key)
        if isinstance(value, list):
            rows.extend([x for x in value if isinstance(x, dict)])
    return rows


def has_question_supported_action(question: str, grounding: dict[str, Any], rotation_report: dict[str, Any]) -> bool:
    """Question-specific action gate.

    Global rotation_summary can be nonzero because there are actionable ideas elsewhere in the portfolio.
    For a pair question like XLB -> SPCX, we require a supported ADD/TRIM/ROTATE row that references the
    symbol(s) in the question. WATCH / RESEARCH_MORE rows are not supported actions.
    """
    symbols = {str(s).upper() for s in grounding.get("symbols_in_question", []) if str(s).strip()}
    rows = _iter_action_rows(rotation_report)
    if symbols:
        relevant = [r for r in rows if _symbols_from_row(r) & symbols]
        return any(_action_class(r) in SUPPORTED_ACTION_CLASSES for r in relevant)

    # If no symbols were extracted, fall back to portfolio-wide summary only for broad rotation questions.
    q = question.lower()
    if not any(w in q for w in PAIR_INTENT_WORDS):
        return False
    s = rotation_summary(rotation_report)
    return _num(s.get("trim_review")) > 0 or _num(s.get("add_review")) > 0 or _num(s.get("rotation_ideas")) > 0


def infer_no_model_supported_action(question: str, grounding: dict[str, Any], rotation_report: dict[str, Any]) -> bool:
    """Fail-safe no-action inference.

    The grounding helper is authoritative when it explicitly says no action, but pair-specific questions
    also need pair-specific gating. A global nonzero rotation summary must not make XLB -> SPCX actionable
    unless a supported action row actually references XLB or SPCX.
    """
    if bool(grounding.get("no_model_supported_action")):
        return True
    if not has_question_supported_action(question, grounding, rotation_report):
        return True
    return False


def forced_no_action_answer(question: str, rotation_report: dict[str, Any]) -> str:
    s = rotation_summary(rotation_report)
    return (
        "No model-supported trim, add, or rotation action is available for this specific question. "
        f"The portfolio-wide rotation summary is trim_review={int(_num(s.get('trim_review')))}, "
        f"add_review={int(_num(s.get('add_review')))}, and rotation_ideas={int(_num(s.get('rotation_ideas')))}, "
        "but no supported ADD/TRIM/ROTATE row is grounded to the symbols in this question. "
        "A specific review amount or percent range is unavailable. Keep this as WATCH / RESEARCH_MORE and use the Grok OAuth prompt only as a manual second opinion; no broker action is authorized."
    )


def build_trust_verdict(
    *,
    no_model_supported_action: bool,
    grounding: dict[str, Any],
    local_validation: dict[str, Any],
    answer_mode: str,
    grok_oauth_prompt_path: Path,
) -> dict[str, Any]:
    """Machine-readable UI/API trust block for production advisory gating."""
    local_ok = bool(local_validation.get("ok"))
    validation_issues = list(local_validation.get("issues") or [])
    inferred_no_action_from_question = no_model_supported_action and not bool(grounding.get("no_model_supported_action"))
    return {
        "final_authority": "grounded_rotation_engine",
        "broker_action": "none",
        "advisory_only": True,
        "answer_mode": answer_mode,
        "model_supported_action": not no_model_supported_action,
        "range_policy": "range_unavailable_when_no_supported_action" if no_model_supported_action else "review_range_allowed_if_grounded",
        "no_model_supported_action": no_model_supported_action,
        "inferred_no_action_from_summary": inferred_no_action_from_question,
        "inferred_no_action_from_question_symbols": inferred_no_action_from_question,
        "local_validation_ok": local_ok,
        "local_validation_issue_count": len(validation_issues),
        "local_validation_issues": validation_issues,
        "grok_mode": "free_oauth_manual_prompt",
        "grok_prompt_path": str(grok_oauth_prompt_path),
        "grok_can_override_grounding": False,
        "uses_api_key": False,
        "uses_paid_xai_api": False,
        "uses_direct_grok_http": False,
        "production_gate": "PASS_ADVISORY_REVIEW" if (no_model_supported_action or local_ok) else "PASS_GROUNDED_FALLBACK",
        "operator_required": True,
        "notes": [
            "Final answer remains grounded when no supported add/trim/rotation action exists for the question symbols.",
            "Local and Grok outputs are second opinions only; neither creates or authorizes broker action.",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", required=True)
    ap.add_argument("--holdings", default=str(DEFAULT_HOLDINGS))
    ap.add_argument("--cards", default=str(DEFAULT_CARDS))
    ap.add_argument("--min-pair-score", type=float, default=35.0)
    ap.add_argument("--local-timeout", type=int, default=300)
    ap.add_argument("--skip-local", action="store_true", help="Only build grounded answer and Grok OAuth prompt (no local LLM)")
    ap.add_argument("--print-grok-prompt-path", action="store_true", help="print only the Grok OAuth prompt path for shell pipelines")
    ap.add_argument("--print-grok-prompt", action="store_true", help="print the full Grok OAuth prompt with copy markers for manual paste")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    holdings_path = Path(args.holdings)
    cards_path = Path(args.cards) if args.cards else None
    holdings_payload = load_json(holdings_path)
    cards_payload = load_json(cards_path) if cards_path and cards_path.exists() else None
    rotation_report = run_rotation_engine(holdings_path, cards_path if cards_path and cards_path.exists() else None, args.min_pair_score)
    grounding = grounding_report(args.question, holdings_payload, cards_payload, rotation_report)
    no_model_supported_action = infer_no_model_supported_action(args.question, grounding, rotation_report)
    grounded_answer = forced_no_action_answer(args.question, rotation_report) if no_model_supported_action else deterministic_answer(args.question, grounding)
    prompt = build_prompt(args.question, holdings_payload, cards_payload, rotation_report, grounding)

    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    slug = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prompt_path = PROMPT_DIR / f"rotation_dual_prompt_{slug}.md"
    grok_oauth_prompt_path = PROMPT_DIR / f"rotation_grok_oauth_prompt_{slug}.md"
    prompt_path.write_text(prompt)

    local_console_output = ""
    if args.skip_local:
        local_answer = grounded_answer
        local_validation = {"ok": False, "issues": ["local_skipped"]}
    else:
        local_answer, local_console_output = call_local_llm_captured(prompt, timeout=args.local_timeout)
        local_validation = validate_llm_answer(local_answer, grounding)

    grok_oauth_prompt = build_grok_oauth_prompt(
        question=args.question,
        local_answer=local_answer,
        grounded_answer=grounded_answer,
        grounding=grounding,
    )
    grok_oauth_prompt_path.write_text(grok_oauth_prompt)

    if args.print_grok_prompt_path:
        print(str(grok_oauth_prompt_path))
        return 0

    if args.print_grok_prompt:
        # Manual free/OAuth Grok path: copy the body below into the Grok web/app channel.
        # This NEVER calls Grok over an API — it only emits the prompt for manual paste.
        print("===== COPY BELOW INTO GROK =====")
        print(grok_oauth_prompt)
        print("===== END GROK PROMPT =====")
        print(f"Prompt file: {grok_oauth_prompt_path}")
        return 0

    # Final answer policy: no-action cases stay grounded. Grok OAuth is a manual second-opinion path.
    if no_model_supported_action:
        final_answer = grounded_answer
        answer_mode = "grounded_no_supported_action"
    elif local_validation.get("ok"):
        final_answer = local_answer
        answer_mode = "local_validated_pending_grok_oauth_review"
    else:
        final_answer = grounded_answer
        answer_mode = "grounded_pending_grok_oauth_review"

    trust_verdict = build_trust_verdict(
        no_model_supported_action=no_model_supported_action,
        grounding=grounding,
        local_validation=local_validation,
        answer_mode=answer_mode,
        grok_oauth_prompt_path=grok_oauth_prompt_path,
    )

    result: dict[str, Any] = {
        "ok": True,
        "advisory_only": True,
        "backend": "local_plus_grok_oauth_prompt",
        "answer_mode": answer_mode,
        "answer": final_answer,
        "trust_verdict": trust_verdict,
        "prompt_path": str(prompt_path),
        "grok_oauth_prompt_path": str(grok_oauth_prompt_path),
        "grok_oauth_instructions": "Open Grok with free/OAuth login, paste the grok_oauth_prompt_path content, and compare Grok's response to the grounded answer. No API key or paid API call is used.",
        "rotation_summary": rotation_summary(rotation_report),
        "data_quality": rotation_report.get("data_quality", {}) if isinstance(rotation_report, dict) else {},
        "grounding_report": grounding,
        "grounded_answer": grounded_answer,
        "local_answer_raw": local_answer,
        "local_answer_validation": local_validation,
        "local_console_output": local_console_output,
        "grok_second_opinion": {
            "mode": "oauth_prompt_manual",
            "ok": None,
            "answer": None,
            "prompt_path": str(grok_oauth_prompt_path),
        },
    }

    print(json.dumps(result, indent=2, sort_keys=True) if args.json else final_answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
