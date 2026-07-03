"""Phase D — closed-loop evaluation: watchlist promotion gate + system impact."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from lib.hermes_outcome_bus.bus import load_outcome_bus_trend

from .closed_loop_evaluation_store import (
    append_closed_loop_eval_audit,
    load_closed_loop_evaluations,
    new_closed_loop_evaluation_id,
    save_closed_loop_evaluations,
)
from .evaluation_engine import _metric_delta, _parse_day, _slice_windows, _window_avg

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
WATCHLIST_AUDIT_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_watchlist_lifecycle_audit.jsonl"


def _load_lifecycle_config() -> dict[str, Any]:
    try:
        import yaml
        path = PROJECT_ROOT / "config" / "hermes_watchlist_lifecycle.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {"evaluation": {"enabled": True}}


def load_watchlist_audit_events(path: Path | None = None, limit: int = 5000) -> list[dict[str, Any]]:
    path = path or WATCHLIST_AUDIT_PATH
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(__import__("json").loads(line))
            except Exception:
                continue
    except Exception:
        return []
    return rows[-limit:]


def _gate_activation_day(events: list[dict[str, Any]]) -> str | None:
    for e in sorted(events, key=lambda x: str(x.get("at") or "")):
        if e.get("action") == "blocked_promotion":
            return str(e["at"])[:10]
        if e.get("action") == "lifecycle_tick" and int(e.get("blocked_promotion_count") or 0) > 0:
            return str(e["at"])[:10]
    return None


def _blocked_symbol_stats(events: list[dict[str, Any]]) -> tuple[set[str], list[dict[str, Any]]]:
    syms: set[str] = set()
    rows: list[dict[str, Any]] = []
    for e in events:
        if e.get("action") != "blocked_promotion":
            continue
        sym = str(e.get("symbol") or "").upper().strip()
        if sym:
            syms.add(sym)
        rows.append(e)
    return syms, rows


def fetch_blocked_symbols_promotion_outcomes(
    cur,
    symbols: set[str],
    lookback_days: int = 90,
) -> dict[str, Any]:
    """Promotion hit rate for symbols that were blocked by the health gate."""
    if not cur or not symbols:
        return {"samples": 0, "hit_rate": None, "symbols": []}
    try:
        sym_list = sorted(symbols)
        cur.execute(
            """SELECT UPPER(symbol) AS sym,
                      count(*) FILTER (WHERE subject_type = 'promotion' AND verdict = 'hit') AS hits,
                      count(*) FILTER (WHERE subject_type = 'promotion') AS total
               FROM hermes_outcome_ledger
               WHERE UPPER(symbol) = ANY(%s)
                 AND emitted_at > NOW() - make_interval(days => %s)
               GROUP BY UPPER(symbol)""",
            (sym_list, lookback_days),
        )
        per_sym: list[dict[str, Any]] = []
        total_hits = 0
        total_n = 0
        for sym, hits, total in cur.fetchall():
            t = int(total or 0)
            h = int(hits or 0)
            if t <= 0:
                continue
            per_sym.append({
                "symbol": str(sym),
                "promotion_hits": h,
                "promotion_total": t,
                "promotion_hit_rate": round(h / t, 3),
            })
            total_hits += h
            total_n += t
        hit_rate = round(total_hits / total_n, 3) if total_n else None
        return {
            "samples": total_n,
            "hit_rate": hit_rate,
            "symbols": per_sym,
            "lookback_days": lookback_days,
        }
    except Exception:
        return {"samples": 0, "hit_rate": None, "symbols": []}


def _gate_verdict(
    hr_delta: float | None,
    blocked_hit_rate: float | None,
    blocked_samples: int,
    before_n: int,
    after_n: int,
    cfg: dict[str, Any],
) -> tuple[str, str, str, float]:
    ev = cfg.get("evaluation") or {}
    helped_hr = float(ev.get("helped_hit_rate_delta", 0.02))
    hurt_hr = float(ev.get("hurt_hit_rate_delta", -0.05))
    weak_blocked_rate = float(ev.get("weak_blocked_hit_rate_ceiling", 0.40))
    min_blocked = int(ev.get("min_blocked_samples", 3))
    min_days = int(ev.get("min_window_days", 7))

    impact = 0.0
    if hr_delta is not None:
        impact += hr_delta * 10 * 0.45
    if blocked_hit_rate is not None and blocked_samples >= min_blocked:
        if blocked_hit_rate <= weak_blocked_rate:
            impact += 0.25
        elif blocked_hit_rate >= 0.55:
            impact -= 0.20

    if before_n < min_days or after_n < min_days:
        return "insufficient_data", "low", "needs_more_data", round(impact, 4)

    if impact >= 0.15 or (hr_delta is not None and hr_delta >= helped_hr):
        return "helped", "medium", "keep_gate", round(impact, 4)
    if impact <= -0.15 or (hr_delta is not None and hr_delta <= hurt_hr):
        return "hurt", "medium", "review_gate", round(impact, 4)
    return "neutral", "medium", "monitor", round(impact, 4)


def evaluate_watchlist_promotion_gate(
    series: list[dict[str, Any]],
    audit_events: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
    cur=None,
) -> dict[str, Any]:
    """Before/after system metrics + blocked-symbol counterfactual."""
    cfg = cfg or _load_lifecycle_config()
    ev_cfg = cfg.get("evaluation") or {}
    if not ev_cfg.get("enabled", True):
        return {"ok": False, "reason": "evaluation_disabled"}

    blocked_syms, blocked_rows = _blocked_symbol_stats(audit_events)
    activation = _gate_activation_day(audit_events)
    ticks_with_blocks = sum(
        1 for e in audit_events
        if e.get("action") == "lifecycle_tick" and int(e.get("blocked_promotion_count") or 0) > 0
    )

    lookback = int((cfg.get("promotion_success") or {}).get("lookback_days", 90))
    blocked_outcomes = fetch_blocked_symbols_promotion_outcomes(cur, blocked_syms, lookback)

    if not activation and not blocked_rows:
        return {
            "id": new_closed_loop_evaluation_id(),
            "subject": "watchlist_promotion_health_gate",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "verdict": "insufficient_data",
            "confidence": "low",
            "recommendation": "needs_more_data",
            "impact_score": 0.0,
            "metrics": {
                "blocked_promotion_events": {"count": 0},
                "blocked_symbol_promo_hit_rate": blocked_outcomes,
            },
            "reasoning": (
                "No blocked_promotion audit events yet. Run governor dry-run; "
                "weak-health symbols with edge≥hot_min should log blocked_promotion rows."
            ),
            "gate_active": False,
        }

    before_days = int(ev_cfg.get("before_window_days", 14))
    after_days = int(ev_cfg.get("after_window_days", 14))
    min_after = int(ev_cfg.get("min_days_after_activation", 7))
    activation_day = activation or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    act_dt = _parse_day(activation_day)
    days_since = (datetime.now(timezone.utc) - act_dt).days if act_dt else 0

    before, after = _slice_windows(series, activation_day, before_days, after_days)
    hr_before = _window_avg(before, "hit_rate_promotions")
    hr_after = _window_avg(after, "hit_rate_promotions")
    mat_before = _window_avg(before, "maturity_composite_score")
    mat_after = _window_avg(after, "maturity_composite_score")
    hr_metric = _metric_delta(hr_before, hr_after)
    mat_metric = _metric_delta(mat_before, mat_after)

    verdict, confidence, recommendation, impact = _gate_verdict(
        hr_metric.get("delta"),
        blocked_outcomes.get("hit_rate"),
        int(blocked_outcomes.get("samples") or 0),
        len(before),
        len(after) if days_since >= min_after else 0,
        cfg,
    )

    if days_since < min_after:
        verdict = "insufficient_data"
        recommendation = "needs_more_data"
        confidence = "low"

    reasoning_parts = [
        f"Gate active since {activation_day} ({days_since}d ago)",
        f"blocked events={len(blocked_rows)} ticks_with_blocks={ticks_with_blocks}",
    ]
    if hr_metric.get("delta") is not None:
        reasoning_parts.append(f"promotion hit rate Δ{hr_metric['delta']:+.1%}")
    if blocked_outcomes.get("hit_rate") is not None:
        reasoning_parts.append(
            f"blocked-symbol promo hit rate {blocked_outcomes['hit_rate']:.1%} (n={blocked_outcomes['samples']})"
        )
    reasoning = "; ".join(reasoning_parts) + f". Impact {impact:+.3f} → {verdict}."

    return {
        "id": new_closed_loop_evaluation_id(),
        "subject": "watchlist_promotion_health_gate",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "gate_activation_day": activation_day,
        "days_since_activation": days_since,
        "gate_active": True,
        "windows": {
            "before": {
                "start": (act_dt - timedelta(days=before_days)).strftime("%Y-%m-%d") if act_dt else None,
                "end": activation_day,
                "days": len(before),
            },
            "after": {
                "start": (act_dt + timedelta(days=1)).strftime("%Y-%m-%d") if act_dt else None,
                "end": (act_dt + timedelta(days=after_days)).strftime("%Y-%m-%d") if act_dt else None,
                "days": len(after),
            },
        },
        "metrics": {
            "hit_rate_promotions": hr_metric,
            "maturity_composite_score": mat_metric,
            "blocked_promotion_events": {"count": len(blocked_rows), "unique_symbols": len(blocked_syms)},
            "blocked_symbol_promo_hit_rate": blocked_outcomes,
        },
        "impact_score": impact,
        "verdict": verdict,
        "confidence": confidence,
        "recommendation": recommendation,
        "reasoning": reasoning,
        "promote_floor": float((cfg.get("health_thresholds") or {}).get("promote_floor", 62)),
    }


def _build_summary(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    by_verdict: dict[str, int] = {}
    by_rec: dict[str, int] = {}
    for e in evaluations:
        by_verdict[e.get("verdict", "unknown")] = by_verdict.get(e.get("verdict"), 0) + 1
        by_rec[e.get("recommendation", "unknown")] = by_rec.get(e.get("recommendation"), 0) + 1
    latest = evaluations[-1] if evaluations else None
    return {
        "count": len(evaluations),
        "by_verdict": by_verdict,
        "by_recommendation": by_rec,
        "latest_evaluation_at": latest.get("evaluated_at") if latest else None,
        "latest_verdict": latest.get("verdict") if latest else None,
    }


def run_closed_loop_evaluation_cycle(
    lookback_days: int | None = None,
    conn=None,
) -> dict[str, Any]:
    """Evaluate watchlist promotion gate; read-only recommendations."""
    cfg = _load_lifecycle_config()
    ev_cfg = cfg.get("evaluation") or {}
    if not ev_cfg.get("enabled", True):
        return {"ok": False, "reason": "evaluation_disabled"}

    window = lookback_days or int(ev_cfg.get("lookback_days", 60))
    trend = load_outcome_bus_trend(days=window)
    series = trend.get("series") or []
    audit_events = load_watchlist_audit_events()

    cur = None
    if conn is not None:
        cur = conn.cursor()
    else:
        try:
            from db_adapter import _get_conn, USE_DB
            if USE_DB:
                conn = _get_conn()
                cur = conn.cursor()
        except Exception:
            pass

    evaluation = evaluate_watchlist_promotion_gate(series, audit_events, cfg, cur=cur)

    store = load_closed_loop_evaluations()
    subject = evaluation.get("subject")
    existing = [
        e for e in (store.get("evaluations") or [])
        if e.get("subject") == subject and e.get("gate_activation_day") == evaluation.get("gate_activation_day")
    ]
    new_evals = list(store.get("evaluations") or [])
    if not existing:
        new_evals.append(evaluation)
        append_closed_loop_eval_audit({
            "action": "evaluated",
            "evaluation_id": evaluation.get("id"),
            "subject": subject,
            "verdict": evaluation.get("verdict"),
        })
    else:
        evaluation = existing[-1]

    payload = {
        "version": "closed-loop-eval-v1",
        "evaluations": new_evals[-50:],
        "summary": _build_summary(new_evals),
        "latest": evaluation,
    }
    save_closed_loop_evaluations(payload)

    return {
        "ok": True,
        "lookback_days": window,
        "evaluation": evaluation,
        "summary": payload["summary"],
        "note": "Read-only — gate recommendations do not auto-change config",
    }


def closed_loop_evaluation_status() -> dict[str, Any]:
    store = load_closed_loop_evaluations()
    return {
        "ok": True,
        "summary": store.get("summary") or {},
        "evaluations": (store.get("evaluations") or [])[-10:],
        "latest": store.get("latest") or ((store.get("evaluations") or [])[-1] if store.get("evaluations") else None),
        "updated_at": store.get("updated_at"),
    }