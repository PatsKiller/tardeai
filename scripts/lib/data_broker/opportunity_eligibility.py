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
_TECHNICAL = (
    ("rsi", "RSI"),
    ("macd_signal", "MACD"),
    ("sma_20", "20-day average"),
    ("sma_50", "50-day average"),
    ("sma_200", "200-day average"),
)
_THESIS_CACHE: dict[str, Any] = {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _instant(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return result.astimezone(timezone.utc) if result.tzinfo else None


def _technical_receipt(tech: dict, now: datetime | None, *, registry=None) -> dict:
    """Re-evaluate every contributing input at the caller's clock; mixed sources never borrow clocks."""
    from lib.data_broker.envelope import envelope, registry_spec

    try:
        spec = registry_spec("technicals", registry=registry)
        window = _number(spec.get("stale_after_hours"))
        if window is None or window <= 0:
            window = None
    except (OSError, ValueError, TypeError, AttributeError, KeyError, OverflowError):
        spec, window = {}, None
    evidence = tech.get("input_evidence")
    evidence = evidence if isinstance(evidence, dict) else {} if "input_evidence" in tech else None
    inputs, clocks = {}, []
    for key, _ in _TECHNICAL:
        # Flat indicator records have one source clock. read_contexts records an explicit field receipt
        # whenever price_stats overrides an average, so neither side can refresh the other.
        raw = evidence.get(key) if evidence is not None else {"as_of": tech.get("as_of"), "source": tech.get("source")}
        raw = raw if isinstance(raw, dict) else {}
        at = _instant(raw.get("as_of"))
        source = raw.get("source")
        source = source if isinstance(source, dict) else {"table": source} if isinstance(source, str) and source else {}
        reason = (
            "technical freshness contract unavailable"
            if window is None
            else "technical source unavailable"
            if not source
            else "technical timestamp unavailable or invalid"
            if at is None
            else "caller clock unavailable or invalid"
            if now is None
            else "technical timestamp is in the future"
            if at > now
            else "technical inputs are stale"
            if (now - at).total_seconds() > window * 3600
            else None
        )
        if at is not None:
            clocks.append(at)
        # envelope's permissive legacy clock coercion is not authority to repair a missing/naive clock.
        safe_spec = {
            key: spec.get(key)
            for key in ("domain", "class", "table", "file", "writer", "writer_status", "projection", "primary_provider")
        }
        safe_spec["stale_after_hours"] = window
        env = envelope(
            "technicals",
            at,
            now=now if now is not None else at,
            registry={"technicals": safe_spec},
            source=source,
        )
        if now is None:
            env["age_hours"] = None
        if env.get("gap") and reason is None:
            reason = "technical producer unavailable"
        if reason:
            env["stale"] = True
        inputs[key] = {**env, "verified": reason is None, "reason": reason}
    fresh = all(row["verified"] for row in inputs.values())
    return {
        "verified": fresh,
        "as_of": min(clocks).isoformat().replace("+00:00", "Z") if len(clocks) == len(_TECHNICAL) else None,
        "source": {key: row["source"] for key, row in inputs.items()},
        "stale_after_hours": window,
        "inputs": inputs,
    }


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


def _reviewable(thesis: Any, now: datetime) -> bool:
    if not isinstance(thesis, dict) or thesis.get("status") != "active":
        return False
    summary, stance = thesis.get("summary"), thesis.get("stance")
    at = _instant(
        thesis.get("published_ts") or thesis.get("updated_ts") or thesis.get("created_ts") or thesis.get("as_of")
    )
    return (
        isinstance(summary, str)
        and bool(summary.strip())
        and isinstance(stance, str)
        and stance.strip().upper()
        not in ("", "UNKNOWN", "N/A", "NONE", "UNVERIFIED", "UNAVAILABLE", "NULL", "NAN", "—", "-")
        and at is not None
        and at <= now
    )


def read_contexts(
    symbols: list[str], *, db_query=None, root: Path = PROJECT_ROOT, technical_symbols=None, now=None, registry=None
) -> dict[str, Any]:
    """Batch the same indicator normalization and price-stat inputs the opportunity detail uses. SELECT only."""
    from lib.data_broker.indicator_snapshot import _normalize_symbol_row
    from lib.data_broker.price_stats import get_price_stats
    from scripts.lib.cio_market_context_state import load_market_risk_projection

    all_syms = sorted({str(s).strip().upper() for s in symbols if s})
    theses, thesis_error = read_theses(all_syms, root)
    now = _instant(now) if now is not None else datetime.now(timezone.utc)
    requested = set(all_syms if technical_symbols is None else technical_symbols)
    # Missing CIO research already disqualifies a TOP pick. Do not pull a year of daily bars for the whole universe.
    syms = [s for s in all_syms if s in requested and now is not None and _reviewable(theses.get(s), now)]
    if db_query is None:
        from scripts.api_v3_opportunities import _db_query

        db_query = _db_query
    technical: dict[str, dict[str, Any]] = {}
    errors = {}
    if syms:
        try:
            rows = (
                db_query(
                    """SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s, full_result, atr, computed_at
                 FROM indicator_confluence_cache WHERE upper(symbol) = ANY(%s) AND profile = 'swing'
                 ORDER BY upper(symbol), computed_at DESC""",
                    (syms,),
                )
                or []
            )
            for row in rows:
                technical[row["s"]] = _normalize_symbol_row(row["s"], row.get("full_result"), row.get("atr"))
                technical[row["s"]]["as_of"] = row.get("computed_at")
                technical[row["s"]]["input_evidence"] = {
                    key: {"as_of": row.get("computed_at"), "source": "indicator_confluence_cache"}
                    for key, _ in _TECHNICAL
                }
            stats = get_price_stats(db_query, syms, now=now, registry=registry)
            for symbol in syms:
                target = technical.setdefault(symbol, {})
                for name in ("sma_20", "sma_50", "sma_200"):
                    value = (stats.get(symbol) or {}).get(name)
                    if _number(value) is not None:
                        target[name] = value
                        target.setdefault("input_evidence", {})[name] = {
                            "as_of": (stats.get(symbol) or {}).get("as_of"),
                            "source": (stats.get(symbol) or {}).get("source"),
                        }
        except Exception:  # a failed evidence read cannot promote a partial research score
            errors["technical"] = "Technical inputs could not be read"
            technical = {}
    if thesis_error:
        errors["theses"] = thesis_error
    return {
        "technical": technical,
        "theses": theses,
        "market_risk": load_market_risk_projection(root),
        "errors": errors,
        "technical_state": {s: "read" if s in syms else "not_checked" for s in all_syms},
    }


def qualify(
    items: list[dict[str, Any]], context: dict[str, Any], cfg: dict[str, Any], *, now=None, technical_registry=None
) -> tuple[list[dict], dict]:
    """Keep every research row, but assign TOP ranks only to complete, CIO-reviewed candidates.

    The original score/rank/stance remain explicit diagnostic fields. No position verdict is calculated here.
    """
    from lib.data_broker import opportunity as op
    from scripts.lib.market_risk.cio_context import evaluated_tier
    from lib.data_broker.watch_prospects import STANCE_FAMILY

    now = _instant(now) if now is not None else datetime.now(timezone.utc)
    floor = _number(((cfg.get("presets") or {}).get("top5") or {}).get("min_coverage"))
    gate = cfg.get("market_risk_gate") or {}
    risk = context.get("market_risk") or {}
    tier = evaluated_tier(risk, max_age_hours=gate.get("max_stale_hours"), now=now)
    risk_at = _instant(risk.get("as_of"))
    max_age = _number(gate.get("max_stale_hours"))
    if (
        now is None
        or risk_at is None
        or risk_at > now
        or (max_age is not None and (now - risk_at).total_seconds() > max_age * 3600)
    ):
        tier = None
    held_tiers = set(gate.get("hold_tiers") or [])
    entry_types = set(gate.get("entry_types") or [])
    out = []
    for assessment in items:
        row = dict(assessment)
        symbol = row.get("symbol")
        tech = (context.get("technical") or {}).get(symbol) or {}
        tech = tech if isinstance(tech, dict) else {}
        technical_receipt = _technical_receipt(tech, now, registry=technical_registry)
        thesis = (context.get("theses") or {}).get(symbol)
        thesis = thesis if isinstance(thesis, dict) else {}
        missing = []
        coverage = _number(row.get("coverage"))
        if floor is None or coverage is None or not 0 <= coverage <= 1 or coverage < floor:
            missing.append("factor coverage below the top-list minimum")
        if not technical_receipt["verified"]:
            missing.extend(
                f"{key}: {receipt['reason']}"
                for key, receipt in technical_receipt["inputs"].items()
                if not receipt["verified"]
            )
        technical_state = (context.get("technical_state") or {}).get(symbol, "read")
        if technical_state == "not_checked":
            missing.append("technical coverage not yet verified")
        elif (context.get("errors") or {}).get("technical"):
            missing.append(context["errors"]["technical"])
        else:
            for key, label in _TECHNICAL:
                value = tech.get(key)
                if key == "macd_signal":
                    present = isinstance(value, str) and value.strip().upper() not in (
                        "",
                        "UNKNOWN",
                        "N/A",
                        "NONE",
                        "UNAVAILABLE",
                        "NAN",
                        "NULL",
                        "—",
                        "-",
                    )
                else:
                    number = _number(value)
                    present = number is not None and (0 <= number <= 100 if key == "rsi" else number > 0)
                if not present:
                    missing.append(label)
        summary = thesis.get("summary")
        stance = thesis.get("stance")
        as_of = (
            thesis.get("published_ts") or thesis.get("updated_ts") or thesis.get("created_ts") or thesis.get("as_of")
        )
        at = _instant(as_of)
        has_thesis = isinstance(summary, str) and bool(summary.strip()) and thesis.get("status") == "active"
        has_stance = isinstance(stance, str) and stance.strip().upper() not in (
            "",
            "UNKNOWN",
            "N/A",
            "NONE",
            "UNVERIFIED",
            "UNAVAILABLE",
            "NULL",
            "NAN",
            "—",
            "-",
        )
        if not has_thesis:
            missing.append((context.get("errors") or {}).get("theses") or "CIO research thesis")
        if not has_stance:
            missing.append("CIO stance")
        if now is None or at is None or at > now:
            missing.append("dated CIO review")
        reviewed = has_thesis and has_stance and now is not None and at is not None and at <= now
        # Reuse the existing stance vocabulary only to recognize additional long exposure. The original CIO
        # stance is returned unchanged; this does not calculate or override a position verdict.
        entry_stance = STANCE_FAMILY.get(str(stance or "").strip().upper()) == "positive"
        entry = row.get("type") in entry_types or row.get("curator_type") in entry_types or entry_stance
        risk_held = entry and (tier is None or tier in held_tiers)
        score = _number(row.get("conviction"))
        if score is None or not 0 <= score <= 100:
            missing.append("research score")
        eligible = not missing and not risk_held
        reason = "CIO-reviewed with technical coverage"
        if missing:
            reason = "Unreviewed for the top list — data missing: " + "; ".join(missing)
        if risk_held:
            hold = f"new long ideas held — market risk {tier or 'unverified'}"
            reason = f"{reason}; {hold}" if missing else hold.capitalize()
        row.update(
            {
                "research_rank": row.get("rank"),
                "automated_stance": row.get("curator_stance", row.get("stance")),
                "rank": None,
                # Keep curator stance for published filters/facets; CIO stance lives in the receipt below.
                "cio_review": {
                    "reviewed": reviewed,
                    "stance": stance if reviewed else None,
                    "as_of": at.isoformat().replace("+00:00", "Z") if reviewed else None,
                    "thesis_version": thesis.get("thesis_version"),
                    "source": "cio_theses_projection.current",
                },
                "top_eligibility": {
                    "eligible": eligible,
                    "missing": missing,
                    "reason": reason,
                    "technical": technical_receipt,
                    "coverage_floor": floor,
                    "entry_held": risk_held,
                },
            }
        )
        out.append(row)
    qualified = op.sort_items([r for r in out if r["top_eligibility"]["eligible"]], "conviction")
    for rank, row in enumerate(qualified, 1):
        row["rank"] = rank
    notice = (
        f"Market risk {tier}: new long ideas are held."
        if tier in held_tiers
        else (
            "Market risk could not be confirmed: new long ideas are held." if tier is None else f"Market risk {tier}."
        )
    )
    return out, {
        "market_risk_tier": tier,
        "notice": notice,
        "eligible": len(qualified),
        "research_only": len(out) - len(qualified),
        "coverage_floor": floor,
    }


def technical_candidates(items: list[dict], cfg: dict, query: dict) -> list[str]:
    from lib.data_broker import opportunity as op

    floor = _number(((cfg.get("presets") or {}).get("top5") or {}).get("min_coverage"))
    # Watch overlays ownership/type before filtering. Only immutable score thresholds are safe before that join.
    safe_query = {k: v for k, v in query.items() if k in ("min_conviction", "min_rr", "min_upside", "min_coverage")}
    out = []
    for row in items:
        coverage = _number(row.get("coverage"))
        if floor is not None and coverage is not None and floor <= coverage <= 1 and op.passes(row, safe_query):
            out.append(row["symbol"])
    return out


def sort_qualified(items: list[dict], sort: str) -> list[dict]:
    from lib.data_broker import opportunity as op

    return sorted(op.sort_items(items, sort), key=lambda row: not row["top_eligibility"]["eligible"])
