"""The institutional blocks as plain tables (title, columns, rows), rendered identically to HTML, PDF and DOCX.

Order follows the approved mockup (approved-mockup-v001, operator 2026-10-26): relative performance, peers,
estimates, ownership, risk, scenarios — then, after the prose sections, macro, filings, earnings call, options /
sentiment / dividends and source coverage. A value the house does not hold prints as "n/a"; each block's gaps print
as its footnote.
"""
from __future__ import annotations

from typing import Any


def fmt(v: Any, unit: str = "") -> str:
    if v is None or v == "":
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        if unit == "$":
            return f"${v:,.2f}"
        if unit == "%":
            return f"{v:.1f}%"
        if unit == "±%":
            return f"{v:+.1f}%"
        if unit == "x":
            return f"{v:.1f}×"
        return f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.0f}"
    return str(v)


def _gaps(block: dict | None) -> str:
    return "; ".join((block or {}).get("gaps") or [])


def top_tables(doc: dict) -> list[dict]:
    b = doc.get("blocks") or {}
    out = []
    rel = b.get("relative_performance") or {}
    if rel.get("returns"):
        cols = ["Return", "1W", "1M", "3M", "YTD", "1Y", "3Y"]
        rows = [[r["name"]] + [fmt(r.get(w), "±%") for w in cols[1:]] for r in rel["returns"]]
        rows.append([f"{doc.get('symbol')} excess vs SPY"] + [fmt((rel.get("excess_vs_spy") or {}).get(w), "±%") for w in cols[1:]])
        rk = rel.get("rank_in_industry") or {}
        kpis = [("Rank in industry", f"{rk['rank']} of {rk['of']} · {rk['percentile']}th pct" if rk else "n/a"),
                ("Relative strength (12m, 0-99)", fmt(rel.get("rs_rating_12m"))),
                ("Sector trend", _trend(rel.get("sector_trend"))), ("Industry trend", _trend(rel.get("industry_trend")))]
        out.append({"id": "relative_performance", "title": "Relative performance · vs sector, industry and the market",
                    "chart": "relative_performance", "columns": cols, "rows": rows, "highlight": 0, "kpis": kpis,
                    "note": _gaps(rel)})
    peers = b.get("peer_comparison") or {}
    if peers.get("rows"):
        fields, labels = peers["fields"], peers["labels"]
        cols = ["Ticker"] + [labels[f] for f in fields] + ["Consensus"]
        rows = [[r["symbol"]] + [fmt(r.get(f)) for f in fields] + [r.get("consensus") or "n/a"] for r in peers["rows"]]
        rows.append(["Peer median"] + [fmt((peers.get("median") or {}).get(f)) for f in fields] + [""])
        out.append({"id": "peer_comparison", "title": f"Peer comparison · {peers.get('industry') or ''}", "columns": cols,
                    "rows": rows, "highlight": 0, "note": _gaps(peers)})
    out += street_top_tables(doc)
    own = b.get("ownership_flows") or {}
    if own:
        out.append({"id": "ownership_flows", "title": "Ownership and flows", "columns": ["Measure", "Value"], "rows": [
            ["Institutional ownership", fmt(own.get("institutional_pct"), "%")],
            ["Institutional change", fmt(own.get("institutional_change_pct"), "%")],
            ["Insider ownership · transactions", f"{fmt(own.get('insider_own_pct'), '%')} · {fmt(own.get('insider_change_pct'), '%')}"],
            ["Insider buys / sells 90d (Form 4)", f"{fmt(own.get('insider_buys_90d'))} / {fmt(own.get('insider_sells_90d'))}"],
            ["Short interest · days to cover", f"{fmt(own.get('short_float_pct'), '%')} · {fmt(own.get('days_to_cover'))}"],
            ["Fund flows 30d (ETFs)", fmt(own.get("etf_flows_30d"))], ["Top holders", fmt(own.get("top_holders"))]],
            "note": _gaps(own)})
    out += positioning_tables(doc)
    risk = b.get("risk_technicals") or {}
    if risk:
        out.append({"id": "risk_technicals", "title": "Risk and technicals", "columns": ["Measure", "Value"], "rows": [
            ["Beta vs S&P (1Y)", fmt(risk.get("beta_1y"))], ["Volatility (annualized)", fmt(risk.get("vol_annualized_pct"), "%")],
            ["Max drawdown 1Y", fmt(risk.get("max_drawdown_1y_pct"), "±%")], ["Correlation to your book", fmt(risk.get("correlation_to_book"))],
            ["Price vs 50 / 200-day", f"{fmt(risk.get('px_vs_sma50_pct'), '±%')} / {fmt(risk.get('px_vs_sma200_pct'), '±%')}"],
            ["RSI(14) · ATR(20)", f"{fmt(risk.get('rsi14'))} · {fmt(risk.get('atr20'), '$')}"]], "note": _gaps(risk)})
    out += valuation_tables(doc)
    sc = b.get("scenarios") or {}
    if sc:
        last = next((f.get("value") for f in doc.get("facts") or [] if f.get("label") == "Last close"), None)
        rows = []
        for c in sc.get("cases") or []:
            move = f" ({(c['price'] / last - 1) * 100:+.1f}%)" if last and c.get("price") else ""
            rows.append([c["case"].upper(), f"{fmt(c.get('probability_pct'))}% likely" if c.get("probability_pct") is not None
                         else "probability n/a", fmt(c.get("price"), "$") + move, c.get("narrative") or ""])
        out.append({"id": "scenarios", "title": "Scenarios · 12 months", "columns": ["Case", "Probability", "Price", "Narrative"],
                    "rows": rows, "note": (sc.get("footer") or "") + (" " + _gaps(sc) if _gaps(sc) else "")})
    return out


def _trend(row: Any) -> str:
    if not isinstance(row, dict):
        return "n/a"
    return str(row.get("trend") or row.get("label") or row.get("momentum") or row.get("score") or "n/a")


MACRO_GROUPS = (("rates", "Fed funds / 10-year yield", ("FEDFUNDS", "DGS10")), ("curve", "Yield curve 10y–2y", ("T10Y2Y",)),
                ("inflation", "CPI / core PCE", ("CPIAUCSL", "PCEPILFE")), ("labor", "Unemployment · payrolls", ("UNRATE", "PAYEMS")),
                ("credit", "High-yield credit spread", ("BAMLH0A0HYM2",)), ("dollar_oil", "Dollar index · oil", ("DTWEXBGS", "DCOILWTICO")))


def bottom_tables(doc: dict) -> list[dict]:
    b = doc.get("blocks") or {}
    out = []
    macro = b.get("macro_sensitivity") or {}
    series, effects = macro.get("series") or {}, macro.get("effects") or {}
    rows = []
    for key, label, ids in MACRO_GROUPS:
        vals = [f"{fmt(series[i]['value'])} · {series[i].get('trend') or 'n/a'}" for i in ids if i in series]
        rows.append([label, " / ".join(vals) or "n/a", effects.get(key) or "n/a"])
    ev = ", ".join(f"{e.get('name') or e.get('event')} {str(e.get('date') or e.get('at') or '')[:10]}" for e in macro.get("next_events") or [])
    out.append({"id": "macro_sensitivity", "title": "Macro sensitivity · FRED", "columns": ["Series", "Latest · trend", "Effect on this name"],
                "rows": rows, "kpis": [("Rate beta to 10-year (% per 1bp)", fmt((macro.get("rate_beta_10y") or 0) * 100 if macro.get("rate_beta_10y") is not None else None)),
                                       ("Next macro events", ev or "n/a")], "note": _gaps(macro)})
    sec = b.get("sec_filings") or {}
    rows = [[f["form"], f.get("filed_at") or "n/a", f.get("writer_note") or f.get("what_changed") or "", f.get("url") or ""]
            for f in sec.get("filings") or []]
    f4 = sec.get("form4_90d") or {}
    if f4.get("buys") is not None:
        rows.append(["Form 4 (90d)", "", f"{f4['buys']} purchases / {f4['sells']} sales", ""])
    if sec.get("ipo"):
        rows.append(["S-1 / 424B", "", sec["ipo"].get("lockup_note") or "", ""])
    out.append({"id": "sec_filings", "title": "Filings · SEC EDGAR", "columns": ["Form", "Filed", "What changed", "EDGAR"],
                "rows": rows, "note": _gaps(sec)})
    call = b.get("earnings_call") or {}
    out.append({"id": "earnings_call", "title": "Earnings call · what management said", "columns": ["Topic", "What was said"], "rows": [
        ["Guidance", call.get("guidance") or "n/a"], ["Demand / margins", call.get("demand_margin") or "n/a"],
        ["Tone vs last call", call.get("tone") or "n/a"], ["Hardest analyst questions", call.get("hard_questions") or "n/a"]],
        "note": _gaps(call)})
    osd = b.get("options_sentiment_dividends") or {}
    ns, so, dv = osd.get("news_sentiment") or {}, osd.get("social") or {}, osd.get("dividend") or {}
    deb = (osd.get("debate") or [{}])[0] if osd.get("debate") else {}
    out.append({"id": "options_sentiment_dividends", "title": "Options, sentiment and dividends", "columns": ["Measure", "Value"], "rows": [
        ["Implied vol · IV rank", f"{fmt(osd.get('iv_pct'), '%')} · {fmt(osd.get('iv_rank'))}"],
        ["Put/call · unusual flow", f"{fmt(osd.get('put_call'))} · {fmt(osd.get('unusual_flow'))}"],
        ["News sentiment 7d", f"{ns.get('label') or 'n/a'} ({fmt(ns.get('weighted_score'))})"],
        ["Social chatter", f"{fmt(so.get('count'))} posts · {fmt(so.get('bullish'))} bullish / {fmt(so.get('bearish'))} bearish"],
        ["Dividend · yield", f"{fmt(dv.get('annual_per_share'), '$')} · {fmt(dv.get('yield_pct'), '%')}"],
        ["House agents' view (debate)", str(deb.get("verdict") or deb.get("consensus") or deb.get("summary") or "n/a")[:200]]],
        "note": _gaps(osd)})
    lt = b.get("fund_lookthrough")
    if lt:
        sw = sorted((lt.get("sector_weights") or {}).items(), key=lambda kv: -(kv[1] if isinstance(kv[1], (int, float)) else 0))[:8]
        out.append({"id": "fund_lookthrough", "title": "Fund look-through · sector weights", "columns": ["Sector", "Weight"],
                    "rows": [[k, fmt(v, "%")] for k, v in sw], "note": f"as of {lt.get('as_of') or 'n/a'}"})
    cov = doc.get("source_coverage") or {}
    rows = [[r["domain"], r["status"], (r.get("as_of") or "")[:10], (r.get("reason") or "") + (f" · refresh {r['refresh']}" if r.get("refresh") else "")]
            for r in cov.get("domains") or []]
    rows += [[f"web: {w['query']}", "used" if w.get("results") else ("failed" if not w.get("ok") else "empty"),
              str(w.get("at") or "")[:10], f"{w.get('provider') or ''} · {w.get('results', 0)} results"] for w in cov.get("web_searches") or []]
    note = "Used · stale (as-of shown) · not applicable · failed. A missing key source marks the report partial."
    if cov.get("key_gaps"):
        note += " PARTIAL: " + "; ".join(cov["key_gaps"])
    out.append({"id": "source_coverage", "title": "Source coverage · every registered source checked",
                "columns": ["Source", "Status", "As of", "Detail"], "rows": rows, "status_col": 1, "note": note})
    return out


# ── the institutional ("Street") blocks (scripts/lib/prospectus/street.py) ──────────────────────────────────────
def _b(v: Any) -> str:
    """$ billions from dollars."""
    return "n/a" if not isinstance(v, (int, float)) else f"{'−' if v < 0 else ''}${abs(v) / 1e9:,.2f}B"


def _n(v: Any) -> str:
    return "n/a" if not isinstance(v, (int, float)) else f"{v:,.0f}"


def _arrow(a: Any, b: Any, unit: str = "") -> str:
    if a in (None, "") and b in (None, ""):
        return "n/a"
    if a in (None, "") or a == b:
        return fmt(b, unit) if not isinstance(b, str) else b
    return f"{fmt(a, unit) if not isinstance(a, str) else a} → {fmt(b, unit) if not isinstance(b, str) else b}"


def street_top_tables(doc: dict) -> list[dict]:
    """Analyst coverage (distribution, target trend, action log), estimates and earnings history, catalyst calendar."""
    b = doc.get("blocks") or {}
    out: list[dict] = []
    ac = b.get("analyst_coverage") or {}
    if ac:
        dist, tg = ac.get("distribution") or {}, ac.get("targets") or {}
        cur = dist.get("current") or {}
        tr = tg.get("trend") or {}
        kpis = [("Consensus", f"{str(tg.get('rating_key') or 'n/a').replace('_', ' ')} · mean {fmt(tg.get('rating_mean'))} (1 = strong buy)"),
                ("Analysts", _n(tg.get("analysts") or cur.get("total"))),
                ("Buy-rated", f"{fmt(cur.get('bullish_pct'), '%')} · {dist.get('trend_90d') or 'trend n/a'}"),
                ("Mean target · upside", f"{fmt(tg.get('mean'), '$')} · {fmt(tg.get('upside_to_mean_pct'), '±%')}"),
                ("Target range", f"{fmt(tg.get('low'), '$')} – {fmt(tg.get('high'), '$')}"),
                ("Mean target 30d · 90d", f"{fmt((tr.get('d30') or {}).get('mean_change_pct'), '±%')} · "
                                          f"{fmt((tr.get('d90') or {}).get('mean_change_pct'), '±%')}")]
        rows = []
        for r in (dist.get("history") or [])[:4]:
            rows.append([str(r.get("period") or "n/a")] + [_n(r.get(k)) for k in ("strong_buy", "buy", "hold", "sell", "strong_sell")]
                        + [fmt(r.get("bullish_pct"), "%")])
        note = []
        if dist.get("source"):
            note.append(f"Ratings: {dist['source']}" + (f", as of {dist['as_of']}" if dist.get("as_of") else "") + ".")
        out.append({"id": "analyst_coverage", "title": "Analyst coverage · what the Street says",
                    "columns": ["Period", "Strong buy", "Buy", "Hold", "Sell", "Strong sell", "Buy-rated"],
                    "rows": rows, "highlight": 0 if rows else None, "kpis": kpis,
                    "note": " ".join(note + ["; ".join(g for g in ac.get("gaps") or [] if g.startswith(("rating", "price targets")))]).strip()})
        if tg:
            def col(key: str) -> list[str]:
                return [fmt(tg.get(key), "$")] + [fmt((tr.get(d) or {}).get(key), "$") for d in ("d30", "d60", "d90")]
            trows = [["Mean target"] + col("mean"), ["Low target"] + col("low"), ["High target"] + col("high"),
                     ["Analysts"] + [_n(tg.get("analysts"))] + [_n((tr.get(d) or {}).get("analysts")) for d in ("d30", "d60", "d90")],
                     ["Rating mean (1-5)"] + [fmt(tg.get("rating_mean"))] + [fmt((tr.get(d) or {}).get("rating_mean")) for d in ("d30", "d60", "d90")]]
            out.append({"id": "analyst_targets_trend", "title": "Price-target trend", "columns": ["Measure", "Now", "30 days ago",
                        "60 days ago", "90 days ago"], "rows": trows,
                        "note": f"Yahoo consensus, newest row {tg.get('as_of') or 'n/a'}" + (f" ({tg['stale']})" if tg.get("stale") else "") + "."})
        acts = ac.get("actions") or []
        t90 = ac.get("actions_90d") or {}
        arows = [[a.get("date"), a.get("firm") or "not named", a.get("action_label") or "n/a",
                  _arrow(a.get("from_grade"), a.get("to_grade")) if (a.get("from_grade") or a.get("to_grade")) else "",
                  _arrow(a.get("prior_target"), a.get("target"), "$") if (a.get("prior_target") or a.get("target")) else "",
                  a.get("url") or ("Yahoo" if a.get("source") == "yahoo" else str(a.get("source") or ""))] for a in acts]
        out.append({"id": "analyst_actions", "title": "Analyst action log",
                     "columns": ["Date", "Firm", "Action", "Rating", "Target", "Source"], "rows": arows,
                     "kpis": [("Last 90 days", f"{t90.get('upgrades', 0)} up · {t90.get('downgrades', 0)} down · "
                                               f"{t90.get('initiations', 0)} initiations · {t90.get('target_raises', 0)} target raises · "
                                               f"{t90.get('target_cuts', 0)} cuts")] if acts else [],
                     "note": "; ".join(g for g in ac.get("gaps") or [] if "action" in g) or
                             "Structured rows from Yahoo; news-reported actions are kept only when the headline names the firm and the action."})
    est = b.get("estimates") or {}
    if est:
        rev = est.get("revisions_90d") or {}
        br = est.get("beat_rate") or {}
        trend = {t["period"]: t for t in est.get("eps_trend") or []}
        revs = {r["period"]: r for r in est.get("revisions") or []}
        crows = []
        for c in est.get("consensus") or []:
            t, r = trend.get(c["period"]) or {}, revs.get(c["period"]) or {}
            crows.append([c["label"], f"{fmt(c.get('eps_avg'), '$')} ({_n(c.get('eps_n'))})",
                          f"{fmt(c.get('eps_low'), '$')} – {fmt(c.get('eps_high'), '$')}",
                          f"{_b(c.get('rev_avg'))} ({_n(c.get('rev_n'))})",
                          f"{fmt(c.get('eps_growth_pct'), '±%')} / {fmt(c.get('rev_growth_pct'), '±%')}",
                          f"{fmt(t.get('chg_d30_pct'), '±%')} · {fmt(t.get('chg_d90_pct'), '±%')}",
                          f"{_n(r.get('up_30d'))} / {_n(r.get('down_30d'))}" if r else "n/a"])
        kpis = [("Next report", est.get("next_report") or "n/a"),
                ("Revisions 30d (up / down)", f"{fmt(rev.get('up'))} / {fmt(rev.get('down'))}" if rev.get("window") else "n/a"),
                ("Beat rate", f"{br.get('beats')} of {br.get('quarters')} quarters" if br.get("quarters") else "n/a"),
                ("Average surprise · 1-day move", f"{fmt(br.get('avg_surprise_pct'), '±%')} · ±{fmt(br.get('avg_abs_one_day_pct'), '%')}"
                 if br.get("quarters") else "n/a")]
        out.append({"id": "estimates", "title": "Estimates · consensus and revisions",
                    "columns": ["Period", "EPS consensus (n)", "EPS range", "Revenue consensus (n)", "Growth EPS / rev",
                                "EPS revision 30d · 90d", "Revisions up / down 30d"], "rows": crows, "kpis": kpis,
                    "note": "; ".join(est.get("gaps") or [])})
        hrows = [[e.get("date") or "last", fmt(e.get("actual"), "$"), fmt(e.get("estimate"), "$"), fmt(e.get("surprise_pct"), "±%"),
                  fmt(e.get("one_day_pct"), "±%"), fmt(e.get("five_day_pct"), "±%")] for e in est.get("eps_surprises") or []]
        if hrows:
            out.append({"id": "estimates_history", "title": "Earnings history · beat / miss and the price reaction",
                        "chart": "eps_surprise", "columns": ["Reported", "EPS actual", "EPS estimate", "Surprise", "1-day", "5-day"],
                        "rows": hrows, "note": "Reaction from house closes: the last close before the market could react to the "
                                               "next session and the fifth session."})
    cal = b.get("catalyst_calendar") or {}
    if cal:
        frows = []
        for e in cal.get("forward") or []:
            mv = e.get("implied_move") or {}
            detail = (f"options imply ±{fmt(mv['move_pct'], '%')} (≈{fmt(mv.get('move_usd'), '$')}) to {mv['expiry']}"
                      if mv.get("move_pct") is not None else "") or e.get("detail") or ""
            frows.append([e["date"], e["label"], e.get("time") or "", detail])
        out.append({"id": "catalyst_calendar", "title": f"Catalyst calendar · next {cal.get('horizon_days', 120)} days",
                    "columns": ["Date", "Event", "Time", "What is priced / detail"], "rows": frows,
                    "note": "; ".join(cal.get("gaps") or [])})
        brows = [[e["date"], e["label"], fmt(e.get("one_day_pct"), "±%"), fmt(e.get("five_day_pct"), "±%")]
                 for e in cal.get("backward") or []]
        if brows:
            out.append({"id": "catalyst_history", "title": "Catalysts behind · how the stock reacted",
                        "columns": ["Date", "Event", "1-day", "5-day"], "rows": brows, "note": cal.get("method") or ""})
    return out


def positioning_tables(doc: dict) -> list[dict]:
    pos = (doc.get("blocks") or {}).get("positioning") or {}
    if not pos:
        return []
    sh, inst, ins, opt = pos.get("short") or {}, pos.get("institutional") or {}, pos.get("insider"), pos.get("options") or {}
    rows = [["Short interest · days to cover", f"{fmt(sh.get('short_float_pct'), '%')} of float · {fmt(sh.get('days_to_cover'))}"],
            ["Institutional ownership · change", f"{fmt(inst.get('own_pct'), '%')} · {fmt(inst.get('change_pct'), '±%')}"]]
    if ins is not None:
        rows.append(["Insider Form 4, 90 days", "n/a" if ins.get("net_value_90d") is None else
                     f"{ins['buys_90d']} buys / {ins['sells_90d']} sells · net {fmt(ins['net_value_90d'], '$')}"])
    for h in (inst.get("holders") or [])[:5]:
        rows.append([f"13F: {h.get('institution')}", f"{_n(h.get('shares'))} sh · {fmt(h.get('change_pct'), '±%')} QoQ"])
    if opt:
        rows += [["Put/call (open interest · volume)", f"{fmt(opt.get('put_call_oi'))} · {fmt(opt.get('put_call_volume'))}"
                  + (f" (OI 30d ago {fmt(opt['put_call_oi_30d_ago'])})" if opt.get("put_call_oi_30d_ago") is not None else "")],
                 ["25-delta skew (put − call IV)", fmt(opt.get("skew25"))],
                 ["ATM implied vol · IV rank · percentile", f"{fmt(opt.get('atm_iv_pct'), '%')} · {fmt(opt.get('iv_rank'))} · "
                  f"{fmt(opt.get('iv_percentile'))} ({opt.get('iv_sessions')} sessions since {opt.get('iv_since')})"],
                 ["IV term structure (front · back · slope)", f"{fmt(opt.get('front_iv_pct'), '%')} · {fmt(opt.get('back_iv_pct'), '%')} · "
                  f"{fmt(opt.get('term_slope_pct'), '±%')}"]]
    return [{"id": "positioning", "title": "Positioning · short interest, insiders, institutions, options",
             "columns": ["Measure", "Value"], "rows": rows,
             "note": (f"Options as of {opt.get('as_of')}. " if opt.get("as_of") else "") + "; ".join(pos.get("gaps") or [])}]


def valuation_tables(doc: dict) -> list[dict]:
    b = doc.get("blocks") or {}
    out = []
    vh = b.get("valuation_history") or {}
    pe = vh.get("pe") or {}
    if vh:
        rows = [["Trailing P/E now", fmt(pe.get("current"), "x")],
                [f"Range since {pe.get('since') or 'n/a'} (low · median · high)",
                 f"{fmt(pe.get('min'), 'x')} · {fmt(pe.get('median'), 'x')} · {fmt(pe.get('max'), 'x')}" if pe else "n/a"],
                ["Percentile in its own range", fmt(pe.get("percentile"))],
                ["Now vs its median", fmt(pe.get("vs_median_pct"), "±%")],
                ["Forward P/E (Finviz)", fmt(vh.get("forward_pe"), "x")],
                ["Trailing four-quarter EPS", fmt(pe.get("ttm_eps"), "$")]]
        out.append({"id": "valuation_history", "title": "Valuation vs its own history", "columns": ["Measure", "Value"],
                    "rows": rows, "note": ((pe.get("basis") + ". ") if pe.get("basis") else "") + "; ".join(vh.get("gaps") or [])})
    fx = b.get("fundamentals_xbrl") or {}
    if fx:
        rows = [[q["period_end"] + (" (derived)" if q.get("derived") else ""), _b(q.get("revenue")), fmt(q.get("revenue_yoy_pct"), "±%"), _b(q.get("operating_income")),
                 fmt(q.get("operating_margin_pct"), "%"), _b(q.get("net_income")), _b(q.get("operating_cash_flow")),
                 _b(q.get("net_debt"))] for q in fx.get("quarters") or []]
        out.append({"id": "fundamentals_xbrl", "title": "Reported quarters · SEC XBRL",
                    "columns": ["Quarter end", "Revenue", "YoY", "Operating income", "Op. margin", "Net income",
                                "Operating cash flow", "Net debt"], "rows": rows,
                    "note": "Net debt = long-term debt − cash. " + (fx.get("method") or "") + " " + "; ".join(fx.get("gaps") or [])})
    return out


STREET_TABLE_IDS = ("analyst_coverage", "analyst_targets_trend", "analyst_actions", "estimates", "estimates_history",
                    "catalyst_calendar", "catalyst_history", "positioning", "valuation_history", "fundamentals_xbrl")


def street_tables(doc: dict, *, hidden: tuple[str, ...] = ()) -> list[dict]:
    """The Street tables in reading order for the page (the API's presentation). Only reports built with the Street
    blocks get them (an older report keeps its original estimates card); ids in ``hidden`` (fund) are dropped."""
    b = doc.get("blocks") or {}
    if not any(k in b for k in ("analyst_coverage", "catalyst_calendar", "positioning")):
        return []
    out = [t for t in street_top_tables(doc) + positioning_tables(doc) + valuation_tables(doc)
           if t.get("id") not in hidden]
    for t in out:
        t["chart"] = None
    return out
