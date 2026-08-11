"""Phase 5 specialist shadow — Guardian (cash/IPS) + Ledger (Roth ladder) + Steph note.

Deterministic first. Ledger tax numbers from portfolio_retirement only
(Claude-only tax-lane policy — no DeepSeek for Roth/IRMAA math).

Each artifact:
  - SHADOW mode, READ_ONLY_ADVISORY
  - Sentinel deterministic review
  - Darwin scorecard line (local + optional cio darwin path)
"""
from __future__ import annotations

import fcntl
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME = PROJECT_ROOT / "data" / "runtime"
SHADOW_DIR = RUNTIME / "advisory_shadow"
ARTIFACTS_DIR = SHADOW_DIR / "artifacts"
SENTINEL_PATH = SHADOW_DIR / "sentinel_reviews.jsonl"
DARWIN_PATH = SHADOW_DIR / "darwin_scorecards.jsonl"
# Also feed platform CIO paths when present (non-fatal)
CIO_SENTINEL = PROJECT_ROOT / "data" / "cio" / "sentinel_reviews.jsonl"
CIO_DARWIN = PROJECT_ROOT / "data" / "cio" / "darwin_scorecards.jsonl"

IPS_MAX_POSITION_PCT = 8.0
MODEL_PORTFOLIO = PROJECT_ROOT / "config" / "model_portfolio.json"
HOLDINGS = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, default=str, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line)
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def _write_artifact(agent: str, payload: dict[str, Any]) -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    aid = payload.get("artifact_id") or str(uuid.uuid4())[:12]
    path = ARTIFACTS_DIR / f"{agent}_{aid}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _sentinel_review(artifact: dict[str, Any]) -> dict[str, Any]:
    """Deterministic Sentinel: structure + authority fence + no broker fields."""
    issues: list[str] = []
    if artifact.get("authority") != "READ_ONLY_ADVISORY":
        issues.append("authority_not_readonly")
    if artifact.get("mode") != "SHADOW":
        issues.append("mode_not_shadow")
    # Fence check: look for execution markers, not deny-list documentation.
    blob = json.dumps(
        {k: v for k, v in artifact.items() if k not in ("denied", "recommendation")},
        default=str,
    ).lower()
    for banned in ("broker_credential", "submit_order", "place_order", "api_key_live"):
        if banned in blob:
            issues.append(f"banned_token:{banned}")
    if not artifact.get("mandate"):
        issues.append("missing_mandate")
    if not artifact.get("findings"):
        issues.append("empty_findings")

    status = "PASS" if not issues else "FAIL"
    review = {
        "event_type": "SENTINEL_REVIEW",
        "timestamp": _now_iso(),
        "reviewer": "sentinel",
        "artifact_id": artifact.get("artifact_id"),
        "agent": artifact.get("agent"),
        "status": status,
        "issues": issues,
        "contradictions": 0 if status == "PASS" else len(issues),
    }
    _append_jsonl(SENTINEL_PATH, review)
    try:
        _append_jsonl(CIO_SENTINEL, review)
    except Exception:
        pass
    return review


def _darwin_score(artifact: dict[str, Any], sentinel: dict[str, Any]) -> dict[str, Any]:
    """Deterministic Darwin scorecard for a specialist artifact."""
    findings = artifact.get("findings") or []
    n = len(findings)
    severity = sum(1 for f in findings if f.get("severity") in ("high", "critical"))
    score = {
        "artifact_id": artifact.get("artifact_id"),
        "agent": artifact.get("agent"),
        "mandate": artifact.get("mandate"),
        "scored_at": _now_iso(),
        "dimensions": {
            "completeness": 1.0 if n >= 1 else 0.0,
            "severity_signal": min(1.0, severity / max(n, 1)),
            "sentinel_pass": 1.0 if sentinel.get("status") == "PASS" else 0.0,
            "readonly_fence": 1.0 if artifact.get("authority") == "READ_ONLY_ADVISORY" else 0.0,
        },
        "overall": None,
        "model_calls": 0,
        "cost_usd": 0.0,
    }
    dims = score["dimensions"]
    score["overall"] = round(sum(dims.values()) / len(dims), 3)
    entry = {
        "event_type": "DARWIN_SCORECARD",
        "timestamp": _now_iso(),
        "scorer": "darwin",
        "payload": score,
    }
    _append_jsonl(DARWIN_PATH, entry)
    try:
        _append_jsonl(CIO_DARWIN, entry)
    except Exception:
        pass
    return score


def guardian_cash_concentration(*, session_id: str = "", desk: dict | None = None) -> dict[str, Any]:
    """Guardian first mandate: cash concentration / IPS single-name breach."""
    findings: list[dict[str, Any]] = []
    cash_pct = cash_mv = total = None
    target_cash = 5.0

    try:
        mp = json.loads(MODEL_PORTFOLIO.read_text(encoding="utf-8"))
        cash_cfg = (mp.get("strategic_allocation") or {}).get("cash_and_equivalents") or {}
        if cash_cfg.get("target_pct") is not None:
            target_cash = float(cash_cfg["target_pct"])
        elif cash_cfg.get("target") is not None:
            target_cash = float(cash_cfg["target"])
    except Exception:
        pass

    try:
        h = json.loads(HOLDINGS.read_text(encoding="utf-8"))
        total = float(h.get("portfolio_total_value") or h.get("total_value") or 0)
        # cash from account summaries or cash positions
        cash_mv = 0.0
        for k, v in (h.get("account_summaries") or {}).items():
            if isinstance(v, dict):
                cash_mv += float(v.get("cash") or v.get("cash_balance") or 0)
        if cash_mv <= 0:
            for pos in h.get("holdings") or []:
                if str(pos.get("symbol") or "").upper() in ("CASH", "SPAXX", "FDRXX", "VMFXX"):
                    cash_mv += float(pos.get("market_value") or 0)
        if total > 0:
            cash_pct = 100.0 * cash_mv / total
    except Exception:
        pass

    # Also read allocation rows from desk if present
    if desk:
        rows = ((desk.get("data") or {}).get("rows") or [])
        for r in rows:
            if r.get("row_class") == "allocation" and "cash" in str(r.get("symbol") or "").lower():
                findings.append({
                    "type": "allocation_row",
                    "severity": "high",
                    "symbol": r.get("symbol"),
                    "verdict": str(getattr(r.get("verdict"), "value", r.get("verdict"))),
                    "rationale": (r.get("rationale") or "")[:240],
                    "market_value": r.get("market_value"),
                })
            # IPS single-name
            wp = r.get("weight_pct")
            if r.get("row_class") == "holding" and wp is not None and float(wp) > IPS_MAX_POSITION_PCT:
                findings.append({
                    "type": "ips_max_position",
                    "severity": "high" if float(wp) > 15 else "medium",
                    "symbol": r.get("symbol"),
                    "weight_pct": wp,
                    "ips_max": IPS_MAX_POSITION_PCT,
                    "rationale": f"{r.get('symbol')} at {wp}% exceeds IPS max {IPS_MAX_POSITION_PCT}%",
                })

    if cash_pct is not None and cash_pct > target_cash + 4.0:
        excess = cash_mv - (total * target_cash / 100.0) if total and cash_mv is not None else None
        findings.append({
            "type": "cash_concentration",
            "severity": "critical" if cash_pct > 30 else "high",
            "cash_pct": round(cash_pct, 2),
            "target_cash_pct": target_cash,
            "cash_mv": round(cash_mv or 0, 0),
            "excess_mv": round(excess, 0) if excess is not None else None,
            "rationale": (
                f"Cash at {cash_pct:.1f}% vs target {target_cash:.1f}%"
                + (f" (excess ~${excess:,.0f})" if excess else "")
            ),
        })

    if not findings:
        findings.append({
            "type": "no_material_breach",
            "severity": "info",
            "rationale": "No cash/IPS concentration breach detected from available state",
        })

    artifact = {
        "artifact_id": str(uuid.uuid4())[:12],
        "agent": "guardian",
        "display_name": "Guardian Risk",
        "mandate": "cash_concentration_ips",
        "mode": "SHADOW",
        "authority": "READ_ONLY_ADVISORY",
        "session_id": session_id,
        "ts": _now_iso(),
        "denied": ["broker.*", "order.*", "risk_policy.write", "2fa.*"],
        "model_policy": "deterministic_first; flash critique optional later",
        "inputs": {
            "cash_pct": cash_pct,
            "cash_mv": cash_mv,
            "total_value": total,
            "target_cash_pct": target_cash,
            "ips_max_position_pct": IPS_MAX_POSITION_PCT,
        },
        "findings": findings,
        "recommendation": (
            "Review idle cash deployment with Steph (advisory only). "
            "Trim single-name IPS breaches via existing proposal+2FA path — Guardian cannot execute."
        ),
        "tax_lane": "n/a",
    }
    path = _write_artifact("guardian", artifact)
    artifact["path"] = str(path)
    sentinel = _sentinel_review(artifact)
    darwin = _darwin_score(artifact, sentinel)
    artifact["sentinel"] = sentinel
    artifact["darwin"] = darwin
    return artifact


def ledger_roth_golden_window(*, session_id: str = "") -> dict[str, Any]:
    """Ledger first mandate: Roth conversion ladder toward Golden Window.

    Tax numbers ONLY from portfolio_retirement (deterministic). No DeepSeek.
    """
    findings: list[dict[str, Any]] = []
    roadmap: dict[str, Any] = {}
    state_dir = PROJECT_ROOT / "data" / "portfolios" / "state"
    try:
        from portfolio_retirement import build_retirement_roadmap
        portfolio: dict[str, Any] = {}
        hp = state_dir / "holdings.json"
        if hp.exists():
            portfolio = json.loads(hp.read_text(encoding="utf-8"))
        roadmap = build_retirement_roadmap(portfolio, state_dir) or {}
    except Exception as e:
        # Fallback: read cached roadmap
        rp = state_dir / "retirement_roadmap.json"
        if rp.exists():
            try:
                roadmap = json.loads(rp.read_text(encoding="utf-8"))
            except Exception:
                roadmap = {}
        if not roadmap:
            findings.append({
                "type": "data_gap",
                "severity": "high",
                "rationale": f"retirement roadmap unavailable: {type(e).__name__}",
            })

    gw = roadmap.get("golden_window") or {}
    key_dates = roadmap.get("key_dates") or {}
    accounts = roadmap.get("accounts") or {}
    ladder = roadmap.get("roth_ladder") or []

    if key_dates.get("years_to_golden") is not None:
        findings.append({
            "type": "golden_window_clock",
            "severity": "high" if float(key_dates.get("years_to_golden") or 99) < 5 else "medium",
            "years_to_golden": key_dates.get("years_to_golden"),
            "days_to_golden": key_dates.get("days_to_golden"),
            "start_age": gw.get("start_age"),
            "end_age": gw.get("end_age"),
            "rationale": (
                f"Golden window in ~{key_dates.get('years_to_golden')}y "
                f"(ages {gw.get('start_age')}–{gw.get('end_age')}); "
                f"optimal conversion ${gw.get('optimal_annual_conversion', 50000):,}/yr in window"
            ),
        })

    if accounts:
        findings.append({
            "type": "account_mix",
            "severity": "info",
            "roth": accounts.get("roth"),
            "traditional": accounts.get("traditional"),
            "roth_pct": accounts.get("roth_pct"),
            "rationale": (
                f"Roth ${accounts.get('roth', 0):,.0f} ({accounts.get('roth_pct')}%) / "
                f"Traditional ${accounts.get('traditional', 0):,.0f}"
            ),
        })

    # Next 3 ladder years
    near = [x for x in ladder if not x.get("golden")][:3]
    if near:
        findings.append({
            "type": "roth_ladder_near_term",
            "severity": "medium",
            "years": near,
            "rationale": (
                "Pre-window conversion plan (deterministic): "
                + ", ".join(f"{y.get('year')}=${y.get('conversion'):,}" for y in near)
            ),
        })

    golden_years = [x for x in ladder if x.get("golden")][:3]
    if golden_years:
        findings.append({
            "type": "roth_ladder_golden",
            "severity": "high",
            "years": golden_years,
            "rationale": (
                "In-window conversions step up (deterministic model): "
                + ", ".join(f"{y.get('year')}=${y.get('conversion'):,}" for y in golden_years)
            ),
        })

    if not findings:
        findings.append({
            "type": "no_ladder",
            "severity": "high",
            "rationale": "No Roth ladder data — operator should refresh retirement roadmap",
        })

    artifact = {
        "artifact_id": str(uuid.uuid4())[:12],
        "agent": "ledger",
        "display_name": "Ledger Tax",
        "mandate": "roth_conversion_golden_window",
        "mode": "SHADOW",
        "authority": "READ_ONLY_ADVISORY",
        "session_id": session_id,
        "ts": _now_iso(),
        "denied": ["broker.*", "order.*", "tax_filing.submit", "2fa.*"],
        "model_policy": "deterministic_retirement_roadmap_only",
        "tax_lane": "claude_only_numbers_via_portfolio_retirement",
        "deepseek_used": False,
        "findings": findings,
        "recommendation": (
            "Maintain pre-window conversion cadence; size up only inside Golden Window per roadmap. "
            "IRMAA/SSDI interactions require Claude tax lane / human review — Ledger does not execute."
        ),
        "source": "portfolio_retirement.build_retirement_roadmap",
    }
    path = _write_artifact("ledger", artifact)
    artifact["path"] = str(path)
    sentinel = _sentinel_review(artifact)
    darwin = _darwin_score(artifact, sentinel)
    artifact["sentinel"] = sentinel
    artifact["darwin"] = darwin
    return artifact


def steph_capital_deployment(*, session_id: str = "", desk: dict | None = None) -> dict[str, Any]:
    """Steph shadow note: idle cash deployment narrative (no rebalance.execute)."""
    findings: list[dict[str, Any]] = []
    cash_note = "Idle cash status unknown"
    if desk:
        for r in ((desk.get("data") or {}).get("rows") or []):
            if r.get("row_class") == "allocation" and "cash" in str(r.get("symbol") or "").lower():
                cash_note = (r.get("rationale") or "")[:300]
                findings.append({
                    "type": "cash_allocation",
                    "severity": "high",
                    "rationale": cash_note,
                    "verdict": str(getattr(r.get("verdict"), "value", r.get("verdict"))),
                })
    if not findings:
        findings.append({
            "type": "awaiting_operator",
            "severity": "medium",
            "rationale": (
                "Operator must declare whether ~cash excess is deliberate vs drift "
                "before capital-deployment narrative is actionable (plan decision #3)."
            ),
        })

    artifact = {
        "artifact_id": str(uuid.uuid4())[:12],
        "agent": "steph",
        "display_name": "Steph Wealth",
        "mandate": "capital_deployment_idle_cash",
        "mode": "SHADOW",
        "authority": "READ_ONLY_ADVISORY",
        "session_id": session_id,
        "ts": _now_iso(),
        "denied": ["rebalance.execute", "broker.*", "order.*"],
        "findings": findings,
        "recommendation": (
            "If cash is drift: stage IPS-aligned deployment plan into proposals queue. "
            "If deliberate: document buffer thesis. Steph cannot execute rebalance."
        ),
        "feeds_desk_synthesis": True,
    }
    path = _write_artifact("steph", artifact)
    artifact["path"] = str(path)
    sentinel = _sentinel_review(artifact)
    darwin = _darwin_score(artifact, sentinel)
    artifact["sentinel"] = sentinel
    artifact["darwin"] = darwin
    return artifact


def run_all_specialists(*, session_id: str = "", desk: dict | None = None) -> dict[str, Any]:
    guardian = guardian_cash_concentration(session_id=session_id, desk=desk)
    ledger = ledger_roth_golden_window(session_id=session_id)
    steph = steph_capital_deployment(session_id=session_id, desk=desk)

    contradictions = 0
    for a in (guardian, ledger, steph):
        if (a.get("sentinel") or {}).get("status") != "PASS":
            contradictions += int((a.get("sentinel") or {}).get("contradictions") or 1)

    return {
        "ok": contradictions == 0,
        "guardian": guardian,
        "ledger": ledger,
        "steph": steph,
        "contradictions": contradictions,
        "darwin_scored": 3,
        "sentinel_reviews": 3,
        "deepseek_on_tax_lane": False,
    }
