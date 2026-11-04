"""Read-only qualification of research scores for a TOP list (FQ-114).

A composite score is not proof of named technical inputs or CIO research. Both list APIs use this boundary before
ranking/pagination. Scores and the curator's persisted research queue are unchanged; CIO stance is read, never derived.
No store constructor/rebuild, persist, notification, provider or broker transport is called here.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_TECHNICAL = (("rsi", "RSI"), ("macd_signal", "MACD"), ("sma_20", "20-day average"),
              ("sma_50", "50-day average"), ("sma_200", "200-day average"))
_THESIS_CACHE: dict[str, Any] = {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def _instant(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return result.astimezone(timezone.utc) if result.tzinfo else None


def read_theses(symbols: list[str], root: Path = PROJECT_ROOT) -> tuple[dict[str, Any], str | None]:
    """Read the CIO store's existing current-head projection, without its write/rebuild-capable constructor."""
    from scripts.lib.symbol_thesis_coverage import symbol_thesis_id

    path = Path(root) / "data/cio/cio_theses_projection.json"
    try:
        stat = path.stat()
        signature = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        if _THESIS_CACHE.get("signature") != signature:
            payload = json.loads(path.read_bytes())
            heads = payload.get("current") if isinstance(payload, dict) else None
            if not isinstance(heads, dict):
                return {}, "CIO research snapshot could not be read"
            _THESIS_CACHE.clear()
            _THESIS_CACHE.update(signature=signature, heads=heads)
        heads = _THESIS_CACHE["heads"]
        return {symbol: heads.get(symbol_thesis_id(symbol)) for symbol in symbols}, None
    except (OSError, ValueError, TypeError):
        return {}, "CIO research snapshot could not be read"


def read_contexts(symbols: list[str], *, db_query=None, root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Batch the same indicator normalization and price-stat inputs the opportunity detail uses. SELECT only."""
    from lib.data_broker.indicator_snapshot import _normalize_symbol_row
    from lib.data_broker.price_stats import get_price_stats
    from scripts.lib.cio_market_context_state import load_market_risk_projection

    syms = sorted({str(s).strip().upper() for s in symbols if s})
    if db_query is None:
        from scripts.api_v3_opportunities import _db_query
        db_query = _db_query
    technical: dict[str, dict[str, Any]] = {}
    errors = {}
    if syms:
        try:
            rows = db_query("""SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s, full_result, atr, computed_at
                 FROM indicator_confluence_cache WHERE upper(symbol) = ANY(%s) AND profile = 'swing'
                 ORDER BY upper(symbol), computed_at DESC""", (syms,)) or []
            for row in rows:
                technical[row["s"]] = _normalize_symbol_row(row["s"], row.get("full_result"), row.get("atr"))
                technical[row["s"]]["as_of"] = row.get("computed_at")
            stats = get_price_stats(db_query, syms)
            for symbol in syms:
                target = technical.setdefault(symbol, {})
                for name in ("sma_20", "sma_50", "sma_200"):
                    value = (stats.get(symbol) or {}).get(name)
                    if _number(value) is not None:
                        target[name] = value
        except Exception:  # a failed evidence read cannot promote a partial research score
            errors["technical"] = "Technical inputs could not be read"
            technical = {}
    theses, thesis_error = read_theses(syms, root)
    if thesis_error:
        errors["theses"] = thesis_error
    return {"technical": technical, "theses": theses, "market_risk": load_market_risk_projection(root), "errors": errors}


def qualify(items: list[dict[str, Any]], context: dict[str, Any], cfg: dict[str, Any], *, now=None) -> tuple[list[dict], dict]:
    """Keep every research row, but assign TOP ranks only to complete, CIO-reviewed candidates.

    The original score/rank/stance remain explicit diagnostic fields. No position verdict is calculated here.
    """
    from lib.data_broker import opportunity as op
    from scripts.lib.market_risk.cio_context import evaluated_tier

    now = now or datetime.now(timezone.utc)
    floor = _number(((cfg.get("presets") or {}).get("top5") or {}).get("min_coverage"))
    gate = cfg.get("market_risk_gate") or {}
    risk = context.get("market_risk") or {}
    tier = evaluated_tier(risk, max_age_hours=gate.get("max_stale_hours"), now=now)
    risk_at = _instant(risk.get("as_of"))
    max_age = _number(gate.get("max_stale_hours"))
    if risk_at is None or risk_at > now or (max_age is not None and (now - risk_at).total_seconds() > max_age * 3600):
        tier = None
    held_tiers = set(gate.get("hold_tiers") or [])
    entry_types = set(gate.get("entry_types") or [])
    out = []
    for assessment in items:
        row = dict(assessment)
        symbol = row.get("symbol")
        tech = (context.get("technical") or {}).get(symbol) or {}
        thesis = (context.get("theses") or {}).get(symbol)
        thesis = thesis if isinstance(thesis, dict) else {}
        missing = []
        coverage = _number(row.get("coverage"))
        if floor is None or coverage is None or not 0 <= coverage <= 1 or coverage < floor:
            missing.append("factor coverage below the top-list minimum")
        for key, label in _TECHNICAL:
            value = tech.get(key)
            if key == "macd_signal":
                present = isinstance(value, str) and value.strip().upper() not in ("", "UNKNOWN", "N/A", "NONE", "UNAVAILABLE")
            else:
                number = _number(value)
                present = number is not None and (0 <= number <= 100 if key == "rsi" else number > 0)
            if not present:
                missing.append(label)
        summary = thesis.get("summary")
        stance = thesis.get("stance")
        as_of = thesis.get("published_ts") or thesis.get("updated_ts") or thesis.get("created_ts") or thesis.get("as_of")
        at = _instant(as_of)
        has_thesis = isinstance(summary, str) and bool(summary.strip()) and thesis.get("status") == "active"
        has_stance = isinstance(stance, str) and stance.strip().upper() not in ("", "UNKNOWN", "N/A", "NONE", "UNVERIFIED")
        if not has_thesis:
            missing.append((context.get("errors") or {}).get("theses") or "CIO research thesis")
        if not has_stance:
            missing.append("CIO stance")
        if at is None or at > now:
            missing.append("dated CIO review")
        reviewed = has_thesis and has_stance and at is not None and at <= now
        entry = row.get("type") in entry_types or row.get("curator_type") in entry_types
        risk_held = entry and (tier is None or tier in held_tiers)
        if risk_held:
            missing.append(f"new entries held: market risk {tier or 'unverified'}")
        score = _number(row.get("conviction"))
        if score is None:
            missing.append("research score")
        eligible = not missing
        reason = "CIO-reviewed with technical coverage" if eligible else "Unreviewed for the top list — data missing: " + "; ".join(missing)
        row.update({
            "research_rank": row.get("rank"), "automated_stance": row.get("stance"), "rank": None,
            "stance": stance if reviewed else None,
            "cio_review": {"reviewed": reviewed, "stance": stance if reviewed else None,
                           "as_of": at.isoformat().replace("+00:00", "Z") if reviewed else None,
                           "thesis_version": thesis.get("thesis_version"), "source": "cio_theses_projection.current"},
            "top_eligibility": {"eligible": eligible, "missing": missing, "reason": reason,
                                "coverage_floor": floor, "entry_held": risk_held},
        })
        out.append(row)
    qualified = op.sort_items([r for r in out if r["top_eligibility"]["eligible"]], "conviction")
    for rank, row in enumerate(qualified, 1):
        row["rank"] = rank
    notice = f"Market risk {tier}: new long ideas are held." if tier in held_tiers else (
        "Market risk could not be confirmed: new long ideas are held." if tier is None else f"Market risk {tier}.")
    return out, {"market_risk_tier": tier, "notice": notice, "eligible": len(qualified),
                 "research_only": len(out) - len(qualified), "coverage_floor": floor}


def sort_qualified(items: list[dict], sort: str) -> list[dict]:
    from lib.data_broker import opportunity as op
    return sorted(op.sort_items(items, sort), key=lambda row: not row["top_eligibility"]["eligible"])
