#!/usr/bin/env python3
"""canary_local_llm_models.py — CPU-only workload canary for candidate local LLM models.

Tests disabled models against real Trade AI workload prompts without modifying
production routing, .env, or DB. Each model is unloaded after testing.

Usage:
    .venv/bin/python scripts/canary_local_llm_models.py
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

OLLAMA_BASE = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
CANDIDATE_MODELS = ["gemma4:e4b", "gemma4:e2b", "qwen3:14b"]
TIMEOUT = 120
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "model_canary"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"candidate_workload_canary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

# ── Sample payloads ────────────────────────────────────────────────────

SAMPLE_TRADE = {
    "trade_id": 464, "symbol": "AXTI", "broker": "schwab",
    "account": "schwab_rollover_ira", "entry_price": 2.87,
    "exit_price": 17.74, "pnl": 3791.88, "pnl_pct": 518.14,
    "entry_date": "2025-07-01", "exit_date": "2025-11-26",
    "hold_days": 148, "source_table": "trade_transactions",
    "enrichment": {
        "ticker_classification": {"strategy": "speculative_growth", "confidence": 0.7},
        "watchlist": {"strategy": "speculative_growth",
                      "thesis": "BUY signal. Analyst upgrade with target >15% above current price."},
    },
}

SAMPLE_CLOSED_TRADE = {
    "trade": {
        "symbol": "BLBD", "entry_price": 80.32, "exit_price": 76.30,
        "pnl": -4.02, "pnl_pct": -5.0, "strategy_id": "swing_breakout",
        "entry_time": "2025-10-01", "exit_time": "2025-10-15",
        "exit_reason": "stop_hit", "stop_price": 76.30, "target_price": 86.75,
    },
    "proposals": [],
    "stop_audit": [],
    "tca": None,
}

# ── Test prompts ───────────────────────────────────────────────────────

TESTS = [
    {
        "name": "basic_json",
        "system": "Return ONLY valid JSON with no other text.",
        "prompt": 'Return valid JSON only with exact shape {"answer":4,"status":"ok"}',
        "required_fields": ["answer", "status"],
        "validate": lambda d: d.get("answer") == 4 and d.get("status") == "ok",
    },
    {
        "name": "strategy_classifier",
        "system": "You are a trade strategy classifier. Return ONLY valid JSON with no other text. Every array element must be a plain string.",
        "prompt": f"""Classify this trade. Return ONLY valid JSON:
{{"strategy_id": "string", "confidence": 0.0, "reasoning": "string", "evidence_used": ["string"], "missing_evidence": ["string"], "requires_review": true}}

TRADE DATA:
{json.dumps(SAMPLE_TRADE, indent=2)}

Rules: Use enrichment data as strong evidence. If ticker and watchlist agree, confidence should be 0.7-0.9.""",
        "required_fields": ["strategy_id", "confidence", "reasoning", "evidence_used", "missing_evidence", "requires_review"],
        "validate": lambda d: bool(d.get("strategy_id")) and isinstance(d.get("confidence"), (int, float)),
    },
    {
        "name": "close_trade_analysis",
        "system": "You are a trade analyst. Return ONLY valid JSON with no other text.",
        "prompt": f"""Analyze this closed trade. Return ONLY valid JSON:
{{"summary": "string", "thesis_assessment": "string", "execution_assessment": "string", "stop_assessment": "string", "tca_assessment": null, "lessons": ["string"], "confidence": 0.0, "data_quality_gaps": ["string"]}}

TRADE DATA:
{json.dumps(SAMPLE_CLOSED_TRADE, indent=2)}""",
        "required_fields": ["summary", "thesis_assessment", "execution_assessment", "stop_assessment", "lessons", "confidence"],
        "validate": lambda d: bool(d.get("summary")) and bool(d.get("thesis_assessment")),
    },
]


def get_loaded_models():
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/ps", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return [m.get("name", "") for m in json.loads(resp.read()).get("models", [])]
    except Exception:
        return []


def unload_model(name):
    try:
        payload = json.dumps({"model": name, "keep_alive": 0, "prompt": ""}).encode()
        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/generate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception:
        return False


def parse_json(raw):
    if not raw:
        return None
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


def call_model(model, system_prompt, user_prompt):
    payload = json.dumps({
        "model": model, "stream": False,
        "options": {"temperature": 0, "seed": 1, "num_gpu": 0, "num_ctx": 2048, "num_predict": 1024},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read())
        content = data.get("message", {}).get("content", "").strip()
        duration = round(data.get("total_duration", 0) / 1e9, 1)
        tokens = data.get("eval_count", 0)
        return content, duration, tokens


def run_test(model, test):
    loaded_before = get_loaded_models()
    t0 = time.time()
    result = {
        "model": model,
        "test_name": test["name"],
        "timestamp": datetime.now().isoformat(),
        "pass": False,
        "content_populated": False,
        "json_parse_success": False,
        "required_fields_present": False,
        "thinking_only_failure": False,
        "bad_content_failure": False,
        "duration_seconds": 0,
        "tokens": 0,
        "error": None,
        "loaded_models_before": loaded_before,
        "loaded_models_after": [],
    }

    try:
        content, duration, tokens = call_model(model, test["system"], test["prompt"])
        result["duration_seconds"] = duration
        result["tokens"] = tokens
        result["content_populated"] = bool(content)

        if not content:
            result["thinking_only_failure"] = True
            result["error"] = "empty_content"
        elif content.startswith("<think>") and "{" not in content:
            result["thinking_only_failure"] = True
            result["error"] = "thinking_only"
        else:
            parsed = parse_json(content)
            if parsed:
                result["json_parse_success"] = True
                missing = [f for f in test["required_fields"] if f not in parsed or parsed[f] is None]
                result["required_fields_present"] = len(missing) == 0
                if missing:
                    result["error"] = f"missing_fields: {missing}"
                if test["validate"](parsed):
                    result["pass"] = True
                elif not result["error"]:
                    result["bad_content_failure"] = True
                    result["error"] = "validation_failed"
            else:
                result["bad_content_failure"] = True
                result["error"] = f"json_parse_failed: {content[:100]}"

    except Exception as e:
        result["duration_seconds"] = round(time.time() - t0, 1)
        result["error"] = str(e)

    result["loaded_models_after"] = get_loaded_models()
    return result


def main():
    print("=" * 70)
    print("Local LLM Candidate Workload Canary (CPU-only)")
    print("=" * 70)

    all_results = []

    for model in CANDIDATE_MODELS:
        print(f"\n{'─' * 60}")
        print(f"Model: {model}")
        print(f"{'─' * 60}")

        for test in TESTS:
            print(f"  [{test['name']}] ", end="", flush=True)
            result = run_test(model, test)
            all_results.append(result)

            status = "PASS" if result["pass"] else "FAIL"
            detail = f"{result['duration_seconds']}s, {result['tokens']} tokens"
            if result["error"]:
                detail += f", {result['error'][:60]}"
            print(f"{status} — {detail}")

            # Log each result
            with open(LOG_FILE, "a") as f:
                f.write(json.dumps(result) + "\n")

        # Unload model
        print(f"  Unloading {model}...", end=" ", flush=True)
        unload_model(model)
        time.sleep(2)
        loaded = get_loaded_models()
        still_loaded = model in str(loaded)
        print(f"{'WARN: still loaded' if still_loaded else 'OK'} — loaded: {loaded}")

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")

    for model in CANDIDATE_MODELS:
        model_results = [r for r in all_results if r["model"] == model]
        passed = sum(1 for r in model_results if r["pass"])
        total = len(model_results)
        print(f"  {model}: {passed}/{total} passed")
        for r in model_results:
            s = "PASS" if r["pass"] else "FAIL"
            print(f"    [{s}] {r['test_name']} — {r['duration_seconds']}s" +
                  (f" ({r['error'][:50]})" if r["error"] else ""))

    # Best candidate
    scores = {}
    for model in CANDIDATE_MODELS:
        model_results = [r for r in all_results if r["model"] == model]
        scores[model] = sum(1 for r in model_results if r["pass"])
    best = max(scores, key=scores.get)
    print(f"\nBest candidate: {best} ({scores[best]}/{len(TESTS)} passed)")
    print(f"Log: {LOG_FILE}")

    # Final loaded models
    final = get_loaded_models()
    print(f"Final loaded models: {final}")

    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
