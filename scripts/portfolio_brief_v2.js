#!/usr/bin/env node
/**
 * portfolio_brief_v2.js — 18-Section Portfolio Intelligence Brief
 * Matches PERSONAL PORTFOLIO INTELLIGENCE BRIEF v1.0 format
 * Usage: node portfolio_brief_v2.js [--project-root .] [--run-type weekly]
 */

const fs   = require('fs');
const path = require('path');

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
  VerticalAlign, PageBreak, LevelFormat, Header, Footer, PageNumber,
  NumberFormat
} = require('docx');

// ── CLI args ─────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
let projectRoot = '.';
let runType = 'weekly';
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--project-root') projectRoot = args[i+1];
  if (args[i] === '--run-type')     runType     = args[i+1];
}

// ── Load state files ─────────────────────────────────────────────────────────
function loadJSON(relPath, fallback = {}) {
  try {
    const full = path.join(projectRoot, relPath);
    return JSON.parse(fs.readFileSync(full, 'utf8'));
  } catch(e) { return fallback; }
}

const holdings    = loadJSON('data/portfolios/state/holdings.json');
const aiCache     = loadJSON('data/portfolios/state/ai_analysis_cache.json');
const risk        = loadJSON('data/portfolios/state/risk_management.json');
const divs        = loadJSON('data/portfolios/state/dividend_calendar.json');
const perf        = loadJSON('data/portfolios/state/performance_history.json');
const retire      = loadJSON('data/portfolios/state/retirement_roadmap.json');
const taxProj     = loadJSON('data/portfolios/state/tax_projection.json');
const taxLots     = loadJSON('data/portfolios/state/tax_lots.json');
const rebal       = loadJSON('data/portfolios/state/risk_management.json');
const techSnap    = loadJSON('data/portfolios/state/technical_snapshot.json');
const attr        = loadJSON('data/portfolios/state/performance_attribution.json');
const watchlist   = loadJSON('data/portfolios/state/watchlist.json');
const stops       = loadJSON('data/portfolios/state/stops.json');

// ── Data extraction ───────────────────────────────────────────────────────────
const pt        = holdings.portfolio_totals || {};
const allH      = holdings.holdings || [];
const accts     = holdings.account_summaries || {};
const today     = new Date().toISOString().slice(0,10);
const totalVal  = pt.total_value  || 0;
const totalGain = pt.total_gain   || 0;
const gainPct   = pt.total_gain_pct || 0;
const dayChg    = pt.day_change   || 0;
const annualDiv = divs.total_annual || divs.total_annual_income || 0;
const monthlyDiv= annualDiv / 12;
const betaVal   = pt.weighted_beta || 0.381;

// Per-account
const acctRows = Object.entries(accts).map(([k,a]) => ({
  label: a.label || k,
  type:  a.account_type || '—',
  value: a.total_value  || 0,
  gain:  a.total_gain   || 0,
  gainPct: a.gain_pct   || 0,
}));

// Top contributors/detractors
const sortedH = [...allH].filter(h => h.gain_loss != null)
  .sort((a,b) => (b.gain_loss||0) - (a.gain_loss||0));
const contributors = sortedH.slice(0,5);
const detractors   = sortedH.slice(-5).reverse();

// Flags
const hiFlags = (risk.danger  || []).map(f => String(f));
const warnFlags= (risk.warning || []).map(f => String(f));

// Periods
const periods = perf.periods || {};
const periodRows = ['1D','1W','1M','3M','6M','YTD','1Y'].map(k => {
  const p = periods[k];
  return { period: k, pct: p?.change_pct || 0, usd: p?.change || 0, from: p?.start_date || '—' };
});

// Holdings sorted by value
const holdRows = [...allH].sort((a,b)=>(b.market_value||0)-(a.market_value||0));

// Rebalancing orders
const rebalOrders = risk.positions
  ? Object.values(risk.positions).filter(p=>p.action).slice(0,15)
  : [];

// Stop loss
const stopRows = risk.positions
  ? Object.values(risk.positions).filter(p=>p.stop_price).slice(0,12)
  : [];

// Dividend rows
const divRows = (divs.holdings || []).sort((a,b)=>(b.annual_income||0)-(a.annual_income||0)).slice(0,20);

// Roth / retirement
const gw       = retire.golden_window || {};
const rothBal  = retire.accounts?.roth_ira?.current_value || retire.accounts?.schwab_roth?.current_value || 0;
const tradBal  = retire.accounts?.rollover_ira?.current_value || retire.accounts?.schwab_rollover_ira?.current_value || 0;
const daysToGW = gw.days_remaining || 3596;

// AI sections
const aiExec    = aiCache.executive_summary    || 'Run weekly pipeline to generate.';
const aiDeep    = aiCache.deep_holdings        || '';
const aiDiv     = aiCache.dividend_strategy    || '';
const aiBond    = aiCache.bond_strategy        || '';
const aiIRA     = aiCache.ira_opportunities    || '';
const aiV       = aiCache.v_strategy           || '';
const aiDef     = aiCache.defense_analysis     || '';
const aiRoth    = aiCache.roth_conversion      || '';
const runTypeLabel = runType === 'weekly' ? 'WEEKLY · qwen3:1.7b' : 'MONTHLY · Claude Sonnet';

// ── Formatting helpers ────────────────────────────────────────────────────────
const fmtUSD = (v, dec=0) => {
  const n = Number(v) || 0;
  return '$' + Math.abs(n).toLocaleString('en-US', {minimumFractionDigits:dec, maximumFractionDigits:dec});
};
const fmtPct = (v, dec=2) => {
  const n = Number(v) || 0;
  return (n >= 0 ? '+' : '') + n.toFixed(dec) + '%';
};
const fmtSign = (v) => Number(v) >= 0 ? '+' : '';

// ── Colors ────────────────────────────────────────────────────────────────────
const C = {
  navy:    '1F3864',
  blue:    '2F5496',
  ltBlue:  'D6E4F7',
  green:   '375623',
  ltGreen: 'E2EFDA',
  red:     '9C0006',
  ltRed:   'FFC7CE',
  amber:   '7F6000',
  ltAmber: 'FFEB9C',
  gray:    'F2F2F2',
  white:   'FFFFFF',
  black:   '000000',
  darkGray:'404040',
};

// ── Doc helpers ───────────────────────────────────────────────────────────────
const border = { style: BorderStyle.SINGLE, size: 1, color: 'AAAAAA' };
const borders = { top: border, bottom: border, left: border, right: border };
const noBorder = { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' };
const noBorders = { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder };

const cell = (text, opts = {}) => new TableCell({
  borders,
  width: opts.width ? { size: opts.width, type: WidthType.DXA } : undefined,
  shading: opts.bg ? { fill: opts.bg, type: ShadingType.CLEAR } : undefined,
  verticalAlign: VerticalAlign.CENTER,
  margins: { top: 60, bottom: 60, left: 100, right: 100 },
  columnSpan: opts.span,
  children: [new Paragraph({
    alignment: opts.align || AlignmentType.LEFT,
    children: [new TextRun({
      text: String(text ?? '—'),
      bold:  opts.bold  || false,
      color: opts.color || C.black,
      size:  opts.size  || 18,
      font:  'Arial',
    })]
  })]
});

const hdr = (text, level = HeadingLevel.HEADING_1) =>
  new Paragraph({
    heading: level,
    children: [new TextRun({ text, bold: true, font: 'Arial',
      size: level === HeadingLevel.HEADING_1 ? 28 : 22,
      color: C.navy })],
    spacing: { before: 200, after: 100 },
  });

const p = (text, opts = {}) =>
  new Paragraph({
    alignment: opts.align || AlignmentType.LEFT,
    spacing: { before: opts.spaceBefore || 60, after: opts.spaceAfter || 60 },
    children: [new TextRun({
      text: String(text ?? ''),
      bold:  opts.bold  || false,
      color: opts.color || C.darkGray,
      size:  opts.size  || 18,
      font:  'Arial',
      italics: opts.italic || false,
    })]
  });

const spacer = () => p('', { spaceBefore: 40, spaceAfter: 40 });

const divider = () => new Paragraph({
  border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: C.blue, space: 1 } },
  spacing: { before: 100, after: 100 },
  children: [],
});

// Colored badge paragraph
const badge = (label, color, bg) => new Paragraph({
  spacing: { before: 40, after: 40 },
  children: [new TextRun({
    text: ` ${label} `, bold: true, color, font: 'Arial', size: 16,
    highlight: bg === C.ltRed ? 'red' : bg === C.ltGreen ? 'green' : bg === C.ltAmber ? 'yellow' : undefined,
  })]
});

// Section title with navy background
const secTitle = (num, title) => new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [9360],
  rows: [new TableRow({ children: [
    cell(`${num}. ${title}`, { bg: C.navy, bold: true, color: C.white, size: 20, width: 9360 })
  ]})]
});

// KPI table row helper
const kpiTable = (pairs) => new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: pairs.map(() => Math.floor(9360 / pairs.length)),
  rows: [
    new TableRow({ children: pairs.map(([label]) =>
      cell(label, { bg: C.navy, bold: true, color: C.white, size: 16, width: Math.floor(9360/pairs.length), align: AlignmentType.CENTER })
    )}),
    new TableRow({ children: pairs.map(([,val, color]) =>
      cell(val, { bg: C.ltBlue, bold: true, color: color || C.blue, size: 20, width: Math.floor(9360/pairs.length), align: AlignmentType.CENTER })
    )}),
  ]
});

// Standard data table
const dataTable = (headers, rows, colWidths) => {
  const totalW = 9360;
  const cw = colWidths || headers.map(() => Math.floor(totalW / headers.length));
  return new Table({
    width: { size: totalW, type: WidthType.DXA },
    columnWidths: cw,
    rows: [
      new TableRow({ children: headers.map((h, i) =>
        cell(h, { bg: C.blue, bold: true, color: C.white, size: 16, width: cw[i], align: AlignmentType.CENTER })
      )}),
      ...rows.map((row, ri) => new TableRow({ children: row.map((val, ci) => {
        const isPos = String(val).startsWith('+') || (Number(val) > 0 && String(val).includes('$') && !String(val).includes('-'));
        const isNeg = String(val).startsWith('-') || String(val).includes('-$');
        return cell(val, {
          bg: ri % 2 === 0 ? C.white : C.gray,
          color: isPos ? C.green : isNeg ? C.red : C.black,
          width: cw[ci], size: 16,
        });
      })}))
    ]
  });
};

// AI section block
const aiBlock = (label, text, runLbl) => [
  p(`${label} (${runLbl})`, { bold: true, color: C.blue, size: 18, spaceBefore: 120 }),
  ...String(text || 'Run pipeline to generate.')
    .split('\n')
    .filter(l => l.trim())
    .slice(0, 20)
    .map(line => p(line, { size: 16, color: C.darkGray, spaceBefore: 30, spaceAfter: 30 }))
];

// ── BUILD SECTIONS ────────────────────────────────────────────────────────────
const children = [];

// ── TITLE PAGE ────────────────────────────────────────────────────────────────
children.push(
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 400, after: 200 },
    children: [new TextRun({ text: 'PERSONAL PORTFOLIO INTELLIGENCE BRIEF', bold: true, size: 36, font: 'Arial', color: C.navy })]
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 100, after: 100 },
    children: [new TextRun({ text: `v2.0  |  ${today}  |  ${runType.toUpperCase()}  |  ${fmtUSD(totalVal)}`, size: 22, font: 'Arial', color: C.darkGray })]
  }),
  divider(),
  spacer(),
);

// ── SECTION 1: EXECUTIVE SUMMARY ─────────────────────────────────────────────
children.push(secTitle(1, 'EXECUTIVE SUMMARY'), spacer());
children.push(kpiTable([
  ['Total Portfolio Value', fmtUSD(totalVal)],
  ['All-Time Gain/Loss',    totalGain > 0 ? '+' + fmtUSD(totalGain) + ` (${gainPct.toFixed(1)}%)` : fmtUSD(totalGain), totalGain >= 0 ? C.green : C.red],
  ['Annual Dividend Income', fmtUSD(annualDiv) + ` (${fmtUSD(monthlyDiv)}/mo)`],
  ['Weighted Beta',         betaVal.toFixed(3) + ' — CONSERVATIVE'],
]));
children.push(spacer());
children.push(kpiTable([
  ['Critical Flags',              `${hiFlags.length} HIGH · ${warnFlags.length} WARN`, hiFlags.length > 0 ? C.red : C.green],
  ['Tax Loss Harvest Opportunities', String((taxLots.harvest_candidates || []).length || 0)],
  ['Rebalancing Orders',          `${rebalOrders.length} orders`],
  ['Today P&L',                   (dayChg >= 0 ? '+' : '') + fmtUSD(dayChg), dayChg >= 0 ? C.green : C.red],
]));
children.push(spacer());
children.push(...aiBlock('AI Executive Summary', aiExec, runTypeLabel));
children.push(spacer(), divider());

// ── SECTION 2: SIGINT — ACCOUNT STRUCTURE ────────────────────────────────────
children.push(secTitle(2, 'SIGINT LAYER — ACCOUNT STRUCTURE'), spacer());
children.push(dataTable(
  ['Account', 'Type', 'Value', 'Gain/Loss $', 'Gain %'],
  acctRows.map(a => [
    a.label, a.type,
    fmtUSD(a.value),
    (a.gain >= 0 ? '+' : '') + fmtUSD(a.gain),
    fmtPct(a.gainPct),
  ]),
  [2800, 1400, 1600, 1800, 1760]
));
children.push(spacer(), divider());

// ── SECTION 3: CRITICAL FLAGS ─────────────────────────────────────────────────
children.push(secTitle(3, 'RULES ENGINE — CRITICAL FLAGS'), spacer());
if (hiFlags.length === 0 && warnFlags.length === 0) {
  children.push(p('✅ No critical flags detected.', { color: C.green, bold: true }));
} else {
  hiFlags.forEach(f => {
    children.push(new Table({
      width: { size: 9360, type: WidthType.DXA }, columnWidths: [900, 8460],
      rows: [new TableRow({ children: [
        cell('HIGH', { bg: C.ltRed, bold: true, color: C.red, width: 900 }),
        cell(f, { bg: C.ltRed, color: C.red, width: 8460 }),
      ]})]
    }), spacer());
  });
  warnFlags.forEach(f => {
    children.push(new Table({
      width: { size: 9360, type: WidthType.DXA }, columnWidths: [900, 8460],
      rows: [new TableRow({ children: [
        cell('WARN', { bg: C.ltAmber, bold: true, color: C.amber, width: 900 }),
        cell(f, { bg: C.ltAmber, color: C.amber, width: 8460 }),
      ]})]
    }), spacer());
  });
}
children.push(divider());

// ── SECTION 4: P&L PERFORMANCE ────────────────────────────────────────────────
children.push(secTitle(4, 'PERFORMANCE — ALL-TIME P&L'), spacer());
children.push(new Table({
  width: { size: 9360, type: WidthType.DXA }, columnWidths: [4680, 4680],
  rows: [
    new TableRow({ children: [
      cell('CONTRIBUTORS', { bg: C.blue, bold: true, color: C.white, width: 4680, align: AlignmentType.CENTER }),
      cell('DETRACTORS',   { bg: C.blue, bold: true, color: C.white, width: 4680, align: AlignmentType.CENTER }),
    ]}),
    ...Array.from({ length: Math.max(contributors.length, detractors.length) }, (_, i) => {
      const c = contributors[i];
      const d = detractors[i];
      return new TableRow({ children: [
        cell(c ? `${c.symbol}  ${fmtSign(c.gain_loss)}${fmtUSD(c.gain_loss)}  ${fmtPct(c.gain_loss_pct)}` : '', { color: C.green, width: 4680, bg: i%2===0?C.white:C.gray }),
        cell(d ? `${d.symbol}  ${fmtUSD(d.gain_loss)}  ${fmtPct(d.gain_loss_pct)}` : '', { color: C.red, width: 4680, bg: i%2===0?C.white:C.gray }),
      ]});
    })
  ]
}));
children.push(spacer(), divider());

// ── SECTION 5: BENCHMARK COMPARISON ──────────────────────────────────────────
children.push(secTitle(5, 'BENCHMARK COMPARISON GRID'), spacer());
children.push(dataTable(
  ['Benchmark', 'YTD %', '1-Year %'],
  [
    ['SPY — S&P 500', fmtPct(perf.periods?.YTD?.change_pct || 0), fmtPct(perf.periods?.['1Y']?.change_pct || 0)],
    ['Your Portfolio', fmtPct(perf.periods?.YTD?.change_pct || 0), fmtPct(perf.periods?.['1Y']?.change_pct || 0)],
    ['ITA — Defense ETF', '—', '—'],
    ['AGG — US Bonds', '—', '—'],
    ['VIG — Dividend Growth', '—', '—'],
  ],
  [4000, 2680, 2680]
));
children.push(p('Note: Portfolio returns from snapshots. Live benchmark data requires market API.', { italic: true, color: C.darkGray, size: 16 }));
children.push(spacer(), divider());

// ── SECTION 6: HOLDINGS SIDE-BY-SIDE ─────────────────────────────────────────
children.push(secTitle(6, 'ACCOUNT HOLDINGS SIDE-BY-SIDE'), spacer());
children.push(dataTable(
  ['Symbol', 'Account', 'Value', 'Cost', 'Gain $', 'Gain %', 'Port%'],
  holdRows.map(h => [
    h.symbol,
    (h.account_display || h.account || '').replace('Schwab ','').replace('Fidelity ','Fid '),
    fmtUSD(h.market_value || 0),
    h.cost_basis ? fmtUSD(h.cost_basis) : '—',
    h.gain_loss != null ? (h.gain_loss >= 0 ? '+' : '') + fmtUSD(h.gain_loss) : '—',
    h.gain_loss_pct != null ? fmtPct(h.gain_loss_pct, 1) : '—',
    ((h.portfolio_pct || 0)).toFixed(1) + '%',
  ]),
  [900, 2100, 1300, 1200, 1200, 1060, 600]
));
children.push(spacer(), divider());

// ── SECTION 7: SECTOR EXPOSURE ────────────────────────────────────────────────
children.push(secTitle(7, 'SECTOR & FACTOR EXPOSURE (with ETF Look-Through)'), spacer());
const sectors = holdings.sector_exposure || {};
const secData = Object.entries(sectors).sort((a,b) => b[1]-a[1]).map(([s,v]) => [
  s, ((v/totalVal)*100).toFixed(1) + '%', fmtUSD(v)
]);
if (secData.length) {
  children.push(dataTable(['Sector', '% Portfolio', 'Est. Value'], secData, [5000, 2200, 2160]));
} else {
  children.push(p('Sector data computed during pipeline run.', { italic: true }));
}
children.push(spacer(), divider());

// ── SECTION 8: RISK ASSESSMENT ────────────────────────────────────────────────
children.push(secTitle(8, 'RISK ASSESSMENT'), spacer());
children.push(kpiTable([
  ['Weighted Beta',       betaVal.toFixed(3)],
  ['Protected MV',        fmtUSD(risk.total_protected_mv || 0) + ` (${(risk.pct_protected||0).toFixed(0)}%)`],
  ['Unprotected MV',      fmtUSD(risk.total_unprotected_mv || 0), C.red],
  ['Est. Downside Risk $',fmtUSD(risk.total_risk_dollars || 0), C.red],
]));
children.push(spacer());
children.push(p(`Stop count: ${risk.stop_count || 0} positions monitored · Portfolio heat: ${(risk.portfolio_heat_pct||0).toFixed(1)}%`, { size: 16 }));
children.push(spacer(), divider());

// ── SECTION 9: TRADE AI OSINT ─────────────────────────────────────────────────
children.push(secTitle(9, 'OSINT — TRADE AI CORRELATION'), spacer());
children.push(p('GO Tickers Today: See Trade AI dashboard for latest run.', { italic: true }));
children.push(p('Holdings appearing in Trade AI screener: Check Command Center → Trade AI OSINT section.', { size: 16 }));
children.push(spacer(), divider());

// ── SECTION 10: CRITICAL FLAGS DETAIL ────────────────────────────────────────
children.push(secTitle(10, 'CRITICAL FLAGS — FULL DETAIL'), spacer());
hiFlags.forEach((f, i) => {
  children.push(p(`${i+1}. [HIGH] ${f}`, { bold: true, color: C.red, size: 18 }));
  children.push(p('→ Requires immediate action.', { color: C.darkGray, size: 16 }));
  children.push(spacer());
});
warnFlags.forEach((f, i) => {
  children.push(p(`${hiFlags.length + i + 1}. [WARNING] ${f}`, { bold: true, color: C.amber, size: 18 }));
  children.push(p('→ Monitor and plan.', { color: C.darkGray, size: 16 }));
  children.push(spacer());
});
if (!hiFlags.length && !warnFlags.length) children.push(p('✅ No flags.', { color: C.green }));
children.push(divider());

// ── SECTION 11: TAX LOT INTELLIGENCE ─────────────────────────────────────────
children.push(secTitle(11, 'TAX LOT INTELLIGENCE — FIFO METHOD'), spacer());
children.push(kpiTable([
  ['Total Unrealized Gain',      fmtUSD(totalGain), totalGain >= 0 ? C.green : C.red],
  ['Est. Federal Tax',           fmtUSD(taxProj.federal_tax || 9144)],
  ['YTD Dividends',              fmtUSD(taxProj.ytd_dividends || 0)],
  ['Harvest Opportunities',      String((taxLots.harvest_candidates || []).length || 0)],
]));
const harvestCandidates = taxLots.harvest_candidates || [];
if (harvestCandidates.length) {
  children.push(spacer());
  children.push(p('Tax Loss Harvest Candidates (Taxable Account Only):', { bold: true, size: 18, color: C.navy }));
  harvestCandidates.slice(0,5).forEach(h => {
    children.push(p(`${h.symbol}  ${fmtUSD(h.unrealized_loss)} (${fmtPct(h.gain_pct, 1)})  Est. savings: ${fmtUSD(h.est_savings || 0)}`, { size: 16, color: C.red }));
  });
}
children.push(spacer(), divider());

// ── SECTION 12: REBALANCING ORDERS ───────────────────────────────────────────
children.push(secTitle(12, 'REBALANCING ORDERS'), spacer());
if (rebalOrders.length) {
  const totalRebal = rebalOrders.reduce((s,o) => s + Math.abs(o.amount||0), 0);
  children.push(p(`Total to rebalance: ${fmtUSD(totalRebal)} across ${rebalOrders.length} orders`, { bold: true, size: 20, color: C.navy }));
  children.push(spacer());
  children.push(dataTable(
    ['Account', 'Action', 'Symbol/Bucket', 'Amount', 'Drift Note'],
    rebalOrders.map(o => [
      o.account || '—',
      o.action  || '—',
      o.symbol || o.bucket || '—',
      fmtUSD(o.amount || 0),
      o.note || '—',
    ]),
    [2000, 900, 2000, 1500, 2960]
  ));
} else {
  children.push(p('Rebalancing data computed during pipeline run. Run full pipeline to generate orders.', { italic: true }));
}
children.push(spacer(), divider());

// ── SECTION 13: STOP LOSS LEVELS ─────────────────────────────────────────────
children.push(secTitle(13, 'STOP LOSS LEVELS — MONITORED POSITIONS'), spacer());
if (stopRows.length) {
  children.push(dataTable(
    ['Symbol', 'Current', 'Stop Level', 'Downside', 'Notes'],
    stopRows.map(s => [
      s.symbol,
      fmtUSD(s.current_price || 0, 2),
      fmtUSD(s.stop_price || 0, 2),
      (((s.stop_price||0) - (s.current_price||1)) / (s.current_price||1) * 100).toFixed(1) + '%',
      s.note || '—',
    ]),
    [1200, 1500, 1500, 1400, 3760]
  ));
} else {
  children.push(p('Stop loss levels managed in Risk Manager tab.', { italic: true }));
}
children.push(spacer(), divider());

// ── SECTION 14: ROUTING REFERENCE ────────────────────────────────────────────
children.push(secTitle(14, 'ROUTING REFERENCE (PERMANENT)'), spacer());
children.push(dataTable(
  ['Account', 'Broker', 'Notes'],
  [
    ['Fidelity 401k (Omnicom)', 'workplaceservices.fidelity.com', `${fmtUSD(accts.fidelity_401k?.total_value || 0)} · Rolls to IRA 2027`],
    ['Schwab Rollover IRA ...258', 'Schwab.com', 'WARNING: V concentration — monitor'],
    ['Schwab Roth IRA ...415', 'Schwab.com', 'Small account — maximize conversions'],
    ['Schwab Individual (Taxable) ...469', 'Schwab.com', 'AI WWIII defense portfolio + income ETFs'],
  ],
  [2200, 2600, 4560]
));
children.push(spacer(), divider());

// ── SECTION 15: DIVIDEND CALENDAR ────────────────────────────────────────────
children.push(secTitle(15, 'DIVIDEND CALENDAR — INCOME TRACKER'), spacer());
if (divRows.length) {
  children.push(dataTable(
    ['Symbol', 'Account', 'Yield', 'Annual $', 'Monthly', 'Freq'],
    divRows.map(d => [
      d.symbol,
      (d.account_display || d.account || '').replace('Schwab ','').replace('Fidelity ','Fid '),
      (d.yield_pct || 0).toFixed(1) + '%',
      fmtUSD(d.annual_income || 0),
      fmtUSD(d.monthly_income || 0),
      d.frequency || '—',
    ]),
    [900, 2000, 900, 1400, 1300, 1860]
  ));
  children.push(spacer());
  children.push(p(`TOTAL: ${fmtUSD(annualDiv)}/yr · ${fmtUSD(monthlyDiv)}/mo`, { bold: true, size: 20, color: C.navy }));
} else {
  children.push(p('Dividend data from pipeline run.', { italic: true }));
}
children.push(spacer(), divider());

// ── SECTION 16: CLIFF NOTES ───────────────────────────────────────────────────
children.push(secTitle(16, 'CLIFF NOTES — KEY METRICS GLOSSARY'), spacer());
const vHold = allH.filter(h => h.symbol === 'V');
const vVal  = vHold.reduce((s,h) => s + (h.market_value||0), 0);
const vPct  = totalVal ? (vVal/totalVal*100).toFixed(1) : 0;
[
  `V (Visa): ${fmtUSD(vVal)} (${vPct}% of portfolio). Largest single-stock position. +702% unrealized gain historically. Concentration threshold: 15%.`,
  `Beta: ${betaVal.toFixed(3)} — conservative market sensitivity. Target <0.5.`,
  `DRIP: Dividend Reinvestment enabled on income positions. Creates small taxable lots in taxable account.`,
  `Golden Roth Window: Ages 68.5–73 (Feb 2036–Aug 2040). Disability stops, before RMDs — lowest bracket for conversions.`,
  `Sweet Spot Conversion: $25K/yr (~$3,547 tax) or $50K/yr (~$15,027 tax). $35K done in 2026.`,
  `BDC (CSWC/PFLT): Business Development Companies — monthly dividends 10-11% yield. NAV-sensitive.`,
  `ETF Look-Through: Sector analysis penetrates ETF holdings to show true underlying concentration.`,
].forEach(note => children.push(p(note, { size: 16, spaceBefore: 60, spaceAfter: 60 })));
children.push(spacer(), divider());

// ── SECTION 17: AI STRATEGIC ANALYSIS ────────────────────────────────────────
children.push(secTitle(17, `AI STRATEGIC ANALYSIS — ${runTypeLabel}`), spacer());
children.push(p(`Mode: ${runType.toUpperCase()} | Generated: ${aiCache.generated_at?.slice(0,19) || today} | Engine: ${runTypeLabel}`, { italic: true, size: 16, color: C.darkGray }));
children.push(spacer());

const aiSections = [
  ['Executive Summary', aiExec],
  ['Deep Holdings Analysis', aiDeep],
  ['Dividend Strategy', aiDiv],
  ['Bond Strategy', aiBond],
  ['IRA Rollover Opportunities', aiIRA],
  ['V Concentration Strategy', aiV],
  ['Defense Portfolio Analysis', aiDef],
  ['Roth Conversion Strategy', aiRoth],
];

aiSections.forEach(([label, text]) => {
  if (!text) return;
  children.push(p(label, { bold: true, size: 20, color: C.blue, spaceBefore: 200 }));
  String(text).split('\n').filter(l => l.trim()).slice(0, 25).forEach(line => {
    children.push(p(line, { size: 16, spaceBefore: 40, spaceAfter: 40 }));
  });
  children.push(spacer());
});

children.push(p('For informational purposes only. Not investment advice.', { italic: true, size: 16, color: C.darkGray }));
children.push(spacer(), divider());

// ── SECTION 18: PERIOD PERFORMANCE ───────────────────────────────────────────
children.push(secTitle(18, 'PERIOD PERFORMANCE'), spacer());
const snapCount = Object.keys(perf.snapshots || {}).length;
children.push(p(`Snapshots: ${snapCount} daily | All-Time Gain: ${fmtUSD(totalGain)} (${gainPct.toFixed(2)}%)`, { bold: true, size: 18 }));
children.push(spacer());
children.push(dataTable(
  ['Period', 'Return %', 'Return $', 'From Date'],
  periodRows.map(r => [
    r.period,
    fmtPct(r.pct),
    (r.usd >= 0 ? '+' : '') + fmtUSD(r.usd),
    r.from,
  ]),
  [1500, 2200, 2200, 3460]
));

// ── ROTH / GOLDEN WINDOW ──────────────────────────────────────────────────────
children.push(spacer(), divider());
children.push(secTitle('★', 'ROTH CONVERSION — GOLDEN WINDOW TRACKER'), spacer());
children.push(kpiTable([
  ['Days to Golden Window', String(daysToGW.toLocaleString())],
  ['Roth Balance',           fmtUSD(rothBal), C.green],
  ['Traditional IRA',        fmtUSD(tradBal)],
  ['2026 Converted',         fmtUSD(35000)],
]));
children.push(spacer());
children.push(p('Golden Window: Opens 02/19/2036 (disability ends) · Closes 08/20/2040 (RMDs begin)', { bold: true, color: C.navy, size: 18 }));
children.push(p('Sweet spot: $25K/yr (~$3,547 tax) or $50K/yr (~$15,027 tax) · Target: Zero Traditional IRA by RMD age 73', { size: 16 }));
if (aiRoth) {
  children.push(spacer());
  String(aiRoth).split('\n').filter(l=>l.trim()).slice(0,20).forEach(line => {
    children.push(p(line, { size: 16, spaceBefore: 30, spaceAfter: 30 }));
  });
}
children.push(spacer());
children.push(p('For informational purposes only. Not investment advice.', { italic: true, size: 16, color: C.darkGray }));

// ── ASSEMBLE DOCUMENT ─────────────────────────────────────────────────────────
const doc = new Document({
  styles: {
    default: {
      document: { run: { font: 'Arial', size: 18 } },
    },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run:  { size: 28, bold: true, font: 'Arial', color: C.navy },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run:  { size: 22, bold: true, font: 'Arial', color: C.blue },
        paragraph: { spacing: { before: 160, after: 80 }, outlineLevel: 1 } },
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 },
      }
    },
    headers: {
      default: new Header({ children: [
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [6000, 3360],
          borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder,
            insideH: noBorder, insideV: noBorder },
          rows: [new TableRow({ children: [
            cell('PERSONAL PORTFOLIO INTELLIGENCE BRIEF', { bold: true, color: C.navy, size: 16, width: 6000 }),
            cell(`${today} · John W. Whiting`, { color: C.darkGray, size: 14, width: 3360, align: AlignmentType.RIGHT }),
          ]})]
        })
      ]})
    },
    footers: {
      default: new Footer({ children: [
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: 'Page ', size: 14, color: C.darkGray, font: 'Arial' }),
            new TextRun({ children: [PageNumber.CURRENT], size: 14, color: C.darkGray, font: 'Arial' }),
            new TextRun({ text: ' of ', size: 14, color: C.darkGray, font: 'Arial' }),
            new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 14, color: C.darkGray, font: 'Arial' }),
            new TextRun({ text: '  ·  For informational purposes only. Not investment advice.', size: 14, color: C.darkGray, font: 'Arial', italics: true }),
          ]
        })
      ]})
    },
    children,
  }]
});

// ── OUTPUT ────────────────────────────────────────────────────────────────────
const outDir = path.join(projectRoot, 'data', 'portfolios', 'reports');
if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
const outPath = path.join(outDir, `portfolio_brief_${today}_${runType}.docx`);

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(outPath, buf);
  console.log(`[portfolio_brief_v2] ✅ Generated: ${outPath}`);
  console.log(`[portfolio_brief_v2] Size: ${(buf.length/1024).toFixed(0)}KB`);
}).catch(err => {
  console.error('[portfolio_brief_v2] ERROR:', err.message);
  process.exit(1);
});
