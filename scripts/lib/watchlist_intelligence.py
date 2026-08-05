"""Watchlist Intelligence Board — read-only aggregation (zero provider calls).

Truthfulness:
  COMPLETE LLM reviews require full immutable provenance.
  Incomplete legacy rows are demoted to NOT RUN (never fabricate model names).
  Street rating is primary research label; Trade AI state is independent.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME = PROJECT_ROOT / "data" / "runtime"
ROCKVILLE_REVIEWS = RUNTIME / "rockville" / "reviews"
INTEL_ARTIFACTS = RUNTIME / "watchlist_intelligence" / "artifacts"
ENRICH_CACHE = PROJECT_ROOT / "data" / "state" / "ticker_enrichment_cache.json"
HOLDINGS = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"

DEFAULT_PRIORITY = ["CECO", "FTH", "AXTI", "NUAI", "SWBI", "PFLT"]

# Provenance fields required for COMPLETE (design gate)
_REQUIRED_COMPLETE = (
    "agent_id",
    "process_id",
    "provider",
    "model",
    "requested_policy",
    "executed_policy",
    "artifact_id",
    "artifact_hash",
    "input_hash",
    "started_at",
    "completed_at",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _json_clean(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _json_clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_clean(x) for x in v]
    if hasattr(v, "__float__") and not isinstance(v, bool):
        try:
            return float(v)
        except Exception:
            return str(v)
    return v


def not_run_review(
    agent_id: str,
    *,
    reason_code: str = "NOT_SCHEDULED",
    next_scheduled: str | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    """Typed NOT RUN — never invent provider/model."""
    out = {
        "agent_id": agent_id,
        "status": "NOT_RUN",
        "reason_code": reason_code,
        "process_id": None,
        "provider": None,
        "model": None,
        "requested_policy": "NO_CALL",
        "executed_policy": "NO_CALL",
        "fallback_used": False,
        "started_at": None,
        "completed_at": None,
        "input_snapshot_id": None,
        "input_hash": None,
        "artifact_id": None,
        "artifact_hash": None,
        "request_id_present": False,
        "provider_request_id": None,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "estimated_cost_usd": 0.0,
        "reconciliation_status": None,
        "verdict": None,
        "summary": None,
        "thesis": None,
        "counter_thesis": None,
        "catalysts": [],
        "risks": [],
        "evidence_gaps": [],
        "what_changes_the_decision": None,
        "evidence_references": [],
        "next_scheduled_review": next_scheduled,
        "display": {
            "label": f"{agent_id.upper()} REVIEW: NOT RUN",
            "provider": "NONE",
            "model": "NONE",
            "policy": "NO_CALL",
            "cost": "$0",
            "reason": reason_code,
        },
    }
    if extra:
        out.update(extra)
    return out


def validate_complete_review(raw: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (ok, missing_fields). Provider/model must be non-null non-empty."""
    missing: list[str] = []
    for k in _REQUIRED_COMPLETE:
        v = raw.get(k)
        if v is None or v == "" or (isinstance(v, str) and v.upper() in ("NONE", "NULL", "N/A")):
            missing.append(k)
    if raw.get("fallback_used") is None:
        missing.append("fallback_used")
    if raw.get("estimated_cost_usd") is None and raw.get("prompt_tokens") is None:
        missing.append("usage")
    # request reference: either request_id or explicit request_id_present with ref field
    has_req = bool(raw.get("provider_request_id") or raw.get("request_id") or raw.get("request_reference"))
    if not has_req and raw.get("request_id_present") is not True:
        missing.append("request_reference")
    return (len(missing) == 0, missing)


def complete_review_from_validated(raw: dict[str, Any]) -> dict[str, Any]:
    """Build COMPLETE summary only after validate_complete_review passes."""
    return {
        "agent_id": raw.get("agent_id"),
        "status": "COMPLETE",
        "reason_code": None,
        "process_id": raw.get("process_id"),
        "provider": raw.get("provider"),
        "model": raw.get("model"),
        "requested_policy": raw.get("requested_policy"),
        "executed_policy": raw.get("executed_policy"),
        "fallback_used": bool(raw.get("fallback_used")),
        "started_at": raw.get("started_at"),
        "completed_at": raw.get("completed_at"),
        "input_snapshot_id": raw.get("input_snapshot_id"),
        "input_hash": raw.get("input_hash"),
        "artifact_id": raw.get("artifact_id"),
        "artifact_hash": raw.get("artifact_hash"),
        "request_id_present": True,
        "provider_request_id": raw.get("provider_request_id") or raw.get("request_id") or raw.get("request_reference"),
        "prompt_tokens": int(raw.get("prompt_tokens") or 0),
        "completion_tokens": int(raw.get("completion_tokens") or 0),
        "estimated_cost_usd": float(raw.get("estimated_cost_usd") or 0.0),
        "reconciliation_status": raw.get("reconciliation_status") or "ADVISORY_COMPLETE",
        "verdict": raw.get("verdict"),
        "summary": raw.get("summary"),
        "thesis": raw.get("thesis"),
        "counter_thesis": raw.get("counter_thesis"),
        "catalysts": raw.get("catalysts") or [],
        "risks": raw.get("risks") or [],
        "evidence_gaps": raw.get("evidence_gaps") or [],
        "what_changes_the_decision": raw.get("what_changes_the_decision"),
        "evidence_references": raw.get("evidence_references") or [],
        "next_scheduled_review": raw.get("next_scheduled_review"),
        "display": {
            "label": f"{str(raw.get('agent_id') or '').upper()} REVIEW: COMPLETE",
            "provider": str(raw.get("provider") or "").upper(),
            "model": str(raw.get("model") or ""),
            "policy": str(raw.get("executed_policy") or ""),
            "cost": f"${float(raw.get('estimated_cost_usd') or 0):.5f}",
            "reason": None,
        },
    }


def map_street_rating(rec_key: str | None, rec_mean: float | None = None) -> dict[str, Any]:
    """Yahoo recommendation_key → primary Street label."""
    key = (rec_key or "").strip().lower().replace(" ", "_")
    label = "NOT RATED"
    tone = "hold"
    if key in ("strong_buy", "strongbuy"):
        label, tone = "STRONG BUY", "strong"
    elif key == "buy":
        label, tone = "BUY", "buy"
    elif key in ("hold", "neutral"):
        label, tone = "HOLD", "hold"
    elif key in ("sell", "underperform"):
        label, tone = "SELL", "hold"
    elif key in ("strong_sell", "strongsell"):
        label, tone = "SELL", "hold"
    elif key in ("none", "", "n/a"):
        # fallback to mean if available (1=strong buy … 5=strong sell)
        if rec_mean is not None:
            m = float(rec_mean)
            if m <= 1.5:
                label, tone = "STRONG BUY", "strong"
            elif m <= 2.5:
                label, tone = "BUY", "buy"
            elif m <= 3.5:
                label, tone = "HOLD", "hold"
            else:
                label, tone = "SELL", "hold"
    return {
        "street_rating": label,
        "street_tone": tone,
        "recommendation_key": rec_key,
        "recommendation_mean": rec_mean,
    }


def _canonical_company_name(description: str | None, symbol: str) -> str:
    from lib.rockville.live_projection import _canonical_company_name as _ccn
    return _ccn(description or "", symbol)


def _company_one_liner(description: str | None, max_len: int = 220) -> str | None:
    """First sentence of profile description — avoid splitting on Corp./Inc./Ltd."""
    if not description:
        return None
    raw = description.strip()
    # Protect common abbreviations so "Corp. provides" is not truncated at Corp.
    protected = raw
    for abbr in (
        "Corp.", "Inc.", "Ltd.", "LLC.", "L.P.", "plc.", "PLC.",
        "Co.", "S.A.", "N.V.", "A.G.", "B.V.",
    ):
        protected = protected.replace(abbr, abbr.replace(".", "\u0000"))
    parts = re.split(r"(?<=[.!?])\s+", protected, maxsplit=1)
    text = parts[0].replace("\u0000", ".").strip()
    if len(text) < 40 and len(raw) > len(text):
        # Abbreviation-only first token — use a longer slice of the description
        text = re.sub(r"\s+", " ", raw)[:max_len].strip()
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text or None


def _held_set() -> set[str]:
    out: set[str] = set()
    try:
        if not HOLDINGS.exists():
            return out
        data = json.loads(HOLDINGS.read_text(encoding="utf-8"))
        for h in data.get("holdings") or []:
            if h.get("is_cash"):
                continue
            s = str(h.get("symbol") or "").upper()
            if not s:
                continue
            if float(h.get("quantity") or h.get("shares") or 0) > 0 or float(h.get("market_value") or 0) > 0:
                out.add(s)
    except Exception:
        pass
    return out


def _enrichment_map(symbols: list[str]) -> dict[str, dict]:
    try:
        raw = json.loads(ENRICH_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    want = {s.upper() for s in symbols}
    out: dict[str, dict] = {}
    for k, v in raw.items():
        ku = str(k).upper()
        if ku in want and isinstance(v, dict):
            out[ku] = v
    return out


def _load_rockville_review(symbol: str) -> dict | None:
    path = ROCKVILLE_REVIEWS / f"{symbol.upper()}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _try_promote_artifact(raw: dict[str, Any], *, agent_id: str) -> dict[str, Any]:
    """Promote raw artifact dict to COMPLETE or demote to NOT RUN.

    operator_approved=true is never sufficient — broker authorization gate required.
    """
    candidate = dict(raw)
    candidate.setdefault("agent_id", agent_id)
    try:
        from lib.data_broker.watch_domains import authorize_review_artifact
        auth_ok, auth_reason = authorize_review_artifact(candidate)
        if not auth_ok:
            return not_run_review(
                agent_id,
                reason_code=auth_reason or "UNVERIFIED_OPERATOR_AUTHORIZATION",
                extra={"legacy_present": bool(raw), "operator_approved_insufficient": True},
            )
    except Exception:
        return not_run_review(agent_id, reason_code="UNVERIFIED_OPERATOR_AUTHORIZATION")
    ok, missing = validate_complete_review(candidate)
    if ok:
        return complete_review_from_validated(candidate)
    return not_run_review(
        agent_id,
        reason_code="LEGACY_INCOMPLETE_PROVENANCE",
        extra={"provenance_missing": missing, "legacy_present": True},
    )


def _load_intelligence_artifacts(symbol: str) -> dict[str, dict[str, Any]]:
    """Load artifacts only via broker authorization gate (quarantine excluded)."""
    try:
        from lib.data_broker.watch_domains import load_review_artifacts
        return load_review_artifacts(symbol)
    except Exception:
        return {}


def _reviews_for_symbol(symbol: str) -> list[dict[str, Any]]:
    """Assemble per-agent review objects — COMPLETE only with full provenance."""
    sym = symbol.upper()
    agents = ("cio", "maria", "sentinel", "steph", "risk", "grok", "chatgpt")
    by_agent: dict[str, dict[str, Any]] = {
        a: not_run_review(a, reason_code="NOT_SCHEDULED") for a in agents
    }

    # Governed intelligence proof artifacts (preferred — full provenance)
    for agent, raw in _load_intelligence_artifacts(sym).items():
        if agent not in by_agent:
            continue
        promoted = _try_promote_artifact(raw, agent_id=agent)
        if promoted.get("status") == "COMPLETE":
            by_agent[agent] = promoted

    # Rockville reflective review file (must have full provenance to COMPLETE)
    rv = _load_rockville_review(sym)
    if rv:
        prov = rv.get("provenance") or rv
        candidate = {
            "agent_id": rv.get("agent_id") or "maria",
            "process_id": prov.get("process_id") or rv.get("process_id"),
            "provider": prov.get("provider"),
            "model": prov.get("model"),
            "requested_policy": prov.get("requested_policy") or prov.get("policy"),
            "executed_policy": prov.get("executed_policy") or prov.get("policy"),
            "fallback_used": prov.get("fallback_used", False),
            "provider_request_id": prov.get("provider_request_id") or prov.get("request_id"),
            "request_id_present": bool(prov.get("provider_request_id") or prov.get("request_id")),
            "started_at": prov.get("started_at") or rv.get("started_at"),
            "completed_at": prov.get("completed_at") or prov.get("generated_at") or rv.get("generated_at"),
            "input_snapshot_id": prov.get("input_snapshot_id") or rv.get("input_snapshot_id"),
            "input_hash": prov.get("input_hash") or rv.get("input_hash"),
            "artifact_id": prov.get("artifact_id") or rv.get("artifact_id") or rv.get("id"),
            "artifact_hash": prov.get("artifact_hash") or rv.get("artifact_hash"),
            "prompt_tokens": prov.get("prompt_tokens") or 0,
            "completion_tokens": prov.get("completion_tokens") or 0,
            "estimated_cost_usd": prov.get("estimated_cost_usd") or 0.0,
            "reconciliation_status": prov.get("reconciliation_status") or rv.get("reconciliation_status"),
            "verdict": rv.get("verdict") or rv.get("decision_summary"),
            "summary": rv.get("decision_summary") or rv.get("summary"),
            "thesis": rv.get("bull_case") or rv.get("thesis"),
            "counter_thesis": rv.get("counter_thesis"),
            "risks": rv.get("principal_risk") and [rv.get("principal_risk")] or (rv.get("risks") or []),
            "evidence_gaps": rv.get("evidence_gaps") or [],
            "what_changes_the_decision": rv.get("what_would_change_view") or rv.get("what_changes_the_decision"),
        }
        agent = str(candidate["agent_id"]).lower()
        if agent not in by_agent:
            agent = "maria"
        by_agent[agent] = _try_promote_artifact(candidate, agent_id=agent)

    # Legacy DB rows: never COMPLETE without full provenance — surface typed NOT RUN
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT ON (lower(agent))
                   agent, model_used, summary, recommendation, full_narrative,
                   prompt_hash, started_at, completed_at, status, id
              FROM watchlist_agent_results
             WHERE upper(symbol)=%s
               AND status IN ('complete','completed','done','success','ok')
             ORDER BY lower(agent), completed_at DESC NULLS LAST
            """,
            (sym,),
        )
        for row in cur.fetchall() or []:
            if hasattr(row, "keys"):
                agent = str(row.get("agent") or "").lower()
                model = row.get("model_used")
                summary = row.get("summary")
                prompt_hash = row.get("prompt_hash")
                completed = row.get("completed_at")
                rid = row.get("id")
            else:
                agent = str(row[0] or "").lower()
                model = row[1]
                summary = row[2]
                prompt_hash = row[5]
                completed = row[7]
                rid = row[9]
            if agent not in by_agent:
                # map common aliases
                if agent in ("research", "research_agent"):
                    agent = "maria"
                elif agent in ("critic",):
                    agent = "sentinel"
                else:
                    continue
            if by_agent[agent].get("status") == "COMPLETE":
                continue
            # Incomplete legacy — NOT RUN with typed reason (never claim COMPLETE)
            by_agent[agent] = not_run_review(
                agent,
                reason_code="LEGACY_INCOMPLETE_PROVENANCE",
                extra={
                    "legacy_present": True,
                    "legacy_model_seen": str(model) if model else None,
                    "legacy_summary_snip": (str(summary)[:160] if summary else None),
                    "legacy_row_id": rid,
                    "legacy_completed_at": completed.isoformat() if hasattr(completed, "isoformat") else completed,
                    "legacy_prompt_hash": prompt_hash,
                    "note": "Legacy row lacks process_id/provider_request_id/artifact_hash — not shown as COMPLETE",
                },
            )
    except Exception:
        pass

    # CIO synthesis table: incomplete provenance → NOT RUN
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT recommendation, synthesis_narrative, model_used, updated_at,
                   dual_consensus_json, decision_safety
              FROM watchlist_final_synthesis
             WHERE upper(symbol)=%s
             LIMIT 1
            """,
            (sym,),
        )
        row = cur.fetchone()
        if row and by_agent["cio"].get("status") != "COMPLETE":
            if hasattr(row, "keys"):
                rec = row.get("recommendation")
                narrative = row.get("synthesis_narrative")
                model = row.get("model_used")
                updated = row.get("updated_at")
            else:
                rec, narrative, model, updated = row[0], row[1], row[2], row[3]
            by_agent["cio"] = not_run_review(
                "cio",
                reason_code="LEGACY_INCOMPLETE_PROVENANCE",
                extra={
                    "legacy_present": True,
                    "legacy_recommendation": rec,
                    "legacy_summary_snip": (str(narrative)[:160] if narrative else None),
                    "legacy_model_seen": str(model) if model else None,
                    "legacy_updated_at": updated.isoformat() if hasattr(updated, "isoformat") else updated,
                    "note": "watchlist_final_synthesis lacks immutable request/artifact provenance",
                },
            )
    except Exception:
        pass

    # Rockville CIO no-call / NMC digest is watchlist-level, not per-symbol COMPLETE
    try:
        from lib.rockville.cio_scheduler import load_latest_artifact
        art = load_latest_artifact()
        if art and by_agent["cio"].get("status") != "COMPLETE":
            if art.get("provider_call_occurred") is False or art.get("status") in (
                "NO_MATERIAL_CHANGE", "NONE", "NO_CALL",
            ):
                by_agent["cio"] = not_run_review(
                    "cio",
                    reason_code="NO_MATERIAL_CHANGE_NO_CALL",
                    extra={
                        "digest_status": art.get("status"),
                        "digest_id": art.get("artifact_id") or art.get("id"),
                    },
                )
    except Exception:
        pass

    return [by_agent[a] for a in agents]


def _street_batch(symbols: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    # Yahoo history first
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT ON (symbol)
                   symbol, recommendation_key, recommendation_mean,
                   number_of_analyst_opinions, target_mean_price,
                   target_high_price, target_low_price, target_median_price,
                   snapshot_date, created_at
              FROM yahoo_analyst_targets_history
             WHERE symbol = ANY(%s)
             ORDER BY symbol, snapshot_date DESC NULLS LAST, created_at DESC NULLS LAST
            """,
            (symbols,),
        )
        for row in cur.fetchall() or []:
            if hasattr(row, "keys"):
                sym = str(row["symbol"]).upper()
                key = row.get("recommendation_key")
                mean = _safe_float(row.get("recommendation_mean"))
                mapped = map_street_rating(key, mean)
                tgt = _safe_float(row.get("target_mean_price") or row.get("target_median_price"))
                out[sym] = {
                    **mapped,
                    "analyst_count": row.get("number_of_analyst_opinions"),
                    "target_mean": tgt,
                    "target_high": _safe_float(row.get("target_high_price")),
                    "target_low": _safe_float(row.get("target_low_price")),
                    "as_of": (row.get("snapshot_date") or row.get("created_at")),
                    "source": "yahoo_analyst_targets_history",
                }
            else:
                sym = str(row[0]).upper()
                mapped = map_street_rating(row[1], _safe_float(row[2]))
                out[sym] = {
                    **mapped,
                    "analyst_count": row[3],
                    "target_mean": _safe_float(row[4]),
                    "target_high": _safe_float(row[5]),
                    "target_low": _safe_float(row[6]),
                    "as_of": row[8] or row[9],
                    "source": "yahoo_analyst_targets_history",
                }
    except Exception:
        pass

    # Fill gaps from pills
    try:
        from lib.data_broker.analyst_rollup import get_analyst_rollup
        pills = get_analyst_rollup(symbols)
        for sym, p in pills.items():
            if sym in out and out[sym].get("street_rating") != "NOT RATED":
                continue
            key = p.get("rec_key") or p.get("consensus")
            mapped = map_street_rating(str(key) if key else None)
            if mapped["street_rating"] == "NOT RATED" and p.get("consensus"):
                # consensus may already be "Strong Buy"
                c = str(p["consensus"]).upper().replace("-", " ")
                if "STRONG BUY" in c:
                    mapped = {"street_rating": "STRONG BUY", "street_tone": "strong", "recommendation_key": key, "recommendation_mean": None}
                elif c == "BUY":
                    mapped = {"street_rating": "BUY", "street_tone": "buy", "recommendation_key": key, "recommendation_mean": None}
                elif c == "HOLD":
                    mapped = {"street_rating": "HOLD", "street_tone": "hold", "recommendation_key": key, "recommendation_mean": None}
                elif "SELL" in c:
                    mapped = {"street_rating": "SELL", "street_tone": "hold", "recommendation_key": key, "recommendation_mean": None}
            out.setdefault(sym, {
                **mapped,
                "analyst_count": p.get("analyst_count"),
                "target_mean": _safe_float(p.get("mean_target")),
                "target_high": None,
                "target_low": None,
                "as_of": p.get("as_of"),
                "source": "pro_analyst_pills",
            })
    except Exception:
        pass

    for s in symbols:
        out.setdefault(s.upper(), {
            "street_rating": "NOT RATED",
            "street_tone": "hold",
            "recommendation_key": None,
            "recommendation_mean": None,
            "analyst_count": None,
            "target_mean": None,
            "target_high": None,
            "target_low": None,
            "as_of": None,
            "source": None,
        })
    return out


def _profiles_batch(symbols: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT symbol, description_1s, sector, industry, instrument_type,
                   ytd_return_pct, dividend_yield_pct, next_earnings_date, updated_at
              FROM symbol_profiles
             WHERE upper(symbol) = ANY(%s)
            """,
            ([s.upper() for s in symbols],),
        )
        for row in cur.fetchall() or []:
            if hasattr(row, "keys"):
                sym = str(row["symbol"]).upper()
                desc = row.get("description_1s")
                out[sym] = {
                    "company": _canonical_company_name(desc, sym),
                    "company_summary": _company_one_liner(desc),
                    "description": desc,
                    "sector": row.get("sector"),
                    "industry": row.get("industry"),
                    "instrument_type": row.get("instrument_type") or "stock",
                    "ytd_return_pct": _safe_float(row.get("ytd_return_pct")),
                    "dividend_yield_pct": _safe_float(row.get("dividend_yield_pct")),
                    "next_earnings_date": row.get("next_earnings_date"),
                    "profile_updated_at": row.get("updated_at"),
                }
            else:
                sym = str(row[0]).upper()
                desc = row[1]
                out[sym] = {
                    "company": _canonical_company_name(desc, sym),
                    "company_summary": _company_one_liner(desc),
                    "description": desc,
                    "sector": row[2],
                    "industry": row[3],
                    "instrument_type": row[4] or "stock",
                    "ytd_return_pct": _safe_float(row[5]),
                    "dividend_yield_pct": _safe_float(row[6]),
                    "next_earnings_date": row[7],
                    "profile_updated_at": row[8],
                }
    except Exception:
        pass
    return out


def _catalysts_batch(symbols: list[str]) -> dict[str, list]:
    out: dict[str, list] = {s.upper(): [] for s in symbols}
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT upper(symbol) AS symbol, catalyst_type, headline, impact_score, severity,
                   COALESCE(published_at, created_at) AS ts, source_url
              FROM catalyst_events
             WHERE upper(symbol) = ANY(%s)
               AND catalyst_type <> 'other'
               AND COALESCE(published_at, created_at) > now() - interval '60 days'
             ORDER BY COALESCE(published_at, created_at) DESC
             LIMIT 200
            """,
            ([s.upper() for s in symbols],),
        )
        for row in cur.fetchall() or []:
            if hasattr(row, "keys"):
                sym = row["symbol"]
                item = {
                    "type": row.get("catalyst_type"),
                    "headline": row.get("headline"),
                    "impact": row.get("impact_score"),
                    "severity": row.get("severity"),
                    "at": row.get("ts"),
                    "url": row.get("source_url"),
                }
            else:
                sym = row[0]
                item = {
                    "type": row[1], "headline": row[2], "impact": row[3],
                    "severity": row[4], "at": row[5], "url": row[6],
                }
            if len(out.get(sym, [])) < 5:
                out.setdefault(sym, []).append(item)
    except Exception:
        pass
    return out


def _tech_batch(symbols: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT ON (upper(wi.symbol))
                   upper(wi.symbol) AS symbol,
                   wi.rsi, wi.rvol, wi.trend, wi.setup_advisory, wi.float_m,
                   sc.support, sc.resistance, sc.ideal_entry, sc.stop_loss,
                   sc.target_price, sc.risk_reward, sc.technical_summary
              FROM watchlist_items wi
              LEFT JOIN LATERAL (
                    SELECT support, resistance, ideal_entry, stop_loss, target_price,
                           risk_reward, technical_summary
                      FROM watchlist_strategy_cards t WHERE t.symbol = wi.symbol LIMIT 1
              ) sc ON true
             WHERE upper(wi.symbol) = ANY(%s)
             ORDER BY upper(wi.symbol), wi.updated_at DESC NULLS LAST
            """,
            ([s.upper() for s in symbols],),
        )
        for row in cur.fetchall() or []:
            if hasattr(row, "keys"):
                sym = row["symbol"]
                out[sym] = {k: row.get(k) for k in (
                    "rsi", "rvol", "trend", "setup_advisory", "float_m",
                    "support", "resistance", "ideal_entry", "stop_loss",
                    "target_price", "risk_reward", "technical_summary",
                )}
            else:
                keys = (
                    "symbol", "rsi", "rvol", "trend", "setup_advisory", "float_m",
                    "support", "resistance", "ideal_entry", "stop_loss",
                    "target_price", "risk_reward", "technical_summary",
                )
                d = dict(zip(keys, row))
                sym = d.pop("symbol")
                out[sym] = d
    except Exception:
        pass
    return out


def _decision_for(symbol: str) -> dict[str, Any]:
    """Trade AI deterministic projection — no provider calls."""
    try:
        from lib.rockville.live_projection import build_live_symbol
        card = build_live_symbol(symbol)
        if not card.get("ok"):
            return {
                "primary_state": "DATA_UNAVAILABLE",
                "proposal_allowed": False,
                "current_mechanics_visible": False,
                "current_mechanics": None,
                "operator_meaning": "Symbol decision packet unavailable",
                "allowed_action_now": "REFRESH INPUTS",
            }
        dec = card.get("decision") or {}
        return {
            "primary_state": dec.get("primary_state"),
            "proposal_allowed": bool(dec.get("proposal_allowed")),
            "current_mechanics_visible": bool(dec.get("current_mechanics_visible")),
            "current_mechanics": dec.get("current_mechanics") if dec.get("current_mechanics_visible") else None,
            "wait_contract": dec.get("wait_contract"),
            "operator_meaning": dec.get("operator_meaning"),
            "allowed_action_now": dec.get("allowed_action_now"),
            "blockers": dec.get("blockers") or [],
            "next_deterministic_review_condition": dec.get("next_deterministic_review_condition"),
            "verification_stages": card.get("verification_stages") or dec.get("verification_stages"),
            "held": bool(card.get("held")),
            "packet_id": card.get("packet_id"),
            "material_fingerprint": card.get("material_fingerprint"),
        }
    except Exception as e:
        return {
            "primary_state": "DATA_UNAVAILABLE",
            "proposal_allowed": False,
            "current_mechanics_visible": False,
            "current_mechanics": None,
            "operator_meaning": f"Decision projection error: {type(e).__name__}",
            "allowed_action_now": "VIEW SOURCE HEALTH",
        }


def _relative_performance(sym: str, enrich: dict, profile: dict) -> dict[str, Any]:
    """Relative performance from enrichment + profile — honest nulls for missing peers."""
    periods = {
        "1D": _safe_float(enrich.get("change_pct") or enrich.get("change_from_open_pct")),
        "1W": _safe_float(enrich.get("perf_week_pct")),
        "1M": _safe_float(enrich.get("perf_month_pct")),
        "3M": _safe_float(enrich.get("perf_quarter_pct")),
        "6M": _safe_float(enrich.get("perf_halfyr_pct")),
        "YTD": _safe_float(enrich.get("perf_ytd_pct") if enrich.get("perf_ytd_pct") is not None else profile.get("ytd_return_pct")),
        "1Y": _safe_float(enrich.get("perf_year_pct")),
    }
    missing = [k for k, v in periods.items() if v is None]
    # Peer/industry deltas not yet joined — explicit gap
    return {
        "periods": periods,
        "versus_industry": None,
        "versus_sector": None,
        "versus_spy": None,
        "summary": _perf_summary(periods),
        "missing": missing + (["versus_industry", "versus_sector", "versus_spy"] if True else []),
        "note": "Industry/sector/SPY relative deltas require peer index join — null until sourced",
    }


def _perf_summary(periods: dict) -> str:
    parts = []
    for k in ("1D", "1M", "3M", "1Y"):
        v = periods.get(k)
        if v is not None:
            parts.append(f"{v:+.1f}% {k}")
    return " · ".join(parts) if parts else "Performance data incomplete"


def _fundamentals_block(enrich: dict, instrument_type: str | None) -> dict[str, Any]:
    itype = (instrument_type or "stock").lower()
    if itype in ("etf", "fund", "bdc", "cef"):
        return {
            "instrument_type": itype,
            "applicability": "fund_fields",
            "fields": {
                "dividend_yield_pct": _safe_float(enrich.get("dividend_yield") or enrich.get("dividend_yield_pct")),
                "expense_ratio": _safe_float(enrich.get("expense_ratio")),
                "ytd_return_pct": _safe_float(enrich.get("perf_ytd_pct")),
            },
            "versus_industry": None,
            "note": "Equity P/E and margin table not applicable for this instrument",
        }
    fields = {
        "pe": _safe_float(enrich.get("pe")),
        "forward_pe": _safe_float(enrich.get("forward_pe")),
        "peg": _safe_float(enrich.get("peg")),
        "gross_margin_pct": _safe_float(enrich.get("gross_margin_pct")),
        "operating_margin_pct": _safe_float(enrich.get("oper_margin_pct") or enrich.get("operating_margin_pct")),
        "profit_margin_pct": _safe_float(enrich.get("profit_margin_pct")),
        "rsi": _safe_float(enrich.get("rsi")),
        "atr": _safe_float(enrich.get("atr")),
    }
    return {
        "instrument_type": itype or "stock",
        "applicability": "equity_fields",
        "fields": fields,
        "versus_industry": None,
        "note": "Industry medians not joined in this shadow release — company fields only",
    }


def _compose_card(
    symbol: str,
    *,
    street: dict,
    profile: dict,
    quote: dict,
    tech: dict,
    catalysts: list,
    enrich: dict,
    decision: dict,
    reviews: list[dict],
    held: bool,
) -> dict[str, Any]:
    sym = symbol.upper()
    last = quote.get("last")
    tgt = street.get("target_mean")
    upside = None
    if last and tgt and last > 0:
        upside = round((float(tgt) - float(last)) / float(last) * 100, 2)

    by_agent = {r["agent_id"]: r for r in reviews}
    cio = by_agent.get("cio") or not_run_review("cio")
    maria = by_agent.get("maria") or not_run_review("maria")
    sentinel = by_agent.get("sentinel") or not_run_review("sentinel")

    cat0 = catalysts[0] if catalysts else None
    catalyst_summary = (cat0 or {}).get("headline") if cat0 else None
    cat_vs_ind = None
    if catalyst_summary:
        cat_vs_ind = f"Company catalyst present; industry relative score not joined (shadow)"
    elif profile.get("next_earnings_date"):
        catalyst_summary = f"Next earnings: {profile.get('next_earnings_date')}"
        cat_vs_ind = "Earnings calendar only — no recent catalyst_events row"

    rel = _relative_performance(sym, enrich, profile)
    state = decision.get("primary_state") or "DATA_UNAVAILABLE"
    proposal = bool(decision.get("proposal_allowed"))
    mech_vis = bool(decision.get("current_mechanics_visible")) and state == "READY"

    # Operator next action from deterministic decision
    next_action = decision.get("allowed_action_now") or "VIEW EVIDENCE"
    thesis_line = decision.get("operator_meaning")
    primary_risk = None
    blockers = decision.get("blockers") or []
    if blockers:
        primary_risk = blockers[0].get("message") if isinstance(blockers[0], dict) else str(blockers[0])

    cio_summary_text = None
    if cio.get("status") == "COMPLETE":
        cio_summary_text = cio.get("summary") or cio.get("verdict")
    elif cio.get("legacy_summary_snip"):
        # Do not present as COMPLETE CIO; label as incomplete legacy note off-path
        cio_summary_text = None

    maria_summary_text = None
    if maria.get("status") == "COMPLETE":
        maria_summary_text = maria.get("summary") or maria.get("verdict")

    return _json_clean({
        "symbol": sym,
        "company": profile.get("company") or sym,
        "company_summary": profile.get("company_summary"),
        "sector": profile.get("sector") or enrich.get("sector"),
        "industry": profile.get("industry") or enrich.get("industry"),
        "instrument_type": profile.get("instrument_type") or "stock",
        # Street primary
        "street_rating": street.get("street_rating") or "NOT RATED",
        "street_tone": street.get("street_tone") or "hold",
        "street_consensus": {
            "rating": street.get("street_rating"),
            "analyst_count": street.get("analyst_count"),
            "target_mean": street.get("target_mean"),
            "target_high": street.get("target_high"),
            "target_low": street.get("target_low"),
            "implied_upside_pct": upside,
            "as_of": street.get("as_of"),
            "source": street.get("source"),
            "recommendation_key": street.get("recommendation_key"),
            "recommendation_mean": street.get("recommendation_mean"),
        },
        # Trade AI independent
        "trade_ai_state": state,
        "proposal_allowed": proposal,
        "current_mechanics_visible": mech_vis,
        "operator_meaning": thesis_line,
        "allowed_action_now": next_action,
        "next_operator_action": next_action,
        "primary_risk": primary_risk,
        "held": held or bool(decision.get("held")),
        # Quote
        "last": last,
        "day_change_pct": quote.get("day_change_pct"),
        "price_as_of": quote.get("price_as_of"),
        "price_source": quote.get("price_source"),
        "quote_id": quote.get("quote_id"),
        "source_record_id": quote.get("source_record_id"),
        "market_session": quote.get("market_session"),
        "freshness_state": quote.get("freshness_state"),
        "market_state": quote.get("market_state"),
        # CIO / Maria summaries on card (COMPLETE only for model display)
        "cio_review": {
            "status": cio.get("status"),
            "summary": cio_summary_text,
            "verdict": cio.get("verdict") if cio.get("status") == "COMPLETE" else None,
            "provider": cio.get("provider") if cio.get("status") == "COMPLETE" else None,
            "model": cio.get("model") if cio.get("status") == "COMPLETE" else None,
            "policy": cio.get("executed_policy") if cio.get("status") == "COMPLETE" else "NO_CALL",
            "reason_code": cio.get("reason_code"),
            "display": cio.get("display"),
            "estimated_cost_usd": cio.get("estimated_cost_usd") if cio.get("status") == "COMPLETE" else 0.0,
        },
        "maria_review": {
            "status": maria.get("status"),
            "summary": maria_summary_text,
            "provider": maria.get("provider") if maria.get("status") == "COMPLETE" else None,
            "model": maria.get("model") if maria.get("status") == "COMPLETE" else None,
            "policy": maria.get("executed_policy") if maria.get("status") == "COMPLETE" else "NO_CALL",
            "reason_code": maria.get("reason_code"),
            "display": maria.get("display"),
            "estimated_cost_usd": maria.get("estimated_cost_usd") if maria.get("status") == "COMPLETE" else 0.0,
        },
        "sentinel_review": {
            "status": sentinel.get("status"),
            "summary": sentinel.get("summary") if sentinel.get("status") == "COMPLETE" else None,
            "reason_code": sentinel.get("reason_code"),
            "display": sentinel.get("display"),
            "kind": "reflective_or_deterministic_label_only",
        },
        # Tech / catalyst / rel perf
        "support": tech.get("support"),
        "resistance": tech.get("resistance"),
        "technical_setup": tech.get("setup_advisory") or tech.get("trend") or tech.get("technical_summary"),
        "rsi": _safe_float(tech.get("rsi") or enrich.get("rsi")),
        "rvol": _safe_float(tech.get("rvol")),
        "atr": _safe_float(enrich.get("atr")),
        "catalyst_summary": catalyst_summary,
        "catalyst_vs_industry": cat_vs_ind,
        "relative_performance_summary": rel.get("summary"),
        "relative_performance": rel,
        "one_line_thesis": thesis_line,
        "next_review_time": decision.get("next_deterministic_review_condition"),
        "material_change": False,
        "investment_thesis": thesis_line,
        "mechanics": decision.get("current_mechanics") if mech_vis else None,
        "provider_calls_on_build": 0,
        "schema": "watchlist_intelligence.card.v1",
    })


def list_intelligence(
    *,
    symbols: list[str] | None = None,
    limit: int = 24,
    offset: int = 0,
    priority_only: bool = True,
) -> dict[str, Any]:
    """Compact paginated list for the Intelligence Board (read-only)."""
    if symbols:
        syms = [s.upper() for s in symbols][offset: offset + limit]
    elif priority_only:
        syms = DEFAULT_PRIORITY[offset: offset + limit]
    else:
        # Active watchlist sample
        try:
            from db_adapter import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS symbol
                  FROM watchlist_items
                 WHERE status IN ('active','researched')
                 ORDER BY upper(symbol), updated_at DESC NULLS LAST
                 LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            syms = [r["symbol"] if hasattr(r, "keys") else r[0] for r in (cur.fetchall() or [])]
        except Exception:
            syms = DEFAULT_PRIORITY[:limit]

    if not syms:
        return {
            "ok": True,
            "schema": "watchlist_intelligence.list.v1",
            "provider_calls": 0,
            "paid_flags_enabled": False,
            "count": 0,
            "cards": [],
            "summary": _empty_summary(),
            "generated_at": _now_iso(),
        }

    from lib.watch_canonical_quote import batch_canonical_quotes

    street = _street_batch(syms)
    profiles = _profiles_batch(syms)
    quotes = batch_canonical_quotes(syms)
    tech = _tech_batch(syms)
    cats = _catalysts_batch(syms)
    enrich = _enrichment_map(syms)
    held = _held_set()

    cards = []
    for sym in syms:
        decision = _decision_for(sym)
        reviews = _reviews_for_symbol(sym)
        cards.append(_compose_card(
            sym,
            street=street.get(sym) or {},
            profile=profiles.get(sym) or {},
            quote=quotes.get(sym) or {},
            tech=tech.get(sym) or {},
            catalysts=cats.get(sym) or [],
            enrich=enrich.get(sym) or {},
            decision=decision,
            reviews=reviews,
            held=sym in held,
        ))

    return {
        "ok": True,
        "schema": "watchlist_intelligence.list.v1",
        "source": "deterministic_aggregation",
        "provider_calls": 0,
        "paid_flags_enabled": False,
        "broker_write_authority": "NONE",
        "count": len(cards),
        "offset": offset,
        "limit": limit,
        "cards": cards,
        "summary": _board_summary(cards),
        "flags": {
            "watch_intelligence_shadow": True,
            "watch_intelligence_visible": False,
            "watch_deepseek_flash_enabled": False,
            "watch_cio_daily_enabled": False,
        },
        "generated_at": _now_iso(),
    }


def _empty_summary() -> dict:
    return {
        "street_strong_buy": 0,
        "street_buy": 0,
        "trade_ai_wait": 0,
        "blocked_or_unavailable": 0,
        "managing_held": 0,
        "proposal_eligible": 0,
    }


def _board_summary(cards: list[dict]) -> dict:
    s = _empty_summary()
    for c in cards:
        r = c.get("street_rating")
        if r == "STRONG BUY":
            s["street_strong_buy"] += 1
        elif r == "BUY":
            s["street_buy"] += 1
        st = c.get("trade_ai_state")
        if st == "WAIT":
            s["trade_ai_wait"] += 1
        if st in ("BLOCKED", "DATA_UNAVAILABLE", "DETERMINISTIC_FAIL", "STALE", "AVOID"):
            s["blocked_or_unavailable"] += 1
        if st == "MANAGING" or c.get("held"):
            s["managing_held"] += 1
        if c.get("proposal_allowed"):
            s["proposal_eligible"] += 1
    return s


def detail_intelligence(symbol: str) -> dict[str, Any]:
    """Full Symbol Intelligence package — read-only, zero provider calls."""
    sym = symbol.upper()
    lst = list_intelligence(symbols=[sym], limit=1, priority_only=False)
    cards = lst.get("cards") or []
    if not cards:
        return {"ok": False, "error": "symbol_not_available", "symbol": sym, "provider_calls": 0}
    card = cards[0]
    reviews = _reviews_for_symbol(sym)
    enrich = _enrichment_map([sym]).get(sym) or {}
    profile = _profiles_batch([sym]).get(sym) or {}
    decision = _decision_for(sym)
    tech = _tech_batch([sym]).get(sym) or {}
    cats = _catalysts_batch([sym]).get(sym) or []

    # Mechanics only when valid
    mechanics = None
    if decision.get("current_mechanics_visible") and decision.get("primary_state") == "READY":
        mechanics = decision.get("current_mechanics")

    cio = next((r for r in reviews if r["agent_id"] == "cio"), not_run_review("cio"))
    maria = next((r for r in reviews if r["agent_id"] == "maria"), not_run_review("maria"))

    package = {
        "ok": True,
        "schema": "watchlist_intelligence.detail.v1",
        "symbol": sym,
        "provider_calls": 0,
        "paid_flags_enabled": False,
        "broker_write_authority": "NONE",
        "card": card,
        "identity": {
            "symbol": sym,
            "company": card.get("company"),
            "company_summary": card.get("company_summary"),
            "description": profile.get("description"),
            "sector": card.get("sector"),
            "industry": card.get("industry"),
            "instrument_type": card.get("instrument_type"),
            "what_the_company_does": profile.get("description") or profile.get("company_summary"),
            "business_model": None,  # typed gap — not in symbol_profiles
            "customers": None,
            "segments": None,
            "geography": None,
            "economic_sensitivity": None,
            "missing": [k for k in ("business_model", "customers", "segments", "geography", "economic_sensitivity") if True],
        },
        "street": card.get("street_consensus"),
        "trade_ai": decision,
        "cio_review": cio,
        "maria_review": maria,
        "reviews": reviews,
        "catalysts": {
            "timeline": cats,
            "versus_industry": card.get("catalyst_vs_industry"),
            "relative_score": None,
            "missing": ["relative_catalyst_score"] if True else [],
        },
        "relative_performance": card.get("relative_performance"),
        "fundamentals": _fundamentals_block(enrich, card.get("instrument_type")),
        "technicals": {
            "trend": tech.get("trend"),
            "rsi": card.get("rsi"),
            "rvol": card.get("rvol"),
            "atr": card.get("atr"),
            "support": tech.get("support"),
            "resistance": tech.get("resistance"),
            "setup": tech.get("setup_advisory") or tech.get("technical_summary"),
            "moving_averages": None,
            "missing": ["moving_averages"],
        },
        "mechanics": mechanics,
        "thesis": {
            "summary": card.get("one_line_thesis"),
            "counter_thesis": maria.get("counter_thesis") if maria.get("status") == "COMPLETE" else None,
            "risks": (maria.get("risks") if maria.get("status") == "COMPLETE" else [])
                     or ([card.get("primary_risk")] if card.get("primary_risk") else []),
            "what_changes_the_decision": (
                maria.get("what_changes_the_decision")
                if maria.get("status") == "COMPLETE"
                else decision.get("next_deterministic_review_condition")
            ),
        },
        "position": {"held": card.get("held")},
        "freshness_matrix": {
            "quote": card.get("freshness_state"),
            "quote_as_of": card.get("price_as_of"),
            "street_as_of": (card.get("street_consensus") or {}).get("as_of"),
            "profile_as_of": profile.get("profile_updated_at"),
            "cio_status": cio.get("status"),
            "maria_status": maria.get("status"),
        },
        "material_changes": [],
        "evidence_lineage": {
            "quote_id": card.get("quote_id"),
            "source_record_id": card.get("source_record_id"),
            "packet_id": decision.get("packet_id"),
            "material_fingerprint": decision.get("material_fingerprint"),
            "cio_artifact_id": cio.get("artifact_id") if cio.get("status") == "COMPLETE" else None,
            "maria_artifact_id": maria.get("artifact_id") if maria.get("status") == "COMPLETE" else None,
        },
        "generated_at": _now_iso(),
    }
    return _json_clean(package)


def reviews_intelligence(symbol: str) -> dict[str, Any]:
    """Stored immutable reviews only — never triggers provider calls."""
    sym = symbol.upper()
    reviews = _reviews_for_symbol(sym)
    complete = [r for r in reviews if r.get("status") == "COMPLETE"]
    return {
        "ok": True,
        "schema": "watchlist_intelligence.reviews.v1",
        "symbol": sym,
        "provider_calls": 0,
        "paid_flags_enabled": False,
        "count": len(reviews),
        "complete_count": len(complete),
        "reviews": reviews,
        "generated_at": _now_iso(),
    }
