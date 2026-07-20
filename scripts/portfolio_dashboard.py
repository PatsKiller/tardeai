"""portfolio_dashboard.py — Trade AI v12 Portfolio Intelligence
Generates 7-tab standalone HTML dashboard + integrates into Trade AI dashboard.
"""
from __future__ import annotations

import json
import html
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _e(s: Any) -> str:
    return html.escape(str(s)) if s is not None else ""

def _fmt_usd(v: Optional[float]) -> str:
    if v is None: return "—"
    return f"{'−' if v < 0 else ''}${abs(v):,.2f}"

def _fmt_pct(v: Optional[float]) -> str:
    if v is None: return "—"
    return f"{v:+.2f}%" if v else "0.00%"

def _color_class(v: Optional[float]) -> str:
    if v is None: return "nt"
    return "up" if v > 0 else ("dn" if v < 0 else "nt")

def _severity_color(s: str) -> str:
    return {"CRITICAL": "#DB4437", "HIGH": "#FF9800",
            "WARNING": "#F4B400", "INFO": "#0F9D58"}.get(s, "#9A9AB0")

def _severity_emoji(s: str) -> str:
    return {"CRITICAL": "🚨", "HIGH": "⚠️", "WARNING": "⚡", "INFO": "ℹ️"}.get(s, "•")


CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d0d1a; color: #e0e0f0; font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }
.header { background: linear-gradient(135deg, #1a1a35 0%, #0d1a2e 100%);
          padding: 12px 20px; border-bottom: 2px solid #2a2a5e; display: flex;
          align-items: center; justify-content: space-between; }
.header-title { font-size: 20px; font-weight: 800; color: #7BB3FF; letter-spacing: 1px; }
.header-sub { font-size: 11px; color: #9A9AB0; margin-top: 2px; }
.nav { display: flex; background: #111128; border-bottom: 1px solid #2a2a4e;
       padding: 0 20px; gap: 4px; overflow-x: auto; }
.tab { padding: 10px 18px; cursor: pointer; font-size: 12px; font-weight: 600;
       color: #9A9AB0; border-bottom: 3px solid transparent; white-space: nowrap; }
.tab.active { color: #7BB3FF; border-bottom-color: #7BB3FF; }
.tab:hover { color: #e0e0f0; }
.content { padding: 16px 20px; min-height: 80vh; }
.section { display: none; }
.section.active { display: block; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
.card { background: #1a1a35; border: 1px solid #2a2a5e; border-radius: 10px;
        padding: 14px 18px; min-width: 160px; flex: 1; }
.card-label { font-size: 10px; color: #9A9AB0; font-weight: 700; text-transform: uppercase; margin-bottom: 4px; }
.card-value { font-size: 22px; font-weight: 800; color: #e0e0f0; }
.card-sub { font-size: 11px; color: #9A9AB0; margin-top: 3px; }
.up { color: #0F9D58; } .dn { color: #DB4437; } .nt { color: #9A9AB0; }
table { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
th { background: #1a1a35; color: #9A9AB0; font-size: 10px; font-weight: 700;
     text-transform: uppercase; padding: 8px 10px; text-align: left; position: sticky; top: 0; }
td { padding: 7px 10px; border-bottom: 1px solid #1a1a2e; font-size: 12px; }
tr:hover td { background: #1e1e38; }
.flag-row { display: flex; gap: 10px; padding: 8px 12px; margin-bottom: 6px;
            background: #1a1a35; border-radius: 8px; align-items: flex-start; }
.flag-icon { font-size: 16px; flex-shrink: 0; margin-top: 2px; }
.flag-body { flex: 1; }
.flag-msg { font-size: 12px; color: #e0e0f0; }
.flag-action { font-size: 11px; color: #9A9AB0; margin-top: 3px; }
.sector-bar { display: flex; height: 28px; border-radius: 6px; overflow: hidden; margin: 8px 0 16px; }
.sector-seg { display: flex; align-items: center; justify-content: center;
              font-size: 10px; font-weight: 700; color: #fff; cursor: default; }
.account-card { background: #1a1a35; border: 1px solid #2a2a5e; border-radius: 10px;
                padding: 14px 18px; margin-bottom: 12px; }
.account-card h3 { font-size: 13px; font-weight: 800; color: #7BB3FF; margin-bottom: 10px; }
.rebal-buy { color: #0F9D58; font-weight: 700; }
.rebal-sell { color: #DB4437; font-weight: 700; }
.rebal-hold { color: #9A9AB0; }
.section-title { font-size: 14px; font-weight: 800; color: #7BB3FF;
                 margin-bottom: 12px; padding-bottom: 6px; border-bottom: 1px solid #2a2a5e; }
.badge { display: inline-block; padding: 2px 7px; border-radius: 4px;
         font-size: 10px; font-weight: 700; }
.badge-crit { background: #DB4437; color: #fff; }
.badge-high { background: #FF9800; color: #000; }
.badge-warn { background: #F4B400; color: #000; }
.badge-info { background: #0F9D58; color: #fff; }
"""

TABS = [
    ("overview",    "📊 Overview"),
    ("accounts",    "🏦 Accounts"),
    ("holdings",    "📋 Holdings"),
    ("performance", "📈 Performance"),
    ("journal",     "📓 Trade Journal"),
    ("risk_mgmt",   "🛡️ Risk Manager"),
    ("tax",         "🧾 Tax & Lots"),
    ("rebalance",   "⚖️ Rebalancing"),
    ("technical",   "📐 Technical"),
    ("retirement",  "🎯 Retirement"),
    ("trade_ai",    "🎯 Trade AI"),
    ("ai_analysis", "🤖 AI Analyst"),
    ("periods",     "📅 Period Returns"),
    ("config",      "⚙️ Config"),
    ("dividends",   "💰 Dividends"),
    ("attribution", "📊 Attribution"),
    ("correlation", "🔗 Correlation"),
    ("watchlist",   "👁️ Watchlist"),
]


def _build_trade_journal(journal: Dict, behavioral: Dict = None) -> str:
    """Trade Journal v2 — full featured with filters, sort, calendar, charts, notes."""
    try:
        import sys, os
        # Import from same scripts directory
        _scripts = str(Path(__file__).parent)
        if _scripts not in sys.path:
            sys.path.insert(0, _scripts)
        from journal_tab import build_journal_tab
        return build_journal_tab(journal or {})
    except Exception as e:
        return f"<div class='section-title'>📓 Trade Journal</div><p class='nt'>Error loading journal: {e}</p>"



def _build_stress_section(stress: Dict) -> str:
    """Stress test scenarios section for Risk Manager tab."""
    if not stress or not stress.get("has_data"):
        return ""
    scenarios = stress.get("scenarios", {})
    total_val = stress.get("portfolio_value", 0)
    scenario_order = ["2022_rate_shock","2020_covid","visa_doj","defense_reversal"]
    cards_html = ""
    for sid in scenario_order:
        s = scenarios.get(sid)
        if not s: continue
        loss = s.get("total_loss", 0)
        loss_pct = s.get("loss_pct", 0)
        after = s.get("total_value_after", 0)
        saves = s.get("stops_would_save", 0)
        col = "#DB4437" if loss_pct < -20 else "#F4B400"
        cards_html += f"""<div class='card' style='border-top:3px solid {col}'>
          <div class='card-label'>{_e(s.get("name",""))}</div>
          <div class='card-value dn'>{loss_pct:.1f}%</div>
          <div class='card-sub nt'>${loss:,.0f} loss → ${after:,.0f}</div>
          <div style='font-size:10px;color:#0F9D58;margin-top:2px'>Stops save: ${saves:,.0f}</div>
        </div>"""
    worst = stress.get("worst_case_scenario","")
    worst_loss = stress.get("worst_case_loss",0)
    return f"""
<div class='section-title' style='margin-top:24px'>💥 Stress Test Scenarios</div>
<div style='font-size:11px;color:#9A9AB0;margin-bottom:8px'>
  Worst case: <b style='color:#DB4437'>{_e(worst)}</b> — 
  portfolio drops ${worst_loss:,.0f}. 
  Stops in place would partially protect. Set stops in the table above ↑
</div>
<div class='cards' style='margin-bottom:12px'>{cards_html}</div>
<div style='overflow-x:auto'>
<table>
  <thead><tr style='font-size:10px;color:#9A9AB0'>
    <th>Scenario</th><th>Description</th>
    <th style='text-align:right'>Loss $</th>
    <th style='text-align:right'>Loss %</th>
    <th style='text-align:right'>Portfolio After</th>
    <th style='text-align:right'>Stops Save</th>
  </tr></thead>
  <tbody style='font-size:11px'>{"".join(
    f"<tr><td><b style='color:#e0e0f0'>{_e(s.get("name",""))}</b></td>"
    f"<td style='font-size:10px;color:#9A9AB0;max-width:250px'>{_e(s.get("description","")[:80])}</td>"
    f"<td style='text-align:right;color:#DB4437'>${s.get("total_loss",0):,.0f}</td>"
    f"<td style='text-align:right;color:#DB4437'>{s.get("loss_pct",0):.1f}%</td>"
    f"<td style='text-align:right;color:#9A9AB0'>${s.get("total_value_after",0):,.0f}</td>"
    f"<td style='text-align:right;color:#0F9D58'>${s.get("stops_would_save",0):,.0f}</td>"
    f"</tr>"
    for sid in scenario_order for s in [scenarios.get(sid,{})] if s
  )}</tbody>
</table></div>"""

def _build_options_section(options: Dict) -> str:
    """Build covered call opportunities section for Risk Manager tab."""
    if not options or not options.get("has_data") or not options.get("opportunities"):
        return """<div class='section-title' style='margin-top:20px'>📈 Covered Call Intelligence</div>
    <div style='background:#1a1a35;border:1px solid #2a2a5e;border-radius:8px;padding:14px'>
      <span class='nt'>Run monthly pipeline to populate covered call analysis (MODEL ESTIMATE — priced from realized volatility, never a live chain)</span>
    </div>"""

    opps = options.get("opportunities", [])
    total_monthly = options.get("total_monthly_income", 0)
    total_annual  = options.get("total_annual_income", 0)
    v_strat = options.get("v_strategy") or {}

    # Provenance banner — these premiums are MODELLED from realized volatility,
    # not quoted from a live chain. Rendering the dollar figures without this
    # reads as tradeable income (2026-07-20 audit).
    _label = options.get("estimate_label") or "MODEL ESTIMATE — NO LIVE CHAIN"
    _disc = options.get("disclaimer") or ""
    estimate_banner = (
        "<div style='background:#2a1f0d;border:1px solid #b8860b;border-radius:8px;"
        "padding:10px;margin-bottom:12px'>"
        f"<b style='color:#e6b800'>&#9888; {_label}</b>"
        f"<div style='color:#c9b98a;font-size:12px;margin-top:4px'>{_disc}</div></div>"
    )

    # V strategy callout
    v_html = ""
    if v_strat:
        v_col = "#DB4437" if v_strat.get("blackout") else "#0F9D58"
        v_label = "⚠️ EARNINGS BLACKOUT" if v_strat.get("blackout") else "✅ READY TO WRITE"
        v_html = f"""<div style='background:#0d1a0d;border:1px solid #0F9D58;border-radius:8px;
                    padding:14px;margin-bottom:14px'>
          <div style='font-size:12px;font-weight:700;color:#0F9D58;margin-bottom:6px'>
            🎯 V Covered Call Strategy — <span style='color:{v_col}'>{v_label}</span>
          </div>
          <div style='font-size:12px;color:#e0e0f0;line-height:1.6'>
            {_e(v_strat.get("summary",""))}
          </div>
          <div style='margin-top:10px;font-size:11px;color:#9A9AB0'>
            Monthly income from V calls → fund Roth conversion ($25K/yr target at ~$2,083/mo needed)
          </div>
        </div>"""

    # Opportunities table
    rows = ""
    for o in opps[:15]:
        sym = o.get("symbol","")
        bl  = o.get("in_blackout", False)
        rec_col = "#DB4437" if bl else "#0F9D58"
        rows += (f"<tr>"
                 f"<td><b style='color:#e0e0f0'>{_e(sym)}</b></td>"
                 f"<td style='text-align:right;color:#9A9AB0'>{o.get('shares',0):.0f}</td>"
                 f"<td style='text-align:right;color:#9A9AB0'>${o.get('price',0):.2f}</td>"
                 f"<td style='text-align:right;color:#9A9AB0'>${o.get('strike',0):.2f}</td>"
                 f"<td style='text-align:right;color:#9A9AB0'>{o.get('otm_pct',0):.1f}%</td>"
                 f"<td style='text-align:right;color:#9A9AB0'>{o.get('dte',30)}d</td>"
                 f"<td style='text-align:right;color:#9A9AB0'>${o.get('premium_per_share',0):.2f}</td>"
                 f"<td style='text-align:right;font-weight:700;color:#0F9D58'>${o.get('monthly_income',0):,.0f}</td>"
                 f"<td style='text-align:right;color:#9A9AB0'>{o.get('annualized_yield',0):.1f}%</td>"
                 f"<td style='text-align:right;color:#9A9AB0'>${o.get('market_value',0):,.0f}</td>"
                 f"<td style='color:{rec_col};font-size:10px'>{_e(o.get('recommendation',''))}</td>"
                 f"</tr>")

    return f"""<div class='section-title' style='margin-top:24px'>📈 Covered Call Intelligence</div>
    {estimate_banner}
    <div class='cards' style='margin-bottom:10px'>
      <div class='card' style='border-top:3px solid #0F9D58'>
        <div class='card-label'>Est. Monthly Income</div>
        <div class='card-value up'>${total_monthly:,.0f}</div>
        <div class='card-sub nt'>If all calls written today</div>
      </div>
      <div class='card'>
        <div class='card-label'>Annualized</div>
        <div class='card-value up'>${total_annual:,.0f}</div>
        <div class='card-sub nt'>vs ${options.get("eligible_positions",0)*0:,.0f} dividends alone</div>
      </div>
      <div class='card'>
        <div class='card-label'>Eligible Positions</div>
        <div class='card-value nt'>{len(opps)}</div>
        <div class='card-sub nt'>{options.get("blackout_count",0)} in earnings blackout</div>
      </div>
      <div class='card' style='border-top:3px solid #F4B400'>
        <div class='card-label'>Roth Conversion Fuel</div>
        <div class='card-value up'>${total_monthly*12:,.0f}/yr</div>
        <div class='card-sub nt'>Target: $25K/yr conversion</div>
      </div>
    </div>

    {v_html}

    <table>
      <thead><tr style='font-size:10px;color:#9A9AB0'>
        <th>Symbol</th><th style='text-align:right'>Shares</th>
        <th style='text-align:right'>Price</th><th style='text-align:right'>Strike</th>
        <th style='text-align:right'>OTM%</th><th style='text-align:right'>DTE</th>
        <th style='text-align:right'>Prem/sh</th>
        <th style='text-align:right'>Monthly $</th>
        <th style='text-align:right'>Ann.Yield</th>
        <th style='text-align:right'>Pos.Value</th>
        <th>Action</th>
      </tr></thead>
      <tbody style='font-size:12px'>{rows}</tbody>
    </table>"""

def _build_risk_management(risk_mgmt: Dict, options: Dict = None, stress: Dict = None) -> str:
    """Build Risk Management tab — stops, portfolio heat, position sizer."""
    if not risk_mgmt:
        return "<div class='section-title'>🛡️ Risk Manager</div><p class='nt'>Loading...</p>"

    positions   = risk_mgmt.get("positions", [])
    heat        = risk_mgmt.get("portfolio_heat_pct", 0)
    total_risk  = risk_mgmt.get("total_risk_dollars", 0)
    pct_prot    = risk_mgmt.get("pct_protected", 0)
    total_mv    = risk_mgmt.get("total_mv", 0)
    triggered   = risk_mgmt.get("triggered", [])
    danger      = risk_mgmt.get("danger", [])
    stop_count  = risk_mgmt.get("stop_count", 0)
    unprotected = risk_mgmt.get("unprotected", [])

    heat_col = "#DB4437" if heat > 5 else "#F4B400" if heat > 2 else "#0F9D58"

    # ── Alerts banner ──
    alert_html = ""
    for p in triggered:
        alert_html += f"""<div style='background:#DB443722;border-left:4px solid #DB4437;
            padding:10px 14px;border-radius:4px;margin-bottom:8px'>
          🚨 <b style='color:#DB4437'>STOP TRIGGERED: {_e(p["symbol"])}</b>
          &nbsp;Price ${p["price"]:.2f} crossed stop ${p.get("stop_price",0):.2f}
          &nbsp;— Max loss: ${p.get("max_loss_dollar",0):,.0f}
        </div>"""
    for p in danger:
        alert_html += f"""<div style='background:#F4B40022;border-left:4px solid #F4B400;
            padding:10px 14px;border-radius:4px;margin-bottom:8px'>
          ⚠️ <b style='color:#F4B400'>STOP NEAR: {_e(p["symbol"])}</b>
          &nbsp;Only {p.get("dist_pct",0):.1f}% above stop
          (${p["price"]:.2f} vs ${p.get("stop_price",0):.2f})
        </div>"""

    # ── Stop rows ──
    STATUS_COL = {"TRIGGERED":"#DB4437","DANGER":"#DB4437",
                  "WARNING":"#F4B400","OK":"#0F9D58","NO STOP":"#9A9AB0"}
    stop_rows = ""
    for p in positions:
        sym    = _e(p.get("symbol",""))
        status = p.get("status","")
        col    = STATUS_COL.get(status,"#9A9AB0")
        protected = p.get("protected", False)

        if protected:
            stop_rows += f"""<tr>
              <td><b style='color:#e0e0f0'>{sym}</b></td>
              <td style='font-size:10px;color:#9A9AB0'>{_e(p.get("account",""))[:18]}</td>
              <td style='text-align:right'>{p.get("shares",0):.0f}</td>
              <td style='text-align:right'>${p.get("price",0):.2f}</td>
              <td style='text-align:right;color:#F4B400;font-weight:700'>${p.get("stop_price",0):.2f}</td>
              <td style='text-align:right;color:#9A9AB0'>{p.get("dist_pct",0):.1f}%</td>
              <td style='text-align:right;color:#DB4437'>${p.get("max_loss_dollar",0):,.0f}</td>
              <td style='text-align:right;color:#9A9AB0'>{p.get("risk_pct_port",0):.2f}%</td>
              <td><span style='color:{col};font-size:10px;font-weight:700'>{status}</span></td>
              <td style='font-size:10px;color:#9A9AB0'>{_e(p.get("notes","")[:30])}</td>
            </tr>"""
        else:
            stop_rows += f"""<tr style='opacity:0.6'>
              <td><b style='color:#e0e0f0'>{sym}</b></td>
              <td style='font-size:10px;color:#9A9AB0'>{_e(p.get("account",""))[:18]}</td>
              <td style='text-align:right;color:#9A9AB0'>{p.get("shares",0):.0f}</td>
              <td style='text-align:right;color:#9A9AB0'>${p.get("price",0):.2f}</td>
              <td style='text-align:right;color:#9A9AB0'>—</td>
              <td style='text-align:right;color:#9A9AB0'>—</td>
              <td style='text-align:right;color:#DB4437'>${p.get("market_value",0):,.0f} at risk</td>
              <td style='text-align:right;color:#9A9AB0'>{p.get("risk_pct_port",0):.1f}%</td>
              <td><span style='color:#9A9AB0;font-size:10px'>NO STOP</span></td>
              <td></td>
            </tr>"""

    # ── Set stop form (calls proxy) ──
    set_stop_js = """
function setStop() {
  var sym   = document.getElementById('stop-sym').value.toUpperCase().trim();
  var price = parseFloat(document.getElementById('stop-price').value);
  var trail = parseFloat(document.getElementById('stop-trail').value || '0');
  var notes = document.getElementById('stop-notes').value.trim();
  if (!sym || (isNaN(price) && isNaN(trail))) {
    alert('Enter symbol and stop price (or trail %)');
    return;
  }
  fetch('http://localhost:7778/api/stop', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action:'set', symbol:sym, stop:price||0, trail_pct:trail||0, notes:notes})
  })
  .then(r => r.json())
  .then(d => { alert(d.message || 'Stop saved! Refresh after next run.'); })
  .catch(e => { alert('Save stops.json manually or re-run scripts/run_portfolio.bat'); });
}
function removeStop(sym) {
  if (!confirm('Remove stop for ' + sym + '?')) return;
  fetch('http://localhost:7778/api/stop', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action:'remove', symbol:sym})
  })
  .then(r => r.json())
  .then(d => { alert(d.message || 'Stop removed! Refresh after next run.'); })
  .catch(e => { alert('Or run: python scripts/portfolio_stops.py remove ' + sym); });
}
"""

    # ── Position sizer ──
    pos_sizer_html = f"""
    <div class='section-title' style='margin-top:16px'>📐 Position Sizer</div>
    <p class='nt' style='font-size:11px;margin-bottom:10px'>
      Enter entry + stop to calculate max shares keeping risk below your limit.
      Portfolio: ${total_mv:,.0f}
    </p>
    <div style='display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin-bottom:12px'>
      <div><div style='font-size:10px;color:#9A9AB0;margin-bottom:3px'>Max Risk % of Portfolio</div>
        <input id='ps-riskpct' type='number' value='1.0' step='0.25' min='0.25' max='5'
               style='width:80px;background:#0d0d1a;border:1px solid #2a2a5e;color:#e0e0f0;
                      padding:5px 8px;border-radius:4px'></div>
      <div><div style='font-size:10px;color:#9A9AB0;margin-bottom:3px'>Entry Price</div>
        <input id='ps-entry' type='number' placeholder='$0.00' step='0.01'
               style='width:100px;background:#0d0d1a;border:1px solid #2a2a5e;color:#e0e0f0;
                      padding:5px 8px;border-radius:4px'></div>
      <div><div style='font-size:10px;color:#9A9AB0;margin-bottom:3px'>Stop Price</div>
        <input id='ps-stop' type='number' placeholder='$0.00' step='0.01'
               style='width:100px;background:#0d0d1a;border:1px solid #2a2a5e;color:#e0e0f0;
                      padding:5px 8px;border-radius:4px'></div>
      <button onclick='calcPositionSize()'
              style='background:#2979FF;color:#fff;border:none;padding:7px 14px;
                     border-radius:4px;cursor:pointer;font-weight:700'>Calculate</button>
    </div>
    <div id='ps-result' style='font-size:12px;color:#9A9AB0'></div>"""

    pos_sizer_js = f"""
function calcPositionSize() {{
  var riskPct = parseFloat(document.getElementById('ps-riskpct').value) || 1.0;
  var entry   = parseFloat(document.getElementById('ps-entry').value);
  var stop    = parseFloat(document.getElementById('ps-stop').value);
  var portVal = {total_mv};
  if (!entry || !stop || entry <= stop) {{
    document.getElementById('ps-result').innerHTML =
      '<span style="color:#DB4437">⚠️ Entry must be above stop price</span>';
    return;
  }}
  var maxRisk    = portVal * riskPct / 100;
  var riskShare  = entry - stop;
  var maxShares  = Math.floor(maxRisk / riskShare);
  var posValue   = maxShares * entry;
  var posPct     = (posValue / portVal * 100).toFixed(1);
  document.getElementById('ps-result').innerHTML =
    '<div style="background:#0d0d1a;padding:10px 14px;border-radius:6px;border:1px solid #2a2a5e">' +
    '<b style="color:#0F9D58">Max ' + maxShares + ' shares</b> @ $' + entry.toFixed(2) +
    ' = $' + posValue.toLocaleString() + ' (' + posPct + '% of portfolio)<br>' +
    'Risk per share: $' + riskShare.toFixed(2) +
    ' | Max loss: $' + maxRisk.toLocaleString(undefined,{{maximumFractionDigits:0}}) +
    ' (' + riskPct + '% of portfolio)' +
    '</div>';
}}"""

    return f"""
    <script>{set_stop_js}{pos_sizer_js}</script>
    <div class='section-title'>🛡️ Risk Manager — Stop-Loss Tracker</div>
    {alert_html}

    <div class='cards'>
      <div class='card'>
        <div class='card-label'>Portfolio Heat</div>
        <div class='card-value' style='color:{heat_col}'>{heat:.2f}%</div>
        <div class='card-sub nt'>${total_risk:,.0f} at risk if all stops hit</div>
      </div>
      <div class='card'>
        <div class='card-label'>Stops Set</div>
        <div class='card-value nt'>{stop_count}</div>
        <div class='card-sub nt'>{pct_prot:.0f}% of portfolio protected</div>
      </div>
      <div class='card'>
        <div class='card-label'>Unprotected</div>
        <div class='card-value {"dn" if pct_prot < 50 else "nt"}'>{100-pct_prot:.0f}%</div>
        <div class='card-sub nt'>${risk_mgmt.get("total_unprotected_mv",0):,.0f} with no stop</div>
      </div>
      <div class='card'>
        <div class='card-label'>Triggered / Near</div>
        <div class='card-value {"dn" if triggered or danger else "up"}'>
          {len(triggered)} / {len(danger)}</div>
        <div class='card-sub nt'>Triggered / Within 5%</div>
      </div>
    </div>

    <div class='section-title' style='margin-top:12px'>➕ Set / Update Stop</div>
    <div style='display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin-bottom:12px'>
      <div><div style='font-size:10px;color:#9A9AB0;margin-bottom:3px'>Symbol</div>
        <input id='stop-sym' type='text' placeholder='V'
               style='width:80px;background:#0d0d1a;border:1px solid #2a2a5e;color:#e0e0f0;
                      padding:5px 8px;border-radius:4px;text-transform:uppercase'></div>
      <div><div style='font-size:10px;color:#9A9AB0;margin-bottom:3px'>Hard Stop $</div>
        <input id='stop-price' type='number' placeholder='280.00' step='0.01'
               style='width:100px;background:#0d0d1a;border:1px solid #2a2a5e;color:#e0e0f0;
                      padding:5px 8px;border-radius:4px'></div>
      <div><div style='font-size:10px;color:#9A9AB0;margin-bottom:3px'>Trail % (alt)</div>
        <input id='stop-trail' type='number' placeholder='8.0' step='0.5'
               style='width:80px;background:#0d0d1a;border:1px solid #2a2a5e;color:#e0e0f0;
                      padding:5px 8px;border-radius:4px'></div>
      <div><div style='font-size:10px;color:#9A9AB0;margin-bottom:3px'>Notes</div>
        <input id='stop-notes' type='text' placeholder='Below 200d MA'
               style='width:160px;background:#0d0d1a;border:1px solid #2a2a5e;color:#e0e0f0;
                      padding:5px 8px;border-radius:4px'></div>
      <button onclick='setStop()'
              style='background:#0F9D58;color:#fff;border:none;padding:7px 14px;
                     border-radius:4px;cursor:pointer;font-weight:700'>Set Stop</button>
    </div>
    <p style='font-size:10px;color:#9A9AB0;margin-bottom:12px'>
      Or use CLI: <code>python scripts/portfolio_stops.py set V 280.00 "Below 200d MA"</code><br>
      Trailing stop: <code>python scripts/portfolio_stops.py trail KTOS 8.0</code>
    </p>

    <table><thead><tr style='font-size:10px;color:#9A9AB0'>
      <th>Symbol</th><th>Account</th>
      <th style='text-align:right'>Shares</th>
      <th style='text-align:right'>Price</th>
      <th style='text-align:right'>Stop $</th>
      <th style='text-align:right'>Distance</th>
      <th style='text-align:right'>Max Loss</th>
      <th style='text-align:right'>Port Risk%</th>
      <th>Status</th>
      <th>Notes</th>
    </tr></thead>
    <tbody style='font-size:12px'>{stop_rows}</tbody></table>

    {pos_sizer_html}

    {_build_stress_section(stress or {})}\n\n    {_build_options_section(options or {})}"""

def _build_overview(portfolio: Dict, analysis: Dict, rebalancing: Dict, perf_history: Dict = None) -> str:




    totals = portfolio.get("portfolio_totals", {})
    flags = analysis.get("critical_flags", [])
    n_crit = analysis.get("flag_count", {}).get("CRITICAL", 0)
    n_high = analysis.get("flag_count", {}).get("HIGH", 0)
    n_warn = analysis.get("flag_count", {}).get("WARNING", 0)
    divs = analysis.get("dividends", {})
    vitals = analysis.get("vitals", {})
    risk = rebalancing.get("risk", {}) if isinstance(rebalancing, dict) else {}

    total_mv = totals.get("total_value", 0)
    total_gain = totals.get("total_gain", 0)
    total_gain_pct = totals.get("total_gain_pct", 0)
    day_chg = totals.get("day_change", 0)

    cards = f"""
    <div class='cards'>
      <div class='card'>
        <div class='card-label'>Total Portfolio</div>
        <div class='card-value'>{_fmt_usd(total_mv)}</div>
        <div class='card-sub {_color_class(day_chg)}'>{_fmt_usd(day_chg)} today</div>
      </div>
      <div class='card'>
        <div class='card-label'>Total Gain / Loss</div>
        <div class='card-value {_color_class(total_gain)}'>{_fmt_usd(total_gain)}</div>
        <div class='card-sub {_color_class(total_gain_pct)}'>{_fmt_pct(total_gain_pct)} all-time</div>
      </div>
      <div class='card'>
        <div class='card-label'>Annual Dividend Income</div>
        <div class='card-value'>{_fmt_usd(divs.get("total_annual_income"))}</div>
        <div class='card-sub nt'>{_fmt_usd(divs.get("total_monthly_income"))}/month est.</div>
      </div>
      <div class='card'>
        <div class='card-label'>Weighted Beta</div>
        <div class='card-value'>{vitals.get("weighted_beta", "—")}</div>
        <div class='card-sub nt'>vs S&P 500 beta 1.0</div>
      </div>
      <div class='card'>
        <div class='card-label'>Critical Flags</div>
        <div class='card-value {("dn" if n_crit > 0 else "nt")}'>{n_crit + n_high}</div>
        <div class='card-sub nt'>{n_crit} critical · {n_high} high · {n_warn} warnings</div>
      </div>
    </div>"""

    # Sector bar
    sector_pct = analysis.get("sector_pct", {})
    SCOLORS = {
        "Defense": "#1565C0", "Financials": "#2E7D32", "Healthcare": "#7B1FA2",
        "Technology": "#E65100", "US Equity": "#1976D2", "International Equity": "#00695C",
        "Bonds": "#5D4037", "Income/Dividend": "#558B2F", "BDC Income": "#4527A0",
        "Growth ETF": "#F57F17", "ETF/Fund": "#424242", "US Equity Funds": "#1A237E",
        "Cash": "#616161", "Other": "#9E9E9E",
    }
    sector_bar = "<div class='sector-bar'>"
    for sector, pct in sorted(sector_pct.items(), key=lambda x: -x[1])[:12]:
        if pct < 1: continue
        col = SCOLORS.get(sector, "#555")
        sector_bar += f"<div class='sector-seg' style='width:{pct:.1f}%;background:{col}' title='{_e(sector)}: {pct:.1f}%'>"
        if pct > 2:
            sector_bar += f"{pct:.1f}%"
        sector_bar += "</div>"
    sector_bar += "</div>"

    sector_legend = "<div style='display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px'>"
    for sector, pct in sorted(sector_pct.items(), key=lambda x: -x[1])[:12]:
        if pct < 1: continue
        col = SCOLORS.get(sector, "#555")
        sector_legend += f"<span><span style='display:inline-block;width:10px;height:10px;border-radius:2px;background:{col};margin-right:4px'></span><span style='font-size:11px'>{_e(sector)} {pct:.1f}%</span></span>"
    sector_legend += "</div>"

    # Flags
    flags_html = ""
    for f in flags[:8]:
        sev = f.get("severity", "INFO")
        col = _severity_color(sev)
        emoji = _severity_emoji(sev)
        flags_html += f"""
        <div class='flag-row' style='border-left:3px solid {col}'>
          <div class='flag-icon'>{emoji}</div>
          <div class='flag-body'>
            <div class='flag-msg'><b>{_e(f.get("symbol") or "")}</b> {_e(f.get("message",""))}</div>
            <div class='flag-action'>{_e(f.get("action",""))}</div>
          </div>
          <span class='badge badge-{sev.lower()[:4]}'>{_e(sev)}</span>
        </div>"""

    # ── Period Returns summary for Overview ──────────────────────────────────
    ph       = perf_history or {}
    ph_pds   = ph.get("periods", {})
    period_cards_html = ""
    PERIOD_ORDER = ["1D","1W","1M","3M","6M","YTD","1Y"]
    period_card_items = []
    for pk in PERIOD_ORDER:
        pd = ph_pds.get(pk)
        if not pd or pd.get("change_pct") is None:
            continue
        chg     = pd.get("change", 0) or 0
        chg_pct = pd.get("change_pct", 0) or 0
        col     = "#0F9D58" if chg >= 0 else "#DB4437"
        sign_c  = "+" if chg >= 0 else ""
        sign_p  = "+" if chg_pct >= 0 else ""
        src_icon = "📸" if pd.get("source") == "snapshot" else "📅"
        period_card_items.append(
            f"<div style='display:flex;justify-content:space-between;align-items:center;"
            f"padding:6px 10px;border-bottom:1px solid #1a1a2e'>"
            f"<span style='font-weight:700;color:#e0e0f0;min-width:32px'>{pk}</span>"
            f"<span style='color:#9A9AB0;font-size:11px'>{pd.get('start_date','')}</span>"
            f"<span style='font-weight:700;color:{col};min-width:80px;text-align:right'>"
            f"{sign_p}{chg_pct:.2f}%</span>"
            f"<span style='color:{col};font-size:11px;min-width:90px;text-align:right'>"
            f"{sign_c}${abs(chg):,.0f}</span>"
            f"<span style='color:#9A9AB0;font-size:10px;margin-left:4px'>{src_icon}</span>"
            f"</div>"
        )
    if period_card_items:
        period_cards_html = f"""
    <div class='section-title' style='margin-top:16px'>📅 Period Returns</div>
    <div style='background:#1a1a35;border:1px solid #2a2a5e;border-radius:8px;
                overflow:hidden;margin-bottom:4px'>
      {''.join(period_card_items)}
    </div>
    <div style='font-size:10px;color:#9A9AB0;margin-bottom:12px'>
      📸 = daily snapshot &nbsp;|&nbsp; 📅 = repriced from price cache
      &nbsp;|&nbsp; <a href='javascript:showTab("periods",document.querySelector("[onclick*=periods]"))' 
      style='color:#7BB3FF;text-decoration:none'>→ Full Period Returns tab</a>
    </div>"""

    # ── Sector bar label threshold ────────────────────────────────────────────
    # (done inline below — show label for any segment ≥ 2%)

    return f"""
    <div class='section-title'>📊 Portfolio Overview — {_e(portfolio.get("as_of",""))}</div>
    {cards}
    <div class='section-title'>Sector Exposure (with ETF Look-Through)</div>
    {sector_bar}
    {sector_legend}
    {period_cards_html}
    <div class='section-title'>⚠️ Critical Flags</div>
    {flags_html}"""


def _build_holdings(portfolio: Dict, analysis: Dict) -> str:
    holdings = [h for h in portfolio.get("holdings", [])
                if not h.get("is_loan") and (h.get("market_value") or 0) > 0]
    holdings.sort(key=lambda h: -(h.get("market_value") or 0))

    rows = ""
    for h in holdings:
        sym = h.get("symbol", "")
        gl = h.get("gain_loss") or 0
        gl_pct = h.get("gain_loss_pct") or 0
        mv = h.get("market_value") or 0
        cb = h.get("cost_basis") or 0
        pct = h.get("portfolio_pct") or 0
        revoked = "⚠️ REVOKED" if h.get("is_revoked") else ""
        drip = "✅" if h.get("reinvest_div") else ""
        asset_type = h.get("asset_type", "")
        badge = ""
        if h.get("is_etf"): badge = "<span style='font-size:9px;color:#F4B400'> ETF</span>"
        elif h.get("is_fund"): badge = "<span style='font-size:9px;color:#7BB3FF'> FUND</span>"
        elif h.get("is_cash"): badge = "<span style='font-size:9px;color:#9A9AB0'> CASH</span>"

        rows += f"""<tr>
          <td><b>{_e(sym)}</b>{badge} {revoked}</td>
          <td style='font-size:11px;color:#9A9AB0;max-width:160px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis'>{_e(h.get("name",""))}</td>
          <td style='font-size:11px;color:#9A9AB0'>{_e(h.get("account_display",""))}</td>
          <td class='nt'>{_e(h.get("account_type",""))}</td>
          <td class='nt' style='text-align:right'>{_fmt_usd(mv)}</td>
          <td class='nt' style='text-align:right'>{_fmt_usd(cb)}</td>
          <td class='{_color_class(gl)}' style='text-align:right'>{_fmt_usd(gl)}</td>
          <td class='{_color_class(gl_pct)}' style='text-align:right'>{_fmt_pct(gl_pct)}</td>
          <td class='nt' style='text-align:right'>{pct:.1f}%</td>
          <td class='nt' style='text-align:center'>{drip}</td>
        </tr>"""

    return f"""
    <div class='section-title'>All Holdings ({len(holdings)} positions)</div>
    <table>
      <thead><tr>
        <th>Symbol</th><th>Name</th><th>Account</th><th>Type</th>
        <th style='text-align:right'>Market Value</th><th style='text-align:right'>Cost Basis</th>
        <th style='text-align:right'>Gain/Loss $</th><th style='text-align:right'>Gain %</th>
        <th style='text-align:right'>% Portfolio</th><th style='text-align:center'>DRIP</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def _build_rebalancing(rebalancing: Dict, sonnet_model: str = "claude-sonnet-4-6") -> str:
    drift        = rebalancing.get("drift_analysis", {})
    orders       = rebalancing.get("rebalance_orders", [])
    total_to_move= rebalancing.get("total_to_rebalance", 0)
    v_scenario   = rebalancing.get("v_to_schd_scenario", {})
    bond_recs    = rebalancing.get("bond_recommendations", [])
    bond_note    = rebalancing.get("bond_note", "")

    # ── Analyst context for key tickers ──────────────────────────────────────
    ANALYST = {
        "V":    {"rating":"HOLD","target":"$340","note":"DOJ antitrust debit routing probe; strong moat; 32x PE"},
        "FCNTX":{"rating":"HOLD","note":"Active fund 40% tech; AAPL/MSFT/NVDA top 3 = hidden tech concentration"},
        "BND":  {"rating":"BUY", "note":"Core bond ETF; 3.4% yield; 6.2yr duration; 0.03% ER"},
        "SCHD": {"rating":"BUY", "note":"Gold standard dividend ETF; 3.58% yield; quality screen; low vol"},
        "SCHG": {"rating":"BUY", "note":"Best-in-class growth ETF; 0.04% ER; better than QQQ on cost"},
        "VCIT": {"rating":"BUY", "note":"Best bond for IRA; 4.8% yield corporate; beats BND by +1.4%"},
        "VXUS": {"rating":"BUY", "note":"International diversification; 0.07% ER; adds non-US exposure"},
        "CSWC": {"rating":"HOLD","note":"BDC 10.5% yield; strong NAV; monthly dividend; moderate risk"},
        "PFLT": {"rating":"HOLD","note":"BDC 11.2% yield; floating rate loans; NAV watch required"},
        "RKLB": {"rating":"BUY", "note":"Rocket Lab; commercial space leader; high risk/high reward"},
        "ARKQ": {"rating":"HOLD","note":"Autonomous tech ETF; TSLA/robotics heavy; 1.38 beta"},
        "PFE":  {"rating":"SELL","note":"Pipeline struggles post-COVID; dividend at risk; avoid"},
        "SRNE": {"rating":"SELL","note":"BANKRUPT — $0.003/share; IRA tax loss = $0 benefit; remove"},
        "ARKG": {"rating":"SELL","note":"ARK Genomics speculative; -80% from peak; consider exit"},
        "LMT":  {"rating":"BUY", "note":"Lockheed; F-35 backlog; dividend growth; defense must-hold"},
        "NOC":  {"rating":"BUY", "note":"Northrop; B-21 bomber program; pure defense pure play"},
        "AVAV": {"rating":"BUY", "note":"AeroVironment; drone/UAV leader; AI WWIII core holding"},
    }

    # ── ETF look-through AAPL warning ────────────────────────────────────────
    ETF_EXPOSURE = {
        "AAPL": {"est_usd": 93400, "pct": 8.2, "via": "FCNTX (14%) + SCHG (12%) + SP500-D (7%)"},
        "MSFT": {"est_usd": 76200, "pct": 6.7, "via": "FCNTX (11%) + SCHG (11%) + FID-CONTRA-F (12%)"},
        "NVDA": {"est_usd": 62800, "pct": 5.5, "via": "FCNTX (8%) + SCHG (10%) + JPM-LGCG (8%)"},
        "AMZN": {"est_usd": 48100, "pct": 4.2, "via": "FCNTX (9%) + SCHG (8%)"},
        "META": {"est_usd": 32400, "pct": 2.8, "via": "FCNTX (6%) + SCHG (6%)"},
    }

    # ── Section 1: ETF Look-Through Warning ───────────────────────────────────
    etf_html = """
    <div style='background:#1a1a35;border:2px solid #F4B400;border-radius:10px;padding:14px 18px;margin-bottom:16px'>
      <div style='font-size:13px;font-weight:800;color:#F4B400;margin-bottom:10px'>
        ⚠️ HIDDEN CONCENTRATION — What You Actually Own Through ETFs & Funds
      </div>
      <p style='font-size:11px;color:#9A9AB0;margin-bottom:10px'>
        Your brokers show 0 shares of AAPL/MSFT/NVDA — but you own significant exposure
        through FCNTX, SCHG, SP500-D, FID-CONTRA-F, and JPM-LGCG:
      </p>"""
    for sym, d in ETF_EXPOSURE.items():
        bar_w = min(d["pct"] * 8, 100)
        etf_html += f"""
      <div style='margin-bottom:8px'>
        <div style='display:flex;justify-content:space-between;margin-bottom:3px'>
          <span style='font-size:12px;font-weight:700;color:#e0e0f0'>{sym}</span>
          <span style='font-size:12px;color:#F4B400;font-weight:700'>~${d['est_usd']:,.0f} ({d['pct']:.1f}% of portfolio)</span>
        </div>
        <div style='background:#0d0d1a;border-radius:4px;height:8px;margin-bottom:3px'>
          <div style='background:#F4B400;height:8px;border-radius:4px;width:{bar_w:.0f}%'></div>
        </div>
        <div style='font-size:10px;color:#9A9AB0'>Via: {_e(d["via"])}</div>
      </div>"""
    etf_html += """
      <div style='margin-top:10px;padding-top:10px;border-top:1px solid #2a2a5e'>
        <span style='font-size:11px;color:#DB4437;font-weight:700'>⚡ ACTION: </span>
        <span style='font-size:11px;color:#e0e0f0'>Selling FCNTX reduces your hidden AAPL/MSFT/NVDA exposure by ~$45K each.
        This is why the rebalancer recommends selling 2,286 shares of FCNTX in your Rollover IRA.</span>
      </div>
    </div>"""

    # ── Section 2: Execution Playbook ────────────────────────────────────────
    # Group orders by account
    by_account: Dict[str, List] = {}
    for o in orders:
        acct = o.get("account","")
        by_account.setdefault(acct, []).append(o)

    PRIORITY_LABELS = {
        "Schwab Roth IRA":            ("1", "TAX-FREE — Do First", "#0F9D58"),
        "Schwab Rollover IRA":        ("2", "TAX-DEFERRED — Do Second", "#2979FF"),
        "Schwab Individual (Taxable)":("3", "TAXABLE — Mind Cap Gains", "#F4B400"),
        "Fidelity 401k (Omnicom)":    ("4", "CALL FIDELITY — Exchange Funds", "#9A9AB0"),
    }

    playbook_html = f"""
    <div class='section-title' style='display:flex;justify-content:space-between;align-items:center'>
      <span>🎯 Execution Playbook — ${total_to_move:,.0f} Net to Rebalance</span>
      <button class='ai-btn' style='font-size:11px;padding:6px 14px' onclick='runFullRebalanceAI()'>
        🤖 Review Full Plan with Sonnet 4.6
      </button>
    </div>
    <p style='font-size:11px;color:#9A9AB0;margin-bottom:12px'>
      Trade in priority order. IRAs first — zero tax on gains regardless of size.
      Taxable account last — capital gains apply. Click any ticker for research or AI analysis.
    </p>"""

    # IRA Rollover expansion — what's NOT in the IRA that should be
    IRA_EXPANSION = [
        {"ticker":"JEPI",  "name":"JPMorgan Equity Premium Income",    "yield":"7.8%", "type":"Covered Call ETF",
         "note":"S&P500 + covered calls. Lower vol than SPY, 7-8% monthly income. Perfect IRA hold.",
         "allocation":"5-8% of IRA (~$26-42K)", "shares_approx":"~465 shares @ $56"},
        {"ticker":"O",     "name":"Realty Income (Monthly Dividend)",   "yield":"5.7%", "type":"REIT",
         "note":"The dividend stock. 655+ consecutive monthly dividends. S&P 500 component.",
         "allocation":"3-5% of IRA (~$16-26K)", "shares_approx":"~260 shares @ $55"},
        {"ticker":"VCIT",  "name":"Vanguard Intermediate Corporate Bond","yield":"4.8%", "type":"Bond ETF",
         "note":"Better than BND for IRA. Corporate bonds 4.8% yield, tax drag irrelevant in IRA.",
         "allocation":"10-15% of IRA ($53-80K) of the $113K bond target",
         "shares_approx":"~625 shares @ $85"},
        {"ticker":"PFF",   "name":"iShares Preferred Stock ETF",        "yield":"6.2%", "type":"Preferred Stock ETF",
         "note":"Bank preferred stocks. 6.2% yield, lower vol than common. Good IRA income layer.",
         "allocation":"3-5% of IRA (~$16-26K)", "shares_approx":"~510 shares @ $32"},
        {"ticker":"VXUS",  "name":"Vanguard Total International Stock",  "yield":"3.1%", "type":"International ETF",
         "note":"You have 0% international. Target 10% ($53K). Adds global diversification.",
         "allocation":"10% of IRA ($53K) — buy this first",
         "shares_approx":"~914 shares @ $58"},
        {"ticker":"JEPQ",  "name":"JPMorgan Nasdaq Equity Premium",     "yield":"9.5%", "type":"Covered Call ETF",
         "note":"Nasdaq + covered calls. 9-10% yield, tech exposure with income buffer.",
         "allocation":"3-5% of IRA (~$16-26K) — replaces some ARKG",
         "shares_approx":"~330 shares @ $50"},
    ]

    ira_rows = ""
    for i in IRA_EXPANSION:
        t = _e(i["ticker"])
        note_js = _e(i["note"]).replace("'","\\'")
        ira_rows += f"""
        <tr>
          <td>
            <b style='color:#0F9D58'>{t}</b>
            <div class='research-bar'>
              <a class='ticker-link' href='https://finance.yahoo.com/quote/{t}' target='_blank'>📈 Yahoo</a>
              <a class='ticker-link' href='https://finviz.com/quote.ashx?t={t}' target='_blank'>📊 Finviz</a>
              <button class='ai-btn haiku' onclick="analyzeTickerAI('{t}','{note_js}')">🤖 AI</button>
            </div>
          </td>
          <td style='font-size:11px;color:#9A9AB0'>{_e(i["name"])}</td>
          <td style='text-align:center'><span style='background:#2979FF22;color:#7BB3FF;padding:2px 6px;border-radius:4px;font-size:10px'>{_e(i["type"])}</span></td>
          <td style='text-align:right;color:#0F9D58;font-weight:700'>{_e(i["yield"])}</td>
          <td style='font-size:10px;color:#9A9AB0'>{_e(i["note"][:65])}</td>
          <td style='font-size:10px;color:#F4B400'>{_e(i["allocation"])}</td>
          <td style='font-size:10px;color:#9A9AB0'>{_e(i["shares_approx"])}</td>
        </tr>"""

    ira_expansion_html = f"""
    <div class='section-title' style='margin-top:20px'>🏦 IRA Rollover — What's Missing (Expansion Opportunities)</div>
    <div style='background:#1a1a35;border:1px solid #0F9D58;border-radius:8px;padding:10px 14px;margin-bottom:10px;font-size:12px'>
      Your Rollover IRA ($531K) is eligible for these investment types not available in your old 401k.
      After the V/FCNTX rebalance, you'll have ~$160K in proceeds to redeploy into bonds + these categories.
      <button class='ai-btn' style='margin-left:8px' onclick="showAIPopup('🏦 IRA Rollover Strategy',
        'Rollover IRA has $531K. Currently 50% in V (Visa), 18% FCNTX, 12% SCHD. After rebalancing sells ($161K), what are the best 3-4 investments to buy? Consider: JEPI (covered call income), O (REIT monthly div), VCIT (corporate bonds), VXUS (international). Give specific allocations and share counts. Be direct.',
        '{sonnet_model}')">🤖 Ask Sonnet for IRA Strategy</button>
    </div>
    <table>
      <thead><tr style='font-size:10px;color:#9A9AB0'>
        <th>Ticker</th><th>Name</th><th>Type</th>
        <th style='text-align:right'>Yield</th><th>Why Add to IRA</th>
        <th>Suggested Allocation</th><th>Approx Shares</th>
      </tr></thead>
      <tbody style='font-size:11px'>{ira_rows}</tbody>
    </table>"""

    for acct_name, (priority, label, color) in PRIORITY_LABELS.items():
        acct_orders = by_account.get(acct_name, [])
        if not acct_orders:
            continue

        sells = [o for o in acct_orders if o.get("action")=="SELL"]
        buys  = [o for o in acct_orders if o.get("action")=="BUY"]

        sell_rows = ""
        for o in sells:
            for d in o.get("sell_details", []):
                analyst = ANALYST.get(d.get("ticker",""), {})
                rating  = analyst.get("rating","")
                base_note = analyst.get("note","")
                t = _e(d.get("ticker",""))
                ctx_js = _e(base_note).replace("'","\\'")
                drift_pct = o.get("drift_pct", 0)
                target_pct = o.get("target_pct", 0)
                current_pct = o.get("current_pct", 0)

                # If selling a BUY-rated ticker, explain it's overweight, not bad
                if rating == "BUY":
                    display_rating = "OVERWEIGHT"
                    rat_col = "#F4B400"
                    note = f"Overweight {current_pct:.1f}% vs {target_pct:.0f}% target — reducing allocation, not exiting position"
                elif rating == "HOLD":
                    display_rating = "TRIM"
                    rat_col = "#F4B400"
                    note = base_note
                else:
                    display_rating = "SELL"
                    rat_col = "#DB4437"
                    note = base_note

                # Dividend impact line
                annual_lost = d.get("annual_div_lost", 0)
                yield_pct   = d.get("yield_pct", 0)
                div_note = ""
                if annual_lost > 0:
                    div_note = f"<span style='color:#DB4437;font-size:10px;margin-left:4px'>📉 Lose ${annual_lost:,.0f}/yr ({yield_pct:.1f}% yield)</span>"
                elif yield_pct == 0 and d.get("proceeds", 0) > 500:
                    div_note = "<span style='color:#9A9AB0;font-size:10px;margin-left:4px'>No dividend</span>"

                sell_rows += f"""
                <tr style='background:#1e0808'>
                  <td><span style='color:#DB4437;font-weight:800'>SELL</span></td>
                  <td>
                    <b style='color:#e0e0f0'>{t}</b>{div_note}
                    <div class='research-bar'>
                      <a class='ticker-link' href='https://finance.yahoo.com/quote/{t}' target='_blank'>📈 Yahoo</a>
                      <a class='ticker-link' href='https://finviz.com/quote.ashx?t={t}' target='_blank'>📊 Finviz</a>
                      <button class='ai-btn haiku' onclick="analyzeTickerAI('{t}','{ctx_js}')">🤖 AI</button>
                    </div>
                  </td>
                  <td style='text-align:right;color:#e0e0f0'>{d.get("shares_to_sell",0):.1f}</td>
                  <td style='text-align:right;color:#9A9AB0'>${(d.get("price") or 0):.2f}</td>
                  <td style='text-align:right;color:#DB4437;font-weight:700'>${(d.get("proceeds") or 0):,.0f}</td>
                  <td><span style='color:{rat_col};font-size:10px;font-weight:700'>{_e(display_rating)}</span></td>
                  <td style='font-size:10px;color:#9A9AB0;max-width:200px'>{_e(note[:80])}</td>
                </tr>"""
            if not o.get("sell_details"):
                sell_rows += f"""
                <tr style='background:#1e0808'>
                  <td><span style='color:#DB4437;font-weight:800'>SELL</span></td>
                  <td colspan='3'><b style='color:#9A9AB0'>{_e(o.get("bucket",""))} bucket</b></td>
                  <td style='text-align:right;color:#DB4437;font-weight:700'>${o.get("amount_usd",0):,.0f}</td>
                  <td></td><td style='font-size:10px;color:#9A9AB0'>Exchange within plan</td>
                </tr>"""

        buy_rows = ""
        for o in buys:
            primary = next((d for d in o.get("buy_details",[]) if d.get("is_primary")), None)
            alt     = next((d for d in o.get("buy_details",[]) if d.get("is_alternative")), None)
            if primary:
                analyst  = ANALYST.get(primary.get("ticker",""), {})
                rating   = analyst.get("rating","")
                note     = analyst.get("note","")
                rat_col  = "#0F9D58" if rating=="BUY" else ("#F4B400" if rating=="HOLD" else "#DB4437")
                t        = _e(primary.get("ticker",""))
                ctx_js   = _e(note).replace("'","\\'")
                alt_note = f"<br><span style='color:#9A9AB0;font-size:10px'>OR: {alt['shares_to_buy']:.0f} shares {alt['ticker']} @ ${alt['price']:.2f}</span>" if alt else ""
                # Dividend gained
                annual_gained  = primary.get("annual_div_gained", 0)
                yield_pct_buy  = primary.get("yield_pct", 0)
                div_gain_note  = ""
                if annual_gained > 0:
                    div_gain_note = f"<span style='color:#0F9D58;font-size:10px;margin-left:4px'>💰 +${annual_gained:,.0f}/yr ({yield_pct_buy:.1f}% yield)</span>"
                elif yield_pct_buy == 0:
                    div_gain_note = "<span style='color:#9A9AB0;font-size:10px;margin-left:4px'>Growth — no yield</span>"
                buy_rows += f"""
                <tr style='background:#081e0e'>
                  <td><span style='color:#0F9D58;font-weight:800'>BUY</span></td>
                  <td>
                    <b style='color:#e0e0f0'>{t}</b>{alt_note}{div_gain_note}
                    <div class='research-bar'>
                      <a class='ticker-link' href='https://finance.yahoo.com/quote/{t}' target='_blank'>📈 Yahoo</a>
                      <a class='ticker-link' href='https://finviz.com/quote.ashx?t={t}' target='_blank'>📊 Finviz</a>
                      <button class='ai-btn haiku' onclick="analyzeRebalanceAI('{_e(acct_name)}','BUY','{t}','{primary.get('cost',0):,.0f}')">🤖 Validate</button>
                    </div>
                  </td>
                  <td style='text-align:right;color:#e0e0f0'>{primary.get("shares_to_buy",0):.0f}</td>
                  <td style='text-align:right;color:#9A9AB0'>${(primary.get("price") or 0):.2f}</td>
                  <td style='text-align:right;color:#0F9D58;font-weight:700'>${(primary.get("cost") or 0):,.0f}</td>
                  <td><span style='color:{rat_col};font-size:10px;font-weight:700'>{_e(rating)}</span></td>
                  <td style='font-size:10px;color:#9A9AB0;max-width:200px'>{_e(note[:60])}</td>
                </tr>"""
            elif not o.get("buy_details"):
                sug = ", ".join(o.get("suggested_tickers",[])[:2])
                buy_rows += f"""
                <tr style='background:#081e0e'>
                  <td><span style='color:#0F9D58;font-weight:800'>BUY</span></td>
                  <td colspan='3'><b style='color:#9A9AB0'>{_e(o.get("bucket",""))} — {_e(sug)}</b></td>
                  <td style='text-align:right;color:#0F9D58;font-weight:700'>${o.get("amount_usd",0):,.0f}</td>
                  <td></td><td style='font-size:10px;color:#9A9AB0'>See bond section below</td>
                </tr>"""

        total_sell_proceeds = sum(
            d.get("proceeds",0) for o in sells for d in o.get("sell_details",[]))
        total_buy_cost = sum(
            d.get("cost",0) for o in buys
            for d in o.get("buy_details",[]) if d.get("is_primary"))
        total_buy_cost += sum(
            o.get("amount_usd",0) for o in buys if not o.get("buy_details"))

        # Net dividend impact
        total_div_lost   = sum(d.get("annual_div_lost",0) for o in sells for d in o.get("sell_details",[]))
        total_div_gained = sum(d.get("annual_div_gained",0) for o in buys
                               for d in o.get("buy_details",[]) if d.get("is_primary"))
        net_div = total_div_gained - total_div_lost
        div_html = ""
        if total_div_lost > 0 or total_div_gained > 0:
            div_col = "#0F9D58" if net_div >= 0 else "#DB4437"
            div_html = f"&nbsp;&nbsp;<span style='font-size:11px'>Div impact: <b style='color:#DB4437'>-${total_div_lost:,.0f}/yr</b> → <b style='color:#0F9D58'>+${total_div_gained:,.0f}/yr</b> · Net: <b style='color:{div_col}'>{'+' if net_div>=0 else ''}${net_div:,.0f}/yr</b></span>"

        balance_note = ""
        if total_sell_proceeds > 0 or total_buy_cost > 0:
            diff = total_buy_cost - total_sell_proceeds
            diff_color = "#9A9AB0" if abs(diff) < 5000 else "#F4B400"
            balance_note = f"""
            <div style='margin-top:8px;padding:6px 10px;background:#0d0d1a;border-radius:6px;
                        font-size:11px;display:flex;gap:20px;flex-wrap:wrap'>
              <span>Sells: <b style='color:#DB4437'>${total_sell_proceeds:,.0f}</b></span>
              <span>Buys: <b style='color:#0F9D58'>${total_buy_cost:,.0f}</b></span>
              <span>Net: <b style='color:{diff_color}'>{f"+${diff:,.0f} new cash needed" if diff > 500 else f"${abs(diff):,.0f} to cash" if diff < -500 else "✅ Balanced"}</b></span>
              {div_html}
            </div>"""
        playbook_html += f"""
        <div style='border:1px solid {color};border-radius:10px;margin-bottom:14px;overflow:hidden'>
          <div style='background:{color}22;padding:10px 16px;border-bottom:1px solid {color}44;
                      display:flex;justify-content:space-between;align-items:center'>
            <div>
              <span style='background:{color};color:#000;padding:2px 8px;border-radius:4px;
                           font-size:11px;font-weight:800;margin-right:8px'>STEP {priority}</span>
              <span style='color:#e0e0f0;font-size:13px;font-weight:700'>{_e(acct_name)}</span>
            </div>
            <span style='color:{color};font-size:11px;font-weight:700'>{_e(label)}</span>
          </div>
          <div style='padding:10px 16px'>
            <table style='width:100%;border-collapse:collapse'>
              <thead><tr style='font-size:10px;color:#9A9AB0'>
                <th style='text-align:left;padding:4px 8px'>ACTION</th>
                <th style='text-align:left;padding:4px 8px'>TICKER</th>
                <th style='text-align:right;padding:4px 8px'>SHARES</th>
                <th style='text-align:right;padding:4px 8px'>PRICE</th>
                <th style='text-align:right;padding:4px 8px'>AMOUNT</th>
                <th style='padding:4px 8px'>ANALYST</th>
                <th style='padding:4px 8px'>RATIONALE</th>
              </tr></thead>
              <tbody style='font-size:12px'>
                {sell_rows}
                <tr><td colspan='7' style='padding:4px 0'></td></tr>
                {buy_rows}
              </tbody>
            </table>
            {balance_note}
          </div>
        </div>"""

    # ── Section 3: V → SCHD Scenario ─────────────────────────────────────────
    v_html = ""
    if v_scenario:
        v_pct  = v_scenario.get("current_v_pct_portfolio", 26.5)
        v_mv   = v_scenario.get("current_v_mv", 302759)
        v_shr  = v_scenario.get("current_v_shares", 1005)
        v_div  = v_scenario.get("current_v_annual_div", 2513)
        rec    = v_scenario.get("recommendation","")
        tax_note = v_scenario.get("tax_note","")

        scenario_rows = ""
        for s in v_scenario.get("scenarios",[]):
            highlight = "border:1px solid #0F9D58;" if s["scenario_pct"]==30 else ""
            rec_label = " ⭐ RECOMMENDED" if s["scenario_pct"]==30 else ""
            scenario_rows += f"""
            <tr style='background:{"#081e0e" if s["scenario_pct"]==30 else "inherit"}'>
              <td style='font-weight:700;color:{"#0F9D58" if s["scenario_pct"]==30 else "#e0e0f0"}'>{s["scenario_pct"]}%{rec_label}</td>
              <td style='text-align:right'>{s["sell_v_shares"]:.0f} shares</td>
              <td style='text-align:right;color:#DB4437'>${s["sell_v_mv"]:,.0f}</td>
              <td style='text-align:right;color:#0F9D58'>{s["buy_schd_shares"]:.0f} SCHD</td>
              <td style='text-align:right;color:#DB4437'>${abs(s.get("lost_v_annual_div",0)):,.0f}/yr lost</td>
              <td style='text-align:right;color:#0F9D58'>+${s["gained_schd_annual_div"]:,.0f}/yr gained</td>
              <td style='text-align:right;font-weight:700;color:#0F9D58'>+${s["net_div_change"]:,.0f}/yr (+${s["net_div_change_monthly"]:,.0f}/mo)</td>
              <td style='text-align:right'>{v_pct:.1f}% → {s["remaining_v_pct"]}%</td>
            </tr>"""

        v_html = f"""
        <div class='section-title' style='margin-top:16px'>📊 V (Visa) → SCHD Scenario Analysis</div>
        <div style='background:#1a1a35;border:1px solid #2a2a5e;border-radius:10px;padding:14px 18px;margin-bottom:16px'>
          <div style='display:flex;gap:24px;margin-bottom:12px;flex-wrap:wrap'>
            <div><span style='color:#9A9AB0;font-size:10px'>CURRENT V POSITION</span><br>
              <span style='color:#e0e0f0;font-size:16px;font-weight:800'>{v_shr:.0f} shares · ${v_mv:,.0f}</span></div>
            <div><span style='color:#9A9AB0;font-size:10px'>PORTFOLIO WEIGHT</span><br>
              <span style='color:#DB4437;font-size:16px;font-weight:800'>{v_pct:.1f}% ⚠️</span></div>
            <div><span style='color:#9A9AB0;font-size:10px'>V DIVIDEND (0.83%)</span><br>
              <span style='color:#9A9AB0;font-size:16px;font-weight:800'>${v_div:,.0f}/yr</span></div>
            <div><span style='color:#9A9AB0;font-size:10px'>SCHD YIELD</span><br>
              <span style='color:#0F9D58;font-size:16px;font-weight:800'>3.58%</span></div>
          </div>
          <div style='background:#0F9D5822;border:1px solid #0F9D58;border-radius:6px;padding:10px 14px;margin-bottom:12px;font-size:12px;color:#e0e0f0'>
            💡 <b>KEY INSIGHT:</b> Both V positions are in IRAs (Rollover + Roth). 
            Selling V inside an IRA = <b style='color:#0F9D58'>ZERO capital gains tax</b> regardless of the +702% gain. 
            This is the ideal account for this rebalance.
          </div>
          <table style='width:100%;font-size:11px'>
            <thead><tr style='color:#9A9AB0;font-size:10px'>
              <th>Sell %</th><th style='text-align:right'>Shares Sold</th>
              <th style='text-align:right'>Proceeds</th><th style='text-align:right'>SCHD Bought</th>
              <th style='text-align:right'>V Div Lost</th><th style='text-align:right'>SCHD Div Gained</th>
              <th style='text-align:right'>Net Income Change</th><th style='text-align:right'>V Concentration</th>
            </tr></thead>
            <tbody>{scenario_rows}</tbody>
          </table>
        </div>"""

    # ── Section 4: Bond Recommendations ──────────────────────────────────────
    bond_html = ""
    if bond_recs:
        bond_rows = ""
        for b in bond_recs:
            highlight = b.get("ticker") in ("BND","VCIT")
            bond_rows += f"""
            <tr style='{"background:#081e0e" if highlight else ""}'>
              <td><b style='color:{"#0F9D58" if highlight else "#e0e0f0"}'>{_e(b["ticker"])}</b>
                {"<span style='background:#0F9D58;color:#000;font-size:9px;padding:1px 5px;border-radius:3px;margin-left:4px'>RECOMMENDED</span>" if highlight else ""}</td>
              <td style='font-size:11px;color:#9A9AB0'>{_e(b["name"])}</td>
              <td style='text-align:right;color:#0F9D58;font-weight:700'>{b["yield_pct"]}%</td>
              <td style='text-align:right'>{b["duration_yrs"]}yr</td>
              <td style='text-align:right;color:#9A9AB0'>{b["expense_ratio"]}%</td>
              <td style='font-size:10px;color:#9A9AB0'>{_e(b["credit_quality"])}</td>
              <td style='font-size:10px;color:#e0e0f0'>{_e(b["best_for"])}</td>
            </tr>"""

        bond_html = f"""
        <div class='section-title' style='margin-top:16px'>🏦 Bond Recommendations — Rollover IRA (Need ${112972:,.0f})</div>
        <div style='background:#1a1a35;border:1px solid #2979FF;border-radius:8px;padding:10px 14px;margin-bottom:10px;font-size:12px;color:#e0e0f0'>
          💡 <b>RECOMMENDED SPLIT:</b> 60% VCIT ($67,783 = 923 shares @ $73.50) + 40% BND ($45,189 = 615 shares @ $73.55)<br>
          Blended yield: ~4.2% = <b style='color:#0F9D58'>~$4,726/yr income</b> inside tax-deferred account.<br>
          <span style='color:#9A9AB0;font-size:10px'>Do NOT use municipal bonds in an IRA — the tax-free feature is wasted.</span>
        </div>
        <table>
          <thead><tr><th>Ticker</th><th>Name</th><th style='text-align:right'>Yield</th>
            <th style='text-align:right'>Duration</th><th style='text-align:right'>Expense</th>
            <th>Credit</th><th>Best For</th></tr></thead>
          <tbody style='font-size:11px'>{bond_rows}</tbody>
        </table>"""

    # ── Section 5: Drift table (original, collapsed by default) ──────────────
    drift_html = "<div class='section-title' style='margin-top:16px'>📋 Drift Detail by Account</div>"
    for acct_key, analysis in drift.items():
        if not analysis: continue
        rows = ""
        for row in analysis.get("drift_rows", []):
            action = row.get("action","HOLD")
            drift_pct = row.get("drift_pct",0)
            cls = "rebal-buy" if action=="BUY" else ("rebal-sell" if action=="SELL" else "rebal-hold")
            needs = row.get("needs_rebalance", False)
            rows += f"""<tr style='{"background:#1e1e08" if needs else ""}'>
              <td>{_e(row.get("bucket",""))}</td>
              <td class='nt' style='text-align:right'>{row.get("target_pct",0):.0f}%</td>
              <td class='nt' style='text-align:right'>{row.get("current_pct",0):.1f}%</td>
              <td class='{_color_class(drift_pct)}' style='text-align:right'>{drift_pct:+.1f}%</td>
              <td class='{cls}' style='text-align:right'>{action}</td>
              <td class='{cls}' style='text-align:right'>{_fmt_usd(abs(row.get("rebalance_mv") or 0))}</td>
              <td style='font-size:10px;color:#9A9AB0'>{_e(", ".join(row.get("holdings_in_bucket",[])[:3]))}</td>
            </tr>"""
        needs_label = "⚠️ REBALANCE NEEDED" if analysis.get("needs_rebalance") else "✅ BALANCED"
        drift_html += f"""
        <div class='account-card'>
          <h3>{_e(analysis.get("account_display",""))} — {_fmt_usd(analysis.get("total_value"))} {needs_label}
            &nbsp;<small style='color:#9A9AB0;font-size:11px'>net ${analysis.get("net_to_move",0):,.0f}</small></h3>
          <table><thead><tr><th>Bucket</th><th style='text-align:right'>Target</th>
            <th style='text-align:right'>Current</th><th style='text-align:right'>Drift</th>
            <th style='text-align:right'>Action</th><th style='text-align:right'>Amount</th>
            <th>Holdings</th></tr></thead>
          <tbody>{rows}</tbody></table>
        </div>"""

    return f"""
    <div class='section-title'>⚖️ Rebalancing — ${total_to_move:,.0f} Net to Move</div>
    {etf_html}
    {playbook_html}
    {v_html}
    {bond_html}
    {ira_expansion_html}
    {drift_html}"""


def _build_tax(tax: Dict) -> str:
    harvest = tax.get("harvest_candidates", [])
    divs_ytd = tax.get("dividend_income_ytd", {})
    summary = tax.get("summary", {})
    unrealized = tax.get("unrealized_gains", [])[:20]

    rows = ""
    for u in unrealized:
        gl = u.get("unrealized_gain") or 0
        tax_est = u.get("tax_estimate") or 0
        hp = u.get("holding_period", "")
        taxable = u.get("taxable", False)
        rows += f"""<tr>
          <td><b>{_e(u.get("symbol",""))}</b></td>
          <td class='nt'>{_e(u.get("account",""))}</td>
          <td class='{_color_class(gl)}'>{_fmt_usd(gl)}</td>
          <td class='{_color_class(u.get("unrealized_gain_pct"))}'>{_fmt_pct(u.get("unrealized_gain_pct"))}</td>
          <td class='nt'>{_e(hp)}</td>
          <td class='nt'>{"Yes" if taxable else "No (IRA)"}</td>
          <td class='dn'>{_fmt_usd(tax_est) if tax_est else "—"}</td>
        </tr>"""

    harvest_html = ""
    for c in harvest:
        harvest_html += f"""
        <div class='flag-row' style='border-left:3px solid #F4B400'>
          <div class='flag-icon'>🌾</div>
          <div class='flag-body'>
            <div class='flag-msg'><b>{_e(c.get("symbol",""))}</b> in {_e(c.get("account",""))}:
              {_fmt_usd(c.get("unrealized_gain"))} loss ({_fmt_pct(c.get("unrealized_gain_pct"))}) —
              Est. tax savings: {_fmt_usd(c.get("tax_savings_estimate"))}</div>
            <div class='flag-action'>{_e(c.get("wash_sale_warning",""))}</div>
          </div>
        </div>"""

    return f"""
    <div class='section-title'>🧾 Tax Intelligence</div>
    <div class='cards'>
      <div class='card'>
        <div class='card-label'>Total Unrealized Gain</div>
        <div class='card-value {_color_class(summary.get("total_unrealized_gain"))}'>{_fmt_usd(summary.get("total_unrealized_gain"))}</div>
        <div class='card-sub nt'>All accounts</div>
      </div>
      <div class='card'>
        <div class='card-label'>Taxable Unrealized Gain</div>
        <div class='card-value {_color_class(summary.get("taxable_unrealized_gain"))}'>{_fmt_usd(summary.get("taxable_unrealized_gain"))}</div>
        <div class='card-sub nt'>Taxable account only</div>
      </div>
      <div class='card'>
        <div class='card-label'>YTD Dividends Received</div>
        <div class='card-value up'>{_fmt_usd(divs_ytd.get("ytd_total"))}</div>
        <div class='card-sub nt'>{divs_ytd.get("transaction_count",0)} transactions</div>
      </div>
      <div class='card'>
        <div class='card-label'>Harvest Opportunities</div>
        <div class='card-value {("dn" if len(harvest) > 0 else "nt")}'>{len(harvest)}</div>
        <div class='card-sub nt'>Potential savings: {_fmt_usd(summary.get("harvest_potential_savings"))}</div>
      </div>
    </div>
    <div class='section-title'>🌾 Tax Loss Harvest Candidates (Taxable Account)</div>
    {harvest_html if harvest_html else "<p class='nt'>No significant harvest candidates in taxable accounts.</p>"}
    <div class='section-title' style='margin-top:16px'>Unrealized Gains by Position</div>
    <table>
      <thead><tr>
        <th>Symbol</th><th>Account</th><th>Gain/Loss $</th><th>Gain/Loss %</th>
        <th>Holding Period</th><th>Taxable?</th><th>Est. Tax</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def _build_trade_ai(risk_data: Dict) -> str:
    ta = risk_data.get("trade_ai_correlation", {})
    go = ta.get("go_tickers", [])
    wait = ta.get("wait_tickers", [])
    overlaps = ta.get("holdings_in_screener", [])

    go_html = ", ".join(f"<b class='up'>{_e(s)}</b>" for s in go) if go else "<span class='nt'>None today</span>"
    wait_html = ", ".join(f"<span class='nt'>{_e(s)}</span>" for s in wait[:10]) if wait else "<span class='nt'>None</span>"

    overlap_rows = ""
    for o in overlaps:
        alert = o.get("alert", "")
        score = o.get("trade_ai_score", 0)
        decision = o.get("trade_ai_decision", "")
        dec_cls = "up" if decision == "GO" else ("nt" if decision == "WAIT" else "dn")
        overlap_rows += f"""<tr>
          <td><b>{_e(o.get("symbol",""))}</b></td>
          <td class='nt'>{_e(o.get("account",""))}</td>
          <td class='nt'>{_fmt_usd(o.get("market_value"))}</td>
          <td class='{_color_class(o.get("unrealized_gain"))}'>{_fmt_usd(o.get("unrealized_gain"))}</td>
          <td class='{dec_cls}'>{_e(decision)} ({score})</td>
          <td class='nt'>{_e(o.get("catalyst","")[:50])}</td>
          <td>{_e(alert)}</td>
        </tr>"""

    return f"""
    <div class='section-title'>🎯 Trade AI Correlation</div>
    <div class='cards'>
      <div class='card'>
        <div class='card-label'>GO Tickers Today</div>
        <div class='card-value up'>{ta.get("go_count", 0)}</div>
      </div>
      <div class='card'>
        <div class='card-label'>WAIT Tickers</div>
        <div class='card-value nt'>{ta.get("wait_count", 0)}</div>
      </div>
      <div class='card'>
        <div class='card-label'>Holdings in Screener</div>
        <div class='card-value nt'>{ta.get("overlap_count", 0)}</div>
      </div>
    </div>
    <p style='margin-bottom:8px'><b>GO Today:</b> {go_html}</p>
    <p style='margin-bottom:16px'><b>WAIT:</b> {wait_html}</p>
    <div class='section-title'>Your Holdings in Trade AI Screener</div>
    {"<table><thead><tr><th>Symbol</th><th>Account</th><th>Value</th><th>Gain/Loss</th><th>Trade AI</th><th>Catalyst</th><th>Alert</th></tr></thead><tbody>" + overlap_rows + "</tbody></table>" if overlaps else "<p class='nt'>None of your holdings appeared in today's Trade AI screener.</p>"}"""


def generate_portfolio_dashboard(
    portfolio: Dict,
    analysis: Dict,
    tax: Dict,
    rebalancing: Dict,
    risk: Dict,
    output_path: Path,
    performance: Optional[Dict] = None,
    ai_analysis: Optional[Dict] = None,
    api_key: str = "",
    journal: Optional[Dict] = None,
    risk_mgmt: Optional[Dict] = None,
    options: Optional[Dict] = None,
    technical: Optional[Dict] = None,
    tax_projection: Optional[Dict] = None,
    stress: Optional[Dict] = None,
    retirement: Optional[Dict] = None,
    behavioral: Optional[Dict] = None,
    perf_history: Optional[Dict] = None,
    dividend_calendar: Optional[Dict] = None,
    attribution: Optional[Dict] = None,
    correlation: Optional[Dict] = None,
    watchlist: Optional[Dict] = None,
    trade_analysis: Optional[Dict] = None,
) -> str:
    as_of = portfolio.get("as_of", datetime.now().strftime("%Y-%m-%d"))
    owner = portfolio.get("owner", "")
    totals = portfolio.get("portfolio_totals", {})
    total_mv = totals.get("total_value", 0)

    nav_html = "".join(
        f"<div class='tab{' active' if i==0 else ''}' onclick='showTab(\"{tid}\",this)'>{label}</div>"
        for i, (tid, label) in enumerate(TABS)
    )

    sonnet_model = os.getenv("CLAUDE_ESCALATION_MODEL", "claude-sonnet-4-6")

    def _safe(name, fn):
        try:
            return fn()
        except Exception as e:
            import traceback as _tb
            err = _tb.format_exc()
            print(f"  [dashboard] ❌ {name}: {e}")
            return (f"<div class='section-title'>❌ {name} Error</div>"
                    f"<div style='background:#2a0000;border:1px solid #DB4437;border-radius:8px;"
                    f"padding:14px;font-family:monospace;font-size:11px;color:#DB4437;white-space:pre-wrap'>"
                    f"<b>{name}</b>: {e}</div>")

    sections = {
        "overview":   _safe("overview",   lambda: _build_overview(portfolio, analysis, risk, perf_history or {})),
        "accounts":   _safe("accounts",   lambda: _build_accounts(portfolio)),
        "holdings":   _safe("holdings",   lambda: _build_holdings(portfolio, analysis)),
        "performance":_safe("performance",lambda: _build_performance(portfolio, analysis, risk, perf_history or {})),
        "journal":    _safe("journal",    lambda: _build_trade_journal(journal or {}, behavioral or {})),
        "risk_mgmt":  _safe("risk_mgmt",  lambda: _build_risk_management(risk_mgmt or {}, options or {}, stress or {})),
        "tax":        _safe("tax",        lambda: _build_tax(tax)),
        "rebalance":  _safe("rebalance",  lambda: _build_rebalancing(rebalancing, sonnet_model)),
        "trade_ai":   _safe("trade_ai",   lambda: _build_trade_ai(risk)),
        "ai_analysis":_safe("ai_analysis",lambda: _build_ai_analysis(ai_analysis, portfolio, analysis, risk, perf_history or {}, rebalancing)),
        "periods":    _safe("periods",    lambda: _build_period_returns(performance, portfolio, perf_history or {})),
        "technical":  _safe("technical",  lambda: _build_technical_tab(technical or {})),
        "retirement": _safe("retirement", lambda: _build_retirement_tab(retirement or {}, tax_projection or {})),
        "config":     _safe("config",     lambda: _build_config_tab_inline(portfolio)),
        "dividends":  _safe("dividends",  lambda: _build_dividends_tab(dividend_calendar or {})),
        "attribution":_safe("attribution",lambda: _build_attribution_tab(attribution or {}, perf_history or {})),
        "correlation":_safe("correlation",lambda: _build_correlation_tab(correlation or {})),
        "watchlist":  _safe("watchlist",  lambda: _build_watchlist_tab(watchlist or {})),
    }

    sections_html = "".join(
        f"<div class='section{' active' if i==0 else ''}' id='sec-{tid}'>{content}</div>"
        for i, (tid, _) in enumerate(TABS)
        for t, content in [(tid, sections.get(tid, ""))]
        if t == tid
    )

    # Pass API key to JS safely
    api_key_js = api_key.replace("'", "\\'") if api_key else ""
    sonnet_model = os.getenv("CLAUDE_ESCALATION_MODEL", "claude-sonnet-4-6")
    haiku_model  = os.getenv("CLAUDE_CHEAP_MODEL",      "claude-haiku-4-5")

    html_doc = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Portfolio Intelligence — {_e(as_of)}</title>
<style>{CSS}
.ai-btn{{background:#2979FF;color:#fff;border:none;padding:4px 10px;border-radius:4px;
         cursor:pointer;font-size:10px;font-weight:700;margin-left:6px}}
.ai-btn:hover{{background:#1565C0}}.ai-btn.haiku{{background:#7B1FA2}}.ai-btn.haiku:hover{{background:#4A148C}}
.ai-popup{{position:fixed;top:60px;right:20px;width:480px;max-height:70vh;overflow-y:auto;
           background:#1a1a35;border:2px solid #2979FF;border-radius:12px;padding:16px;
           z-index:9999;box-shadow:0 8px 32px #0007;display:none}}
.ai-popup h4{{color:#7BB3FF;margin-bottom:8px;font-size:13px}}
.ai-popup .close-btn{{float:right;cursor:pointer;color:#9A9AB0;font-size:16px;background:none;border:none}}
.ai-popup p{{font-size:12px;color:#e0e0f0;line-height:1.6;white-space:pre-wrap}}
.ticker-link{{color:#7BB3FF;text-decoration:none;font-size:10px;margin-left:4px}}
.ticker-link:hover{{text-decoration:underline}}
.research-bar{{display:flex;gap:4px;align-items:center;flex-wrap:wrap}}
</style></head><body>
<div id='ai-popup' class='ai-popup'>
  <button class='close-btn' onclick="document.getElementById('ai-popup').style.display='none'">✕</button>
  <h4 id='ai-popup-title'>AI Analysis</h4>
  <div id='ai-popup-body'><p style='color:#9A9AB0'>Loading...</p></div>
</div>
<div class='header'>
  <div>
    <div class='header-title'>💼 Portfolio Intelligence v1.2</div>
    <div class='header-sub'>{_e(owner)} · {_e(as_of)} · {_fmt_usd(total_mv)} total</div>
  </div>
  <div style='text-align:right;font-size:11px;color:#9A9AB0'>
    <div>Trade AI v12.1d</div>
    <div id='clock'></div>
  </div>
</div>
<div class='nav'>{nav_html}</div>
<div class='content' id='main-content'>{sections_html}</div>
<script>
function showTab(id, el) {{
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  var sec = document.getElementById('sec-' + id);
  if (sec) sec.classList.add('active');
  if (el) el.classList.add('active');
}}
function updateClock() {{
  var now = new Date();
  document.getElementById('clock').textContent =
    now.toLocaleTimeString('en-US', {{hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:'America/New_York'}}) + ' ET';
}}
setInterval(updateClock, 1000); updateClock();

// ── AI Analysis on demand ──────────────────────────────────────────────────
const API_KEY    = '{api_key_js}';
const SONNET     = '{sonnet_model}';
const HAIKU      = '{haiku_model}';

function showAIPopup(title, prompt, model) {{
  var popup = document.getElementById('ai-popup');
  var body  = document.getElementById('ai-popup-body');
  var ttl   = document.getElementById('ai-popup-title');
  ttl.textContent  = title;
  body.innerHTML   = '<p style="color:#9A9AB0">⏳ Calling Claude ' + (model===SONNET?'Sonnet 4.6':'Haiku') + '...</p>';
  popup.style.display = 'block';
  if (!API_KEY) {{
    body.innerHTML = '<div style="color:#F4B400;font-size:12px">' +
      '<b>⚡ API key not embedded in this dashboard.</b><br><br>' +
      'Re-run the pipeline to embed your key:<br>' +
      '<code style="background:#0d0d1a;padding:4px 8px;border-radius:4px;display:inline-block;margin-top:6px">' +
      'run_portfolio.bat</code><br><br>' +
      'Then refresh this page at localhost:7777' +
      '</div>';
    return;
  }}
  // Call via local proxy (handles CORS) — proxy runs on port 7778 via run_dashboard.bat
  fetch('http://localhost:7778/api/claude', {{
    method: 'POST',
    headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{model:model, max_tokens:800, messages:[{{role:'user',content:prompt}}]}})
  }})
  .then(r => {{
    if (!r.ok) return r.json().then(e => {{ throw new Error(JSON.stringify(e)); }});
    return r.json();
  }})
  .then(d => {{
    var text = (d.content && d.content[0] && d.content[0].text) ? d.content[0].text : JSON.stringify(d);
    body.innerHTML = '<p>' + text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</p>';
  }})
  .catch(e => {{
    var msg = String(e);
    if (msg.includes('Failed to fetch') || msg.includes('NetworkError') || msg.includes('ERR_CONNECTION')) {{
      body.innerHTML = '<div style="color:#F4B400;font-size:12px">' +
        '<b>⚡ Local proxy not running.</b><br><br>' +
        'Open dashboard via: <code style="background:#0d0d1a;padding:4px 8px;border-radius:4px">run_dashboard.bat</code><br>' +
        '(This starts both the file server and AI proxy on port 7778)' +
        '</div>';
    }} else {{
      body.innerHTML = '<div style="color:#DB4437;font-size:12px"><b>Error:</b><br>' + msg.replace(/</g,'&lt;') + '</div>';
    }}
  }});
}}

function analyzeTickerAI(ticker, context) {{
  var prompt = 'You are a senior wealth manager. In 200 words, give me a direct assessment of ' + ticker + 
    ' for a personal investor in April 2026. Context: ' + context + 
    '. Cover: analyst consensus, price target, key risk, specific recommendation (BUY/HOLD/SELL/TRIM). Be direct.';
  showAIPopup('🤖 ' + ticker + ' — Quick Analysis (Haiku)', prompt, HAIKU);
}}

function analyzeRebalanceAI(acct, action, ticker, amount) {{
  var prompt = 'Portfolio rebalancing question: ' + action + ' ' + ticker + ' for $' + amount + 
    ' in ' + acct + '. Is this the right move in April 2026? Confirm rationale in 3 sentences ' +
    'and flag any timing risk. Be direct and specific.';
  showAIPopup('🤖 Validate: ' + action + ' ' + ticker, prompt, HAIKU);
}}

function runFullRebalanceAI() {{
  var prompt = `Portfolio rebalancing review (April 2026, $1,144,617 total):
ROTH IRA: SELL 130 V → BUY 922 SCHG (tax-free)
ROLLOVER IRA: SELL FCNTX/V/PFE/XLB/XLI → BUY 1536 BND + VXUS (tax-deferred)
TAXABLE: SELL 37 ARKQ → BUY LMT/NOC, add SCHD
Is this rebalancing plan sound? What would you change? Any better alternatives?
Flag any timing concerns with the current market (April 2026 tariff uncertainty, rate environment).
Be specific and direct. 4-5 sentences max.`;
  showAIPopup('🤖 Full Rebalancing Plan Review (Sonnet 4.6)', prompt, SONNET);
}}

function researchTicker(ticker) {{
  window.open('https://finance.yahoo.com/quote/' + ticker, '_blank');
}}
</script></body></html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"  [dashboard] Portfolio dashboard → {output_path}")
    return str(output_path)


def _build_accounts(portfolio: Dict) -> str:
    summaries = portfolio.get("account_summaries", {})
    holdings = portfolio.get("holdings", [])
    parts = []
    for acct_key, s in sorted(summaries.items(), key=lambda x: -x[1].get("total_value", 0)):
        acct_holdings = [h for h in holdings
                        if h.get("account") == acct_key and not h.get("is_loan")
                        and (h.get("market_value") or 0) > 0]
        acct_holdings.sort(key=lambda h: -(h.get("market_value") or 0))
        rows = ""
        for h in acct_holdings[:15]:
            gl = h.get("gain_loss") or 0
            rows += f"""<tr>
              <td><b>{_e(h.get("symbol",""))}</b></td>
              <td class='nt' style='font-size:11px'>{_e(h.get("name",""))[:35]}</td>
              <td class='nt' style='text-align:right'>{_fmt_usd(h.get("market_value"))}</td>
              <td class='{_color_class(gl)}' style='text-align:right'>{_fmt_usd(gl)}</td>
              <td class='{_color_class(h.get("gain_loss_pct"))}' style='text-align:right'>{_fmt_pct(h.get("gain_loss_pct"))}</td>
              <td class='nt' style='text-align:right'>{h.get("account_pct",0):.1f}%</td>
            </tr>"""
        gl_total = s.get("total_gain", 0)
        parts.append(f"""
        <div class='account-card'>
          <h3>{_e(s.get("display_name",""))} · {_e(s.get("account_type",""))} · {_fmt_usd(s.get("total_value"))}</h3>
          <div style='margin-bottom:8px;font-size:11px;color:#9A9AB0'>
            Total Gain: <span class='{_color_class(gl_total)}'>{_fmt_usd(gl_total)} ({_fmt_pct(s.get("total_gain_pct"))})</span>
            · {s.get("holding_count",0)} positions
            {"· Loan: " + _fmt_usd(s.get("loan_balance")) if s.get("loan_balance") else ""}
          </div>
          <table><thead><tr><th>Symbol</th><th>Name</th><th style='text-align:right'>Value</th>
            <th style='text-align:right'>Gain $</th><th style='text-align:right'>Gain %</th>
            <th style='text-align:right'>% Acct</th></tr></thead>
          <tbody>{rows}</tbody></table>
        </div>""")
    return "<div class='section-title'>🏦 Accounts</div>" + "\n".join(parts)


def _build_ai_analysis(ai_analysis: Optional[Dict], portfolio: Optional[Dict] = None,
                       analysis: Optional[Dict] = None, risk: Optional[Dict] = None,
                       perf_history: Optional[Dict] = None, rebalancing: Optional[Dict] = None) -> str:
    if not ai_analysis:
        return """<div class='section-title'>🤖 AI Strategic Analysis</div>
        <p class='nt'>Run with --run-type monthly to generate full Sonnet 4.6 analysis.</p>"""

    def _ai_card(title: str, key: str, icon: str = "🤖") -> str:
        text = ai_analysis.get(key, "")
        if not text: return ""

        def _detect_bar_chart(lines_block: list) -> str:
            """Detect lines like '- $10K additional: ~$2,200 tax' and render as horizontal bar chart."""
            import re as _re
            items = []
            for ln in lines_block:
                m = _re.match(r'^[-•*]\s*\$?([\d,.]+K?)\s*(additional|more)?\s*:?\s*[~]?\$?([\d,.]+K?)\s*(.*)', ln.strip())
                if m:
                    label = f"${m.group(1)}"
                    val_str = m.group(3).replace(",","").replace("K","000")
                    try: val = float(val_str)
                    except: continue
                    note = m.group(4).strip().lstrip("(").rstrip(")")
                    items.append((label, val, note))
            if len(items) < 2: return ""
            max_val = max(v for _,v,_ in items) or 1
            bars = ""
            for label, val, note in items:
                pct = val / max_val * 100
                rec = "← RECOMMENDED" in note.upper() or "OPTIMAL" in note.upper()
                col = "#0F9D58" if rec else "#2979FF"
                border = f"border:1px solid {col};" if rec else ""
                bars += (f"<div style='display:flex;align-items:center;gap:8px;margin:4px 0;{border}"
                         f"padding:4px 8px;border-radius:4px'>"
                         f"<span style='color:#e0e0f0;font-size:11px;min-width:50px;font-weight:600'>{label}</span>"
                         f"<div style='flex:1;background:#1a1a35;border-radius:3px;height:18px;overflow:hidden'>"
                         f"<div style='background:{col};height:100%;width:{pct:.0f}%;border-radius:3px;"
                         f"display:flex;align-items:center;padding-left:6px'>"
                         f"<span style='color:#fff;font-size:9px;font-weight:600'>${val:,.0f}</span></div></div>"
                         f"<span style='color:#9A9AB0;font-size:9px;min-width:80px'>{_e(note[:40])}</span></div>")
            return (f"<div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;"
                    f"padding:12px;margin:10px 0'>"
                    f"<div style='color:#7BB3FF;font-size:10px;font-weight:700;margin-bottom:8px;"
                    f"text-transform:uppercase;letter-spacing:.5px'>📊 Tax Impact Analysis</div>{bars}</div>")

        def _detect_allocation_chart(lines_block: list) -> str:
            """Detect numbered allocation lists like '1. **SCHG (0.4%)** — desc' and render as horizontal bars."""
            import re as _re
            items = []
            for ln in lines_block:
                clean = ln.strip().replace("**", "")
                m = _re.match(r'^\d+\.\s*([A-Z/]+(?:\s*\w*)?)\s*\(([^)]+)\)\s*[—–-]\s*(.*)', clean)
                if m:
                    ticker = m.group(1).strip()
                    metric = m.group(2).strip()
                    desc = m.group(3).strip()
                    items.append((ticker, metric, desc))
            if len(items) < 3: return ""
            cols = ["#2979FF","#0F9D58","#F4B400","#DB4437","#9C27B0","#00BCD4"]
            bars = ""
            for i, (ticker, metric, desc) in enumerate(items):
                col = cols[i % len(cols)]
                width = max(20, 100 - i * 15)
                bars += (f"<div style='display:flex;align-items:center;gap:8px;margin:3px 0'>"
                         f"<span style='color:#e0e0f0;font-size:11px;min-width:50px;font-weight:700'>{_e(ticker)}</span>"
                         f"<div style='flex:1;background:#1a1a35;border-radius:3px;height:14px;overflow:hidden'>"
                         f"<div style='background:{col};height:100%;width:{width}%;border-radius:3px'></div></div>"
                         f"<span style='color:{col};font-size:10px;min-width:55px'>{_e(metric)}</span>"
                         f"<span style='color:#9A9AB0;font-size:9px'>{_e(desc[:50])}</span></div>")
            return (f"<div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;"
                    f"padding:12px;margin:10px 0'>"
                    f"<div style='color:#7BB3FF;font-size:10px;font-weight:700;margin-bottom:8px;"
                    f"text-transform:uppercase;letter-spacing:.5px'>📈 Allocation Priority</div>{bars}</div>")

        def _detect_deduction_table(lines_block: list) -> str:
            """Detect deduction lists like '1. **Home office:** $3,000-$5,000' and render as table."""
            import re as _re
            items = []
            for ln in lines_block:
                clean = ln.strip().replace("**", "")
                m = _re.match(r'^\d+\.\s*([^:]+):\s*\$?([\d,.]+)\s*[-–]\s*\$?([\d,.]+)', clean)
                if m:
                    items.append((m.group(1).strip(), m.group(2), m.group(3)))
            if len(items) < 3: return ""
            rows = ""
            for cat, lo, hi in items:
                rows += (f"<tr><td style='padding:4px 8px;border-bottom:1px solid #1e1e38;color:#e0e0f0;font-size:11px'>"
                         f"{_e(cat)}</td>"
                         f"<td style='padding:4px 8px;border-bottom:1px solid #1e1e38;color:#0F9D58;font-size:11px;"
                         f"text-align:right;font-weight:600'>${lo} – ${hi}</td></tr>")
            return (f"<div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;"
                    f"padding:12px;margin:10px 0'>"
                    f"<div style='color:#7BB3FF;font-size:10px;font-weight:700;margin-bottom:8px;"
                    f"text-transform:uppercase;letter-spacing:.5px'>💰 Deduction Opportunities</div>"
                    f"<table style='width:100%;border-collapse:collapse'>"
                    f"<tr><th style='padding:4px 8px;color:#6b6b8a;font-size:9px;text-align:left;"
                    f"border-bottom:1px solid #2a2a5e'>Category</th>"
                    f"<th style='padding:4px 8px;color:#6b6b8a;font-size:9px;text-align:right;"
                    f"border-bottom:1px solid #2a2a5e'>Annual Range</th></tr>{rows}</table></div>")

        def _inline(s: str) -> str:
            """Convert inline markdown (**bold**, *italic*, `code`) to HTML."""
            import re
            s = _e(s)
            s = re.sub(r'\*\*(.+?)\*\*', r'<strong style="color:#F4B400">\1</strong>', s)
            s = re.sub(r'\*([^*]+?)\*',  r'<em style="color:#aaddff">\1</em>', s)
            s = re.sub(r'`([^`]+)`',     r'<code style="background:#1e2a4a;color:#80CBC4;padding:1px 4px;border-radius:3px;font-size:11px">\1</code>', s)
            return s

        def _render_md(md: str) -> str:
            lines      = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            body       = ""
            table_rows: list = []
            in_table   = False

            # Pre-scan: detect chart-worthy blocks and insert them
            _chart_inserts = {}  # line_index -> chart_html
            _block = []
            _block_start = -1
            for li, raw in enumerate(lines):
                stripped = raw.strip()
                if stripped and (stripped[0] in "-•*" or (len(stripped) > 1 and stripped[:2].rstrip(". ").isdigit())):
                    if not _block:
                        _block_start = li
                    _block.append(stripped)
                else:
                    if len(_block) >= 3:
                        chart = _detect_bar_chart(_block)
                        if not chart:
                            chart = _detect_allocation_chart(_block)
                        if not chart:
                            chart = _detect_deduction_table(_block)
                        if chart:
                            _chart_inserts[_block_start] = chart
                    _block = []
                    _block_start = -1
            if len(_block) >= 3:
                chart = _detect_bar_chart(_block) or _detect_allocation_chart(_block) or _detect_deduction_table(_block)
                if chart:
                    _chart_inserts[_block_start] = chart

            def flush_table() -> str:
                nonlocal table_rows, in_table
                if not table_rows:
                    in_table = False
                    return ""
                out = ("<div style='overflow-x:auto;margin:10px 0 16px'>"
                       "<table style='width:100%;border-collapse:collapse;font-size:12px'>")
                for ridx, row in enumerate(table_rows):
                    cells = [c.strip() for c in row.strip("|").split("|")]
                    if ridx == 0:
                        out += ("<thead><tr>"
                                + "".join(
                                    f"<th style='padding:6px 10px;background:#1e2a4a;color:#7BB3FF;"
                                    f"font-weight:700;text-align:left;border:1px solid #2a2a5e;"
                                    f"white-space:nowrap'>{_inline(c)}</th>"
                                    for c in cells)
                                + "</tr></thead><tbody>")
                    else:
                        out += ("<tr>"
                                + "".join(
                                    f"<td style='padding:5px 10px;border:1px solid #2a2a5e;"
                                    f"color:#e0e0f0;background:{'#191b30' if ci == 0 else 'transparent'}'>"
                                    f"{_inline(c)}</td>"
                                    for ci, c in enumerate(cells))
                                + "</tr>")
                out += "</tbody></table></div>"
                table_rows = []
                in_table   = False
                return out

            for _li, raw in enumerate(lines):
                line = raw.strip()

                # Insert auto-detected chart before this line if applicable
                if _li in _chart_inserts:
                    body += _chart_inserts[_li]

                # blank line — flush table if open, skip otherwise
                if not line:
                    if in_table:
                        body += flush_table()
                    continue

                # table separator row (|---|---|) — skip silently
                if line.startswith("|") and line.endswith("|") and set(line) <= set("|-: "):
                    continue

                # table data row
                if line.startswith("|") and line.endswith("|"):
                    in_table = True
                    table_rows.append(line)
                    continue

                # flush open table before any non-table line
                if in_table:
                    body += flush_table()

                # ── headings ──────────────────────────────────────────────
                if line.startswith("#### "):
                    body += (f"<p style='color:#9A9AB0;font-size:10px;font-weight:700;"
                             f"margin:10px 0 2px;text-transform:uppercase;letter-spacing:.6px'>"
                             f"{_inline(line[5:])}</p>")
                elif line.startswith("### "):
                    body += (f"<div style='color:#F4B400;font-size:12px;font-weight:700;"
                             f"margin:12px 0 5px;padding:3px 0 4px 8px;"
                             f"border-left:2px solid #F4B400'>{_inline(line[4:])}</div>")
                elif line.startswith("## "):
                    body += (f"<div style='color:#7BB3FF;font-size:13px;font-weight:800;"
                             f"margin:16px 0 6px;padding:5px 10px;background:#151b2e;"
                             f"border-left:3px solid #2979FF;border-radius:0 4px 4px 0'>"
                             f"{_inline(line[3:])}</div>")
                elif line.startswith("# "):
                    body += (f"<div style='color:#ffffff;font-size:14px;font-weight:900;"
                             f"margin:18px 0 8px;padding:7px 12px;background:#1e2a4a;"
                             f"border-radius:6px;border-left:4px solid #2979FF'>"
                             f"{_inline(line[2:])}</div>")

                # ── checklist items (✅/❌/⚠️ prefix) ────────────────────
                elif any(line.startswith(p) for p in ("✅", "❌", "⚠️", "- ✅", "- ❌", "- ⚠️")):
                    txt = line.lstrip("-•* ").strip()
                    icon = txt[0] if txt and txt[0] in "✅❌⚠" else "▸"
                    rest = txt.lstrip("✅❌⚠️ ").strip()
                    border_col = "#0F9D58" if "✅" in txt[:3] else "#DB4437" if "❌" in txt[:3] else "#F4B400"
                    body += (f"<div style='display:flex;align-items:flex-start;"
                             f"padding:6px 10px;margin:3px 0;background:#0d0d1a;"
                             f"border-left:3px solid {border_col};border-radius:0 4px 4px 0'>"
                             f"<span style='margin-right:8px;flex-shrink:0;font-size:13px'>{icon}</span>"
                             f"<span style='color:#e0e0f0;font-size:12px;"
                             f"line-height:1.55'>{_inline(rest)}</span></div>")

                # ── bullet points ─────────────────────────────────────────
                elif line and line[0] in "•-*→▸":
                    txt = line.lstrip("•-*→▸ ")
                    if txt:   # skip empty bullets entirely
                        body += (f"<div style='display:flex;align-items:flex-start;"
                                 f"padding:2px 0 2px 8px;margin:2px 0'>"
                                 f"<span style='color:#2979FF;margin-right:8px;"
                                 f"margin-top:1px;flex-shrink:0'>▸</span>"
                                 f"<span style='color:#e0e0f0;font-size:12px;"
                                 f"line-height:1.55'>{_inline(txt)}</span></div>")

                # ── horizontal rule ───────────────────────────────────────
                elif len(line) >= 3 and set(line) <= {"-", "=", "_"}:
                    body += "<hr style='border:none;border-top:1px solid #2a2a5e;margin:10px 0'>"

                # ── RECOMMENDATION / ACTION highlight card ─────────────
                elif any(line.upper().startswith(p) for p in
                         ("RECOMMENDATION:", "ACTION:", "KEY RISK:", "WHY IT MATTERS:",
                          "OPTIMAL:", "IMMEDIATE ACTION:", "PRIORITY:")):
                    label_end = line.index(":")
                    label = line[:label_end].strip()
                    rest = line[label_end+1:].strip()
                    label_col = "#DB4437" if "RISK" in label.upper() else "#0F9D58" if any(w in label.upper() for w in ("RECOMMEND","ACTION","OPTIMAL")) else "#F4B400"
                    body += (f"<div style='background:#0d0d1a;border:1px solid {label_col}30;"
                             f"border-left:3px solid {label_col};border-radius:0 6px 6px 0;"
                             f"padding:8px 12px;margin:8px 0'>"
                             f"<span style='color:{label_col};font-size:10px;font-weight:800;"
                             f"text-transform:uppercase;letter-spacing:.5px'>{_inline(label)}</span>"
                             f"<div style='color:#e0e0f0;font-size:12px;margin-top:3px;"
                             f"line-height:1.5'>{_inline(rest)}</div></div>")

                # ── ALL-CAPS label (e.g. "EXECUTIVE RECOMMENDATION") ──────
                elif (line == line.upper() and len(line) > 4
                      and any(c.isalpha() for c in line)
                      and not line.startswith("|")):
                    body += (f"<div style='color:#F4B400;font-size:11px;font-weight:800;"
                             f"margin:14px 0 4px;letter-spacing:.7px'>{_inline(line)}</div>")

                # ── numbered item "1. " or "1) " ──────────────────────────
                elif line[:3].rstrip(". )").isdigit():
                    body += (f"<div style='background:#111122;border-left:2px solid #2979FF;"
                             f"padding:6px 10px;margin:6px 0;border-radius:0 4px 4px 0'>"
                             f"<span style='color:#7BB3FF;font-size:12px;font-weight:700'>"
                             f"{_inline(line)}</span></div>")

                # ── normal paragraph (compact) ────────────────────────────
                else:
                    body += (f"<p style='color:#b8b8d0;font-size:12px;"
                             f"margin:4px 0;line-height:1.6'>{_inline(line)}</p>")

            if in_table:
                body += flush_table()
            return body

        body      = _render_md(text)
        generated = ai_analysis.get("generated_at", "")[:10]
        lines_count = len([l for l in text.split("\n") if l.strip()])
        is_long = lines_count > 15
        card_id = f"ai-{key}"
        collapse_btn = ""
        collapse_style = ""
        if is_long:
            collapse_btn = (f"<button onclick=\"var c=document.getElementById('{card_id}-body');"
                            f"var b=this;if(c.style.maxHeight==='200px'){{c.style.maxHeight='none';"
                            f"b.textContent='▲ Collapse'}}else{{c.style.maxHeight='200px';"
                            f"b.textContent='▼ Show all {lines_count} items'}}\""
                            f" style='background:none;border:1px solid #2a2a5e;color:#7BB3FF;"
                            f"font-size:10px;padding:3px 10px;border-radius:4px;cursor:pointer;"
                            f"margin-top:8px'>▼ Show all {lines_count} items</button>")
            collapse_style = "max-height:200px;overflow:hidden;"
        return f"""
        <div class='account-card' style='border-left:4px solid #2979FF;margin-bottom:16px'>
          <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:10px'>
            <h3 style='color:#7BB3FF;font-size:13px;font-weight:800'>{icon} {_e(title)}</h3>
            <span style='font-size:10px;color:#9A9AB0'>claude-sonnet-4-20250514 · {generated}</span>
          </div>
          <div id='{card_id}-body' style='border-top:1px solid #2a2a5e;padding-top:10px;{collapse_style}'>{body}</div>
          {collapse_btn}
        </div>"""

    run_type = ai_analysis.get("run_type","daily")
    generated = ai_analysis.get("generated_at","")[:10]

    sections = [
        ("executive_summary",  "Executive Portfolio Brief",           "📋"),
        ("deep_holdings",      "Deep Holdings Analysis",              "🔬"),
        ("dividend_strategy",  "Dividend Strategy & Income Upgrades", "💰"),
        ("bond_strategy",      "Bond Strategy for Rollover IRA",      "📊"),
        ("ira_opportunities",  "IRA Rollover — Expanded Universe",    "🏦"),
        ("roth_conversion",    "Roth Conversion Strategy 2026",       "🔄"),
        ("v_strategy",         "V (Visa) Concentration — Full Analysis","⚠️"),
        ("defense_analysis",   "Defense Portfolio — AI WWIII",        "🛡️"),
    ]

    mode_badge = f"<span style='background:#2979FF;color:#fff;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700'>{run_type.upper()}</span>"
    refresh_note = "" if run_type != "daily" else \
        "<p style='font-size:11px;color:#F4B400;margin-bottom:12px'>⚡ Daily mode — full analysis cached from last monthly run. Run monthly for fresh Sonnet analysis.</p>"

    # ── KPI Hero Bar + Sector Pie ────────────────────────────────────────
    _p = portfolio or {}
    _a = analysis or {}
    _r = risk or {}
    _ph = perf_history or {}
    _rb = rebalancing or {}
    _totals = _p.get("portfolio_totals", {})
    _tv = _totals.get("total_value", 0)
    _tg = _totals.get("total_gain", 0)
    _tg_pct = _totals.get("total_gain_pct", 0)
    _dc = _totals.get("day_change", 0) or 0
    _dc_pct = _totals.get("day_change_pct", 0) or 0
    _divs = _a.get("dividends", {})
    _div_inc = _divs.get("total_annual_income", 0) or 0
    _beta = _r.get("portfolio_beta", 0) or 0
    _ytd = _ph.get("periods", {}).get("YTD", {}).get("change_pct", 0) or 0
    _1y = _ph.get("periods", {}).get("1Y", {}).get("change_pct", 0) or 0
    _dc_col = "#0F9D58" if _dc >= 0 else "#DB4437"
    _ytd_col = "#0F9D58" if _ytd >= 0 else "#DB4437"

    # Sector pie chart (CSS conic-gradient)
    _sectors = _p.get("resolved_sectors", [])
    _sec_colors = ["#2979FF","#0F9D58","#F4B400","#DB4437","#9C27B0","#00BCD4",
                   "#FF5722","#8BC34A","#3F51B5","#E91E63","#607D8B","#795548","#CDDC39"]
    _pie_stops = []
    _legend = ""
    _cum = 0
    for i, s in enumerate(_sectors[:10]):
        pct = s.get("pct", 0)
        col = _sec_colors[i % len(_sec_colors)]
        _pie_stops.append(f"{col} {_cum}% {_cum + pct}%")
        _cum += pct
        _legend += (f"<div style='display:flex;align-items:center;gap:6px;margin:2px 0'>"
                    f"<div style='width:8px;height:8px;border-radius:2px;background:{col};flex-shrink:0'></div>"
                    f"<span style='color:#9A9AB0;font-size:10px'>{_e(s.get('sector',''))} {pct:.1f}%</span></div>")
    if _cum < 100:
        _pie_stops.append(f"#1a1a35 {_cum}% 100%")
    _pie_grad = ", ".join(_pie_stops)

    kpi_html = f"""
    <div style='display:grid;grid-template-columns:1fr 280px;gap:16px;margin-bottom:16px'>
      <!-- KPI Cards -->
      <div style='display:grid;grid-template-columns:repeat(3,1fr);gap:8px'>
        <div class='account-card' style='text-align:center;padding:12px'>
          <div style='color:#6b6b8a;font-size:9px;text-transform:uppercase;letter-spacing:1px'>Portfolio</div>
          <div style='color:#e0e0f0;font-size:22px;font-weight:800'>${_tv:,.0f}</div>
          <div style='color:{_dc_col};font-size:11px'>{'+' if _dc>=0 else ''}{_dc_pct:.2f}% today</div>
        </div>
        <div class='account-card' style='text-align:center;padding:12px'>
          <div style='color:#6b6b8a;font-size:9px;text-transform:uppercase;letter-spacing:1px'>All-Time Gain</div>
          <div style='color:#0F9D58;font-size:22px;font-weight:800'>+${_tg:,.0f}</div>
          <div style='color:#0F9D58;font-size:11px'>+{_tg_pct:.1f}%</div>
        </div>
        <div class='account-card' style='text-align:center;padding:12px'>
          <div style='color:#6b6b8a;font-size:9px;text-transform:uppercase;letter-spacing:1px'>Dividends/yr</div>
          <div style='color:#e0e0f0;font-size:22px;font-weight:800'>${_div_inc:,.0f}</div>
          <div style='color:#F4B400;font-size:11px'>{_div_inc/_tv*100:.2f}% yield</div>
        </div>
        <div class='account-card' style='text-align:center;padding:12px'>
          <div style='color:#6b6b8a;font-size:9px;text-transform:uppercase;letter-spacing:1px'>Beta</div>
          <div style='color:#e0e0f0;font-size:22px;font-weight:800'>{_beta:.2f}</div>
          <div style='color:{"#0F9D58" if _beta<1.0 else "#F4B400"};font-size:11px'>{"Below" if _beta<1.0 else "Above"} 1.0 target</div>
        </div>
        <div class='account-card' style='text-align:center;padding:12px'>
          <div style='color:#6b6b8a;font-size:9px;text-transform:uppercase;letter-spacing:1px'>YTD</div>
          <div style='color:{_ytd_col};font-size:22px;font-weight:800'>{_ytd:+.1f}%</div>
          <div style='color:#9A9AB0;font-size:11px'>1Y: {_1y:+.1f}%</div>
        </div>
        <div class='account-card' style='text-align:center;padding:12px'>
          <div style='color:#6b6b8a;font-size:9px;text-transform:uppercase;letter-spacing:1px'>Rebalance</div>
          <div style='color:#F4B400;font-size:22px;font-weight:800'>${_rb.get("total_to_rebalance",0):,.0f}</div>
          <div style='color:#9A9AB0;font-size:11px'>{_rb.get("order_count",0)} orders</div>
        </div>
      </div>
      <!-- Sector Pie -->
      <div class='account-card' style='padding:12px'>
        <div style='color:#6b6b8a;font-size:9px;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;text-align:center'>Sector Exposure (Look-Through)</div>
        <div style='display:flex;align-items:center;gap:12px'>
          <div style='width:120px;height:120px;border-radius:50%;flex-shrink:0;
                      background:conic-gradient({_pie_grad});
                      box-shadow:0 0 12px rgba(41,121,255,0.15)'></div>
          <div style='flex:1;max-height:120px;overflow-y:auto'>{_legend}</div>
        </div>
      </div>
    </div>"""

    html = f"""<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px'>
      <div class='section-title' style='margin:0'>🤖 AI Strategic Analysis — claude-sonnet-4-20250514</div>
      <div style='font-size:11px;color:#9A9AB0'>{mode_badge} &nbsp; Generated: {generated}</div>
    </div>
    {refresh_note}
    {kpi_html}"""

    for key, title, icon in sections:
        html += _ai_card(title, key, icon)

    return html


def _build_performance(portfolio: Dict, analysis: Dict, risk: Dict, perf_history: Dict = None) -> str:
    # Build dynamic period card from perf_history
    _ph     = perf_history or {}
    _ph_pds = _ph.get("periods", {})
    _snaps  = int(_ph.get("snapshot_count") or 0)
    _building = _ph.get("building", [])

    # Find best available short period
    _period_card_html = ""
    for _pd_key in ["1W","1M","3M"]:
        _pd = _ph_pds.get(_pd_key)
        if _pd and _pd.get("change_pct") is not None:
            _chg = (_pd.get("change") or 0); _chg_pct = (_pd.get("change_pct") or 0)
            _pcc = "up" if (_chg or 0) >= 0 else "dn"
            _period_card_html = (
                f"<div class='card'>"
                f"<div class='card-label'>{_pd_key} Return</div>"
                f"<div class='card-value {_pcc}'>{'+' if _chg>=0 else ''}${abs(_chg):,.0f}</div>"
                f"<div class='card-sub {_pcc}'>{'+' if _chg_pct>=0 else ''}{_chg_pct:.2f}%</div>"
                f"</div>"
            )
            break

    if not _period_card_html:
        # No period data yet — show all-time from cost basis + progress
        _all = _ph_pds.get("ALL",{}) or {}
        _all_pct = _all.get("change_pct",0) or 0
        _needed  = max(0, 7 - _snaps)
        _progress_msg = f"{_snaps}/7 snapshots → 1W unlocks" if _snaps < 7 else f"1W soon"
        _period_card_html = (
            f"<div class='card'>"
            f"<div class='card-label'>Since Inception</div>"
            f"<div class='card-value up'>+{_all_pct:.1f}%</div>"
            f"<div class='card-sub nt' style='font-size:10px'>"
            f"{'&#9608;' * min(_snaps,7)}{'&#9617;' * max(0,7-_snaps)} "
            f"{_progress_msg}</div>"
            f"</div>"
        )
    attribution   = analysis.get("attribution", {})
    contributors  = attribution.get("top_contributors", [])
    detractors    = attribution.get("top_detractors", [])
    benchmarks    = risk.get("benchmark_comparison", {}).get("benchmarks", [])
    totals        = portfolio.get("portfolio_totals", {})
    holdings      = portfolio.get("holdings", [])
    account_sums  = portfolio.get("account_summaries", {})

    total_mv      = totals.get("total_value", 0)
    total_gain    = totals.get("total_gain", 0)
    total_gain_pct= totals.get("total_gain_pct", 0)
    day_pnl       = totals.get("day_change", 0)
    day_pnl_pct   = (day_pnl / (total_mv - day_pnl) * 100) if total_mv > day_pnl > -total_mv else 0

    # ── Today's P&L by account ──────────────────────────────────────────────
    acct_day_rows = ""
    acct_keys_list = []   # ordered list for filter pills
    for k, s in sorted(account_sums.items(), key=lambda x: -(x[1].get("total_value") or 0)):
        d = s.get("day_change") or 0
        v = s.get("total_value", 0)
        d_pct = (d / (v - d) * 100) if v > abs(d) else 0
        display = s.get("display_name", k)
        acct_keys_list.append((k, display))
        # Add data-acct for JS filtering
        acct_day_rows += f"""<tr data-acct="{_e(k)}">
          <td><b style='color:#e0e0f0'>{_e(display)}</b></td>
          <td class='nt'>{_e(s.get("account_type",""))}</td>
          <td style='text-align:right;font-weight:700'>{_fmt_usd(v)}</td>
          <td class='{_color_class(d)}' style='text-align:right;font-weight:700'>{_fmt_usd(d)}</td>
          <td class='{_color_class(d_pct)}' style='text-align:right'>{d_pct:+.2f}%</td>
        </tr>"""

    # ── Today's P&L by sector (from individual holding day changes) ─────────
    try:
        from portfolio_analyzer import _get_sector as _get_sector_fn
    except ImportError:
        def _get_sector_fn(sym, asset_type=""):  # type: ignore
            _MAP = {
                # Financials
                "V": "Financials", "AMANX": "Financials",
                # Defense
                "LMT": "Defense", "NOC": "Defense", "RTX": "Defense",
                "AVAV": "Defense", "KTOS": "Defense", "ITA": "Defense",
                # Technology / Growth
                "RKLB": "Technology",
                "SCHG": "US Equity", "ARKQ": "Growth ETF", "ARKG": "Growth ETF",
                # Income / Dividend
                "SCHD": "Income/Dividend", "DIV": "Income/Dividend",
                "CSWC": "BDC Income", "PFLT": "BDC Income",
                # Bonds
                "BND": "Bonds", "VCIT": "Bonds", "AGG": "Bonds",
                # International
                "VXUS": "International Equity", "VEU": "International Equity",
                # Healthcare
                "PFE": "Healthcare", "SRNE": "Healthcare",
                # Sector ETFs
                "XLI": "Industrials", "XLB": "Materials",
                # Fidelity 401k mapped tickers (Yahoo equivalents)
                "FCNTX": "US Equity Funds", "FXAIX": "US Equity Funds",
                "SLYG": "US Equity Funds", "TILCX": "US Equity Funds",
                "VFTNX": "International Equity", "JLGMX": "US Equity Funds",
                "WBGNX": "US Equity Funds", "WBSNX": "US Equity Funds",
                "ABDZX": "US Equity Funds", "ABSZX": "US Equity Funds",
                "FDIVX": "International Equity", "SSGLX": "International Equity",
                "SLYG": "US Equity Funds",
            }
            if sym in _MAP:
                return _MAP[sym]
            if asset_type in ("etf", "fund", "mutual_fund"):
                return "ETF/Fund"
            return "Other"

    sector_day: Dict[str, list] = {}
    for h in holdings:
        if h.get("is_loan") or h.get("is_cash"): continue
        d = h.get("day_change") or 0
        mv = h.get("market_value") or 0
        if mv <= 0: continue
        sector = _get_sector_fn(h.get("symbol",""), h.get("asset_type",""))
        sector_day.setdefault(sector, [0.0, 0.0])
        sector_day[sector][0] += d
        sector_day[sector][1] += mv

    sector_rows = ""
    for sector, (d, mv) in sorted(sector_day.items(), key=lambda x: -abs(x[1][0])):
        if mv < 100: continue
        d_pct = (d / (mv - d) * 100) if mv > abs(d) else 0
        pct_port = mv / total_mv * 100 if total_mv else 0
        sector_rows += f"""<tr>
          <td>{_e(sector)}</td>
          <td class='nt' style='text-align:right'>{pct_port:.1f}%</td>
          <td style='text-align:right;font-weight:700'>{_fmt_usd(mv)}</td>
          <td class='{_color_class(d)}' style='text-align:right;font-weight:700'>{_fmt_usd(d)}</td>
          <td class='{_color_class(d_pct)}' style='text-align:right'>{d_pct:+.2f}%</td>
        </tr>"""

    # ── All-time by position ─────────────────────────────────────────────────
    gainers = sorted([h for h in holdings if (h.get("gain_loss") or 0) > 0
                      and not h.get("is_loan")], key=lambda h: -(h.get("gain_loss") or 0))[:8]
    losers  = sorted([h for h in holdings if (h.get("gain_loss") or 0) < 0
                      and not h.get("is_loan")], key=lambda h: (h.get("gain_loss") or 0))[:8]

    g_rows = "".join(f"""<tr data-acct="{_e(h.get('account',''))}">
      <td><b>{_e(h.get("symbol",""))}</b></td>
      <td class='nt' style='font-size:11px'>{_e(h.get("account_display",""))}</td>
      <td class='up' style='text-align:right;font-weight:700'>{_fmt_usd(h.get("gain_loss"))}</td>
      <td class='up' style='text-align:right'>{_fmt_pct(h.get("gain_loss_pct"))}</td>
    </tr>""" for h in gainers)

    l_rows = "".join(f"""<tr data-acct="{_e(h.get('account',''))}">
      <td><b>{_e(h.get("symbol",""))}</b></td>
      <td class='nt' style='font-size:11px'>{_e(h.get("account_display",""))}</td>
      <td class='dn' style='text-align:right;font-weight:700'>{_fmt_usd(h.get("gain_loss"))}</td>
      <td class='dn' style='text-align:right'>{_fmt_pct(h.get("gain_loss_pct"))}</td>
    </tr>""" for h in losers)

    # Get portfolio YTD and 1Y from perf_history
    _ph_periods = (perf_history or {}).get("periods", {})
    _port_ytd   = (_ph_periods.get("YTD") or {}).get("change_pct")
    _port_1y    = (_ph_periods.get("1Y")  or {}).get("change_pct")
    _port_1m    = (_ph_periods.get("1M")  or {}).get("change_pct")

    bench_rows = "".join(f"""<tr>
      <td><b>{_e(b.get("ticker",""))}</b></td>
      <td class='nt'>{_e(b.get("name",""))}</td>
      <td class='{_color_class(b.get("ytd_pct"))}'>{_fmt_pct(b.get("ytd_pct"))}</td>
      <td class='{_color_class(b.get("1yr_pct"))}'>{_fmt_pct(b.get("1yr_pct"))}</td>
      <td class='{_color_class(_port_ytd) if _port_ytd is not None else "nt"}' style='font-weight:700'>
        {"&#8212;" if _port_ytd is None else _fmt_pct(_port_ytd)}</td>
      <td class='{_color_class(_port_1y) if _port_1y is not None else "nt"}' style='font-weight:700'>
        {"&#8212;" if _port_1y is None else _fmt_pct(_port_1y)}</td>
    </tr>""" for b in benchmarks)


    # Historical returns from reconstruction
    hist_periods = (perf_history or {}).get("periods", {})
    hist_rows = ""
    period_order = ["1D","1W","1M","3M","6M","YTD","1Y"]
    for p in period_order:
        pd = hist_periods.get(p)
        if not pd: continue
        chg     = pd.get("change", 0) or 0
        chg_pct = pd.get("change_pct", 0) or 0
        past_v  = pd.get("start_value") or pd.get("past_value") or 0
        src_lbl = "📸" if pd.get("source")=="snapshot" else "📊"
        col     = "#0F9D58" if chg >= 0 else "#DB4437"
        hist_rows += (f"<tr>"
                      f"<td style='font-weight:700;color:#e0e0f0'>{p}</td>"
                      f"<td>{_e(pd.get('start_date') or pd.get('date',''))}</td>"
                      f"<td style='text-align:right;color:#9A9AB0'>${past_v:,.0f}</td>"
                      f"<td style='text-align:right;font-weight:700;color:{col}'>"
                      f"{'$+' if chg>=0 else '$'}{chg:,.0f}</td>"
                      f"<td style='text-align:right;font-weight:700;color:{col}'>"
                      f"{'+' if chg_pct>=0 else ''}{chg_pct:.2f}%</td>"
                      f"<td style='color:#9A9AB0;font-size:10px'>{src_lbl}</td>"
                      f"</tr>")
    hist_section = ""
    if hist_rows:
        hist_section = f"""<div class='section-title' style='margin-top:18px'>📅 Period Returns (Reconstructed)</div>
    <div style='font-size:10px;color:#9A9AB0;margin-bottom:6px'>
      📊 = Reconstructed from transaction history + Yahoo Finance closing prices &nbsp;|&nbsp;
      📸 = Actual daily snapshot
    </div>
    <table>
      <thead><tr style='font-size:10px;color:#9A9AB0'>
        <th>Period</th><th>From Date</th>
        <th style='text-align:right'>Portfolio Then</th>
        <th style='text-align:right'>Change $</th>
        <th style='text-align:right'>Change %</th>
        <th>Source</th>
      </tr></thead>
      <tbody style='font-size:12px'>{hist_rows}</tbody>
    </table>"""
    else:
        hist_section = ("<div style='background:#1a1a35;border:1px solid #2a2a5e;border-radius:8px;"
                        "padding:12px;margin-top:14px'>"
                        "<span class='nt'>Historical returns will appear here after first run with "
                        "<code>portfolio_performance_history.py</code></span></div>")


    # ── Account filter pill HTML + JS ────────────────────────────────────────
    _perf_filter_js = """
<script>
(function() {
  function perfFilter(acct) {
    // Update pill styles
    document.querySelectorAll('.perf-pill').forEach(function(p) {
      p.style.background = p.dataset.acct === acct ? '#2979FF' : '#1a1a35';
      p.style.color      = p.dataset.acct === acct ? '#fff' : '#9A9AB0';
      p.style.borderColor= p.dataset.acct === acct ? '#2979FF' : '#2a2a5e';
    });
    // Filter all data-acct rows in the performance section
    var sec = document.getElementById('sec-performance');
    if (!sec) return;
    sec.querySelectorAll('tr[data-acct]').forEach(function(row) {
      if (!acct || row.dataset.acct === acct) {
        row.style.display = '';
      } else {
        row.style.display = 'none';
      }
    });
    // Update the section title to show active filter
    var title = sec.querySelector('.section-title');
    if (title) {
      if (acct) {
        var pillLabel = document.querySelector('.perf-pill[data-acct="' + acct + '"]');
        var lbl = pillLabel ? pillLabel.textContent.trim() : acct;
        title.innerHTML = '📈 Performance Dashboard <span style="font-size:11px;color:#2979FF;font-weight:400;margin-left:8px">Filtered: ' + lbl + '</span>';
      } else {
        title.innerHTML = '📈 Performance Dashboard';
      }
    }
    // Recompute totals row visibility hint
    window._perfActiveAcct = acct;
  }
  window.perfFilter = perfFilter;
})();
</script>"""

    _pill_colors = {
        "schwab_rollover_ira":  "#2979FF",
        "schwab_roth":          "#0F9D58",
        "schwab_taxable":       "#F4B400",
        "fidelity_401k":        "#9A9AB0",
    }
    _pills_html = ""
    for _ak, _dn in [("", "All Accounts")] + acct_keys_list:
        _col = _pill_colors.get(_ak, "#7BB3FF") if _ak else "#2979FF"
        _active = "background:#2979FF;color:#fff;border-color:#2979FF" if not _ak else \
                  "background:#1a1a35;color:#9A9AB0;border-color:#2a2a5e"
        _pills_html += (
            f"<button class='perf-pill' data-acct='{_e(_ak)}' onclick='perfFilter(\"{_e(_ak)}\")' "
            f"style='{_active};border:1px solid;border-radius:16px;padding:4px 12px;"
            f"font-size:11px;font-weight:700;cursor:pointer;margin-right:6px;"
            f"white-space:nowrap'>{_e(_dn)}</button>"
        )
    _filter_bar = f"""
    {_perf_filter_js}
    <div style='display:flex;align-items:center;flex-wrap:wrap;gap:4px;
                margin-bottom:12px;padding:8px 0'>
      <span style='font-size:11px;color:#9A9AB0;margin-right:6px;white-space:nowrap'>
        🔽 Filter by account:
      </span>
      {_pills_html}
    </div>"""

    return f"""
    {_filter_bar}
    <div class='section-title'>📈 Performance Dashboard</div>
    <div class='cards'>
      <div class='card'>
        <div class='card-label'>Today P&L</div>
        <div class='card-value {_color_class(day_pnl)}'>{_fmt_usd(day_pnl)}</div>
        <div class='card-sub {_color_class(day_pnl_pct)}'>{day_pnl_pct:+.2f}% today</div>
      </div>
      <div class='card'>
        <div class='card-label'>All-Time Gain</div>
        <div class='card-value {_color_class(total_gain)}'>{_fmt_usd(total_gain)}</div>
        <div class='card-sub {_color_class(total_gain_pct)}'>{_fmt_pct(total_gain_pct)} since inception</div>
      </div>
      {_period_card_html}
      <div class='card'>
        <div class='card-label'>Portfolio Value</div>
        <div class='card-value nt'>{_fmt_usd(total_mv)}</div>
        <div class='card-sub nt'>Across 4 accounts</div>
      </div>
    </div>

    <div style='background:#1a1a35;border:1px solid #2a2a5e;border-radius:8px;padding:10px 14px;
                margin-bottom:14px;font-size:11px;color:#9A9AB0'>
      ⏳ <b style='color:#F4B400'>Week/Month/Quarter/Year returns</b> appear automatically in the
      <b>Period Returns</b> tab after daily snapshots accumulate (1 week = 7 days, etc).
      Drop fresh Schwab CSVs in <code>data/portfolios/input/</code> each morning before 7 AM
      to build history. You currently have {_snaps} snapshot{'s' if _snaps != 1 else ''}.
    </div>

    <div style='display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px'>
      <div>
        <div class='section-title' style='font-size:12px'>📅 Today by Account</div>
        <table><thead><tr><th>Account</th><th>Type</th>
          <th style='text-align:right'>Value</th>
          <th style='text-align:right'>Today $</th>
          <th style='text-align:right'>Today %</th></tr></thead>
        <tbody>{acct_day_rows}</tbody></table>
      </div>
      <div>
        <div class='section-title' style='font-size:12px'>📅 Today by Sector</div>
        <table><thead><tr><th>Sector</th><th style='text-align:right'>% Port</th>
          <th style='text-align:right'>Value</th>
          <th style='text-align:right'>Today $</th>
          <th style='text-align:right'>Today %</th></tr></thead>
        <tbody>{sector_rows}</tbody></table>
      </div>
    </div>

    <div style='display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px'>
      <div>
        
    {hist_section}

    <div class='section-title' style='font-size:12px'>🏆 All-Time Top Gainers</div>
        <table><thead><tr><th>Symbol</th><th>Account</th>
          <th style='text-align:right'>Gain $</th><th style='text-align:right'>Gain %</th>
        </tr></thead><tbody>{g_rows}</tbody></table>
      </div>
      <div>
        <div class='section-title' style='font-size:12px'>📉 All-Time Losers</div>
        <table><thead><tr><th>Symbol</th><th>Account</th>
          <th style='text-align:right'>Loss $</th><th style='text-align:right'>Loss %</th>
        </tr></thead><tbody>{l_rows}</tbody></table>
      </div>
    </div>

    <div class='section-title'>📊 Benchmark Comparison (Reference)</div>
    <p class='nt' style='font-size:11px;margin-bottom:8px'>
      Portfolio all-time gain is vs cost basis, not YTD. Use Period Returns tab for comparable period returns.
    </p>
    <table><thead><tr><th>Ticker</th><th>Benchmark</th>
      <th style='text-align:right'>YTD Benchmark</th><th style='text-align:right'>1-Year Benchmark</th>
      <th style='text-align:right;color:#4CAF50'>Your YTD</th><th style='text-align:right;color:#4CAF50'>Your 1Y</th>
    </tr></thead><tbody>{bench_rows}</tbody></table>"""


def _build_period_returns(performance, portfolio, perf_history=None):
    """Period Returns tab -- uses perf_history (snapshot-based)."""
    ph       = perf_history or {}
    ph_pds   = ph.get("periods", {})
    snaps    = ph.get("snapshot_count", 0)
    building = ph.get("building", [])
    totals   = portfolio.get("portfolio_totals", {})

    day_pnl    = totals.get("day_change", 0) or 0
    total_gain = totals.get("total_gain", 0) or 0
    gain_pct   = totals.get("total_gain_pct", 0) or 0
    total_val  = totals.get("total_value", 0) or 0

    # Best available period card (1W preferred, fallback to inception progress)
    best_card = ""
    for pk in ["1W","1M","3M","6M"]:
        pd = ph_pds.get(pk)
        if pd and pd.get("change_pct") is not None:
            c = pd["change"]; cp = pd["change_pct"]
            col = "up" if c >= 0 else "dn"
            sign_c = "+" if c >= 0 else ""
            sign_p = "+" if cp >= 0 else ""
            best_card = (f"<div class='card'><div class='card-label'>{pk} Return</div>"
                         f"<div class='card-value {col}'>{sign_c}{_fmt_usd(c)}</div>"
                         f"<div class='card-sub {col}'>{sign_p}{cp:.2f}%</div></div>")
            break

    if not best_card:
        filled = min(snaps, 7); empty = max(0, 7 - snaps)
        bar = "&#9608;" * filled + "&#9617;" * empty
        need = 7 - snaps
        msg  = f"{bar} {snaps}/7 &mdash; 1W in {need}d" if snaps < 7 else f"{bar} 1W ready next run"
        best_card = (f"<div class='card' style='border-top:3px solid #F4B400'>"
                     f"<div class='card-label'>Since Inception</div>"
                     f"<div class='card-value up'>+{gain_pct:.1f}%</div>"
                     f"<div class='card-sub nt' style='font-size:10px'>{msg}</div></div>")

    d1   = ph_pds.get("1D") or {}
    d1c  = d1.get("change", day_pnl) or day_pnl
    d1cp = d1.get("change_pct")
    d1sub = f"{'+'if (d1cp or 0)>=0 else ''}{d1cp:.2f}% today" if d1cp else "Today change"
    d1col = "up" if d1c >= 0 else "dn"

    cards_html = (
        f"<div class='cards'>"
        f"<div class='card'><div class='card-label'>Today P&amp;L</div>"
        f"<div class='card-value {d1col}'>{_fmt_usd(d1c)}</div>"
        f"<div class='card-sub nt'>{d1sub}</div></div>"
        f"<div class='card'><div class='card-label'>All-Time Gain</div>"
        f"<div class='card-value up'>{_fmt_usd(total_gain)}</div>"
        f"<div class='card-sub up'>+{gain_pct:.1f}% since inception</div></div>"
        f"{best_card}"
        f"<div class='card'><div class='card-label'>Portfolio Value</div>"
        f"<div class='card-value nt'>{_fmt_usd(total_val)}</div>"
        f"<div class='card-sub nt'>{snaps} snapshot{'s' if snaps!=1 else ''} saved</div></div>"
        f"</div>"
    )

    # Detail rows
    rows = ""
    for pk in ["ALL","1D","1W","1M","3M","6M","YTD","1Y"]:
        pd = ph_pds.get(pk)
        if not pd:
            if pk in ("1W","1M","3M","6M","YTD","1Y"):
                need_map = {"1W":7,"1M":30,"3M":90,"6M":180,"YTD":None,"1Y":365}
                nd = need_map.get(pk, 30)
                rows += (f"<tr style='opacity:0.45'><td style='color:#9A9AB0'>{pk}</td>"
                         f"<td>--</td><td></td><td></td>"
                         f"<td colspan='2' style='color:#9A9AB0;font-size:10px'>"
                         f"Building ({snaps}/{nd if nd else '?'})</td></tr>")
            continue
        chg  = (pd.get("change") or 0); cpct = (pd.get("change_pct") or 0)
        pval = pd.get("start_value") or pd.get("past_value") or 0
        lbl  = pd.get("label", pk)
        col  = "#0F9D58" if chg >= 0 else "#DB4437"
        icon = "&#128248;" if pd.get("source")=="snapshot" else ("&#128176;" if pd.get("source")=="cost_basis" else "&#128197;")
        sc = "+" if chg >= 0 else ""; sp = "+" if cpct >= 0 else ""
        rows += (f"<tr>"
                 f"<td style='font-weight:700;color:#e0e0f0'>{lbl}</td>"
                 f"<td style='color:#9A9AB0'>{pd.get('start_date') or pd.get('date','')}</td>"
                 f"<td style='text-align:right;color:#9A9AB0'>{_fmt_usd(pval) if pval else '--'}</td>"
                 f"<td style='text-align:right;font-weight:700;color:{col}'>{sc}{_fmt_usd(chg)}</td>"
                 f"<td style='text-align:right;font-weight:700;color:{col}'>{sp}{cpct:.2f}%</td>"
                 f"<td style='color:#9A9AB0;font-size:10px'>{icon}</td></tr>")

    build_note = ""
    if building:
        nd_1w = max(0, 7 - snaps)
        build_note = (
            f"<div style='background:#1a1500;border:1px solid #F4B400;border-radius:8px;"
            f"padding:10px 14px;margin-top:12px;font-size:11px;color:#9A9AB0'>"
            f"<b style='color:#F4B400'>&#9203; Building history:</b> "
            f"{', '.join(building)} will appear automatically as snapshots accumulate. "
            f"Export Schwab CSVs to <code>data/portfolios/input/</code> each morning before 7AM. "
            f"{'1W unlocks in ' + str(nd_1w) + ' more day(s).' if nd_1w > 0 else ''}"
            f"</div>"
        )

    return (
        f"<div class='section-title'>&#128197; Period Returns</div>"
        f"{cards_html}"
        f"{build_note}"
        f"<div style='overflow-x:auto;margin-top:14px'>"
        f"<table><thead><tr style='font-size:10px;color:#9A9AB0'>"
        f"<th>Period</th><th>From Date</th>"
        f"<th style='text-align:right'>Value Then</th>"
        f"<th style='text-align:right'>Change $</th>"
        f"<th style='text-align:right'>Change %</th>"
        f"<th>Source</th></tr></thead>"
        f"<tbody style='font-size:12px'>{rows or '<tr><td colspan=6 class=nt style=padding:12px>No period data yet.</td></tr>'}</tbody>"
        f"</table></div>"
        f"<div style='margin-top:8px;font-size:10px;color:#9A9AB0'>"
        f"&#128248; = snapshot &nbsp;|&nbsp; &#128176; = cost basis &nbsp;|&nbsp; &#128197; = day change &nbsp;|&nbsp;"
        f" 1W=7d &middot; 1M=30d &middot; 3M=90d &middot; 6M=180d &middot; 1Y=365d</div>"
    )
def _build_technical_tab(technical: Dict) -> str:
    """📐 Technical Analysis tab — MA status, scores, support/resistance, stop gaps."""
    if not technical or not technical.get("positions"):
        return ("<div class='section-title'>📐 Technical Analysis</div>"
                "<div style='background:#1a1a35;border:1px solid #2a2a5e;border-radius:8px;padding:16px'>"
                "<span class='nt'>Run weekly pipeline to populate technical analysis.<br>"
                "Pulls SMA20/50/200, RSI, ATR, support/resistance from Finviz Elite.</span></div>")

    positions  = technical.get("positions", {})
    port_score = technical.get("portfolio_score", 50)
    port_grade = technical.get("portfolio_grade", "yellow")
    changes    = technical.get("signal_changes", [])
    critical   = technical.get("critical_signals", [])

    grade_col  = {"green":"#0F9D58","yellow":"#F4B400","red":"#DB4437"}.get(port_grade,"#F4B400")

    # Signal change alerts
    alert_html = ""
    if critical:
        for c in critical:
            alert_html += (f"<div style='background:#2a0000;border:1px solid #DB4437;border-radius:6px;"
                           f"padding:8px 12px;margin-bottom:6px;font-size:12px'>"
                           f"🚨 <b style='color:#DB4437'>{_e(c.get('type',''))}</b> — "
                           f"{_e(c.get('msg',''))}</div>")
    if changes and not critical:
        for c in changes[:5]:
            col = "#F4B400" if c.get("severity")=="HIGH" else "#9A9AB0"
            alert_html += (f"<div style='background:#1a1500;border:1px solid {col};border-radius:6px;"
                           f"padding:6px 12px;margin-bottom:4px;font-size:11px'>"
                           f"⚡ {_e(c.get('msg',''))}</div>")

    # Build traffic light table
    rows = ""
    for sym, d in sorted(positions.items(), key=lambda x: -(x[1].get("market_value",0))):
        mv     = d.get("market_value",0)
        price  = d.get("price",0)
        score  = d.get("tech_score",50)
        grade  = d.get("tech_grade","yellow")
        gc     = {"green":"#0F9D58","yellow":"#F4B400","red":"#DB4437"}.get(grade,"#F4B400")
        rsi    = d.get("rsi")
        rsi_st = d.get("rsi_status","neutral")
        cross  = d.get("cross","none")
        sma200 = d.get("sma200")
        above  = d.get("above_sma200")
        intent = d.get("intent","unclassified")
        sug_stop = d.get("suggested_stop")
        cur_stop = d.get("current_stop")
        stop_gap = d.get("stop_gap_pct")
        pct_high = d.get("pct_from_high")
        pct_low  = d.get("pct_from_low")

        # Cross badge
        cross_badge = ""
        if cross == "golden": cross_badge = "<span style='background:#0F9D5822;color:#0F9D58;padding:1px 5px;border-radius:3px;font-size:9px;margin-left:4px'>✨GC</span>"
        elif cross == "death": cross_badge = "<span style='background:#DB443722;color:#DB4437;padding:1px 5px;border-radius:3px;font-size:9px;margin-left:4px'>☠️DC</span>"

        # RSI badge
        rsi_col = "#9A9AB0"
        if rsi_st in ("overbought","overbought_extreme"): rsi_col = "#DB4437"
        elif rsi_st in ("oversold","oversold_extreme"):   rsi_col = "#0F9D58"
        rsi_str = f"{rsi:.0f}" if rsi else "—"

        # SMA200 status
        sma_str = f"${sma200:.0f}" if sma200 else "—"
        above_str = "▲ Above" if above else ("▼ Below" if above is False else "—")
        above_col = "#0F9D58" if above else ("#DB4437" if above is False else "#9A9AB0")

        # Stop gap
        gap_str = ""
        if stop_gap and stop_gap > 15:
            gap_str = f"<span style='color:#F4B400;font-size:9px'>⚠️{stop_gap:.0f}%gap</span>"

        _stop_cell = (f"<td style='font-size:11px;color:#9A9AB0'>${sug_stop:.2f} {gap_str}</td>"
                      if sug_stop else
                      f"<td style='font-size:11px;color:#3a3a5e'>— {gap_str}</td>")
        rows += (f"<tr>"
                 f"<td><b style='color:#e0e0f0'>{_e(sym)}</b>{cross_badge}</td>"
                 f"<td style='text-align:right;color:#9A9AB0'>${mv:,.0f}</td>"
                 f"<td style='text-align:right;color:#9A9AB0'>${price:.2f}</td>"
                 f"<td><span style='background:{gc}22;color:{gc};padding:2px 8px;"
                 f"border-radius:10px;font-size:10px;font-weight:700'>{score}</span></td>"
                 f"<td style='color:{above_col};font-size:11px'>{above_str}<br>"
                 f"<span style='color:#9A9AB0;font-size:9px'>{sma_str}</span></td>"
                 f"<td style='text-align:right;color:{rsi_col}'>{rsi_str}</td>"
                 f"<td style='text-align:right;color:#9A9AB0'>"
                 f"{f'{pct_high:.1f}%' if pct_high is not None else chr(8212)}</td>"
                 f"<td style='text-align:right;color:#9A9AB0'>"
                 f"{f'{pct_low:.1f}%' if pct_low is not None else chr(8212)}</td>"
                 + _stop_cell +
                 f"<td style='font-size:9px;color:#9A9AB0'>{_e(intent)}</td>"
                 f"</tr>")

    # Support/resistance quick table (top 8 positions by MV)
    sr_rows = ""
    top_pos = sorted(positions.items(), key=lambda x: -(x[1].get("market_value",0)))[:8]
    for sym, d in top_pos:
        price = d.get("price",0)
        sups  = d.get("supports",[])
        ress  = d.get("resistances",[])
        s1 = sups[0]["level"] if sups else None
        s2 = sups[1]["level"] if len(sups)>1 else None
        r1 = ress[0]["level"] if ress else None
        dist_s1 = round((price-s1)/price*100,1) if s1 and price else None
        dist_r1 = round((r1-price)/price*100,1) if r1 and price else None
        sr_rows += (f"<tr>"
                    f"<td><b style='color:#e0e0f0'>{_e(sym)}</b></td>"
                    f"<td style='text-align:right;color:#9A9AB0'>${price:.2f}</td>"
                    f"<td style='text-align:right;color:#0F9D58'>"
                    f"{'${:.2f}'.format(s1) if s1 else '—'}</td>"
                    f"<td style='text-align:right;color:#9A9AB0;font-size:10px'>"
                    f"{'{:.1f}%'.format(dist_s1) if dist_s1 else '—'}</td>"
                    f"<td style='text-align:right;color:#0F9D58'>"
                    f"{'${:.2f}'.format(s2) if s2 else '—'}</td>"
                    f"<td style='text-align:right;color:#DB4437'>"
                    f"{'${:.2f}'.format(r1) if r1 else '—'}</td>"
                    f"<td style='text-align:right;color:#9A9AB0;font-size:10px'>"
                    f"{'{:.1f}%'.format(dist_r1) if dist_r1 else '—'}</td>"
                    f"</tr>")

    last_updated = technical.get("last_updated","")

    return f"""
<div class='section-title'>📐 Technical Analysis
  <span style='font-size:10px;color:#9A9AB0;font-weight:400;margin-left:8px'>
    Updated: {_e(last_updated)}
  </span>
</div>

<!-- Portfolio Health Gauge — Row 1 -->
<div class='cards' style='margin-bottom:6px'>
  <div class='card' style='border-top:3px solid {grade_col};min-width:140px'>
    <div class='card-label'>Portfolio Tech Score</div>
    <div class='card-value' style='font-size:32px;color:{grade_col}'>{port_score:.0f}</div>
    <div class='card-sub' style='color:{grade_col}'>{port_grade.upper()}</div>
  </div>
  <div class='card'>
    <div class='card-label'>Positions Analyzed</div>
    <div class='card-value nt'>{len(positions)}</div>
    <div class='card-sub nt'>&#62;$1K market value</div>
  </div>
  <div class='card'>
    <div class='card-label'>Signal Changes</div>
    <div class='card-value {"dn" if critical else "nt"}'>{len(changes)}</div>
    <div class='card-sub dn'>{len(critical)} critical</div>
  </div>
</div>
<!-- Portfolio Health Gauge — Row 2 -->
<div class='cards' style='margin-bottom:12px'>
  <div class='card'>
    <div class='card-label'>Above SMA200</div>
    <div class='card-value up'>{sum(1 for d in positions.values() if d.get("above_sma200"))}</div>
    <div class='card-sub dn'>Below: {sum(1 for d in positions.values() if d.get("above_sma200")==False)}</div>
  </div>
  <div class='card'>
    <div class='card-label'>Overbought RSI&#62;70</div>
    <div class='card-value dn'>{sum(1 for d in positions.values() if (d.get("rsi") or 0)>70)}</div>
    <div class='card-sub nt'>Oversold &#60;30: {sum(1 for d in positions.values() if (d.get("rsi") or 50)<30)}</div>
  </div>
  <div class='card'>
    <div class='card-label'>Golden / Death Cross</div>
    <div class='card-value up'>{sum(1 for d in positions.values() if d.get("cross")=="golden")} <span style='color:#9A9AB0;font-size:14px'>/</span> <span class='dn'>{sum(1 for d in positions.values() if d.get("cross")=="death")}</span></div>
    <div class='card-sub nt'>Golden ↑ / Death ↓ crosses</div>
  </div>
</div>

{alert_html}

<!-- Traffic Light Table -->
<div class='section-title' style='font-size:11px;margin-bottom:6px'>🚦 Position Technical Status</div>
<div style='overflow-x:auto'>
<table>
  <thead><tr style='font-size:10px;color:#9A9AB0'>
    <th>Symbol</th>
    <th style='text-align:right'>Mkt Val</th>
    <th style='text-align:right'>Price</th>
    <th>Score</th>
    <th>vs SMA200</th>
    <th style='text-align:right'>RSI</th>
    <th style='text-align:right'>From High</th>
    <th style='text-align:right'>From Low</th>
    <th style='text-align:right'>Stop Suggest</th>
    <th>Intent</th>
  </tr></thead>
  <tbody style='font-size:11px'>{rows}</tbody>
</table>
</div>

<!-- Support/Resistance Table -->
<div class='section-title' style='font-size:11px;margin-top:18px;margin-bottom:6px'>
  🎯 Support &amp; Resistance — Top 8 Positions by Value
</div>
<table>
  <thead><tr style='font-size:10px;color:#9A9AB0'>
    <th>Symbol</th>
    <th style='text-align:right'>Price</th>
    <th style='text-align:right'>Support 1</th>
    <th style='text-align:right'>Distance</th>
    <th style='text-align:right'>Support 2</th>
    <th style='text-align:right'>Resistance</th>
    <th style='text-align:right'>Distance</th>
  </tr></thead>
  <tbody style='font-size:12px'>{sr_rows}</tbody>
</table>

<div style='margin-top:10px;font-size:10px;color:#9A9AB0'>
  Score: 70-100 = Green (bullish structure) · 40-69 = Yellow (neutral/watch) · 0-39 = Red (bearish/at risk)<br>
  Support levels derived from SMA200, SMA50, 52-week low. Resistance from SMA levels + 52-week high.
</div>"""


def _build_retirement_tab(retirement: Dict, tax_projection: Dict) -> str:
    """🎯 Retirement Roadmap tab — wealth timeline, Roth ladder, Golden Window."""
    if not retirement:
        return ("<div class='section-title'>🎯 Retirement Roadmap</div>"
                "<div style='background:#1a1a35;border:1px solid #2a2a5e;border-radius:8px;padding:16px'>"
                "<span class='nt'>Run pipeline to populate retirement roadmap.</span></div>")

    kd       = retirement.get("key_dates", {})
    accts    = retirement.get("accounts", {})
    loan     = retirement.get("loan", {})
    gw       = retirement.get("golden_window", {})
    income   = retirement.get("income_floor", {})
    timeline = retirement.get("timeline", [])
    roth_l   = retirement.get("roth_ladder", [])
    cur_age  = retirement.get("current_age", 58)

    days_golden = kd.get("days_to_golden", 0)
    yrs_golden  = kd.get("years_to_golden", 0)

    # Tax projection data
    tx = tax_projection.get("tax", {})
    roth_info = tax_projection.get("roth", {})

    # Wealth timeline SVG
    def _timeline_svg(timeline, w=700, h=200):
        if not timeline: return ""
        vals_b = [t.get("base",0) for t in timeline]
        vals_c = [t.get("conservative",0) for t in timeline]
        vals_a = [t.get("aggressive",0) for t in timeline]
        mn, mx = 0, max(vals_a) if vals_a else 1
        rng = mx or 1; pad = 40
        px = lambda i: pad + i/(len(vals_b)-1)*(w-pad*2)
        py = lambda v: h-pad - v/rng*(h-pad*2)

        def line(vals, col):
            pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i,v in enumerate(vals))
            return f"<polyline points='{pts}' fill='none' stroke='{col}' stroke-width='2' opacity='0.8'/>"

        # Milestone markers
        markers = ""
        for i, t in enumerate(timeline):
            if t.get("milestone"):
                x = px(i); y = py(vals_b[i])
                col = "#F4B400" if "Golden" in t["milestone"] else "#2979FF"
                markers += (f"<circle cx='{x:.1f}' cy='{y:.1f}' r='5' fill='{col}'/>"
                           f"<text x='{x:.1f}' y='{h-4}' fill='{col}' font-size='7' "
                           f"text-anchor='middle'>{t['age']}</text>")

        ylbls = ""
        for v in [0, mx//4, mx//2, mx*3//4, mx]:
            y = py(v)
            ylbls += f"<text x='2' y='{y:.0f}' fill='#9A9AB0' font-size='7'>${v/1e6:.1f}M</text>"

        return (f"<svg width='{w}' height='{h}' style='display:block'>"
                f"{line(vals_c,'#9A9AB0')}{line(vals_b,'#0F9D58')}{line(vals_a,'#2979FF')}"
                f"{markers}{ylbls}"
                f"<text x='{w-60}' y='14' fill='#2979FF' font-size='7'>Aggressive 9%</text>"
                f"<text x='{w-60}' y='24' fill='#0F9D58' font-size='7'>Base 7%</text>"
                f"<text x='{w-60}' y='34' fill='#9A9AB0' font-size='7'>Conservative 5%</text>"
                f"</svg>")

    # Roth ladder SVG
    def _roth_svg(ladder, w=500, h=150):
        if not ladder: return ""
        vals = [l.get("balance",0) for l in ladder]
        mx = max(vals) if vals else 1; pad = 30
        px = lambda i: pad + i/(len(vals)-1)*(w-pad*2)
        py = lambda v: h-pad - v/mx*(h-pad*2)
        pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i,v in enumerate(vals))
        fill = f"{px(0):.1f},{h-pad} {pts} {px(len(vals)-1):.1f},{h-pad}"
        # Golden window shading
        gw_shade = ""
        gw_items = [i for i,l in enumerate(ladder) if l.get("golden")]
        if gw_items:
            x1 = px(gw_items[0]); x2 = px(gw_items[-1])
            gw_shade = f"<rect x='{x1:.1f}' y='{pad}' width='{x2-x1:.1f}' height='{h-pad*2}' fill='#F4B40022'/>"
            gw_shade += f"<text x='{(x1+x2)/2:.1f}' y='{pad+12}' fill='#F4B400' font-size='7' text-anchor='middle'>Golden Window</text>"
        return (f"<svg width='{w}' height='{h}' style='display:block'>"
                f"{gw_shade}"
                f"<polygon points='{fill}' fill='#0F9D5822'/>"
                f"<polyline points='{pts}' fill='none' stroke='#0F9D58' stroke-width='2'/>"
                f"<text x='4' y='14' fill='#9A9AB0' font-size='7'>${mx/1e6:.2f}M</text>"
                f"</svg>")

    # Quarterly payment table
    qp = tax_projection.get("quarterly_payments", [])
    qp_rows = ""
    for q in qp:
        due     = q.get("due","")
        days    = q.get("days_until", 0)
        amount  = q.get("amount", 0)
        urgent  = 0 < days < 14
        due_col = "#DB4437" if urgent else ("#F4B400" if 0 < days < 30 else "#9A9AB0")
        past    = days < 0
        if past: continue
        qp_rows += (f"<tr>"
                    f"<td style='color:#e0e0f0'>{_e(q.get('period',''))}</td>"
                    f"<td>{_e(due)}</td>"
                    f"<td style='color:{due_col}'>{days}d</td>"
                    f"<td style='text-align:right;font-weight:700;color:#F4B400'>${amount:,.0f}</td>"
                    f"{'<td style=\"color:#DB4437\">⚠️ URGENT</td>' if urgent else '<td></td>'}"
                    f"</tr>")

    loan_urgent = loan.get("urgent", False)
    loan_col    = "#DB4437" if loan_urgent else "#F4B400"

    return f"""
<div class='section-title'>🎯 Retirement Roadmap</div>

<div class='cards' style='margin-bottom:6px'>
  <div class='card' style='border-top:3px solid #F4B400'>
    <div class='card-label'>Golden Window</div>
    <div class='card-value' style='color:#F4B400'>{yrs_golden:.1f} yrs</div>
    <div class='card-sub nt'>{days_golden:,} days · Age {gw.get("start_age",68.5)}</div>
  </div>
  <div class='card' style='border-top:3px solid #0F9D58'>
    <div class='card-label'>Current Roth Balance</div>
    <div class='card-value up'>${accts.get("roth",0):,.0f}</div>
    <div class='card-sub nt'>{accts.get("roth_pct",0):.1f}% of portfolio</div>
  </div>
  <div class='card'>
    <div class='card-label'>Traditional IRA/401k</div>
    <div class='card-value nt'>${accts.get("traditional",0):,.0f}</div>
    <div class='card-sub nt'>Target: $0 at age 73</div>
  </div>
</div>
<div class='cards' style='margin-bottom:12px'>
  <div class='card'>
    <div class='card-label'>Total Portfolio</div>
    <div class='card-value up'>${accts.get("total",0):,.0f}</div>
    <div class='card-sub nt'>Age {cur_age:.1f}</div>
  </div>
  <div class='card' style='border-top:3px solid #2979FF'>
    <div class='card-label'>Roth at Golden Window</div>
    <div class='card-value up'>${gw.get("projected_roth_at_start",0):,.0f}</div>
    <div class='card-sub nt'>Converting ${roth_info.get("optimal_annual",25000):,.0f}/yr now</div>
  </div>
  <div class='card' style='border-top:3px solid {"#DB4437" if loan_urgent else "#F4B400"}'>
    <div class='card-label'>401k Loan</div>
    <div class='card-value' style='color:{loan_col}'>${loan.get("balance",0):,.0f}</div>
    <div class='card-sub' style='color:{loan_col}'>{loan.get("days_remaining",0)}d to deadline</div>
  </div>
</div>

<!-- Wealth Timeline Chart -->
<div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px'>
  <div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:12px;grid-column:1/-1'>
    <div style='font-size:11px;color:#9A9AB0;margin-bottom:6px'>
      💹 Wealth Timeline (Ages {int(cur_age)}–80) — Colored dots = key milestones
    </div>
    {_timeline_svg(timeline)}
  </div>
  <div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:12px'>
    <div style='font-size:11px;color:#9A9AB0;margin-bottom:6px'>
      🌱 Roth Balance Projection — Yellow band = Golden Window (Ages 68.5–73)
    </div>
    {_roth_svg(roth_l)}
  </div>
  <div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:12px'>
    <div style='font-size:12px;font-weight:700;color:#7BB3FF;margin-bottom:10px'>
      🧾 Tax Projection — {retirement.get("as_of","2026")[:4]}
    </div>
    <table style='font-size:11px;width:100%'>
      {"".join(f'<tr><td class=\"nt\">{k}</td><td style=\"text-align:right;color:#e0e0f0\">{v}</td></tr>' for k,v in [
        ("Current Bracket",          tx.get("current_bracket","?")),
        ("Taxable Income",           f'${tx.get("taxable_income",0):,.0f}'),
        ("Federal Tax Est.",         f'${tx.get("federal_tax",0):,.0f}'),
        ("NY + NYC Est.",            f'${(tx.get("ny_state_est",0)+tx.get("nyc_est",0)):,.0f}'),
        ("Total Tax Est.",           f'${tx.get("total_est",0):,.0f}'),
        ("Effective Rate",           f'{tx.get("effective_rate",0):.1f}%'),
        ("YTD Conversions",          f'${tax_projection.get("income",{}).get("ytd_conversions",0):,.0f}'),
        ("Remaining Capacity",       f'${roth_info.get("remaining_capacity",0):,.0f}'),
        ("IRMAA Exposure",           f'${tax_projection.get("irmaa",{}).get("annual_surcharge",0):,.0f}/yr'),
      ])}
    </table>
  </div>
</div>

<!-- 401k Loan Alert -->
{f"""<div style='background:#2a1500;border:1px solid {loan_col};border-radius:8px;padding:12px;margin-bottom:12px'>
  <b style='color:{loan_col}'>⚠️ 401k Loan Payoff Required Before Rollover</b><br>
  <span style='font-size:12px;color:#e0e0f0'>
    Balance: ${loan.get("balance",0):,.0f} · Deadline: {kd.get("loan_deadline","")} · 
    Monthly needed: ${loan.get("monthly_to_payoff",0):,.0f} · 
    {loan.get("days_remaining",0)} days remaining
  </span>
</div>""" if loan.get("balance",0) > 0 else ""}

<!-- Income Floor -->
<div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px'>
  <div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:12px'>
    <div style='font-size:12px;font-weight:700;color:#7BB3FF;margin-bottom:10px'>
      💵 Income Floor at Age 68.5 (Disability Ends)
    </div>
    <table style='font-size:11px;width:100%'>
      {"".join(f'<tr><td class=\"nt\">{k}</td><td style=\"text-align:right;color:#e0e0f0\">{v}</td></tr>' for k,v in [
        ("Social Security/mo",  f'${income.get("ss_monthly",0):,.0f}'),
        ("Portfolio 4% SWR/mo", f'${income.get("portfolio_4pct",0):,.0f}'),
        ("SCHD Dividends/mo",   f'${income.get("schd_dividends",0):,.0f}'),
        ("Total Monthly",       f'${income.get("total_monthly",0):,.0f}'),
        ("vs Current Disability",f'${income.get("vs_current_disability",0):+,.0f}/mo'),
      ])}
    </table>
  </div>
  <div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:12px'>
    <div style='font-size:12px;font-weight:700;color:#7BB3FF;margin-bottom:10px'>
      📅 Quarterly Estimated Tax Payments
    </div>
    <table style='font-size:11px;width:100%'>
      <thead><tr style='color:#9A9AB0'><th>Period</th><th>Due</th><th>Days</th><th style='text-align:right'>Amount</th><th></th></tr></thead>
      <tbody>{qp_rows or "<tr><td colspan='5' class='nt'>All payments current</td></tr>"}</tbody>
    </table>
  </div>
</div>"""


def _build_config_tab_inline(portfolio: Dict) -> str:
    """⚙️ Config tab — load config_tab.py if available, fallback to inline."""
    try:
        from config_tab import build_config_tab
        from pathlib import Path as _Path
        root = _Path(__file__).parent.parent
        return build_config_tab(portfolio, root)
    except Exception as e:
        return (f"<div class='section-title'>⚙️ Configuration</div>"
                f"<div style='background:#1a1a35;border:1px solid #2a2a5e;border-radius:8px;padding:16px'>"
                f"<span class='nt'>config_tab.py: {e}</span></div>")


# ══════════════════════════════════════════════════════════════════════════════
# DIVIDEND CALENDAR TAB
# ══════════════════════════════════════════════════════════════════════════════
def _build_dividends_tab(div_cal: Dict) -> str:
    if not div_cal or not div_cal.get("has_data"):
        return ("<div class='section-title'>💰 Dividend Calendar</div>"
                "<div style='background:#1a1a35;border:1px solid #2a2a5e;border-radius:8px;padding:16px'>"
                "<span class='nt'>Run pipeline to populate dividend calendar.</span></div>")

    payers = div_cal.get("payers",[])
    total  = div_cal.get("total_annual",0)
    qual   = div_cal.get("qualified_annual",0)
    ord_   = div_cal.get("ordinary_annual",0)
    monthly= div_cal.get("monthly_average",0)
    alerts = div_cal.get("ex_div_alerts",[])
    months = div_cal.get("monthly_summary",[])
    drip   = div_cal.get("drip_analysis",{})
    safety = div_cal.get("safety_summary",{})

    # Alert badges
    alert_html = ""
    for a in alerts:
        col  = "#DB4437" if a.get("urgent") else "#F4B400"
        days = a.get("days_until",0)
        alert_html += (f"<div style='background:#1a1500;border:1px solid {col};border-radius:6px;"
                       f"padding:8px 12px;margin-bottom:6px;display:flex;justify-content:space-between'>"
                       f"<span><b style='color:{col}'>{_e(a.get('symbol',''))}</b> goes ex-div "
                       f"<b>{_e(a.get('ex_date',''))}</b> — <b style='color:#e0e0f0'>{days} days</b></span>"
                       f"<span style='color:#0F9D58'>${a.get('total_income',0):,.2f} captured if holding</span>"
                       f"</div>")

    # Monthly calendar bar chart (SVG)
    max_m = max((m.get("total",0) or 0 for m in months),default=1) or 1
    bar_w = 38; bar_gap = 6
    svg_w = (bar_w+bar_gap)*12+40; svg_h = 120
    bars = ""
    for i,m in enumerate(months):
        x    = 20 + i*(bar_w+bar_gap)
        h_   = max(4, int(m["total"]/max_m*80))
        y    = 90 - h_
        col  = "#0F9D58" if (m.get("total",0) or 0)>(monthly or 0) else "#2979FF"
        bars += (f"<rect x='{x}' y='{y}' width='{bar_w}' height='{h_}' fill='{col}' rx='3'/>"
                 f"<text x='{x+bar_w//2}' y='107' fill='#9A9AB0' font-size='8' text-anchor='middle'>"
                 f"{_e(m['month_name'])}</text>"
                 f"<text x='{x+bar_w//2}' y='{y-2}' fill='#e0e0f0' font-size='7' text-anchor='middle'>"
                 f"${m['total']:,.0f}</text>")
    cal_svg = (f"<svg width='{svg_w}' height='{svg_h}' style='display:block'>"
               f"<line x1='18' y1='90' x2='{svg_w-10}' y2='90' stroke='#3a3a5e' stroke-width='1'/>"
               f"{bars}</svg>")

    # Payer table rows
    payer_rows = ""
    for p in payers:
        sym  = p.get("symbol",""); mv = p.get("market_value",0)
        yi   = p.get("yield_pct",0); ann = p.get("annual_income",0)
        freq = p.get("frequency",""); qual_flag = "✓" if p.get("qualified") else "·"
        saf  = p.get("safety",""); saf_col = "#0F9D58" if saf=="strong" else "#F4B400"
        payer_rows += (f"<tr><td><b style='color:#e0e0f0'>{_e(sym)}</b></td>"
                       f"<td style='text-align:right;color:#9A9AB0'>${mv:,.0f}</td>"
                       f"<td style='text-align:right;color:#0F9D58'>{yi:.2f}%</td>"
                       f"<td style='text-align:right;font-weight:700;color:#0F9D58'>${ann:,.0f}</td>"
                       f"<td style='text-align:right;color:#9A9AB0'>${ann/12:,.0f}</td>"
                       f"<td style='color:#9A9AB0'>{freq}</td>"
                       f"<td style='color:#9A9AB0'>{qual_flag}</td>"
                       f"<td style='color:{saf_col};font-size:10px'>{saf}</td></tr>")

    return f"""
<div class='section-title'>💰 Dividend Income Calendar</div>
<div class='cards' style='margin-bottom:10px'>
  <div class='card' style='border-top:3px solid #0F9D58'>
    <div class='card-label'>Annual Income</div>
    <div class='card-value up'>${total:,.0f}</div>
    <div class='card-sub nt'>${monthly:,.0f}/mo average</div>
  </div>
  <div class='card'><div class='card-label'>Qualified (15% tax)</div>
    <div class='card-value up'>${qual:,.0f}</div>
    <div class='card-sub nt'>{qual/total*100:.0f}% of income</div>
  </div>
  <div class='card'><div class='card-label'>Ordinary (income rate)</div>
    <div class='card-value {"dn" if ord_>qual else "nt"}'>${ord_:,.0f}</div>
    <div class='card-sub nt'>BDCs/bonds taxed as income</div>
  </div>
  <div class='card'><div class='card-label'>Payers</div>
    <div class='card-value nt'>{len(payers)}</div>
    <div class='card-sub nt'>
      ✅ Safe: {len(safety.get("strong",[]))} · ⚠️ Watch: {len(safety.get("watch",[]))}
    </div>
  </div>
</div>

{f"<div class='section-title' style='font-size:11px;color:#F4B400'>⚠️ Ex-Dividend Alerts</div>{alert_html}" if alerts else ""}

<div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:12px;margin-bottom:12px'>
  <div style='font-size:11px;color:#9A9AB0;margin-bottom:6px'>
    📅 Monthly Income Distribution — Blue line = average ${monthly:,.0f}/mo
  </div>
  {cal_svg}
</div>

<table style='margin-bottom:14px'>
  <thead><tr style='font-size:10px;color:#9A9AB0'>
    <th>Symbol</th><th style='text-align:right'>Mkt Val</th>
    <th style='text-align:right'>Yield</th><th style='text-align:right'>Annual $</th>
    <th style='text-align:right'>Monthly $</th><th>Frequency</th>
    <th>Qual</th><th>Safety</th>
  </tr></thead>
  <tbody style='font-size:11px'>{payer_rows}</tbody>
</table>

{f"""<div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:12px'>
  <div style='font-size:12px;font-weight:700;color:#7BB3FF;margin-bottom:8px'>
    🌱 SCHD DRIP Analysis — Should You Reinvest Dividends?
  </div>
  <div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;font-size:12px'>
    <div><span class='nt'>Current Annual Income</span><br><b style='color:#0F9D58'>${drip.get("current_income",0):,.0f}</b></div>
    <div><span class='nt'>10-Yr Value (DRIP)</span><br><b style='color:#0F9D58'>${drip.get("10yr_drip_value",0):,.0f}</b></div>
    <div><span class='nt'>10-Yr Value (Cash)</span><br><b style='color:#9A9AB0'>${drip.get("10yr_cash_value",0):,.0f}</b></div>
    <div style='grid-column:1/-1'><span class='nt'>DRIP Advantage:</span> <b style='color:#F4B400'>${drip.get("drip_advantage",0):,.0f} more over 10 years</b></div>
    <div style='grid-column:1/-1;font-size:11px;color:#9A9AB0'>{_e(drip.get("recommendation",""))}</div>
  </div>
</div>""" if drip else ""}
"""


# ══════════════════════════════════════════════════════════════════════════════
# ATTRIBUTION TAB
# ══════════════════════════════════════════════════════════════════════════════
def _build_attribution_tab(attribution: Dict, perf_history: Dict) -> str:
    if not attribution or not attribution.get("has_data"):
        return ("<div class='section-title'>📊 Performance Attribution</div>"
                "<div style='background:#1a1a35;border:1px solid #2a2a5e;border-radius:8px;padding:16px'>"
                "<span class='nt'>Run monthly pipeline to compute attribution vs benchmark.</span></div>")

    bench_lbl = attribution.get("benchmark_label","55% SPY / 20% ITA / 25% AGG")
    alpha     = attribution.get("alpha_annualized")
    port_cagr = attribution.get("port_cagr")
    bench_cagr= attribution.get("bench_cagr")
    inc_ret   = attribution.get("inception_return")
    bench_3yr = attribution.get("bench_3yr_return")
    p_sharpe  = attribution.get("port_sharpe")
    b_sharpe  = attribution.get("bench_sharpe")
    p_sort    = attribution.get("port_sortino")
    b_sort    = attribution.get("bench_sortino")
    p_dd      = attribution.get("port_maxdd")
    b_dd      = attribution.get("bench_maxdd")
    gainers   = attribution.get("top_gainers",[])
    losers    = attribution.get("top_losers",[])
    note      = attribution.get("note","")
    snap_cnt  = attribution.get("snapshot_count",0)
    rolling   = attribution.get("rolling_alpha",[])

    def _metric(label, port_v, bench_v, higher_better=True, suffix="", fmt=".2f"):
        if port_v is None:
            return f"<div style='display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #1a1a35'><span class='nt'>{label}</span><span style='color:#9A9AB0;font-size:11px'>Need 30+ snapshots</span></div>"
        if bench_v is None:
            is_better = False
        else:
            is_better = (port_v > bench_v) if higher_better else (port_v < bench_v)
        pc = "#0F9D58" if is_better else "#DB4437"; bc = "#9A9AB0"
        pv_str = f"{port_v:{fmt}}{suffix}"; bv_str = f"{bench_v:{fmt}}{suffix}" if bench_v is not None else "—"
        edge = "▲" if is_better else "▼"
        return (f"<div style='display:flex;justify-content:space-between;align-items:center;"
                f"padding:5px 0;border-bottom:1px solid #1a1a35'>"
                f"<span class='nt'>{label}</span>"
                f"<span><b style='color:{pc}'>{pv_str}</b>"
                f" <span style='color:#3a3a5e;font-size:10px'>vs</span>"
                f" <span style='color:{bc}'>{bv_str}</span>"
                f" <span style='color:{pc};font-size:10px'>{edge}</span></span></div>")

    # Rolling alpha mini-SVG
    rolling_svg = ""
    if rolling:
        alphas = [d.get("alpha",0) for d in rolling]
        mn_a,mx_a = min(alphas),max(alphas); rng_a = mx_a-mn_a or 1
        pad=20; w=500; h=80
        px = lambda i: pad+i/(len(alphas)-1)*(w-pad*2)
        py = lambda v: h-pad-(v-mn_a)/rng_a*(h-pad*2)
        pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i,v in enumerate(alphas))
        y0  = py(0)
        colors = [("green" if v >= 0 else "red") for v in alphas]
        dots  = "".join(f"<circle cx='{px(i):.1f}' cy='{py(v):.1f}' r='3' fill='{'#0F9D58' if v>=0 else '#DB4437'}'/>" for i,v in enumerate(alphas))
        rolling_svg = (f"<svg width='{w}' height='{h}' style='display:block;background:#0d0d1a'>"
                       f"<line x1='{pad}' y1='{y0:.1f}' x2='{w-pad}' y2='{y0:.1f}' stroke='#3a3a5e' stroke-dasharray='3,2'/>"
                       f"<polyline points='{pts}' fill='none' stroke='#2979FF' stroke-width='1.5'/>"
                       f"{dots}"
                       f"<text x='4' y='14' fill='#9A9AB0' font-size='7'>{mx_a:+.1f}%</text>"
                       f"<text x='4' y='{h-4}' fill='#9A9AB0' font-size='7'>{mn_a:+.1f}%</text>"
                       f"</svg>")

    alpha_col = "#0F9D58" if alpha and alpha > 0 else "#DB4437" if alpha and alpha < 0 else "#9A9AB0"
    alpha_str = f"{alpha:+.2f}%" if alpha is not None else "N/A"

    return f"""
<div class='section-title'>📊 Performance Attribution vs {_e(bench_lbl)}</div>
{f"<div style='font-size:11px;color:#9A9AB0;margin-bottom:10px'>{_e(note)}</div>" if note else ""}

<div class='cards' style='margin-bottom:12px'>
  <div class='card' style='border-top:3px solid {alpha_col}'>
    <div class='card-label'>Alpha (Annualized)</div>
    <div class='card-value' style='color:{alpha_col}'>{alpha_str}</div>
    <div class='card-sub nt'>vs blended benchmark</div>
  </div>
  <div class='card'>
    <div class='card-label'>All-Time Return</div>
    <div class='card-value {"up" if inc_ret and inc_ret>0 else "nt"}'>{f"+{inc_ret:.1f}%" if inc_ret else "N/A"}</div>
    <div class='card-sub nt'>Benchmark 3yr: {f"+{bench_3yr:.1f}%" if bench_3yr else "N/A"}</div>
  </div>
  <div class='card'>
    <div class='card-label'>Portfolio CAGR</div>
    <div class='card-value {"up" if port_cagr and port_cagr>0 else "nt"}'>{f"+{port_cagr:.1f}%/yr" if port_cagr else f"{snap_cnt} snapshots"}</div>
    <div class='card-sub nt'>Benchmark: {f"+{bench_cagr:.1f}%/yr" if bench_cagr else "—"}</div>
  </div>
  <div class='card'>
    <div class='card-label'>Sharpe Ratio</div>
    <div class='card-value {"up" if p_sharpe and b_sharpe and p_sharpe>b_sharpe else "nt"}'>{f"{p_sharpe:.2f}" if p_sharpe else f"Need {30-snap_cnt}+ more"}</div>
    <div class='card-sub nt'>Benchmark: {f"{b_sharpe:.2f}" if b_sharpe else "—"}</div>
  </div>
</div>

<div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px'>
  <div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:12px'>
    <div style='font-size:11px;color:#9A9AB0;margin-bottom:8px'>📈 Risk-Adjusted Metrics</div>
    {_metric("Sharpe Ratio", p_sharpe, b_sharpe, True)}
    {_metric("Sortino Ratio", p_sort, b_sort, True)}
    {_metric("Max Drawdown", p_dd, b_dd, False, "%", ".1f")}
    {_metric("CAGR", port_cagr, bench_cagr, True, "%", ".1f")}
  </div>
  <div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:12px'>
    <div style='font-size:11px;color:#9A9AB0;margin-bottom:8px'>🏆 Attribution</div>
    {"".join(f"<div style='display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #1a1a35'><b style='color:#e0e0f0'>{_e(g.get('symbol',''))}</b><span style='color:#0F9D58'>+${g.get('gain',0):,.0f}</span></div>" for g in gainers[:4])}
    {"".join(f"<div style='display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #1a1a35'><b style='color:#e0e0f0'>{_e(l.get('symbol',''))}</b><span style='color:#DB4437'>${l.get('loss',0):,.0f}</span></div>" for l in losers[:3])}
  </div>
</div>

{f"""<div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:12px'>
  <div style='font-size:11px;color:#9A9AB0;margin-bottom:6px'>📐 Rolling 90-Day Alpha vs Benchmark</div>
  {rolling_svg}
  <div style='font-size:10px;color:#9A9AB0;margin-top:4px'>Green dots = outperforming benchmark | Red = underperforming</div>
</div>""" if rolling else ""}
<div style='margin-top:12px;font-size:10px;color:#9A9AB0'>
  Benchmark: {_e(bench_lbl)}. Reflects your investment thesis (defense overweight + US large cap + bonds).
  Sharpe/Sortino require 30+ daily snapshots. Export Schwab CSVs daily before 7AM to build history.
</div>"""


# ══════════════════════════════════════════════════════════════════════════════
# CORRELATION TAB
# ══════════════════════════════════════════════════════════════════════════════
def _build_correlation_tab(corr: Dict) -> str:
    if not corr or not corr.get("has_data"):
        return ("<div class='section-title'>🔗 Correlation & Factor Analysis</div>"
                "<div style='background:#1a1a35;border:1px solid #2a2a5e;border-radius:8px;padding:16px'>"
                "<span class='nt'>Run monthly pipeline to compute correlation matrix.</span></div>")

    sectors    = corr.get("sector_exposure",{})
    geo        = corr.get("geographic",{})
    rate_score = corr.get("rate_sensitivity",0)
    rate_interp= corr.get("rate_interpretation","")
    defense_pct= corr.get("defense_cluster_pct",0)
    v_pct      = corr.get("v_concentration_pct",0)
    high_corr  = corr.get("high_correlations",[])
    matrix     = corr.get("correlation_matrix",{})
    syms       = corr.get("symbols_analyzed",[])

    # Correlation matrix SVG
    def _matrix_svg(matrix, syms, cell=34):
        if not matrix or not syms: return ""
        n = len(syms); w = n*cell+60; h = n*cell+60
        cells = ""
        for i,s1 in enumerate(syms):
            # Row label
            cells += f"<text x='2' y='{i*cell+cell//2+54}' fill='#9A9AB0' font-size='7' dominant-baseline='middle'>{_e(s1[:6])}</text>"
            # Col label
            cells += f"<text x='{i*cell+34+cell//2}' y='14' fill='#9A9AB0' font-size='7' text-anchor='middle'>{_e(s1[:4])}</text>"
            for j,s2 in enumerate(syms):
                c = (matrix.get(s1) or {}).get(s2)
                if c is None:
                    col = "#1a1a35"; txt = "?"
                else:
                    c = float(c)
                    if c >= 0.85:    col="#DB443788"; txt=f"{c:.2f}"
                    elif c >= 0.70:  col="#F4B40066"; txt=f"{c:.2f}"
                    elif c >= 0.40:  col="#2979FF33"; txt=f"{c:.2f}"
                    elif c >= 0:     col="#0d0d1a";   txt=f"{c:.2f}"
                    else:            col="#0F9D5833"; txt=f"{c:.2f}"
                x = i*cell+34; y = j*cell+20
                cells += (f"<rect x='{x}' y='{y}' width='{cell-1}' height='{cell-1}' fill='{col}' rx='2'/>"
                          f"<text x='{x+cell//2-1}' y='{y+cell//2}' fill='#e0e0f0' font-size='6' "
                          f"text-anchor='middle' dominant-baseline='middle'>{txt}</text>")
        return f"<svg width='{w}' height='{h}' style='display:block;background:#0d0d1a'>{cells}</svg>"

    sector_rows = "".join(
        f"<tr><td style='color:#e0e0f0'>{_e(k)}</td>"
        f"<td style='text-align:right;color:#9A9AB0'>{v:.1f}%</td>"
        f"<td><div style='height:8px;background:#2979FF;width:{min(v,100):.0f}%;border-radius:4px'></div></td></tr>"
        for k,v in sectors.items()
    )
    high_rows = "".join(
        f"<tr><td><b style='color:#e0e0f0'>{_e(c['s1'])}</b></td>"
        f"<td><b style='color:#e0e0f0'>{_e(c['s2'])}</b></td>"
        f"<td style='text-align:right;color:{'#DB4437' if abs(c['corr'])>=0.85 else '#F4B400'};font-weight:700'>{c['corr']:.3f}</td>"
        f"<td style='color:#9A9AB0;font-size:10px'>{c['type']}</td></tr>"
        for c in high_corr[:8]
    )

    rate_col = "#DB4437" if rate_score < -0.3 else "#0F9D58" if rate_score > 0.3 else "#9A9AB0"

    return f"""
<div class='section-title'>🔗 Correlation & Factor Exposure</div>
<div class='cards' style='margin-bottom:12px'>
  <div class='card' style='border-top:3px solid {"#DB4437" if v_pct>20 else "#F4B400"}'>
    <div class='card-label'>V Concentration</div>
    <div class='card-value {"dn" if v_pct>20 else "nt"}'>{v_pct:.1f}%</div>
    <div class='card-sub nt'>Target: ≤15% post-rebalance</div>
  </div>
  <div class='card'>
    <div class='card-label'>Defense Cluster</div>
    <div class='card-value nt'>{defense_pct:.1f}%</div>
    <div class='card-sub nt'>LMT+NOC+RTX+KTOS+etc</div>
  </div>
  <div class='card' style='border-top:3px solid {rate_col}'>
    <div class='card-label'>Rate Sensitivity</div>
    <div class='card-value' style='color:{rate_col}'>{rate_score:+.2f}</div>
    <div class='card-sub nt'>-2=very sensitive, +2=benefits</div>
  </div>
  <div class='card'>
    <div class='card-label'>High Correlations</div>
    <div class='card-value {"dn" if len(high_corr)>5 else "nt"}'>{len(high_corr)}</div>
    <div class='card-sub nt'>Pairs with corr ≥ 0.70</div>
  </div>
  <div class='card'>
    <div class='card-label'>US Exposure</div>
    <div class='card-value nt'>{geo.get("US",0):.0f}%</div>
    <div class='card-sub nt'>Intl: {geo.get("International",0):.0f}%</div>
  </div>
</div>

<div style='font-size:11px;color:{rate_col};margin-bottom:12px;padding:8px 12px;background:#1a1a35;border-radius:6px'>
  ⚡ Rate Sensitivity: <b>{_e(rate_interp)}</b>
</div>

<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:14px'>
  <div>
    <div class='section-title' style='font-size:11px'>🏭 Sector Exposure</div>
    <table style='font-size:11px'>{sector_rows}</table>
  </div>
  <div>
    <div class='section-title' style='font-size:11px'>⚠️ High Correlations</div>
    <table>
      <thead><tr style='font-size:10px;color:#9A9AB0'><th>Sym 1</th><th>Sym 2</th><th style='text-align:right'>Corr</th><th>Level</th></tr></thead>
      <tbody style='font-size:11px'>{high_rows or "<tr><td colspan='4' class='nt'>No high correlations</td></tr>"}</tbody>
    </table>
  </div>
  <div>
    <div class='section-title' style='font-size:11px'>🌍 Geographic</div>
    {"".join(f"<div style='display:flex;justify-content:space-between;padding:4px 0;font-size:12px'><span class='nt'>{_e(k)}</span><b style='color:#e0e0f0'>{v:.1f}%</b></div>" for k,v in geo.items())}
  </div>
</div>

<div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:12px'>
  <div style='font-size:11px;color:#9A9AB0;margin-bottom:8px'>
    🔢 Correlation Matrix — Top positions (6-month daily returns)
    <span style='float:right;font-size:9px'>
      🔴 High (≥0.85) · 🟡 Moderate (≥0.70) · 🔵 Low · 🟢 Negative
    </span>
  </div>
  {_matrix_svg(matrix, syms[:10])}
</div>"""


# ══════════════════════════════════════════════════════════════════════════════
# WATCHLIST TAB
# ══════════════════════════════════════════════════════════════════════════════
def _build_watchlist_tab(wl_data: Dict) -> str:
    if not wl_data or not wl_data.get("has_data"):
        return ("<div class='section-title'>👁️ Watchlist Intelligence</div>"
                "<div style='background:#1a1a35;border:1px solid #2a2a5e;border-radius:8px;padding:16px'>"
                "<span class='nt'>Run pipeline to populate watchlist.</span></div>")

    wl      = wl_data.get("watchlist",[])
    opps    = wl_data.get("sizing_opportunities",[])
    v_pct   = wl_data.get("v_concentration_pct",0)
    def_pct = wl_data.get("defense_pct",0)

    opp_html = "".join(
        f"<div style='background:{'#2a0a00' if 'Required' in o['type'] else '#1a1500'};"
        f"border:1px solid {'#DB4437' if 'Required' in o['type'] else '#F4B400'};"
        f"border-radius:6px;padding:10px 14px;margin-bottom:8px'>"
        f"<b style='color:{'#DB4437' if 'Required' in o['type'] else '#F4B400'}'>"
        f"{'🚨' if 'Required' in o['type'] else '⚠️'} {_e(o['type'])}</b><br>"
        f"<span style='font-size:12px;color:#e0e0f0'>{_e(o['message'])}</span><br>"
        f"<span style='font-size:11px;color:#9A9AB0'>→ {_e(o['action'])}</span></div>"
        for o in opps
    )

    wl_rows = ""
    for item in wl:
        sym       = item.get("symbol","")
        holds     = item.get("currently_hold",False)
        score     = item.get("tech_score")
        rsi       = item.get("rsi")
        pct_high  = item.get("pct_from_high")
        intent    = item.get("target_intent","")
        INTENT_COLORS = {"long_term_hold":"#0F9D58","growth_speculative":"#FF6D00",
                         "income":"#F4B400","etf_broad":"#9A9AB0","covered_call_candidate":"#2979FF"}
        ic = INTENT_COLORS.get(intent,"#9A9AB0")
        hold_badge = ("<span style='background:#0F9D5822;color:#0F9D58;padding:1px 5px;"
                      "border-radius:3px;font-size:9px'>✓ Holding</span>" if holds else "")
        score_str = f"{score}" if score else "—"
        rsi_str   = f"{rsi:.0f}" if rsi else "—"
        rsi_col   = "#DB4437" if rsi and rsi>70 else "#0F9D58" if rsi and rsi<30 else "#9A9AB0"
        high_str  = f"{pct_high:.1f}%" if pct_high is not None else "—"
        wl_rows += (f"<tr>"
                    f"<td><b style='color:#e0e0f0'>{_e(sym)}</b> {hold_badge}</td>"
                    f"<td style='max-width:280px;font-size:10px;color:#9A9AB0'>{_e(item.get('thesis','')[:60])}</td>"
                    f"<td><span style='background:{ic}22;color:{ic};padding:1px 5px;"
                    f"border-radius:3px;font-size:9px'>{_e(intent.replace('_',' '))}</span></td>"
                    f"<td style='text-align:right;color:#9A9AB0'>{score_str}</td>"
                    f"<td style='text-align:right;color:{rsi_col}'>{rsi_str}</td>"
                    f"<td style='text-align:right;color:#9A9AB0'>{high_str}</td>"
                    f"</tr>")

    return f"""
<div class='section-title'>👁️ Watchlist Intelligence & Buy Pipeline</div>
{opp_html}
<table>
  <thead><tr style='font-size:10px;color:#9A9AB0'>
    <th>Symbol</th><th>Thesis</th><th>Intent</th>
    <th style='text-align:right'>Score</th>
    <th style='text-align:right'>RSI</th>
    <th style='text-align:right'>From High</th>
  </tr></thead>
  <tbody style='font-size:11px'>{wl_rows}</tbody>
</table>
<div style='margin-top:10px;font-size:10px;color:#9A9AB0'>
  Add/remove tickers by editing <code>data/portfolios/state/watchlist.json</code>.
  Technical data populates weekly after the Sunday scan.
</div>"""
