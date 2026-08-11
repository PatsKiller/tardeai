"""Advisory Opinion Engine — S3 opinion layer for the Advisory Desk.

Reads config/advisory_desk.yaml for routing. Composes with
cio_governed_model_bridge.py (the canonical router, never a parallel one).

Phase 2:
  - Stable-prefix system prompt (provider cache friendly) + volatile user body
  - Local opinion cache keyed by material advisory_row_hash
  - Run telemetry: cache hits, tokens, cost estimates, rows_called
  - Per-row Flash only; one Pro synthesis call dollars-first

Architecture:
  - The LLM never computes a number — every figure comes from the evidence bundle.
  - Deterministic verdict is computed first and passed in; model disagreement is
    flagged, not resolved silently.
  - Per-row hash cache is the primary cost lever (unchanged row = 0 model calls).
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
TELEMETRY_PATH = CACHE_DIR / "advisory_opinion_run_telemetry.jsonl"
SYNTHESIS_CACHE_PATH = CACHE_DIR / "advisory_synthesis_cache.json"

# Default stable system prefix when yaml omits stable_system_prompt
_DEFAULT_STABLE_SYSTEM = """You are a disciplined portfolio analyst writing for a sophisticated retail operator.
READ_ONLY_ADVISORY only — never invent prices, percentages, dates, or share counts.
Every figure in your response must already exist in the evidence bundle provided in the user message.
If the evidence is thin, say so and keep the opinion brief.

Verdict taxonomy (use exactly one):
ADD, AVOID, EXIT, HOLD, INSUFFICIENT_DATA, RE_ENTER, TRIM, WAIT

IPS defaults (unless evidence overrides): max single position 8%, max drawdown 25%.

Output schema — return ONLY one JSON object:
{
  "verdict": "<one of taxonomy>",
  "conviction": <0-100 integer>,
  "what_changed": "<one line>",
  "rationale": "<2-4 sentences citing evidence titles/dates>",
  "key_risk": "<strongest argument AGAINST the verdict — required>",
  "evidence_cited": ["ref_id1", "ref_id2"]
}

Rules:
- Every number in prose must appear verbatim in the evidence bundle.
- evidence_cited must only use ref_ids/titles present in the bundle.
- If you disagree with the deterministic verdict, say so and set verdict to your recommendation.
- key_risk is REQUIRED.
- No order types, no share counts, no execution instructions.
- CONVICTION measures thesis confidence (evidence quality), NOT position size.
"""

_DEFAULT_SYNTHESIS_SYSTEM = """You are a portfolio synthesis analyst for a READ_ONLY_ADVISORY desk.
Return ONE concise paragraph (4-6 sentences), no JSON, no order tickets.
Lead with the largest dollar-at-stake item first. Name exactly three things the operator should consider today.
Cite symbols. Name one blind spot. Do not invent numbers not present in the rows.
"""


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


def _append_telemetry(event: dict[str, Any]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        event = dict(event)
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())
        with TELEMETRY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except Exception:
        pass


# Module-level lane-failure cache — lanes that fail twice consecutively are skipped.
_DEAD_LANES: dict[str, int] = {}  # lane -> consecutive failure count
_CALL_TIMEOUT = 60  # seconds — Ollama with a large evidence bundle needs ~15-30s


def _call_bridge(
    messages: list[dict[str, str]],
    config: dict[str, Any],
    prefer_lane: str = "deepseek-flash",
    max_tokens: int = 500,
    *,
    task_type: str | None = None,
) -> dict[str, Any] | None:
    """Call the model endpoint via the governed bridge (DeepSeek) or Ollama.

    DeepSeek lanes MUST go through cio_governed_model_bridge on port 8766 so
    reservation, daily caps, never_escalate, and consumption logging apply.
    Direct api.deepseek.com calls are forbidden (P0 cost governance).
    """
    import urllib.error
    import urllib.request

    lanes = config.get("routing", {}).get("lane_preference", [])
    lane = next((l for l in lanes if l.get("lane") == prefer_lane), lanes[0] if lanes else {})
    lane_name = lane.get("lane", "unknown")
    provider = str(lane.get("provider", "")).lower()

    if lane_name in _DEAD_LANES and _DEAD_LANES[lane_name] >= 2:
        return {
            "ok": False,
            "error": f"lane '{lane_name}' failed 2x consecutively — skipped",
            "model": lane.get("model", "?"),
        }

    model_id = lane.get("model", "deepseek-v4-flash")
    bridge_cfg = config.get("routing", {}).get("bridge", {})
    default_bridge = "http://127.0.0.1:8766/v1/chat/completions"

    resolved_task = task_type or bridge_cfg.get("task_type") or "advisory_opinion"
    if prefer_lane in ("deepseek-pro",) or "synthesis" in str(resolved_task):
        resolved_task = "advisory_synthesis"
    elif prefer_lane in ("deepseek-flash",) or provider == "deepseek":
        if resolved_task not in ("advisory_opinion", "advisory_synthesis"):
            resolved_task = "advisory_opinion"

    if provider == "deepseek":
        endpoint = bridge_cfg.get("endpoint") or default_bridge
        lane_ep = str(lane.get("endpoint") or "")
        if "api.deepseek.com" in lane_ep or not lane_ep:
            endpoint = bridge_cfg.get("endpoint") or default_bridge
        elif "8766" in lane_ep or "bridge" in lane_ep.lower():
            endpoint = lane_ep
        else:
            endpoint = bridge_cfg.get("endpoint") or default_bridge
    else:
        endpoint = lane.get("endpoint") or bridge_cfg.get("endpoint") or default_bridge

    payload: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}
    using_bridge = (
        provider == "deepseek"
        or "8766" in str(endpoint)
        or "bridge" in str(endpoint).lower()
    )
    if using_bridge:
        headers["X-TradeAI-Agent"] = bridge_cfg.get("caller", "advisory_desk")
        headers["X-TradeAI-Task-Type"] = resolved_task
        headers["X-TradeAI-Process-Id"] = (
            "advisory_desk_synthesis"
            if resolved_task == "advisory_synthesis"
            else "advisory_desk_opinion"
        )

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_CALL_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if isinstance(body, dict) and body.get("error") and not body.get("choices"):
                err = body.get("error") or {}
                code = err.get("code") or "GOVERNANCE_ERROR"
                msg = err.get("message") or str(err)
                if code in ("COST_CAP_EXCEEDED", "CIRCUIT_OPEN", "PROCESS_NOT_REGISTERED"):
                    return {
                        "ok": False,
                        "error": f"{code}: {msg}",
                        "model": model_id,
                        "lane": lane_name,
                        "governance_refused": True,
                        "governance_code": code,
                    }
                count = _DEAD_LANES.get(lane_name, 0) + 1
                _DEAD_LANES[lane_name] = count
                return {
                    "ok": False,
                    "error": f"{code}: {msg}",
                    "model": model_id,
                    "lane": lane_name,
                    "governance_refused": True,
                    "governance_code": code,
                }
            choices = body.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                usage = body.get("usage") or {}
                return {
                    "ok": True,
                    "content": content,
                    "model": body.get("model") or model_id,
                    "lane": lane_name,
                    "usage": usage,
                    "via_bridge": using_bridge,
                    "task_type": resolved_task,
                }
            return {"ok": False, "error": "No choices in response", "raw": body}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {}
        err = (body or {}).get("error") or {}
        code = err.get("code") or f"HTTP_{e.code}"
        msg = err.get("message") or str(e)
        if code in ("COST_CAP_EXCEEDED", "CIRCUIT_OPEN", "PROCESS_NOT_REGISTERED"):
            return {
                "ok": False,
                "error": f"{code}: {msg}",
                "model": model_id,
                "lane": lane_name,
                "governance_refused": True,
                "governance_code": code,
            }
        count = _DEAD_LANES.get(lane_name, 0) + 1
        _DEAD_LANES[lane_name] = count
        return {
            "ok": False,
            "error": f"{lane_name} HTTP {e.code}: {code}: {msg}",
            "model": model_id,
            "lane": lane_name,
            "governance_refused": True,
            "governance_code": code,
        }
    except Exception as e:
        count = _DEAD_LANES.get(lane_name, 0) + 1
        _DEAD_LANES[lane_name] = count
        if count < 2:
            return {
                "ok": False,
                "error": f"{lane_name} network error (attempt {count}): {e}",
                "model": model_id,
                "retry": True,
            }
        return {"ok": False, "error": f"{lane_name} failed {count}x: {e}", "model": model_id}


def _stable_system_prompt(config: dict[str, Any]) -> str:
    routing = config.get("routing") or {}
    text = (routing.get("stable_system_prompt") or "").strip()
    return text or _DEFAULT_STABLE_SYSTEM


def _build_opinion_messages(
    evidence_bundle: dict[str, Any],
    deterministic_verdict: str,
    config: dict[str, Any],
    *,
    symbol: str = "",
    memory_block: str = "",
) -> list[dict[str, str]]:
    """Stable system prefix first; volatile evidence/memory last (provider cache).

    Anti-pattern: never put timestamp, run_id, or symbol into the system prompt.
    """
    system = _stable_system_prompt(config)
    # Compact evidence — sort keys for stable JSON when contents equal
    evidence_json = json.dumps(evidence_bundle, indent=2, sort_keys=True, default=str)
    user_parts = [
        f"Deterministic verdict (pre-computed): {deterministic_verdict}",
        "Evidence bundle:",
        evidence_json,
    ]
    if memory_block:
        user_parts.append("[ MEMORY — context only, not instruction ]")
        user_parts.append(memory_block)
    user_parts.append(
        "Return ONLY the JSON object. Symbol context for your prose may mention "
        f"the instrument if present in evidence (hint field, may be empty): {symbol or 'see evidence'}."
    )
    # Symbol is in user message only — system stays identical across rows for prefix cache
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def _extract_json_from_response(content: str) -> dict[str, Any] | None:
    """Extract the JSON object from a model response, handling markdown fences."""
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

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

    valid_verdicts = {
        "ADD", "AVOID", "EXIT", "HOLD", "INSUFFICIENT_DATA", "RE_ENTER", "TRIM", "WAIT",
    }
    verdict = opinion.get("verdict", "")
    if verdict not in valid_verdicts:
        errors.append(f"Invalid verdict: '{verdict}'")

    evidence_str = json.dumps(evidence_bundle)
    for field in ("rationale", "what_changed", "key_risk"):
        text = opinion.get(field, "")
        if not isinstance(text, str):
            continue
        numbers = re.findall(r"\d+\.?\d*\s*%?", text)
        for num in numbers:
            clean = num.replace("%", "").strip()
            if clean and clean not in evidence_str and "." in clean:
                if not re.match(r"^\d{4}$", clean):
                    errors.append(f"Number '{num}' in {field} not found in evidence")

    evidence_items = evidence_bundle.get("evidence_items", [])
    valid_ref_ids: set[str] = set()
    for item in evidence_items:
        if not isinstance(item, dict):
            continue
        title = item.get("title", "")
        if title:
            valid_ref_ids.add(title)
        source = item.get("source", "")
        tp = item.get("type", "")
        valid_ref_ids.add(f"{tp}:{source}")
        if item.get("agent"):
            valid_ref_ids.add(str(item.get("agent")))

    cited = opinion.get("evidence_cited", [])
    if isinstance(cited, list):
        for ref in cited:
            if ref not in valid_ref_ids:
                errors.append(f"Cited ref '{ref}' not found in evidence bundle")

    if not opinion.get("key_risk"):
        errors.append("key_risk is required but missing")

    if verdict and verdict != deterministic_verdict and verdict in valid_verdicts:
        opinion["model_deterministic_disagreement"] = True
        opinion["deterministic_verdict"] = deterministic_verdict
    else:
        opinion["model_deterministic_disagreement"] = False

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
    memory_block: str = "",
) -> dict[str, Any]:
    """Generate an LLM opinion for one advisory desk row.

    Uses per-row material hash cache — only calls the model if the row changed.
    """
    if config is None:
        config = _load_config()

    row_hash = row.get("advisory_row_hash", "")
    opinion_cache = _load_opinion_cache()

    if not force and row_hash and row_hash in opinion_cache:
        cached = dict(opinion_cache[row_hash]) if isinstance(opinion_cache[row_hash], dict) else {}
        if cached:
            cached["cache_hit"] = True
            return cached

    messages = _build_opinion_messages(
        evidence_bundle,
        deterministic_verdict,
        config,
        symbol=str(row.get("symbol") or ""),
        memory_block=memory_block,
    )

    result = None
    errors: list[str] = []
    routing = config.get("routing", {})

    for lane in routing.get("lane_preference", []):
        lane_name = lane.get("lane", "unknown")
        purpose = str(lane.get("purpose", "")).lower()
        if "synthesis" in purpose or (
            "pro" in lane_name and "flash" not in lane_name
        ):
            continue
        result = _call_bridge(
            messages,
            config,
            prefer_lane=lane_name,
            task_type="advisory_opinion",
        )
        if result and result.get("ok"):
            break
        if result:
            errors.append(f"{lane_name}: {result.get('error', 'unknown')}")
            if result.get("governance_code") == "COST_CAP_EXCEEDED":
                break

    if not result or not result.get("ok"):
        return {
            "verdict": deterministic_verdict,
            "conviction": int((row.get("confidence") or 0.5) * 100),
            "what_changed": "No change — model unavailable.",
            "rationale": row.get(
                "rationale",
                "Deterministic fallback — all model lanes unreachable.",
            ),
            "key_risk": (
                "Model unavailable — opinion is deterministic only, "
                "no counter-argument analysis performed."
            ),
            "evidence_cited": [],
            "advisory_row_hash": row_hash,
            "model_deterministic_disagreement": False,
            "llm_rejected": False,
            "degraded": True,
            "degraded_reason": f"All lanes failed: {'; '.join(errors)}",
            "cache_hit": False,
            "usage": {},
        }

    content = result.get("content", "")
    opinion = _extract_json_from_response(content)

    if not opinion:
        return {
            "verdict": deterministic_verdict,
            "conviction": int((row.get("confidence") or 0.5) * 100),
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
            "usage": result.get("usage") or {},
        }

    validated, validation_errors = validate_opinion_output(
        opinion, evidence_bundle, deterministic_verdict
    )
    validated["advisory_row_hash"] = row_hash
    validated["model"] = result.get("model", "unknown")
    validated["lane"] = result.get("lane", "unknown")
    validated["cache_hit"] = False
    validated["usage"] = result.get("usage") or {}
    validated["via_bridge"] = bool(result.get("via_bridge"))

    # Only cache clean (non-rejected) opinions so bad prose does not stick
    if row_hash and not validated.get("llm_rejected"):
        opinion_cache[row_hash] = {
            k: v for k, v in validated.items() if k != "cache_hit"
        }
        _save_opinion_cache(opinion_cache)

    return validated


def _dollars_at_stake(row: dict[str, Any]) -> float:
    mv = float(row.get("market_value") or 0)
    if row.get("row_class") == "allocation":
        # Allocation drift often stores excess as market_value or weight gap
        return abs(mv)
    return abs(mv)


def _verdict_str(row: dict[str, Any]) -> str:
    v = row.get("verdict")
    if hasattr(v, "value"):
        return str(v.value)
    return str(v or "?")


def rank_rows_dollars_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort rows by dollars at stake (desc), then actionable severity."""
    severity = {
        "EXIT": 5, "TRIM": 4, "ADD": 3, "RE_ENTER": 2,
        "HOLD": 1, "WAIT": 0, "AVOID": 1, "INSUFFICIENT_DATA": 0,
    }

    def key(r: dict[str, Any]) -> tuple:
        return (
            _dollars_at_stake(r),
            severity.get(_verdict_str(r), 0),
        )

    return sorted(rows, key=key, reverse=True)


def generate_desk_synthesis(
    rows: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """One Pro call for desk synthesis — rows ranked dollars-first.

    Returns dict with text, model, usage, cache_hit, degraded flags.
    """
    if config is None:
        config = _load_config()

    routing = config.get("routing", {})
    ranked = rank_rows_dollars_first(rows)

    summary_rows: list[dict[str, Any]] = []
    for r in ranked:
        summary_rows.append({
            "symbol": r.get("symbol", "?"),
            "row_class": r.get("row_class", "?"),
            "verdict": _verdict_str(r),
            "confidence": r.get("confidence"),
            "weight_pct": r.get("weight_pct"),
            "market_value": r.get("market_value"),
            "dollars_at_stake": _dollars_at_stake(r),
            "gain_loss_pct": r.get("gain_loss_pct"),
            "days_held": r.get("days_held"),
            "rationale": str(r.get("rationale") or "")[:150],
            "evidence_count": (r.get("evidence_bundle") or {}).get("evidence_count", 0),
            "evidence_gaps": (r.get("evidence_bundle") or {}).get("evidence_gaps", []),
        })

    # Local synthesis cache: content hash of ranked material fields
    synth_key = hashlib.sha256(
        json.dumps(summary_rows, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    try:
        if not force and SYNTHESIS_CACHE_PATH.exists():
            sc = json.loads(SYNTHESIS_CACHE_PATH.read_text(encoding="utf-8"))
            if sc.get("key") == synth_key and sc.get("text"):
                return {
                    "text": sc["text"],
                    "cache_hit": True,
                    "model": sc.get("model", "cache"),
                    "usage": {},
                    "degraded": False,
                    "lead_symbol": (summary_rows[0]["symbol"] if summary_rows else None),
                    "lead_dollars": (summary_rows[0]["dollars_at_stake"] if summary_rows else None),
                }
    except Exception:
        pass

    template = routing.get("synthesis_prompt_template") or ""
    if template and "{rows_json}" in template:
        user_body = template.replace(
            "{rows_json}",
            json.dumps(summary_rows, indent=2, default=str),
        )
    else:
        user_body = (
            "Rows ranked by dollars_at_stake (largest first):\n"
            + json.dumps(summary_rows, indent=2, default=str)
            + "\n\nLead with the largest dollar item. Name three things for today."
        )

    system = (routing.get("stable_synthesis_system_prompt") or "").strip() or _DEFAULT_SYNTHESIS_SYSTEM
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_body},
    ]

    synthesis_lane = "deepseek-pro"
    lanes = routing.get("lane_preference") or []
    if not any(l.get("lane") == synthesis_lane for l in lanes):
        for l in lanes:
            if "pro" in str(l.get("lane", "")).lower() and "flash" not in str(l.get("lane", "")).lower():
                synthesis_lane = l.get("lane")
                break

    result = _call_bridge(
        messages,
        config,
        prefer_lane=synthesis_lane,
        max_tokens=800,
        task_type="advisory_synthesis",
    )
    if result and result.get("ok"):
        text = (result.get("content") or "").strip()
        if text:
            try:
                SYNTHESIS_CACHE_PATH.write_text(
                    json.dumps({
                        "key": synth_key,
                        "text": text,
                        "model": result.get("model"),
                        "at": datetime.now(timezone.utc).isoformat(),
                    }, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass
            return {
                "text": text,
                "cache_hit": False,
                "model": result.get("model"),
                "lane": result.get("lane"),
                "usage": result.get("usage") or {},
                "degraded": False,
                "via_bridge": bool(result.get("via_bridge")),
                "lead_symbol": (summary_rows[0]["symbol"] if summary_rows else None),
                "lead_dollars": (summary_rows[0]["dollars_at_stake"] if summary_rows else None),
            }
        # Empty provider content → fall through to degraded dollars-first text

    # Degraded deterministic synthesis — still dollars-first
    lead = summary_rows[0] if summary_rows else {}
    second = summary_rows[1] if len(summary_rows) > 1 else {}
    third = summary_rows[2] if len(summary_rows) > 2 else {}
    text = (
        f"[DEGRADED — Pro synthesis unreachable] "
        f"First by dollars: {lead.get('symbol')} ({lead.get('verdict')}, "
        f"${lead.get('dollars_at_stake') or 0:,.0f}). "
        f"Second: {second.get('symbol')} ({second.get('verdict')}). "
        f"Third: {third.get('symbol')} ({third.get('verdict')}). "
        f"Review allocation drift and any TRIM/EXIT above the materiality floor."
    )
    return {
        "text": text,
        "cache_hit": False,
        "model": "deterministic_degraded",
        "usage": {},
        "degraded": True,
        "lead_symbol": lead.get("symbol"),
        "lead_dollars": lead.get("dollars_at_stake"),
    }


def estimate_cost_usd(
    usage: dict[str, Any],
    *,
    model: str = "deepseek-v4-flash",
) -> float:
    """Rough USD estimate from usage when registry pricing unavailable."""
    # Snapshot rates from llm_model_registry (flash cache-miss / output)
    # flash: miss 0.14 / out 0.28 per MTok; pro higher — conservative mid
    prompt = float(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = float(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    cached = float(usage.get("prompt_cache_hit_tokens") or usage.get("cached_tokens") or 0)
    if "pro" in (model or "").lower():
        in_rate, out_rate, cache_rate = 1.0, 2.0, 0.1  # placeholder $/M if needed
    else:
        in_rate, out_rate, cache_rate = 0.14, 0.28, 0.014
    billable_in = max(prompt - cached, 0)
    return (billable_in * in_rate + cached * cache_rate + completion * out_rate) / 1_000_000.0
