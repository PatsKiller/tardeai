#!/usr/bin/env python3
"""
Rotation Dual LLM Advisor

Runs the grounded rotation advisor context through:
1) the local LLM, and then
2) Grok via xAI's OpenAI-compatible chat completions API.

Final answer is still safety-gated by the deterministic grounding rules. Grok is
used as a second-opinion reviewer, not an execution authority.

Requirements:
  export XAI_API_KEY="..."
Optional:
  export XAI_BASE_URL="https://api.x.ai/v1"
  export XAI_GROK_MODEL="grok-4.3"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
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

DEFAULT_XAI_BASE_URL = "https://api.x.ai/v1"
DEFAULT_XAI_MODEL = "grok-4.3"


def call_grok(prompt: str, local_answer: str, grounded_answer: str, grounding: dict[str, Any], timeout: int, model: str) -> dict[str, Any]:
    api_key = os.getenv("XAI_API_KEY", "").strip()
    if not api_key:
        return {
            "ok": False,
            "error": "missing_XAI_API_KEY",
            "answer": "Grok second opinion skipped because XAI_API_KEY is not set.",
        }

    base = os.getenv("XAI_BASE_URL", DEFAULT_XAI_BASE_URL).rstrip("/")
    url = f"{base}/chat/completions"
    reviewer_prompt = f"""
You are Grok acting as a second-opinion reviewer for an advisory-only portfolio rotation workflow.

Do not provide broker instructions. Do not invent tax impact, account placement, position sizes, or trim amounts.

Grounding report:
{json.dumps(grounding, indent=2, sort_keys=True)}

Deterministic grounded answer:
{grounded_answer}

Local LLM draft answer:
{local_answer}

Task:
1. Identify whether the local answer overreaches beyond the grounding report.
2. Provide a corrected second-opinion answer.
3. If no trim/add/rotation signal is supported, say range unavailable and recommend WATCH or RESEARCH_MORE only.
4. Keep the answer concise and operator-ready.
""".strip()

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a strict second-opinion portfolio rotation reviewer. Advisory only."},
            {"role": "user", "content": reviewer_prompt},
        ],
        "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        return {
            "ok": bool(text),
            "model": data.get("model", model),
            "answer": text,
            "usage": data.get("usage", {}),
        }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[-2000:]
        return {"ok": False, "error": f"http_{exc.code}", "answer": body}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "answer": "Grok second opinion failed."}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", required=True)
    ap.add_argument("--holdings", default=str(DEFAULT_HOLDINGS))
    ap.add_argument("--cards", default=str(DEFAULT_CARDS))
    ap.add_argument("--min-pair-score", type=float, default=35.0)
    ap.add_argument("--local-timeout", type=int, default=300)
    ap.add_argument("--grok-timeout", type=int, default=120)
    ap.add_argument("--grok-model", default=os.getenv("XAI_GROK_MODEL", DEFAULT_XAI_MODEL))
    ap.add_argument("--skip-local", action="store_true", help="Only build grounded answer and ask Grok")
    ap.add_argument("--json", action="store_true")
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
    prompt_path = PROMPT_DIR / f"rotation_dual_prompt_{slug}.md"
    prompt_path.write_text(prompt)

    if args.skip_local:
        local_answer = grounded_answer
        local_validation = {"ok": False, "issues": ["local_skipped"]}
    else:
        local_answer = call_local_llm(prompt, timeout=args.local_timeout, fallback=False)
        local_validation = validate_llm_answer(local_answer, grounding)

    grok = call_grok(
        prompt=prompt,
        local_answer=local_answer,
        grounded_answer=grounded_answer,
        grounding=grounding,
        timeout=args.grok_timeout,
        model=args.grok_model,
    )

    # Final answer policy: no-action cases stay grounded. Grok/local are recorded as opinions.
    if grounding.get("no_model_supported_action"):
        final_answer = grounded_answer
        answer_mode = "grounded_no_supported_action"
    elif grok.get("ok"):
        final_answer = grok.get("answer", grounded_answer)
        answer_mode = "grok_second_opinion"
    elif local_validation.get("ok"):
        final_answer = local_answer
        answer_mode = "local_validated"
    else:
        final_answer = grounded_answer
        answer_mode = "grounded_fallback"

    result = {
        "ok": True,
        "advisory_only": True,
        "backend": "local_plus_grok",
        "answer_mode": answer_mode,
        "answer": final_answer,
        "prompt_path": str(prompt_path),
        "rotation_summary": rotation_report.get("summary", {}) if isinstance(rotation_report, dict) else {},
        "data_quality": rotation_report.get("data_quality", {}) if isinstance(rotation_report, dict) else {},
        "grounding_report": grounding,
        "grounded_answer": grounded_answer,
        "local_answer_raw": local_answer,
        "local_answer_validation": local_validation,
        "grok_second_opinion": grok,
    }

    print(json.dumps(result, indent=2, sort_keys=True) if args.json else final_answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
