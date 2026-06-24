"""report_oversight.py — Claude cloud oversight pass for analyst prospectuses.

ADVISORY ONLY. Never a broker action. Runs AFTER the report JSON is assembled, BEFORE export:

  1. Free dual-lane sanity (Grok :8645 + ChatGPT :8646 via the existing OAuth proxies) —
     each lane critiques the assembled report against a live data packet.
  2. Claude oversight (metered Anthropic lane, model resolved from config — NOT hardcoded) —
     senior arbiter that returns a verdict + machine-applicable fixes + an analyst overlay.
  3. Deterministic fix application + meta.claude_oversight stamp.

Cost gate (hard): free lanes run whenever oversight is requested; the metered Claude lane runs
ONLY when explicitly requested (operator / --claude-oversight) or when REPORT_CLAUDE_OVERSIGHT is
enabled AND a trigger fires (free lane flagged a fabrication/contradiction, or a BUY/ADD holding on
the monthly cadence). If the Claude lane is down it degrades to the dual free-lane verdict and never
blocks the report.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Model resolution order: explicit report override → shared escalation model → lane default.
# Resolved at call-time from env only; never hardcode a model id here.
def _claude_model() -> str:
    return (
        os.getenv("REPORT_CLAUDE_MODEL")
        or os.getenv("CLAUDE_ESCALATION_MODEL")
        or os.getenv("CRITICAL_CLOUD_MODEL")
        or ""  # empty → let the lane config supply its default
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v) if v is not None else d
    except (TypeError, ValueError):
        return d


# ───────────────────────── data packet ─────────────────────────
def build_data_packet(report: dict) -> dict:
    """Extract the live, checkable facts so a reviewer can detect fabrication / staleness."""
    meta = report.get("meta") or {}
    kpis = meta.get("kpis") or {}
    secs = {s.get("id"): s for s in (report.get("sections") or [])}

    intel = secs.get("intelligence_view") or {}
    risk = secs.get("risk_assessment") or {}
    ap = secs.get("analyst_predictions") or {}
    tech = secs.get("technical_analysis") or {}
    peer = secs.get("peer_comparison") or {}
    news = secs.get("news_catalysts") or {}
    hermes = secs.get("hermes_research") or {}
    action = secs.get("action_plan") or {}
    rmx = risk.get("metrics") or {}
    # Price levels referenced by the action plan ARE derived from price/ATR/SMA/target — expose them
    # so they are verifiable rather than read as fabricated.
    price_levels = {
        "current_price": kpis.get("price"),
        "valid_low_support": rmx.get("valid_low"),
        "valid_high": rmx.get("valid_high"),
        "do_not_chase": round(_f(kpis.get("price")) * 1.03, 2) if kpis.get("price") else None,
        "target_mean": (ap.get("metrics") or {}).get("target_mean"),
        "reward_risk": rmx.get("reward_risk"),
        "derivation": "add-zone = valid_low(support)..price; do-not-chase = price×1.03; target = street mean",
    }
    return {
        "symbol": meta.get("symbol"),
        "generated_at": meta.get("generated_at"),
        "price": kpis.get("price"),
        "recommendation": kpis.get("recommendation"),
        "thesis_status": kpis.get("thesis_status"),
        "unrealized_pnl_pct": kpis.get("unrealized_pnl_pct"),
        "portfolio_pct": kpis.get("portfolio_pct"),
        # these are the GROUND-TRUTH values the prose is derived from — provided so the
        # reviewer verifies rather than flags computed specifics as fabricated.
        "risk_metrics": risk.get("metrics"),
        "analyst_metrics": ap.get("metrics"),
        "price_levels": price_levels,
        "technical_metrics": tech.get("metrics"),
        "peer_metrics": peer.get("metrics"),
        "peer_rows": peer.get("bullets"),
        "news_headlines": news.get("bullets"),
        "hermes_notes": hermes.get("bullets"),
        "hermes_metrics": hermes.get("metrics"),
        "confidence_displayed": kpis.get("confidence"),
        "confidence_source": kpis.get("confidence_source"),
        "confidence_raw_before_discounts": kpis.get("confidence_raw"),
        "confidence_adjustments_applied": kpis.get("confidence_adjustments"),
        "dual_lane_consensus": intel.get("dual_lane"),
        "synthesis_age_days": intel.get("synthesis_age_days"),
        "agents_suppressed": intel.get("agents_suppressed"),
        "agent_panel": [
            {"agent": a.get("agent"), "rec": a.get("recommendation"), "weight": a.get("weight"),
             "accuracy_pct": a.get("accuracy_pct")}
            for a in (intel.get("agents") or [])
        ],
        "note_to_reviewer": (
            "All numeric specifics above ARE the source data. The report legitimately DERIVES values from "
            "them: add-zone = price×0.97..price, do-not-chase = price×1.03, peer rank, calibration-weighted "
            "for/against tallies, and the IMPLIED Buy/Hold/Sell split (modeled from the consensus mean, "
            "explicitly labeled 'implied'). These derivations are NOT fabrications. Flag 'fabrications' ONLY "
            "for a value that CONTRADICTS this packet or has no basis in it; flag 'stale_or_contradictory' "
            "only for genuine internal contradictions. Do not flag a number merely because the packet does "
            "not restate it verbatim."
        ),
        "section_ids": list(secs.keys()),
    }


_CRITIQUE_SCHEMA = (
    '{"fabrications":["..."],"stale_or_contradictory":["..."],'
    '"unsupported_claims":["..."],"missing_required":["..."],'
    '"section_grades":{"section_id":"A-F"}}'
)


def _extract_json(text: str) -> dict:
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        # tolerate trailing commas / minor noise
        cleaned = re.sub(r",\s*([}\]])", r"\1", m.group(0))
        try:
            return json.loads(cleaned)
        except Exception:
            return {}


def _section_text(report: dict, *, limit: int = 5000) -> str:
    out = []
    for s in report.get("sections") or []:
        out.append(f"## {s.get('title') or s.get('id')}\n{s.get('content') or ''}")
        for b in (s.get("bullets") or [])[:4]:
            out.append(f"  - {b}")
    return "\n".join(out)[:limit]


# ───────────────────────── free lanes ─────────────────────────
def _lane_available(lane: str) -> bool:
    try:
        import llm_lane
        return bool(llm_lane.available(lane))
    except Exception:
        return False


def _call_lane(lane: str, prompt: str, *, timeout: int = 120, model: str = "") -> str:
    """Resolve and call a lane via the shared researcher (handles grok/chatgpt/claude)."""
    try:
        import hermes_external_researcher as her
        cfg = her.LANE_CFG.get(lane) or {}
        mdl = model or cfg.get("default_model")
        return her.call_external(lane, mdl, prompt, max_tokens=1600) or ""
    except Exception:
        # free-lane fallback via llm_lane proxy (grok/chatgpt only)
        if lane in ("grok", "chatgpt"):
            try:
                import llm_lane
                return llm_lane.generate(prompt, lane=lane, timeout=timeout, model=model or None)
            except Exception:
                return ""
        return ""


def free_lane_critique(report: dict, packet: dict, lane: str, *, timeout: int = 120) -> dict:
    """One free OAuth lane returns a structured critique of the assembled report."""
    if not _lane_available(lane):
        return {"lane": lane, "available": False}
    prompt = (
        "You are an INDEPENDENT analyst-desk reviewer auditing a per-ticker research report before "
        "publication. Compare the report PROSE against the LIVE DATA PACKET (ground truth). Flag only "
        "real problems. Reply with STRICT JSON, no prose:\n" + _CRITIQUE_SCHEMA + "\n\n"
        f"LIVE DATA PACKET (ground truth):\n{json.dumps(packet, default=str)[:3000]}\n\n"
        f"REPORT PROSE:\n{_section_text(report)}\n"
    )
    raw = _call_lane(lane, prompt, timeout=timeout)
    parsed = _extract_json(raw)
    return {
        "lane": lane,
        "available": True,
        "fabrications": parsed.get("fabrications") or [],
        "stale_or_contradictory": parsed.get("stale_or_contradictory") or [],
        "unsupported_claims": parsed.get("unsupported_claims") or [],
        "missing_required": parsed.get("missing_required") or [],
        "section_grades": parsed.get("section_grades") or {},
    }


def _free_lane_flagged(critiques: list[dict]) -> bool:
    for c in critiques:
        if c.get("fabrications") or c.get("stale_or_contradictory"):
            return True
    return False


# ───────────────────────── Claude arbiter ─────────────────────────
_CLAUDE_SCHEMA = (
    '{"verdict":"PUBLISH|PUBLISH_WITH_FIXES|BLOCK",'
    '"fixes":[{"section":"id","action":"...","detail":"..."}],'
    '"analyst_note":"2-3 sentence senior overlay",'
    '"confidence_check":"does stated confidence match evidence?"}'
)


def claude_oversight(report: dict, packet: dict, free_critiques: list[dict], *, timeout: int = 150) -> dict:
    """Senior Claude arbiter. Resolves model from config. Advisory only."""
    if not _lane_available("claude"):
        return {"verdict": "SKIPPED", "skipped": "lane_down", "available": False}
    prompt = (
        "You are the SENIOR analyst overseeing a junior desk's per-ticker research report. You receive "
        "the report, the live data packet (ground truth), and two independent free-lane critiques. "
        "Decide whether it can publish.\n"
        "VERDICT RUBRIC (apply strictly):\n"
        "- BLOCK only for a genuine DATA-INTEGRITY failure: a stated number/claim that CONTRADICTS the "
        "  packet, or a figure with no possible basis in it. A value the report legitimately DERIVES from "
        "  packet data (add-zone, do-not-chase ceiling, peer rank, weighted tallies, implied rating split, "
        "  realized vol, thesis band) is NOT a fabrication — verify it against `price_levels`/`derivation`.\n"
        "- PUBLISH_WITH_FIXES for prose/disclosure/tone improvements or minor omissions.\n"
        "- PUBLISH if clean. Do NOT BLOCK merely because a free lane (esp. the smaller model) listed a "
        "  computed number it could not independently recompute. Treat free-lane flags as leads to verify, "
        "  not as verdicts. Do NOT invent data.\n"
        "Reply with STRICT JSON only:\n" + _CLAUDE_SCHEMA + "\n\n"
        f"LIVE DATA PACKET:\n{json.dumps(packet, default=str)[:2600]}\n\n"
        f"FREE-LANE CRITIQUES:\n{json.dumps(free_critiques, default=str)[:2000]}\n\n"
        f"REPORT PROSE:\n{_section_text(report, limit=4200)}\n"
    )
    raw = _call_lane("claude", prompt, timeout=timeout, model=_claude_model())
    parsed = _extract_json(raw)
    verdict = str(parsed.get("verdict") or "").upper()
    if verdict not in ("PUBLISH", "PUBLISH_WITH_FIXES", "BLOCK"):
        verdict = "PUBLISH_WITH_FIXES" if parsed else "SKIPPED"
    return {
        "verdict": verdict,
        "available": True,
        "fixes": parsed.get("fixes") or [],
        "analyst_note": parsed.get("analyst_note") or "",
        "confidence_check": parsed.get("confidence_check") or "",
        "model": _claude_model() or "lane_default",
    }


# ───────────────────────── apply fixes ─────────────────────────
def apply_fixes(report: dict, oversight: dict) -> int:
    """Deterministically apply the SAFE subset of fixes (advisory overlays + flags).

    We never let the model silently rewrite numbers — the deterministic builder already
    governs the data. Applied: analyst-note overlay, per-section oversight flags, BLOCK warning.
    """
    applied = 0
    secs = {s.get("id"): s for s in (report.get("sections") or [])}

    note = (oversight.get("analyst_note") or "").strip()
    if note:
        exec_sec = secs.get("executive_summary")
        if exec_sec is not None:
            exec_sec.setdefault("callouts", [])
            exec_sec["callouts"].insert(0, {"label": "Senior Analyst Overlay", "text": note})
            applied += 1

    for fx in oversight.get("fixes") or []:
        sid = fx.get("section")
        sec = secs.get(sid)
        if sec is not None:
            sec.setdefault("oversight_flags", []).append(
                {"action": fx.get("action"), "detail": fx.get("detail")}
            )
            applied += 1

    if oversight.get("verdict") == "BLOCK":
        exec_sec = secs.get("executive_summary")
        if exec_sec is not None:
            exec_sec.setdefault("callouts", []).insert(
                0, {"label": "⚠ Oversight: HOLD FOR REVIEW",
                    "text": oversight.get("confidence_check") or "Senior oversight blocked publication pending review."}
            )
            applied += 1
    return applied


# ───────────────────────── orchestration ─────────────────────────
def _should_run_claude(report: dict, free_critiques: list[dict], *, requested: bool | None,
                       cadence: str | None) -> tuple[bool, str]:
    if requested is True:
        return True, "explicit_request"
    if requested is False:
        return False, "explicitly_disabled"
    # requested is None → env-gated heuristic
    if not _env_bool("REPORT_CLAUDE_OVERSIGHT", False):
        return False, "env_disabled"
    if _free_lane_flagged(free_critiques):
        return True, "free_lane_flagged"
    rec = str(((report.get("meta") or {}).get("kpis") or {}).get("recommendation") or "").upper()
    if cadence == "monthly" and any(k in rec for k in ("BUY", "ADD")):
        return True, "monthly_buy_holding"
    return False, "no_trigger"


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _audit_log(symbol: str, oversight: dict, free: list[dict]) -> None:
    """Best-effort append to the LLM audit (advisory)."""
    try:
        from db_adapter import _execute
        _execute(
            """INSERT INTO ai_oversight_audit
                 (created_at, surface, symbol, verdict, model, free_lanes, payload_json)
               VALUES (NOW(), 'analyst_report', %s, %s, %s, %s, %s::jsonb)""",
            (symbol, oversight.get("verdict"), oversight.get("model"),
             ",".join(c["lane"] for c in free if c.get("available")),
             json.dumps({"oversight": oversight, "free": free}, default=str)),
            fetch=None,
        )
    except Exception:
        # audit table may not exist in every env — never block the report on audit
        pass


def oversee_report(
    report: dict,
    *,
    claude_oversight: bool | None = None,
    cadence: str | None = None,
    timeout: int = 150,
) -> dict:
    """Run the oversight pipeline and stamp meta.claude_oversight. Mutates + returns report."""
    meta = report.setdefault("meta", {})
    symbol = meta.get("symbol")
    packet = build_data_packet(report)

    free: list[dict] = []
    for lane in ("grok", "chatgpt"):
        try:
            free.append(free_lane_critique(report, packet, lane, timeout=min(timeout, 120)))
        except Exception as e:
            free.append({"lane": lane, "available": False, "error": str(e)[:160]})

    run_claude, reason = _should_run_claude(report, free, requested=claude_oversight, cadence=cadence)
    oversight = None
    if run_claude:
        oversight = claude_oversight_call(report, packet, free, timeout=timeout)
        if oversight.get("verdict") == "SKIPPED" or not oversight.get("available"):
            # Claude lane down → never block; degrade to free-lane verdict.
            reason = "claude_lane_down"
            oversight = None
    if oversight is None:
        flagged = _free_lane_flagged(free)
        oversight = {
            "verdict": "PUBLISH_WITH_FIXES" if flagged else "PUBLISH",
            "available": any(c.get("available") for c in free),
            "fixes": [],
            "analyst_note": "",
            "confidence_check": "",
            "model": "free_lanes_only",
            "skipped": "lane_down(claude)" if reason == "claude_lane_down" else None,
        }

    fixes_applied = apply_fixes(report, oversight)
    stamp = {
        "verdict": oversight.get("verdict"),
        "model": oversight.get("model"),
        "ts": _now_iso(),
        "fixes_applied": fixes_applied,
        "claude_ran": run_claude,
        "claude_gate_reason": reason,
        "free_lanes": [
            {"lane": c.get("lane"), "available": c.get("available"),
             "fabrications": len(c.get("fabrications") or []),
             "stale": len(c.get("stale_or_contradictory") or [])}
            for c in free
        ],
        "confidence_check": oversight.get("confidence_check"),
    }
    if oversight.get("skipped"):
        stamp["skipped"] = oversight["skipped"]
    meta["claude_oversight"] = stamp
    _audit_log(symbol, oversight, free)
    return report


def oversight_skip_is_lane_down(reason: str) -> bool:
    return reason in ("lane_down",)


# alias so the public call name reads clearly while avoiding shadowing the module fn above
def claude_oversight_call(report: dict, packet: dict, free: list[dict], *, timeout: int = 150) -> dict:
    return claude_oversight(report, packet, free, timeout=timeout)


def run_oversight_only(symbol: str, report_type: str = "symbol_holding", **kw) -> dict:
    """Re-run oversight on an existing living prospectus JSON without rebuilding it."""
    from report_lineage import canonical_export_paths
    p = canonical_export_paths(symbol, report_type)["json"]
    if not p.exists():
        return {"ok": False, "error": f"no existing report for {symbol}"}
    report = json.loads(p.read_text())
    oversee_report(report, **kw)
    p.write_text(json.dumps(report, indent=2, default=str))
    return {"ok": True, "symbol": symbol, "oversight": (report.get("meta") or {}).get("claude_oversight")}
