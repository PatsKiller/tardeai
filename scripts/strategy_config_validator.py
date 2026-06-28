#!/usr/bin/env python3
"""strategy_config_validator.py — P0-3: detect lifecycle config drift in strategy YAMLs.

`intraday_execution` is the AUTHORITATIVE source of truth for an intraday strategy's
trading window, proposal TTL, fast-path account/mode, and max price drift. This validator
fails when other blocks (entry_criteria, screen_filters, lifecycle, auto_disqualifiers)
contradict it.

Reusable:
    from strategy_config_validator import validate_strategy_config
    result = validate_strategy_config("momentum_scalp")   # -> {ok, errors, warnings, ...}

CLI:
    python3 scripts/strategy_config_validator.py momentum_scalp
    python3 scripts/strategy_config_validator.py --all
    python3 scripts/strategy_config_validator.py --all --json
Exit 0 = consistent. Non-zero = a drift error was found.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRAT_DIR = PROJECT_ROOT / "config" / "strategies"
_SKIP_STEMS = {"strategy_schema", "recommendation_schema", "shared_risk_rules"}


def _hhmm_to_minutes(s: str) -> int | None:
    """'12:00' -> 720 minutes from midnight."""
    try:
        h, m = str(s).strip().split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _entry_criteria(cfg: dict, cid: str) -> dict | None:
    for c in cfg.get("entry_criteria") or []:
        if isinstance(c, dict) and c.get("id") == cid:
            return c
    return None


def _load_cfg(strategy_id: str) -> dict | None:
    import yaml
    p = STRAT_DIR / f"{strategy_id}.yaml"
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text()) or {}


def validate_strategy_config(strategy_id: str, cfg: dict | None = None) -> dict:
    """Validate one strategy's lifecycle-config consistency. Returns a structured result.

    Pure: pass `cfg` to validate an in-memory dict without touching disk (used by tests).
    """
    if cfg is None:
        cfg = _load_cfg(strategy_id)
    errors: list[dict] = []
    warnings: list[dict] = []
    if cfg is None:
        return {"ok": False, "strategy_id": strategy_id,
                "errors": [{"code": "CONFIG_MISSING", "detail": f"{strategy_id}.yaml not found"}],
                "warnings": []}

    tf_class = str(cfg.get("timeframe_class") or "").upper()
    ix = cfg.get("intraday_execution") or {}
    is_intraday = tf_class == "INTRADAY" or bool(ix)

    # Only intraday strategies carry the authoritative intraday_execution block.
    if not is_intraday:
        return {"ok": True, "strategy_id": strategy_id, "is_intraday": False,
                "errors": [], "warnings": [], "authoritative": "n/a (non-intraday)"}

    if not ix:
        errors.append({"code": "MISSING_INTRADAY_EXECUTION",
                       "detail": "intraday strategy has no intraday_execution block (source of truth)"})
        return {"ok": False, "strategy_id": strategy_id, "is_intraday": True,
                "errors": errors, "warnings": warnings}

    sf = cfg.get("screen_filters") or {}
    lifecycle = cfg.get("lifecycle") or {}

    # ── 1. FLOAT consistency: entry_criteria.FLOAT_LOW must match screen_filters.max_float_m ──
    max_float = sf.get("max_float_m")
    fl = _entry_criteria(cfg, "FLOAT_LOW")
    if max_float is not None and fl is not None and fl.get("value") is not None:
        try:
            if float(fl["value"]) != float(max_float):
                errors.append({"code": "FLOAT_THRESHOLD_CONFLICT",
                               "detail": f"entry_criteria.FLOAT_LOW={fl['value']} != "
                                         f"screen_filters.max_float_m={max_float}"})
        except (TypeError, ValueError):
            pass

    # ── 2. TRADING WINDOW consistency: entry_criteria.ENTRY_WINDOW (minutes) == intraday_execution end ──
    win = ix.get("trading_window_et") or {}
    end_min = _hhmm_to_minutes(win.get("end"))
    ew = _entry_criteria(cfg, "ENTRY_WINDOW")
    if end_min is not None and ew is not None and ew.get("value") is not None:
        try:
            if int(ew["value"]) != int(end_min):
                errors.append({"code": "ENTRY_WINDOW_CONFLICT",
                               "detail": f"entry_criteria.ENTRY_WINDOW={ew['value']}min != "
                                         f"intraday_execution.trading_window_et.end={win.get('end')} "
                                         f"({end_min}min)"})
        except (TypeError, ValueError):
            pass

    # ── 3. TTL consistency: lifecycle must not contradict intraday_execution.proposal_ttl_minutes ──
    ttl = ix.get("proposal_ttl_minutes")
    if ttl is not None:
        ttl = int(ttl)
        # legacy hours field that disagrees with the minutes TTL is a hard conflict
        if "proposal_expiry_hours" in lifecycle:
            hrs = lifecycle.get("proposal_expiry_hours")
            try:
                if float(hrs) * 60 != float(ttl):
                    errors.append({"code": "TTL_CONFLICT",
                                   "detail": f"lifecycle.proposal_expiry_hours={hrs} "
                                             f"({float(hrs)*60:.0f}min) != "
                                             f"intraday_execution.proposal_ttl_minutes={ttl}"})
            except (TypeError, ValueError):
                pass
        if "proposal_expiry_minutes" in lifecycle:
            try:
                if int(lifecycle["proposal_expiry_minutes"]) != ttl:
                    errors.append({"code": "TTL_CONFLICT",
                                   "detail": f"lifecycle.proposal_expiry_minutes="
                                             f"{lifecycle['proposal_expiry_minutes']} != "
                                             f"intraday_execution.proposal_ttl_minutes={ttl}"})
            except (TypeError, ValueError):
                pass
        # advisory: lifecycle should declare the source of truth
        if lifecycle and "source_of_truth" not in lifecycle:
            warnings.append({"code": "TTL_SOURCE_UNDECLARED",
                             "detail": "lifecycle should set source_of_truth: "
                                       "intraday_execution.proposal_ttl_minutes"})
    else:
        errors.append({"code": "MISSING_TTL",
                       "detail": "intraday_execution.proposal_ttl_minutes is required (source of truth)"})

    # ── 4. HUMAN-FACING window language must match the authoritative window (P0-2) ──
    # Stale prompt/context/description text (e.g. "13:30 ET" when the window is 06:00–12:00)
    # misleads the LLM and operator even though the numeric gates are correct.
    if end_min is not None:
        import re as _re
        end_hhmm = win.get("end")
        # Times referenced in human-facing fields that are NOT the configured window edges are stale.
        allowed_times = {str(win.get("start")), str(end_hhmm)}

        def _scan_text(obj, path):
            if isinstance(obj, str):
                for t in _re.findall(r"\b([0-2]?\d:[0-5]\d)\b", obj):
                    if t not in allowed_times:
                        errors.append({"code": "STALE_WINDOW_TEXT",
                                       "detail": f"human-facing field {path} references '{t}' but the "
                                                 f"authoritative window is {win.get('start')}–{end_hhmm} ET"})
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    _scan_text(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    _scan_text(v, f"{path}[{i}]")

        for field in ("prompt_context", "purpose"):
            if field in cfg:
                _scan_text(cfg[field], field)

    # ── 5. Paper fast-path vs live-approval semantics (P0-1, momentum_scalp) ──
    # Paper sample-collection may be deterministic/no-approval, but LIVE operator-approval / 2FA
    # language must remain intact, promotion must still need human review, and momentum_scalp
    # stays TESTING. A config that requires paper approval for sample collection is a regression.
    ptr = cfg.get("paper_trade_rules") or {}
    vg = cfg.get("validation_gate") or {}
    lep = cfg.get("live_execution_policy") or {}
    is_paper_fast_path = (ptr.get("submit_mode") == "paper_only_fast_path"
                          or strategy_id == "momentum_scalp")
    if is_paper_fast_path:
        if vg.get("paper_approval_required_for_sample_collection") is True:
            errors.append({"code": "PAPER_APPROVAL_REQUIRED_REGRESSION",
                           "detail": "paper sample collection must be deterministic/no-approval "
                                     "(paper_approval_required_for_sample_collection must be false)"})
        if ptr.get("paper_approval_required") is True:
            errors.append({"code": "PAPER_APPROVAL_REQUIRED_REGRESSION",
                           "detail": "paper_trade_rules.paper_approval_required must be false for the fast path"})
        if vg.get("human_approval_required_for_promotion") is False:
            errors.append({"code": "PROMOTION_APPROVAL_WEAKENED",
                           "detail": "human_approval_required_for_promotion must remain true"})
        # LIVE operator-confirmation / 2FA language must be present and intact.
        if lep and (lep.get("operator_confirmation_required") is False
                    or lep.get("two_factor_required") is False
                    or lep.get("autonomous_live_trading") is True):
            errors.append({"code": "LIVE_APPROVAL_WEAKENED",
                           "detail": "live_execution_policy must keep operator_confirmation_required + "
                                     "two_factor_required true and autonomous_live_trading false"})
        if strategy_id == "momentum_scalp" and str(cfg.get("status", "")).upper() != "TESTING":
            errors.append({"code": "NOT_TESTING",
                           "detail": f"momentum_scalp must remain TESTING (got status={cfg.get('status')})"})

    return {
        "ok": not errors,
        "strategy_id": strategy_id,
        "is_intraday": True,
        "authoritative": "intraday_execution",
        "resolved": {
            "max_float_m": max_float,
            "trading_window_et": win,
            "proposal_ttl_minutes": ttl,
            "fast_path_account": ix.get("fast_path_account"),
            "fast_path_mode": ("fast_path_auto_approve" if ix.get("fast_path_auto_approve") else "manual"),
            "max_price_drift_pct": ix.get("max_price_drift_pct"),
        },
        "errors": errors,
        "warnings": warnings,
    }


def validate_all() -> dict:
    results = []
    for p in sorted(STRAT_DIR.glob("*.yaml")):
        if p.stem in _SKIP_STEMS:
            continue
        results.append(validate_strategy_config(p.stem))
    ok = all(r["ok"] for r in results)
    return {"ok": ok, "count": len(results),
            "failed": [r["strategy_id"] for r in results if not r["ok"]],
            "results": results}


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate strategy lifecycle-config consistency (P0-3)")
    ap.add_argument("strategy_id", nargs="?", help="single strategy id (e.g. momentum_scalp)")
    ap.add_argument("--all", action="store_true", help="validate every strategy yaml")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.all or not args.strategy_id:
        report = validate_all()
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            for r in report["results"]:
                tag = "OK  " if r["ok"] else "FAIL"
                print(f"  [{tag}] {r['strategy_id']}"
                      + ("" if r["ok"] else "  -> " + "; ".join(e["code"] for e in r["errors"])))
            print(f"\n  {report['count'] - len(report['failed'])}/{report['count']} consistent")
        return 0 if report["ok"] else 1

    result = validate_strategy_config(args.strategy_id)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        if result["ok"]:
            print(f"  [OK] {args.strategy_id}: lifecycle config consistent")
        else:
            print(f"  [FAIL] {args.strategy_id}:")
            for e in result["errors"]:
                print(f"    - {e['code']}: {e['detail']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
