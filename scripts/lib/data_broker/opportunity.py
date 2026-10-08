"""Opportunity engine — risk/reward ladder, six factor scores, conviction, rank, type, condition, stance.

Investment Command Center (operator 2026-10-08): "I can see that something is actionable, but I cannot immediately
determine why it is attractive versus competing opportunities." For every symbol in the universe this module
computes, from stores the platform already holds (zero provider calls, read-only):

  * a risk/reward ladder — entry, invalidation level, T1..T3, $ and % risk, % reward per target, R:R;
  * six 0-100 factor scores — technical, fundamental, analyst, momentum, risk/reward, portfolio fit — and a weighted
    conviction score (missing factors dropped and the rest re-normalised; ``coverage`` says how much was real);
  * the opportunity type, technical condition, market-cap band, position status and a CIO stance label.

Every rule and threshold lives in config/opportunity_conviction.yaml. The pure functions (``assess``) take one
symbol's gathered context; ``gather`` does the batched reads. The curated result is persisted in CIO memory by
scripts/cio_opportunity_curator.py — this module never writes.

MBI_BEHAVIOR = 0: levels are analysis references, never orders. Keys deliberately avoid the CIO-memory behaviour
fields (no ``stop``/``limit``/``size``/``qty``/``order``): ``entry_ref``, ``invalidation_level``, ``targets``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "opportunity_conviction.yaml"
SCHEMA = "OpportunityAssessment@v1"
SORTS = ("conviction", "rr", "upside", "reward_pct", "risk_pct", "momentum", "rank")
TYPES = ("new_position", "existing", "re_entry", "add_on", "exit_candidate", "watchlist")
CONDITIONS = ("breaking_out", "pullback", "oversold", "overbought", "trend_continuation", "range")
POSITION_STATUSES = ("owned", "not_owned", "recently_sold", "watchlist")
_cfg: dict[str, Any] = {"mtime": None, "cfg": None}


def load_config() -> dict[str, Any]:
    import yaml

    m = CONFIG_PATH.stat().st_mtime
    if _cfg["mtime"] != m:
        _cfg["cfg"] = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        _cfg["mtime"] = m
    return _cfg["cfg"]


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _iso(v: Any) -> Optional[str]:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v else None)


# ── risk / reward ───────────────────────────────────────────────────────────


def risk_reward(ctx: dict[str, Any]) -> dict[str, Any]:
    """Entry → invalidation → T1..T3 with the source of every level. Pure."""
    cfg = load_config().get("levels") or {}
    last = _f((ctx.get("quote") or {}).get("price"))
    plan = ctx.get("ladder") or {}
    strat = ctx.get("strategy") or {}
    an = ctx.get("analyst") or {}
    ind = ctx.get("indicators") or {}

    lo, hi = _f(plan.get("entry_zone_low")), _f(plan.get("entry_zone_high"))
    entry, entry_src = None, None
    for v, src in ((plan.get("suggested_entry"), "entry_plan.suggested_entry"),
                   ((lo + hi) / 2 if lo and hi else None, "entry_plan.zone_mid"),
                   (strat.get("ideal_entry"), "strategy_card.ideal_entry"), (last, "current_price")):
        if _f(v):
            entry, entry_src = _f(v), src
            break
    inval, inval_src = None, None
    for v, src in ((plan.get("invalidation_level"), "entry_plan"), (strat.get("stop_loss"), "strategy_card")):
        if _f(v) and entry and _f(v) < entry:
            inval, inval_src = _f(v), src
            break
    atr = _f(ind.get("atr"))
    if inval is None and entry and atr:
        inval, inval_src = round(entry - float(cfg.get("atr_invalidation_mult") or 2.0) * atr, 4), "atr"

    targets: list[dict[str, Any]] = []
    for t in plan.get("targets") or []:
        if _f(t.get("px")) and entry and _f(t["px"]) > entry:
            targets.append({"label": t.get("label") or f"T{len(targets) + 1}", "px": _f(t["px"]), "source": "entry_plan"})
    if not targets:
        for v, lab, src in ((plan.get("plan_target"), "Plan target", "entry_plan"),
                            (strat.get("target_price"), "Strategy target", "strategy_card")):
            if _f(v) and entry and _f(v) > entry:
                targets.append({"label": lab, "px": _f(v), "source": src})
                break
    if cfg.get("analyst_targets_as_ladder", True):
        have = {round(t["px"], 2) for t in targets}
        for v, lab in ((an.get("target_mean"), "Street mean"), (an.get("target_high"), "Street high")):
            if len(targets) < 3 and _f(v) and entry and _f(v) > entry and round(_f(v), 2) not in have:
                targets.append({"label": lab, "px": _f(v), "source": "analyst"})
                have.add(round(_f(v), 2))
    targets = sorted(targets, key=lambda t: t["px"])[:3]
    for i, t in enumerate(targets):
        t["tier"] = f"T{i + 1}"
        t["reward_pct"] = round((t["px"] - entry) / entry * 100, 2) if entry else None

    out: dict[str, Any] = {"entry_ref": entry, "entry_source": entry_src, "current_price": last,
                           "entry_zone": [lo, hi] if lo and hi else None,
                           "invalidation_level": inval, "invalidation_source": inval_src, "targets": targets}
    if entry and inval and entry > inval:
        risk_ps = entry - inval
        out["risk_per_share"] = round(risk_ps, 4)
        out["risk_pct"] = round(risk_ps / entry * 100, 2)
        if targets:
            # R:R is measured to the PRIMARY target (operator example: entry 40, stop 36, target 52 → 3.0x). Plan
            # ladders put T1 at +1R by construction, so T1 would make every planned R:R exactly 1.0.
            pt = _f(plan.get("plan_target"))
            primary = next((t for t in targets if pt and abs(t["px"] - pt) < 1e-6), None) or (
                targets[1] if len(targets) > 1 and targets[0]["source"] == "entry_plan"
                and "1r" in str(targets[0]["label"]).lower().replace(" ", "") else targets[0])
            primary["primary"] = True
            out["primary_target"] = primary["px"]
            out["reward_pct"] = primary["reward_pct"]
            rr = round((primary["px"] - entry) / risk_ps, 2)
            if out["risk_pct"] < float(cfg.get("min_risk_pct") or 1.0):
                out["rr_raw"], out["rr_flag"] = rr, "invalidation too close to entry"
            elif rr > float(cfg.get("max_rr") or 15):
                out["rr_raw"], out["rr_flag"] = rr, "implausible R:R"
            else:
                out["rr"] = rr
            trust = cfg.get("source_trust") or {}
            out["level_trust"] = min(float(trust.get(inval_src or "", 0.6)), float(trust.get(primary["source"], 0.6)),
                                     1.0 if (entry_src or "").startswith("entry_plan") else 0.75)
    return out


# ── factor scores ───────────────────────────────────────────────────────────


def _piecewise(x: float, pts: list[list[float]]) -> float:
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def factors(ctx: dict[str, Any], rr: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """{factor: {score 0-100, detail}} — a factor without inputs is absent (dropped, not neutral). Pure."""
    cfg = load_config()
    sc = cfg.get("scoring") or {}
    out: dict[str, dict[str, Any]] = {}
    hc = ctx.get("hermes") or {}
    ind = ctx.get("indicators") or {}
    st = ctx.get("stats") or {}
    an = ctx.get("analyst") or {}
    q = ctx.get("quote") or {}

    # technical: Hermes momentum + setup quality, else MA alignment adjusted by RSI
    hs = [_f((hc.get(k) or {}).get("score")) for k in ("technical_momentum", "setup_quality")]
    hs = [x for x in hs if x is not None]
    align = ind.get("alignment") or st.get("ma_alignment")
    if hs:
        out["technical"] = {"score": round(sum(hs) / len(hs), 1),
                            "detail": "; ".join(str((hc.get(k) or {}).get("detail") or "") for k in
                                                ("technical_momentum", "setup_quality") if hc.get(k))[:160],
                            "source": "hermes_score_components"}
    elif align:
        base = float((sc.get("alignment_score") or {}).get(str(align).lower(), 50))
        rsi = _f(ind.get("rsi"))
        if rsi is not None:
            base += 10 if 45 <= rsi <= 65 else (-10 if rsi > 75 or rsi < 25 else 0)
        out["technical"] = {"score": round(_clip(base), 1), "detail": f"MA alignment {align}"
                            + (f", RSI {rsi:.0f}" if rsi is not None else ""), "source": "indicator_confluence_cache"}

    # fundamental: sparse fundamental_data (ROE, margin, forward PE)
    fd = ctx.get("fundamentals") or {}
    pts = []
    if _f(fd.get("ROE")) is not None:
        pts.append(_clip(50 + _f(fd["ROE"]) * (100 if abs(_f(fd["ROE"])) < 2 else 1) * 1.5))
    if _f(fd.get("ProfitMargin")) is not None:
        pts.append(_clip(50 + _f(fd["ProfitMargin"]) * (100 if abs(_f(fd["ProfitMargin"])) < 2 else 1) * 1.5))
    fpe = _f(fd.get("ForwardPE"))
    if fpe is not None and fpe > 0:
        pts.append(_clip(100 - (fpe - 10) * 2.5))
    if len(pts) >= int(sc.get("fundamental_min_metrics") or 2):
        out["fundamental"] = {"score": round(sum(pts) / len(pts), 1), "detail": ", ".join(
            f"{k} {fd[k]}" for k in ("ROE", "ProfitMargin", "ForwardPE") if fd.get(k) is not None)[:160],
            "source": "fundamental_data"}

    # analyst: recommendation mean + upside, when enough analysts cover it
    cnt = _f(an.get("analyst_count")) or 0
    last = _f(q.get("price"))
    tm = _f(an.get("target_mean"))
    upside = round((tm - last) / last * 100, 2) if tm and last else _f(an.get("upside_pct"))
    rmean = _f(an.get("recommendation_mean"))
    if upside is not None and upside > float(sc.get("analyst_upside_sanity_pct") or 150):
        upside = None  # implausible target (stale or penny stock) — flagged in assess(), never scored
    if cnt >= float(sc.get("analyst_min_count") or 3) and (rmean is not None or upside is not None):
        w = float(sc.get("analyst_mean_weight") or 0.6)
        parts, ws = [], []
        if rmean is not None:
            parts.append(_clip((5 - rmean) / 4 * 100))
            ws.append(w)
        if upside is not None:
            parts.append(_clip(50 + upside / float(sc.get("analyst_upside_full_pct") or 40) * 50))
            ws.append(1 - w)
        out["analyst"] = {"score": round(sum(p * x for p, x in zip(parts, ws)) / sum(ws), 1),
                          "detail": f"{an.get('recommendation_key') or '—'} · {int(cnt)} analysts"
                          + (f" · {upside:+.1f}% to mean target" if upside is not None else ""),
                          "source": an.get("source") or "analyst"}

    # momentum: 1-month and 1-week change, plus relative volume on an up day
    m1, w1, rv = _f(st.get("change_1m_pct")), _f(st.get("change_1w_pct")), _f(st.get("relative_volume"))
    if m1 is not None or w1 is not None:
        s = 50 + (m1 or 0) * float(sc.get("momentum_1m_mult") or 1.2) + (w1 or 0) * float(sc.get("momentum_1w_mult") or 2.0)
        if rv and rv >= 1.5 and (_f(q.get("day_change_pct")) or 0) > 0:
            s += float(sc.get("momentum_rvol_bonus") or 10)
        out["momentum"] = {"score": round(_clip(s), 1), "detail": ", ".join(x for x in (
            f"1W {w1:+.1f}%" if w1 is not None else "", f"1M {m1:+.1f}%" if m1 is not None else "",
            f"RVOL {rv:.2f}" if rv else "") if x), "source": "price_stats"}

    # risk/reward
    if rr.get("rr") is not None:
        trust = float(rr.get("level_trust") or 1.0)
        raw = _piecewise(rr["rr"], sc.get("rr_points") or [[0, 0], [5, 100]])
        out["risk_reward"] = {"score": round(raw * trust, 1),
                              "detail": f"R:R {rr['rr']:.1f}x · risk {rr.get('risk_pct')}% · reward {rr.get('reward_pct')}%"
                              + (f" · levels from {rr.get('invalidation_source')} (trust {trust:.2f})" if trust < 1 else ""),
                              "source": "risk_reward"}

    # portfolio fit: position weight and sector concentration
    pc = ctx.get("position") or {}
    sector_w = _f((ctx.get("sector_weights") or {}).get(str((ctx.get("profile") or {}).get("sector") or "").lower()))
    if ctx.get("portfolio_known"):
        s = float(sc.get("fit_base") or 60)
        notes = []
        wpct = _f(pc.get("weight_pct"))
        if wpct is not None and wpct >= float(sc.get("fit_position_cap_pct") or 10):
            s -= 35
            notes.append(f"position {wpct:.1f}% of book")
        if sector_w is not None:
            if sector_w >= float(sc.get("fit_sector_cap_pct") or 30):
                s -= 20
                notes.append(f"sector {sector_w:.0f}% of book")
            elif sector_w < float(sc.get("fit_sector_light_pct") or 5):
                s += 15
                notes.append(f"sector only {sector_w:.1f}% of book")
        out["portfolio_fit"] = {"score": round(_clip(s), 1), "detail": "; ".join(notes) or "no concentration flag",
                                "source": "portfolio_snapshot"}
    return out


def conviction(fx: dict[str, dict[str, Any]]) -> tuple[Optional[float], float]:
    """(weighted 0-100 conviction, coverage 0-1). Missing factors re-normalised away."""
    w = {k: float(v.get("weight") or 0) for k, v in (load_config().get("factors") or {}).items()}
    tot = sum(w.values()) or 1.0
    have = {k: v["score"] for k, v in fx.items() if k in w and v.get("score") is not None}
    if not have:
        return None, 0.0
    hw = sum(w[k] for k in have)
    return round(sum(w[k] * have[k] for k in have) / hw, 1), round(hw / tot, 3)


# ── classification ──────────────────────────────────────────────────────────


def _cond_holds(cond: dict[str, Any], c: dict[str, Any]) -> bool:
    for k, v in cond.items():
        if k == "held" and bool(c["held"]) is not bool(v):
            return False
        if k == "stance_in" and c.get("stance") not in v:
            return False
        if k == "min_conviction" and (c.get("conviction") or 0) < float(v):
            return False
        if k == "max_conviction" and (c.get("conviction") if c.get("conviction") is not None else 101) > float(v):
            return False
        if k == "min_rr" and (c.get("rr") or 0) < float(v):
            return False
        if k == "min_weight_pct" and (c.get("weight_pct") or 0) < float(v):
            return False
        if k == "reentry_or_recently_sold" and bool(c.get("reentry_or_recently_sold")) is not bool(v):
            return False
        if k == "min_coverage" and (c.get("coverage") or 0) < float(v):
            return False
    return True


def technical_condition(ctx: dict[str, Any]) -> str:
    cfg = load_config().get("conditions") or {}
    ind, st, q = ctx.get("indicators") or {}, ctx.get("stats") or {}, ctx.get("quote") or {}
    rsi, last = _f(ind.get("rsi")), _f(q.get("price"))
    align = str(ind.get("alignment") or st.get("ma_alignment") or "").lower()
    s20, s50 = _f(st.get("sma_20")), _f(st.get("sma_50"))
    hi, rv = _f(st.get("high_52w")), _f(st.get("relative_volume"))
    for name, c in cfg.items():
        ok = True
        if "rsi_min" in c and (rsi is None or rsi < float(c["rsi_min"])):
            ok = False
        if "rsi_max" in c and (rsi is None or rsi > float(c["rsi_max"])):
            ok = False
        if "near_52w_high_pct" in c and not (last and hi and last >= hi * (1 - float(c["near_52w_high_pct"]) / 100)):
            ok = False
        if "rvol_min" in c and (rv or 0) < float(c["rvol_min"]):
            ok = False
        if "alignment_in" in c and align not in [str(x).lower() for x in c["alignment_in"]]:
            ok = False
        if c.get("below_sma20") and not (last and s20 and last < s20):
            ok = False
        if c.get("above_sma50") and not (last and s50 and last > s50):
            ok = False
        if ok:
            return name
    return "range"


def cap_band(mc: Optional[float]) -> Optional[str]:
    if not mc:
        return None
    bands = load_config().get("cap_bands") or {}
    for name in ("mega", "large", "mid", "small"):
        if mc >= float(bands.get(name, 0)):
            return name
    return "small"


STANCE_WHY = {
    "EXIT": "Conviction has fallen to {conv}; the case for holding would need the invalidation conditions cleared.",
    "TRIM": "The position is {w}% of the book — above the concentration line; a smaller weight would reduce single-name risk.",
    "ADD": "Conviction {conv} with R:R {rr}x; an add would fit if price holds above the invalidation level.",
    "RE_ENTER": "Previously owned; conviction {conv} with R:R {rr}x — a re-entry would make sense if the setup confirms.",
    "HOLD": "Owned; conviction {conv} — nothing in the factors argues for a change today.",
    "WATCH": "Not owned; conviction {conv} — worth tracking until the factors or the setup improve.",
}


def classify(ctx: dict[str, Any], conv: Optional[float], rr: dict[str, Any], coverage: float = 1.0) -> dict[str, Any]:
    cfg = load_config()
    pc = ctx.get("position") or {}
    held = bool(pc.get("owned"))
    recent = bool(ctx.get("reentry_state")) or bool(pc.get("recently_sold"))
    c = {"held": held, "conviction": conv, "rr": rr.get("rr"), "weight_pct": _f(pc.get("weight_pct")),
         "reentry_or_recently_sold": recent, "coverage": coverage}
    sc = cfg.get("stance") or {}
    stance = "HOLD" if held else "WATCH"
    for name, key in (("EXIT", "exit_if"), ("TRIM", "trim_if"), ("ADD", "add_if"), ("RE_ENTER", "re_enter_if")):
        if sc.get(key) and _cond_holds(sc[key], c):
            stance = name
            break
    c["stance"] = stance
    typ = "watchlist"
    for name, cond in (cfg.get("types") or {}).items():
        if _cond_holds(cond or {}, c):
            typ = name
            break
    status = "owned" if held else ("recently_sold" if pc.get("recently_sold") else (
        "watchlist" if ctx.get("on_watchlist") else "not_owned"))
    why = STANCE_WHY[stance].format(conv=f"{conv:.0f}" if conv is not None else "n/a",
                                    rr=f"{rr['rr']:.1f}" if rr.get("rr") is not None else "n/a",
                                    w=f"{c['weight_pct']:.1f}" if c["weight_pct"] is not None else "n/a")
    return {"type": typ, "stance": stance, "stance_rationale": why, "position_status": status,
            "technical_condition": technical_condition(ctx),
            "cap_band": cap_band(_f((ctx.get("profile") or {}).get("market_cap_usd")))}


def assess(symbol: str, ctx: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """The curated assessment for one symbol. Pure given ctx."""
    now = now or datetime.now(timezone.utc)
    rr = risk_reward(ctx)
    fx = factors(ctx, rr)
    conv, cov = conviction(fx)
    cls = classify(ctx, conv, rr, cov)
    an = ctx.get("analyst") or {}
    last = _f((ctx.get("quote") or {}).get("price"))
    tm = _f(an.get("target_mean"))
    w = load_config().get("factors") or {}
    up = round((tm - last) / last * 100, 2) if tm and last else _f(an.get("upside_pct"))
    return {
        "schema": SCHEMA,
        "symbol": symbol,
        "as_of": now.isoformat(),
        "conviction": conv,
        "coverage": cov,
        "rankable": conv is not None and cov >= float(load_config().get("min_coverage") or 0.5),
        "factors": {k: {**v, "label": (w.get(k) or {}).get("label", k), "weight": (w.get(k) or {}).get("weight")}
                    for k, v in fx.items()},
        "factors_missing": [k for k in w if k not in fx],
        "risk_reward": rr,
        "upside_pct": up,
        "upside_flag": ("implausible target — check freshness" if up is not None and up > float(
            (load_config().get("scoring") or {}).get("analyst_upside_sanity_pct") or 150) else (
            "analyst data stale" if an.get("stale") else None)),
        "momentum_score": (fx.get("momentum") or {}).get("score"),
        **cls,
        "sector": (ctx.get("profile") or {}).get("sector"),
        "industry": (ctx.get("profile") or {}).get("industry"),
        "company": (ctx.get("profile") or {}).get("company"),
        "market_cap_usd": _f((ctx.get("profile") or {}).get("market_cap_usd")),
        "reentry_state": ctx.get("reentry_state"),
        "inputs_as_of": {k: _iso(v) for k, v in (ctx.get("as_of") or {}).items()},
        "authority": "READ_ONLY_ADVISORY",
    }


def rank(assessments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank rankable assessments by conviction (ties: R:R, then upside); others get rank None."""
    ok = sorted([a for a in assessments if a.get("rankable")],
                key=lambda a: (-(a.get("conviction") or 0), -((a.get("risk_reward") or {}).get("rr") or 0),
                               -(a.get("upside_pct") or 0), a["symbol"]))
    for i, a in enumerate(ok, 1):
        a["rank"] = i
    for a in assessments:
        a.setdefault("rank", None)
    return assessments


# ── list filters, sorts, presets ────────────────────────────────────────────


def _csv(v: Any) -> set[str]:
    return {x.strip().lower() for x in str(v or "").split(",") if x.strip()}


def passes(a: dict[str, Any], q: dict[str, Any]) -> bool:
    rr = (a.get("risk_reward") or {}).get("rr")
    for key, val in (("type", a.get("type")), ("technical_condition", a.get("technical_condition")),
                     ("cap_band", a.get("cap_band")), ("position_status", a.get("position_status")),
                     ("stance", (a.get("stance") or "").lower())):
        want = _csv(q.get(key))
        if want and str(val or "").lower() not in want:
            return False
    sectors = _csv(q.get("sector"))
    if sectors and str(a.get("sector") or "").lower() not in sectors:
        return False
    for key, val in (("min_conviction", a.get("conviction")), ("min_rr", rr), ("min_upside", a.get("upside_pct")),
                     ("min_coverage", a.get("coverage"))):
        v = _f(q.get(key))
        if v is not None and (val is None or val < v):
            return False
    s = str(q.get("q") or "").strip().upper()
    if s and s not in f"{a['symbol']} {a.get('company') or ''} {a.get('sector') or ''}".upper():
        return False
    return True


def sort_items(items: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    sort = (sort or "conviction").lower()

    def key(a: dict[str, Any]):
        rr = a.get("risk_reward") or {}
        if sort == "rank":
            return (a.get("rank") is None, a.get("rank") or 0)
        if sort == "risk_pct":
            return (rr.get("risk_pct") is None, rr.get("risk_pct") or 0)  # lowest risk first
        v = {"conviction": a.get("conviction"), "rr": rr.get("rr"),
             "upside": None if (a.get("upside_flag") or "").startswith("implausible") else a.get("upside_pct"),
             "reward_pct": rr.get("reward_pct"), "momentum": a.get("momentum_score")}.get(sort, a.get("conviction"))
        return (v is None, -(v or 0), -(a.get("conviction") or 0))

    return sorted(items, key=key)


def apply_preset(q: dict[str, Any]) -> dict[str, Any]:
    p = (load_config().get("presets") or {}).get(str(q.get("preset") or "").lower())
    if not p:
        return q
    merged = {**{k: v for k, v in p.items()}, **{k: v for k, v in q.items() if k != "preset"}}
    return merged


# ── gather (batched reads) ──────────────────────────────────────────────────


def _rows(db_query, sql: str, params: Any) -> list[dict[str, Any]]:
    try:
        return list(db_query(sql, params) or [])
    except Exception:
        return []


def universe(db_query) -> list[str]:
    """Held + active watchlist + re-entry desk + fresh technicals + fresh analyst targets (~1,000)."""
    u = load_config().get("universe") or {}
    syms: set[str] = set()
    for r in _rows(db_query, """SELECT DISTINCT upper(symbol) AS s FROM watchlist_items
                                 WHERE status = ANY(%s)""", (list(u.get("include_watchlist_status") or ["active"]),)):
        syms.add(r["s"])
    for r in _rows(db_query, """SELECT DISTINCT upper(symbol) AS s FROM indicator_confluence_cache
                                 WHERE profile = 'swing' AND computed_at > now() - (%s || ' days')::interval""",
                   (str(int(u.get("confluence_fresh_days") or 7)),)):
        syms.add(r["s"])
    for r in _rows(db_query, """SELECT DISTINCT upper(symbol) AS s FROM yahoo_analyst_targets_history
                                 WHERE created_at > now() - (%s || ' days')::interval AND target_mean_price IS NOT NULL""",
                   (str(int(u.get("analyst_fresh_days") or 30)),)):
        syms.add(r["s"])
    try:
        from lib.data_broker.watch_domains import membership_held

        syms |= set(membership_held()[0])
    except Exception:
        pass
    try:
        from lib.data_broker.watch_decision import reentry_rows

        syms |= set(reentry_rows())
    except Exception:
        pass
    # broker settlement ids (9-char alnum, no punctuation) never resolve — same filter as the Watch universe
    return sorted(s for s in syms if s and not (len(s) == 9 and s.isalnum() and not s.isalpha()))


def gather(db_query, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """One batched read per source → {SYMBOL: ctx}. Every block carries its own source; missing stays missing."""
    from lib.data_broker.analyst_detail import get_analyst_targets
    from lib.data_broker.analyst_rollup import get_analyst_rollup
    from lib.data_broker.entry_plan import get_entry_ladders
    from lib.data_broker.market_quote import get_price_batch
    from lib.data_broker.positions_context import get_positions_context
    from lib.data_broker.price_stats import get_price_stats
    from lib.data_broker.symbol_profile import get_symbol_profiles
    from lib.data_broker.watch_domains import enrichment_batch

    syms = sorted({s.upper() for s in symbols if s})
    ctx: dict[str, dict[str, Any]] = {s: {"as_of": {}} for s in syms}
    try:
        quotes = get_price_batch(db_query, syms, skip_live=True) or {}
    except Exception:
        quotes = {}
    for r in _rows(db_query, """SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s, price, prev_close,
                                       day_change_pct, volume, fetched_at
                                  FROM market_quotes WHERE upper(symbol) = ANY(%s)
                                 ORDER BY upper(symbol), fetched_at DESC""", (syms,)):
        q = ctx[r["s"]].setdefault("quote", {})
        q.update(price=_f(r.get("price")), prev_close=_f(r.get("prev_close")),
                 day_change_pct=_f(r.get("day_change_pct")), volume=_f(r.get("volume")), as_of=_iso(r.get("fetched_at")))
        ctx[r["s"]]["as_of"]["quote"] = r.get("fetched_at")
    for s, q in quotes.items():
        if s in ctx and not (ctx[s].get("quote") or {}).get("price"):
            ctx[s]["quote"] = {"price": _f(q.get("price")), "day_change_pct": _f(q.get("chg_pct")), "source": q.get("source")}
    for s, st in (get_price_stats(db_query, syms) or {}).items():
        ctx[s]["stats"] = st
        ctx[s]["as_of"]["stats"] = st.get("as_of")
    for r in _rows(db_query, """SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s, full_result, atr, key_levels,
                                       computed_at FROM indicator_confluence_cache
                                 WHERE upper(symbol) = ANY(%s) AND profile = 'swing'
                                 ORDER BY upper(symbol), computed_at DESC""", (syms,)):
        from lib.data_broker.indicator_snapshot import _normalize_symbol_row

        ind = _normalize_symbol_row(r["s"], r.get("full_result"), r.get("atr"))
        kl = r.get("key_levels") or {}
        if isinstance(kl, str):
            import json

            try:
                kl = json.loads(kl)
            except ValueError:
                kl = {}
        pv = (kl or {}).get("pivots_weekly") or {}
        ind["levels"] = {k: _f(pv.get(k)) for k in ("s1", "s2", "r1", "r2", "pp")}
        ctx[r["s"]]["indicators"] = ind
        ctx[r["s"]]["as_of"]["indicators"] = r.get("computed_at")
    authority = get_analyst_targets(db_query, syms) or {}
    try:
        pills = get_analyst_rollup(syms) or {}
    except Exception:
        pills = {}
    for s in syms:
        a = authority.get(s)
        p = pills.get(s) or {}
        if a and _f(a.get("target_mean")):
            ctx[s]["analyst"] = {**a, "recommendation_mean": p.get("recommendation_mean"),
                                 "source": "yahoo_analyst_targets_history"}
            ctx[s]["as_of"]["analyst"] = a.get("created_at")
        elif p and _f(p.get("mean_target")):
            ctx[s]["analyst"] = {"target_mean": p.get("mean_target"), "target_high": p.get("target_high"),
                                 "target_low": p.get("target_low"), "recommendation_key": p.get("rec_key"),
                                 "recommendation_mean": p.get("recommendation_mean"),
                                 "analyst_count": p.get("analyst_count"), "upside_pct": p.get("upside_pct"),
                                 "stale": p.get("stale"), "source": "pro_analyst_pills"}
            ctx[s]["as_of"]["analyst"] = p.get("as_of")
    for s, lad in (get_entry_ladders(db_query, syms) or {}).items():
        ctx[s]["ladder"] = lad
        ctx[s]["as_of"]["entry_plan"] = lad.get("created_at")
    for r in _rows(db_query, """SELECT upper(symbol) AS s, ideal_entry, stop_loss, target_price, support, resistance,
                                       updated_at FROM watchlist_strategy_cards WHERE upper(symbol) = ANY(%s)""", (syms,)):
        ctx[r["s"]]["strategy"] = r
    for r in _rows(db_query, """SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s, hermes_score_components
                                  FROM watchlist_items WHERE upper(symbol) = ANY(%s) AND hermes_score_components IS NOT NULL
                                 ORDER BY upper(symbol), hermes_scored_at DESC NULLS LAST""", (syms,)):
        hc = r.get("hermes_score_components")
        if isinstance(hc, str):
            import json

            try:
                hc = json.loads(hc)
            except ValueError:
                hc = {}
        ctx[r["s"]]["hermes"] = hc or {}
    for r in _rows(db_query, """SELECT DISTINCT upper(symbol) AS s FROM watchlist_items
                                 WHERE upper(symbol) = ANY(%s) AND status = 'active'""", (syms,)):
        ctx[r["s"]]["on_watchlist"] = True
    for r in _rows(db_query, """SELECT DISTINCT ON (upper(symbol), metric_name) upper(symbol) AS s, metric_name,
                                       metric_value FROM fundamental_data WHERE upper(symbol) = ANY(%s)
                                 ORDER BY upper(symbol), metric_name, fetched_at DESC""", (syms,)):
        ctx[r["s"]].setdefault("fundamentals", {})[r["metric_name"]] = _f(r.get("metric_value"))
    profiles = get_symbol_profiles(db_query, syms) or {}
    enrich = enrichment_batch(syms) or {}
    for s in syms:
        p = profiles.get(s) or {}
        e = enrich.get(s) or {}
        ctx[s]["profile"] = {"sector": p.get("sector") or e.get("sector"), "industry": p.get("industry") or e.get("industry"),
                             "company": p.get("company") or p.get("name") or e.get("company") or e.get("name"),
                             "next_earnings_date": _iso(p.get("next_earnings_date")),
                             # market_cap_usd is dollars; the cache's market_cap_b is millions (mislabelled)
                             "market_cap_usd": _f(e.get("market_cap_usd"))}
    pos = get_positions_context(db_query, syms) or {}
    sold_days = int((load_config().get("universe") or {}).get("recently_sold_days") or 180)
    cutoff = (date.today() - timedelta(days=sold_days)).isoformat()
    try:
        from lib.data_broker.watch_decision import reentry_rows

        desk = reentry_rows()
    except Exception:
        desk = {}
    portfolio_known = bool(pos) or _held_any()
    sw = sector_weights()
    for s in syms:
        pc = dict(pos.get(s) or {})
        pc["recently_sold"] = bool(not pc.get("owned") and (pc.get("last_sell_date") or "") >= cutoff)
        ctx[s]["position"] = pc
        ctx[s]["portfolio_known"] = portfolio_known
        ctx[s]["sector_weights"] = sw
        if s in desk:
            ctx[s]["reentry_state"] = desk[s].get("state")
    return ctx


def _held_any() -> bool:
    try:
        from lib.data_broker.watch_domains import membership_held

        return bool(membership_held()[0])
    except Exception:
        return False


def sector_weights() -> dict[str, float]:
    """{sector lower: % of book} from the portfolio snapshot's sector allocation."""
    try:
        from lib.data_broker.portfolio_snapshot import get_portfolio_snapshot

        snap = get_portfolio_snapshot(write_on_miss=False) or {}
    except Exception:
        return {}
    out: dict[str, float] = {}
    for row in snap.get("sector_allocation") or []:
        try:
            name, pct = (row[0], row[1]) if isinstance(row, (list, tuple)) else (row.get("sector"), row.get("pct"))
            out[str(name).lower()] = float(pct)
        except (TypeError, ValueError, IndexError, AttributeError):
            continue
    return out
