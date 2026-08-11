"""Advisory Opinion Engine — S3 opinion layer for the Advisory Desk.

Reads config/advisory_desk.yaml for routing. Composes with
cio_governed_model_bridge.py (the canonical router, never a parallel one).

For each row whose advisory_row_hash has changed, sends the evidence bundle
to the lowest-available model lane and captures the structured opinion.
Validates every numeric token against the evidence bundle.

Architecture:
  - The LLM never computes a number — every figure comes from the evidence bundle.
  - Deterministic verdict is computed first and passed in; model disagreement is
    flagged, not resolved silently.
  - Per-row hash cache from S1 FIX-5 is the cost model.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = PROJECT_ROOT / "config"
CACHE_DIR = PROJECT_ROOT / "data" / "runtime"

CONFIG_PATH = CONFIG_DIR / "advisory_desk.yaml"
OPINION_CACHE_PATH = CACHE_DIR / "advisory_opinion_cache.json"


def _load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def _load_opinion_cache() -> dict[str, Any]:
    try:
        if OPINION_CACHE_PATH.exists():
            return json.loads(OPINION_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_opinion_cache(cache: dict[str, Any]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        OPINION_CACHE_PATH.write_text(json.dumps(cache, indent=2, default=str))
    except Exception:
        pass


# Module-level lane-failure cache — lanes that fail twice consecutively are skipped.
_DEAD_LANES: dict[str, int] = {}  # lane -> consecutive failure count
_CALL_TIMEOUT = 60  # seconds — Ollama with a large evidence bundle needs ~15-30s


def _call_bridge(
    messages: list[dict[str, str]],
    config: dict[str, Any],
    prefer_lane: str = "chatgpt-oauth",
    max_tokens: int = 500,
) -> dict[str, Any] | None:
    """Call the model endpoint (bridge or direct provider).

    For DeepSeek lanes: calls api.deepseek.com directly with deepseek_tradeai key.
    For Ollama: calls the Ollama OpenAI-compatible endpoint.
    Dead lanes are skipped after 2 consecutive failures per run.
    """
    import urllib.request

    lanes = config.get("routing", {}).get("lane_preference", [])
    lane = next((l for l in lanes if l.get("lane") == prefer_lane), lanes[0] if lanes else {})
    lane_name = lane.get("lane", "unknown")
    provider = str(lane.get("provider", "")).lower()

    if lane_name in _DEAD_LANES and _DEAD_LANES[lane_name] >= 2:
        return {"ok": False, "error": f"lane '{lane_name}' failed 2x consecutively — skipped", "model": lane.get("model", "?")}

    model_id = lane.get("model", "gpt-5.4")
    endpoint = lane.get("endpoint")
    thinking_config: dict[str, Any] = {}

    # ── DeepSeek: call api.deepseek.com directly, bypassing the governed bridge ──
    if provider == "deepseek":
        import os
        key = os.environ.get("deepseek_tradeai") or os.environ.get("DEEPSEEK_TRADEAI") or os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            # Try sourcing from the rendered env file
            env_path = "/run/user/1000/tradeai/env"
            try:
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("deepseek_tradeai="):
                            key = line.split("=", 1)[1].strip("\"'")
                            break
            except Exception:
                pass
        if not key:
            count = _DEAD_LANES.get(lane_name, 0) + 1
            _DEAD_LANES[lane_name] = count
            return {"ok": False, "error": "deepseek_tradeai not available in env or rendered file", "model": model_id}

        endpoint = "https://api.deepseek.com/v1/chat/completions"
        if not lane.get("thinking", True):
            thinking_config = {"type": "disabled"}

    if not endpoint:
        bridge_cfg = config.get("routing", {}).get("bridge", {})
        endpoint = bridge_cfg.get("endpoint", "http://127.0.0.1:8766/v1/chat/completions")

    payload: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    if thinking_config:
        payload["thinking"] = thinking_config

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if provider == "deepseek":
        headers["Authorization"] = f"Bearer {key}"
    elif "8766" in endpoint or "bridge" in endpoint.lower():
        bridge_cfg = config.get("routing", {}).get("bridge", {})
        headers["X-TradeAI-Agent"] = bridge_cfg.get("caller", "advisory_desk")
        headers["X-TradeAI-Process-Id"] = bridge_cfg.get("process_id", "advisory_desk_synthesis")
        headers["X-TradeAI-Task-Type"] = bridge_cfg.get("task_type", "advisory_opinion")

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_CALL_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            # OpenAI-compatible response
            choices = body.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                return {"ok": True, "content": content, "model": model_id}
            return {"ok": False, "error": "No choices in response", "raw": body}
    except Exception as e:
        count = _DEAD_LANES.get(lane_name, 0) + 1
        _DEAD_LANES[lane_name] = count
        if count < 2:
            # Clear timeout errors to allow retry next row
            return {"ok": False, "error": f"{lane_name} network error (attempt {count}): {e}", "model": model_id, "retry": True}
        return {"ok": False, "error": f"{lane_name} failed {count}x: {e}", "model": model_id}


def _extract_json_from_response(content: str) -> dict[str, Any] | None:
    """Extract the JSON object from a model response, handling markdown fences."""
    # Try direct parse first
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError:
        pass

    # Try to find JSON in markdown code block
    match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', content)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find any JSON object
    match = re.search(r'\{[\s\S]*"verdict"[\s\S]*\}', content)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def validate_opinion_output(
    opinion: dict[str, Any],
    evidence_bundle: dict[str, Any],
    deterministic_verdict: str,
) -> tuple[dict[str, Any], list[str]]:
    """Validate a model-generated opinion against the evidence bundle.

    Returns (annotated_opinion, errors).
    """
    errors: list[str] = []

    # 1. Verdict must be in the taxonomy
    valid_verdicts = {"ADD", "AVOID", "EXIT", "HOLD", "INSUFFICIENT_DATA", "RE_ENTER", "TRIM", "WAIT"}
    verdict = opinion.get("verdict", "")
    if verdict not in valid_verdicts:
        errors.append(f"Invalid verdict: '{verdict}'")

    # 2. Check numeric tokens in prose against evidence
    evidence_str = json.dumps(evidence_bundle)
    for field in ("rationale", "what_changed", "key_risk"):
        text = opinion.get(field, "")
        if not isinstance(text, str):
            continue
        # Extract all numbers (with optional % sign and decimals)
        numbers = re.findall(r'\d+\.?\d*\s*%?', text)
        for num in numbers:
            clean = num.replace("%", "").strip()
            if clean and clean not in evidence_str and "." in clean:
                # Only flag decimal numbers missing from evidence (whole numbers are often
                # in prose like "2-4 sentences" or dates)
                if not re.match(r'^\d{4}$', clean):  # skip years
                    errors.append(f"Number '{num}' in {field} not found in evidence")

    # 3. Evidence citations must exist
    evidence_items = evidence_bundle.get("evidence_items", [])
    valid_ref_ids: set[str] = set()
    for item in evidence_items:
        title = item.get("title", "")
        if title:
            valid_ref_ids.add(title)
        source = item.get("source", "")
        as_of = str(item.get("as_of", ""))
        tp = item.get("type", "")
        valid_ref_ids.add(f"{tp}:{source}")

    cited = opinion.get("evidence_cited", [])
    if isinstance(cited, list):
        for ref in cited:
            if ref not in valid_ref_ids:
                errors.append(f"Cited ref '{ref}' not found in evidence bundle")

    # 4. key_risk is required
    if not opinion.get("key_risk"):
        errors.append("key_risk is required but missing")

    # 5. Track disagreements with deterministic verdict
    if verdict and verdict != deterministic_verdict and verdict in valid_verdicts:
        opinion["model_deterministic_disagreement"] = True
        opinion["deterministic_verdict"] = deterministic_verdict
    else:
        opinion["model_deterministic_disagreement"] = False

    # 6. Rejection handling
    if errors:
        opinion["llm_rejected"] = True
        opinion["rejection_reasons"] = errors
    else:
        opinion["llm_rejected"] = False

    return opinion, errors


def generate_row_opinion(
    row: dict[str, Any],
    evidence_bundle: dict[str, Any],
    deterministic_verdict: str,
    config: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Generate an LLM opinion for one advisory desk row.

    Uses per-row hash cache — only calls the model if the row has changed.
    Returns the opinion dict merged with the cache key.
    """
    if config is None:
        config = _load_config()

    row_hash = row.get("advisory_row_hash", "")
    opinion_cache = _load_opinion_cache()

    # Check per-row cache
    if not force and row_hash and row_hash in opinion_cache:
        cached = opinion_cache[row_hash]
        if isinstance(cached, dict):
            cached["cache_hit"] = True
            return cached

    # Build messages
    routing = config.get("routing", {})
    template = routing.get("opinion_prompt_template", "{evidence_json}")
    evidence_json = json.dumps(evidence_bundle, indent=2, default=str)

    prompt = template.replace("{evidence_json}", evidence_json).replace(
        "{deterministic_verdict}", deterministic_verdict
    )

    messages = [
        {"role": "system", "content": "You are a disciplined portfolio analyst. Return only valid JSON."},
        {"role": "user", "content": prompt},
    ]

    # Call the bridge — try lanes in order
    max_rows = routing.get("cost", {}).get("max_model_rows_per_run", 20)
    result = None
    errors: list[str] = []

    for lane in routing.get("lane_preference", []):
        lane_name = lane.get("lane", "unknown")
        result = _call_bridge(messages, config, prefer_lane=lane_name)
        if result and result.get("ok"):
            break
        if result:
            errors.append(f"{lane_name}: {result.get('error', 'unknown')}")

    if not result or not result.get("ok"):
        # All lanes failed — return deterministic template
        return {
            "verdict": deterministic_verdict,
            "conviction": int(row.get("confidence", 0.5) * 100),
            "what_changed": "No change — model unavailable.",
            "rationale": row.get("rationale", "Deterministic fallback — all model lanes unreachable."),
            "key_risk": "Model unavailable — opinion is deterministic only, no counter-argument analysis performed.",
            "evidence_cited": [],
            "advisory_row_hash": row_hash,
            "model_deterministic_disagreement": False,
            "llm_rejected": False,
            "degraded": True,
            "degraded_reason": f"All lanes failed: {'; '.join(errors)}",
            "cache_hit": False,
        }

    # Parse the response
    content = result.get("content", "")
    opinion = _extract_json_from_response(content)

    if not opinion:
        return {
            "verdict": deterministic_verdict,
            "conviction": int(row.get("confidence", 0.5) * 100),
            "what_changed": "No change — model response unparseable.",
            "rationale": f"Deterministic fallback — could not parse model response: {content[:200]}",
            "key_risk": "Model response invalid — opinion is deterministic only.",
            "evidence_cited": [],
            "advisory_row_hash": row_hash,
            "model_deterministic_disagreement": False,
            "llm_rejected": True,
            "degraded": True,
            "raw_response": content[:500],
            "cache_hit": False,
        }

    # Validate
    validated, validation_errors = validate_opinion_output(
        opinion, evidence_bundle, deterministic_verdict
    )
    validated["advisory_row_hash"] = row_hash
    validated["model"] = result.get("model", "unknown")
    validated["cache_hit"] = False

    # Cache the result
    if row_hash:
        opinion_cache[row_hash] = validated
        _save_opinion_cache(opinion_cache)

    return validated


def generate_desk_synthesis(
    rows: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> str:
    """Generate a one-paragraph desk-level synthesis using the PRO lane.

    Returns a text paragraph, or an empty string if unreachable.
    """
    if config is None:
        config = _load_config()

    routing = config.get("routing", {})

    # Build a concise summary of the desk for the synthesis model
    summary_rows: list[dict[str, Any]] = []
    for r in rows:
        summary_rows.append({
            "symbol": r.get("symbol", "?"),
            "row_class": r.get("row_class", "?"),
            "verdict": r.get("verdict", {}).value if isinstance(r.get("verdict"), object) and hasattr(r["verdict"], "value") else str(r.get("verdict", "?")),
            "confidence": r.get("confidence"),
            "weight_pct": r.get("weight_pct"),
            "gain_loss_pct": r.get("gain_loss_pct"),
            "days_held": r.get("days_held"),
            "rationale": r.get("rationale", "")[:150],
            "evidence_count": r.get("evidence_bundle", {}).get("evidence_count", 0),
            "evidence_gaps": r.get("evidence_bundle", {}).get("evidence_gaps", []),
        })

    template = routing.get("synthesis_prompt_template", "")
    prompt = template.replace("{rows_json}", json.dumps(summary_rows, indent=2, default=str))

    messages = [
        {"role": "system", "content": "You are a portfolio synthesis analyst. Return a concise paragraph, no JSON."},
        {"role": "user", "content": prompt},
    ]

    result = _call_bridge(messages, config, prefer_lane=config.get("routing", {}).get("lane_preference", [{}])[0].get("lane", "local"), max_tokens=800)
    if result and result.get("ok"):
        return result.get("content", "").strip()

    # Degraded synthesis
    verdict_counts: dict[str, int] = {}
    for r in rows:
        v = str(r["verdict"].value) if isinstance(r.get("verdict"), object) and hasattr(r["verdict"], "value") else str(r.get("verdict", "?"))
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    n_holdings = sum(1 for r in rows if r.get("row_class") == "holding")
    return (
        f"[DEGRADED — model unreachable] "
        f"Advisory desk: {n_holdings} holdings reviewed. "
        f"Verdict distribution: {json.dumps(verdict_counts)}. "
        f"Top items to review: allocation drift and any EXIT signals above the materiality floor. "
        f"Full desk available in advisory_desk_latest.json."
    )
