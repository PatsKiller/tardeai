#!/usr/bin/env python3
"""broker_promote_oversight.py — AI oversight gates for paper→broker promote.

Requires completed local agent reviews (Maria / Risk / Steph) and optional Grok+ChatGPT
cloud second-opinion before saving to the live broker queue. Merges with sizing gates in
evaluate-promote and promote-from-paper.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Config-driven (env override) — no hardcoded gate roster (per no-hardcoded-values rule).
REQUIRED_AGENTS = tuple(
    a.strip() for a in os.getenv("BROKER_REQUIRED_AGENTS", "maria,risk_agent,steph").split(",") if a.strip()
)
BLOCK_VOTES = frozenset(v.strip().upper() for v in os.getenv("BROKER_BLOCK_VOTES", "BLOCK").split(",") if v.strip())
WARN_VOTES = frozenset(
    v.strip().upper() for v in os.getenv("BROKER_WARN_VOTES", "REJECT,CAUTIOUS_TEST,WAIT_FOR_DATA").split(",") if v.strip()
)
WATCHLIST_REC_TO_VOTE = {
    "BUY": "APPROVE_TEST",
    "HOLD": "CAUTIOUS_TEST",
    "AVOID": "REJECT",
    "SELL": "REJECT",
    "WAIT": "WAIT_FOR_DATA",
    "BLOCK": "BLOCK",
}
CLOUD_CACHE_HOURS = int(os.getenv("BROKER_CLOUD_OVERSIGHT_CACHE_HOURS", "24"))
REQUIRE_CLOUD = os.getenv("BROKER_REQUIRE_CLOUD_OVERSIGHT", "0") == "1"
REQUIRE_CLOUD_LIVE = os.getenv("BROKER_REQUIRE_CLOUD_OVERSIGHT_LIVE", "0") == "1"
AUTO_CLOUD_OVERSIGHT = os.getenv("BROKER_AUTO_CLOUD_OVERSIGHT", "1") == "1"
CLOUD_INFLIGHT_STALE_SEC = int(os.getenv("BROKER_CLOUD_INFLIGHT_STALE_SEC", "300"))
INTEL_READINESS_BLOCK = float(os.getenv("BROKER_INTEL_READINESS_BLOCK", "50"))
INTEL_READINESS_WARN = float(os.getenv("BROKER_INTEL_READINESS_WARN", "75"))


def _get_conn():
    from db_adapter import _get_conn
    return _get_conn()


def _q(sql, params=None, one=False):
    try:
        cur = _get_conn().cursor()
        cur.execute(sql, params or ())
        if one:
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception:
        return None if one else []


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _cloud_inflight_path(proposal_id: int) -> Path:
    d = _project_root() / "data" / "broker_cloud_inflight"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{proposal_id}.lock"


def _is_cloud_inflight(proposal_id: int) -> bool:
    p = _cloud_inflight_path(proposal_id)
    if not p.exists():
        return False
    try:
        age = time.time() - p.stat().st_mtime
        if age > CLOUD_INFLIGHT_STALE_SEC:
            p.unlink(missing_ok=True)
            return False
    except Exception:
        return False
    return True


def _mark_cloud_inflight(proposal_id: int) -> bool:
    if _is_cloud_inflight(proposal_id):
        return False
    try:
        _cloud_inflight_path(proposal_id).write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception:
        return False


def _clear_cloud_inflight(proposal_id: int) -> None:
    try:
        _cloud_inflight_path(proposal_id).unlink(missing_ok=True)
    except Exception:
        pass


def _lane_availability() -> dict:
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
        from oauth_lane_status import lanes_available
        return lanes_available()
    except Exception:
        out = {"grok": False, "chatgpt": False}
        try:
            import cloud_review
            for lane in ("grok", "chatgpt"):
                out[lane] = bool(cloud_review.available(lane))
        except Exception:
            pass
        return out


def _fetch_agent_reviews(proposal_id: int) -> list[dict]:
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
        from cio_agent_contract import extract_evidence_packet as _eep
    except Exception:
        _eep = lambda x: {"evidence": [], "data_i_doubt": "none", "agent_contract": None}
    rows = _q(
        """SELECT agent_name, status, vote, confidence, summary, payload,
                  reviewed_by_model, reviewed_at
           FROM proposal_agent_reviews WHERE proposal_id=%s ORDER BY agent_name""",
        (proposal_id,),
    ) or []
    out = []
    for r in rows:
        ep = _eep(r.get("payload") or r)
        out.append({
            "agent": r.get("agent_name"),
            "status": r.get("status"),
            "vote": r.get("vote"),
            "verdict": r.get("vote"),
            "confidence": float(r["confidence"]) if r.get("confidence") is not None else None,
            "summary": (r.get("summary") or "")[:300],
            "model": r.get("reviewed_by_model"),
            "reviewed_at": str(r.get("reviewed_at") or "")[:19] or None,
            "evidence": ep.get("evidence") or [],
            "data_i_doubt": ep.get("data_i_doubt"),
            "agent_contract": ep.get("agent_contract"),
        })
    return out


def _fetch_local_llm(proposal_id: int) -> dict:
    prop = _q(
        """SELECT local_llm_review_status, llm_review_status, agent_review_status,
                  symbol, strategy_id, proposed_entry, proposed_stop, proposed_target1, proposed_rr,
                  catalyst, catalyst_verified, cio_view, origin, discovery_source, sizing_basis
           FROM paper_trade_proposals WHERE id=%s""",
        (proposal_id,), one=True,
    ) or {}
    analysis = _q(
        """SELECT model_used, narrative_source, summary, approve_case, reject_case, confidence,
                  catalyst_summary, risk_summary, technical_summary
           FROM paper_proposal_analysis WHERE proposal_id=%s
           ORDER BY created_at DESC LIMIT 1""",
        (proposal_id,), one=True,
    ) or {}
    has_analysis = bool(analysis.get("summary") or analysis.get("approve_case"))
    llm_status = prop.get("local_llm_review_status") or prop.get("llm_review_status") or ""
    if has_analysis:
        state = "complete"
    elif str(llm_status).upper() in ("QUEUED", "PENDING", "PROCESSING"):
        state = "queued"
    elif str(llm_status).upper() in ("COMPLETE", "COMPLETED", "DONE"):
        state = "complete"
    elif str(llm_status).upper() in ("ERROR", "FAILED"):
        state = "error"
    else:
        state = "missing"
    preview = analysis.get("approve_case") or analysis.get("summary") or ""
    fallback = _build_thesis_fallback(prop)
    if state == "missing" and fallback.strip():
        state = "watchlist_plan"
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
        from cio_agent_contract import extract_evidence_packet as _eep
    except Exception:
        _eep = lambda x: {"evidence": [], "data_i_doubt": "none", "agent_contract": None}
    _lep = _eep(analysis)
    return {
        "status": state,
        "model": analysis.get("model_used"),
        "narrative_source": analysis.get("narrative_source"),
        "summary_preview": str(preview)[:400] if preview else None,
        "confidence": float(analysis["confidence"]) if analysis.get("confidence") is not None else None,
        "proposal_llm_status": llm_status,
        "agent_review_status": prop.get("agent_review_status"),
        "symbol": prop.get("symbol"),
        "strategy_id": prop.get("strategy_id"),
        "thesis": preview or fallback,
        "evidence": _lep.get("evidence") or [],
        "data_i_doubt": _lep.get("data_i_doubt"),
        "agent_contract": _lep.get("agent_contract"),
    }


def _build_thesis_fallback(prop: dict) -> str:
    parts = []
    origin = str(prop.get("origin") or "").lower()
    discovery = str(prop.get("discovery_source") or "").lower()
    if origin == "watchlist" or discovery == "watchlist":
        rating = prop.get("cio_view")
        basis = prop.get("sizing_basis")
        if isinstance(basis, str):
            try:
                basis = json.loads(basis)
            except Exception:
                basis = {}
        if isinstance(basis, dict):
            rating = rating or basis.get("watchlist_rating")
            src = basis.get("watchlist_rating_source")
            if rating:
                label = f"Watchlist {rating}"
                if src:
                    label += f" ({src})"
                parts.append(label)
    if prop.get("catalyst"):
        tag = "Verified" if prop.get("catalyst_verified") else "Unverified"
        parts.append(f"{tag} catalyst: {prop['catalyst']}")
    entry, stop, tgt = prop.get("proposed_entry"), prop.get("proposed_stop"), prop.get("proposed_target1")
    if entry and stop and tgt:
        parts.append(f"Plan: entry ${entry}, stop ${stop}, target ${tgt}, R:R {prop.get('proposed_rr') or '—'}")
    if prop.get("strategy_id"):
        parts.append(f"Strategy: {prop['strategy_id']}")
    return ". ".join(parts)[:800]


def _fetch_cached_cloud_review(proposal_id: int) -> dict | None:
    row = _q(
        """SELECT metadata_json, human_review_label, notes, created_at
           FROM llm_feedback_observations
           WHERE workflow='broker_cloud_oversight' AND source_id=%s
             AND created_at > NOW() - (%s || ' hours')::interval
           ORDER BY created_at DESC LIMIT 1""",
        (str(proposal_id), str(CLOUD_CACHE_HOURS)), one=True,
    )
    if not row:
        return None
    meta = row.get("metadata_json")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    if not isinstance(meta, dict):
        meta = {}
    consensus = meta.get("consensus") or {}
    verdict = str(consensus.get("verdict") or row.get("human_review_label") or "UNKNOWN").upper()
    return {
        "status": verdict.lower() if verdict != "UNKNOWN" else "unknown",
        "consensus": consensus,
        "lanes": meta.get("lanes") or {},
        "ran_at": str(row.get("created_at") or "")[:19],
        "notes": row.get("notes"),
        "cached": True,
    }


def _persist_cloud_oversight(proposal_id: int, symbol: str, result: dict) -> None:
    try:
        consensus = result.get("consensus") or {}
        verdict = str(consensus.get("verdict") or "UNKNOWN").upper()
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO llm_feedback_observations
               (source_table, source_id, workflow, symbol, model_role, model_name,
                decision_action, human_review_label, notes, metadata_json)
               VALUES ('broker_promote_oversight', %s, 'broker_cloud_oversight', %s,
                       'consensus', 'grok+chatgpt', %s, %s, %s, %s::jsonb)""",
            (
                str(proposal_id),
                (symbol or "").upper()[:16],
                f"cloud_{verdict.lower()}",
                verdict,
                f"Broker cloud oversight #{proposal_id}: {verdict} ({consensus.get('lanes_ok', 0)} lanes)",
                json.dumps({
                    "proposal_id": proposal_id,
                    "consensus": consensus,
                    "lanes": result.get("lanes") or {},
                    "task": "broker_promote_oversight",
                }, default=str)[:12000],
            ),
        )
        conn.commit()
    except Exception:
        pass


def _cloud_review_context(proposal_id: int, local: dict) -> dict:
    """Facts cloud lanes need: timestamp, live price, thesis band, live R:R."""
    ctx = {
        "proposal_id": proposal_id,
        "symbol": local.get("symbol"),
        "strategy": local.get("strategy_id"),
        "local_llm_status": local.get("status"),
        "local_model": local.get("model"),
        "agent_review_status": local.get("agent_review_status"),
        "note": "Broker promote oversight — judge thesis vs LIVE price band, not plan entry alone",
    }
    try:
        from zoneinfo import ZoneInfo
        ctx["as_of_et"] = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        ctx["as_of_utc"] = datetime.now(timezone.utc).isoformat()[:19]
    prop = _q(
        """SELECT proposed_entry, proposed_stop, proposed_target1, proposed_rr, current_price,
                  origin, discovery_source, cio_view
           FROM paper_trade_proposals WHERE id=%s""",
        (proposal_id,), one=True,
    ) or {}
    try:
        from broker_trade_litmus import _fetch_live_quote
        from broker_thesis_validity import attach_thesis_validity
        sym = str(local.get("symbol") or "").upper()
        quote = _fetch_live_quote(sym)
        work = {**prop, "symbol": sym}
        if quote.get("last") is not None:
            work["current_price"] = quote["last"]
            work["quote_provider"] = quote.get("provider")
            work["refreshed_at"] = datetime.now(timezone.utc).isoformat()[:19]
        attach_thesis_validity(work)
        tv = work.get("thesis_validity") or {}
        ctx.update({
            "live_price": tv.get("current_price") or quote.get("last"),
            "quote_provider": quote.get("provider"),
            "planned_entry": prop.get("proposed_entry"),
            "stop": prop.get("proposed_stop"),
            "target": prop.get("proposed_target1"),
            "planned_rr": tv.get("planned_rr") or prop.get("proposed_rr"),
            "live_rr": tv.get("current_rr"),
            "drift_pct": tv.get("drift_pct"),
            "thesis_zone": tv.get("zone_status"),
            "thesis_valid_low": tv.get("valid_low"),
            "thesis_valid_high": tv.get("valid_high"),
            "thesis_actionable": tv.get("actionable"),
            "thesis_reasons": (tv.get("reasons") or [])[:4],
            "watchlist_rating": prop.get("cio_view"),
            "origin": prop.get("origin"),
        })
    except Exception as e:
        ctx["live_context_error"] = str(e)[:120]
    return ctx


def _build_cloud_review_subject(local: dict, context: dict) -> str:
    """Structured live trade packet — cloud judges the setup, not meta 'paper test' wording."""
    sym = local.get("symbol") or context.get("symbol") or "?"
    strat = local.get("strategy_id") or context.get("strategy") or "?"
    lines = [
        f"LIVE broker queue trade review (Path B — real Schwab/Fidelity desk, not Alpaca paper).",
        f"Symbol {sym} · strategy {strat} · proposal #{context.get('proposal_id')}.",
        f"As of {context.get('as_of_et') or context.get('as_of_utc') or 'now'}.",
    ]
    if context.get("watchlist_rating") or context.get("origin") == "watchlist":
        lines.append(f"Source: watchlist {context.get('watchlist_rating') or 'BUY'}.")
    if context.get("planned_entry"):
        lines.append(
            f"Plan entry ${context.get('planned_entry')} · stop ${context.get('stop')} · "
            f"target ${context.get('target')} · planned R:R {context.get('planned_rr') or '—'}."
        )
    if context.get("live_price") is not None:
        lines.append(
            f"Live ${context.get('live_price')} · drift {context.get('drift_pct')}% · "
            f"live R:R {context.get('live_rr') or '—'} · zone {context.get('thesis_zone') or '—'}."
        )
    if context.get("thesis_valid_low") is not None:
        lines.append(
            f"Valid band ${context.get('thesis_valid_low')} – ${context.get('thesis_valid_high')} "
            f"(actionable={context.get('thesis_actionable')})."
        )
    reasons = context.get("thesis_reasons") or []
    if reasons:
        lines.append("Band notes: " + "; ".join(str(r) for r in reasons[:3]))
    notes = (local.get("thesis") or "").strip()
    if notes:
        lines.append(f"Background: {notes[:500]}")
    lines.append(
        "Question: Given LIVE price and band, is this long setup still disciplined "
        "(ignore paperwork about paper testing — judge the trade math and thesis only)."
    )
    return "\n".join(lines)


def run_cloud_oversight(proposal_id: int, *, timeout: int = 120) -> dict:
    """Run Grok+ChatGPT second opinion on the local thesis. Persists cache row."""
    local = _fetch_local_llm(proposal_id)
    context = _cloud_review_context(proposal_id, local)
    thesis = _build_cloud_review_subject(local, context).strip()
    if not thesis:
        return {"ok": False, "error": "No trade context to review — refresh prices first"}

    try:
        import cloud_review
        result = cloud_review.review(
            "broker_live_trade_review",
            local_output=thesis,
            context=context,
            timeout=timeout,
            persist=True,
            symbol=str(local.get("symbol") or "").upper(),
            source="broker_promote_oversight",
        )
        _persist_cloud_oversight(proposal_id, str(local.get("symbol") or ""), result)
        consensus = result.get("consensus") or {}
        verdict = str(consensus.get("verdict") or "UNKNOWN").upper()
        return {
            "ok": bool(result.get("ok")),
            "status": verdict.lower() if verdict != "UNKNOWN" else "unknown",
            "consensus": consensus,
            "lanes": result.get("lanes") or {},
            "ran_at": datetime.now(timezone.utc).isoformat()[:19],
            "cached": False,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def needs_cloud_oversight(proposal_id: int) -> bool:
    """True when Grok+ChatGPT should run automatically for this proposal."""
    if not AUTO_CLOUD_OVERSIGHT:
        return False
    if _fetch_cached_cloud_review(proposal_id):
        return False
    if _is_cloud_inflight(proposal_id):
        return False
    lanes = _lane_availability()
    if not any(lanes.values()):
        return False
    local = _fetch_local_llm(proposal_id)
    thesis = (local.get("thesis") or "").strip()
    if not thesis:
        return False
    # Watchlist bridge rows often lack paper_proposal_analysis — allow cloud when price-plan thesis exists.
    if local.get("status") == "queued":
        return False
    if local.get("status") == "error":
        return False
    return True


def queue_cloud_oversight(proposal_id: int, *, timeout: int = 120) -> dict:
    """Spawn background Grok+ChatGPT review (non-blocking for API/UI)."""
    if not needs_cloud_oversight(proposal_id):
        return {"ok": True, "skipped": True, "reason": "not_needed"}
    if not _mark_cloud_inflight(proposal_id):
        return {"ok": True, "skipped": True, "reason": "already_running"}
    import subprocess as sp
    root = _project_root()
    py = str(root / ".venv/bin/python")
    script = str(root / "scripts/broker_promote_oversight.py")
    try:
        sp.Popen(
            [py, script, "--run-cloud-oversight", str(proposal_id), "--timeout", str(timeout)],
            cwd=str(root),
            stdout=sp.DEVNULL,
            stderr=sp.DEVNULL,
        )
        return {"ok": True, "queued": True, "proposal_id": proposal_id}
    except Exception as e:
        _clear_cloud_inflight(proposal_id)
        return {"ok": False, "error": str(e)[:120]}


def maybe_queue_cloud_oversight(proposal_id: int, *, timeout: int = 120) -> dict:
    """Safe to call from hot API paths — queues cloud review when prerequisites are met."""
    return queue_cloud_oversight(proposal_id, timeout=timeout)


def queue_cloud_oversight_batch(
    proposal_ids: list[int],
    *,
    timeout: int = 120,
    max_batch: int = 30,
) -> dict:
    """Queue background Grok+ChatGPT for an explicit ID list (filter-then-run workflow)."""
    queued: list[int] = []
    skipped: list[dict] = []
    seen: set[int] = set()
    for raw in proposal_ids or []:
        try:
            pid = int(raw)
        except Exception:
            continue
        if pid <= 0 or pid in seen:
            continue
        seen.add(pid)
        if len(queued) + len(skipped) >= max_batch:
            skipped.append({"id": pid, "reason": "batch_cap"})
            continue
        result = queue_cloud_oversight(pid, timeout=timeout)
        if result.get("queued"):
            queued.append(pid)
        else:
            skipped.append({"id": pid, "reason": result.get("reason") or result.get("error") or "skipped"})
    return {
        "ok": True,
        "queued": queued,
        "skipped": skipped,
        "queued_count": len(queued),
        "skipped_count": len(skipped),
        "max_batch": max_batch,
    }


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def evaluate_intel_diligence(proposal_id: int) -> dict:
    """Research/intel gates for paper→broker promote (catalyst, analyst, enrichment)."""
    violations: list[str] = []
    warnings: list[str] = []
    try:
        import broker_proposal_intel as bpi
        intel = bpi.get_intel_packet(proposal_id, include_oversight=False)
    except Exception as e:
        return {
            "ok": False,
            "violations": [f"Intel packet failed to load: {str(e)[:120]}"],
            "warnings": [],
        }

    if not intel.get("ok"):
        return {
            "ok": False,
            "violations": ["Decision context not loaded — run Enrich on paper proposal"],
            "warnings": [],
        }

    cat = intel.get("catalyst") or {}
    verdict = str(cat.get("critic_verdict") or "").upper()
    if verdict == "BLOCK":
        violations.append("Catalyst critic BLOCK — thesis rejected for live promote")
    elif verdict == "DOWNGRADE":
        warnings.append("Catalyst critic DOWNGRADE — reduced conviction")

    if cat.get("text") and not cat.get("verified"):
        warnings.append("Catalyst not verified — confirm headline before live size")
    elif not cat.get("text"):
        warnings.append("No catalyst on record")

    an = intel.get("analyst") or {}
    quality = an.get("quality") or {}
    for w in quality.get("warnings") or []:
        warnings.append(w)
    if quality.get("coverage") == "thin":
        warnings.append("Thin analyst coverage — single-source street data is not promote-grade")

    ir = intel.get("intel_readiness")
    if ir is not None:
        ir_f = float(ir)
        if ir_f < INTEL_READINESS_BLOCK:
            violations.append(
                f"Intel readiness {ir_f:.0f}% below {INTEL_READINESS_BLOCK:.0f}% — enrichment incomplete"
            )
        elif ir_f < INTEL_READINESS_WARN:
            warnings.append(
                f"Intel readiness {ir_f:.0f}% below promote-ready threshold ({INTEL_READINESS_WARN:.0f}%)"
            )

    tech = intel.get("technicals") or {}
    grade = str(tech.get("technical_grade") or tech.get("grade") or "").upper()
    if grade in ("TECH_INCOMPLETE", "INCOMPLETE"):
        warnings.append("Technical grade incomplete — confirm indicators before promote")

    return {
        "ok": True,
        "violations": _dedupe(violations),
        "warnings": _dedupe(warnings),
        "catalyst_verdict": verdict or None,
        "analyst_coverage": quality.get("coverage"),
        "intel_readiness": float(ir) if ir is not None else None,
        "source_count": quality.get("source_count"),
    }


def needs_oversight_queue(proposal_id: int) -> bool:
    """True when local agent/LLM diligence still needs to run."""
    snap = get_oversight_snapshot(proposal_id)
    pending = snap.get("agents", {}).get("pending") or []
    local_status = (snap.get("local_llm") or {}).get("status")
    return bool(pending) or local_status in ("missing", "queued")


def queue_oversight_jobs(proposal_id: int) -> dict:
    """Queue Maria/Risk/Steph + local LLM analysis for a proposal."""
    import subprocess as sp
    row = _q("SELECT symbol FROM paper_trade_proposals WHERE id=%s", (proposal_id,), one=True) or {}
    sym = str(row.get("symbol") or "").upper()
    root = Path(__file__).resolve().parent.parent
    py = str(root / ".venv/bin/python")
    scripts = root / "scripts"
    started = []
    for script, args in (
        ("queue_proposal_agent_reviews.py", ["--symbol", sym, "--apply"] if sym else ["--apply"]),
        ("proposal_intelligence_analyzer.py", ["--proposal-id", str(proposal_id), "--apply"]),
        ("proposal_agent_review.py", ["--proposal-id", str(proposal_id)]),
    ):
        try:
            sp.Popen(
                [py, str(scripts / script)] + args,
                cwd=str(root),
                stdout=sp.DEVNULL,
                stderr=sp.DEVNULL,
            )
            started.append(script)
        except Exception:
            pass
    return {"ok": True, "started": started, "symbol": sym}


def get_oversight_snapshot(proposal_id: int) -> dict:
    """Fast DB snapshot for UI — no cloud LLM calls."""
    reviews = _fetch_agent_reviews(proposal_id)
    by_agent = {r["agent"]: r for r in reviews}
    pending = [a for a in REQUIRED_AGENTS if by_agent.get(a, {}).get("status") == "pending" or not by_agent.get(a, {}).get("vote")]
    completed = [a for a in REQUIRED_AGENTS if a not in pending and by_agent.get(a, {}).get("vote")]
    local = _fetch_local_llm(proposal_id)
    cloud = _fetch_cached_cloud_review(proposal_id)
    if not cloud and _is_cloud_inflight(proposal_id):
        cloud = {
            "status": "running",
            "consensus": None,
            "lanes": {},
            "ran_at": None,
            "cached": False,
            "auto_queued": True,
        }
    lanes = _lane_availability()
    return {
        "agents": {
            "required": list(REQUIRED_AGENTS),
            "completed": len(completed),
            "pending": pending,
            "reviews": reviews,
        },
        "local_llm": local,
        "cloud_review": cloud or {
            "status": "not_run",
            "consensus": None,
            "lanes": {},
            "ran_at": None,
            "cached": False,
        },
        "lanes_available": lanes,
        "cloud_auto_enabled": AUTO_CLOUD_OVERSIGHT,
    }


def _is_live_route_proposal(proposal_id: int) -> bool:
    """True when proposal targets Schwab/Fidelity (live broker route, not simulation-only)."""
    row = _q(
        """SELECT intended_broker, target_account FROM paper_trade_proposals WHERE id=%s""",
        (proposal_id,), one=True,
    ) or {}
    broker = str(row.get("intended_broker") or row.get("target_account") or "").lower()
    return broker.startswith("schwab") or broker.startswith("fidelity")


def evaluate_oversight(proposal_id: int, *, cloud: dict | None = None, live_route: bool | None = None) -> dict:
    """PASS | WARN | BLOCK oversight verdict for broker promote."""
    snap = get_oversight_snapshot(proposal_id)
    if live_route is None:
        live_route = _is_live_route_proposal(proposal_id)
    require_cloud = REQUIRE_CLOUD or (REQUIRE_CLOUD_LIVE and live_route)
    violations: list[str] = []
    warnings: list[str] = []

    agents = snap["agents"]
    pending = agents.get("pending") or []
    if pending:
        violations.append(f"Agent reviews incomplete: {', '.join(pending)} still pending")

    for r in agents.get("reviews") or []:
        if r.get("agent") not in REQUIRED_AGENTS:
            continue
        vote = str(r.get("vote") or "").upper()
        if vote in BLOCK_VOTES:
            violations.append(f"{r['agent']} voted BLOCK")
        elif vote in WARN_VOTES:
            warnings.append(f"{r['agent']} voted {vote}")

    local = snap.get("local_llm") or {}
    if local.get("status") == "missing":
        violations.append("Local LLM decision packet missing — run AI Review before broker promote")
    elif local.get("status") == "queued":
        violations.append("Local LLM review still queued — wait for completion before promote")
    elif local.get("status") == "error":
        warnings.append("Local LLM review errored — re-run AI Review")

    intel_dd = evaluate_intel_diligence(proposal_id)
    violations.extend(intel_dd.get("violations") or [])
    warnings.extend(intel_dd.get("warnings") or [])

    try:
        import broker_trade_plan_gate as btpg
        tp_gate = btpg.assess_proposal_trade_plan(proposal_id)
        violations.extend(tp_gate.get("violations") or [])
        warnings.extend(tp_gate.get("warnings") or [])
    except Exception:
        violations.append("Trade plan gate unavailable — refresh before live route")

    violations = _dedupe(violations)
    warnings = _dedupe(warnings)

    cloud_data = cloud if cloud is not None else (snap.get("cloud_review") or {})
    cloud_status = str(cloud_data.get("status") or "not_run").lower()
    consensus = cloud_data.get("consensus") or {}
    lanes_ok = int(consensus.get("lanes_ok") or 0)

    if cloud_status == "disagree" and lanes_ok >= 1:
        violations.append("Grok/ChatGPT cloud review DISAGREE with local thesis")
    elif cloud_status == "caution" and lanes_ok >= 1:
        warnings.append("Grok/ChatGPT cloud review CAUTION — review concerns before sending")
    elif cloud_status in ("disagree", "caution", "error") and lanes_ok < 1:
        # Fail-closed: 0 usable lanes means inconclusive — BLOCK promote, not silent pass.
        violations.append(
            "Cloud oversight INCONCLUSIVE — 0 lanes returned a usable verdict; re-run Grok+ChatGPT before promote"
        )
    elif cloud_status == "agree" and lanes_ok < 1:
        violations.append("Cloud oversight AGREE claimed but 0 lanes OK — re-run Grok+ChatGPT before promote")
    elif cloud_status == "running":
        warnings.append("Cloud oversight running (Grok+ChatGPT) — refresh in a minute")
    elif cloud_status in ("not_run", "unknown", ""):
        if require_cloud:
            violations.append("Cloud oversight required but not run (Grok+ChatGPT)")
        else:
            avail = [k for k, v in (snap.get("lanes_available") or {}).items() if v]
            if avail:
                warnings.append(f"Cloud oversight not run — tap Run Grok+ChatGPT review ({', '.join(avail)} available)")
            else:
                warnings.append("Cloud oversight not run — Grok/ChatGPT lanes unavailable")
    elif cloud_status == "agree":
        pass

    if violations:
        status = "BLOCK"
        allowed = False
    elif warnings:
        status = "WARN"
        allowed = True
    else:
        status = "PASS"
        allowed = True

    out_snap = dict(snap)
    if cloud is not None and cloud.get("ok") is not False:
        out_snap["cloud_review"] = {
            "status": str(cloud.get("status") or "unknown").lower(),
            "consensus": cloud.get("consensus") or {},
            "lanes": cloud.get("lanes") or {},
            "ran_at": cloud.get("ran_at"),
            "cached": bool(cloud.get("cached")),
            "fresh_run": not cloud.get("cached", True),
        }

    return {
        "status": status,
        "allowed": allowed,
        "violations": violations,
        "warnings": warnings,
        "intel_diligence": intel_dd,
        "promote_ready": allowed and status == "PASS",
        **out_snap,
    }


def _stage(status: str, detail: str | None = None, action: str | None = None) -> dict:
    return {"status": status, "detail": detail, "action": action}


def _proposal_intel_row(proposal_id: int) -> dict:
    return _q(
        """SELECT ptp.intel_readiness, ptp.local_llm_review_status, ptp.llm_review_status,
                  ptp.catalyst_verified, ptp.packet_last_enriched_at,
                  scan.critic_verdict, scan.catalyst_verified AS scan_catalyst_verified
           FROM paper_trade_proposals ptp
           LEFT JOIN LATERAL (
               SELECT critic_verdict, catalyst_verified
               FROM trade_ai_scans WHERE symbol = ptp.symbol ORDER BY scanned_at DESC LIMIT 1
           ) scan ON true
           WHERE ptp.id=%s""",
        (proposal_id,), one=True,
    ) or {}


def build_promote_diligence_stages(
    proposal_id: int,
    *,
    snap: dict | None = None,
    intel_row: dict | None = None,
    intel_dd: dict | None = None,
    oversight: dict | None = None,
) -> list[dict]:
    """Seven-step broker promote maturity checklist."""
    snap = snap or get_oversight_snapshot(proposal_id)
    intel_row = intel_row or _proposal_intel_row(proposal_id)
    if intel_dd is None:
        intel_dd = evaluate_intel_diligence(proposal_id)
    if oversight is None:
        oversight = evaluate_oversight(proposal_id)

    ir = intel_row.get("intel_readiness")
    ir_f = float(ir) if ir is not None else None
    critic = str(intel_row.get("critic_verdict") or "").upper()
    pending = snap.get("agents", {}).get("pending") or []
    reviews = snap.get("agents", {}).get("reviews") or []
    local = snap.get("local_llm") or {}
    local_st = local.get("status") or "missing"
    cloud = snap.get("cloud_review") or {}
    cloud_st = str(cloud.get("status") or "not_run").lower()

    # 1 Enrich
    if ir_f is None:
        enrich = _stage("PENDING", "Not enriched", "Run Enrich / refresh proposal data")
    elif ir_f < INTEL_READINESS_BLOCK:
        enrich = _stage("BLOCK", f"Intel {ir_f:.0f}%", "Run proposal enrichment")
    elif ir_f < INTEL_READINESS_WARN:
        enrich = _stage("WARN", f"Intel {ir_f:.0f}%", "Re-enrich before live promote")
    else:
        enrich = _stage("PASS", f"Intel {ir_f:.0f}%")

    # 2 Agent reviews
    if pending:
        agents = _stage(
            "PENDING",
            f"Pending: {', '.join(pending)}",
            "Queue agent reviews",
        )
    else:
        warn_votes = [
            f"{r['agent']} {r.get('vote')}"
            for r in reviews
            if r.get("agent") in REQUIRED_AGENTS and str(r.get("vote") or "").upper() in WARN_VOTES
        ]
        block_votes = [
            r["agent"] for r in reviews
            if r.get("agent") in REQUIRED_AGENTS and str(r.get("vote") or "").upper() in BLOCK_VOTES
        ]
        if block_votes:
            agents = _stage("BLOCK", f"Blocked: {', '.join(block_votes)}", "Review agent dissent")
        elif warn_votes:
            agents = _stage("WARN", "; ".join(warn_votes[:2]), "Review cautious agent votes")
        else:
            agents = _stage("PASS", f"{len(REQUIRED_AGENTS)} agents complete")

    # 3 Local LLM
    if local_st == "missing":
        llm = _stage("BLOCK", "No decision packet", "Run AI Review (step 3)")
    elif local_st == "queued":
        llm = _stage("PENDING", "Queued", "Wait for AI Review to finish")
    elif local_st == "error":
        llm = _stage("WARN", "Review errored", "Re-run AI Review")
    else:
        llm = _stage("PASS", local.get("model") or "complete")

    # 4 Research intel (catalyst + analyst)
    if not intel_dd.get("ok"):
        research = _stage("BLOCK", "Intel packet missing", "Run Enrich")
    elif intel_dd.get("violations"):
        research = _stage("BLOCK", intel_dd["violations"][0][:80], "Fix intel blockers")
    elif intel_dd.get("warnings"):
        research = _stage("WARN", f"Critic {critic or '—'} · {intel_dd.get('analyst_coverage') or '—'} coverage")
    else:
        research = _stage("PASS", f"Critic {critic or '—'}")

    # 5 Cloud oversight
    lanes_ok = int((cloud.get("consensus") or {}).get("lanes_ok") or 0)
    if cloud_st in ("disagree", "caution", "error") and lanes_ok < 1:
        cloud_stage = _stage("BLOCK", "Cloud INCONCLUSIVE (0 lanes)", "Re-run Grok+ChatGPT review")
    elif cloud_st == "disagree":
        cloud_stage = _stage("BLOCK", "Grok+ChatGPT DISAGREE", "Reconcile thesis or reject")
    elif cloud_st == "caution":
        cloud_stage = _stage("WARN", "Cloud CAUTION", "Read cloud concerns")
    elif cloud_st == "agree" and lanes_ok < 1:
        cloud_stage = _stage("BLOCK", "Cloud AGREE but 0 lanes", "Re-run Grok+ChatGPT review")
    elif cloud_st == "agree":
        cloud_stage = _stage("PASS", "Cloud AGREE")
    elif cloud_st == "running":
        cloud_stage = _stage("PENDING", "Grok+ChatGPT running", "Wait for cloud review")
    elif REQUIRE_CLOUD or (REQUIRE_CLOUD_LIVE and _is_live_route_proposal(proposal_id)):
        cloud_stage = _stage("BLOCK", "Not run", "Run Grok+ChatGPT review")
    elif AUTO_CLOUD_OVERSIGHT and needs_cloud_oversight(proposal_id):
        cloud_stage = _stage("PENDING", "Auto-queuing cloud", "Grok+ChatGPT will run shortly")
    else:
        lanes = [k for k, v in (snap.get("lanes_available") or {}).items() if v]
        cloud_stage = _stage("WARN" if lanes else "PENDING", "Not run", "Run Grok+ChatGPT (optional)")

    # 6 Trade plan (authoritative entry/stop/target — no generic 2R gambling)
    try:
        import broker_trade_plan_gate as btpg
        tp_gate = btpg.assess_proposal_trade_plan(proposal_id)
    except Exception:
        tp_gate = {"status": "BLOCK", "violations": ["Trade plan gate error"], "plan_source": None}
    if tp_gate.get("violations"):
        trade_plan = _stage(
            "BLOCK",
            tp_gate["violations"][0][:80],
            "Run materialize cards + bridge refresh or add trade_plans row",
        )
    elif tp_gate.get("warnings"):
        trade_plan = _stage("WARN", tp_gate["warnings"][0][:80], "Refresh plan before live route")
    elif tp_gate.get("status") == "PASS":
        src = tp_gate.get("plan_source") or "authoritative"
        trade_plan = _stage("PASS", f"Plan: {src}")
    else:
        trade_plan = _stage("BLOCK", "No authoritative plan", "Add trade_plans or strategy card levels")

    # 7 Broker gate (oversight + sizing deferred to modal/account)
    ov_st = oversight.get("status") or "PASS"
    if ov_st == "BLOCK":
        broker = _stage("BLOCK", f"{len(oversight.get('violations') or [])} blocker(s)", "Resolve diligence blockers")
    elif ov_st == "WARN":
        broker = _stage("WARN", f"{len(oversight.get('warnings') or [])} warning(s)", "Review then size for account")
    else:
        broker = _stage("PASS", "Diligence clear — pick account & size")

    return [
        {"id": "enrich", "label": "Enrich", **enrich},
        {"id": "agents", "label": "Agents", **agents},
        {"id": "local_llm", "label": "AI Review", **llm},
        {"id": "research", "label": "Intel", **research},
        {"id": "cloud", "label": "Cloud", **cloud_stage},
        {"id": "trade_plan", "label": "Trade plan", **trade_plan},
        {"id": "broker", "label": "Broker", **broker},
    ]


def _next_action_from_stages(stages: list[dict]) -> str:
    for s in stages:
        if s.get("status") in ("BLOCK", "PENDING", "WARN"):
            return s.get("action") or f"Complete {s.get('label')}"
    return "Open Send to Broker — pick account and confirm sizing"


def build_promote_diligence_plan(proposal_id: int) -> dict:
    """Full broker promote maturity plan for UI + API."""
    snap = get_oversight_snapshot(proposal_id)
    intel_row = _proposal_intel_row(proposal_id)
    intel_dd = evaluate_intel_diligence(proposal_id)
    oversight = evaluate_oversight(proposal_id)
    stages = build_promote_diligence_stages(
        proposal_id, snap=snap, intel_row=intel_row, intel_dd=intel_dd, oversight=oversight,
    )
    blockers = [s for s in stages if s.get("status") == "BLOCK"]
    pending = [s for s in stages if s.get("status") == "PENDING"]
    done = sum(1 for s in stages if s.get("status") == "PASS")
    current_idx = next(
        (i for i, s in enumerate(stages) if s.get("status") in ("BLOCK", "PENDING", "WARN")),
        len(stages) - 1,
    )
    overall = "BLOCK" if blockers or oversight.get("status") == "BLOCK" else (
        "WARN" if oversight.get("status") == "WARN" or any(s.get("status") == "WARN" for s in stages) else "PASS"
    )
    return {
        "proposal_id": proposal_id,
        "status": overall,
        "promote_ready": bool(oversight.get("promote_ready")),
        "stages": stages,
        "current_step": current_idx + 1,
        "total_steps": len(stages),
        "completed_steps": done,
        "next_action": _next_action_from_stages(stages),
        "auto_queue_recommended": needs_oversight_queue(proposal_id),
        "oversight": oversight,
        "intel_diligence": intel_dd,
    }


def get_broker_diligence_summary(proposal_id: int) -> dict:
    """Lightweight diligence summary for paper proposal cards."""
    snap = get_oversight_snapshot(proposal_id)
    intel_row = _proposal_intel_row(proposal_id)
    pending = snap.get("agents", {}).get("pending") or []
    local_st = (snap.get("local_llm") or {}).get("status") or "missing"
    ir = intel_row.get("intel_readiness")
    ir_f = float(ir) if ir is not None else None
    critic = str(intel_row.get("critic_verdict") or "").upper()

    blockers: list[str] = []
    if pending:
        blockers.append(f"agents pending ({', '.join(pending)})")
    if local_st in ("missing", "queued"):
        blockers.append(f"AI review {local_st}")
    if critic == "BLOCK":
        blockers.append("catalyst critic BLOCK")
    if ir_f is not None and ir_f < INTEL_READINESS_BLOCK:
        blockers.append(f"intel {ir_f:.0f}%")

    if blockers:
        status = "BLOCK"
    elif pending or local_st in ("missing", "queued"):
        status = "PENDING"
    elif critic == "DOWNGRADE" or (ir_f is not None and ir_f < INTEL_READINESS_WARN):
        status = "WARN"
    else:
        status = "PASS"
    next_action = (
        "Run broker diligence" if pending or local_st in ("missing", "queued")
        else "Resolve blockers" if blockers
        else "Send to Broker"
    )
    return {
        "status": status,
        "promote_ready": status == "PASS",
        "blockers": blockers,
        "next_action": next_action,
        "agents_pending": pending,
        "local_llm_status": local_st,
        "intel_readiness": ir_f,
        "critic_verdict": critic or None,
    }


def sync_proposal_reviews_from_watchlist(proposal_id: int) -> dict:
    """Backfill proposal_agent_reviews from completed watchlist jobs (proposal_review payload)."""
    row = _q("SELECT symbol, strategy_id FROM paper_trade_proposals WHERE id=%s", (proposal_id,), one=True) or {}
    sym = str(row.get("symbol") or "").upper()
    if not sym:
        return {"ok": False, "error": "proposal not found", "synced": []}

    jobs = _q(
        """SELECT j.requested_agent, r.recommendation, r.confidence, r.summary, r.model_used, j.completed_at
           FROM watchlist_agent_jobs j
           JOIN watchlist_agent_results r ON r.id = j.result_id
           WHERE j.symbol = %s AND j.status = 'completed'
             AND COALESCE(j.payload->>'proposal_id', '') = %s
           ORDER BY j.completed_at DESC NULLS LAST""",
        (sym, str(proposal_id)),
    ) or []

    seen: set[str] = set()
    synced: list[str] = []
    conn = _get_conn()
    cur = conn.cursor()
    try:
        for j in jobs:
            agent = str(j.get("requested_agent") or "").lower()
            if agent not in REQUIRED_AGENTS or agent in seen:
                continue
            seen.add(agent)
            rec = str(j.get("recommendation") or "").upper().strip()
            vote = WATCHLIST_REC_TO_VOTE.get(rec, "CAUTIOUS_TEST")
            conf_raw = j.get("confidence")
            try:
                conf_pct = int(round(float(conf_raw) * 100)) if conf_raw is not None else 50
            except (TypeError, ValueError):
                conf_pct = 50
            summary = str(j.get("summary") or "")[:500]
            model = j.get("model_used") or "watchlist_agent"
            cur.execute(
                """UPDATE proposal_agent_reviews SET
                       status = 'reviewed', vote = %s, confidence = %s, summary = %s,
                       reviewed_by_model = %s, reviewed_at = NOW()
                 WHERE proposal_id = %s AND agent_name = %s""",
                (vote, conf_pct, summary, model, proposal_id, agent),
            )
            if cur.rowcount == 0:
                cur.execute(
                    """INSERT INTO proposal_agent_reviews
                           (proposal_id, symbol, strategy_id, agent_name, role, status, vote,
                            confidence, summary, reviewed_by_model, reviewed_at)
                       VALUES (%s, %s, %s, %s, %s, 'reviewed', %s, %s, %s, %s, NOW())""",
                    (
                        proposal_id, sym, row.get("strategy_id"), agent, agent,
                        vote, conf_pct, summary, model,
                    ),
                )
            synced.append(agent)
        if synced:
            votes = _q(
                """SELECT vote FROM proposal_agent_reviews
                   WHERE proposal_id=%s AND agent_name = ANY(%s)""",
                (proposal_id, list(REQUIRED_AGENTS)),
            ) or []
            vote_vals = [str(v.get("vote") or "").upper() for v in votes]
            if any(v == "BLOCK" for v in vote_vals):
                agent_status = "BLOCKED"
            elif any(v in ("REJECT", "BLOCK") for v in vote_vals):
                agent_status = "REJECTED"
            elif all(v in ("APPROVE_TEST", "CAUTIOUS_TEST", "NOT_APPLICABLE") for v in vote_vals if v):
                agent_status = "REVIEWED"
            else:
                agent_status = "REVIEWED"
            cur.execute(
                "UPDATE paper_trade_proposals SET agent_review_status=%s WHERE id=%s",
                (agent_status, proposal_id),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        return {"ok": False, "error": str(e)[:160], "synced": synced}
    return {"ok": True, "synced": synced, "symbol": sym}


def advance_broker_diligence(proposal_id: int) -> dict:
    """Auto-run the next diligence steps (enrich queue, agents, LLM)."""
    actions: list[str] = []
    sync = sync_proposal_reviews_from_watchlist(proposal_id)
    if sync.get("synced"):
        actions.append("synced_watchlist_agents:" + ",".join(sync["synced"]))

    row = _proposal_intel_row(proposal_id)
    ir = row.get("intel_readiness")
    ir_f = float(ir) if ir is not None else 0.0

    if ir_f < INTEL_READINESS_WARN:
        try:
            import subprocess as sp
            root = Path(__file__).resolve().parent.parent
            sp.Popen(
                [str(root / ".venv/bin/python"), str(root / "scripts/proposal_enrichment_loop.py"),
                 "--run", "--proposal-id", str(proposal_id)],
                cwd=str(root), stdout=sp.DEVNULL, stderr=sp.DEVNULL,
            )
            actions.append("enrichment_queued")
        except Exception:
            pass

    if needs_oversight_queue(proposal_id):
        q = queue_oversight_jobs(proposal_id)
        if q.get("started"):
            actions.append("oversight_queued")

    if needs_cloud_oversight(proposal_id):
        cq = queue_cloud_oversight(proposal_id)
        if cq.get("queued"):
            actions.append("cloud_oversight_queued")

    try:
        import broker_trade_plan_gate as btpg
        tp_gate = btpg.assess_proposal_trade_plan(proposal_id)
        if not tp_gate.get("allowed"):
            import remediate_proposal_trade_plans as rtpr
            rem = rtpr.remediate_symbol(
                _get_conn(), str(row.get("symbol") or "").upper(),
                proposal_ids=[proposal_id],
            )
            if rem.get("cleared"):
                actions.append("trade_plan_remediated")
            elif rem.get("error"):
                actions.append(f"trade_plan_remediate_pending:{rem.get('error')}")
    except Exception:
        pass

    plan = build_promote_diligence_plan(proposal_id)
    return {
        "ok": True,
        "actions": actions,
        "message": "Diligence advanced" if actions else "No automatic steps needed — check plan",
        "plan": plan,
    }


def merge_evaluation_with_oversight(evaluation: dict, oversight: dict) -> dict:
    """Combine sizing/market evaluation with AI oversight (worst status wins)."""
    out = dict(evaluation or {})
    ov = oversight or {}
    out["oversight"] = ov
    ov_status = ov.get("status") or "PASS"
    cur = out.get("status") or "PASS"

    if ov_status == "BLOCK":
        out["status"] = "BLOCK"
        out["allowed"] = False
        out["violations"] = list(out.get("violations") or []) + list(ov.get("violations") or [])
    elif ov_status == "WARN" and cur == "PASS":
        out["status"] = "WARN"
        out["warnings"] = list(out.get("warnings") or []) + list(ov.get("warnings") or [])
    elif ov_status == "WARN":
        out["warnings"] = list(out.get("warnings") or []) + list(ov.get("warnings") or [])

    if ov.get("warnings") and out.get("status") != "BLOCK":
        out.setdefault("warnings", [])
        for w in ov["warnings"]:
            if w not in out["warnings"]:
                out["warnings"].append(w)
    return out


def _cli_run_cloud_oversight(proposal_id: int, *, timeout: int = 120) -> int:
    """CLI entry for background cloud review worker."""
    try:
        result = run_cloud_oversight(proposal_id, timeout=timeout)
        if not result.get("ok"):
            print(json.dumps(result, default=str))
            return 1
        print(json.dumps(result, default=str))
        return 0
    finally:
        _clear_cloud_inflight(proposal_id)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Broker promote AI oversight utilities")
    parser.add_argument("--run-cloud-oversight", type=int, metavar="PROPOSAL_ID")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if args.run_cloud_oversight:
        raise SystemExit(_cli_run_cloud_oversight(args.run_cloud_oversight, timeout=args.timeout))
    parser.print_help()
    raise SystemExit(1)