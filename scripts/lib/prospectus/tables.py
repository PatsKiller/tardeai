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
    est = b.get("estimates") or {}
    if est:
        rows = [[e.get("date") or "last", fmt(e.get("actual"), "$"), fmt(e.get("estimate"), "$"), fmt(e.get("surprise_pct"), "±%")]
                for e in est.get("eps_surprises") or []]
        rev = est.get("revisions_90d") or {}
        out.append({"id": "estimates", "title": "Estimates and earnings surprises", "chart": "eps_surprise",
                    "columns": ["Quarter", "EPS actual", "EPS estimate", "Surprise"], "rows": rows,
                    "kpis": [("Estimate revisions 90d", f"{fmt(rev.get('up'))} up / {fmt(rev.get('down'))} down"),
                             ("Next report", est.get("next_report") or "n/a")], "note": _gaps(est)})
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
    risk = b.get("risk_technicals") or {}
    if risk:
        out.append({"id": "risk_technicals", "title": "Risk and technicals", "columns": ["Measure", "Value"], "rows": [
            ["Beta vs S&P (1Y)", fmt(risk.get("beta_1y"))], ["Volatility (annualized)", fmt(risk.get("vol_annualized_pct"), "%")],
            ["Max drawdown 1Y", fmt(risk.get("max_drawdown_1y_pct"), "±%")], ["Correlation to your book", fmt(risk.get("correlation_to_book"))],
            ["Price vs 50 / 200-day", f"{fmt(risk.get('px_vs_sma50_pct'), '±%')} / {fmt(risk.get('px_vs_sma200_pct'), '±%')}"],
            ["RSI(14) · ATR(20)", f"{fmt(risk.get('rsi14'))} · {fmt(risk.get('atr20'), '$')}"]], "note": _gaps(risk)})
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
