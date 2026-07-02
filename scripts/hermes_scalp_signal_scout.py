#!/usr/bin/env python3
"""hermes_scalp_signal_scout.py — Signal Scout Agent for momentum scalp Hermes swarm.

Detects and qualifies momentum + social signals from scalp_scan_results and trade_ai_scans.
Applies freshness SLA. Writes qualified_signals.json for Entry Validation.

  python3 scripts/hermes_scalp_signal_scout.py [--once] [--interval 45]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.momentum_scalp_swarm_state import now_iso, read_json, write_json, append_audit  # noqa: E402

FRESHNESS_PURE_SCALP_S = 45
FRESHNESS_SOCIAL_MAX_S = 90


def _load_yaml_limits() -> dict:
    import yaml
    cfg = yaml.safe_load((PROJECT_ROOT / "config/strategies/momentum_scalp.yaml").read_text())
    sf = cfg.get("screen_filters") or {}
    risk = cfg.get("risk") or {}
    return {
        "min_rvol": float(sf.get("min_rvol", 5.0)),
        "max_price": float(sf.get("max_price", 25.0)),
        "min_price": float(sf.get("min_price", 1.0)),
        "max_float_m": float(sf.get("max_float_m", 20)),
        "max_concurrent": int(risk.get("max_concurrent_scalps", 3)),
    }


def _age_seconds(ts) -> float | None:
    if ts is None:
        return None
    if hasattr(ts, "timestamp"):
        return (datetime.now(timezone.utc) - ts.replace(tzinfo=timezone.utc)).total_seconds()
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return None


def _conviction(row: dict, lim: dict) -> int:
    score = 40
    rvol = float(row.get("rvol") or 0)
    if rvol >= 8:
        score += 25
    elif rvol >= lim["min_rvol"]:
        score += 15
    dec = str(row.get("decision") or "").upper()
    if dec in ("GO", "A+"):
        score += 20
    elif dec == "WAIT":
        score += 8
    if row.get("catalyst_verified"):
        score += 12
    src = row.get("source") or ""
    sources = row.get("sources")
    if isinstance(sources, list) and any("social" in str(s).lower() for s in sources):
        src = "social_scalp"
    if src in ("social", "social_scalp", "scalp_social", "premarket_social", "scalp_scan"):
        score += 5
    grade = str(row.get("grade") or "")
    if grade.startswith("A"):
        score += 10
    return min(100, max(0, score))


def _setup_tag(row: dict) -> str:
    src = str(row.get("source") or "").lower()
    sources = row.get("sources")
    if isinstance(sources, list) and any("social" in str(s).lower() for s in sources):
        src = "social"
    if "social" in src:
        if row.get("catalyst_verified"):
            return "social_route_confirmed"
        return "social_route_unverified"
    return "pure_momentum_scalp"


def _qualify_row(row: dict, lim: dict) -> dict | None:
    sym = str(row.get("symbol") or "").upper()
    if not sym or len(sym) > 5:
        return None
    price = float(row.get("price") or 0)
    if price and (price < lim["min_price"] or price > lim["max_price"]):
        return {"symbol": sym, "policy_compliant": False, "reject_reason": f"price ${price} outside ${lim['min_price']}-${lim['max_price']}"}
    rvol = float(row.get("rvol") or 0)
    if rvol and rvol < lim["min_rvol"]:
        return {"symbol": sym, "policy_compliant": False, "reject_reason": f"RVOL {rvol:.1f}x < {lim['min_rvol']}x minimum"}
    freshness_s = row.get("freshness_s")
    if freshness_s is None:
        freshness_s = _age_seconds(row.get("scanned_at"))
    setup = _setup_tag(row)
    max_fresh = FRESHNESS_SOCIAL_MAX_S if "social" in setup else FRESHNESS_PURE_SCALP_S
    if freshness_s is not None and freshness_s > max_fresh:
        return {"symbol": sym, "policy_compliant": False, "reject_reason": f"freshness {int(freshness_s)}s > SLA {max_fresh}s"}
    regime = read_json("regime_state.json", {}) or {}
    sym_regime = (regime.get("symbols") or {}).get(sym, {})
    return {
        "symbol": sym,
        "conviction": _conviction(row, lim),
        "freshness_s": round(freshness_s, 1) if freshness_s is not None else None,
        "setup_tag": setup,
        "regime": sym_regime.get("regime") or regime.get("market_regime"),
        "decision": row.get("decision"),
        "grade": row.get("grade"),
        "rvol": rvol,
        "price": price or row.get("price"),
        "gap_pct": row.get("gap_pct"),
        "source": row.get("source"),
        "scan_id": row.get("id"),
        "policy_compliant": True,
        "reject_reason": None,
        "status": "pending_validation",
        "policy_ref": "MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md §1, §3 L1",
    }


def _fetch_candidates() -> list[dict]:
    from db_adapter import _execute
    rows = _execute(
        """SELECT id, symbol, score, grade, decision, rvol, gap_pct, change_pct,
                  price, catalyst_verified, sources, scanned_at, 'scalp_scan' AS source
           FROM scalp_scan_results
           WHERE scanned_at > NOW() - INTERVAL '3 hours'
             AND decision IN ('GO', 'A+', 'WAIT')
           ORDER BY score DESC NULLS LAST, scanned_at DESC
           LIMIT 40""",
        fetch="all",
    ) or []
    out = []
    for r in rows:
        d = dict(r)
        d["freshness_s"] = _age_seconds(d.get("scanned_at"))
        out.append(d)
    try:
        extra = _execute(
            """SELECT id, symbol, score, decision, rvol, gap_pct, change_pct,
                      price, scanned_at, COALESCE(source, 'trade_ai_scan') AS source
               FROM trade_ai_scans
               WHERE scanned_at > NOW() - INTERVAL '2 hours'
                 AND decision IN ('GO', 'WAIT')
                 AND (source ILIKE '%social%' OR source ILIKE '%scalp%' OR source = 'continuous')
               ORDER BY score DESC NULLS LAST
               LIMIT 20""",
            fetch="all",
        ) or []
    except Exception:
        extra = []
    for r in extra:
        d = dict(r)
        d["freshness_s"] = _age_seconds(d.get("scanned_at"))
        out.append(d)
    return out


def tick() -> dict:
    lim = _load_yaml_limits()
    open_count = len((read_json("open_scalps.json", {}) or {}).get("scalps") or [])
    existing = read_json("qualified_signals.json", {"signals": []}) or {"signals": []}
    seen = {s["symbol"] for s in existing.get("signals") or [] if s.get("status") == "pending_validation"}

    qualified, rejected = [], []
    for row in _fetch_candidates():
        q = _qualify_row(row, lim)
        if not q:
            continue
        if not q.get("policy_compliant"):
            rejected.append(q)
            continue
        if q["symbol"] in seen:
            continue
        if open_count >= lim["max_concurrent"]:
            q["policy_compliant"] = False
            q["reject_reason"] = f"max concurrent scalps ({lim['max_concurrent']}) reached"
            rejected.append(q)
            continue
        qualified.append(q)
        seen.add(q["symbol"])

    # Keep prior pending + add new (dedupe by symbol, newest wins)
    prior = [s for s in (existing.get("signals") or []) if s.get("status") != "pending_validation"]
    merged = {s["symbol"]: s for s in prior}
    for s in qualified:
        merged[s["symbol"]] = s
    signals = list(merged.values())[-30:]

    payload = {
        "schema_version": "1.0",
        "updated_at": now_iso(),
        "signals": signals,
        "rejected_last_tick": rejected[-10:],
        "qualified_count": len(qualified),
        "rejected_count": len(rejected),
    }
    write_json("qualified_signals.json", payload)

    if qualified:
        append_audit({
            "agent": "signal_scout",
            "action": "qualify",
            "symbols": [s["symbol"] for s in qualified],
            "count": len(qualified),
        })

    return {"qualified": len(qualified), "rejected": len(rejected), "pending": len(signals)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=45)
    args = ap.parse_args()
    if args.once:
        print(json.dumps(tick(), indent=2))
        return
    print("[signal_scout] starting loop", flush=True)
    while True:
        try:
            out = tick()
            print(f"[signal_scout] {now_iso()} qualified={out['qualified']} pending={out['pending']}", flush=True)
        except Exception as e:
            print(f"[signal_scout] error: {e}", flush=True)
        time.sleep(max(15, args.interval))


if __name__ == "__main__":
    main()