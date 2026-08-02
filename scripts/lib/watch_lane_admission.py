"""Watch lane admission — MAIN / RESEARCH / COVERAGE classifier (quality-first plan).

Deterministic, no LLM. Used by /api/v2/watchlist/items?lane=, quality board, and
proposal bridge gate. Demote ≠ delete.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "watch_lane_admission.json"
PROFILES_PATH = PROJECT_ROOT / "config" / "hermes_score_profiles.yaml"
WEIGHTS_PATH = PROJECT_ROOT / "config" / "hermes_score_weights.yaml"

_DEFAULT = {
    "main_cap": 60,
    "default_lane": "main",
    "main_source_allowlist": [
        "operator", "personal_watchlist", "pullback_macd", "trade_ai_go",
        "hermes", "portfolio", "prev_traded",
    ],
    "coverage_sources": ["analyst", "analyst_coverage", "analyst_signal", "pro_analyst"],
    "coverage_source_substrings": ["analyst", "coverage"],
    "setup_shaped_types": [
        "pullback entry", "trend continuation", "range / mean-reversion",
        "reversal / mean-reversion watch", "support bounce", "breakout",
        "momentum continuation (extended)",
    ],
    "no_trade_type_substrings": ["no-trade", "downtrend"],
    "proposal_bridge": {"require_main_go": True},
    "authority": {
        "operator_star_grants_m1": True,
        "screener_pin_grants_m1": True,
        "directive_watch_grants_m1": False,
    },
}


def load_policy() -> dict:
    try:
        doc = json.loads(CONFIG_PATH.read_text())
        if isinstance(doc, dict):
            merged = dict(_DEFAULT)
            merged.update(doc)
            return merged
    except Exception:
        pass
    return dict(_DEFAULT)


def _src(item: dict) -> str:
    return str(item.get("source") or item.get("wl_source") or "").strip().lower()


def _setup_type(item: dict) -> str:
    sc = item.get("setup_context") or {}
    if isinstance(sc, dict):
        return str(sc.get("type") or "").strip().lower()
    return str(item.get("entry_setup") or item.get("setup_type") or "").strip().lower()


def is_coverage_source(source: str, policy: dict | None = None) -> bool:
    p = policy or load_policy()
    s = (source or "").lower()
    if s in {x.lower() for x in (p.get("coverage_sources") or [])}:
        return True
    for sub in p.get("coverage_source_substrings") or []:
        if sub and sub.lower() in s:
            return True
    return False


def is_setup_shaped(item: dict, policy: dict | None = None) -> bool:
    p = policy or load_policy()
    t = _setup_type(item)
    if not t:
        # entry_setup tokens without full setup_context
        es = str(item.get("entry_setup") or "").lower()
        if es in ("pullback", "support_bounce", "breakout", "reversal", "continuation"):
            return True
        return False
    for bad in p.get("no_trade_type_substrings") or []:
        if bad and bad in t:
            return False
    for good in p.get("setup_shaped_types") or []:
        if good and good.lower() in t:
            return True
    if "pullback" in t or "continuation" in t or "bounce" in t or "breakout" in t:
        return True
    return False


def is_no_trade_setup(item: dict, policy: dict | None = None) -> bool:
    p = policy or load_policy()
    t = _setup_type(item)
    for bad in p.get("no_trade_type_substrings") or []:
        if bad and bad in t:
            return True
    return False


def has_m1_identity(item: dict, policy: dict | None = None) -> bool:
    """Source allowlist, star, pin, directive, or explicit promote — not analyst alone."""
    p = policy or load_policy()
    auth = p.get("authority") or {}
    src = _src(item)
    allow = {x.lower() for x in (p.get("main_source_allowlist") or [])}
    if src in allow and not is_coverage_source(src, p):
        return True
    if auth.get("operator_star_grants_m1") and item.get("starred"):
        return True
    if auth.get("screener_pin_grants_m1") and item.get("screener_pinned"):
        return True
    if auth.get("directive_watch_grants_m1") and item.get("in_directive_watch"):
        return True
    if item.get("main_promoted") or item.get("lane_promoted_main"):
        return True
    # Defense → MAIN promote bridge (soft-auto SCHD/defensive ETFs or operator click)
    if _is_defense_main_promoted(item):
        return True
    # ai_discovered / topic_research / paper_proposal never earn M1 from actionable alone —
    # they stay RESEARCH until operator star, screener pin, directive, or explicit promote.
    return False


def _is_defense_main_promoted(item: dict) -> bool:
    origin = str(item.get("origin_system") or "").lower()
    if origin in ("defense_rotation", "defense_main_promote"):
        return True
    notes = str(item.get("notes") or "")
    if "defense_main_promote" in notes:
        return True
    if item.get("defense_main_promoted"):
        return True
    return False


def has_m3_ticket(item: dict) -> bool:
    if item.get("decision_actionable") is True:
        return True
    stop = item.get("entry_stop") or item.get("stop_loss") or item.get("card_stop")
    target = item.get("entry_target") or item.get("target_price") or item.get("card_target")
    rr = item.get("entry_rr") or item.get("risk_reward") or item.get("card_rr")
    try:
        if stop is not None and target is not None and rr is not None and float(rr) >= 1.0:
            return True
    except (TypeError, ValueError):
        pass
    return False


def classify_lane(item: dict, policy: dict | None = None) -> str:
    """Return main | coverage | research."""
    p = policy or load_policy()
    src = _src(item)
    if is_coverage_source(src, p):
        return "coverage"
    # Analyst-only rating without setup → coverage-ish research
    rating_src = str(item.get("rating_source") or "").lower()
    if rating_src in ("pro_analyst", "analyst") and not is_setup_shaped(item, p) and not item.get("starred"):
        if not has_m1_identity(item, p):
            return "coverage"
    if item.get("decision_quality_status") == "unsafe" and not item.get("starred"):
        return "research"
    if is_no_trade_setup(item, p) and not item.get("starred"):
        return "research"
    if has_m1_identity(item, p) and (is_setup_shaped(item, p) or item.get("starred") or item.get("screener_pinned")):
        if has_m3_ticket(item) or item.get("starred") or item.get("screener_pinned") or _src(item) in {
            "operator", "personal_watchlist", "pullback_macd", "trade_ai_go", "portfolio", "prev_traded", "hermes",
        }:
            # hermes/operator without ticket still wait on MAIN as WAIT later
            if is_setup_shaped(item, p) or item.get("starred") or item.get("screener_pinned") or _src(item) in {
                "operator", "personal_watchlist", "pullback_macd", "trade_ai_go", "portfolio", "prev_traded",
            }:
                return "main"
    # Defense-promoted funds/ETFs: MAIN WAIT without equity setup_shaped (star-parity)
    if _is_defense_main_promoted(item) and not is_no_trade_setup(item, p):
        return "main"
    if has_m1_identity(item, p) and has_m3_ticket(item) and not is_no_trade_setup(item, p):
        return "main"
    return "research"


def now_status(item: dict, policy: dict | None = None) -> str:
    """GO | WAIT | NOGO for a MAIN-admitted row (or pre-admission view)."""
    p = policy or load_policy()
    lane = item.get("lane") or classify_lane(item, p)
    if lane == "coverage":
        return "COVERAGE"
    if lane != "main":
        return "NOGO"
    if item.get("decision_quality_status") == "unsafe" or item.get("decision_safety") == "unsafe":
        return "NOGO"
    if is_no_trade_setup(item, p):
        return "NOGO"
    if item.get("decision_actionable") is True and is_setup_shaped(item, p):
        return "GO"
    if has_m3_ticket(item) and is_setup_shaped(item, p):
        return "GO"
    if item.get("starred") and not is_no_trade_setup(item, p):
        return "WAIT"
    # Defense promote lands WAIT until fund-aware ticket/plan exists
    if _is_defense_main_promoted(item) and not is_no_trade_setup(item, p):
        if has_m3_ticket(item) and is_setup_shaped(item, p):
            return "GO"
        return "WAIT"
    if has_m1_identity(item, p) and not is_no_trade_setup(item, p):
        return "WAIT"
    return "NOGO"


def primary_cta(item: dict, policy: dict | None = None) -> str:
    st = now_status(item, policy)
    if st == "GO":
        return "Propose"
    if st == "WAIT":
        return "Refresh plan"
    if st == "COVERAGE":
        return "Open coverage"
    return "Park research"


def annotate_item(item: dict, policy: dict | None = None) -> dict:
    p = policy or load_policy()
    lane = classify_lane(item, p)
    item["lane"] = lane
    item["now_status"] = now_status(item, p) if lane == "main" else (
        "COVERAGE" if lane == "coverage" else "RESEARCH"
    )
    item["primary_cta"] = primary_cta(item, p)
    item["main_eligible"] = lane == "main"
    reasons = []
    if not has_m1_identity(item, p):
        reasons.append("m1_identity")
    if is_no_trade_setup(item, p):
        reasons.append("no_trade_setup")
    if not is_setup_shaped(item, p) and not item.get("starred"):
        reasons.append("not_setup_shaped")
    if not has_m3_ticket(item) and not item.get("starred"):
        reasons.append("no_ticket")
    if is_coverage_source(_src(item), p):
        reasons.append("coverage_source")
    item["lane_blockers"] = reasons if lane != "main" else []
    return item


def apply_main_cap(items: list[dict], policy: dict | None = None) -> list[dict]:
    p = policy or load_policy()
    cap = int(p.get("main_cap") or 60)
    main = [it for it in items if it.get("lane") == "main" or it.get("main_eligible")]
    # Prefer GO then WAIT, then hermes_rank / score
    def sort_key(it: dict):
        st = it.get("now_status") or now_status(it, p)
        pri = 0 if st == "GO" else 1 if st == "WAIT" else 2
        rank = it.get("hermes_rank")
        try:
            rank_n = int(rank) if rank is not None else 99999
        except (TypeError, ValueError):
            rank_n = 99999
        return (pri, rank_n, str(it.get("symbol") or ""))

    main_sorted = sorted(main, key=sort_key)
    kept = {id(it) for it in main_sorted[:cap]}
    out = []
    for it in items:
        if it.get("lane") == "main" and id(it) not in kept:
            it = dict(it)
            it["lane"] = "research"
            it["main_eligible"] = False
            it["now_status"] = "RESEARCH"
            it["lane_blockers"] = list(it.get("lane_blockers") or []) + ["main_cap_overflow"]
            it["primary_cta"] = "Promote to main"
        out.append(it)
    return out


def quality_board_from_items(items: list[dict], policy: dict | None = None) -> dict:
    p = policy or load_policy()
    annotated = [annotate_item(dict(it), p) for it in items]
    by_lane: dict[str, int] = {}
    by_now: dict[str, int] = {}
    actionable = no_setup = coverage_on_main = 0
    for it in annotated:
        lane = it.get("lane") or "research"
        by_lane[lane] = by_lane.get(lane, 0) + 1
        st = it.get("now_status") or "—"
        by_now[st] = by_now.get(st, 0) + 1
        if it.get("decision_actionable") is True:
            actionable += 1
        if is_no_trade_setup(it, p):
            no_setup += 1
    main_n = by_lane.get("main", 0)
    return {
        "sample_n": len(annotated),
        "by_lane": by_lane,
        "by_now": by_now,
        "actionable_n": actionable,
        "actionable_pct": round(100.0 * actionable / len(annotated), 1) if annotated else 0.0,
        "no_setup_n": no_setup,
        "no_setup_pct": round(100.0 * no_setup / len(annotated), 1) if annotated else 0.0,
        "main_n": main_n,
        "main_cap": int(p.get("main_cap") or 60),
        "main_go": by_now.get("GO", 0),
        "main_wait": by_now.get("WAIT", 0),
        "main_nogo": by_now.get("NOGO", 0),
        "default_lane": p.get("default_lane") or "main",
        "policy_version": p.get("version") or "watch-lane-admission-v1",
    }


def live_weights_meta() -> dict:
    meta: dict[str, Any] = {"path": str(WEIGHTS_PATH), "locked": False, "profile": None, "weights": {}}
    try:
        import yaml
        doc = yaml.safe_load(WEIGHTS_PATH.read_text()) or {}
        meta["locked"] = bool(doc.get("locked") or doc.get("graft_forbidden"))
        meta["profile"] = doc.get("profile") or "legacy"
        meta["weights"] = doc.get("weights") or {}
        meta["analyst_weight"] = float((doc.get("weights") or {}).get("analyst") or 0)
        meta["setup_quality_weight"] = float((doc.get("weights") or {}).get("setup_quality") or 0)
        meta["graft_forbidden"] = bool(doc.get("graft_forbidden"))
        meta["lock_reason"] = doc.get("lock_reason")
    except Exception as e:
        meta["error"] = str(e)[:160]
    return meta


def main_sql_source_clause(policy: dict | None = None) -> tuple[str, list]:
    """SQL fragment for pre-filtering MAIN-ish rows (M1 identity approx). Params list.

    Intentionally does NOT include in_directive_watch or maturity.actionable alone —
    those pull thousands of ai_discovered rows and defeat quality admission.
    """
    p = policy or load_policy()
    allow = list(p.get("main_source_allowlist") or [])
    # allowlist sources + operator star + screener pin only
    sql = """(
        wi.source = ANY(%s)
        OR EXISTS (SELECT 1 FROM operator_starred_symbols s WHERE upper(s.symbol) = upper(wi.symbol))
        OR EXISTS (SELECT 1 FROM screener_find_pins sfp WHERE upper(sfp.symbol) = upper(wi.symbol) AND sfp.active = true)
    )"""
    return sql, [allow]
