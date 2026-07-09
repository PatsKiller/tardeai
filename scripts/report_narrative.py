"""report_narrative.py — professional analyst voice and true synthesis for holding reports."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _pct(v: Any) -> str:
    if v is None:
        return "—"
    return f"{_f(v):+.2f}%"


def _money(v: Any) -> str:
    n = _f(v)
    if n == 0 and v is None:
        return "—"
    return f"${n:,.2f}"


def strip_md(text: str) -> str:
    return re.sub(r"\*+", "", str(text or "")).strip()


def _rec_bucket(rec: str) -> str:
    u = str(rec or "").upper()
    for k in ("STRONG BUY", "STRONG_BUY", "ADD", "BUY", "HOLD", "TRIM", "SELL", "AVOID", "MONITOR"):
        if k.replace("_", " ") in u or k in u:
            return k.replace("_", " ")
    return u.split()[0] if u else "—"


def thesis_rationale(
    thesis: str,
    *,
    synthesis: dict | None,
    proposal: dict | None,
    enrich: dict,
    gl_pct: float | None,
    ensemble: dict | None,
) -> str:
    reasons: list[str] = []
    ens = str((ensemble or {}).get("final_decision") or "").lower()
    if thesis == "Broken":
        return "Thesis invalidated — price or fundamentals have breached defined stop/invalidation criteria."
    if thesis == "At risk":
        if ens == "block":
            reasons.append("Layer 4 ensemble blocked new risk")
        if gl_pct is not None and _f(gl_pct) < -25:
            reasons.append("material personal drawdown from cost basis")
        tv = (proposal or {}).get("thesis_validity") or {}
        if str(tv.get("zone_status") or "").lower() in ("at_risk", "stressed", "warning"):
            reasons.append("broker thesis zone under stress")
        if (synthesis or {}).get("conflicts_detected"):
            reasons.append("synthesis flagged internal conflicts")
        return (
            "Thesis under pressure because " + ", ".join(reasons[:3]) + "."
            if reasons else "Thesis requires closer monitoring — risk flags present but not yet broken."
        )
    if ens == "block":
        return "Core thesis intact, but ensemble gate blocks adding until risk checks clear."
    if gl_pct is not None and _f(gl_pct) < -30:
        return "Thesis narrative intact on fundamentals, but personal book shows deep unrealized loss — size discipline required."
    return "No material invalidation signals; original investment case remains operable."


def action_recommendation_line(
    rec: str,
    *,
    price: float,
    proposal: dict | None,
    pro: dict | None,
    thesis: str,
    levels: dict | None = None,
    held_shares: float | None = None,
) -> str:
    rec_u = _rec_bucket(rec)
    levels = levels or {}
    held = _f(held_shares)
    stop = _f((proposal or {}).get("proposed_stop")) or _f(levels.get("stop")) or None
    target = _f((proposal or {}).get("proposed_target1")) or _f((pro or {}).get("target_mean_price")) or _f(levels.get("target"))
    # Single source of truth for the accumulation band (matches the action-plan bullets).
    add_low = _f(levels.get("valid_low")) or stop or (price * 0.97 if price else 0)
    add_high = _f(levels.get("entry")) or price
    target_is_analyst = bool(levels.get("target_is_analyst")) or bool((proposal or {}).get("proposed_target1"))
    if "AVOID" in rec_u:
        if held < 1:
            if stop:
                return (f"Do not initiate; remain off-book until thesis and data quality clear. "
                        f"Reassess only on a defined plan breach below ${stop:,.2f}.")
            return "Do not initiate; remain off-book until thesis and data quality clear."
        if stop:
            return f"Reduce or exit exposure; maintain stops and review on breach of ${stop:,.2f}."
        return f"Reduce or exit exposure at current levels (${price:,.2f}); thesis is {thesis.lower()}."
    if "ADD" in rec_u or "BUY" in rec_u:
        if held < 1:
            if add_low and add_high:
                lo, hi = min(add_low, add_high), max(add_low, add_high)
                tgt = f" toward the ${target:,.2f} consensus target" if (target and target > price and target_is_analyst) else ""
                return f"Initiate between ${lo:,.2f} and ${hi:,.2f}{tgt}; do not chase above ${price * 1.03:,.2f}."
        if add_low and add_high:
            lo, hi = min(add_low, add_high), max(add_low, add_high)
            # only cite a "target" when it is analyst/plan-derived — never present a synthetic +12% as one
            tgt = f" toward the ${target:,.2f} consensus target" if (target and target > price and target_is_analyst) else ""
            return f"Accumulate between ${lo:,.2f} and ${hi:,.2f}{tgt}; do not chase above ${price * 1.03:,.2f}."
        return "Add only on defined pullbacks — confirm size vs risk budget before committing capital."
    if "TRIM" in rec_u or "SELL" in rec_u:
        return f"Reduce exposure at current levels (${price:,.2f}); tighten risk if thesis is {thesis.lower()}."
    if "MONITOR" in rec_u:
        if held < 1:
            return "No position — monitor catalysts; do not initiate until plan confirms."
        return "No new capital — monitor catalysts and reassess after next material event."
    if "HOLD" in rec_u and held < 1:
        if stop:
            return f"No position held — wait for plan confirmation; invalidation below ${stop:,.2f}."
        return "No position held — maintain watch-only stance until entry plan confirms."
    return f"Hold current size; maintain stops and review on breach of ${stop:,.2f}." if stop else "Hold current size; no change required."


def compose_executive(
    *,
    company: str,
    sym: str,
    sector: str,
    price: float,
    day_pct: Any,
    rec: str,
    conf_label: str,
    thesis: str,
    thesis_why: str,
    action_line: str,
    synthesis: dict | None,
    enrich: dict,
    gl_pct: float | None,
    continuity: dict | None,
    synthesis_age_days: float | None = None,
) -> dict:
    """Confident executive block — narrative first, callouts separate.

    The exec lead is ALWAYS built from current structured facts. The watchlist synthesis free-text
    narrative is NOT used verbatim — it bakes in its own numbers (position weight, 'analyst upgrade',
    RSI) that drift from live enrichment and read as fabrications. Stance is still driven by rec/conf.
    """
    street = ""
    pe = enrich.get("pe")
    if pe and str(enrich.get("instrument_type") or "").lower() not in ("etf", "fund", "etn"):
        street = f" Shares screen at {pe}× trailing earnings."

    personal = ""
    if gl_pct is not None:
        personal = f" Your book shows {_pct(gl_pct)} unrealized."

    lead = (
        f"{company} ({sym}) trades at ${price:,.2f} ({_pct(day_pct)} today) in {sector}.{street}{personal} "
        f"Our stance is {rec} ({conf_label} confidence) — thesis {thesis.lower()}."
    )

    change = ""
    if continuity and not continuity.get("first_report"):
        pd = continuity.get("metrics", {}).get("price_delta_pct")
        if pd is not None:
            change = f" Since the last report, price moved {_pct(pd)}."

    content = lead + change

    return {
        "content": content,
        "metrics": {
            "recommendation": rec,
            "confidence_label": conf_label,
            "thesis_status": thesis,
            "thesis_rationale": thesis_why,
            "action_recommendation": action_line,
            "what_to_do_now": action_line,
        },
        "callouts": [
            {"label": "Action Recommendation", "text": action_line},
            {"label": "Thesis Status", "text": f"{thesis} — {thesis_why}"},
        ],
    }


_BULL = ("STRONG BUY", "STRONG_BUY", "ADD", "BUY", "ACCUMULATE", "OVERWEIGHT")
_BEAR = ("SELL", "TRIM", "REDUCE", "AVOID", "UNDERWEIGHT", "EXIT")
_NEUT = ("HOLD", "MONITOR", "WATCH", "NEUTRAL", "WAIT", "RESEARCH_MORE", "RESEARCH MORE")


def _stance_bucket(rec: str) -> str:
    """Collapse a recommendation to bullish / bearish / neutral so ADD≈BUY align."""
    u = str(rec or "").upper()
    if any(k in u for k in _BULL):
        return "bullish"
    if any(k in u for k in _BEAR):
        return "bearish"
    if any(k in u for k in _NEUT):
        return "neutral"
    return "neutral"


def synthesize_agent_collective(
    agents: list[dict],
    synthesis: dict | None,
    ensemble: dict | None,
    continuity: dict | None,
    agent_meta: dict | None = None,
) -> dict:
    """True synthesis — calibration-weighted collective view + compact relevance table.

    agents are expected pre-deduped/freshness-filtered upstream; each may carry an
    `accuracy` (0-100 calibration) used to weight its vote. agent_meta carries
    suppressed-stale count, synthesis age, and the dual-lane (Grok/ChatGPT) consensus.
    """
    agent_meta = agent_meta or {}
    evaluated: list[dict] = []
    syn_rec = str((synthesis or {}).get("recommendation") or "")
    syn_bucket = _stance_bucket(syn_rec)
    ens_dec = str((ensemble or {}).get("final_decision") or "").lower()
    aligned = divergent = noise = 0
    weighted_for = weighted_against = 0.0
    bucket_recs: list[str] = []

    for a in agents[:8]:
        agent = str(a.get("agent") or "agent").replace("_", " ")
        rec = str(a.get("recommendation") or "—")
        bucket = _stance_bucket(rec)
        bucket_recs.append(_rec_bucket(rec))
        summary = str(a.get("summary") or "")
        acc = a.get("accuracy")
        acc_f = _f(acc) if acc is not None else None
        # calibration weight: scale 0.5–1.5 around 50% accuracy, default 1.0 when unknown
        w = 1.0 if acc_f is None else max(0.4, min(1.6, 0.4 + acc_f / 62.5))

        is_aligned = (
            (syn_bucket != "neutral" and bucket == syn_bucket)
            or (ens_dec == "approve" and bucket == "bullish")
            or (ens_dec == "block" and bucket in ("bearish", "neutral"))
        )
        if len(summary) < 20:
            weight_lbl = "Low weight — thin rationale"
            noise += 1
        elif is_aligned:
            weight_lbl = "Aligned — supports synthesis"
            aligned += 1
            weighted_for += w
        else:
            weight_lbl = "Divergent — secondary input"
            divergent += 1
            weighted_against += w
        acc_note = f" · {acc_f:.0f}% hist. acc" if acc_f is not None else ""
        evaluated.append({
            "agent": agent,
            "recommendation": _rec_bucket(rec),
            "relevance": weight_lbl + acc_note,
            "weight": "Primary" if is_aligned else ("Low" if "Low weight" in weight_lbl else "Secondary"),
            "accuracy_pct": round(acc_f, 1) if acc_f is not None else None,
        })

    counts = Counter(bucket_recs)
    top_rec = counts.most_common(1)[0][0] if counts else "—"
    panel_size = len(evaluated)
    suppressed = int(agent_meta.get("suppressed_count") or 0)

    if not evaluated:
        narrative = "No fresh agent coverage on file. Weight watchlist synthesis and Layer 4 ensemble as primary intelligence."
    else:
        net = weighted_for - weighted_against
        tilt = "confirms" if net > 0.5 else ("contradicts" if net < -0.5 else "is split on")
        narrative = (
            f"Across {panel_size} fresh, de-duplicated agent notes the prevailing tilt is {top_rec}; "
            f"on a calibration-weighted basis the panel {tilt} the {syn_rec or 'synthesis'} stance "
            f"(weighted {weighted_for:.1f} for / {weighted_against:.1f} against). "
        )
        if divergent:
            narrative += f"{divergent} dissenting view(s) are down-weighted unless tied to a fresh catalyst. "
        if noise:
            narrative += f"{noise} thin output(s) add little decision value. "
    if suppressed:
        narrative += f"{suppressed} stale note(s) pre-dating the current position were suppressed. "

    # P1-2: Layer 4 ensemble + dual-lane (Grok/ChatGPT) consensus
    ens_line = ""
    if ensemble and ensemble.get("final_decision"):
        score = ensemble.get("final_score")
        narrative += (
            f"Layer 4 ensemble: {ensemble.get('final_decision')} "
            f"(score {score}/10, confidence {ensemble.get('final_confidence', '—')}). "
        )
        ens_line = f"Ensemble {ensemble.get('final_decision')} — score {score}/10"

    dual = agent_meta.get("dual_lane") or {}
    grok = dual.get("grok")
    cgpt = dual.get("chatgpt")
    if grok or cgpt:
        agree = dual.get("models_agree")
        if agree is True:
            narrative += f"Dual-lane cloud check agrees (Grok {grok} · ChatGPT {cgpt}) — conviction confirmed. "
        elif agree is False:
            narrative += (
                f"Dual-lane cloud check DISAGREES (Grok {grok} · ChatGPT {cgpt}); "
                f"per policy the verdict is treated more cautiously (confidence ×0.8). "
            )
        else:
            narrative += f"Dual-lane cloud check: Grok {grok} · ChatGPT {cgpt}. "
        ens_line = (ens_line + " · " if ens_line else "") + f"Grok {grok}/ChatGPT {cgpt}"

    age_days = agent_meta.get("synthesis_age_days")
    if age_days is not None and age_days > 14:
        narrative += f"Note: unified synthesis is {int(age_days)}d old — refresh recommended before sizing up. "

    prior = (continuity or {}).get("metrics", {}).get("prior_call_assessment")
    perf_note = (
        f"Prior report call on this name: {prior}."
        if prior else "Insufficient dated history to score prior agent accuracy on this ticker."
    )

    bullets = []
    if panel_size:
        bullets.append(f"Panel consensus: {top_rec} ({counts[top_rec]}/{panel_size}, calibration-weighted)")
    if dual.get("models_agree") is False:
        bullets.append("Model disagreement → cautious verdict (×0.8) applied")
    bullets.append(perf_note)

    return {
        "narrative": narrative.strip(),
        "performance_note": perf_note,
        "agents": evaluated,
        "ensemble_line": ens_line,
        "bullets": bullets,
    }


def narrative_technical(enrich: dict, mom: str) -> str:
    rsi = enrich.get("rsi")
    rvol = enrich.get("rvol")
    s20 = enrich.get("sma20_pct")
    s50 = enrich.get("sma50_pct")
    parts = [mom.rstrip(".")]
    if rsi is not None:
        parts.append(f"RSI at {_f(rsi):.0f}")
    if rvol is not None:
        parts.append(f"volume running {_f(rvol):.1f}× average")
    if s20 is not None and s50 is not None:
        posture = "below" if _f(s20) < 0 and _f(s50) < 0 else ("above" if _f(s20) > 0 else "near")
        parts.append(f"price is {posture} key moving averages (SMA20 {_pct(s20)}, SMA50 {_pct(s50)})")
    return ". ".join(parts) + "."


def narrative_fundamental(enrich: dict, pro: dict | None, price: float) -> str:
    # Finviz 'recom' is a technical screen, NOT an analyst rating — never present it as "Street rates".
    rating = (pro or {}).get("recommendation_key")
    rating = str(rating).replace("_", " ").title() if rating else None
    target = _f((pro or {}).get("target_mean_price") or enrich.get("target_mean_price"))
    pe = enrich.get("pe")
    fwd = enrich.get("forward_pe")
    n = (pro or {}).get("number_of_analyst_opinions")
    is_etf = str(enrich.get("instrument_type") or "").lower() in ("etf", "fund", "etn")
    if rating:
        base = f"Street rates {rating}"
        if n:
            base += f" ({n} analysts)"
    elif is_etf:
        # use the same YTD source as the technical/packet (Finviz perf_ytd) to avoid a two-source contradiction
        ytd = enrich.get("perf_ytd_pct") if enrich.get("perf_ytd_pct") is not None else enrich.get("ytd_return_pct")
        yld = enrich.get("dividend_yield_pct") or enrich.get("div_yield_pct")
        base = (
            f"Fund vehicle — no single-name analyst rating applies. "
            f"YTD {_pct(ytd)}" + (f", distribution yield {_f(yld):.2f}%" if yld else "")
        )
        return base + "."
    else:
        base = "No professional analyst rating on file"
    if target > 0 and price > 0:
        upside = (target - price) / price * 100
        base += f" with ${_f(target):,.0f} mean target ({upside:+.0f}% from current)."
    else:
        base += "."
    if pe or fwd:
        base += f" Valuation: {pe or '—'}× trailing / {fwd or '—'}× forward."
    return base


def narrative_news(news: list[dict], pro: dict | None) -> tuple[str, list[str]]:
    bullets: list[str] = []
    impacts = {"Positive": 0, "Negative": 0, "Neutral": 0}
    for n in news[:5]:
        from report_synthesis import news_impact
        impact = news_impact(str(n.get("title") or ""), str(n.get("summary") or ""))
        impacts[impact] = impacts.get(impact, 0) + 1
        title = str(n.get("title") or "Headline")[:90]
        bullets.append(f"{impact}: {title}")
    if pro and pro.get("latest_event_headline"):
        bullets.insert(0, f"Street: {str(pro.get('latest_event_headline'))[:90]}")
    if not bullets:
        return "No material scored catalysts in the current ingestion window.", []
    neg, pos = impacts.get("Negative", 0), impacts.get("Positive", 0)
    if neg > pos:
        tone = "News flow skews cautious — monitor for thesis impact."
    elif pos > neg:
        tone = "Recent headlines are net supportive of the holding case."
    else:
        tone = "Headlines are mixed; no single catalyst dominates the near-term setup."
    return tone, bullets[:4]


_RATING_FROM_MEAN = (
    (1.5, "Strong Buy"),
    (2.5, "Buy"),
    (3.5, "Hold"),
    (4.5, "Sell"),
    (99.0, "Strong Sell"),
)


def consensus_rating(mean: Any) -> str:
    m = _f(mean)
    if m <= 0:
        return "—"
    for thresh, label in _RATING_FROM_MEAN:
        if m < thresh:
            return label
    return "Strong Sell"


def rating_distribution(pro: dict | None) -> dict:
    """Approximate Buy/Hold/Sell split from Yahoo recommendation_mean (1=SB .. 5=SS)."""
    pro = pro or {}
    mean = _f(pro.get("recommendation_mean"))
    n = int(_f(pro.get("number_of_analyst_opinions")))
    if mean <= 0 or n <= 0:
        return {}
    # Map mean to a plausible buy/hold/sell tilt (street convention: lower = more bullish).
    if mean < 1.8:
        buy, hold, sell = 0.78, 0.18, 0.04
    elif mean < 2.4:
        buy, hold, sell = 0.58, 0.32, 0.10
    elif mean < 3.0:
        buy, hold, sell = 0.38, 0.45, 0.17
    elif mean < 3.6:
        buy, hold, sell = 0.20, 0.50, 0.30
    else:
        buy, hold, sell = 0.08, 0.37, 0.55
    return {
        "buy": round(buy * n),
        "hold": round(hold * n),
        "sell": max(0, n - round(buy * n) - round(hold * n)),
        "n": n,
    }


def narrative_analyst_predictions(pro: dict | None, enrich: dict, price: float) -> tuple[str, dict, list[str]]:
    """Wall-Street consensus: targets, upside, rating distribution, valuation read.

    Uses professional coverage pills (Yahoo street data), NOT the Finviz recom field
    (which is not an analyst rating — see finviz-is-not-a-rating correction).
    """
    pro = pro or {}
    n = int(_f(pro.get("number_of_analyst_opinions")))
    mean = _f(pro.get("recommendation_mean"))
    rating = consensus_rating(mean) if mean else (pro.get("recommendation_key") or "—")
    rating = str(rating).replace("_", " ").title()
    t_mean = _f(pro.get("target_mean_price"))
    t_low = _f(pro.get("target_low_price"))
    t_high = _f(pro.get("target_high_price"))
    upside = pro.get("upside_to_mean_target_pct")
    if upside is None and t_mean > 0 and price > 0:
        upside = (t_mean - price) / price * 100

    if n <= 0 and t_mean <= 0:
        return (
            "No professional analyst coverage on file for this name — treat valuation and "
            "price-target references as not available rather than inferred.",
            {}, [],
        )

    dist = rating_distribution(pro)
    pe = enrich.get("pe")
    fwd = enrich.get("forward_pe")

    parts = []
    if n:
        parts.append(f"{n} covering analysts rate this a consensus **{rating}** (mean score {mean:.2f}/5)")
    elif rating != "—":
        parts.append(f"Street consensus: {rating}")
    if t_mean > 0:
        band = f" (range ${t_low:,.0f}–${t_high:,.0f})" if t_low and t_high else ""
        up_txt = f"{_f(upside):+.1f}% vs ${price:,.2f}" if upside is not None and price > 0 else ""
        parts.append(f"mean 12-month target ${t_mean:,.2f}{band}, {up_txt}".rstrip(", "))
    val_read = ""
    if pe and t_mean > 0 and price > 0:
        if _f(upside) > 12:
            val_read = f" At {pe}× trailing / {fwd or '—'}× forward earnings the street sees the holding as undervalued to its target."
        elif _f(upside) < 0:
            val_read = f" At {pe}× trailing the price already sits above the mean target — limited consensus upside."
        else:
            val_read = f" At {pe}× trailing / {fwd or '—'}× forward the stock trades roughly in line with its consensus target."
    content = (". ".join(p for p in parts if p) + "." + val_read).replace("..", ".").strip()

    metrics = {
        "consensus_rating": rating,
        "analysts": n or None,
        "target_low": t_low or None,
        "target_mean": t_mean or None,
        "target_high": t_high or None,
        "upside_to_mean_pct": round(_f(upside), 1) if upside is not None else None,
        "pe": pe,
        "forward_pe": fwd,
    }
    bullets = []
    if dist:
        # Honest: this split is IMPLIED from the consensus mean (Yahoo gives the mean, not per-analyst
        # counts), not a verbatim tally — label it so it is never read as exact analyst votes.
        bullets.append(
            f"Implied rating split (modeled from the {mean:.2f}/5 mean, not a verbatim tally): "
            f"≈{dist['buy']} Buy · ≈{dist['hold']} Hold · ≈{dist['sell']} Sell of {dist['n']} analysts"
        )
    if pro.get("latest_event_headline") and pro.get("latest_event_type") in ("analyst_upgrade", "analyst_downgrade"):
        bullets.append(f"Street action: {str(pro['latest_event_headline'])[:110]}")
    return content, metrics, bullets


def narrative_personal(gl_pct: Any, entry: Any, unreal: Any, perf_ytd: Any, quality: str) -> str:
    return (
        f"Entered at {_money(entry)}; position is {_pct(gl_pct)} unrealized ({_money(unreal)}). "
        f"{quality.split('—')[0].strip()}. "
        f"Symbol YTD {_pct(perf_ytd)} vs your cost basis."
    ).replace("..", ".")


def _vol_clause(enrich: dict) -> str:
    """P0-4: report a correctly-labelled volatility metric, never the Finviz weekly-range field."""
    rv = enrich.get("realized_vol_annualized_pct")
    atr_pct = enrich.get("atr_pct")
    beta = enrich.get("beta")
    beta_txt = f"beta {_f(beta):.2f}" if beta not in (None, "") else "beta —"
    if rv is not None and _f(rv) > 0:
        return f"{beta_txt}, 20-day realized volatility {_f(rv):.0f}% annualized"
    if atr_pct is not None and _f(atr_pct) > 0:
        return f"{beta_txt}, average daily range (ATR) {_f(atr_pct):.1f}% of price"
    return beta_txt


def narrative_risk(enrich: dict, thesis: str, tv: dict, synthesis: dict | None) -> tuple[str, list[str]]:
    flags: list[str] = []
    if synthesis and synthesis.get("safety_reasons"):
        sr = synthesis["safety_reasons"]
        if isinstance(sr, list):
            flags.extend(str(x)[:100] for x in sr[:2])
    if thesis != "Still valid":
        flags.append(f"Thesis marked {thesis}")

    zone = tv.get("zone_status")
    if zone and str(zone).lower() not in ("n/a", "none", "unknown", ""):
        band = ""
        vlo, vhi = tv.get("valid_low"), tv.get("valid_high")
        if vlo and vhi:
            band = f" (valid band ${_f(vlo):,.2f}–${_f(vhi):,.2f})"
        zone_txt = str(zone).replace("_", " ")
        thesis_clause = (
            f"Thesis-validity zone is {zone_txt}{band}"
            + (f", drift {_pct(tv.get('drift_pct'))}." if tv.get("drift_pct") is not None else ".")
        )
    else:
        thesis_clause = "Thesis-validity band not computable — entry/support/target levels unavailable."

    content = f"Risk profile: {_vol_clause(enrich)}. {thesis_clause}"
    rr = tv.get("planned_rr") or tv.get("current_rr")
    if rr:
        flags.insert(0, f"Reward:risk on current levels ≈ {_f(rr):.1f}:1")
    if not flags:
        flags.append("No explicit invalidation triggers — maintain stops and event calendar.")
    return content, flags[:3]


def compact_metrics(keys: dict[str, Any], allow: tuple[str, ...]) -> dict:
    return {k: keys[k] for k in allow if keys.get(k) is not None}


def polish_sections(sections: list[dict]) -> list[dict]:
    """Remove duplicate bullets and collapse legacy duplicate agent blocks."""
    seen: set[str] = set()
    out: list[dict] = []
    for sec in sections:
        sid = sec.get("id")
        if sid in ("agent_performance_note", "ensemble_validation") and any(
            s.get("id") == "intelligence_view" for s in sections
        ):
            continue
        content = strip_md(str(sec.get("content") or ""))[:1200]
        if content in seen and sid not in ("header_context", "executive_summary"):
            continue
        seen.add(content)
        sec = dict(sec)
        sec["content"] = content
        if sid == "agent_synthesis":
            sec["bullets"] = []
        out.append(sec)
    return out