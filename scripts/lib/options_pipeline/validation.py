"""validation.py — paper-outcome ledger + validation-gate reporting (Stage B).

Records closed paper outcomes for paper-only options strategies (deep_itm_call
first) into options_paper_outcomes (migrations/2026_07_05_options_paper_outcomes.sql)
and computes progress against the strategy config's validation_gate
(min_closed_paper_trades / min_profit_factor / min_win_rate / min_calendar_months).

ADVISORY ONLY — HARD INVARIANTS (test-enforced by source inspection):
  • This module NEVER enables live execution. There is no write path that touches
    execution flags, strategy status, or the strategy YAML. The config's
    execution block keeps its paper-only guarantees regardless of gate progress.
  • A met gate is reported as "gate met — operator decision required
    (human_approval_required)". Nothing is flipped anywhere; the operator decides.
  • The only registry write is update_registry_maturity(): trades_taken count +
    a metadata.paper_validation advisory blob on strategy_registry. It never
    touches the registry's lifecycle, activation, or eligibility columns.
  • No broker / order / 2FA imports (same forbidden-imports sweep as Stage A).

Metric definitions (documented so the gate math is auditable):
  • n_closed        = all recorded outcomes (win + loss + scratch)
  • win_rate        = wins / (wins + losses)  — scratches are WR-neutral
  • profit_factor   = gross profit / gross loss over ALL outcomes' pnl
                      (None until both a win and a loss exist; inf-free: with
                       profits and zero losses it reports None + note, honest)
  • calendar_months = span from earliest closed_at to now, in avg-month units
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

STRATEGY_ID = "deep_itm_call"
SUPPORTED_STRATEGIES = (STRATEGY_ID,)
VALID_OUTCOMES = ("win", "loss", "scratch")
AVG_MONTH_DAYS = 30.44

# Default gate — overridden by the strategy YAML's validation_gate when present.
DEFAULT_GATE: Dict[str, Any] = {
    "min_closed_paper_trades": 30,
    "min_win_rate": 0.55,
    "min_profit_factor": 1.3,
    "min_calendar_months": 3,
    "human_approval_required": True,
}

Executor = Callable[..., Any]  # (sql, params=None, fetch=None) -> rows | True | None


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if x != x else x  # NaN guard


def _default_executor() -> Executor:
    from db_adapter import _execute
    return _execute


def _parse_ts(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# ── outcome recording ────────────────────────────────────────────────────────

def record_outcome(
    proposal_id: str,
    *,
    outcome: str,
    strategy_id: str = STRATEGY_ID,
    symbol: str = "",
    pnl: Optional[float] = None,
    entry_debit: Optional[float] = None,
    exit_value: Optional[float] = None,
    pnl_r: Optional[float] = None,
    opened_at: Optional[str] = None,
    closed_at: Optional[str] = None,
    exit_reason: str = "",
    notes: str = "",
    meta: Optional[dict] = None,
    executor: Optional[Executor] = None,
) -> dict:
    """Record one closed paper outcome (upsert on proposal_id — re-records correct).

    Honest-input checks: outcome must be win/loss/scratch and, when pnl is
    supplied, must not contradict it (a 'win' with negative pnl is refused).
    """
    if not proposal_id:
        return {"ok": False, "error": "proposal_id required"}
    oc = (outcome or "").strip().lower()
    if oc not in VALID_OUTCOMES:
        return {"ok": False, "error": f"outcome must be one of {list(VALID_OUTCOMES)}"}
    if strategy_id not in SUPPORTED_STRATEGIES:
        return {"ok": False, "error": f"unsupported strategy_id '{strategy_id}' "
                                      f"(supported: {list(SUPPORTED_STRATEGIES)})"}
    if pnl is not None:
        p = _f(pnl)
        if oc == "win" and p < 0:
            return {"ok": False, "error": f"outcome 'win' contradicts pnl {p:.2f}"}
        if oc == "loss" and p > 0:
            return {"ok": False, "error": f"outcome 'loss' contradicts pnl {p:.2f}"}

    ex = executor or _default_executor()
    res = ex(
        """INSERT INTO options_paper_outcomes
             (proposal_id, strategy_id, symbol, opened_at, closed_at,
              entry_debit, exit_value, pnl, pnl_r, outcome, exit_reason, notes, meta)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
           ON CONFLICT (proposal_id) DO UPDATE SET
             strategy_id=EXCLUDED.strategy_id,
             symbol=EXCLUDED.symbol,
             opened_at=COALESCE(EXCLUDED.opened_at, options_paper_outcomes.opened_at),
             closed_at=EXCLUDED.closed_at,
             entry_debit=EXCLUDED.entry_debit,
             exit_value=EXCLUDED.exit_value,
             pnl=EXCLUDED.pnl,
             pnl_r=EXCLUDED.pnl_r,
             outcome=EXCLUDED.outcome,
             exit_reason=EXCLUDED.exit_reason,
             notes=EXCLUDED.notes,
             meta=EXCLUDED.meta,
             updated_at=NOW()""",
        (
            proposal_id, strategy_id, (symbol or "").upper() or None,
            opened_at, closed_at or _now().isoformat(),
            entry_debit, exit_value, pnl, pnl_r, oc,
            (exit_reason or "")[:80] or None, (notes or "")[:500] or None,
            json.dumps(meta or {}, default=str),
        ),
    )
    if res is None:
        return {"ok": False, "error": "db unavailable — outcome NOT recorded"}
    return {"ok": True, "proposal_id": proposal_id, "strategy_id": strategy_id,
            "outcome": oc}


def fetch_outcomes(strategy_id: str = STRATEGY_ID,
                   executor: Optional[Executor] = None) -> List[dict]:
    ex = executor or _default_executor()
    rows = ex(
        """SELECT proposal_id, strategy_id, symbol, opened_at, closed_at,
                  entry_debit, exit_value, pnl, pnl_r, outcome, exit_reason, recorded_at
           FROM options_paper_outcomes
           WHERE strategy_id = %s
           ORDER BY closed_at NULLS LAST, recorded_at""",
        (strategy_id,), fetch="all",
    )
    return [dict(r) for r in rows] if rows else []


# ── gate math (pure — unit-testable without a DB) ────────────────────────────

def compute_gate_metrics(outcomes: List[dict], *, now: Optional[datetime] = None) -> dict:
    """n / win-rate / profit-factor / calendar-month span over recorded outcomes."""
    n = len(outcomes)
    wins = sum(1 for o in outcomes if (o.get("outcome") or "").lower() == "win")
    losses = sum(1 for o in outcomes if (o.get("outcome") or "").lower() == "loss")
    scratches = n - wins - losses

    gross_profit = sum(_f(o.get("pnl")) for o in outcomes if _f(o.get("pnl")) > 0)
    gross_loss = sum(-_f(o.get("pnl")) for o in outcomes if _f(o.get("pnl")) < 0)

    win_rate = round(wins / (wins + losses), 4) if (wins + losses) else None
    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 4)
        pf_note = ""
    elif gross_profit > 0:
        profit_factor = None
        pf_note = "no losing trades yet — profit factor undefined until a loss exists"
    else:
        profit_factor = None
        pf_note = "no P/L recorded yet"

    closes = sorted(d for d in (_parse_ts(o.get("closed_at")) for o in outcomes) if d)
    if closes:
        months = round((_now(now) - closes[0]).total_seconds() / 86400.0 / AVG_MONTH_DAYS, 2)
    else:
        months = 0.0

    return {
        "n_closed": n, "wins": wins, "losses": losses, "scratches": scratches,
        "win_rate": win_rate,
        "profit_factor": profit_factor, "profit_factor_note": pf_note,
        "gross_profit": round(gross_profit, 2), "gross_loss": round(gross_loss, 2),
        "net_pnl": round(gross_profit - gross_loss, 2),
        "calendar_months": months,
        "first_closed_at": closes[0].isoformat() if closes else None,
        "last_closed_at": closes[-1].isoformat() if closes else None,
    }


def evaluate_gate(metrics: dict, gate: Optional[dict] = None) -> dict:
    """Per-check pass/fail vs the validation gate. Missing metrics fail honestly."""
    g = dict(DEFAULT_GATE)
    g.update(gate or {})
    checks = [
        {"id": "min_closed_paper_trades",
         "required": g["min_closed_paper_trades"], "actual": metrics.get("n_closed", 0),
         "pass": metrics.get("n_closed", 0) >= int(g["min_closed_paper_trades"])},
        {"id": "min_win_rate",
         "required": g["min_win_rate"], "actual": metrics.get("win_rate"),
         "pass": metrics.get("win_rate") is not None
                 and metrics["win_rate"] >= float(g["min_win_rate"])},
        {"id": "min_profit_factor",
         "required": g["min_profit_factor"], "actual": metrics.get("profit_factor"),
         "pass": metrics.get("profit_factor") is not None
                 and metrics["profit_factor"] >= float(g["min_profit_factor"])},
        {"id": "min_calendar_months",
         "required": g["min_calendar_months"], "actual": metrics.get("calendar_months", 0),
         "pass": _f(metrics.get("calendar_months")) >= float(g["min_calendar_months"])},
    ]
    met = all(c["pass"] for c in checks)
    if met:
        message = ("gate met — operator decision required "
                   "(human_approval_required; nothing is auto-enabled)")
    else:
        failing = [c["id"] for c in checks if not c["pass"]]
        message = (f"gate not met — {metrics.get('n_closed', 0)}"
                   f"/{g['min_closed_paper_trades']} closed paper outcomes; "
                   f"failing: {', '.join(failing)}")
    return {"gate": g, "checks": checks, "gate_met": met, "message": message,
            "advisory_only": True}


def _load_gate_config(strategy_id: str) -> dict:
    """validation_gate + execution echo from the strategy YAML (read-only)."""
    try:
        from strategy_config_loader import load_strategy_config
        cfg = load_strategy_config(strategy_id) or {}
    except Exception:
        cfg = {}
    return {
        "gate": cfg.get("validation_gate") or dict(DEFAULT_GATE),
        "status": cfg.get("status") or "UNVALIDATED",
        "paper_only": bool(cfg.get("paper_only", True)),
        "execution": cfg.get("execution") or {"paper_allowed": True, "live_allowed": False},
        "display_name": cfg.get("display_name") or strategy_id,
        "discovery_ref": cfg.get("discovery_ref") or {},
    }


def validation_status(strategy_id: str = STRATEGY_ID,
                      *,
                      executor: Optional[Executor] = None,
                      outcomes: Optional[List[dict]] = None,
                      now: Optional[datetime] = None) -> dict:
    """Full advisory report: outcomes → metrics → gate verdict. Never enables anything."""
    if strategy_id not in SUPPORTED_STRATEGIES:
        return {"ok": False, "error": f"unsupported strategy_id '{strategy_id}'"}
    cfg = _load_gate_config(strategy_id)
    rows = outcomes if outcomes is not None else fetch_outcomes(strategy_id, executor)
    metrics = compute_gate_metrics(rows, now=now)
    verdict = evaluate_gate(metrics, cfg["gate"])
    return {
        "ok": True,
        "strategy_id": strategy_id,
        "display_name": cfg["display_name"],
        "lifecycle_status": cfg["status"],
        "paper_only": cfg["paper_only"],
        "execution": cfg["execution"],   # read-only echo — live stays operator-gated
        "discovery_ref": cfg["discovery_ref"],
        "metrics": metrics,
        **verdict,
        "progress_label": f"paper validation {metrics['n_closed']}"
                          f"/{verdict['gate']['min_closed_paper_trades']}",
        "generated_at": _now(now).isoformat(),
    }


# ── registry maturity (advisory blob only — no lifecycle/eligibility writes) ─

def update_registry_maturity(strategy_id: str = STRATEGY_ID,
                             *,
                             executor: Optional[Executor] = None,
                             status_report: Optional[dict] = None) -> dict:
    """Mirror the advisory validation report onto strategy_registry.

    Writes ONLY trades_taken (count of closed paper outcomes) and a
    metadata.paper_validation blob. Deliberately never touches the registry's
    lifecycle, activation, or eligibility columns — gate progress is information
    for the operator, not a switch.
    """
    report = status_report or validation_status(strategy_id, executor=executor)
    if not report.get("ok"):
        return report
    blob = {
        "n_closed": report["metrics"]["n_closed"],
        "win_rate": report["metrics"]["win_rate"],
        "profit_factor": report["metrics"]["profit_factor"],
        "calendar_months": report["metrics"]["calendar_months"],
        "gate_met": report["gate_met"],
        "message": report["message"],
        "advisory_only": True,
        "updated_at": report["generated_at"],
    }
    ex = executor or _default_executor()
    res = ex(
        """UPDATE strategy_registry
           SET trades_taken = %s,
               metadata = COALESCE(metadata, '{}'::jsonb)
                          || jsonb_build_object('paper_validation', %s::jsonb),
               updated_at = NOW()
           WHERE strategy_type = %s""",
        (blob["n_closed"], json.dumps(blob, default=str), strategy_id),
    )
    if res is None:
        return {"ok": False, "error": "db unavailable — registry not updated"}
    return {"ok": True, "strategy_id": strategy_id, "paper_validation": blob}
