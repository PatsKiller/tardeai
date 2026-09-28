"""research_write_path.py — the ONE write path for thesis-like research (Wave 2 item 2).

Every producer that generates research prose about a subject (external lanes, watchlist agents,
analyst / research-intel, advisory opinion, options CIO review, AEC thesis fact) hands its result to
``submit``. The adapter stamps memory provenance (context_id, retrieval_receipt_id, memory_context_miss)
from the producer's open MemoryContext, normalises the payload to the ResearchResult shape that
``research_thesis_delta.accept_research_result`` reads, and then either

* SHADOW (default per lane): records a ``WritePathReceipt@v1`` row saying exactly what WOULD have been
  handed to the write path (payload hash, classification, provenance) — no thesis store is touched; or
* LIVE: calls the existing single writer (``accept_research_result`` via
  ``cio_product_reassessment.reassess_on_research_completed`` when a request envelope exists).

Modes live in ``config/memory_influence_policy.json`` → ``write_path.adapters.<lane_id>``; the global
``TRADEAI_INTELLIGENCE_MODE`` kill switch forces SHADOW everywhere. ``TRADEAI_WRITE_PATH_MODE`` overrides
a single process (tests / operator runs). Authority: READ_ONLY_ADVISORY — nothing here sizes, orders,
stops or weights; ``MBI_BEHAVIOR`` stays 0. The adapter never raises into a producer.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any

SCHEMA = "WritePathReceipt@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
LANES = ("hermes-external", "hermes-cio-worker", "watchlist-agent", "analyst-research-intel",
         "advisory-desk-opinion", "options-cio-review", "aec-thesis-fact")
CLASSIFICATIONS = ("CONFIRMS", "STRENGTHENS", "WEAKENS", "INVALIDATES", "NO_NEW_INFO", "CONFLICTED", "INSUFFICIENT_DATA")
DEFAULT_CLASSIFICATION = "NO_NEW_INFO"


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _lib(name: str):
    try:
        return __import__(name)
    except ImportError:
        pass
    for prefix in ("lib.", "scripts.lib."):
        try:
            mod = __import__(prefix + name, fromlist=[name])
            return mod
        except ImportError:
            continue
    raise ImportError(name)


def _proj_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _policy(env: dict) -> dict:
    p = Path(env.get("TRADEAI_MEMORY_INFLUENCE_POLICY") or _proj_root() / "config" / "memory_influence_policy.json")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def lane_family(lane_id: str) -> str:
    """'hermes-external-chatgpt' → 'hermes-external'; 'watchlist-agent-alex' → 'watchlist-agent'."""
    l = str(lane_id or "")
    for fam in LANES:
        if l == fam or l.startswith(fam + "-"):
            return fam
    return l


def mode_for(lane_id: str, env: dict | None = None) -> str:
    """SHADOW | LIVE for a producer lane. Global kill switch → SHADOW. Unknown lane → SHADOW."""
    env = os.environ if env is None else env
    if str(env.get("TRADEAI_INTELLIGENCE_MODE", "")).upper() == "SHADOW":
        return "SHADOW"
    forced = str(env.get("TRADEAI_WRITE_PATH_MODE", "")).upper()
    if forced in ("SHADOW", "LIVE"):
        return forced
    wp = (_policy(env).get("write_path") or {})
    adapters = wp.get("adapters") or {}
    m = adapters.get(lane_id) or adapters.get(lane_family(lane_id)) or wp.get("default") or "SHADOW"
    m = str(m).upper()
    return m if m in ("SHADOW", "LIVE") else "SHADOW"


def receipts_path(root: Path | None = None, env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("TRADEAI_WRITE_PATH_RECEIPTS_PATH"):
        return Path(env["TRADEAI_WRITE_PATH_RECEIPTS_PATH"])
    ic = _lib("intelligence_client")
    return ic._cio_dir(root, env) / "research_write_path_receipts.jsonl"


def stamp_provenance(result: dict, ctx: dict | None = None) -> dict:
    """Copy memory provenance onto a producer result IN PLACE (call before shadow_commit clears the
    process-current context). Returns the same dict."""
    if not isinstance(result, dict):
        return result
    ctx_id = rr_id = None
    if isinstance(ctx, dict):
        ctx_id = ctx.get("context_id")
        rr_id = ctx.get("retrieval_receipt_id") or ((ctx.get("retrieval_receipt") or {}).get("receipt_id")
                                                    if isinstance(ctx.get("retrieval_receipt"), dict) else ctx.get("retrieval_receipt"))
    if not ctx_id:
        try:
            ic = _lib("intelligence_client")
            ctx_id = ic.current_context_id()
            rr_id = rr_id or ic.current_retrieval_receipt_id()
        except Exception:  # noqa: BLE001
            pass
    result.setdefault("context_id", ctx_id)
    if rr_id:
        result.setdefault("retrieval_receipt_id", rr_id)
    result.setdefault("memory_context_miss", ctx_id is None)
    if isinstance(ctx, dict) and ctx.get("degraded"):
        result.setdefault("memory_context_degraded", True)
    return result


def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def normalize(result: dict, *, symbol: str, lane_id: str) -> dict:
    """Project any producer's output onto the ResearchResult fields accept_research_result reads.
    Missing classification → NO_NEW_INFO, so an unstructured producer records a delta but can never
    publish a thesis version (publishing needs grade A + a material classification)."""
    r = dict(result or {})
    summary = _first(r, "summary", "answer", "review", "narrative", "full_narrative", "opinion", "text", "claim")
    if isinstance(summary, dict):
        summary = summary.get("summary") or summary.get("text") or json.dumps(summary, sort_keys=True)[:2000]
    cls = str(_first(r, "classification") or DEFAULT_CLASSIFICATION).upper()
    if cls not in CLASSIFICATIONS:
        cls = DEFAULT_CLASSIFICATION
    evidence = _first(r, "evidence", "evidence_json", "facts", "primary_disclosures") or []
    if isinstance(evidence, dict):
        evidence = [evidence]
    if not isinstance(evidence, list):
        evidence = [str(evidence)]
    out = {
        **r,
        "symbol": symbol,
        "summary": str(summary or "")[:4000],
        "recommendation": str(_first(r, "recommendation", "stance", "verdict", "conviction", "decision") or "")[:400],
        "classification": cls,
        "confidence": r.get("confidence"),
        "evidence": evidence,
        "source_refs": _first(r, "source_refs", "sources", "citations") or [],
        "provider": r.get("provider") or r.get("model_used") or lane_id,
        "model": r.get("model") or r.get("model_used"),
        "write_path_lane": lane_id,
        "authority": AUTHORITY,
    }
    return out


def _payload_sha(payload: dict) -> str:
    keep = {k: payload.get(k) for k in ("symbol", "summary", "recommendation", "classification", "confidence", "evidence", "source_refs")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _receipt(row: dict, root: Path | None, env: dict) -> None:
    p = receipts_path(root, env)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    except OSError:
        pass


def submit(lane_id: str, symbol: str, result: dict, *, research_id: str, ctx: dict | None = None,
           request: dict | None = None, root: Path | None = None, env: dict | None = None,
           trigger: str = "research_completion") -> dict:
    """Hand one producer result to the single write path. Never raises.

    Returns {ok, mode, accepted, receipt_id, classification, context_id, ...}. In SHADOW the thesis
    stores are untouched and ``accepted`` is False; the receipt is the proof of what would have flowed.
    """
    env = os.environ if env is None else env
    sym = str(symbol or "").upper().strip()
    mode = mode_for(lane_id, env)
    try:
        stamped = stamp_provenance(dict(result or {}), ctx)
        payload = normalize(stamped, symbol=sym, lane_id=lane_id)
        sha = _payload_sha(payload)
        rid = hashlib.sha256(f"{lane_id}|{sym}|{research_id}|{sha}".encode("utf-8")).hexdigest()[:16]
        row = {"schema": SCHEMA, "receipt_id": f"wp_{rid}", "ts": _now_iso(), "lane_id": lane_id,
               "lane_family": lane_family(lane_id), "symbol": sym, "research_id": str(research_id),
               "mode": mode, "would_call": "research_thesis_delta.accept_research_result",
               "classification": payload["classification"], "has_summary": bool(payload["summary"]),
               "context_id": payload.get("context_id"), "retrieval_receipt_id": payload.get("retrieval_receipt_id"),
               "memory_context_miss": bool(payload.get("memory_context_miss")),
               "payload_sha256": sha, "trigger": trigger, "authority": AUTHORITY, "memory_behavior_influence": 0}
        if not sym:
            row.update({"outcome": "REFUSED", "reason": "NO_SYMBOL"})
            _receipt(row, root, env)
            return {"ok": False, "mode": mode, "accepted": False, "receipt_id": row["receipt_id"], "reason": "NO_SYMBOL"}
        if mode != "LIVE":
            row["outcome"] = "SHADOW_RECORDED"
            _receipt(row, root, env)
            return {"ok": True, "mode": mode, "accepted": False, "receipt_id": row["receipt_id"],
                    "classification": payload["classification"], "context_id": payload.get("context_id")}
        # LIVE — the existing single writer, through the reassessment entry when a request envelope exists.
        if request:
            cpr = _lib("cio_product_reassessment")
            res = cpr.reassess_on_research_completed(dict(request), payload, root=root, env=env, notify=False)
        else:
            rtd = _lib("research_thesis_delta")
            rpc = _lib("research_prompt_context")
            pctx = payload.get("prompt_context") if isinstance(payload.get("prompt_context"), dict) else None
            if pctx is None and hasattr(rpc, "build_research_prompt_context"):
                try:
                    pctx = rpc.build_research_prompt_context(sym, question=str(payload.get("summary") or "")[:400], root=root)
                except Exception:  # noqa: BLE001
                    pctx = None
            pctx = pctx or {"symbol": sym, "as_of": _now_iso(), "standing_thesis": {}}
            res = rtd.accept_research_result(sym, payload, prompt_context=pctx, research_id=str(research_id), root=root,
                                             provider=payload.get("provider"), model=payload.get("model"), trigger=trigger)
        accepted = bool(isinstance(res, dict) and res.get("ok") and not res.get("refused"))
        row.update({"outcome": "ACCEPTED" if accepted else "NOT_ACCEPTED",
                    "version_published": bool(isinstance(res, dict) and res.get("version_published")),
                    "refusal_reason": (res or {}).get("refusal_reason") if isinstance(res, dict) else None})
        _receipt(row, root, env)
        return {"ok": True, "mode": mode, "accepted": accepted, "receipt_id": row["receipt_id"],
                "classification": payload["classification"], "context_id": payload.get("context_id"), "result": res}
    except Exception as exc:  # noqa: BLE001 — the write path must never take a producer down
        _receipt({"schema": SCHEMA, "receipt_id": None, "ts": _now_iso(), "lane_id": lane_id, "symbol": sym,
                  "research_id": str(research_id), "mode": mode, "outcome": "ERROR",
                  "error": f"{type(exc).__name__}:{str(exc)[:200]}", "authority": AUTHORITY}, root, env)
        return {"ok": False, "mode": mode, "accepted": False, "error": f"{type(exc).__name__}:{str(exc)[:200]}"}


def record_passthrough(lane_id: str, symbol: str, result: dict, *, research_id: str, ctx: dict | None = None,
                       root: Path | None = None, env: dict | None = None, trigger: str = "research_completion") -> dict:
    """The lane's existing call already reaches accept_research_result (the two Hermes lanes): record the
    receipt with the provenance that now rides on the result, call nothing. Never raises."""
    env = os.environ if env is None else env
    sym = str(symbol or "").upper().strip()
    try:
        stamped = stamp_provenance(dict(result or {}), ctx)
        payload = normalize(stamped, symbol=sym, lane_id=lane_id)
        sha = _payload_sha(payload)
        rid = hashlib.sha256(f"{lane_id}|{sym}|{research_id}|{sha}".encode("utf-8")).hexdigest()[:16]
        row = {"schema": SCHEMA, "receipt_id": f"wp_{rid}", "ts": _now_iso(), "lane_id": lane_id, "lane_family": lane_family(lane_id),
               "symbol": sym, "research_id": str(research_id), "mode": mode_for(lane_id, env), "outcome": "PASSTHROUGH",
               "would_call": "research_thesis_delta.accept_research_result", "classification": payload["classification"],
               "has_summary": bool(payload["summary"]), "context_id": payload.get("context_id"),
               "retrieval_receipt_id": payload.get("retrieval_receipt_id"), "memory_context_miss": bool(payload.get("memory_context_miss")),
               "payload_sha256": sha, "trigger": trigger, "authority": AUTHORITY, "memory_behavior_influence": 0}
        _receipt(row, root, env)
        return {"ok": True, "receipt_id": row["receipt_id"], "context_id": payload.get("context_id")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}:{str(exc)[:200]}"}


def read_receipts(root: Path | None = None, env: dict | None = None, limit: int = 100_000) -> list[dict]:
    p = receipts_path(root, env)
    out: list[dict] = []
    try:
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                if len(out) >= limit:
                    break
    except OSError:
        pass
    return out
