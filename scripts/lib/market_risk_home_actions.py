"""Home market-risk card, design home/v006: the Protect / Hedge / Rotate blocks, folded groups and the glossary.

Pure functions over dicts the API join already has (``market_risk_book_dollars.build`` output, the projection) plus
three read-only inputs the join passes in: the Defense desk's inverse-hedge stoplight snapshot, its sector momentum
rows, and the symbols with a fresh overnight print. Every threshold is config (``home_actions`` and ``glossary`` in
``config/market_risk_policy.yaml``; the hedge thresholds stay in ``config/defense_recommendations.json``).

MBI_BEHAVIOR = 0. Protect clauses are facts and review prompts; the hedge block is a verdict and the desk's
thresholds, never a size band, level, playbook or per-account dollars; Rotate is relative strength, never "buy".
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

try:
    from scripts.lib.defense_hedge_state import stoplight_thesis
    from scripts.lib.market_risk.contract import assert_no_behavior_fields
    from scripts.lib.market_risk.lookthrough import SECTOR_TO_GROUP
except ImportError:  # pragma: no cover — the API imports as lib.*
    from lib.defense_hedge_state import stoplight_thesis  # type: ignore
    from lib.market_risk.contract import assert_no_behavior_fields  # type: ignore
    from lib.market_risk.lookthrough import SECTOR_TO_GROUP  # type: ignore

#: Keys a hedge block may never carry (the Defense desk's hedge card has them; Home shows none).
HEDGE_FORBIDDEN = ("size_band", "levels", "playbook", "dollars_by_account", "impact_dollars", "tp1", "tp2")
#: Action verbs a Protect clause or glossary text must not start a sentence with (brief_guard's rule, reused).
_ACTION = re.compile(
    r"(^|[.;:]\s*)(sell|buy|add|size|hedge now|trim|tighten|raise|lower|move|place|set|exit|reduce|cut)\b", re.IGNORECASE
)


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _usd(v: float) -> str:
    return f"${v:,.0f}"


# ── Protect ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def protect(
    review: list[dict[str, Any]],
    *,
    budgets: list[dict[str, Any]],
    reentry: dict[str, Any],
    overnight: set[str] | None,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Each review item gains ``clauses`` [{key, text}] and ``consideration`` (joined), built in the configured
    order from facts the join already has. ``shown`` items go in the block, the rest in ``more``."""
    cfg = (policy.get("home_actions") or {}).get("protect") or {}
    tpl = cfg.get("templates") or {}
    max_clauses = int(cfg.get("max_clauses", 3))
    shown = int(cfg.get("shown", 3))
    conc_min = _f(cfg.get("concentration_min_share", 0.8))
    overnight = {s.upper() for s in (overnight or set())}

    by_sym: dict[str, list[dict[str, Any]]] = {}
    for it in review:
        by_sym.setdefault(str(it.get("symbol")).upper(), []).append(it)

    items = []
    for it in review:
        sym = str(it.get("symbol")).upper()
        acct = it.get("account_label")
        kinds = list(it.get("kinds") or [])
        facts = it.get("facts") or {}
        cl: list[tuple[str, str]] = []
        if "stop_near" in kinds and facts.get("stop_distance_pct") is not None:
            cl.append(("stop_near", tpl.get("stop_near", "stop {d}% below last").format(d=f"{_f(facts['stop_distance_pct']):.1f}")))
        if "no_stop" in kinds:
            cl.append(("no_stop", tpl.get("no_stop", "no stop")))
        if sym in overnight:
            cl.append(("overnight", tpl.get("overnight", "trades overnight now")))
        order = {"single_sector_pct": 0, "growth_style_pct": 1, "unprotected_pct": 2}
        for b in sorted(budgets, key=lambda x: order.get(str(x.get("budget")), 9)):
            if b.get("account_label") != acct or b.get("actual") is None:
                continue
            drivers = b.get("drivers") or []
            act_usd = _f(b.get("actual_usd"))
            # a symbol driver carries its own dollars; a sector driver (single_sector_pct) does not, so the
            # position's own value is compared with the budget's dollars
            own = next((_f(d.get("usd")) for d in drivers if str(d.get("name")).upper() == sym), 0.0)
            if not own and b.get("budget") == "single_sector_pct" and drivers:
                grp = SECTOR_TO_GROUP.get(str(drivers[0].get("name") or "").lower())
                own = _f(facts.get("value_usd")) * _f((facts.get("groups") or {}).get(grp)) if grp else 0.0
            kind = {"single_sector_pct": "concentration", "growth_style_pct": "concentration_growth"}.get(str(b.get("budget")))
            if kind and act_usd and own / act_usd >= conc_min and not any(k.startswith("concentration") for k, _ in cl):
                cl.append((kind, tpl.get(kind, "").format(p=f"{_f(b['actual']):.0f}", limit=f"{_f(b.get('limit')):.0f}")))
            if b.get("budget") == "unprotected_pct" and drivers and str(drivers[0].get("name")).upper() == sym:
                cl.append(("unprotected", tpl.get("unprotected", "").format(
                    p=f"{_f(b['actual']):.1f}", limit=f"{_f(b.get('limit')):.0f}")))
        same = by_sym.get(sym) or []
        if len(same) > 1:
            other = next((x.get("account_label") for x in same if x is not it), "another")
            total = sum(_f((x.get("facts") or {}).get("value_usd") or x.get("usd")) for x in same)
            cl.append(("same_issuer", tpl.get("same_issuer", "").format(
                other_acct=other, usd=_usd(total), sym=sym, n=len(same))))
        if "stressed_exposure" in kinds and facts.get("stressed_share") is not None:
            cl.append(("stressed", tpl.get("stressed", "{s}% in stressed groups").format(s=round(100 * _f(facts["stressed_share"])))))
        w = ((reentry or {}).get(sym) or {}).get("wash_sale") or {}
        if w.get("state") == "occurred" and w.get("account_label") == acct and w.get("rebuy_date"):
            cl.append(("rebuy", tpl.get("rebuy", "re-bought {date} (wash sale occurred)").format(date=str(w["rebuy_date"])[5:10])))
        for k, txt in (("no_lookthrough", "no look-through (sector unknown)"), ("data_conflict", None)):
            if k in kinds:
                cl.append((k, txt or next((t for t in str(it.get("text") or "").split(" · ") if "ledger" in t), "ledger and holdings disagree")))
        cl = [(k, t) for k, t in cl if t][:max_clauses]
        items.append({**it, "clauses": [{"key": k, "text": t} for k, t in cl],
                      "consideration": "; ".join(t for _, t in cl) or it.get("text")})
    more = items[shown:]
    return {
        "items": items[:shown],
        "more": [{"symbol": m["symbol"], "account_label": m.get("account_label"),
                  "short": (m["clauses"][0]["text"] if m.get("clauses") else m.get("text")), "to": m.get("to")} for m in more],
    }


# ── Hedge ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def hedge(
    *,
    stoplights: dict[str, Any] | None,
    momentum_rows: list[dict[str, Any]] | None,
    book_exposure: dict[str, Any],
    defense_cfg: dict[str, Any],
    today: date,
    transitions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The Hedge block: NOT_NOW / WATCH / CONSIDER / UNKNOWN from the stoplight's THESIS lights, with the book facts
    against the Defense desk's own thresholds. Never re-derives a competing thesis."""
    ie = defense_cfg.get("inverse_etf") or {}
    sl = defense_cfg.get("inverse_stoplights") or {}
    thr = {
        "trigger_book_pct": ie.get("trigger_book_pct"),
        "index_trigger_lagging_sectors": ie.get("index_trigger_lagging_sectors"),
        "materiality_exposure_pct": sl.get("materiality_exposure_pct"),
        "bounce_day_pct": sl.get("bounce_day_pct"),
    }
    # the one thesis reader, shared with the Defense posture's hedge_state (review of #2460, follow-up 1)
    th = stoplight_thesis(stoplights, today=today, stale_days=int(sl.get("stale_calendar_days", 4)))
    state, cands, as_of, reason = th["state"], th["candidates"], th["as_of"], th["reason"]
    rows = [r for r in momentum_rows or [] if isinstance(r, dict)]
    weak = [r for r in rows if r.get("state") in ("WEAKENING", "LAGGING") and r.get("book_pct") is not None]
    largest = max(weak, key=lambda r: _f(r.get("book_pct")), default=None)
    lagging = sum(1 for r in rows if r.get("state") == "LAGGING")
    verdict = {"GREEN": "CONSIDER", "AMBER": "WATCH", "RED": "NOT_NOW"}.get(state, "UNKNOWN")
    since = None
    for t in transitions or []:
        if str(t.get("light")) == "THESIS" and str(t.get("new_state", "")).split("|")[0] == state:
            since = str(t.get("created_at"))[:10]
            break
    block = {
        "verdict": verdict,
        "thesis_state": state,
        "candidates": cands,
        "since": since,
        "as_of": as_of,
        "reason": reason,
        "thresholds": thr,
        "largest_weakening": {"label": largest.get("sector"), "pct_invested": largest.get("book_pct")} if largest else None,
        "lagging_count": lagging,
        "stressed_usd": book_exposure.get("stressed_usd"),
        "stressed_pct_book": book_exposure.get("stressed_pct_book"),
        "stressed_pct_invested": book_exposure.get("stressed_pct_invested"),
        "entry": None,
    }
    if state == "GREEN":
        c0 = next((c for c in (stoplights or {}).get("candidates") or []
                   if ((c.get("lights") or {}).get("THESIS") or {}).get("state") == "GREEN"), {})
        en = (c0.get("lights") or {}).get("ENTRY") or {}
        block["entry"] = {"inverse": c0.get("inverse"), "bench": c0.get("bench"), "state": en.get("state"), "label": en.get("label")}
    leaked = [k for k in HEDGE_FORBIDDEN if k in block]
    if leaked:  # an explicit raise, not an assert (asserts vanish under -O); review of #2460, follow-up 4
        raise ValueError(f"hedge block carries forbidden key(s) {leaked}: Home never shows a hedge size or plan")
    assert_no_behavior_fields(block)
    return block


# ── Rotate ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def rotate(
    heatmap: list[dict[str, Any]],
    *,
    leadership: dict[str, Any] | None,
    momentum_rows: list[dict[str, Any]] | None,
    book_groups: dict[str, Any] | None,
    policy: dict[str, Any],
    sector_groups: list[dict[str, Any]] | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Top groups leading SPY on both horizons (config ``home_actions.rotate``), each with the Defense desk's sector
    momentum state (matched by ETF symbol from ``sector_groups``) and the book's look-through dollars."""
    cfg = (policy.get("home_actions") or {}).get("rotate") or {}
    kinds = set(cfg.get("kinds") or ["sector", "theme"])
    ok_states = set(cfg.get("eligible_states") or ["RESILIENT"])
    ok_lead = set(cfg.get("eligible_leadership") or [])
    bad_lead = set(cfg.get("exclude_leadership") or [])
    req = list(cfg.get("require_positive") or ["rs1", "rs5"])
    wts = cfg.get("rank_weights") or {"rs1": 0.5, "rs5": 0.5}
    lead = ((leadership or {}).get("groups") or {}) if isinstance(leadership, dict) else {}
    desk = {}
    etf_of = {}
    for g in (sector_groups or heatmap):
        if g.get("kind", "sector") not in kinds:
            continue  # the "defensive" basket reuses XLP/XLV/XLU; a sector keeps its own ETF
        for sym in g.get("symbols") or []:
            etf_of.setdefault(str(sym).upper(), g.get("key"))
    for r in momentum_rows or []:
        k = etf_of.get(str(r.get("etf") or "").upper())
        if k:
            desk[k] = r.get("state")
    out = []
    for h in heatmap:
        if h.get("kind") not in kinds:
            continue
        cls = str((lead.get(h.get("key")) or {}).get("class") or "UNKNOWN")
        if cls in bad_lead:
            continue
        if not (h.get("state") in ok_states or cls in ok_lead):
            continue
        if any(h.get(k) is None or _f(h.get(k)) <= 0 for k in req):
            continue
        score = sum(_f(wts.get(k, 0)) * _f(h.get(k)) for k in wts)
        out.append({"key": h.get("key"), "label": h.get("label"), "rs1": h.get("rs1"), "rs5": h.get("rs5"),
                    "state": h.get("state"), "leadership_class": cls, "desk_state": desk.get(h.get("key")),
                    "usd": ((book_groups or {}).get(h.get("key")) or {}).get("usd"), "_s": score})
    out.sort(key=lambda r: (-r["_s"], -_f(r.get("rs5"))))
    for r in out:
        r.pop("_s")
    n = int(cfg.get("max_groups", 3))
    return {"groups": out[:n], "as_of": as_of,
            "none_reason": None if out else "No group is beating SPY on both 1 and 5 sessions today."}


# ── Folded groups ───────────────────────────────────────────────────────────────────────────────────────────────────
FOLD_STATES = ("STRESS", "WEAK", "UNKNOWN")


def folded(heatmap: list[dict[str, Any]], book_groups: dict[str, Any] | None, policy: dict[str, Any]) -> list[dict[str, Any]]:
    """Stressed / weak / not-measured sector and theme groups where the book holds under ``fold_below_usd``."""
    lim = _f(((policy.get("home_actions") or {}).get("sectors") or {}).get("fold_below_usd", 0))
    out = []
    for h in heatmap:
        if h.get("kind") not in ("sector", "theme") or h.get("state") not in FOLD_STATES:
            continue
        usd = _f(((book_groups or {}).get(h.get("key")) or {}).get("usd"))
        if usd < lim:
            out.append({"key": h.get("key"), "label": h.get("label"), "state": h.get("state"), "usd": round(usd, 2)})
    return out


# ── Glossary ────────────────────────────────────────────────────────────────────────────────────────────────────────
def glossary(policy: dict[str, Any], defense_cfg: dict[str, Any], budget_cfg: dict[str, Any] | None = None,
             path: Path | None = None) -> dict[str, dict[str, str]]:
    """Resolved tap-to-explain texts from ``config/market_risk_glossary.json``; ``{placeholder}`` from config."""
    g = (policy.get("glossary") or {})
    p = path or (ROOT / str(g.get("path") or "config/market_risk_glossary.json"))
    doc = json.loads(Path(p).read_text(encoding="utf-8"))
    if budget_cfg is None:
        try:
            try:
                from scripts.lib.market_risk.risk_budget import load_budget
            except ImportError:  # pragma: no cover
                from lib.market_risk.risk_budget import load_budget  # type: ignore
            budget_cfg = load_budget()
        except (OSError, ValueError):
            budget_cfg = {}
    acc = ((budget_cfg or {}).get("accounts") or {}).get("default") or {}
    fill = {
        "single_sector_pct": acc.get("max_single_sector_pct"),
        "trigger_book_pct": (defense_cfg.get("inverse_etf") or {}).get("trigger_book_pct"),
        "index_trigger_lagging_sectors": (defense_cfg.get("inverse_etf") or {}).get("index_trigger_lagging_sectors"),
    }
    out = {}
    for k, v in (doc.get("terms") or {}).items():
        text = str(v.get("text") or "")
        for a, b in fill.items():
            if b is not None:
                text = text.replace("{" + a + "}", f"{float(b):g}")
        out[k] = {"label": str(v.get("label") or k), "text": text}
    return out


def unresolved_placeholders(terms: dict[str, dict[str, str]]) -> list[str]:
    return [k for k, v in terms.items() if re.search(r"\{[a-z_]+\}", v.get("text", ""))]


def has_action_verb(text: str) -> bool:
    return bool(_ACTION.search(text or ""))
