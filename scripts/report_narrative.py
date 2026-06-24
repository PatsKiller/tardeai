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
    for k in ("STRONG BUY", "STRONG_BUY", "ADD", "BUY", "HOLD", "TRIM", "SELL", "MONITOR"):
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
) -> str:
    rec_u = _rec_bucket(rec)
    stop = _f((proposal or {}).get("proposed_stop")) or None
    target = _f((proposal or {}).get("proposed_target1")) or _f((pro or {}).get("target_mean_price"))
    if "ADD" in rec_u or "BUY" in rec_u:
        if stop and stop < price:
            return f"Add on pullbacks to ${stop:,.2f}–${price:,.2f} only; do not chase above ${price * 1.03:,.2f}."
        if target and target > price:
            return f"Scale in toward ${target:,.2f} street target; accumulate between ${price * 0.97:,.2f} and ${price:,.2f}."
        return "Add only on defined pullbacks — confirm size vs risk budget before committing capital."
    if "TRIM" in rec_u or "SELL" in rec_u:
        return f"Reduce exposure at current levels (${price:,.2f}); tighten risk if thesis is {thesis.lower()}."
    if "MONITOR" in rec_u:
        return "No new capital — monitor catalysts and reassess after next material event."
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
) -> dict:
    """Confident executive block — narrative first, callouts separate."""
    narr_bits: list[str] = []
    if synthesis:
        for k in ("synthesis_narrative", "raw_response"):
            raw = strip_md(str(synthesis.get(k) or ""))
            if len(raw) > 40:
                narr_bits.append(raw[:320].rsplit(" ", 1)[0] + ("…" if len(raw) > 320 else ""))
                break

    street = ""
    pe = enrich.get("pe")
    if pe:
        street = f" Valuation screens at {pe}× trailing earnings"

    personal = ""
    if gl_pct is not None:
        personal = f" Your book shows {_pct(gl_pct)} unrealized"

    lead = (
        f"{company} ({sym}) trades at ${price:,.2f} ({_pct(day_pct)} today) in {sector}.{street}.{personal}. "
        f"Our stance is {rec} ({conf_label} confidence)."
    )
    if narr_bits:
        lead = narr_bits[0]
    elif not narr_bits:
        mom = "oversold" if _f(enrich.get("rsi")) < 35 else "range-bound"
        lead = (
            f"{company} ({sym}) is {mom} at ${price:,.2f} in {sector}. "
            f"Street and synthesis support a {rec} view ({conf_label} confidence).{personal}."
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


def synthesize_agent_collective(
    agents: list[dict],
    synthesis: dict | None,
    ensemble: dict | None,
    continuity: dict | None,
) -> dict:
    """True synthesis — collective view + compact relevance table (no verbatim dumps)."""
    evaluated: list[dict] = []
    recs: list[str] = []
    syn_rec = _rec_bucket(str((synthesis or {}).get("recommendation") or ""))
    ens_dec = str((ensemble or {}).get("final_decision") or "").lower()
    aligned = divergent = noise = 0

    for a in agents[:8]:
        agent = str(a.get("agent") or "agent").replace("_", " ")
        rec = str(a.get("recommendation") or "—")
        recs.append(_rec_bucket(rec))
        summary = str(a.get("summary") or "")
        rec_u = rec.upper()
        is_aligned = (
            (syn_rec and syn_rec in rec_u)
            or (ens_dec == "approve" and "BUY" in rec_u)
            or (ens_dec == "block" and any(x in rec_u for x in ("SELL", "TRIM", "HOLD", "WAIT")))
        )
        if len(summary) < 20:
            weight = "Low weight — thin rationale"
            noise += 1
        elif is_aligned:
            weight = "Aligned — supports synthesis"
            aligned += 1
        else:
            weight = "Divergent — secondary input"
            divergent += 1
        evaluated.append({
            "agent": agent,
            "recommendation": _rec_bucket(rec),
            "relevance": weight,
            "weight": "Primary" if "Aligned" in weight else ("Low" if "Low" in weight else "Secondary"),
        })

    counts = Counter(recs)
    top_rec = counts.most_common(1)[0][0] if counts else "—"
    panel_size = len(evaluated)

    if not evaluated:
        narrative = "No recent agent panel on file. Weight watchlist synthesis and Layer 4 ensemble as primary intelligence."
    else:
        narrative = (
            f"Across {panel_size} agent notes, the prevailing tilt is {top_rec} "
            f"({counts[top_rec]} of {panel_size} calls). "
        )
        if aligned >= max(1, panel_size // 2):
            narrative += (
                f"{aligned} inputs align with our {syn_rec or 'synthesis'} stance — treat these as confirmatory. "
            )
        if divergent:
            narrative += f"{divergent} dissenting view(s) should be down-weighted unless tied to a fresh catalyst. "
        if noise:
            narrative += f"{noise} thin output(s) add little decision value."

    ens_line = ""
    if ensemble:
        score = ensemble.get("final_score")
        narrative += (
            f" Layer 4 ensemble: {ensemble.get('final_decision')} "
            f"(score {score}/10, confidence {ensemble.get('final_confidence', '—')})."
        )
        ens_line = f"Ensemble {ensemble.get('final_decision')} — score {score}/10"

    prior = (continuity or {}).get("metrics", {}).get("prior_call_assessment")
    perf_note = (
        f"Prior report call on this name: {prior}."
        if prior else "Insufficient history to score prior agent accuracy on this ticker."
    )

    return {
        "narrative": narrative.strip(),
        "performance_note": perf_note,
        "agents": evaluated,
        "ensemble_line": ens_line,
        "bullets": [
            f"Panel consensus: {top_rec} ({counts[top_rec]}/{panel_size})" if panel_size else "No agent panel",
            perf_note,
        ] if panel_size else [perf_note],
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
    rating = (pro or {}).get("recommendation_key") or enrich.get("analyst_rating") or "—"
    target = _f((pro or {}).get("target_mean_price") or enrich.get("target_mean_price"))
    pe = enrich.get("pe")
    fwd = enrich.get("forward_pe")
    n = (pro or {}).get("number_of_analyst_opinions")
    base = f"Street rates {rating}"
    if n:
        base += f" ({n} analysts)"
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


def narrative_personal(gl_pct: Any, entry: Any, unreal: Any, perf_ytd: Any, quality: str) -> str:
    return (
        f"Entered at {_money(entry)}; position is {_pct(gl_pct)} unrealized ({_money(unreal)}). "
        f"{quality.split('—')[0].strip()}. "
        f"Symbol YTD {_pct(perf_ytd)} vs your cost basis."
    ).replace("..", ".")


def narrative_risk(enrich: dict, thesis: str, tv: dict, synthesis: dict | None) -> tuple[str, list[str]]:
    flags: list[str] = []
    if synthesis and synthesis.get("safety_reasons"):
        sr = synthesis["safety_reasons"]
        if isinstance(sr, list):
            flags.extend(str(x)[:100] for x in sr[:2])
    if thesis != "Still valid":
        flags.append(f"Thesis marked {thesis}")
    beta = enrich.get("beta")
    vol = enrich.get("volatility_w_pct")
    content = (
        f"Risk profile: beta {beta or '—'}, weekly volatility {_pct(vol)}. "
        f"Thesis validity zone {tv.get('zone_status', 'n/a')}"
        + (f", drift {_pct(tv.get('drift_pct'))}." if tv.get("drift_pct") is not None else ".")
    )
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