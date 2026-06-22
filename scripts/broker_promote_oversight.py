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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REQUIRED_AGENTS = ("maria", "risk_agent", "steph")
BLOCK_VOTES = frozenset({"BLOCK"})
WARN_VOTES = frozenset({"REJECT", "CAUTIOUS_TEST", "WAIT_FOR_DATA"})
CLOUD_CACHE_HOURS = int(os.getenv("BROKER_CLOUD_OVERSIGHT_CACHE_HOURS", "24"))
REQUIRE_CLOUD = os.getenv("BROKER_REQUIRE_CLOUD_OVERSIGHT", "0") == "1"
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


def _lane_availability() -> dict:
    out = {"grok": False, "chatgpt": False}
    try:
        import cloud_review
        for lane in ("grok", "chatgpt"):
            out[lane] = bool(cloud_review.available(lane))
    except Exception:
        pass
    return out


def _fetch_agent_reviews(proposal_id: int) -> list[dict]:
    rows = _q(
        """SELECT agent_name, status, vote, confidence, summary, reviewed_by_model, reviewed_at
           FROM proposal_agent_reviews WHERE proposal_id=%s ORDER BY agent_name""",
        (proposal_id,),
    ) or []
    return [
        {
            "agent": r.get("agent_name"),
            "status": r.get("status"),
            "vote": r.get("vote"),
            "confidence": float(r["confidence"]) if r.get("confidence") is not None else None,
            "summary": (r.get("summary") or "")[:300],
            "model": r.get("reviewed_by_model"),
            "reviewed_at": str(r.get("reviewed_at") or "")[:19] or None,
        }
        for r in rows
    ]


def _fetch_local_llm(proposal_id: int) -> dict:
    prop = _q(
        """SELECT local_llm_review_status, llm_review_status, agent_review_status,
                  symbol, strategy_id, proposed_entry, proposed_stop, proposed_target1, proposed_rr,
                  catalyst, catalyst_verified
           FROM paper_trade_proposals WHERE id=%s""",
        (proposal_id,), one=True,
    ) or {}
    analysis = _q(
        """SELECT model_used, narrative_source, summary, approve_case, reject_case, confidence
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
        "thesis": preview or _build_thesis_fallback(prop),
    }


def _build_thesis_fallback(prop: dict) -> str:
    parts = []
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


def run_cloud_oversight(proposal_id: int, *, timeout: int = 120) -> dict:
    """Run Grok+ChatGPT second opinion on the local thesis. Persists cache row."""
    local = _fetch_local_llm(proposal_id)
    thesis = (local.get("thesis") or "").strip()
    if not thesis:
        return {"ok": False, "error": "No local thesis to review — run AI Review on paper proposal first"}

    context = {
        "proposal_id": proposal_id,
        "symbol": local.get("symbol"),
        "strategy": local.get("strategy_id"),
        "local_llm_status": local.get("status"),
        "local_model": local.get("model"),
        "agent_review_status": local.get("agent_review_status"),
        "note": "Broker promote oversight — validate thesis before live queue",
    }
    try:
        import cloud_review
        result = cloud_review.review(
            "broker_promote_oversight",
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
        intel = bpi.get_intel_packet(proposal_id)
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
    }


def evaluate_oversight(proposal_id: int, *, cloud: dict | None = None) -> dict:
    """PASS | WARN | BLOCK oversight verdict for broker promote."""
    snap = get_oversight_snapshot(proposal_id)
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
    elif cloud_status in ("not_run", "unknown", ""):
        if REQUIRE_CLOUD:
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

    return {
        "status": status,
        "allowed": allowed,
        "violations": violations,
        "warnings": warnings,
        "intel_diligence": intel_dd,
        "promote_ready": allowed and status == "PASS",
        **snap,
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