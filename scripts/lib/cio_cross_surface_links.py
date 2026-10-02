"""Read-only cross-surface link index for Hermes research, CIO decisions and agents.

Schemas: HermesResearchLinks@v1, AgentRuntimeProof@v1
Authority: READ_ONLY_ADVISORY — this module only reads append-only evidence
stores; it never writes, never calls a provider and never infers a link that
is not recorded.  A link that no store records is reported as NOT_RECORDED;
a proof field that no store can attribute to an agent is NOT_EXPOSED.

Where Hermes consumption is recorded (the producer side already writes these):

* ``cio_research_impacts.jsonl`` (ResearchImpact@v1) — written by
  ``cio_product_reassessment`` when a completed Hermes result re-composes the
  CIO product: ``result_id`` -> ``new_product_id`` (a decision key resolvable
  by ``/api/v3/cio/decision/{id}/lineage``).
* ``intelligence_lineages.json`` (IntelligenceLineage@v1 projection) —
  ``research_result_ids`` -> ``decision_id`` / ``advisory_use.product_id`` /
  ``thesis_id`` / ``cio_case_id``.
* ``cio_investment_brief.json`` (CIOInvestmentProduct@v1, latest) —
  ``research_cases.items[].hermes_result_id`` and book/verdict
  ``thesis.source_refs`` -> ``symbol_thesis_version``.
* ``cio_workflow_lineage.jsonl`` (CIOWorkflowLineage@v1) — research node ->
  ``workflow_id`` (prefiltered, bounded tail scan).

All large stores are read with a bounded tail window; the response states the
window so a missing link outside it is not silently claimed absent forever.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Optional

LINKS_SCHEMA = "HermesResearchLinks@v1"
PROOF_SCHEMA = "AgentRuntimeProof@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

RECORDED = "RECORDED"
NOT_RECORDED = "NOT_RECORDED"
NOT_EXPOSED = "NOT_EXPOSED"

# Bounded windows (bytes) for large append-only stores.
RESULTS_TAIL_BYTES = int(os.getenv("CIO_XSURFACE_RESULTS_TAIL_BYTES", str(12 * 1024 * 1024)))
IMPACTS_TAIL_BYTES = int(os.getenv("CIO_XSURFACE_IMPACTS_TAIL_BYTES", str(16 * 1024 * 1024)))
WORKFLOW_TAIL_BYTES = int(os.getenv("CIO_XSURFACE_WORKFLOW_TAIL_BYTES", str(24 * 1024 * 1024)))
TRACES_TAIL_BYTES = int(os.getenv("CIO_XSURFACE_TRACES_TAIL_BYTES", str(16 * 1024 * 1024)))
RETRIEVALS_TAIL_BYTES = int(os.getenv("CIO_XSURFACE_RETRIEVALS_TAIL_BYTES", str(512 * 1024)))
CACHE_TTL_SECONDS = float(os.getenv("CIO_XSURFACE_CACHE_TTL_SECONDS", "60"))

# Agent-run triggers that are not natural (operator/test/fixture driven).
NON_NATURAL_TRIGGERS = frozenset({"manual", "test", "fixture", "replay", "backfill", "operator", "canary"})

_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


def default_cio_root() -> Path:
    env = os.getenv("TRADEAI_CIO_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data" / "cio"


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _tail_lines(path: Path, max_bytes: int, needle: Optional[Iterable[str]] = None) -> list[str]:
    """Return complete lines from the last ``max_bytes`` of ``path``.

    ``needle`` prefilters raw lines (any substring match) before JSON parsing.
    """
    if not path.is_file():
        return []
    needles = tuple(needle) if needle else ()
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            start = max(0, size - max(0, int(max_bytes)))
            handle.seek(start)
            blob = handle.read()
    except OSError:
        return []
    text = blob.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if start > 0 and lines:
        lines = lines[1:]  # first line is partial
    if needles:
        lines = [line for line in lines if any(n in line for n in needles)]
    return lines


def _parse(lines: Iterable[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _store_window(path: Path, max_bytes: int) -> dict[str, Any]:
    try:
        size = path.stat().st_size if path.is_file() else 0
    except OSError:
        size = 0
    return {
        "source_ref": path.name,
        "present": path.is_file(),
        "bytes": size,
        "window_bytes": min(size, max_bytes),
        "complete": size <= max_bytes,
    }


def _cached(key: tuple, builder):
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    value = builder()
    with _CACHE_LOCK:
        _CACHE[key] = (now, value)
    return value


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _add_ref(bucket: dict[str, dict[str, Any]], ref_id: str, **fields: Any) -> None:
    ref_id = _text(ref_id)
    if not ref_id:
        return
    row = bucket.setdefault(ref_id, {"id": ref_id, "sources": []})
    source = fields.pop("source", None)
    if source and source not in row["sources"]:
        row["sources"].append(source)
    for key, value in fields.items():
        if value not in (None, "", []) and row.get(key) in (None, "", []):
            row[key] = value


def _brief_thesis_refs(brief: dict[str, Any]) -> dict[str, dict[str, str]]:
    """result_id -> {symbol_thesis_version, symbol} from the latest product's book rows."""
    out: dict[str, dict[str, str]] = {}

    def visit(obj: Any) -> None:
        if isinstance(obj, dict):
            thesis = obj.get("thesis")
            if isinstance(thesis, dict):
                refs = thesis.get("source_refs") or []
                version = _text(thesis.get("symbol_thesis_version") or thesis.get("thesis_version"))
                if isinstance(refs, list) and version:
                    for ref in refs:
                        if _text(ref):
                            out.setdefault(_text(ref), {"thesis_ref": version, "symbol": _text(thesis.get("symbol"))})
            for value in obj.values():
                visit(value)
        elif isinstance(obj, list):
            for value in obj:
                visit(value)

    for key in ("reentry_book", "opportunity_book", "action_book", "governed_verdicts"):
        visit(brief.get(key))
    return out


def build_hermes_research_links(
    cio_root: Path | str | None = None,
    *,
    limit: int = 50,
    result_id: Optional[str] = None,
    decision_id: Optional[str] = None,
    symbol: Optional[str] = None,
) -> dict[str, Any]:
    """Reverse index: Hermes run/result -> CIO decisions, thesis refs and symbol."""
    root = Path(cio_root) if cio_root else default_cio_root()
    limit = max(1, min(int(limit or 50), 500))
    want_result = _text(result_id)
    want_decision = _text(decision_id)
    want_symbol = _text(symbol).upper()

    results_path = root / "hermes_research_results.jsonl"
    impacts_path = root / "cio_research_impacts.jsonl"
    lineage_path = root / "intelligence_lineages.json"
    brief_path = root / "cio_investment_brief.json"
    workflow_path = root / "cio_workflow_lineage.jsonl"

    results = [
        row for row in _parse(_tail_lines(results_path, RESULTS_TAIL_BYTES, needle=('"result_id"',)))
        if _text(row.get("result_id"))
    ]
    by_result: dict[str, dict[str, Any]] = {}
    for row in results:  # later rows win (append-only store)
        by_result[_text(row.get("result_id"))] = row

    decisions: dict[str, dict[str, dict[str, Any]]] = {}
    theses: dict[str, dict[str, dict[str, Any]]] = {}
    workflows: dict[str, set[str]] = {}
    lineage_ids: dict[str, set[str]] = {}
    plans: dict[str, set[str]] = {}

    for row in _parse(_tail_lines(impacts_path, IMPACTS_TAIL_BYTES, needle=('"result_id"',))):
        rid = _text(row.get("result_id"))
        if not rid:
            continue
        _add_ref(
            decisions.setdefault(rid, {}), _text(row.get("new_product_id")),
            kind="CIO_PRODUCT", as_of=row.get("as_of"), impact=row.get("impact"),
            source="cio_research_impacts.jsonl#ResearchImpact@v1",
        )

    lineage = _read_json(lineage_path)
    lineage_rows = lineage.get("lineages") if isinstance(lineage.get("lineages"), dict) else {}
    for lin_id, lin in (lineage_rows or {}).items():
        if not isinstance(lin, dict):
            continue
        rids = [_text(x) for x in (lin.get("research_result_ids") or []) if _text(x)]
        if not rids:
            continue
        advisory = lin.get("advisory_use") if isinstance(lin.get("advisory_use"), dict) else {}
        for rid in rids:
            bucket = decisions.setdefault(rid, {})
            src = "intelligence_lineages.json#IntelligenceLineage@v1"
            _add_ref(bucket, _text(lin.get("decision_id")), kind="CIO_DECISION", as_of=advisory.get("at"), source=src)
            _add_ref(bucket, _text(advisory.get("product_id")), kind="CIO_PRODUCT", as_of=advisory.get("at"), source=src)
            if _text(lin.get("thesis_id")):
                _add_ref(theses.setdefault(rid, {}), _text(lin.get("thesis_id")), source=src)
            lineage_ids.setdefault(rid, set()).add(_text(lin_id))
            if _text(lin.get("cio_case_id")):
                plans.setdefault(rid, set()).add(_text(lin.get("cio_case_id")))

    brief = _read_json(brief_path)
    brief_decision = _text(brief.get("decision_id") or brief.get("product_id"))
    cases = (brief.get("research_cases") or {}).get("items") if isinstance(brief.get("research_cases"), dict) else None
    for item in cases or []:
        if isinstance(item, dict) and _text(item.get("hermes_result_id")) and brief_decision:
            _add_ref(
                decisions.setdefault(_text(item.get("hermes_result_id")), {}), brief_decision,
                kind="CIO_DECISION", as_of=brief.get("as_of"),
                source="cio_investment_brief.json#research_cases",
            )
    for rid, ref in _brief_thesis_refs(brief).items():
        _add_ref(theses.setdefault(rid, {}), ref["thesis_ref"], symbol=ref.get("symbol") or None,
                 source="cio_investment_brief.json#thesis.source_refs")

    # Selection of the result rows to report.
    selected: list[dict[str, Any]]
    if want_result:
        selected = [by_result[want_result]] if want_result in by_result else []
    else:
        ordered = sorted(by_result.values(), key=lambda r: _text(r.get("completed_ts") or r.get("as_of")), reverse=True)
        if want_symbol:
            ordered = [r for r in ordered if _text(r.get("symbol")).upper() == want_symbol]
        if want_decision:
            ordered = [r for r in ordered if want_decision in decisions.get(_text(r.get("result_id")), {})]
        selected = ordered[:limit]

    # Workflow ids: one bounded, prefiltered scan for the selected research/result ids.
    wanted_ids = {_text(r.get("result_id")) for r in selected} | {_text(r.get("research_id")) for r in selected}
    wanted_ids.discard("")
    if wanted_ids:
        for row in _parse(_tail_lines(workflow_path, WORKFLOW_TAIL_BYTES, needle=('"node_id": "rr_', '"node_id": "res_'))):
            if row.get("record_type") != "node":
                continue
            node_id = _text(row.get("node_id"))
            if node_id in wanted_ids and _text(row.get("workflow_id")):
                workflows.setdefault(node_id, set()).add(_text(row.get("workflow_id")))

    items: list[dict[str, Any]] = []
    for row in selected:
        rid = _text(row.get("result_id"))
        research_id = _text(row.get("research_id"))
        dec = sorted(decisions.get(rid, {}).values(), key=lambda d: _text(d.get("as_of")), reverse=True)
        th = sorted(theses.get(rid, {}).values(), key=lambda d: d["id"])
        sym = _text(row.get("symbol")).upper()
        if not sym:
            sym_from_thesis = next((t.get("symbol") for t in th if t.get("symbol")), "")
            sym = _text(sym_from_thesis).upper()
        wf = sorted(workflows.get(rid, set()) | workflows.get(research_id, set()))
        items.append({
            "result_id": rid,
            "research_id": research_id or None,
            "plan_id": _text(row.get("plan_id")) or None,
            "completed_at": row.get("completed_ts") or row.get("as_of"),
            "classification": row.get("classification"),
            "agent": ((row.get("provenance") or {}).get("agent") if isinstance(row.get("provenance"), dict) else None),
            "symbol": sym or None,
            "symbol_link": {"state": RECORDED if sym else NOT_RECORDED},
            "decision_ids": [d["id"] for d in dec],
            "decisions": dec,
            "decision_link": {
                "state": RECORDED if dec else NOT_RECORDED,
                "reason": None if dec else "no ResearchImpact, IntelligenceLineage or current-product row references this result",
            },
            "thesis_refs": [t["id"] for t in th],
            "thesis_link": {"state": RECORDED if th else NOT_RECORDED},
            "workflow_ids": wf,
            "lineage_ids": sorted(lineage_ids.get(rid, set())),
            "cio_case_ids": sorted(plans.get(rid, set())),
        })

    by_decision: dict[str, list[str]] = {}
    for item in items:
        for did in item["decision_ids"]:
            by_decision.setdefault(did, []).append(item["result_id"])

    recorded = sum(1 for item in items if item["decision_link"]["state"] == RECORDED)
    return {
        "schema": LINKS_SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "composition_as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_as_of": max((_text(r.get("completed_ts") or r.get("as_of")) for r in selected), default=None),
        "filters": {"result_id": want_result or None, "decision_id": want_decision or None, "symbol": want_symbol or None, "limit": limit},
        "items": items,
        "by_decision": by_decision,
        "counts": {
            "results": len(items),
            "decision_link_recorded": recorded,
            "decision_link_not_recorded": len(items) - recorded,
            "thesis_link_recorded": sum(1 for i in items if i["thesis_refs"]),
            "symbol_recorded": sum(1 for i in items if i["symbol"]),
        },
        "stores": [
            _store_window(results_path, RESULTS_TAIL_BYTES),
            _store_window(impacts_path, IMPACTS_TAIL_BYTES),
            _store_window(lineage_path, 1 << 62),
            _store_window(brief_path, 1 << 62),
            _store_window(workflow_path, WORKFLOW_TAIL_BYTES),
        ],
        "honesty": "A link is RECORDED only when a store row names both ids; otherwise NOT_RECORDED. Nothing is inferred from symbol or time.",
    }


def _proof_field(state: str, *, value: Any = None, at: Any = None, source_ref: Optional[str] = None,
                 reason: Optional[str] = None, **extra: Any) -> dict[str, Any]:
    out = {"state": state, "value": value, "at": at, "source_ref": source_ref, "reason": reason}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def build_agent_runtime_proof(
    cio_root: Path | str | None = None,
    *,
    agent_ids: Optional[Iterable[str]] = None,
    research_links: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Per-agent runtime proof rows from production evidence stores.

    Fields: last_natural_wake, last_research_action, last_memory_retrieval,
    decisions_contributed.  Each is RECORDED (with value), NOT_RECORDED (the
    store attributes rows to agents but none to this one) or NOT_EXPOSED (no
    store attributes this proof to an agent at all).
    """
    root = Path(cio_root) if cio_root else default_cio_root()
    traces_path = root / "agent_run_traces.jsonl"
    results_path = root / "hermes_research_results.jsonl"
    retrievals_path = root / "aif_memory_retrievals.jsonl"

    wakes: dict[str, dict[str, Any]] = {}
    decisions: dict[str, dict[str, str]] = {}
    for row in _parse(_tail_lines(traces_path, TRACES_TAIL_BYTES, needle=('"agent"',))):
        agent = _text(row.get("agent")).lower()
        if not agent:
            continue
        trigger = _text(row.get("trigger")).lower()
        at = row.get("ended_at") or row.get("started_at")
        if trigger and trigger not in NON_NATURAL_TRIGGERS and _text(row.get("status")).lower() == "completed":
            if _text(at) >= _text((wakes.get(agent) or {}).get("at")):
                wakes[agent] = {"at": at, "wake_id": row.get("wake_id"), "trigger": row.get("trigger")}
        decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
        did = _text(decision.get("decision_id"))
        if did:
            bucket = decisions.setdefault(agent, {})
            if _text(at) >= bucket.get(did, ""):
                bucket[did] = _text(at)

    research: dict[str, dict[str, Any]] = {}
    for row in _parse(_tail_lines(results_path, RESULTS_TAIL_BYTES, needle=('"agent"',))):
        prov = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
        agent = _text(prov.get("agent")).lower()
        if not agent:
            continue
        at = row.get("completed_ts") or row.get("as_of")
        if _text(at) >= _text((research.get(agent) or {}).get("at")):
            research[agent] = {"at": at, "result_id": row.get("result_id"), "symbol": row.get("symbol")}

    retrieval_rows = _parse(_tail_lines(retrievals_path, RETRIEVALS_TAIL_BYTES))
    attributed_keys = ("agent", "agent_id", "consumer", "caller", "actor_id")
    retrieval_attributable = any(any(_text(r.get(k)) for k in attributed_keys) for r in retrieval_rows)
    retrievals: dict[str, str] = {}
    fleet_last_retrieval = max((_text(r.get("at")) for r in retrieval_rows), default="") or None
    if retrieval_attributable:
        for r in retrieval_rows:
            agent = next((_text(r.get(k)).lower() for k in attributed_keys if _text(r.get(k))), "")
            if agent and _text(r.get("at")) >= retrievals.get(agent, ""):
                retrievals[agent] = _text(r.get("at"))

    consumed: dict[str, set[str]] = {}
    for item in (research_links or {}).get("items") or []:
        agent = _text(item.get("agent")).lower()
        if agent:
            consumed.setdefault(agent, set()).update(item.get("decision_ids") or [])

    observed = set(wakes) | set(decisions) | set(research) | set(retrievals) | set(consumed)
    requested = {_text(a).lower() for a in (agent_ids or []) if _text(a)}
    agents: dict[str, Any] = {}
    for agent in sorted(observed | requested):
        wake = wakes.get(agent)
        res = research.get(agent)
        trace_decisions = decisions.get(agent, {})
        consumed_ids = sorted(consumed.get(agent, set()))
        if trace_decisions:
            recent = sorted(trace_decisions.items(), key=lambda kv: kv[1], reverse=True)
            dec_field = _proof_field(
                RECORDED, value=len(trace_decisions), at=recent[0][1], source_ref="agent_run_traces.jsonl#decision.decision_id",
                recent_ids=[k for k, _ in recent[:5]], window="tail",
            )
        elif consumed_ids:
            dec_field = _proof_field(
                RECORDED, value=len(consumed_ids), source_ref="cio_research_impacts.jsonl + intelligence_lineages.json (result consumed)",
                recent_ids=consumed_ids[:5], window="tail",
            )
        else:
            dec_field = _proof_field(NOT_RECORDED, value=0, source_ref="agent_run_traces.jsonl",
                                     reason="no decision row attributed to this agent in the read window")
        if retrieval_attributable:
            mem_field = (
                _proof_field(RECORDED, at=retrievals[agent], source_ref="aif_memory_retrievals.jsonl")
                if agent in retrievals else
                _proof_field(NOT_RECORDED, source_ref="aif_memory_retrievals.jsonl", reason="no retrieval attributed to this agent")
            )
        else:
            mem_field = _proof_field(
                NOT_EXPOSED, source_ref="aif_memory_retrievals.jsonl",
                reason="retrieval rows carry no agent attribution", fleet_last_at=fleet_last_retrieval,
            )
        agents[agent] = {
            "last_natural_wake": (
                _proof_field(RECORDED, value=wake.get("trigger"), at=wake.get("at"), source_ref="agent_run_traces.jsonl", wake_id=wake.get("wake_id"))
                if wake else
                _proof_field(NOT_RECORDED, source_ref="agent_run_traces.jsonl", reason="no completed natural run attributed to this agent in the read window")
            ),
            "last_research_action": (
                _proof_field(RECORDED, value=res.get("result_id"), at=res.get("at"), source_ref="hermes_research_results.jsonl#provenance.agent", symbol=res.get("symbol"))
                if res else
                _proof_field(NOT_RECORDED, source_ref="hermes_research_results.jsonl#provenance.agent", reason="no research result attributed to this agent")
            ),
            "last_memory_retrieval": mem_field,
            "decisions_contributed": dec_field,
        }
    return {
        "schema": PROOF_SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "evidence_class": "PRODUCTION_STORE_READ",
        "composition_as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fields": {
            "last_natural_wake": {"attributable": True, "source_ref": "agent_run_traces.jsonl"},
            "last_research_action": {"attributable": True, "source_ref": "hermes_research_results.jsonl"},
            "last_memory_retrieval": {"attributable": retrieval_attributable, "source_ref": "aif_memory_retrievals.jsonl"},
            "decisions_contributed": {"attributable": True, "source_ref": "agent_run_traces.jsonl"},
        },
        "agents": agents,
        "stores": [
            _store_window(traces_path, TRACES_TAIL_BYTES),
            _store_window(results_path, RESULTS_TAIL_BYTES),
            _store_window(retrievals_path, RETRIEVALS_TAIL_BYTES),
        ],
    }


def cached_hermes_research_links(**kwargs: Any) -> dict[str, Any]:
    key = ("links", str(kwargs.get("cio_root") or default_cio_root()), kwargs.get("limit"), kwargs.get("result_id"),
           kwargs.get("decision_id"), kwargs.get("symbol"))
    return _cached(key, lambda: build_hermes_research_links(**kwargs))


def cached_agent_runtime_proof(cio_root: Path | str | None = None, agent_ids: Optional[Iterable[str]] = None) -> dict[str, Any]:
    ids = tuple(sorted({_text(a).lower() for a in (agent_ids or []) if _text(a)}))
    key = ("proof", str(cio_root or default_cio_root()), ids)

    def build() -> dict[str, Any]:
        links = build_hermes_research_links(cio_root, limit=500)
        return build_agent_runtime_proof(cio_root, agent_ids=ids, research_links=links)

    return _cached(key, build)
