"""ExpectationPolicy@v1 — every decision states what would prove it wrong.

Operator-approved 2026-10-03 (Policy Review P1). ~19,800 of ~20,000 outcome
checkpoints were OBSERVE/HOLD/WAIT with no direction, so the belief writer
could score almost nothing. An expectation records, per decision, what the
call implies relative to a benchmark over a horizon.

Source is always explicit:
  STATED          the producer stated the expectation itself
  POLICY_DEFAULT  derived from the action by the reviewed rule table in
                  config/expectation_policy.json — never presented as the
                  agent's own claim

Advisory only (READ_ONLY_ADVISORY, MBI=0): an expectation is a measurement
contract, never an order, size or stop.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

SCHEMA = "DecisionExpectation@v1"
SCORE_SCHEMA = "ExpectationScore@v1"
SOURCE_STATED = "STATED"
SOURCE_POLICY_DEFAULT = "POLICY_DEFAULT"
DIRECTIONS = frozenset({"UP", "DOWN", "FLAT_VS_BENCHMARK", "WITHIN_BAND"})
STATUS_SCORED = "SCORED"
STATUS_PENDING_DATA = "PENDING_DATA"

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "expectation_policy.json"
_CACHE: dict[str, Any] = {"key": None, "doc": None}


def load_policy(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path) if path else CONFIG_PATH
    try:
        st = p.stat()
        key = (str(p), st.st_size, st.st_mtime_ns)
    except OSError:
        return {}
    if _CACHE["key"] == key and _CACHE["doc"] is not None:
        return _CACHE["doc"]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    _CACHE["key"], _CACHE["doc"] = key, doc
    return doc


def _num(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _stated(stated: Any, policy: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not isinstance(stated, dict):
        return None
    direction = str(stated.get("direction") or "").strip().upper()
    if direction not in DIRECTIONS:
        return None
    horizon = _num(stated.get("horizon_days")) or _num(policy.get("default_horizon_days"))
    band = _num(stated.get("band_pct"))
    if direction in {"WITHIN_BAND", "FLAT_VS_BENCHMARK"} and band is None:
        band = _num(policy.get("default_band_pct"))
    return {
        "schema": SCHEMA,
        "direction": direction,
        "benchmark": str(stated.get("benchmark") or policy.get("default_benchmark") or "").upper() or None,
        "horizon_days": int(horizon) if horizon else None,
        "band_pct": band,
        "source": SOURCE_STATED,
        "policy": policy.get("version") or "ExpectationPolicy@v1",
    }


def build_expectation(
    action: Any,
    *,
    stated: Any = None,
    benchmark: Optional[str] = None,
    policy: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """The decision's expectation, or None when the action makes no claim.

    A valid ``stated`` expectation always wins over the policy default.
    """
    pol = policy if policy is not None else load_policy()
    if not pol:
        return None
    explicit = _stated(stated, pol)
    if explicit:
        return explicit
    act = str(action or "").strip().upper()
    for rule in pol.get("rules") or []:
        if act in {str(a).upper() for a in rule.get("actions") or []}:
            direction = str(rule.get("direction") or "").upper()
            if direction not in DIRECTIONS:
                return None
            out = {
                "schema": SCHEMA,
                "direction": direction,
                "benchmark": str(benchmark or pol.get("default_benchmark") or "").upper() or None,
                "horizon_days": int(_num(pol.get("default_horizon_days")) or 0) or None,
                "band_pct": _num(pol.get("default_band_pct")) if direction in {"WITHIN_BAND", "FLAT_VS_BENCHMARK"} else None,
                "source": SOURCE_POLICY_DEFAULT,
                "policy": pol.get("version") or "ExpectationPolicy@v1",
                "derived_from_action": act,
            }
            return out
    return None


def score_expectation(
    expectation: Any,
    symbol_change_pct: Any,
    benchmark_change_pct: Any,
) -> dict[str, Any]:
    """Hit/miss for one expectation. PENDING_DATA when either side is missing.

    Relative to the benchmark: UP hits when the symbol beat it, DOWN when it
    lagged, WITHIN_BAND / FLAT_VS_BENCHMARK when |excess| <= band_pct.
    """
    exp = expectation if isinstance(expectation, dict) else {}
    base = {
        "schema": SCORE_SCHEMA,
        "basis": "EXPECTATION",
        "policy": exp.get("policy"),
        "source": exp.get("source"),
        "direction": exp.get("direction"),
        "benchmark": exp.get("benchmark"),
        "band_pct": exp.get("band_pct"),
    }
    sym = _num(symbol_change_pct)
    bench = _num(benchmark_change_pct)
    direction = str(exp.get("direction") or "").upper()
    if direction not in DIRECTIONS:
        return {**base, "status": STATUS_PENDING_DATA, "reason": "no_valid_expectation", "hit": None}
    if sym is None or bench is None:
        missing = "benchmark_price" if bench is None else "symbol_price"
        return {**base, "status": STATUS_PENDING_DATA, "reason": f"missing_{missing}", "hit": None}
    excess = round(sym - bench, 4)
    if direction == "UP":
        hit = excess > 0
    elif direction == "DOWN":
        hit = excess < 0
    else:
        band = _num(exp.get("band_pct"))
        if band is None:
            return {**base, "status": STATUS_PENDING_DATA, "reason": "no_band", "hit": None}
        hit = abs(excess) <= band
    return {
        **base,
        "status": STATUS_SCORED,
        "hit": bool(hit),
        "symbol_change_pct": sym,
        "benchmark_change_pct": bench,
        "excess_pct": excess,
        "magnitude_pct": abs(excess),
    }


def expectation_verdict(realized: Any) -> Optional[str]:
    """CONFIRMED / CONTRADICTED from a scored expectation, else None."""
    if not isinstance(realized, dict):
        return None
    score = realized.get("expectation_score")
    if not isinstance(score, dict) or score.get("status") != STATUS_SCORED or score.get("hit") is None:
        return None
    return "CONFIRMED" if score.get("hit") else "CONTRADICTED"
