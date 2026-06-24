"""report_synthesis.py — actionable analyst-grade synthesis for holding/watchlist reports.

Transforms raw agent/enrichment data into structured, personal-context reports that answer:
  What is happening? What does it mean for me? What should I do? How confident?
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"

HOLDING_REPORT_SECTIONS = (
    "header_context",
    "executive_summary",
    "personal_performance",
    "report_continuity",
    "news_catalysts",
    "technical_analysis",
    "fundamental_valuation",
    "intelligence_view",
    "risk_assessment",
    "action_plan",
    # legacy aliases → intelligence_view / merged sections
    "agent_synthesis",
    "agent_performance_note",
    "ensemble_validation",
)


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


def _confidence_label(score: float | None) -> str:
    if score is None:
        return "Low"
    s = _f(score)
    if s >= 75:
        return "High"
    if s >= 50:
        return "Medium"
    return "Low"


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default if default is not None else {}


def _pro_analyst(symbol: str) -> dict | None:
    data = _load_json(RUNTIME_DIR / "pro_analyst_pills_latest.json", {})
    pills = data.get("pills") or data.get("symbols") or []
    sym = symbol.upper()
    if isinstance(pills, dict):
        row = pills.get(sym)
        return row if isinstance(row, dict) else None
    if isinstance(pills, list):
        for p in pills:
            if (p.get("symbol") or "").upper() == sym:
                return p
    return None


def aggregate_holdings(symbol: str, holdings_loader) -> dict:
    """Merge all account lots for one symbol into personal context."""
    sym = symbol.upper()
    rows = [
        h for h in (holdings_loader() or [])
        if str(h.get("symbol", "")).upper() == sym and not h.get("is_cash")
    ]
    if not rows:
        return {}
    total_mv = sum(_f(r.get("market_value")) for r in rows)
    total_cb = sum(_f(r.get("cost_basis")) for r in rows if r.get("cost_basis"))
    total_gl = sum(_f(r.get("gain_loss")) for r in rows if r.get("gain_loss") is not None)
    total_sh = sum(_f(r.get("shares")) for r in rows)
    pct_port = sum(_f(r.get("portfolio_pct")) for r in rows)
    accounts = sorted({str(r.get("account") or "unknown").replace("_", " ") for r in rows})
    entry = (total_cb / total_sh) if total_sh > 0 and total_cb > 0 else None
    gl_pct = (total_gl / total_cb * 100) if total_cb > 0 and total_gl else (
        rows[0].get("gain_loss_pct") if len(rows) == 1 else None
    )
    price = _f(rows[0].get("current_price") or rows[0].get("price"))
    return {
        "accounts": accounts,
        "market_value": total_mv,
        "cost_basis": total_cb or None,
        "entry_price": entry,
        "shares": total_sh,
        "unrealized_pnl": total_gl if total_cb else None,
        "unrealized_pnl_pct": gl_pct,
        "portfolio_pct": pct_port,
        "current_price": price,
        "name": rows[0].get("name"),
        "cost_basis_source": rows[0].get("cost_basis_source"),
        "as_of": rows[0].get("as_of") or rows[0].get("updated_at"),
        "primary": rows[0],
    }


def thesis_status(synthesis: dict | None, proposal: dict | None, enrich: dict) -> str:
    tv = (proposal or {}).get("thesis_validity") or {}
    zone = str(tv.get("zone_status") or "").lower()
    if zone in ("invalid", "broken", "invalidated"):
        return "Broken"
    if zone in ("at_risk", "stressed", "warning"):
        return "At risk"
    safety = str((synthesis or {}).get("decision_safety") or "").lower()
    if safety in ("unsafe", "blocked", "caution"):
        return "At risk"
    if (synthesis or {}).get("conflicts_detected"):
        return "At risk"
    return "Still valid"


def entry_quality(unrealized_pct: float | None, perf_ytd: Any) -> str:
    if unrealized_pct is None:
        return "Unknown — no cost basis on file"
    u = _f(unrealized_pct)
    if u >= 15:
        return "Strong — position has compounded well since entry"
    if u >= 0:
        return "Average — modest gain since entry"
    if u >= -15:
        return "Underwater — entry timing was early or thesis lagging"
    return "Poor — significant drawdown from cost basis; review sizing and thesis"


def news_impact(title: str, summary: str) -> str:
    t = f"{title} {summary}".lower()
    neg = ("downgrade", "miss", "cut", "lawsuit", "delay", "weak", "decline", "loss", "warning")
    pos = ("upgrade", "beat", "raise", "award", "contract", "growth", "surge", "win", "record")
    if any(w in t for w in neg):
        return "Negative"
    if any(w in t for w in pos):
        return "Positive"
    return "Neutral"


def evaluate_agents(agents: list[dict], synthesis: dict | None, ensemble: dict | None) -> tuple[list[dict], str]:
    """Score agent outputs for relevance; return evaluated rows + synthesis paragraph."""
    syn_rec = str((synthesis or {}).get("recommendation") or "").upper()
    ens_dec = str((ensemble or {}).get("final_decision") or "").lower()
    evaluated: list[dict] = []
    noise = 0
    valuable = 0
    for a in agents[:8]:
        agent = str(a.get("agent") or "agent")
        rec = str(a.get("recommendation") or "—")
        conf = a.get("confidence")
        summary = (a.get("summary") or "")[:200]
        rec_u = rec.upper()
        aligned = (
            (syn_rec and syn_rec in rec_u)
            or (ens_dec == "approve" and "BUY" in rec_u)
            or (ens_dec == "block" and any(x in rec_u for x in ("SELL", "TRIM", "HOLD", "WAIT")))
        )
        if not summary or len(summary) < 20:
            relevance = "Low value — thin or missing rationale"
            noise += 1
        elif aligned:
            relevance = "Relevant — aligns with synthesis/ensemble direction"
            valuable += 1
        else:
            relevance = "Mixed — diverges from current synthesis; treat as secondary"
            noise += 1
        evaluated.append({
            "agent": agent,
            "recommendation": rec,
            "confidence": conf,
            "summary": summary,
            "relevance": relevance,
            "created_at": a.get("created_at"),
        })
    if not evaluated:
        para = "No recent per-agent notes on file — rely on Layer 4 ensemble and watchlist synthesis."
    elif valuable >= max(1, len(evaluated) // 2):
        para = (
            f"Agent panel ({len(evaluated)} notes): majority align with the synthesized stance. "
            f"Prioritize synthesis + ensemble over isolated agent calls."
        )
    else:
        para = (
            f"Agent panel ({len(evaluated)} notes): significant divergence — "
            f"{noise} outputs appear noisy or contradictory. Weight Layer 4 ensemble and personal P&L context higher."
        )
    return evaluated, para


def momentum_label(rsi: Any, sma20: Any, sma50: Any) -> str:
    r = _f(rsi) if rsi is not None else None
    s20 = _f(sma20)
    s50 = _f(sma50)
    if r is not None and r >= 70:
        return "Short-term overbought — extension risk"
    if r is not None and r <= 30:
        return "Oversold — potential bounce zone"
    if s20 > 0 and s50 > 0:
        return "Uptrend — price above key moving averages"
    if s20 < 0 and s50 < 0:
        return "Downtrend — price below SMA20/50"
    return "Mixed momentum — no clear trend"


def build_action_steps(
    rec: str,
    *,
    price: float,
    personal: dict,
    proposal: dict | None,
    enrich: dict,
    pro: dict | None,
    thesis: str,
) -> list[str]:
    steps: list[str] = []
    rec_u = rec.upper()
    stop = _f((proposal or {}).get("proposed_stop")) or None
    target = _f((proposal or {}).get("proposed_target1")) or _f((pro or {}).get("target_mean_price"))
    pct = _f(personal.get("portfolio_pct"))
    gl_pct = personal.get("unrealized_pnl_pct")

    if "ADD" in rec_u or "BUY" in rec_u:
        if stop and stop > 0:
            steps.append(f"Consider adding only on pullback toward ${stop:,.2f} (advised stop / support zone).")
        elif target and target > price:
            steps.append(f"Street mean target ${target:,.2f} — scale in; avoid chasing above ${price * 1.03:,.2f} (+3%).")
        else:
            steps.append("Scale in per plan; confirm position size vs portfolio risk budget before adding.")
    elif "TRIM" in rec_u or "SELL" in rec_u or "REDUCE" in rec_u:
        steps.append(f"Reduce exposure — current allocation {pct:.2f}% may exceed risk tolerance.")
        if stop:
            steps.append(f"Tighten stop to ${stop:,.2f} or exit on break.")
    elif "MONITOR" in rec_u or "WATCH" in rec_u:
        steps.append("No new capital — monitor catalysts and reassess after next earnings or thesis checkpoint.")
    else:
        steps.append("Maintain position size; review on material news or stop breach.")

    if gl_pct is not None and _f(gl_pct) < -20:
        steps.append(f"Personal P&L {_pct(gl_pct)} — revisit original thesis; avoid averaging down without fresh catalyst.")
    if thesis == "At risk":
        steps.append("Thesis at risk — require explicit invalidation criteria before adding.")
    elif thesis == "Broken":
        steps.append("Thesis broken — default action is exit or hedge; do not add.")

    if pct > 8:
        steps.append(f"Concentration note: {pct:.1f}% of portfolio — consider trim if above sleeve limit.")
    elif pct < 1 and ("ADD" in rec_u or "BUY" in rec_u):
        steps.append(f"Underweight at {pct:.2f}% — room to add if thesis intact.")

    return steps[:5]


def compose_symbol_sections(
    *,
    symbol: str,
    enrich: dict,
    holding: dict | None,
    personal: dict,
    wl: dict | None,
    synthesis: dict | None,
    agents: list[dict],
    ensemble: dict | None,
    news: list[dict],
    proposal: dict | None,
    sections: list[str],
    report_type: str,
    exec_metrics: dict,
    continuity: dict | None = None,
    peer_rows: list[dict] | None = None,
    option_rows: list[dict] | None = None,
) -> list[dict]:
    """Build v2 actionable sections from pre-fetched context."""
    sym = symbol.upper()
    pro = _pro_analyst(sym)
    price = _f(enrich.get("price") or enrich.get("latest_price") or personal.get("current_price"))
    company = enrich.get("company") or personal.get("name") or sym
    sector = enrich.get("sector") or (wl or {}).get("sector") or "—"
    rec = exec_metrics.get("recommendation") or "Review"
    conf = exec_metrics.get("confidence")
    conf_label = exec_metrics.get("confidence_label") or _confidence_label(conf)
    thesis = thesis_status(synthesis, proposal, enrich)
    gl_pct = personal.get("unrealized_pnl_pct")
    if gl_pct is None and holding:
        gl_pct = holding.get("gain_loss_pct")

    from report_narrative import (
        action_recommendation_line,
        compose_executive,
        compact_metrics,
        narrative_fundamental,
        narrative_news,
        narrative_personal,
        narrative_risk,
        narrative_technical,
        polish_sections,
        synthesize_agent_collective,
        thesis_rationale,
    )

    want_intel = any(s in sections for s in (
        "intelligence_view", "agent_synthesis", "agent_performance_note", "ensemble_validation",
    ))
    action_line = action_recommendation_line(
        rec, price=price, proposal=proposal, pro=pro, thesis=thesis,
    )
    thesis_why = thesis_rationale(
        thesis, synthesis=synthesis, proposal=proposal, enrich=enrich,
        gl_pct=gl_pct, ensemble=ensemble,
    )

    out: list[dict] = []

    if "header_context" in sections:
        out.append({
            "id": "header_context",
            "title": "Identification & Personal Context",
            "metrics": compact_metrics({
                "symbol": sym,
                "company": company,
                "sector": sector,
                "price": price,
                "portfolio_pct": personal.get("portfolio_pct") or (holding or {}).get("portfolio_pct"),
                "entry_price": personal.get("entry_price") or (holding.get("entry_price") if holding else None),
                "unrealized_pnl_pct": gl_pct,
                "accounts": ", ".join(personal.get("accounts") or []) or (holding or {}).get("account"),
            }, ("symbol", "company", "sector", "price", "portfolio_pct", "entry_price", "unrealized_pnl_pct", "accounts")),
            "content": (
                f"{company} ({sym}) · {sector} · ${price:,.2f} · "
                f"{'Portfolio holding' if personal or holding else 'Watchlist'} · "
                f"P&L {_money(personal.get('unrealized_pnl'))} ({_pct(gl_pct)})."
            ),
        })

    if "executive_summary" in sections:
        exec_block = compose_executive(
            company=company, sym=sym, sector=sector, price=price,
            day_pct=enrich.get("day_change_pct"), rec=rec, conf_label=conf_label,
            thesis=thesis, thesis_why=thesis_why, action_line=action_line,
            synthesis=synthesis, enrich=enrich, gl_pct=gl_pct, continuity=continuity,
        )
        out.append({
            "id": "executive_summary",
            "title": "Executive Summary & Action Recommendation",
            "content": exec_block["content"],
            "metrics": exec_block["metrics"],
            "callouts": exec_block.get("callouts"),
        })

    if "personal_performance" in sections:
        perf_ytd = enrich.get("perf_ytd_pct") or enrich.get("perf_ytd")
        eq = entry_quality(gl_pct, perf_ytd)
        out.append({
            "id": "personal_performance",
            "title": "Personal Performance & Entry Assessment",
            "content": narrative_personal(
                gl_pct,
                personal.get("entry_price") or (holding or {}).get("entry_price"),
                personal.get("unrealized_pnl"),
                perf_ytd,
                eq,
            ),
            "metrics": compact_metrics({
                "entry_quality": eq.split("—")[0].strip(),
                "market_value": personal.get("market_value"),
                "portfolio_pct": personal.get("portfolio_pct"),
            }, ("entry_quality", "market_value", "portfolio_pct")),
        })

    if "report_continuity" in sections:
        cont = continuity or {
            "content": "Baseline report — subsequent editions will track changes and prior-call accuracy.",
            "bullets": [],
            "metrics": {"prior_report": False, "generation": 1},
        }
        bullets = cont.get("bullets") or []
        if len(bullets) > 3:
            bullets = bullets[:2] + [bullets[-1]]
        out.append({
            "id": "report_continuity",
            "title": "Report Continuity (Changes Since Last Report)",
            "content": cont.get("content") or "No prior report on file.",
            "bullets": bullets,
            "metrics": compact_metrics(cont.get("metrics") or {}, (
                "price_delta_pct", "pnl_delta_pct", "prior_call_assessment", "generation",
            )),
        })

    if "news_catalysts" in sections:
        news_narr, news_bullets = narrative_news(news, pro)
        out.append({
            "id": "news_catalysts",
            "title": "Latest News & Catalysts",
            "content": news_narr,
            "bullets": news_bullets,
        })

    if "technical_analysis" in sections:
        mom = momentum_label(enrich.get("rsi"), enrich.get("sma20_pct"), enrich.get("sma50_pct"))
        out.append({
            "id": "technical_analysis",
            "title": "Technical & Price Action Analysis",
            "content": narrative_technical(enrich, mom),
            "metrics": compact_metrics({
                "rsi": enrich.get("rsi"),
                "rvol": enrich.get("rvol"),
                "sma20_pct": enrich.get("sma20_pct"),
                "sma50_pct": enrich.get("sma50_pct"),
                "momentum": mom,
            }, ("rsi", "rvol", "sma20_pct", "sma50_pct", "momentum")),
        })

    if "fundamental_valuation" in sections:
        rating = (pro or {}).get("recommendation_key") or enrich.get("analyst_rating")
        target = (pro or {}).get("target_mean_price") or enrich.get("target_mean_price")
        upside = (pro or {}).get("upside_to_mean_target_pct")
        out.append({
            "id": "fundamental_valuation",
            "title": "Fundamental & Valuation Snapshot",
            "content": narrative_fundamental(enrich, pro, price),
            "metrics": compact_metrics({
                "pe": enrich.get("pe"),
                "forward_pe": enrich.get("forward_pe"),
                "street_rating": rating,
                "target_mean": target,
                "upside_to_target_pct": upside,
            }, ("pe", "forward_pe", "street_rating", "target_mean", "upside_to_target_pct")),
        })

    if want_intel:
        intel = synthesize_agent_collective(agents, synthesis, ensemble, continuity)
        out.append({
            "id": "intelligence_view",
            "title": "Synthesized Agent & Intelligence View",
            "content": intel["narrative"],
            "agents": intel["agents"],
            "bullets": [intel["performance_note"]] if intel.get("performance_note") else [],
            "metrics": compact_metrics({
                "ensemble_decision": (ensemble or {}).get("final_decision"),
                "ensemble_score": (ensemble or {}).get("final_score"),
            }, ("ensemble_decision", "ensemble_score")) if ensemble else {},
            "ensemble": ensemble,
        })

    if "risk_assessment" in sections:
        tv = (proposal or {}).get("thesis_validity") or {}
        risk_narr, risk_flags = narrative_risk(enrich, thesis, tv, synthesis)
        out.append({
            "id": "risk_assessment",
            "title": "Risk Assessment & Thesis Validity",
            "content": risk_narr,
            "metrics": compact_metrics({
                "beta": enrich.get("beta"),
                "thesis_status": thesis,
                "zone_status": tv.get("zone_status"),
                "drift_pct": tv.get("drift_pct"),
            }, ("beta", "thesis_status", "zone_status", "drift_pct")),
            "bullets": risk_flags,
        })

    if "peer_comparison" in sections and peer_rows:
        bullets = [
            f"{p['symbol']}: {_pct(p.get('day_change_pct'))} today · PE {p.get('pe', '—')} · 1M {_pct(p.get('perf_month_pct'))}"
            for p in peer_rows[:8]
        ]
        sym_day = _f(enrich.get("day_change_pct"))
        rank = sum(1 for p in peer_rows if _f(p.get("day_change_pct")) > sym_day) + 1
        out.append({
            "id": "peer_comparison",
            "title": "Peer Comparison",
            "content": (
                f"{sym} vs {len(peer_rows)} {sector} peers — "
                f"today rank {rank}/{len(peer_rows) + 1} by day change ({_pct(sym_day)})."
            ),
            "bullets": bullets,
            "metrics": {"peer_count": len(peer_rows), "sector": sector, "day_rank": rank},
        })

    if "options_strategy" in sections and option_rows:
        bullets = []
        for o in option_rows[:6]:
            bullets.append(
                f"{o.get('side', '—').upper()} {o.get('qty')}× "
                f"{o.get('option_type', 'opt').upper()} ${o.get('strike')} "
                f"DTE {o.get('dte', '—')} · MV {_money(o.get('market_value'))}"
            )
        out.append({
            "id": "options_strategy",
            "title": "Options Greeks & Strategy View",
            "content": (
                f"{len(option_rows)} listed option leg(s) on {sym}. "
                "Review DTE and side vs underlying thesis before adjusting equity size."
            ),
            "bullets": bullets,
            "metrics": {"legs": len(option_rows)},
        })

    if "action_plan" in sections:
        steps = build_action_steps(
            rec, price=price, personal=personal, proposal=proposal, enrich=enrich, pro=pro, thesis=thesis,
        )
        out.append({
            "id": "action_plan",
            "title": "Recommendation & Specific Action Plan",
            "content": (
                f"We reiterate {rec} ({conf_label} confidence). {action_line} "
                f"Conviction tempered by {thesis_why.rstrip('.')}."
            ),
            "metrics": compact_metrics({
                "recommendation": rec,
                "confidence_label": conf_label,
                "action_recommendation": action_line,
            }, ("recommendation", "confidence_label", "action_recommendation")),
            "bullets": steps[:4],
            "callouts": [{"label": "Primary Action", "text": action_line}],
        })

    built_ids = {s["id"] for s in out}
    if "investment_thesis" in sections and "investment_thesis" not in built_ids:
        narr = (synthesis or {}).get("synthesis_narrative") or ""
        out.append({"id": "investment_thesis", "title": "Investment Thesis", "content": narr[:800] or "See executive summary."})
    if "recommendation" in sections and "recommendation" not in built_ids and "action_plan" not in built_ids:
        out.append({"id": "recommendation", "title": "Recommendation", "content": f"{rec} — {conf_label} confidence."})
    if "fundamental_news" in sections and "fundamental_news" not in built_ids:
        nc = next((s for s in out if s["id"] == "news_catalysts"), None)
        out.append({"id": "fundamental_news", "title": "Fundamental / News", "bullets": (nc or {}).get("bullets", [])})
    if "valuation_targets" in sections and "valuation_targets" not in built_ids:
        out.append({"id": "valuation_targets", "title": "Valuation / Targets",
                    "content": f"Mean target ${(pro or {}).get('target_mean_price', '—')}"})
    if "key_risks" in sections and "key_risks" not in built_ids:
        ra = next((s for s in out if s["id"] == "risk_assessment"), {})
        out.append({"id": "key_risks", "title": "Key Risks", "bullets": ra.get("bullets") or []})

    alias_order = {
        "fundamental_news": "news_catalysts",
        "recommendation": "action_plan",
        "valuation_targets": "fundamental_valuation",
        "key_risks": "risk_assessment",
        "agent_synthesis": "intelligence_view",
        "agent_performance_note": "intelligence_view",
        "ensemble_validation": "intelligence_view",
    }
    order = {sid: i for i, sid in enumerate(sections)}
    out.sort(key=lambda s: order.get(s["id"], order.get(alias_order.get(s["id"], s["id"]), 999)))
    return polish_sections(out)