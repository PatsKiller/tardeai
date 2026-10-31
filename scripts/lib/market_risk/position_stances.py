"""Position-level CIO stances from market risk: exit review, trim review, and the re-entry conditions (precision PR).

Operator 2026-10-31: "It should have advised me I would have got out earlier ... and then it also needs to advise me
when to get back in." Expressed ONLY as the CIO's existing advisory stance vocabulary — WATCH_CLOSELY, TRIM (review),
EXIT (review), RE_ENTER_IF, RE_ENTER, HOLD — with reasons. Never a size, share count, order, price, weight or stop level
(MBI_BEHAVIOR = 0, AGENTS §0 rule 1): every output passes ``contract.assert_no_behavior_fields`` and the sizing-text
check of ``buy_ready_cio_review``. The operator decides and acts.

Rules (``config/market_risk_policy.yaml`` ``positions:``):
* Only positions whose look-through share in the STRESSED groups is at least ``min_exposure`` are flagged — unless the
  shock type is SYSTEMIC, which flags the whole book. Positions in groups holding up stay HOLD with that reason.
* Tier -> stance: YELLOW -> WATCH_CLOSELY, ORANGE -> TRIM review, RED -> EXIT review.
* Once flagged TRIM/EXIT, the position carries RE_ENTER_IF conditions evaluated every cycle; when ``require_all`` hold
  (or any of ``or_any``) it becomes RE_ENTER, and a P2 card names which conditions fired.
"""

from __future__ import annotations

from typing import Any

from scripts.lib.market_risk import contract as c

TIER_STANCE = {"YELLOW": "WATCH_CLOSELY", "ORANGE": "TRIM", "RED": "EXIT"}
STANCE_LABEL = {
    "WATCH_CLOSELY": "watch closely",
    "TRIM": "trim review",
    "EXIT": "exit review",
    "RE_ENTER_IF": "re-enter if",
    "RE_ENTER": "re-entry conditions met",
    "HOLD": "hold",
}
RANK = {"NONE": 0, "GREEN": 0, "BLUE": 1, "YELLOW": 2, "ORANGE": 3, "RED": 4}


def _group_state(block: dict[str, Any], key: str) -> str:
    for r in (block or {}).get("groups") or []:
        if r.get("key") == key:
            return str(r.get("state") or "UNKNOWN")
    return "UNKNOWN"


def reentry_conditions(
    *,
    flagged_groups: list[str],
    sectors_block: dict[str, Any],
    history: list[dict[str, Any]],
    index_above_50d: bool | None,
    vix_below_20d: bool | None,
    engine_tier: str,
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """Deterministic RE_ENTER_IF conditions. ``history`` is the prior evaluations' sectors blocks + tiers, newest last
    (one per completed session), used for 'for N sessions' conditions."""
    n = int(cfg.get("recovered_sessions", 2))
    recent = (history or [])[-n:]
    group_ok = bool(flagged_groups) and len(recent) >= n and all(
        all(_group_state(h.get("sectors") or {}, g) not in ("STRESS", "WEAK") for g in flagged_groups) for h in recent
    )
    tier_ok = len(recent) >= n and all(RANK.get(str(h.get("tier")), 0) < RANK["YELLOW"] for h in recent)
    return [
        {"key": "group_recovered", "met": group_ok,
         "text": f"{', '.join(flagged_groups) or 'flagged groups'} out of stress for {n} sessions"},
        {"key": "market_below_yellow", "met": tier_ok, "text": f"market risk below YELLOW for {n} sessions"},
        {"key": "index_reclaimed_50d", "met": bool(index_above_50d), "known": index_above_50d is not None,
         "text": f"{cfg.get('reclaim_symbol', 'QQQ')} back above its 50-day average"},
        {"key": "vix_below_20d", "met": bool(vix_below_20d), "known": vix_below_20d is not None,
         "text": "VIX below its 20-day average"},
        {"key": "engine_green", "met": str(engine_tier) == "GREEN", "text": "market risk GREEN"},
    ]


def stances(
    *,
    positions: list[str],
    exposures: dict[str, dict[str, Any]],
    tier: str,
    shock: dict[str, Any],
    sectors_block: dict[str, Any],
    prior: dict[str, dict[str, Any]] | None,
    reentry: list[dict[str, Any]],
    stop_distance_pct: dict[str, float] | None,
    policy: dict[str, Any],
    as_of: str | None,
) -> dict[str, dict[str, Any]]:
    cfg = (policy or {}).get("positions") or {}
    min_exp = float(cfg.get("min_exposure", 0.25))
    key_by_label = {r.get("label"): r.get("key") for r in (sectors_block or {}).get("groups") or []}
    stressed_keys = [key_by_label.get(x) for x in (sectors_block or {}).get("stressed") or []]
    stressed_keys = [k for k in stressed_keys if k]
    systemic = str((shock or {}).get("class")) == "SYSTEMIC"
    prior = prior or {}
    req_all = list(cfg.get("reenter_require_all") or ["group_recovered", "index_reclaimed_50d", "vix_below_20d"])
    or_any = list(cfg.get("reenter_or_any") or ["engine_green"])
    met = {r["key"]: bool(r.get("met")) for r in reentry or []}
    out: dict[str, dict[str, Any]] = {}
    for sym in positions:
        ex = exposures.get(sym) or {}
        groups = ex.get("groups") or {}
        hit = {g: s for g, s in groups.items() if g in stressed_keys and s}
        share = max(hit.values(), default=0.0)
        prev = prior.get(sym) or {}
        prev_st = str(prev.get("stance") or "HOLD")
        reasons: list[str] = []
        if hit:
            reasons.append("exposed to " + ", ".join(f"{g} {round(v * 100)}%" for g, v in sorted(hit.items(), key=lambda kv: -kv[1])))
        if ex.get("reporting"):
            reasons.append(f"{len(ex['reporting'])} holding(s) report in the earnings window")
        if stop_distance_pct and sym in stop_distance_pct:
            reasons.append(f"broker stop {stop_distance_pct[sym]:.1f}% below last")
        if shock:
            reasons.append(str(shock.get("headline") or ""))
        flagged = RANK.get(str(tier), 0) >= RANK["YELLOW"] and (systemic or share >= min_exp)
        if not groups:
            st, why = "HOLD", ["look-through unknown: " + (ex.get("note") or "no data")]
        elif flagged:
            st, why = TIER_STANCE[str(tier)], reasons
        elif prev_st in ("TRIM", "EXIT", "RE_ENTER_IF"):
            # flagged earlier: stays RE_ENTER_IF until the conditions are met
            fired = [k for k in or_any if met.get(k)] or ([k for k in req_all if met.get(k)] if all(met.get(k) for k in req_all) else [])
            st = "RE_ENTER" if fired else "RE_ENTER_IF"
            why = ["conditions met: " + ", ".join(fired)] if fired else ["waiting: " + ", ".join(r["text"] for r in reentry if r["key"] in req_all and not r.get("met"))]
        else:
            st = "HOLD"
            why = ["defensive group holding up" if any(_group_state(sectors_block, g) == "RESILIENT" for g in groups) else "not exposed to the stressed groups"]
        rec = {
            "symbol": sym,
            "stance": st,
            "label": STANCE_LABEL.get(st, st.lower()),
            "reasons": [r for r in why if r],
            "since": prev.get("since") if prev_st == st else as_of,
            "exposure_to_stressed": round(share, 4),
            "re_enter_if": [r for r in reentry if r["key"] in req_all + or_any] if st in ("TRIM", "EXIT", "RE_ENTER_IF", "RE_ENTER") else [],
            "flagged_groups": sorted(hit) or prev.get("flagged_groups") or [],
            "as_of": as_of,
        }
        c.assert_no_behavior_fields(rec)
        out[sym] = rec
    _check_text(out)
    return out


def _check_text(recs: dict[str, dict[str, Any]]) -> None:
    from scripts.lib import buy_ready_cio_review as br

    for r in recs.values():
        blob = " ".join([r["label"], *r["reasons"]])
        if br._SIZING_TEXT.search(blob):  # noqa: SLF001 — the shared sizing-text guard, used as-is
            raise ValueError(f"sizing text in stance for {r['symbol']}")


def reentry_card(rec: dict[str, Any]) -> str:
    fired = [r["text"] for r in rec.get("re_enter_if") or [] if r.get("met")]
    return (
        f"🟢 RE-ENTRY CONDITIONS MET · {rec['symbol']}\n"
        + "Fired: " + "; ".join(fired) + "\n"
        + "CIO stance: RE_ENTER (advisory). Your decision; no order, size or price is implied."
    )
