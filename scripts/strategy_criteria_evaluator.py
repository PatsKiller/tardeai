#!/usr/bin/env python3
"""strategy_criteria_evaluator.py — DETERMINISTIC machine evaluation of strategy YAML entry criteria.

Until now the rich criteria in config/strategies/*.yaml (entry_criteria, screen_filters,
setup_qualification, minimum_evidence) were interpreted by LLMs/operator — unrepeatable and untestable.
This module evaluates them as code, identically every time, for BOTH live proposal gating and the
point-in-time signal simulator (the backtesting unlock).

Semantics:
  - entry_criteria: list of {id, metric, operator, value} → evaluated with the operator table below.
  - screen_filters / setup_qualification: dicts of min_X / max_X / bool keys → mapped to gte/lte/eq.
  - minimum_evidence.required: metrics that MUST be present — missing => fail (fail-closed on evidence).
  - other missing metrics => 'skipped' (counted in coverage, never auto-fail) — honest about data gaps.
Handles the schema drift between files (swing_breakout uses setup_qualification; momentum_scalp uses
entry_criteria). Read-only; no DB writes.

CLI:
  .venv/bin/python scripts/strategy_criteria_evaluator.py --self-test
  .venv/bin/python scripts/strategy_criteria_evaluator.py --strategy momentum_scalp \
      --metrics '{"rvol": 6.2, "price": 5.1, "float_m": 18, "catalyst_verified": true}'
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STRAT_DIR = ROOT / "config" / "strategies"

_OPS = {
    "eq":  lambda got, want: got == want,
    "ne":  lambda got, want: got != want,
    "gte": lambda got, want: _num(got) is not None and _num(got) >= _num(want),
    "lte": lambda got, want: _num(got) is not None and _num(got) <= _num(want),
    "gt":  lambda got, want: _num(got) is not None and _num(got) > _num(want),
    "lt":  lambda got, want: _num(got) is not None and _num(got) < _num(want),
    "between": lambda got, want: (_num(got) is not None and isinstance(want, (list, tuple))
                                  and _num(want[0]) <= _num(got) <= _num(want[1])),
    "in":  lambda got, want: got in (want if isinstance(want, (list, tuple)) else [want]),
}

# metric aliases: YAML names vs live metric-dict names
_ALIASES = {
    "relative_volume": "rvol", "rel_volume": "rvol",
    "float_shares": "float_m", "float": "float_m",
    "gap_percent": "gap_pct", "gap": "gap_pct",
    "change_percent": "change_pct",
}


def _num(x):
    try:
        if isinstance(x, bool):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _get_metric(metrics: dict, name: str):
    name = (name or "").strip()
    if name in metrics:
        return metrics[name], True
    alias = _ALIASES.get(name)
    if alias and alias in metrics:
        return metrics[alias], True
    # reverse alias
    for k, v in _ALIASES.items():
        if v == name and k in metrics:
            return metrics[k], True
    return None, False


def load_strategy(strategy_id: str) -> dict:
    import yaml
    p = STRAT_DIR / f"{strategy_id}.yaml"
    if not p.exists():
        p = STRAT_DIR / "_archive" / f"{strategy_id}.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def _norm_criteria(cfg: dict) -> list:
    """Normalize all criteria sections into [{id, metric, operator, value, section}]."""
    out = []
    for c in (cfg.get("entry_criteria") or []):
        if isinstance(c, dict) and c.get("metric") and c.get("operator"):
            out.append({"id": c.get("id") or c["metric"], "metric": c["metric"],
                        "operator": c["operator"], "value": c.get("value"), "section": "entry_criteria"})
    for section in ("screen_filters", "setup_qualification"):
        d = cfg.get(section) or {}
        if not isinstance(d, dict):
            continue
        for k, v in d.items():
            if isinstance(v, bool):
                out.append({"id": k, "metric": k, "operator": "eq", "value": v, "section": section})
            elif isinstance(v, (int, float)):
                if k.startswith("min_"):
                    out.append({"id": k, "metric": k[4:], "operator": "gte", "value": v, "section": section})
                elif k.startswith("max_"):
                    out.append({"id": k, "metric": k[4:], "operator": "lte", "value": v, "section": section})
                # bare numerics (e.g. volume_dry_up_threshold) need context — expose as gte by convention only
                # when the simulator passes the matching metric; otherwise they'll be 'skipped'.
                else:
                    out.append({"id": k, "metric": k, "operator": "gte", "value": v, "section": section})
    return out


def evaluate(strategy_id: str, metrics: dict, cfg: dict = None) -> dict:
    """Deterministically evaluate a metrics dict against a strategy's criteria.

    Returns {pass, fail_ids, results[], evaluated, skipped, coverage, missing_required}."""
    cfg = cfg or load_strategy(strategy_id)
    if not cfg:
        return {"pass": False, "error": f"strategy {strategy_id} not found", "results": []}
    crit = _norm_criteria(cfg)
    required = ((cfg.get("minimum_evidence") or {}).get("required")) or []
    missing_required = [r for r in required if not _get_metric(metrics, r)[1]]
    results, fails, skipped = [], [], 0
    for c in crit:
        got, present = _get_metric(metrics, c["metric"])
        if not present or got is None:
            results.append({**c, "got": None, "ok": None, "status": "skipped"})
            skipped += 1
            continue
        op = _OPS.get(str(c["operator"]).lower())
        if not op:
            results.append({**c, "got": got, "ok": None, "status": "unknown_operator"})
            skipped += 1
            continue
        ok = bool(op(got, c["value"]))
        results.append({**c, "got": got, "ok": ok, "status": "pass" if ok else "FAIL"})
        if not ok:
            fails.append(c["id"])
    evaluated = len(crit) - skipped
    coverage = round(evaluated / len(crit), 2) if crit else 0.0
    passed = (not fails) and (not missing_required) and evaluated > 0
    return {"pass": passed, "strategy_id": strategy_id, "fail_ids": fails,
            "missing_required": missing_required, "evaluated": evaluated, "skipped": skipped,
            "coverage": coverage, "results": results}


def _self_test() -> int:
    cases = [
        # momentum_scalp: rvol>=5, price band, float cap, catalyst_verified
        ("momentum_scalp", {"rvol": 6.2, "price": 5.1, "float_m": 18, "catalyst_verified": True,
                            "price_data": 1, "gap_pct": 12, "rvol_data": 1, "float_data": 1,
                            "trade_plan": 1, "stop_defined": 1}, True),
        ("momentum_scalp", {"rvol": 2.0, "price": 5.1, "float_m": 18, "catalyst_verified": True,
                            "price_data": 1}, False),                       # rvol too low
        ("momentum_scalp", {"rvol": 6.2, "price": 5.1, "float_m": 500, "catalyst_verified": True,
                            "price_data": 1}, False),                       # float too big
        # swing_breakout: setup_qualification section (schema drift) — base length + breakout volume
        ("swing_breakout", {"rvol": 2.0, "price": 25, "float_m": 100, "base_days": 30,
                            "breakout_volume_ratio": 2.0, "score": 40, "price_data": 1,
                            "base_duration": 30, "volume_pattern": 1, "breakout_level": 24.5,
                            "stop_below_base": 1, "trade_plan": 1}, True),
        ("swing_breakout", {"rvol": 2.0, "price": 25, "float_m": 100, "base_days": 5,
                            "breakout_volume_ratio": 2.0, "score": 40, "price_data": 1,
                            "base_duration": 5}, False),                    # base too short
    ]
    failures = 0
    for sid, metrics, expect in cases:
        r = evaluate(sid, metrics)
        ok = r.get("pass") == expect
        print(f"  [{'PASS' if ok else 'FAIL'}] {sid} expect={expect} got={r.get('pass')} "
              f"fails={r.get('fail_ids')} missing_req={r.get('missing_required')} coverage={r.get('coverage')}")
        if not ok:
            failures += 1
    print(f"  self-test: {len(cases)-failures}/{len(cases)} passed")
    return failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy")
    ap.add_argument("--metrics", help="JSON metrics dict")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        raise SystemExit(_self_test())
    if not a.strategy or not a.metrics:
        ap.error("--strategy and --metrics required (or --self-test)")
    print(json.dumps(evaluate(a.strategy, json.loads(a.metrics)), indent=2, default=str))


if __name__ == "__main__":
    main()
