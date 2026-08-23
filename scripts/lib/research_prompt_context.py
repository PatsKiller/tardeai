"""Canonical stateful context for material symbol research.

The context is evidence, not authority. It contains no credentials, account
identifiers, raw chain-of-thought, or broker mutation capability.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "ResearchPromptContext@v1"
SAFE_MARKET_FIELDS = (
    "cached_at", "company", "sector", "industry", "country", "market_cap_b",
    "price", "atr", "rvol", "avg_vol_m", "sma20_pct", "sma50_pct",
    "sma200_pct", "week52_high_pct", "week52_low_pct", "rsi", "trend",
    "analyst_rating", "target_price", "perf_week_pct", "perf_month_pct",
    "perf_quarter_pct", "perf_ytd_pct", "perf_year_pct",
)
_SECRET_KEY = re.compile(r"(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|2fa|otp)", re.I)
_SECRET_VALUE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._~-]+|(?:api[_-]?key|password|secret|token)\s*[:=]\s*\S+)"
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _root(root: Path | str | None) -> Path:
    return Path(root) if root is not None else Path(__file__).resolve().parents[2]


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _redact(value: Any) -> Any:
    """Remove credential-shaped fields and strings from prompt context."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub("[REDACTED]", value)
    return value


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def delta_path(root: Path | str | None = None) -> Path:
    override = os.getenv("RESEARCH_THESIS_DELTA_PATH")
    return Path(override).expanduser() if override else _root(root) / "data/cio/research_thesis_deltas.jsonl"


def latest_delta(symbol: str, *, root: Path | str | None = None) -> dict[str, Any] | None:
    sym = str(symbol or "").upper()
    for row in reversed(_read_jsonl(delta_path(root))):
        if str(row.get("symbol") or "").upper() == sym:
            return row
    return None


def _market_snapshot(symbol: str, root: Path) -> dict[str, Any]:
    for rel in (
        "data/portfolios/state/ticker_enrichment_cache.json",
        "data/state/ticker_enrichment_cache.json",
    ):
        blob = _read_json(root / rel)
        if not isinstance(blob, dict):
            continue
        row = blob.get(symbol) or (blob.get("tickers") or {}).get(symbol)
        if isinstance(row, dict):
            return {k: row.get(k) for k in SAFE_MARKET_FIELDS if row.get(k) is not None}
    return {}


def deterministic_changes(current: dict[str, Any], previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    previous = previous or {}
    changes: list[dict[str, Any]] = []
    for key in sorted(set(current) | set(previous)):
        before, after = previous.get(key), current.get(key)
        if before != after:
            changes.append({"field": key, "before": before, "after": after})
    return changes


def _db_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    try:
        from scripts.db_adapter import _execute
    except Exception:
        try:
            from db_adapter import _execute  # type: ignore
        except Exception:
            return {}
    try:
        row = _execute(sql, params, fetch="one")
        return dict(row) if row else {}
    except Exception:
        return {}


def _previous_research(symbol: str) -> dict[str, Any] | None:
    row = _db_one(
        """SELECT id, recommendation, dissent, confidence, lane, model, created_at
           FROM hermes_external_research
           WHERE symbol=%s AND status='sent'
           ORDER BY created_at DESC LIMIT 1""",
        (symbol,),
    )
    if not row:
        return None
    return {
        "research_id": row.get("id"),
        "conclusion": row.get("recommendation"),
        "dissent": row.get("dissent"),
        "confidence": row.get("confidence"),
        "provider": row.get("lane"),
        "model": row.get("model"),
        "as_of": row.get("created_at"),
    }


def _market_regime() -> dict[str, Any] | None:
    row = _db_one(
        "SELECT regime_label, created_at FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1"
    )
    return row or None


def _sector_state(sector: str | None) -> dict[str, Any] | None:
    if not sector:
        return None
    row = _db_one(
        """SELECT sector, etf, state, rs5, rs20, rs60, slope, as_of
           FROM sector_momentum_state WHERE sector=%s ORDER BY as_of DESC LIMIT 1""",
        (sector,),
    )
    return row or None


def _memory_context(symbol: str) -> dict[str, Any]:
    base = {
        "authority": "NON_AUTHORITATIVE_CONTEXT",
        "memory_behavior_influence": "0",
        "retrieval_status": "NOT_CONFIGURED",
        "supporting": [],
        "counter": [],
        "conflicts": [],
    }
    try:
        from scripts.lib.agent_durable_memory import get_durable_provider
        from scripts.lib.agent_memory_governance import retrieve_for_context
        result = retrieve_for_context(
            get_durable_provider(),
            query=f"{symbol} investment thesis research context",
            symbols=[symbol],
            top_k=6,
            budget_tokens=900,
        )
    except Exception:
        return base

    def slim(rows: Any) -> list[dict[str, Any]]:
        return [
            {
                "memory_id": r.get("memory_id"),
                "status": r.get("status"),
                "memory_type": r.get("memory_type"),
                "subject": r.get("subject") or r.get("summary"),
            }
            for r in (rows or []) if isinstance(r, dict)
        ][:6]

    base.update({
        "retrieval_status": result.get("retrieval_status"),
        "supporting": slim(result.get("supporting")),
        "counter": slim(result.get("counter_memory")),
        "conflicts": list(result.get("conflicts") or [])[:6],
    })
    return base


def _ratified_lessons(symbol: str, root: Path) -> list[dict[str, Any]]:
    try:
        from scripts.lib.maturity_control.lessons import collect_lessons
        lessons = collect_lessons(root=root).get("lessons") or []
    except Exception:
        return []
    eligible = []
    for row in lessons:
        if row.get("lifecycle") not in {"RATIFIED_CONTEXT", "SHADOW_INFLUENCE", "ADVISORY_ACTIVE"}:
            continue
        symbols = [str(x).upper() for x in (row.get("symbols") or [])]
        if symbols and symbol not in symbols:
            continue
        eligible.append({
            "lesson_id": row.get("lesson_id"),
            "title": row.get("title"),
            "lifecycle": row.get("lifecycle"),
            "evidence_refs": list(row.get("evidence_refs") or [])[:8],
            "not_production_policy": True,
        })
    return eligible[:5]


def _eligible_feedback(symbol: str, root: Path) -> list[dict[str, Any]]:
    try:
        from scripts.lib.cio_operator_ticker_feedback import journal_for_symbol
        rows = journal_for_symbol(symbol, limit=10, root=root)
    except Exception:
        return []
    out = []
    for row in rows:
        if str(row.get("status") or "").upper() == "RETRO_LABELED":
            continue
        out.append({
            "feedback_id": row.get("feedback_id"),
            "intent": row.get("intent"),
            "stance": row.get("stance"),
            "reason": row.get("free_text"),
            "source_surface": row.get("channel"),
            "timestamp": row.get("ts"),
        })
    return out[:5]


def _financial_senses_receipts(symbol: str, root: Path) -> list[dict[str, Any]]:
    rows = _read_jsonl(root / "data/cio/agent_tool_traces.jsonl")
    out: list[dict[str, Any]] = []
    for row in reversed(rows):
        if not (row.get("fs_provider") or row.get("fs_capability")):
            continue
        row_symbol = str(row.get("symbol") or "").upper()
        if row_symbol and row_symbol != symbol:
            continue
        out.append({
            "receipt_id": row.get("receipt_id") or row.get("trace_id") or row.get("tool_call_id"),
            "symbol": row_symbol or None,
            "provider": row.get("fs_provider"),
            "capability": row.get("fs_capability"),
            "status": row.get("status"),
            "as_of": row.get("as_of") or row.get("ts") or row.get("timestamp"),
            "evidence_refs": list(row.get("evidence_refs") or [])[:8],
        })
        if len(out) >= 8:
            break
    return out


def build_research_prompt_context(
    symbol: str,
    *,
    question: str,
    root: Path | str | None = None,
    rag_catalog: dict[str, Any] | None = None,
    deterministic_current: dict[str, Any] | None = None,
    previous_research: dict[str, Any] | None = None,
    operator_feedback: list[dict[str, Any]] | None = None,
    memory_context: dict[str, Any] | None = None,
    ratified_lessons: list[dict[str, Any]] | None = None,
    financial_senses_receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the one redacted context contract used by material research lanes."""
    root_p = _root(root)
    sym = str(symbol or "").strip().upper()
    from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol
    fields = thesis_fields_for_symbol(sym, root=root_p)
    prior_delta = latest_delta(sym, root=root_p)
    current = deterministic_current if deterministic_current is not None else _market_snapshot(sym, root_p)
    prior_snapshot = (prior_delta or {}).get("deterministic_snapshot") or {}

    if rag_catalog is None:
        try:
            from scripts.lib.symbol_thesis_evidence import build_evidence_catalog
            rag_catalog = build_evidence_catalog(
                sym,
                question=question,
                role=str(fields.get("portfolio_role") or "UNKNOWN"),
                limit_each=8,
            )
        except Exception:
            rag_catalog = {"supporting": [], "contradictory": [], "sufficiency": {}}

    support = list((rag_catalog or {}).get("supporting") or [])[:8]
    contradiction = list((rag_catalog or {}).get("contradictory") or [])[:8]
    sector = current.get("sector") if isinstance(current, dict) else None
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "symbol_identity": {
            "symbol": sym,
            "company": current.get("company") if isinstance(current, dict) else None,
            "sector": sector,
            "industry": current.get("industry") if isinstance(current, dict) else None,
        },
        "memberships": list(fields.get("memberships") or []),
        "portfolio_role": fields.get("portfolio_role"),
        "standing_thesis": {
            "thesis_id": fields.get("symbol_thesis_id"),
            "version": fields.get("symbol_thesis_version"),
            "state": fields.get("thesis_state"),
            "stance": fields.get("thesis_stance"),
            "summary": fields.get("thesis_summary"),
            "last_reviewed": fields.get("last_reviewed"),
            "age_days": fields.get("thesis_age_days"),
            "fresh": fields.get("fresh"),
            "evidence_for": list(fields.get("evidence_for") or []),
            "counter_evidence": list(fields.get("counter_evidence") or []),
            "invalidation_conditions": list(fields.get("invalidation_conditions") or []),
        },
        "previous_research_delta": prior_delta,
        "previous_research_conclusion": previous_research if previous_research is not None else _previous_research(sym),
        "unresolved_research_gaps": list(fields.get("research_gaps") or []),
        "deterministic_current_data": current,
        "deterministic_changes_since_prior_review": deterministic_changes(current, prior_snapshot),
        "market_regime": _market_regime(),
        "sector_industry_state": _sector_state(str(sector) if sector else None),
        "rag": {
            "supporting": support,
            "contradictory": contradiction,
            "sufficiency": (rag_catalog or {}).get("sufficiency") or {},
            "retrieval_order": "RAG_FIRST_SUPPORT_AND_CONTRADICTION",
        },
        "operator_feedback": operator_feedback if operator_feedback is not None else _eligible_feedback(sym, root_p),
        "memory_context": memory_context if memory_context is not None else _memory_context(sym),
        "ratified_lessons": ratified_lessons if ratified_lessons is not None else _ratified_lessons(sym, root_p),
        "financial_senses_receipts": (
            list(financial_senses_receipts)[:8]
            if financial_senses_receipts is not None
            else _financial_senses_receipts(sym, root_p)
        ),
        "counter_evidence": contradiction,
        "question": question,
        "authority": AUTHORITY,
        "memory_behavior_influence": 0,
        "raw_chain_of_thought": False,
    }
    body = _redact(body)
    body["prompt_context_hash"] = _hash(body)
    body["as_of"] = _now()
    return body
