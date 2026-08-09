"""Re-Entry LLM Insight — DeepSeek Flash analysis for stopped-out symbols.

Two call types, both governed and advisory-only:

  A. Stop-Out Quality Assessment
     - For any symbol in the re-entry decision desk
     - Analyses whether the stop was well-managed, a whipsaw, or poorly handled

  B. Re-Entry Thesis Generation
     - For READY TO REVIEW or NEAR ENTRY symbols
     - Produces a thesis: what changed, why re-enter, what invalidates

Model: deepseek-v4-flash (FAST policy, no thinking, no fallback)
Daily caps: 20 stop-out quality calls + 10 thesis calls
Cost: ~$0.007/day at max usage

Results stored in ui_prefs under portfolio.reentry.llm_insights.v1
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

# ── Core call — uses canonical DeepSeek client ──


@dataclass
class InsightResult:
    symbol: str
    success: bool
    provider: str = "deepseek"
    model_used: str = "deepseek-v4-flash"
    requested_policy: str = "FAST"
    executed_policy: str | None = None
    cost_estimate: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    request_id: str | None = None
    fallback_used: bool = False
    error: str | None = None
    analysis_raw: str | None = None
    analysis_parsed: dict[str, Any] | None = None


def _call_deepseek_flash(
    prompt: str,
    symbol: str,
    *,
    max_tokens: int = 600,
    timeout: float = 45.0,
) -> dict[str, Any]:
    """Single governed DeepSeek V4 Flash call. No fallback, no retry, JSON-only output."""
    try:
        from lib.deepseek_client import DeepSeekError, chat
        from lib.llm_model_registry import get_deepseek_api_key

        key, _, _ = get_deepseek_api_key()
        if not key:
            return {
                "success": False,
                "error": "DEEPSEEK_API_KEY not configured",
                "cost_estimate": 0.0,
            }

        started = time.time()
        resp = chat(
            policy="FAST",
            prompt=prompt,
            timeout=timeout,
            max_tokens=max_tokens,
            thinking="disabled",
            response_json=False,  # parse manually for robustness
        )
        latency = int((time.time() - started) * 1000)

        if not resp.ok or not resp.content:
            return {
                "success": False,
                "error": resp.error_message or "no content returned",
                "cost_estimate": resp.estimated_cost_usd or 0.0,
                "latency_ms": latency,
                "fallback_used": resp.fallback_used,
                "request_sent": getattr(resp, "request_sent", False),
            }

        content = resp.content.strip()
        usage = resp.usage or {}

        # Parse JSON from the response (robust against markdown fences)
        parsed = None
        try:
            # Strip markdown code fences if present
            clean = content
            if clean.startswith("```"):
                lines = clean.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                clean = "\n".join(lines)
            parsed = json.loads(clean)
        except json.JSONDecodeError:
            # Try to extract JSON object from the content
            import re
            m = re.search(r'\{[^{}]*\}', content)
            if m:
                try:
                    parsed = json.loads(m.group())
                except json.JSONDecodeError:
                    pass

        return {
            "success": True,
            "content": content,
            "parsed": parsed,
            "provider": "deepseek",
            "model_used": resp.returned_model or "deepseek-v4-flash",
            "requested_policy": resp.requested_policy,
            "executed_policy": resp.executed_policy,
            "cost_estimate": resp.estimated_cost_usd or 0.0,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "latency_ms": latency,
            "request_id": resp.request_id,
            "fallback_used": resp.fallback_used,
        }

    except DeepSeekError as e:
        return {
            "success": False,
            "error": f"{getattr(e, 'code', 'DEEPSEEK_ERROR')}: {e}",
            "cost_estimate": 0.0,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)[:200],
            "cost_estimate": 0.0,
        }


# ── Stop-Out Quality Assessment ──


def _build_stop_quality_prompt(
    symbol: str,
    exit_price: float | None,
    stop_price: float | None,
    realized_pnl: float | None,
    realized_pnl_pct: float | None,
    current_price: float | None,
    rsi: float | None,
    wash_blocked: bool,
    company: str | None,
    sector_industry: str | None,
) -> str:
    current_str = f"${current_price:.2f}" if current_price is not None else "unavailable"
    rsi_str = f"{rsi:.1f}" if rsi is not None else "unavailable"
    exit_str = f"${exit_price:.2f}" if exit_price is not None else "unavailable"
    stop_str = f"${stop_price:.2f}" if stop_price is not None else "unavailable"
    pnl_str = f"${realized_pnl:+.2f} ({realized_pnl_pct:+.1f}%)" if realized_pnl is not None else "unavailable"
    company_str = company or "unknown"
    sector_str = sector_industry or "unknown sector"

    return (
        f"You are an advisory-only portfolio analyst. Analyze the quality of a past stop-out exit. "
        f"Do NOT recommend buying or selling. Do NOT provide prices, stops, or targets. "
        f"Respond with a single JSON object, no markdown, no commentary.\n\n"
        f"Symbol: {symbol}\n"
        f"Company: {company_str}\n"
        f"Sector/Industry: {sector_str}\n"
        f"Exit price: {exit_str}\n"
        f"Stop price: {stop_str}\n"
        f"Realized P&L: {pnl_str}\n"
        f"Current price: {current_str}\n"
        f"Current RSI(14): {rsi_str}\n"
        f"Wash-sale blocked: {'yes' if wash_blocked else 'no'}\n\n"
        f"JSON schema:\n"
        f'{{"stop_quality":"well_managed"|"marginal"|"poorly_managed"|"whipsaw"|"insufficient_evidence",'
        f'"stop_quality_reason":"1-2 sentence explanation",'
        f'"reentry_risk":"low"|"medium"|"high",'
        f'"reentry_risk_reason":"1 sentence why",'
        f'"key_observation":"most important fact about this exit"}}'
    )


def assess_stop_quality(
    symbol: str,
    *,
    exit_price: float | None = None,
    stop_price: float | None = None,
    realized_pnl: float | None = None,
    realized_pnl_pct: float | None = None,
    current_price: float | None = None,
    rsi: float | None = None,
    wash_blocked: bool = False,
    company: str | None = None,
    sector_industry: str | None = None,
) -> InsightResult:
    """Assess the quality of a past stop-out using DeepSeek Flash.

    Call cap: 20/day. This function does NOT enforce the cap internally —
    the caller should batch and limit calls.
    """
    prompt = _build_stop_quality_prompt(
        symbol=symbol,
        exit_price=exit_price,
        stop_price=stop_price,
        realized_pnl=realized_pnl,
        realized_pnl_pct=realized_pnl_pct,
        current_price=current_price,
        rsi=rsi,
        wash_blocked=wash_blocked,
        company=company,
        sector_industry=sector_industry,
    )

    result = _call_deepseek_flash(prompt, symbol, max_tokens=400, timeout=45)

    return InsightResult(
        symbol=symbol,
        success=result["success"],
        provider=result.get("provider", "deepseek"),
        model_used=result.get("model_used", "deepseek-v4-flash"),
        requested_policy=result.get("requested_policy", "FAST"),
        executed_policy=result.get("executed_policy"),
        cost_estimate=result.get("cost_estimate", 0.0),
        prompt_tokens=result.get("prompt_tokens", 0),
        completion_tokens=result.get("completion_tokens", 0),
        latency_ms=result.get("latency_ms", 0),
        request_id=result.get("request_id"),
        fallback_used=result.get("fallback_used", False),
        error=result.get("error"),
        analysis_raw=result.get("content"),
        analysis_parsed=result.get("parsed"),
    )


# ── Re-Entry Thesis Generation ──


def _build_thesis_prompt(
    symbol: str,
    company: str | None,
    sector_industry: str | None,
    current_price: float | None,
    entry_low: float | None,
    entry_high: float | None,
    exit_price: float | None,
    rsi: float | None,
    wash_blocked: bool,
    analyst_rec: str | None,
    catalyst_headline: str | None,
) -> str:
    price_str = f"${current_price:.2f}" if current_price is not None else "unavailable"
    zone_str = (
        f"${entry_low:.2f}–${entry_high:.2f}"
        if entry_low is not None and entry_high is not None
        else "no validated zone"
    )
    exit_str = f"${exit_price:.2f}" if exit_price is not None else "unavailable"
    rsi_str = f"{rsi:.1f}" if rsi is not None else "unavailable"
    company_str = company or "unknown"
    sector_str = sector_industry or "unknown sector"
    analyst_str = analyst_rec or "unavailable"
    catalyst_str = catalyst_headline or "no known catalyst"

    return (
        f"You are an advisory-only investment analyst. Generate a re-entry thesis for a symbol "
        f"that meets mechanical readiness criteria (in zone, RSI constructive). "
        f"Do NOT recommend buying or selling. Do NOT provide prices, stops, or entry points. "
        f"Use only the facts provided; do not invent missing data. "
        f"Respond with a single JSON object, no markdown, no commentary.\n\n"
        f"Symbol: {symbol}\n"
        f"Company: {company_str}\n"
        f"Sector/Industry: {sector_str}\n"
        f"Current price: {price_str}\n"
        f"Entry zone: {zone_str}\n"
        f"Exit price (when stopped out): {exit_str}\n"
        f"Current RSI(14): {rsi_str}\n"
        f"Wash-sale blocked: {'yes' if wash_blocked else 'no'}\n"
        f"Analyst consensus: {analyst_str}\n"
        f"Recent catalyst: {catalyst_str}\n\n"
        f"JSON schema:\n"
        f'{{"thesis":"2-3 sentence re-entry thesis: what changed since exit, why consider re-entry now, what would invalidate",'
        f'"confidence":"low"|"medium"|"high",'
        f'"key_risk":"primary risk to the thesis",'
        f'"missing_evidence":"what data would strengthen or weaken the case"}}'
    )


def generate_reentry_thesis(
    symbol: str,
    *,
    company: str | None = None,
    sector_industry: str | None = None,
    current_price: float | None = None,
    entry_low: float | None = None,
    entry_high: float | None = None,
    exit_price: float | None = None,
    rsi: float | None = None,
    wash_blocked: bool = False,
    analyst_rec: str | None = None,
    catalyst_headline: str | None = None,
) -> InsightResult:
    """Generate a re-entry thesis using DeepSeek Flash.

    Only call for READY TO REVIEW or NEAR ENTRY symbols.
    Call cap: 10/day. This function does NOT enforce the cap internally.
    """
    prompt = _build_thesis_prompt(
        symbol=symbol,
        company=company,
        sector_industry=sector_industry,
        current_price=current_price,
        entry_low=entry_low,
        entry_high=entry_high,
        exit_price=exit_price,
        rsi=rsi,
        wash_blocked=wash_blocked,
        analyst_rec=analyst_rec,
        catalyst_headline=catalyst_headline,
    )

    result = _call_deepseek_flash(prompt, symbol, max_tokens=500, timeout=45)

    return InsightResult(
        symbol=symbol,
        success=result["success"],
        provider=result.get("provider", "deepseek"),
        model_used=result.get("model_used", "deepseek-v4-flash"),
        requested_policy=result.get("requested_policy", "FAST"),
        executed_policy=result.get("executed_policy"),
        cost_estimate=result.get("cost_estimate", 0.0),
        prompt_tokens=result.get("prompt_tokens", 0),
        completion_tokens=result.get("completion_tokens", 0),
        latency_ms=result.get("latency_ms", 0),
        request_id=result.get("request_id"),
        fallback_used=result.get("fallback_used", False),
        error=result.get("error"),
        analysis_raw=result.get("content"),
        analysis_parsed=result.get("parsed"),
    )


# ── Batch runner for decision desk integration ──

STOP_QUALITY_DAILY_CAP = 20
THESIS_DAILY_CAP = 10
CACHE_KEY = "portfolio.reentry.llm_insights.v1"


def run_reentry_insights(
    rows: list[dict[str, Any]],
    *,
    quality_cap: int = STOP_QUALITY_DAILY_CAP,
    thesis_cap: int = THESIS_DAILY_CAP,
) -> dict[str, InsightResult]:
    """Run stop-out quality + thesis insight for top re-entry candidates.

    Returns a dict of symbol -> InsightResult.
    Quality assessments run first (up to quality_cap), then thesis (up to thesis_cap).
    Only assesses symbols with price and RSI data.
    """
    results: dict[str, InsightResult] = {}
    quality_count = 0
    thesis_count = 0

    # Sort: actionable first (READY/NEAR), then by price age ascending
    order = {"READY TO REVIEW": 0, "NEAR ENTRY": 1, "OVERSOLD REVIEW": 2, "WAIT": 3, "WASH BLOCK": 4}
    sorted_rows = sorted(
        rows,
        key=lambda r: (
            order.get((r.get("intel") or {}).get("state", "WAIT"), 10),
            r.get("price_age_h") or 999,
        ),
    )

    for row in sorted_rows:
        sym = row.get("symbol", "")
        if not sym:
            continue
        intel = row.get("intel") or {}
        state = intel.get("state", "WAIT")
        price = row.get("price")
        rsi = row.get("rsi")
        entry_low = row.get("entry_low")
        entry_high = row.get("entry_high")
        wash_blocked = row.get("wash_blocked", False)
        company = row.get("company")
        cat = row.get("catalyst") or {}

        # Skip symbols without market data
        if price is None or rsi is None:
            continue

        # ── Stop-Out Quality (all eligible symbols) ──
        if quality_count < quality_cap:
            try:
                result = assess_stop_quality(
                    sym,
                    exit_price=price,  # best available price context
                    stop_price=row.get("stop"),
                    current_price=price,
                    rsi=rsi,
                    wash_blocked=wash_blocked,
                    company=company,
                    sector_industry=company,  # already includes sector
                )
                results[f"{sym}:quality"] = result
                quality_count += 1
            except Exception:
                pass

        # ── Re-Entry Thesis (READY TO REVIEW / NEAR ENTRY only) ──
        if state in ("READY TO REVIEW", "NEAR ENTRY") and thesis_count < thesis_cap:
            try:
                analyst_rec = None
                if cat and cat.get("verified"):
                    analyst_rec = cat.get("headline")
                result = generate_reentry_thesis(
                    sym,
                    company=company,
                    sector_industry=company,
                    current_price=price,
                    entry_low=entry_low,
                    entry_high=entry_high,
                    exit_price=price,
                    rsi=rsi,
                    wash_blocked=wash_blocked,
                    analyst_rec=analyst_rec,
                    catalyst_headline=cat.get("headline") if isinstance(cat, dict) else None,
                )
                results[f"{sym}:thesis"] = result
                thesis_count += 1
            except Exception:
                pass

        # Early exit when both caps are reached
        if quality_count >= quality_cap and thesis_count >= thesis_cap:
            break

    return results


def store_insights(db_execute, results: dict[str, InsightResult]) -> bool:
    """Persist insights to ui_prefs for frontend consumption."""
    import datetime

    insights_dict: dict[str, dict[str, Any]] = {}
    total_cost = 0.0
    success_count = 0

    for key, r in results.items():
        insights_dict[key] = {
            "symbol": r.symbol,
            "success": r.success,
            "provider": r.provider,
            "model_used": r.model_used,
            "requested_policy": r.requested_policy,
            "executed_policy": r.executed_policy,
            "cost_estimate": r.cost_estimate,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "latency_ms": r.latency_ms,
            "request_id": r.request_id,
            "fallback_used": r.fallback_used,
            "error": r.error,
            "analysis_raw": r.analysis_raw,
            "analysis_parsed": r.analysis_parsed,
        }
        total_cost += r.cost_estimate
        if r.success:
            success_count += 1

    payload = {
        "insights": insights_dict,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_calls": len(results),
        "success_count": success_count,
        "total_estimated_cost_usd": round(total_cost, 6),
        "model": "deepseek-v4-flash",
        "policy": "FAST",
        "advisory_only": True,
    }

    try:
        db_execute(
            """INSERT INTO ui_prefs (key, value, updated_at)
               VALUES (%s, %s::jsonb, NOW())
               ON CONFLICT (key) DO UPDATE
               SET value = EXCLUDED.value, updated_at = NOW()""",
            (CACHE_KEY, json.dumps(payload)),
        )
        return True
    except Exception:
        return False
