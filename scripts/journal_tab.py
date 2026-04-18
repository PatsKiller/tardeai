"""journal_tab.py — Trade Journal v2 HTML tab. Called by portfolio_dashboard.py."""
from __future__ import annotations
import html as _html, json as _json, calendar as _cal
from datetime import datetime
from typing import Dict, List

def _e(s):
    return _html.escape(str(s)) if s is not None else ""

def _cc(v):
    if v is None: return "nt"
    try:
        f = float(v)
        return "up" if f > 0 else ("dn" if f < 0 else "nt")
    except:
        return "nt"

def _chart_card(title, svg):
    return (f"<div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:10px'>"
            f"<div style='font-size:11px;color:#9A9AB0;margin-bottom:4px'>{title}</div>"
            f"{svg}</div>")

def _svg_equity(eq, w=380, h=120):
    vals = [d.get("cumulative", d.get("cumulative_pnl", d.get("value", 0))) for d in eq]
    dates= [d["date"] for d in eq]
    if len(vals) < 2:
        return "<p style='color:#9A9AB0;font-size:11px'>Accumulating...</p>"
    mn,mx = min(vals),max(vals); rng = mx-mn or 1; pad = 28
    px = lambda v: pad + (v-mn)/rng*(w-pad*2)
    py = lambda v: h-pad - (v-mn)/rng*(h-pad*2)
    col = "#0F9D58" if vals[-1] >= 0 else "#DB4437"
    pts = " ".join(f"{px(v):.1f},{py(v):.1f}" for v in vals)
    fill = f"{px(vals[0]):.1f},{h-pad} {pts} {px(vals[-1]):.1f},{h-pad}"
    zero = ""
    if mn < 0 < mx:
        y0 = py(0)
        zero = f"<line x1='{pad}' y1='{y0:.1f}' x2='{w-pad}' y2='{y0:.1f}' stroke='#3a3a5e' stroke-dasharray='3,2'/>"
    xlbls = ""
    step = max(1, len(dates)//4)
    for i in range(0, len(dates), step):
        x = px(vals[i]); lbl = dates[i][5:]
        xlbls += f"<text x='{x:.1f}' y='{h-2}' fill='#9A9AB0' font-size='7' text-anchor='middle'>{_e(lbl)}</text>"
    circles = "".join(
        f"<circle cx='{px(v):.1f}' cy='{py(v):.1f}' r='6' fill='transparent'"
        f" data-val='{v:.2f}' data-date='{_e(dates[i])}'/>" for i,v in enumerate(vals))
    return (f"<svg width='{w}' height='{h}' style='display:block'>"
            f"<polygon points='{fill}' fill='{col}22'/>"
            f"<polyline points='{pts}' fill='none' stroke='{col}' stroke-width='2'/>"
            f"{zero}{xlbls}{circles}"
            f"<text x='4' y='12' fill='#9A9AB0' font-size='7'>${mx:,.0f}</text>"
            f"<text x='4' y='{h-4}' fill='#9A9AB0' font-size='7'>${mn:,.0f}</text>"
            f"</svg>")

def _svg_drawdown(dd, w=380, h=100):
    vals = [d["drawdown"] for d in dd]
    if len(vals) < 2: return "<p style='color:#9A9AB0;font-size:11px'>Accumulating...</p>"
    mn = min(vals); pad = 20
    px = lambda i: pad + i/(len(vals)-1)*(w-pad*2)
    py = lambda v: pad + (0-v)/(-mn or 1)*(h-pad*2)
    pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i,v in enumerate(vals))
    fill = f"{pad},{pad} {pts} {px(len(vals)-1):.1f},{pad}"
    dd_dates = [d.get("date", d.get("close_date", "")) for d in dd]
    dd_circles = "".join(
        f"<circle cx='{px(i):.1f}' cy='{py(v):.1f}' r='6' fill='transparent'"
        f" data-dd='{abs(v):.2f}' data-date='{_e(dd_dates[i])}'/>" for i,v in enumerate(vals))
    return (f"<svg width='{w}' height='{h}' style='display:block'>"
            f"<polygon points='{fill}' fill='#DB443733'/>"
            f"<polyline points='{pts}' fill='none' stroke='#DB4437' stroke-width='1.5'/>"
            f"{dd_circles}"
            f"<text x='4' y='14' fill='#9A9AB0' font-size='7'>Max: ${mn:,.0f}</text>"
            f"</svg>")

def _svg_scatter(scatter, w=380, h=150):
    if not scatter:
        return (
            "<div style='background:#1a1a35;border:1px solid #2a2a5e;border-radius:6px;padding:12px;text-align:center'>"
            "<div style='color:#9A9AB0;font-size:11px;margin-bottom:6px'>⏱️ No timestamp data in current CSVs</div>"
            "<div style='font-size:10px;color:#6a6a8a'>To enable: Schwab → Accounts → History → export <b style=\'color:#F4B400\'>Transaction History</b><br>"
            "(not Gain/Loss) — includes trade timestamps</div>"
            "</div>"
        )
    pnls=[d["pnl"] for d in scatter]; mins=[d["close_min"] for d in scatter]
    mn_p,mx_p=min(pnls),max(pnls); rng_p=mx_p-mn_p or 1
    mn_t,mx_t=min(mins),max(mins); rng_t=mx_t-mn_t or 1; pad=28
    px = lambda m: pad+(m-mn_t)/rng_t*(w-pad*2)
    py = lambda v: h-pad-(v-mn_p)/rng_p*(h-pad*2)
    dots=""
    for d in scatter:
        cx=px(d["close_min"]); cy=py(d["pnl"])
        col="#0F9D58" if d["is_win"] else "#DB4437"
        dots+=f"<circle cx='{cx:.1f}' cy='{cy:.1f}' r='3.5' fill='{col}99'/>"
    zero=""
    if mn_p<0<mx_p:
        y0=py(0)
        zero=f"<line x1='{pad}' y1='{y0:.1f}' x2='{w-pad}' y2='{y0:.1f}' stroke='#3a3a5e' stroke-dasharray='3,2'/>"
    xlbls=""
    for hhmm in range(max(int(mn_t)//60*60,540),min(int(mx_t)+61,960),60):
        if mn_t<=hhmm<=mx_t:
            x=px(hhmm)
            xlbls+=f"<text x='{x:.1f}' y='{h-3}' fill='#9A9AB0' font-size='7' text-anchor='middle'>{hhmm//60}:{hhmm%60:02d}</text>"
    return (f"<svg width='{w}' height='{h}' style='display:block'>"
            f"{zero}{dots}{xlbls}"
            f"<text x='2' y='12' fill='#9A9AB0' font-size='7'>${mx_p:+,.0f}</text>"
            f"<text x='2' y='{h-14:.0f}' fill='#9A9AB0' font-size='7'>${mn_p:+,.0f}</text>"
            f"</svg>")

def _svg_winrate(rwr, w=380, h=80):
    vals=[d["win_rate"] for d in rwr]
    if len(vals)<5: return "<p style='color:#9A9AB0;font-size:11px'>Need 5+ trades</p>"
    pad=16
    px = lambda i: pad+i/(len(vals)-1)*(w-pad*2)
    py = lambda v: h-pad-v/100*(h-pad*2)
    pts=" ".join(f"{px(i):.1f},{py(v):.1f}" for i,v in enumerate(vals))
    y50=py(50)
    # Trade number comes from rolling_win_rate index (each entry = one trade)
    wr_nums = [d.get('trade_num', i+1) for i, d in enumerate(rwr)]
    wr_circles = "".join(
        f"<circle cx='{px(i):.1f}' cy='{py(v):.1f}' r='5' fill='transparent' "
        f"data-wr='{v:.1f}' data-n='{wr_nums[i]}'/>"
        for i, v in enumerate(vals)
    )
    return (f"<svg width='{w}' height='{h}' style='display:block'>"
            f"<line x1='{pad}' y1='{y50:.1f}' x2='{w-pad}' y2='{y50:.1f}' stroke='#3a3a5e' stroke-dasharray='3,2'/>"
            f"<polyline points='{pts}' fill='none' stroke='#2979FF' stroke-width='2'/>"
            f"{wr_circles}"
            f"<text x='4' y='12' fill='#9A9AB0' font-size='7'>100%</text>"
            f"<text x='4' y='{y50:.0f}' fill='#9A9AB0' font-size='7'>50%</text>"
            f"</svg>")

def _build_calendar(closed):
    by_date = {}
    for t in closed:
        d = t.get("close_date","")[:10]
        if not d or d=="UNKNOWN": continue
        if d not in by_date: by_date[d]={"pnl":0,"count":0,"syms":[]}
        by_date[d]["pnl"] = round(by_date[d]["pnl"]+t.get("pnl",0), 2)
        by_date[d]["count"] += 1
        s = t.get("symbol","")
        if s and s not in by_date[d]["syms"]: by_date[d]["syms"].append(s)
    if not by_date: return ""

    # Limit to last 6 months to keep HTML small
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    by_date = {k:v for k,v in by_date.items() if k >= cutoff}
    if not by_date: return ""

    dates = sorted(by_date.keys())
    first = datetime.strptime(dates[0],"%Y-%m-%d").replace(day=1)
    last  = datetime.strptime(dates[-1],"%Y-%m-%d")
    parts = ["<div id='jcal' style='display:none;margin-bottom:14px'>"]
    cur = first
    while cur <= last:
        nd  = _cal.monthrange(cur.year, cur.month)[1]
        dow = datetime(cur.year,cur.month,1).weekday()
        hdr = "".join(f"<th style='font-size:8px;color:#9A9AB0;padding:1px 4px'>{x}</th>"
                      for x in ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"])
        cells = ["<td></td>"*dow]
        for dn in range(1, nd+1):
            ds = f"{cur.year}-{cur.month:02d}-{dn:02d}"
            info = by_date.get(ds,{})
            p = info.get("pnl",0); cnt = info.get("count",0)
            if p > 0:    bg,bdr,tc = "#0F9D5820","#0F9D58","#0F9D58"
            elif p < 0:  bg,bdr,tc = "#DB443720","#DB4437","#DB4437"
            elif cnt > 0:bg,bdr,tc = "#2a2a5e20","#3a3a5e","#9A9AB0"
            else:        bg,bdr,tc = "transparent","transparent","#3a3a5e"
            pstr = f"${p:+,.0f}" if cnt else ""
            sym  = _e((info.get("syms") or [""])[0]) if cnt else ""
            ocl  = f"onclick=\"jFilterDate('{ds}')\"" if cnt else ""
            cursor = "pointer" if cnt else "default"
            cells.append(
                f"<td style='background:{bg};border:1px solid {bdr};border-radius:4px;"
                f"padding:3px 4px;min-width:42px;vertical-align:top;cursor:{cursor}' {ocl}>"
                f"<div style='font-size:8px;color:#9A9AB0'>{dn}</div>"
                f"<div style='font-size:10px;font-weight:700;color:{tc}'>{pstr}</div>"
                f"<div style='font-size:8px;color:#9A9AB0'>{sym}</div></td>"
            )
            if datetime(cur.year,cur.month,dn).weekday()==6:
                cells.append("</tr><tr>")
        parts.append(
            f"<div style='margin-bottom:12px'>"
            f"<div style='font-size:12px;font-weight:700;color:#e0e0f0;margin-bottom:5px'>{cur.strftime('%B %Y')}</div>"
            f"<table style='border-collapse:separate;border-spacing:2px'>"
            f"<thead><tr>{hdr}</tr></thead>"
            f"<tbody><tr>{''.join(cells)}</tr></tbody></table></div>"
        )
        cur = datetime(cur.year+1,1,1) if cur.month==12 else datetime(cur.year,cur.month+1,1)
    parts.append("</div>")
    return "".join(parts)

def build_journal_tab(journal: Dict, behavioral: Dict = None) -> str:
    if not journal.get("has_data"):
        return ("<div class='section-title'>📓 Trade Journal</div>"
                "<div style='background:#1a1a35;border:1px solid #F4B400;border-radius:8px;padding:16px'>"
                "<b style='color:#F4B400'>📂 Export Schwab History CSV to activate</b><br><br>"
                "<span style='color:#9A9AB0;font-size:12px'>"
                "Accounts → History → Export → CSV → save to <code>data/portfolios/input/</code><br>"
                "Repeat for each account. Re-run <code>scripts/run_portfolio.bat</code>"
                "</span></div>")

    stats   = journal.get("stats", {})
    closed  = journal.get("closed_trades", [])
    syms    = journal.get("all_symbols", [])
    accts   = journal.get("all_accounts", [])
    opens   = journal.get("open_lots", [])
    eq      = stats.get("equity_curve", [])
    dd      = stats.get("drawdown_data", [])
    rwr     = stats.get("rolling_winrate", [])
    scatter = stats.get("time_scatter", [])

    total_pnl  = stats.get("total_pnl", 0)
    win_rate   = stats.get("win_rate", 0)
    pf         = stats.get("profit_factor", 0)
    avg_win    = stats.get("avg_winner", 0)
    avg_lose   = stats.get("avg_loser", 0)
    n_trades   = stats.get("total_trades", 0)
    n_winners  = stats.get("num_winners", 0)
    n_losers   = stats.get("num_losers", 0)
    expectancy = stats.get("trade_expectancy", 0)
    max_dd     = stats.get("max_drawdown", 0)
    avg_r      = stats.get("avg_r_multiple")

    # ── Type cards ────────────────────────────────────────────────────────────
    TCLR = {"DAY":"#DB4437","SWING":"#F4B400","SHORT":"#2979FF","LONG":"#9A9AB0"}
    by_type = stats.get("by_type",{})
    type_cards_html = ""
    for tt, d in by_type.items():
        tc = TCLR.get(tt,"#9A9AB0"); pv = d.get("total_pnl",0); vc = _cc(pv)
        type_cards_html += (f"<div class='card' style='border-top:3px solid {tc}'>"
                            f"<div class='card-label'>{tt}</div>"
                            f"<div class='card-value {vc}'>${pv:+,.0f}</div>"
                            f"<div class='card-sub nt'>{d.get('count',0)} \u00b7 {d.get('win_rate',0):.0f}%W</div></div>")

    # ── Account cards ─────────────────────────────────────────────────────────
    by_acct = stats.get("by_account", {})
    acct_cards_html = ""
    ACCT_SHORT = {
        "schwab_rollover_ira": "Rollover IRA",
        "schwab_roth":         "Roth IRA",
        "schwab_taxable":      "Individual",
        "Schwab Rollover IRA": "Rollover IRA",
        "Schwab Roth IRA":     "Roth IRA",
        "Schwab Individual (Taxable)": "Individual",
    }
    # Compute avg hold days per account from closed trades
    _acct_holds = {}
    for _t in closed:
        _a = _t.get("account", ""); _h = _t.get("hold_days", 0) or 0
        _acct_holds.setdefault(_a, []).append(_h)

    acct_bar_data = []
    for acct, d in by_acct.items():
        pv   = d.get("total_pnl", 0)
        cnt  = d.get("count", 0)
        wins = d.get("wins", 0)
        wr   = round(wins / cnt * 100, 1) if cnt else 0
        vc   = _cc(pv)
        label = ACCT_SHORT.get(acct, acct[:16])
        _holds = _acct_holds.get(acct, [])
        _avg_h = round(sum(_holds) / len(_holds), 1) if _holds else 0
        _hold_str = f"{int(_avg_h)}d avg" if _avg_h >= 1 else (f"{int(_avg_h*24)}h avg" if _avg_h > 0 else "")
        acct_cards_html += (
            f"<div class='card' style='border-top:3px solid {'#0F9D58' if pv>=0 else '#DB4437'}'>"
            f"<div class='card-label'>{_e(label)}</div>"
            f"<div class='card-value {vc}'>${pv:+,.0f}</div>"
            f"<div class='card-sub nt'>{cnt} trades &middot; {wr:.0f}%W</div>"
            + (f"<div class='card-sub nt' style='font-size:9px;color:#9A9AB0'>{_hold_str}</div>" if _hold_str else "")
            + f"</div>"
        )
        acct_bar_data.append((label, wr, pv))

    # Win rate by account mini bar chart
    def _svg_acct_wr(acct_data, w=380, h=80):
        if not acct_data: return ""
        pad = 30; bar_w = min(60, (w - pad*2) // max(len(acct_data),1) - 8)
        svgc = f"<svg width='{w}' height='{h}' style='display:block'>"
        svgc += f"<line x1='{pad}' y1='{h-pad}' x2='{w-pad}' y2='{h-pad}' stroke='#3a3a5e'/>"
        # 50% line
        y50 = pad + (50/100)*(h-pad*2); svgc += f"<line x1='{pad}' y1='{y50:.0f}' x2='{w-pad}' y2='{y50:.0f}' stroke='#3a3a5e' stroke-dasharray='2,2'/>"
        svgc += f"<text x='{pad-2}' y='{y50:.0f}' fill='#9A9AB0' font-size='7' text-anchor='end'>50%</text>"
        n = len(acct_data); spacing = (w-pad*2) // n
        for i,(label,wr,pnl) in enumerate(acct_data):
            x = pad + i*spacing + spacing//2 - bar_w//2
            bh = int((wr/100)*(h-pad*2)); y = h-pad-bh
            col = "#0F9D58" if wr>=50 else "#DB4437"
            svgc += f"<rect x='{x}' y='{y}' width='{bar_w}' height='{bh}' fill='{col}44' rx='2'/>"
            svgc += f"<rect x='{x}' y='{y}' width='{bar_w}' height='2' fill='{col}'/>"
            svgc += f"<text x='{x+bar_w//2}' y='{h-pad+10}' fill='#9A9AB0' font-size='7' text-anchor='middle'>{_e(label[:8])}</text>"
            svgc += f"<text x='{x+bar_w//2}' y='{y-3}' fill='{col}' font-size='8' text-anchor='middle'>{wr:.0f}%</text>"
        svgc += "</svg>"
        return svgc

    # R-Multiple histogram
    def _svg_r_histogram(closed, w=380, h=100):
        rs = [t.get("r_multiple") for t in closed if t.get("r_multiple") is not None]
        if len(rs) < 3:
            return "<p style='color:#9A9AB0;font-size:11px'>Need stops set — R-Multiple requires stop levels in Risk tab</p>"
        bins = [("< -1R", lambda r: r < -1), ("-1R to 0", lambda r: -1 <= r < 0),
                ("0 to 1R", lambda r: 0 <= r < 1), ("1R to 2R", lambda r: 1 <= r < 2), ("> 2R", lambda r: r >= 2)]
        counts = [sum(1 for r in rs if fn(r)) for _, fn in bins]
        labels = [b[0] for b in bins]
        colors = ["#DB4437","#FF6D00","#F4B400","#0F9D58","#00C853"]
        mx = max(counts) or 1; pad = 30; bar_w = (w-pad*2)//len(bins) - 4
        svgc = f"<svg width='{w}' height='{h}' style='display:block'>"
        for i,(cnt,lbl,col) in enumerate(zip(counts,labels,colors)):
            x = pad + i*(bar_w+4); bh = int(cnt/mx*(h-pad*2)); y = h-pad-bh
            svgc += f"<rect x='{x}' y='{y}' width='{bar_w}' height='{bh}' fill='{col}66' rx='2'/>"
            svgc += f"<rect x='{x}' y='{y}' width='{bar_w}' height='2' fill='{col}'/>"
            if cnt: svgc += f"<text x='{x+bar_w//2}' y='{y-3}' fill='{col}' font-size='9' text-anchor='middle'>{cnt}</text>"
            svgc += f"<text x='{x+bar_w//2}' y='{h-pad+10}' fill='#9A9AB0' font-size='7' text-anchor='middle'>{_e(lbl)}</text>"
        svgc += "</svg>"
        return svgc

    # ── Symbol rows ───────────────────────────────────────────────────────────
    by_sym = stats.get("by_symbol",{})
    sym_rows_html = ""
    for s, d in list(by_sym.items())[:20]:
        pv = d.get("total_pnl",0); ar = d.get("avg_r"); vc = _cc(pv)
        rc = "#0F9D58" if ar and ar>0 else "#DB4437" if ar and ar<0 else "#9A9AB0"
        rs = f"{ar:+.2f}R" if ar is not None else "\u2014"
        sym_rows_html += (f"<tr><td><b style='color:#e0e0f0'>{_e(s)}</b></td>"
                          f"<td class='{vc}' style='text-align:right;font-weight:700'>${pv:+,.0f}</td>"
                          f"<td style='text-align:right;color:#9A9AB0'>{d.get('count',0)}</td>"
                          f"<td style='text-align:right;color:#9A9AB0'>{d.get('win_rate',0):.0f}%</td>"
                          f"<td style='text-align:right;color:{rc}'>{rs}</td></tr>")

    # ── Week rows ─────────────────────────────────────────────────────────────
    by_week = stats.get("by_week",{})
    week_rows_html = ""
    for wk, p in list(by_week.items())[:12]:
        cnt = len([t for t in closed if t.get("week","")==wk])
        vc  = _cc(p)
        week_rows_html += (f"<tr><td>{_e(wk)}</td>"
                           f"<td class='{vc}' style='text-align:right;font-weight:700'>${p:+,.0f}</td>"
                           f"<td style='text-align:right;color:#9A9AB0'>{cnt}</td></tr>")

    # ── Open lots rows ────────────────────────────────────────────────────────
    open_rows_html = ""
    for ol in opens[:25]:
        dh = ol.get("days_held",0)
        ac = "#DB4437" if dh>30 else "#F4B400" if dh>7 else "#9A9AB0"
        open_rows_html += (f"<tr><td>{_e(ol.get('open_date','')[:10])}</td>"
                           f"<td><b style='color:#e0e0f0'>{_e(ol.get('symbol',''))}</b></td>"
                           f"<td style='font-size:10px;color:#9A9AB0'>{_e(ol.get('account',''))[:16]}</td>"
                           f"<td style='text-align:right;color:#9A9AB0'>{ol.get('shares',0):.0f}</td>"
                           f"<td style='text-align:right;color:#9A9AB0'>${ol.get('buy_price',0):.2f}</td>"
                           f"<td style='text-align:right'>${ol.get('cost_basis',0):,.0f}</td>"
                           f"<td style='text-align:right;color:{ac}'>{dh}d</td></tr>")

    # ── Full stats table ──────────────────────────────────────────────────────
    stat_pairs = [
        ("Total P&L",           f"${stats.get('total_pnl',0):+,.2f}"),
        ("Win Rate",            f"{stats.get('win_rate',0):.1f}%"),
        ("Profit Factor",       f"{stats.get('profit_factor',0):.2f}"),
        ("Trade Expectancy",    f"${stats.get('trade_expectancy',0):+,.2f}"),
        ("Avg Winner",          f"${stats.get('avg_winner',0):+,.2f}"),
        ("Avg Loser",           f"${stats.get('avg_loser',0):,.2f}"),
        ("Total Trades",        str(stats.get("total_trades",0))),
        ("Winners / Losers",    f"{stats.get('num_winners',0)} / {stats.get('num_losers',0)}"),
        ("Total Trading Days",  str(stats.get("total_trading_days",0))),
        ("Win Days / Lose Days",f"{stats.get('winning_days',0)} / {stats.get('losing_days',0)}"),
        ("Avg Daily P&L",       f"${stats.get('avg_daily_pnl',0):+,.2f}"),
        ("Avg Winning Day",     f"${stats.get('avg_winning_day',0):+,.2f}"),
        ("Avg Losing Day",      f"${stats.get('avg_losing_day',0):,.2f}"),
        ("Largest Profit Day",  f"${stats.get('largest_profit_day',0):+,.2f}"),
        ("Largest Loss Day",    f"${stats.get('largest_loss_day',0):,.2f}"),
        ("Max Consec Wins",     str(stats.get("max_consec_wins",0))),
        ("Max Consec Losses",   str(stats.get("max_consec_losses",0))),
        ("Avg Hold (All)",      stats.get("avg_hold_all","")),
        ("Avg Hold (Winners)",  stats.get("avg_hold_win","")),
        ("Avg Hold (Losers)",   stats.get("avg_hold_lose","")),
        ("Avg R-Multiple",      f"{avg_r:+.2f}R" if avg_r is not None else "Set stops in Risk tab"),
        ("Max Drawdown",        f"${stats.get('max_drawdown',0):,.2f} ({stats.get('max_drawdown_pct',0):.1f}%)"),
        ("Open Positions",      str(len(opens))),
    ]
    stat_rows_html = "".join(
        f"<div style='display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #1a1a35'>"
        f"<span class='nt'>{k}</span><b style='color:#e0e0f0'>{v}</b></div>"
        for k, v in stat_pairs
    )

    # ── JS data ───────────────────────────────────────────────────────────────
    trades_js = _json.dumps([{
        "sym":t.get("symbol",""), "acct":t.get("account",""),
        "od":t.get("open_date","")[:10], "cd":t.get("close_date","")[:10],
        "ot":t.get("open_time",""),     "ct":t.get("close_time",""),
        "tt":t.get("trade_type",""),    "sh":t.get("shares",0),
        "bp":t.get("buy_price",0),      "sp":t.get("sell_price",0),
        "pnl":t.get("pnl",0),          "pp":t.get("pnl_pct",0),
        "hd":t.get("hold_days",0),      "rm":t.get("r_multiple"),
        "rat":t.get("rating",0),        "setup":t.get("setup",""),
        "exec":t.get("execution",""),   "tags":t.get("tags",[]),
        "note":t.get("note",""),        "nk":t.get("note_key",""),
    } for t in closed], default=str)

    sym_opts  = "".join(f"<option value='{_e(s)}'>{_e(s)}</option>" for s in syms)
    acct_opts = "".join(f"<option value='{_e(a)}'>{_e(a[:28])}</option>" for a in accts)
    SETUP_OPTS = ["","Gap & Go","RVOL Spike","Catalyst Play","Rebalance","Portfolio","Breakout","Reversal","Other"]
    EXEC_OPTS  = ["","Planned","Chased","FOMO","Partial Fill","Stopped Out","Oversize","Undersize"]
    TAG_OPTS   = ["News","FDA","Earnings","Technical","AI Signal","Options Flow","Breakout","Squeeze","Rebalance"]
    setup_opts_js = _json.dumps(SETUP_OPTS)
    exec_opts_js  = _json.dumps(EXEC_OPTS)
    tag_opts_js   = _json.dumps(TAG_OPTS)

    eq_vals  = [d.get("cumulative", d.get("cumulative_pnl", d.get("value", 0))) for d in eq]
    eq_dates = [d.get("date", d.get("close_date", "")) for d in eq]
    wr_badge = "up" if win_rate >= 50 else "dn"
    pf_badge = "up" if pf >= 1 else "dn"
    pnl_col  = "#0F9D58" if total_pnl >= 0 else "#DB4437"
    ar_txt   = f"{avg_r:+.2f}R" if avg_r is not None else "→ Set stops"
    ar_badge = _cc(avg_r)

    cal_html = _build_calendar(closed)

    # Pre-build pill HTML to avoid f-string escaping issues
    def _pill(fn, val, label, group):
        v = val.replace('"', '&quot;')
        return (f"<button onclick=\"{ fn }(&quot;{ v }&quot;,this)\" "
                f"class=\'jpill\' data-group=\'{ group }\'>{ label }</button>")
    sym_pill_html  = "".join(_pill("jPillSym",  s, s,      "sym")  for s in syms[:12])
    acct_pill_html = "".join(_pill("jPillAcct", a, a[:18], "acct") for a in accts)


    return f"""
<div class='section-title'>📓 Trade Journal v2</div>

<div class='cards' style='margin-bottom:10px'>
  <div class='card' style='border-top:3px solid {pnl_col}'>
    <div class='card-label'>Net P&L</div>
    <div class='card-value {_cc(total_pnl)}'>${total_pnl:+,.2f}</div>
    <div class='card-sub nt'>{n_trades} trades</div>
  </div>
  <div class='card'>
    <div class='card-label'>Win Rate</div>
    <div class='card-value {wr_badge}'>{win_rate:.1f}%</div>
    <div class='card-sub nt'>{n_winners}W / {n_losers}L</div>
  </div>
  <div class='card'>
    <div class='card-label'>Profit Factor</div>
    <div class='card-value {pf_badge}'>{pf:.2f}&times;</div>
    <div class='card-sub nt'>Expectancy ${expectancy:+,.2f}</div>
  </div>
  <div class='card'>
    <div class='card-label'>Avg Win / Loss</div>
    <div class='card-value up'>${avg_win:,.0f}</div>
    <div class='card-sub dn'>${avg_lose:,.0f}</div>
  </div>
  <div class='card'>
    <div class='card-label'>Avg R-Multiple</div>
    <div class='card-value {ar_badge}'>{ar_txt}</div>
    <div class='card-sub nt'>{stats.get("r_multiple_count",0)} w/ stop</div>
  </div>
  <div class='card'>
    <div class='card-label'>Max Drawdown</div>
    <div class='card-value dn'>${max_dd:,.0f}</div>
    <div class='card-sub nt'>{stats.get("max_drawdown_pct",0):.1f}% from peak</div>
  </div>
  {type_cards_html}
</div>

<div class='section-title' style='font-size:11px;margin-bottom:6px'>📊 By Account</div>
<div class='cards' style='margin-bottom:8px'>{acct_cards_html}</div>
<div style='display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px'>
  {_chart_card("📊 Win Rate by Account", _svg_acct_wr(acct_bar_data))}
  {_chart_card("📐 R-Multiple Distribution", _svg_r_histogram(closed))}
</div>

<div style='display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px'>
  {_chart_card("📈 Equity Curve", _svg_equity(eq_vals, eq_dates) if eq_vals else "<p class='nt' style='font-size:11px'>No data</p>")}
  {_chart_card("📉 Drawdown", _svg_drawdown(dd))}
  {_chart_card("⏱️ Time-of-Day P&L Scatter", _svg_scatter(scatter))}
  {_chart_card("📊 Rolling 20-Trade Win Rate", _svg_winrate(rwr))}
</div>

<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:12px'>
  <div>
    <div class='section-title' style='font-size:11px'>📅 Weekly P&L</div>
    <table><thead><tr><th>Week</th><th style='text-align:right'>P&L</th><th style='text-align:right'>Trades</th></tr></thead>
    <tbody style='font-size:11px'>{week_rows_html or "<tr><td colspan='3' class='nt'>No data</td></tr>"}</tbody></table>
  </div>
  <div>
    <div class='section-title' style='font-size:11px'>🏆 By Symbol</div>
    <table><thead><tr><th>Symbol</th><th style='text-align:right'>P&L</th><th style='text-align:right'>#</th><th style='text-align:right'>W%</th><th style='text-align:right'>AvgR</th></tr></thead>
    <tbody style='font-size:11px'>{sym_rows_html or "<tr><td colspan='5' class='nt'>No data</td></tr>"}</tbody></table>
  </div>
  <div>
    <div class='section-title' style='font-size:11px'>🔓 Open Lots</div>
    <table><thead><tr><th>Opened</th><th>Sym</th><th>Acct</th><th style='text-align:right'>Sh</th><th style='text-align:right'>Buy</th><th style='text-align:right'>Cost</th><th style='text-align:right'>Age</th></tr></thead>
    <tbody style='font-size:11px'>{open_rows_html or "<tr><td colspan='7' class='nt'>All closed</td></tr>"}</tbody></table>
  </div>
</div>

<div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:12px 16px;margin-bottom:12px'>
  <div style='display:grid;grid-template-columns:1fr 1fr;gap:0 24px;font-size:12px'>{stat_rows_html}</div>
</div>

<div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:10px 14px;margin-bottom:8px'>
  <!-- Date range pill buttons (Row 1) -->
  <div style='display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:8px'>
    <span style='font-size:10px;color:#9A9AB0;margin-right:2px'>📅 Period:</span>
    <button onclick='jSetDate("all",this)' id='jpill-all' class='jpill active-pill' data-group='period'>All</button>
    <button onclick='jSetDate("today",this)' id='jpill-today' class='jpill' data-group='period'>Today</button>
    <button onclick='jSetDate("week",this)' id='jpill-week' class='jpill' data-group='period'>This Week</button>
    <button onclick='jSetDate("month",this)' id='jpill-month' class='jpill' data-group='period'>This Month</button>
    <button onclick='jSetDate("quarter",this)' id='jpill-quarter' class='jpill' data-group='period'>Quarter</button>
    <button onclick='jSetDate("ytd",this)' id='jpill-ytd' class='jpill' data-group='period'>YTD</button>
    <button onclick='jSetDate("7d",this)' id='jpill-7d' class='jpill' data-group='period'>Last 7D</button>
    <button onclick='jSetDate("30d",this)' id='jpill-30d' class='jpill' data-group='period'>Last 30D</button>
    <button onclick='jSetDate("90d",this)' id='jpill-90d' class='jpill' data-group='period'>Last 90D</button>
  </div>
  <!-- Filter pills row (Row 2) — hidden selects keep JS working -->
  <select id='jf-date' onchange='jApply()' style='display:none'><option value='all'>all</option></select>
  <select id='jf-sym'    onchange='jApply()' style='display:none'><option value=''>All Symbols</option>{sym_opts}</select>
  <select id='jf-acct'   onchange='jApply()' style='display:none'><option value=''>All Accounts</option>{acct_opts}</select>
  <select id='jf-type'   onchange='jApply()' style='display:none'><option value=''>All Types</option><option>DAY</option><option>SWING</option><option>SHORT</option><option>LONG</option></select>
  <select id='jf-result' onchange='jApply()' style='display:none'><option value=''>All Results</option><option value='win'>Winners</option><option value='loss'>Losers</option></select>
  <select id='jf-setup'  onchange='jApply()' style='display:none'><option value=''>All Setups</option>{"".join(f"<option>{o}</option>" for o in SETUP_OPTS[1:])}</select>

  <!-- Symbol pills -->
  <div style='display:flex;gap:5px;flex-wrap:wrap;align-items:center;margin-bottom:6px'>
    <span style='font-size:10px;color:#9A9AB0;min-width:50px'>Symbol:</span>
    <button onclick='jPillSym("",this)' class='jpill active-pill' data-group='sym'>All</button>
    {sym_pill_html}
  </div>
  <!-- Account pills -->
  <div style='display:flex;gap:5px;flex-wrap:wrap;align-items:center;margin-bottom:6px'>
    <span style='font-size:10px;color:#9A9AB0;min-width:50px'>Account:</span>
    <button onclick='jPillAcct("",this)' class='jpill active-pill' data-group='acct'>All</button>
    {acct_pill_html}
  </div>
  <!-- Type + Result + Setup pills -->
  <div style='display:flex;gap:5px;flex-wrap:wrap;align-items:center'>
    <span style='font-size:10px;color:#9A9AB0;min-width:50px'>Type:</span>
    <button onclick='jPillType("",this)' class='jpill active-pill' data-group='type'>All</button>
    <button onclick='jPillType("DAY",this)' class='jpill' data-group='type' style='border-color:#DB443766;color:#DB4437'>DAY</button>
    <button onclick='jPillType("SWING",this)' class='jpill' data-group='type' style='border-color:#F4B40066;color:#F4B400'>SWING</button>
    <button onclick='jPillType("SHORT",this)' class='jpill' data-group='type' style='border-color:#2979FF66;color:#2979FF'>SHORT</button>
    <button onclick='jPillType("LONG",this)' class='jpill' data-group='type' style='border-color:#9A9AB066;color:#9A9AB0'>LONG</button>
    <span style='color:#3a3a5e;margin:0 4px'>|</span>
    <button onclick='jPillResult("",this)' class='jpill active-pill' data-group='result'>All</button>
    <button onclick='jPillResult("win",this)' class='jpill' data-group='result' style='color:#0F9D58'>&#9650; Winners</button>
    <button onclick='jPillResult("loss",this)' class='jpill' data-group='result' style='color:#DB4437'>&#9660; Losers</button>
    <div style='margin-left:auto;display:flex;gap:6px'>
      <button onclick='jToggleCal()' style='background:#2979FF;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px'>📅 Calendar</button>
      <button onclick='jExportCSV()' style='background:#0F9D58;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px'>&#11015; CSV</button>
      <button onclick='jClear()' style='background:#3a3a5e;color:#9A9AB0;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px'>&#10005; Clear All</button>
    </div>
  </div>
</div>
<div id='jfilt-summary' style='font-size:11px;color:#9A9AB0;margin-bottom:6px'></div>

{cal_html}

<div style='overflow-x:auto'>
<table id='jtable'>
  <thead><tr style='font-size:10px;color:#9A9AB0;cursor:pointer'>
    <th onclick='jSort(0)'>Close Date &#8597;</th>
    <th onclick='jSort(1)'>Symbol &#8597;</th>
    <th onclick='jSort(2)'>Account &#8597;</th>
    <th onclick='jSort(3)'>Type &#8597;</th>
    <th onclick='jSort(4)' style='text-align:right'>Sh &#8597;</th>
    <th onclick='jSort(5)' style='text-align:right'>Buy$ &#8597;</th>
    <th onclick='jSort(6)' style='text-align:right'>Sell$ &#8597;</th>
    <th onclick='jSort(7)' style='text-align:right'>Hold &#8597;</th>
    <th onclick='jSort(8)' style='text-align:right'>P&amp;L$ &#8597;</th>
    <th onclick='jSort(9)' style='text-align:right'>P&amp;L% &#8597;</th>
    <th onclick='jSort(10)' style='text-align:right'>R &#8597;</th>
    <th onclick='jSort(11)'>Setup &#8597;</th>
    <th>&#9733;</th><th>Notes</th><th></th>
  </tr></thead>
  <tbody id='jtbody'></tbody>
</table>
</div>

<div id='jdrawer' style='position:fixed;top:0;right:-440px;width:420px;height:100vh;
     background:#1a1a35;border-left:2px solid #2979FF;z-index:9998;overflow-y:auto;
     transition:right .3s;padding:20px;box-shadow:-4px 0 20px #000a'>
  <button onclick="document.getElementById('jdrawer').style.right='-440px'"
          style='float:right;background:none;border:none;color:#9A9AB0;font-size:20px;cursor:pointer'>&#10005;</button>
  <h3 id='jd-title' style='color:#7BB3FF;font-size:14px;margin-bottom:12px'></h3>
  <div id='jd-body'></div>
</div>

<style>
.jpill{{background:#1a1a35;color:#9A9AB0;border:1px solid #3a3a5e;padding:4px 10px;border-radius:12px;cursor:pointer;font-size:11px;transition:all 0.15s}}
.jcal-day{{transition:all 0.15s}}
.jcal-day:hover{{filter:brightness(1.4);transform:scale(1.05)}}
.jpill:hover{{background:#2a2a5e;color:#e0e0f0}}
.active-pill{{background:#2979FF!important;color:#fff!important;border-color:#2979FF!important}}
</style>
<script>
var JT_ALL = {trades_js};

// ── Chart hover tooltip infrastructure ────────────────────────────────────────
var _jTip = null;
function _jTipCreate() {{
  if (_jTip) return;
  _jTip = document.createElement('div');
  _jTip.id = 'jtip';
  _jTip.style.cssText = 'position:fixed;background:#1a1a35;border:1px solid #2979FF;border-radius:6px;padding:6px 10px;font-size:11px;color:#e0e0f0;pointer-events:none;z-index:9999;display:none;white-space:nowrap;box-shadow:0 2px 12px #0008';
  document.body.appendChild(_jTip);
}}
function _jTipShow(e, html) {{
  _jTipCreate();
  _jTip.innerHTML = html;
  _jTip.style.display = 'block';
  _jTipMove(e);
}}
function _jTipHide() {{
  if (_jTip) _jTip.style.display = 'none';
}}
function _jTipMove(e) {{
  if (!_jTip || _jTip.style.display === 'none') return;
  var x = e.clientX + 14, y = e.clientY - 28;
  if (x + 200 > window.innerWidth) x = e.clientX - 200;
  _jTip.style.left = x + 'px'; _jTip.style.top = y + 'px';
}}

// Attach hover tooltips to equity curve SVG circles after DOM ready
function _jAttachChartTooltips() {{
  // Equity curve: circles with data-date and data-val attributes
  document.querySelectorAll('circle[data-val]').forEach(function(c) {{
    c.style.cursor = 'pointer';
    c.addEventListener('mouseenter', function(e) {{
      var date = c.getAttribute('data-date') || '';
      var val  = parseFloat(c.getAttribute('data-val') || 0);
      var col  = val >= 0 ? '#0F9D58' : '#DB4437';
      _jTipShow(e, (date ? '<b style="color:#9A9AB0">'+date+'</b><br>' : '') +
        'P&L: <b style="color:'+col+'">' + (val>=0?'+':'') + '$' + Math.abs(val).toLocaleString('en',{{minimumFractionDigits:2,maximumFractionDigits:2}}) + '</b>');
    }});
    c.addEventListener('mousemove', _jTipMove);
    c.addEventListener('mouseleave', _jTipHide);
  }});
  // Drawdown: rects with data-date and data-dd
  document.querySelectorAll('rect[data-dd]').forEach(function(r) {{
    r.style.cursor = 'pointer';
    r.addEventListener('mouseenter', function(e) {{
      var date = r.getAttribute('data-date') || '';
      var dd   = parseFloat(r.getAttribute('data-dd') || 0);
      _jTipShow(e, (date ? '<b style="color:#9A9AB0">'+date+'</b><br>' : '') +
        'Drawdown: <b style="color:#DB4437">$' + dd.toLocaleString('en',{{minimumFractionDigits:2,maximumFractionDigits:2}}) + '</b>');
    }});
    r.addEventListener('mousemove', _jTipMove);
    r.addEventListener('mouseleave', _jTipHide);
  }});
  // Rolling win rate: circles with data-wr
  document.querySelectorAll('circle[data-wr]').forEach(function(c) {{
    c.style.cursor = 'pointer';
    c.addEventListener('mouseenter', function(e) {{
      var n  = c.getAttribute('data-n') || '';
      var wr = parseFloat(c.getAttribute('data-wr') || 0);
      var col = wr >= 50 ? '#0F9D58' : '#DB4437';
      _jTipShow(e, (n ? 'Trade #'+n+'<br>' : '') +
        'Win Rate: <b style="color:'+col+'">' + wr.toFixed(1) + '%</b>');
    }});
    c.addEventListener('mousemove', _jTipMove);
    c.addEventListener('mouseleave', _jTipHide);
  }});
}}
// Run after DOM is ready
if (document.readyState === 'loading') {{
  document.addEventListener('DOMContentLoaded', _jAttachChartTooltips);
}} else {{
  setTimeout(_jAttachChartTooltips, 100);
}}
console.log('[journal_tab] v2.1 loaded — JT_ALL:', JT_ALL.length, 'trades');
var jSortCol=0,jSortDir=-1,jFiltered=JT_ALL.slice();
var SETUP_OPTS={setup_opts_js};
var EXEC_OPTS={exec_opts_js};
var TAG_OPTS={tag_opts_js};
var TCLR={{DAY:'#DB4437',SWING:'#F4B400',SHORT:'#2979FF',LONG:'#9A9AB0'}};

var jActiveDateFilter='all';
function jSetDate(val,btn){{
  jActiveDateFilter=val;
  document.querySelectorAll('.jpill[data-group="period"]').forEach(function(b){{b.classList.remove('active-pill');}});
  if(btn)btn.classList.add('active-pill');
  jApply();
}}
function jApply(){{
  var df=jActiveDateFilter;
  var sf=document.getElementById('jf-sym').value,
      af=document.getElementById('jf-acct').value,tf=document.getElementById('jf-type').value,
      rf=document.getElementById('jf-result').value,stf=document.getElementById('jf-setup').value;
  var now=new Date(),today=now.toISOString().split('T')[0];
  var wa=new Date(+now-7*864e5).toISOString().split('T')[0];
  var ma=new Date(now.getFullYear(),now.getMonth(),1).toISOString().split('T')[0];
  var qa=new Date(now.getFullYear(),Math.floor(now.getMonth()/3)*3,1).toISOString().split('T')[0];
  var ya=now.getFullYear()+'-01-01';
  var d7=new Date(+now-7*864e5).toISOString().split('T')[0];
  var d30=new Date(+now-30*864e5).toISOString().split('T')[0];
  var d90=new Date(+now-90*864e5).toISOString().split('T')[0];
  jFiltered=JT_ALL.filter(function(t){{
    if(sf&&t.sym!==sf)return false; if(af&&t.acct!==af)return false;
    if(tf&&t.tt!==tf)return false;
    if(rf==='win'&&t.pnl<=0)return false; if(rf==='loss'&&t.pnl>=0)return false;
    if(stf&&t.setup!==stf)return false;
    if(df==='today'&&t.cd!==today)return false;
    if(df==='week'&&t.cd<wa)return false;
    if(df==='month'&&t.cd<ma)return false;
    if(df==='quarter'&&t.cd<qa)return false;
    if(df==='ytd'&&t.cd<ya)return false;
    if(df==='7d'&&t.cd<d7)return false;
    if(df==='30d'&&t.cd<d30)return false;
    if(df==='90d'&&t.cd<d90)return false;
    return true;
  }});
  jRender(); jSummary();
}}
function jSort(c){{
  if(jSortCol===c)jSortDir*=-1; else{{jSortCol=c;jSortDir=-1;}}
  var keys=['cd','sym','acct','tt','sh','bp','sp','hd','pnl','pp','rm','setup'];
  var k=keys[c];
  jFiltered.sort(function(a,b){{
    var av=a[k],bv=b[k];
    if(av==null)av=-9e9; if(bv==null)bv=-9e9;
    return(typeof av==='string'?av.localeCompare(bv):(av-bv))*jSortDir;
  }});
  jRender();
}}
function jFilterDate(d){{
  // Filter table to this date
  jFiltered=JT_ALL.filter(function(t){{return t.cd===d;}});
  jRender(); jSummary();
  // Highlight the matching period pill as custom date
  document.querySelectorAll('.jpill[data-group="period"]').forEach(function(b){{b.classList.remove('active-pill');}});
  // Scroll table into view smoothly
  var tbl=document.getElementById('jtable');
  if(tbl) tbl.scrollIntoView({{behavior:'smooth',block:'start'}});
  // Update filter summary to show which date was clicked
  var s=document.getElementById('jfilt-summary');
  if(s){{
    var n=jFiltered.length;
    var pnl=jFiltered.reduce(function(a,t){{return a+t.pnl;}},0);
    s.innerHTML='<b style="color:#2979FF">📅 '+d+'</b> — '+n+' trade'+(n!==1?'s':'')+
      ' | P&L: <b style="color:'+(pnl>=0?'#0F9D58':'#DB4437')+'">'+(pnl>=0?'+':'')+'$'+Math.abs(pnl).toFixed(2)+'</b>'+
      ' <span style="color:#9A9AB0;font-size:10px;margin-left:8px;cursor:pointer" onclick="jClear()">✕ clear</span>';
  }}
}}
// ── Pill filter helpers ────────────────────────────────────────────────────
function jActivatePill(group, el) {{
  document.querySelectorAll('.jpill[data-group="'+group+'"]').forEach(function(b){{
    b.classList.remove('active-pill');
  }});
  el.classList.add('active-pill');
}}
function jPillSym(val, el) {{
  jActivatePill('sym', el);
  document.getElementById('jf-sym').value = val;
  jApply();
}}
function jPillAcct(val, el) {{
  jActivatePill('acct', el);
  document.getElementById('jf-acct').value = val;
  jApply();
}}
function jPillType(val, el) {{
  jActivatePill('type', el);
  document.getElementById('jf-type').value = val;
  jApply();
}}
function jPillResult(val, el) {{
  jActivatePill('result', el);
  document.getElementById('jf-result').value = val;
  jApply();
}}

// Override jClear to also reset pills
var _jClearOrig = jClear;
jClear = function() {{
  // Reset all active pills to "All"
  ['sym','acct','type','result'].forEach(function(group) {{
    var first = document.querySelector('.jpill[data-group="'+group+'"]');
    if (first) {{
      document.querySelectorAll('.jpill[data-group="'+group+'"]').forEach(function(b){{b.classList.remove('active-pill');}});
      first.classList.add('active-pill');
    }}
  }});
  _jClearOrig();
}};

function jClear(){{
  ['jf-sym','jf-acct','jf-type','jf-result','jf-setup'].forEach(function(id){{
    document.getElementById(id).value='';
  }});
  jActiveDateFilter='all';
  document.querySelectorAll('.jpill').forEach(function(b){{b.classList.remove('active-pill');}});
  document.querySelectorAll('.jpill[data-group="period"]').forEach(function(b){{b.classList.remove('active-pill');}});
  var allBtn=document.getElementById('jpill-all');
  if(allBtn)allBtn.classList.add('active-pill');
  jFiltered=JT_ALL.slice();jRender();jSummary();
}}
function jToggleCal(){{var c=document.getElementById('jcal');if(c)c.style.display=c.style.display==='none'?'block':'none';}}
function jRender(){{
  var TB=document.getElementById('jtbody'); TB.innerHTML='';
  jFiltered.slice(0,200).forEach(function(t){{
    var pc=t.pnl>=0?'#0F9D58':'#DB4437',tc=TCLR[t.tt]||'#9A9AB0';
    var rm=t.rm!=null?('<span style="color:'+(t.rm>=0?'#0F9D58':'#DB4437')+'">'+(t.rm>=0?'+':'')+t.rm.toFixed(2)+'R</span>'):'<span style="color:#3a3a5e">&#8212;</span>';
    var stars='';for(var i=1;i<=5;i++)stars+='<span style="color:'+(i<=t.rat?'#F4B400':'#3a3a5e')+'">&#9733;</span>';
    var tr=document.createElement('tr');
    tr.style.cssText='cursor:pointer;font-size:11px';
    tr.innerHTML='<td>'+t.cd+(t.ct?'<br><span style="color:#9A9AB0;font-size:9px">'+t.ct+'</span>':'')+'</td>'
      +'<td><b style="color:#e0e0f0">'+t.sym+'</b></td>'
      +'<td style="font-size:10px;color:#9A9AB0">'+t.acct.substring(0,16)+'</td>'
      +'<td><span style="background:'+tc+'22;color:'+tc+';padding:1px 5px;border-radius:3px;font-size:9px">'+t.tt+'</span></td>'
      +'<td style="text-align:right;color:#9A9AB0">'+t.sh.toFixed(0)+'</td>'
      +'<td style="text-align:right;color:#9A9AB0">$'+t.bp.toFixed(2)+'</td>'
      +'<td style="text-align:right;color:#9A9AB0">$'+t.sp.toFixed(2)+'</td>'
      +'<td style="text-align:right;color:#9A9AB0">'+t.hd+'d</td>'
      +'<td style="text-align:right;font-weight:700;color:'+pc+'">'+(t.pnl>=0?'$+':'$\u2212')+Math.abs(t.pnl).toFixed(2)+'</td>'
      +'<td style="text-align:right;color:'+pc+'">'+(t.pp>=0?'+':'')+t.pp.toFixed(1)+'%</td>'
      +'<td style="text-align:right">'+rm+'</td>'
      +'<td style="font-size:10px;color:#9A9AB0">'+t.setup+'</td>'
      +'<td style="font-size:11px">'+stars+'</td>'
      +'<td>'+(t.note?'<span title="'+t.note.substring(0,50)+'">&#128221;</span>':'<span style="color:#3a3a5e">&#183;</span>')+'</td>'
      +'<td style="text-align:center"><span onclick="event.stopPropagation();jOpenDrawer(t)" title="View details" style="cursor:pointer;color:#2979FF;font-size:12px;opacity:0.6" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=0.6">&#9654;</span></td>';
    tr.onmouseover=function(){{this.style.background='#1a1a35';}};
    tr.onmouseout =function(){{this.style.background='';}};
    tr.onclick=function(){{jOpenDrawer(t);}};
    TB.appendChild(tr);
  }});
  if(jFiltered.length>200){{
    var tr=document.createElement('tr');
    tr.innerHTML='<td colspan="14" style="text-align:center;color:#9A9AB0;font-size:11px;padding:8px">Showing 200 of '+jFiltered.length+'. Use filters to narrow.</td>';
    TB.appendChild(tr);
  }}
}}
function jSummary(){{
  var p=jFiltered.reduce(function(s,t){{return s+t.pnl;}},0);
  var w=jFiltered.filter(function(t){{return t.pnl>0;}}).length;
  var wr=jFiltered.length?Math.round(w/jFiltered.length*100):0;
  document.getElementById('jfilt-summary').textContent=
    jFiltered.length+' trades | P&L: $'+(p>=0?'+':'')+p.toFixed(2)+' | Win: '+wr+'%';
}}
function jOpenDrawer(t){{
  document.getElementById('jdrawer').style.right='0';
  document.getElementById('jd-title').textContent=t.sym+' \u2014 '+t.cd+(t.ot?' '+t.ot:'');
  var rmStr=t.rm!=null?((t.rm>=0?'+':'')+t.rm.toFixed(2)+'R'):'No stop set';
  var stars='';
  for(var i=1;i<=5;i++){{
    stars+='<span onclick="jRateEl(this)" data-nk="'+t.nk+'" data-i="'+i+'" style="cursor:pointer;font-size:20px;color:'+(i<=t.rat?'#F4B400':'#3a3a5e')+'">&#9733;</span>';
  }}
  var tagChips=TAG_OPTS.filter(function(x){{return x;}}).map(function(tag){{
    var on=(t.tags||[]).indexOf(tag)>=0;
    return '<span onclick="jToggleEl(this)" data-nk="'+t.nk+'" data-tag="'+tag+'" '
      +'style="cursor:pointer;display:inline-block;margin:2px;padding:2px 8px;border-radius:12px;font-size:10px;border:1px solid #2979FF;'
      +'background:'+(on?'#2979FF':'#1a1a35')+';color:'+(on?'#fff':'#9A9AB0')+'">'+tag+'</span>';
  }}).join('');
  document.getElementById('jd-body').innerHTML=
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:5px;font-size:11px;margin-bottom:10px">'
    +'<span class="nt">Open: <b style="color:#e0e0f0">'+t.od+(t.ot?' '+t.ot:'')+'</b></span>'
    +'<span class="nt">Close: <b style="color:#e0e0f0">'+t.cd+(t.ct?' '+t.ct:'')+'</b></span>'
    +'<span class="nt">Shares: <b style="color:#e0e0f0">'+t.sh+'</b></span>'
    +'<span class="nt">Hold: <b style="color:#e0e0f0">'+t.hd+'d</b></span>'
    +'<span class="nt">Buy: <b style="color:#e0e0f0">$'+t.bp.toFixed(4)+'</b></span>'
    +'<span class="nt">Sell: <b style="color:#e0e0f0">$'+t.sp.toFixed(4)+'</b></span>'
    +'<span class="nt">P&amp;L: <b style="color:'+(t.pnl>=0?'#0F9D58':'#DB4437')+'">'+(t.pnl>=0?'+':'')+t.pnl.toFixed(2)+'</b></span>'
    +'<span class="nt">R: <b style="color:'+(t.rm&&t.rm>=0?'#0F9D58':t.rm&&t.rm<0?'#DB4437':'#9A9AB0')+'">'+rmStr+'</b></span>'
    +'<span class="nt" style="font-size:10px;color:#9A9AB0;grid-column:1/-1">'+t.acct+'</span>'
    +'</div>'
    +'<div style="margin:8px 0"><div style="font-size:10px;color:#9A9AB0;margin-bottom:3px">Setup</div>'
    +'<select id="jd-setup" data-nk="'+t.nk+'" onchange="jSaveField(this.dataset.nk,&quot;setup&quot;,this.value)" style="width:100%;background:#0d0d1a;border:1px solid #3a3a5e;color:#e0e0f0;padding:5px;border-radius:4px;font-size:11px">'
    +SETUP_OPTS.map(function(o){{return '<option'+(t.setup===o?' selected':'')+'>'+o+'</option>';}}).join('')
    +'</select></div>'
    +'<div style="margin:8px 0"><div style="font-size:10px;color:#9A9AB0;margin-bottom:3px">Execution</div>'
    +'<select id="jd-exec" data-nk="'+t.nk+'" onchange="jSaveField(this.dataset.nk,&quot;execution&quot;,this.value)" style="width:100%;background:#0d0d1a;border:1px solid #3a3a5e;color:#e0e0f0;padding:5px;border-radius:4px;font-size:11px">'
    +EXEC_OPTS.map(function(o){{return '<option'+(t.exec===o?' selected':'')+'>'+o+'</option>';}}).join('')
    +'</select></div>'
    +'<div style="margin:8px 0"><div style="font-size:10px;color:#9A9AB0;margin-bottom:4px">Rating</div><div id="jd-stars">'+stars+'</div></div>'
    +'<div style="margin:8px 0"><div style="font-size:10px;color:#9A9AB0;margin-bottom:4px">Tags</div><div>'+tagChips+'</div></div>'
    +'<div style="margin:8px 0"><div style="font-size:10px;color:#9A9AB0;margin-bottom:4px">Notes</div>'
    +'<textarea id="jd-note" rows="5" style="width:100%;background:#0d0d1a;border:1px solid #3a3a5e;color:#e0e0f0;padding:6px;border-radius:4px;font-size:11px;resize:vertical">'+t.note+'</textarea>'
    +'<button data-nk="'+t.nk+'" data-sym="'+t.sym+'" data-cd="'+t.cd+'" onclick="jSaveNote(this.dataset.nk,this.dataset.sym,this.dataset.cd)" style="margin-top:6px;background:#0F9D58;color:#fff;border:none;padding:6px 16px;border-radius:4px;cursor:pointer;font-size:11px">&#128190; Save</button></div>'
    +'<div style="margin-top:12px;display:flex;gap:10px">'
    +'<a href="https://finance.yahoo.com/quote/'+t.sym+'" target="_blank" style="color:#7BB3FF;font-size:11px">&#128200; Yahoo</a>'
    +'<a href="https://finviz.com/quote.ashx?t='+t.sym+'" target="_blank" style="color:#7BB3FF;font-size:11px">&#128202; Finviz</a>'
    +'</div>';
}}
function jSaveNote(nk,sym,date){{
  var note=document.getElementById('jd-note').value;
  var setup=document.getElementById('jd-setup').value;
  var exec=document.getElementById('jd-exec').value;
  fetch('http://localhost:7778/api/note',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{action:'save',key:nk,note:note,setup:setup,execution:exec}})}})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    if(d.ok){{var t=JT_ALL.find(function(x){{return x.nk===nk;}});if(t){{t.note=note;t.setup=setup;t.exec=exec;}}alert('Saved!');}}
  }}).catch(function(){{alert('Start run_dashboard.bat for live saves');}});
}}
function jSaveField(nk,field,val){{
  fetch('http://localhost:7778/api/note',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{action:'save_field',key:nk,field:field,value:val}})}}).catch(function(){{}});
  var t=JT_ALL.find(function(x){{return x.nk===nk;}});
  if(t)t[field==='execution'?'exec':field]=val;
}}
function jRateEl(el){{jRate(el.dataset.nk,parseInt(el.dataset.i));}}
function jRate(nk,r){{
  jSaveField(nk,'rating',r);
  var t=JT_ALL.find(function(x){{return x.nk===nk;}});if(t)t.rat=r;
  for(var i=1;i<=5;i++)s+='<span onclick="jRateEl(this)" data-nk="'+nk+'" data-i="'+i+'" style="cursor:pointer;font-size:20px;color:'+(i<=r?'#F4B400':'#3a3a5e')+'">&#9733;</span>';
  document.getElementById('jd-stars').innerHTML=s;
}}
function jToggleEl(el){{jToggleTag(el.dataset.nk,el,el.dataset.tag);}}
function jToggleTag(nk,el,tag){{
  var t=JT_ALL.find(function(x){{return x.nk===nk;}});if(!t)return;
  var idx=(t.tags||[]).indexOf(tag);
  if(idx>=0)t.tags.splice(idx,1);else{{if(!t.tags)t.tags=[];t.tags.push(tag);}}
  el.style.background=idx<0?'#2979FF':'#1a1a35';el.style.color=idx<0?'#fff':'#9A9AB0';
  jSaveField(nk,'tags',t.tags);
}}
function jExportCSV(){{
  var rows=[['Date','Open Time','Symbol','Account','Type','Shares','Buy','Sell','Hold','PnL','PnL%','R','Setup','Execution','Tags','Rating','Notes']];
  jFiltered.forEach(function(t){{
    rows.push([t.cd,t.ot,t.sym,t.acct,t.tt,t.sh,t.bp,t.sp,t.hd,t.pnl,t.pp,
      t.rm!=null?t.rm:'',t.setup,t.exec,(t.tags||[]).join('|'),t.rat,t.note]);
  }});
  var csv=rows.map(function(r){{
    return r.map(function(v){{return '"'+(v||'').toString().replace(/"/g,'""')+'"';}}).join(',');
  }}).join(String.fromCharCode(10));
  var a=document.createElement('a');
  a.href='data:text/csv;charset=utf-8,'+encodeURIComponent(csv);
  a.download='trade_journal_'+new Date().toISOString().split('T')[0]+'.csv';
  a.click();
}}
jRender();jSummary();
</script>
"""
    + _build_behavioral_section(behavioral or {})


def _svg_equity(vals, dates=None, w=380, h=120):
    if len(vals) < 2: return "<p style='color:#9A9AB0;font-size:11px'>Accumulating...</p>"
    mn,mx=min(vals),max(vals); rng=mx-mn or 1; pad=28
    px = lambda v: pad+(v-mn)/rng*(w-pad*2)
    py = lambda v: h-pad-(v-mn)/rng*(h-pad*2)
    col = "#0F9D58" if vals[-1]>=0 else "#DB4437"
    pts=" ".join(f"{px(v):.1f},{py(v):.1f}" for v in vals)
    fill=f"{px(vals[0]):.1f},{h-pad} {pts} {px(vals[-1]):.1f},{h-pad}"
    zero=""
    if mn<0<mx:
        y0=py(0)
        zero=f"<line x1='{pad}' y1='{y0:.1f}' x2='{w-pad}' y2='{y0:.1f}' stroke='#3a3a5e' stroke-dasharray='3,2'/>"
    xlbls=""
    if dates:
        step=max(1,len(dates)//4)
        for i in range(0,len(dates),step):
            x=px(vals[i]); lbl=dates[i][5:]
            xlbls+=f"<text x='{x:.1f}' y='{h-2}' fill='#9A9AB0' font-size='7' text-anchor='middle'>{_e(lbl)}</text>"
    circles2 = "".join(
        f"<circle cx='{px(v):.1f}' cy='{py(v):.1f}' r='6' fill='transparent'"
        f" data-val='{v:.2f}' data-date='{(dates[i][5:] if dates and i<len(dates) else '')}'/>"
        for i,v in enumerate(vals))
    return (f"<svg width='{w}' height='{h}' style='display:block'>"
            f"<polygon points='{fill}' fill='{col}22'/>"
            f"<polyline points='{pts}' fill='none' stroke='{col}' stroke-width='2'/>"
            f"{zero}{xlbls}{circles2}"
            f"<text x='4' y='12' fill='#9A9AB0' font-size='7'>${mx:,.0f}</text>"
            f"<text x='4' y='{h-4}' fill='#9A9AB0' font-size='7'>${mn:,.0f}</text>"
            f"</svg>")


def _build_behavioral_section(behavioral: Dict) -> str:
    """Behavioral analytics section appended to trade journal."""
    if not behavioral or not behavioral.get("has_data"):
        return ""

    dow    = behavioral.get("day_of_week", [])
    hours  = behavioral.get("hour_of_day", [])
    setups = behavioral.get("by_setup", [])
    execs  = behavioral.get("by_execution", [])
    best_day    = behavioral.get("best_day") or {}
    worst_day   = behavioral.get("worst_day") or {}
    best_hour   = behavioral.get("best_hour") or {}
    worst_hour  = behavioral.get("worst_hour") or {}
    revenge     = behavioral.get("revenge_signal", False)
    improving   = behavioral.get("improving", False)
    post_loss   = behavioral.get("post_loss_wr")
    rolling     = behavioral.get("rolling_periods", [])
    n           = behavioral.get("sample_size", 0)

    # Day rows
    dow_rows = "".join(
        f"<tr><td style='color:#e0e0f0'>{_e(d['day'])}</td>"
        f"<td style='text-align:right;color:#9A9AB0'>{d['count']}</td>"
        f"<td class='{_cc(d["avg_pnl"])}' style='text-align:right;font-weight:700'>${d['avg_pnl']:+,.2f}</td>"
        f"<td style='text-align:right;color:{'#0F9D58' if d["win_rate"]>=50 else '#DB4437'}'>{d['win_rate']:.0f}%</td>"
        f"<td class='{_cc(d["total_pnl"])}' style='text-align:right'>${d['total_pnl']:+,.0f}</td></tr>"
        for d in dow
    )
    hour_rows = "".join(
        f"<tr><td style='color:#e0e0f0'>{_e(d['label'])}</td>"
        f"<td style='text-align:right;color:#9A9AB0'>{d['count']}</td>"
        f"<td class='{_cc(d["avg_pnl"])}' style='text-align:right;font-weight:700'>${d['avg_pnl']:+,.2f}</td>"
        f"<td style='text-align:right;color:{'#0F9D58' if d["win_rate"]>=50 else '#DB4437'}'>{d['win_rate']:.0f}%</td>"
        f"</tr>"
        for d in hours
    )
    setup_rows = "".join(
        f"<tr><td style='color:#e0e0f0'>{_e(d['setup'])}</td>"
        f"<td style='text-align:right;color:#9A9AB0'>{d['count']}</td>"
        f"<td class='{_cc(d["avg_pnl"])}' style='text-align:right;font-weight:700'>${d['avg_pnl']:+,.2f}</td>"
        f"<td style='text-align:right;color:{'#0F9D58' if d["win_rate"]>=50 else '#DB4437'}'>{d['win_rate']:.0f}%</td>"
        f"</tr>"
        for d in setups[:8]
    )

    revenge_html = ""
    if revenge:
        revenge_html = (f"<div style='background:#2a0000;border:1px solid #DB4437;"
                        f"border-radius:8px;padding:10px;margin-bottom:10px'>"
                        f"<b style='color:#DB4437'>⚠️ Revenge Trading Pattern Detected</b><br>"
                        f"<span style='font-size:11px;color:#9A9AB0'>"
                        f"Win rate after a losing trade: {post_loss:.0f}% "
                        f"(vs overall average). Consider taking a break after losses.</span></div>")

    trend_html = ""
    if len(rolling) >= 2:
        direction = "📈 Improving" if improving else "📉 Declining"
        col = "#0F9D58" if improving else "#DB4437"
        period_strs = " → ".join(f"{p['win_rate']:.0f}% ({p['label']})" for p in reversed(rolling))
        trend_html = (f"<div style='background:#0d1a0d;border:1px solid #0F9D58;"
                      f"border-radius:8px;padding:10px;margin-bottom:10px'>"
                      f"<b style='color:{col}'>{direction}</b>"
                      f"<span style='font-size:11px;color:#9A9AB0;margin-left:8px'>"
                      f"Rolling win rate: {period_strs}</span></div>")

    return f"""
<div class='section-title' style='margin-top:24px'>🧠 Behavioral Analytics
  <span style='font-size:10px;color:#9A9AB0;font-weight:400;margin-left:8px'>
    {n} trades analyzed · numerical data only
  </span>
</div>

{revenge_html}{trend_html}

<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:12px'>
  <div>
    <div style='font-size:11px;color:#9A9AB0;margin-bottom:6px'>
      📅 Best: <b style='color:#0F9D58'>{_e(best_day.get("day","?"))}</b>
      (${best_day.get("avg_pnl",0):+,.0f} avg)
      &nbsp;Worst: <b style='color:#DB4437'>{_e(worst_day.get("day","?"))}</b>
    </div>
    <table>
      <thead><tr style='font-size:10px;color:#9A9AB0'>
        <th>Day</th><th style='text-align:right'>#</th>
        <th style='text-align:right'>Avg P&amp;L</th>
        <th style='text-align:right'>Win%</th>
        <th style='text-align:right'>Total</th>
      </tr></thead>
      <tbody style='font-size:11px'>{dow_rows}</tbody>
    </table>
  </div>
  <div>
    <div style='font-size:11px;color:#9A9AB0;margin-bottom:6px'>
      ⏰ Best: <b style='color:#0F9D58'>{_e(best_hour.get("label","?"))}</b>
      &nbsp;Worst: <b style='color:#DB4437'>{_e(worst_hour.get("label","?"))}</b>
    </div>
    <table>
      <thead><tr style='font-size:10px;color:#9A9AB0'>
        <th>Hour</th><th style='text-align:right'>#</th>
        <th style='text-align:right'>Avg P&amp;L</th>
        <th style='text-align:right'>Win%</th>
      </tr></thead>
      <tbody style='font-size:11px'>{hour_rows or "<tr><td colspan='4' class='nt'>No timestamp data</td></tr>"}</tbody>
    </table>
  </div>
  <div>
    <div style='font-size:11px;color:#9A9AB0;margin-bottom:6px'>🎯 By Setup</div>
    <table>
      <thead><tr style='font-size:10px;color:#9A9AB0'>
        <th>Setup</th><th style='text-align:right'>#</th>
        <th style='text-align:right'>Avg P&amp;L</th>
        <th style='text-align:right'>Win%</th>
      </tr></thead>
      <tbody style='font-size:11px'>{setup_rows or "<tr><td colspan='4' class='nt'>Tag trades to see setup analytics</td></tr>"}</tbody>
    </table>
  </div>
</div>"""
