"""Per-position protection playbook, shown at YELLOW and above for exposed positions (precision PR).

Operator 2026-10-31: "advise me what sectors were there that I should have put a trail and stop in? The percentages
recommendation for each trail and stop ... the ones that are traded in pre-market or extended, that I wouldn't have to
wait till the market opens to get stopped out."

BOUNDARY (AGENTS §0 rule 1, MBI_BEHAVIOR = 0; ``BehaviorWriteRefused`` unchanged): the agent never places, writes or
decides a stop. This module DISPLAYS the operator's own house policy — the family bands in ``config/stop_policy.yaml``
computed by ``scripts/holding_family.py`` (``classify_family`` + ``protection_bounds``), the same reader the Prospectus
stop plan uses — beside the broker stop distance, plus verified facts about extended-hours sessions, the measured gap
risk, the look-through implied open, re-entry conditions, a wash-sale note for taxable accounts, hedge context and
which positions move together. Any tier-based tightening is the OPERATOR-SET proposal in
``config/market_risk_policy.yaml`` ``positions.playbook.tier_posture`` (§17), applied through holding_family's own
``regime_adjustments`` — never decided here. Every payload passes ``contract.assert_no_behavior_fields``; every
rendered line passes the shared sizing-text guard. Nothing here reaches an order route.
"""

from __future__ import annotations

import math
from statistics import mean
from typing import Any

from scripts.lib.market_risk import contract as c


def house_band(symbol: str, tier: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """The house family band for this symbol at this tier, from holding_family (the operator's stop_policy.yaml)."""
    import holding_family as hf  # scripts/holding_family.py, on sys.path via scripts/

    fam, src = hf.classify_family(symbol)
    posture = ((cfg.get("tier_posture") or {}).get(str(tier).upper())) or None
    b = hf.protection_bounds(fam, regime=posture)
    tiers = hf.policy_tiers()
    return {
        "family": fam,
        "family_label": (tiers.get(fam) or {}).get("label") or fam,
        "family_source": src,
        "stop_band_pct": [b.get("stop_min_pct"), b.get("stop_max_pct")],
        "trail_band_pct": [b.get("trail_min_pct"), b.get("trail_max_pct")],
        "posture_applied": posture,
        "posture_source": "config/market_risk_policy.yaml positions.playbook.tier_posture (OPERATOR-SET, §17)"
        if posture
        else None,
    }


def gap_risk(bars: list[dict[str, Any]], stop_distance_pct: float | None, lookback: int) -> dict[str, Any]:
    """How often the open gapped through a stop this far below the prior close, in the position's own history."""
    if stop_distance_pct is None:
        return {"known": False, "reason": "no broker stop distance"}
    rows = [r for r in bars if r.get("open") is not None and r.get("close") is not None][-(lookback + 1) :]
    gaps = [(rows[i]["open"] / rows[i - 1]["close"] - 1.0) * 100.0 for i in range(1, len(rows)) if rows[i - 1]["close"]]
    if len(gaps) < 60:
        return {"known": False, "reason": f"only {len(gaps)} sessions of open/close history"}
    k = sum(1 for g in gaps if g <= -abs(stop_distance_pct))
    worst = min(gaps)
    return {
        "known": True,
        "sessions": len(gaps),
        "gapped_through": k,
        "worst_gap_pct": round(worst, 2),
        "text": f"Stop at {abs(stop_distance_pct):.1f}% below; in the last {len(gaps)} sessions the open gapped past it {k} time(s) (worst {worst:.1f}%).",
    }


def implied_open(holdings: list[dict[str, Any]], moves: dict[str, float]) -> dict[str, Any]:
    """Look-through implied open: sum of holding weight x that holding's extended-hours move."""
    alias = {"GOOG": "GOOGL"}
    used, w_total, impact = [], 0.0, 0.0
    for h in holdings or []:
        sym = str(h.get("holding") or "").upper()
        mv = moves.get(sym) if sym in moves else moves.get(alias.get(sym, ""))
        w = float(h.get("weight") or 0.0)
        if mv is None or not w:
            continue
        impact += w * float(mv)
        w_total += w
        used.append({"holding": sym, "holding_pct": round(w * 100, 1), "move_pct": round(float(mv), 2)})
    if not used:
        return {"known": False, "reason": "no extended-hours prints for the holdings"}
    used.sort(key=lambda u: -abs(u["holding_pct"] * u["move_pct"]))
    desc = ", ".join(f"{u['holding']} {u['holding_pct']}% of fund {u['move_pct']:+.1f}%" for u in used[:5])
    return {
        "known": True,
        "implied_open_pct": round(impact, 2),
        "coverage_pct": round(w_total * 100, 1),
        "movers": used,
        "text": f"implied open {impact:+.2f}% from {len(used)} after-hours movers ({desc}); covers {w_total * 100:.0f}% of the fund",
    }


def moves_with(
    symbol: str, returns: dict[str, list[float]], groups: dict[str, list[str]], min_corr: float
) -> list[str]:
    """Positions that move WITH this one in this shock — direct pairs only (no transitive chaining): the same flagged
    group, or daily-return correlation >= min_corr over the window."""
    out = []
    mine = set(groups.get(symbol) or [])
    for other in sorted(set(returns) | set(groups)):
        if other == symbol:
            continue
        if mine & set(groups.get(other) or []):
            out.append(other)
            continue
        a, b = returns.get(symbol) or [], returns.get(other) or []
        n = min(len(a), len(b))
        if n >= 20:
            a, b = a[-n:], b[-n:]
            ma, mb = mean(a), mean(b)
            va = math.sqrt(sum((x - ma) ** 2 for x in a))
            vb = math.sqrt(sum((y - mb) ** 2 for y in b))
            if va and vb and sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb) >= min_corr:
                out.append(other)
    return out


def book_clusters(returns: dict[str, list[float]], groups: dict[str, list[str]], min_corr: float) -> list[list[str]]:
    """Positions that move together in this shock: daily-return correlation >= min_corr or the same flagged group."""
    syms = sorted(returns)

    def corr(a: list[float], b: list[float]) -> float | None:
        n = min(len(a), len(b))
        if n < 20:
            return None
        a, b = a[-n:], b[-n:]
        ma, mb = mean(a), mean(b)
        va = math.sqrt(sum((x - ma) ** 2 for x in a))
        vb = math.sqrt(sum((y - mb) ** 2 for y in b))
        return None if not va or not vb else sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb)

    parent = {s: s for s in set(syms) | set(groups)}

    def find(x: str) -> str:
        while parent[x] != x:
            x = parent[x]
        return x

    for i, a in enumerate(syms):
        for b in syms[i + 1 :]:
            r = corr(returns[a], returns[b])
            if r is not None and r >= min_corr:
                parent[find(a)] = find(b)
    allsyms = list(parent)
    for i, a in enumerate(allsyms):
        for b in allsyms[i + 1 :]:
            if set(groups.get(a) or []) & set(groups.get(b) or []):
                parent[find(a)] = find(b)
    out: dict[str, list[str]] = {}
    for s in allsyms:
        out.setdefault(find(s), []).append(s)
    return sorted([sorted(v) for v in out.values() if len(v) > 1], key=len, reverse=True)


def build(
    *,
    symbol: str,
    tier: str,
    stance: dict[str, Any],
    stop_distance_pct: float | None,
    bars: list[dict[str, Any]],
    holdings: list[dict[str, Any]] | None,
    after_hours_moves: dict[str, float] | None,
    account_types: list[str] | None,
    hedge: dict[str, Any] | None,
    cluster: list[str] | None,
    policy: dict[str, Any],
    as_of: str | None,
    band: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = ((policy or {}).get("positions") or {}).get("playbook") or {}
    band = band if band is not None else house_band(symbol, tier, cfg)
    smax = band["stop_band_pct"][1]
    outside = None if (stop_distance_pct is None or smax is None) else abs(stop_distance_pct) > float(smax)
    gap = gap_risk(bars, stop_distance_pct, int(cfg.get("gap_lookback_sessions", 500)))
    imp = implied_open(holdings or [{"holding": symbol, "weight": 1.0}], after_hours_moves or {})
    if imp.get("known") and stop_distance_pct is not None:
        room = abs(stop_distance_pct) + float(imp["implied_open_pct"])
        imp["room_to_stop_pct"] = round(room, 2)
        imp["near_stop"] = room <= float(cfg.get("near_stop_pct", 2.0))
    taxable = any(str(t).lower() in ("taxable", "individual", "brokerage", "joint") for t in (account_types or []))
    pb = {
        "symbol": symbol,
        "tier": tier,
        "stance": stance.get("stance"),
        "house": band,
        "broker_stop_distance_pct": None if stop_distance_pct is None else round(abs(stop_distance_pct), 2),
        "outside_house_band": outside,
        "session_facts": list(cfg.get("session_facts") or []),
        "session_alternatives": list(cfg.get("session_alternatives") or []),
        "gap_risk": gap,
        "implied_open": imp,
        "re_enter_if": stance.get("re_enter_if") or [],
        "wash_sale_note": cfg.get("wash_sale_note") if taxable else None,
        "hedge": hedge,
        "moves_with": [s for s in (cluster or []) if s != symbol],
        "as_of": as_of,
    }
    c.assert_no_behavior_fields(pb)
    _sizing_guard(render_lines(pb))
    return pb


def render_lines(pb: dict[str, Any]) -> list[str]:
    h = pb["house"]
    lines = [
        f"{pb['symbol']} · CIO {str(pb.get('stance') or '').lower().replace('_', ' ')} · house {h['family_label']}: "
        f"stop {h['stop_band_pct'][0]}–{h['stop_band_pct'][1]}%, trail {h['trail_band_pct'][0]}–{h['trail_band_pct'][1]}%"
        + (f" (tier posture {h['posture_applied']}, operator-set)" if h.get("posture_applied") else ""),
    ]
    if pb.get("broker_stop_distance_pct") is None:
        lines.append("No broker stop is observed on this position.")
    if pb.get("broker_stop_distance_pct") is not None:
        lines.append(
            f"Broker stop {pb['broker_stop_distance_pct']}% below last"
            + (
                " — wider than the house band at this tier"
                if pb.get("outside_house_band")
                else " — inside the house band"
            )
        )
    if (pb.get("gap_risk") or {}).get("known"):
        lines.append(pb["gap_risk"]["text"])
    imp = pb.get("implied_open") or {}
    if imp.get("known"):
        lines.append(imp["text"] + (" — within reach of your stop" if imp.get("near_stop") else ""))
    lines += list(pb.get("session_facts") or [])[:2]
    if pb.get("moves_with"):
        lines.append("Moves with: " + ", ".join(pb["moves_with"]))
    if pb.get("hedge"):
        lines.append(f"Hedge context: {pb['hedge'].get('symbol')} stoplight {pb['hedge'].get('state')}")
    if pb.get("wash_sale_note"):
        lines.append(pb["wash_sale_note"])
    lines.append("Advisory. The house bands are your stop_policy.yaml; no order, size or stop price is implied.")
    return lines


def _sizing_guard(lines: list[str]) -> None:
    from scripts.lib import buy_ready_cio_review as br

    blob = " ".join(lines)
    if br._SIZING_TEXT.search(blob):  # noqa: SLF001 — the shared sizing-text guard, used as-is
        raise ValueError("sizing text in protection playbook")
