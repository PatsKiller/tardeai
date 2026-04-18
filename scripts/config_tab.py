"""config_tab.py — Portfolio Intent Config Editor Tab (dashboard UI)
Editable via proxy /api/intent endpoint. No manual YAML editing needed.
"""
from __future__ import annotations
import html as _html, json as _json, yaml
from pathlib import Path
from typing import Dict, List

def _e(s): return _html.escape(str(s)) if s else ""

INTENT_LABELS = {
    "covered_call_candidate": ("📈","Covered Call Candidate","SMA200 stop + monthly calls"),
    "long_term_hold":         ("💎","Long-Term Hold","SMA200 − 1×ATR stop"),
    "growth_speculative":     ("🚀","Growth / Speculative","SMA50 − 0.5×ATR stop"),
    "income":                 ("💰","Income / Yield","SMA50 − 1×ATR stop"),
    "etf_broad":              ("🏦","Broad ETF","SMA200 wide stop"),
    "day_trade":              ("⚡","Day Trade","SMA20 or 8% trail"),
    "unclassified":           ("❓","Unclassified","SMA50 default"),
}


def _build_opts(cur_intent):
    parts = []
    for k, lbl in INTENT_LABELS.items():
        sel = " selected" if k == cur_intent else ""
        parts.append(f"<option value='{k}'{sel}>{lbl[0]} {lbl[1]}</option>")
    return "".join(parts)

def build_config_tab(portfolio: Dict, root: Path) -> str:
    # Load current intent map
    intent_file = root / "assets" / "portfolio_intent.yaml"
    intent_cfg  = {}
    intent_map  = {}
    if intent_file.exists():
        try:
            intent_cfg = yaml.safe_load(intent_file.read_text()) or {}
            skip = {"covered_call_settings","stop_settings","benchmark","fidelity_funds"}
            for cat, tickers in intent_cfg.items():
                if cat in skip or not isinstance(tickers, list): continue
                for t in tickers:
                    intent_map[str(t).upper()] = cat
        except Exception as e:
            pass

    # Get all non-trivial holdings
    holdings = [h for h in portfolio.get("holdings",[])
                if h.get("market_value",0) >= 500 and not h.get("is_loan")
                and not h.get("is_cash")]

    # Build intent options
    intent_opts = "".join(
        f"<option value='{k}'>{lbl[0]} {lbl[1]}</option>"
        for k, lbl in INTENT_LABELS.items()
    )

    # Build table rows
    rows = ""
    for h in sorted(holdings, key=lambda x: -x.get("market_value",0)):
        sym   = h.get("symbol","").upper()
        mv    = h.get("market_value",0)
        price = h.get("price",0)
        cur_intent = intent_map.get(sym, "unclassified")
        icon, label, tip = INTENT_LABELS.get(cur_intent, ("❓","Unclassified",""))
        badge_col = {
            "covered_call_candidate":"#2979FF",
            "long_term_hold":"#0F9D58",
            "growth_speculative":"#FF6D00",
            "income":"#F4B400",
            "etf_broad":"#9A9AB0",
            "day_trade":"#DB4437",
            "unclassified":"#3a3a5e",
        }.get(cur_intent,"#3a3a5e")

        # Covered call eligible?
        shares = h.get("shares",0) or 0
        cc_badge = ""
        if shares >= 100:
            cc_badge = "<span style='background:#2979FF22;color:#2979FF;padding:1px 5px;border-radius:3px;font-size:9px;margin-left:4px'>CC eligible</span>"

        rows += f"""<tr id='row-{sym}'>
          <td><b style='color:#e0e0f0'>{_e(sym)}</b>{cc_badge}</td>
          <td style='text-align:right;color:#9A9AB0'>${mv:,.0f}</td>
          <td style='text-align:right;color:#9A9AB0'>{shares:.0f}</td>
          <td style='text-align:right;color:#9A9AB0'>${price:.2f}</td>
          <td>
            <select id='intent-{sym}' onchange='saveIntent("{sym}",this.value)'
              style='background:#1a1a35;border:1px solid #3a3a5e;color:#e0e0f0;padding:3px 6px;border-radius:4px;font-size:11px;width:100%'>
              {_build_opts(cur_intent)}
            </select>
          </td>
          <td style='font-size:10px;color:#9A9AB0;padding-left:6px'>{_e(tip)}</td>
          <td><span id='status-{sym}' style='font-size:10px;color:#9A9AB0'></span></td>
        </tr>"""

    # CC settings display
    cc_cfg = intent_cfg.get("covered_call_settings",{})
    bench  = intent_cfg.get("benchmark",{})

    return f"""
<div class='section-title'>⚙️ Portfolio Configuration</div>

<div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px'>
  <!-- Covered Call Settings -->
  <div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:12px'>
    <div style='font-size:12px;font-weight:700;color:#7BB3FF;margin-bottom:8px'>📈 Covered Call Settings</div>
    <table style='font-size:11px;width:100%'>
      <tr><td class='nt'>Default DTE (days)</td><td style='text-align:right;color:#e0e0f0'>{cc_cfg.get('default_dte_days',30)}</td></tr>
      <tr><td class='nt'>Default OTM %</td><td style='text-align:right;color:#e0e0f0'>{cc_cfg.get('default_otm_pct',0.06)*100:.0f}%</td></tr>
      <tr><td class='nt'>Min OTM %</td><td style='text-align:right;color:#e0e0f0'>{cc_cfg.get('min_otm_pct',0.04)*100:.0f}%</td></tr>
      <tr><td class='nt'>Max OTM %</td><td style='text-align:right;color:#e0e0f0'>{cc_cfg.get('max_otm_pct',0.10)*100:.0f}%</td></tr>
      <tr><td class='nt'>Earnings Blackout</td><td style='text-align:right;color:#e0e0f0'>{cc_cfg.get('earnings_blackout_days',14)}d</td></tr>
      <tr><td class='nt'>Min Shares / Contract</td><td style='text-align:right;color:#e0e0f0'>{cc_cfg.get('min_shares_for_call',100)}</td></tr>
    </table>
    <div style='margin-top:8px;font-size:10px;color:#9A9AB0'>Edit <code>assets/portfolio_intent.yaml</code> to change settings</div>
  </div>
  <!-- Benchmark Settings -->
  <div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:12px'>
    <div style='font-size:12px;font-weight:700;color:#7BB3FF;margin-bottom:8px'>📊 Benchmark (Performance Attribution)</div>
    <table style='font-size:11px;width:100%'>
      <tr><td class='nt'>SPY (US Large Cap)</td><td style='text-align:right;color:#e0e0f0'>{bench.get('spy_weight',0.55)*100:.0f}%</td></tr>
      <tr><td class='nt'>ITA (US Defense ETF)</td><td style='text-align:right;color:#e0e0f0'>{bench.get('ita_weight',0.20)*100:.0f}%</td></tr>
      <tr><td class='nt'>AGG (US Bond ETF)</td><td style='text-align:right;color:#e0e0f0'>{bench.get('agg_weight',0.25)*100:.0f}%</td></tr>
    </table>
    <div style='margin-top:8px;font-size:10px;color:#9A9AB0'>Blended benchmark reflects your actual investment thesis</div>
  </div>
</div>

<!-- Intent editor table -->
<div style='background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:12px;margin-bottom:12px'>
  <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:10px'>
    <div style='font-size:12px;font-weight:700;color:#7BB3FF'>🏷️ Position Intent Map</div>
    <div style='display:flex;gap:8px'>
      <input id='intent-search' oninput='filterIntentTable(this.value)' placeholder='Filter...'
        style='background:#1a1a35;border:1px solid #3a3a5e;color:#e0e0f0;padding:3px 8px;border-radius:4px;font-size:11px;width:120px'>
      <button onclick='saveAllIntents()' style='background:#0F9D58;color:#fff;border:none;padding:4px 12px;border-radius:4px;cursor:pointer;font-size:11px'>
        💾 Save All
      </button>
    </div>
  </div>
  <div style='font-size:10px;color:#9A9AB0;margin-bottom:8px'>
    Changes auto-save when you change a dropdown. Intent drives stop suggestions, covered call eligibility, and technical analysis depth.
  </div>
  <!-- Legend -->
  <div style='display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px'>
    {"".join(f"<span style='background:#1a1a35;border:1px solid #2a2a5e;padding:2px 8px;border-radius:12px;font-size:9px;color:#9A9AB0'>{lbl[0]} {lbl[1]}</span>" for lbl in INTENT_LABELS.values())}
  </div>
  <div style='overflow-x:auto'>
  <table id='intent-table'>
    <thead><tr style='font-size:10px;color:#9A9AB0'>
      <th>Symbol</th>
      <th style='text-align:right'>Mkt Val</th>
      <th style='text-align:right'>Shares</th>
      <th style='text-align:right'>Price</th>
      <th style='min-width:180px'>Intent</th>
      <th>Stop Logic</th>
      <th>Status</th>
    </tr></thead>
    <tbody id='intent-tbody'>{rows}</tbody>
  </table>
  </div>
</div>

<script>
var pendingIntents = {{}};

function saveIntent(sym, intent) {{
  pendingIntents[sym] = intent;
  document.getElementById('status-'+sym).textContent = '⏳';
  fetch('http://localhost:7778/api/intent', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{action: 'set', symbol: sym, intent: intent}})
  }}).then(function(r) {{ return r.json(); }}).then(function(d) {{
    document.getElementById('status-'+sym).textContent = d.ok ? '✅' : '❌';
    setTimeout(function() {{ document.getElementById('status-'+sym).textContent = ''; }}, 2000);
  }}).catch(function() {{
    document.getElementById('status-'+sym).textContent = '⚠️ Save YAML manually';
  }});
}}

function saveAllIntents() {{
  var selects = document.querySelectorAll('[id^="intent-"]');
  var batch = {{}};
  selects.forEach(function(s) {{
    var sym = s.id.replace('intent-','');
    if(sym && sym !== 'search') batch[sym] = s.value;
  }});
  fetch('http://localhost:7778/api/intent', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{action: 'batch', intents: batch}})
  }}).then(function(r) {{ return r.json(); }}).then(function(d) {{
    alert(d.ok ? '✅ All intents saved!' : '❌ Error: ' + d.error);
  }}).catch(function() {{ alert('Run run_dashboard.bat to enable live saves'); }});
}}

function filterIntentTable(q) {{
  var rows = document.querySelectorAll('#intent-tbody tr');
  rows.forEach(function(r) {{
    r.style.display = r.textContent.toLowerCase().includes(q.toLowerCase()) ? '' : 'none';
  }});
}}
</script>
"""
