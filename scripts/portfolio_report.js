// portfolio_report.js — Trade AI v12 Portfolio Intelligence
// Generates AIWWIII-style CIA/GSE intelligence brief as Word .docx
// Format mirrors AI WWIII Intel Brief v3.12 — 16 sections

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType,
  VerticalAlign, PageNumber, PageBreak, LevelFormat, Header, Footer,
  ImageRun
} = require('docx');
const fs = require('fs');

const DATA = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));
const CHART_PATHS  = DATA.chart_paths  || {};
const PERFORMANCE  = DATA.performance  || {};
const AI_ANALYSIS  = DATA.ai_analysis  || {};

// Embed PNG chart as ImageRun if path exists
function chartImage(key, widthEmu = 6480000, heightEmu = 3600000) {
  const p = CHART_PATHS[key];
  if (!p) return null;
  try {
    const imgData = require('fs').readFileSync(p);
    return new ImageRun({ data: imgData, transformation: { width: Math.round(widthEmu/9144), height: Math.round(heightEmu/9144) }, type: 'png' });
  } catch(e) { return null; }
}
function chartPara(key, w=600, h=350) {
  const img = chartImage(key, w*9144, h*9144);
  if (!img) return null;
  return new Paragraph({ children: [img], spacing: { before: 120, after: 120 } });
}
const OUTPUT = process.argv[3];

// ── Colors ────────────────────────────────────────────────────────────────────
const C = {
  navy:   "1A237E", darkBlue: "0D1B4F", accent: "2979FF",
  green:  "1B5E20", lightGreen: "E8F5E9",
  red:    "B71C1C", lightRed:   "FFEBEE",
  yellow: "F57F17", lightYellow:"FFFDE7",
  gray:   "424242", lightGray:  "F5F5F5",
  white:  "FFFFFF", black:      "000000",
  gold:   "F9A825",
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function border(color = "CCCCCC", size = 6) {
  return { style: BorderStyle.SINGLE, size, color };
}
function noB() {
  const n = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
  return { top: n, bottom: n, left: n, right: n };
}
function allBorders(c = "CCCCCC", sz = 6) {
  const b = border(c, sz);
  return { top: b, bottom: b, left: b, right: b };
}
function shade(fill, type = ShadingType.CLEAR) { return { fill, type }; }
function cell(children, opts = {}) {
  // Handle legacy call pattern: cell("text", isHeader, width)
  if (typeof opts === 'boolean') {
    const isHdr = opts;
    const w = arguments[2];
    opts = { fill: isHdr ? C.navy : undefined, width: w };
    if (isHdr && typeof children === 'string') {
      children = p(children, { bold: true, size: 9, color: C.white });
    } else if (typeof children === 'string') {
      children = p(children, { size: 9 });
    }
  }
  return new TableCell({
    width: opts.width ? { size: opts.width, type: WidthType.DXA } : undefined,
    shading: opts.fill ? shade(opts.fill) : undefined,
    borders: opts.borders || allBorders(),
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    verticalAlign: VerticalAlign.CENTER,
    children: Array.isArray(children) ? children : [children],
  });
}
function row(cells) { return new TableRow({ children: cells }); }
function p(text, opts = {}) {
  return new Paragraph({
    alignment: opts.align || AlignmentType.LEFT,
    spacing: { before: opts.before || 0, after: opts.after || 60 },
    border: opts.border,
    children: [new TextRun({
      text: String(text),
      bold: opts.bold || false,
      italics: opts.italic || false,
      color: opts.color || C.black,
      size: (opts.size || 11) * 2,
      font: "Arial",
      underline: opts.underline ? {} : undefined,
    })]
  });
}
function p2(runs, opts = {}) {
  return new Paragraph({
    alignment: opts.align || AlignmentType.LEFT,
    spacing: { before: opts.before || 0, after: opts.after || 60 },
    border: opts.border,
    children: runs,
  });
}
function run(text, opts = {}) {
  return new TextRun({
    text: String(text), bold: opts.bold, italics: opts.italic,
    color: opts.color || C.black, size: (opts.size || 11) * 2, font: "Arial",
    underline: opts.underline ? {} : undefined,
  });
}
function hRule(color = C.accent) {
  return new Paragraph({
    border: { bottom: { style: BorderStyle.SINGLE, size: 12, color, space: 1 } },
    spacing: { before: 120, after: 120 },
    children: [],
  });
}

function heading1(text) {
  return new Paragraph({
    text: String(text),
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 240, after: 100 },
  });
}

function heading2(text) {
  return new Paragraph({
    text: String(text),
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 200, after: 80 },
  });
}

function heading3(text) {
  return new Paragraph({
    text: String(text),
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 160, after: 60 },
  });
}

function sectionHeader(num, title) {
  return [
    hRule(C.darkBlue),
    new Paragraph({
      spacing: { before: 200, after: 80 },
      children: [
        run(`${num}. `, { bold: true, color: C.accent, size: 13 }),
        run(title, { bold: true, color: C.darkBlue, size: 13 }),
      ],
    }),
  ];
}
function fmtUSD(v) {
  if (v == null) return "—";
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  return sign + "$" + abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtPct(v) {
  if (v == null) return "—";
  return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
}
function gainColor(v) { return v > 0 ? C.green : (v < 0 ? C.red : C.gray); }

// ── Data extraction ───────────────────────────────────────────────────────────
const portfolio  = DATA.portfolio  || {};
const analysis   = DATA.analysis   || {};
const tax        = DATA.tax        || {};
const rebal      = DATA.rebalancing || {};
const risk       = DATA.risk       || {};
const totals     = portfolio.portfolio_totals || {};
const accounts   = portfolio.account_summaries || {};
const holdings   = portfolio.holdings || [];
const flags      = analysis.critical_flags || [];
const divs       = analysis.dividends || {};
const vitals     = analysis.vitals || {};
const sectorPct  = analysis.sector_pct || {};
const attribution = analysis.attribution || {};
const riskMetrics = risk.risk_metrics || {};
const benchmarks  = (risk.benchmark_comparison || {}).benchmarks || [];
const taCorr      = risk.trade_ai_correlation || {};
const harvestCand = tax.harvest_candidates || [];
const driftData   = rebal.drift_analysis || {};
const rebalOrders = rebal.rebalance_orders || [];

const asOf = portfolio.as_of || new Date().toISOString().slice(0, 10);
const owner = portfolio.owner || "";
const totalMV = totals.total_value || 0;
const totalGain = totals.total_gain || 0;
const totalGainPct = totals.total_gain_pct || 0;
const flagCount = analysis.flag_count || {};

// Status
const status = (flagCount.CRITICAL || 0) > 0 ? "⚠ CRITICAL FLAGS" :
               (flagCount.HIGH || 0) > 0 ? "ACTION REQUIRED" : "MONITORING";

// ── Document Construction ─────────────────────────────────────────────────────
const children = [];

// COVER BLOCK
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 0, after: 80 },
  shading: shade(C.darkBlue),
  border: { bottom: border(C.accent, 24) },
  children: [
    run("PERSONAL PORTFOLIO INTELLIGENCE BRIEF", { bold: true, color: C.white, size: 16 }),
  ],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 0, after: 160 },
  shading: shade(C.darkBlue),
  children: [
    run(`v1.0  |  ${asOf}  |  ${status}  |  ${fmtUSD(totalMV)}`, { color: C.gold, size: 11 }),
  ],
}));

// SECTION 1 — EXECUTIVE SUMMARY
children.push(...sectionHeader(1, "EXECUTIVE SUMMARY"));
const execRows = [
  ["Total Portfolio Value", fmtUSD(totalMV), ""],
  ["All-Time Gain/Loss", fmtUSD(totalGain), fmtPct(totalGainPct)],
  ["Annual Dividend Income (Est.)", fmtUSD(divs.total_annual_income), `${fmtUSD(divs.total_monthly_income)}/mo`],
  ["Weighted Portfolio Beta", riskMetrics.weighted_beta || "—", riskMetrics.risk_assessment || ""],
  ["Critical Flags", flagCount.CRITICAL || 0, `${flagCount.HIGH || 0} HIGH · ${flagCount.WARNING || 0} WARN`],
  ["Tax Loss Harvest Opportunities", harvestCand.length, `Potential savings: ${fmtUSD((tax.summary || {}).harvest_potential_savings)}`],
  ["Rebalancing Orders", rebalOrders.length, `${fmtUSD(rebal.total_to_rebalance)} to move`],
];
children.push(new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [3200, 2480, 3680],
  rows: execRows.map(([label, val, note]) => row([
    cell(p(label, { bold: true, size: 10 }), { fill: C.lightGray, width: 3200 }),
    cell(p(val, { bold: true, size: 10, color: gainColor(parseFloat(String(val).replace(/[$,%+]/g, "")) || 0) }), { width: 2480 }),
    cell(p(note, { size: 10, color: C.gray }), { width: 3680 }),
  ])),
}));

// SECTION 2 — SIGINT LAYER (Account Breakdown)
children.push(...sectionHeader(2, "SIGINT LAYER — ACCOUNT STRUCTURE"));
const acctRows = Object.entries(accounts).map(([k, s]) =>
  row([
    cell(p(s.display_name || k, { bold: true, size: 10 }), { width: 3200 }),
    cell(p(s.account_type || "", { size: 10 }), { width: 1500 }),
    cell(p(fmtUSD(s.total_value), { bold: true, size: 10 }), { width: 1800 }),
    cell(p(fmtUSD(s.total_gain), { size: 10, color: gainColor(s.total_gain || 0) }), { width: 1700 }),
    cell(p(fmtPct(s.total_gain_pct), { size: 10, color: gainColor(s.total_gain_pct || 0) }), { width: 1160 }),
  ])
);
children.push(new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [3200, 1500, 1800, 1700, 1160],
  rows: [
    row([
      cell(p("Account", { bold: true, size: 10, color: C.white }), { fill: C.navy, width: 3200 }),
      cell(p("Type", { bold: true, size: 10, color: C.white }), { fill: C.navy, width: 1500 }),
      cell(p("Value", { bold: true, size: 10, color: C.white }), { fill: C.navy, width: 1800 }),
      cell(p("Gain/Loss $", { bold: true, size: 10, color: C.white }), { fill: C.navy, width: 1700 }),
      cell(p("Gain %", { bold: true, size: 10, color: C.white }), { fill: C.navy, width: 1160 }),
    ]),
    ...acctRows,
  ],
}));

// SECTION 3 — CRITICAL FLAGS (Rules Engine)
children.push(...sectionHeader(3, "RULES ENGINE — CRITICAL FLAGS"));
if (flags.length === 0) {
  children.push(p("✅ No critical flags at this time.", { color: C.green }));
} else {
  flags.slice(0, 12).forEach(f => {
    const sevColor = f.severity === "CRITICAL" ? C.red : f.severity === "HIGH" ? "E65100" :
                     f.severity === "WARNING" ? C.yellow : C.green;
    const sevFill  = f.severity === "CRITICAL" ? "FFEBEE" : f.severity === "HIGH" ? "FFF3E0" :
                     f.severity === "WARNING" ? "FFFDE7" : C.lightGreen;
    children.push(new Table({
      width: { size: 9360, type: WidthType.DXA },
      columnWidths: [800, 8560],
      rows: [row([
        cell(p(f.severity || "", { bold: true, size: 9, color: C.white, align: AlignmentType.CENTER }),
             { fill: sevColor, width: 800 }),
        cell([
          p2([run(`${f.symbol ? "[" + f.symbol + "] " : ""}`, { bold: true, size: 10 }),
              run(f.message || "", { size: 10 })]),
          p(f.action || "", { size: 9, italic: true, color: C.gray }),
        ], { fill: sevFill, width: 8560 }),
      ])],
    }));
    children.push(p("", { after: 40 }));
  });
}

// SECTION 4 — PERFORMANCE P&L
children.push(...sectionHeader(4, "PERFORMANCE — ALL-TIME P&L"));
const contributors = attribution.top_contributors || [];
const detractors = attribution.top_detractors || [];
if (contributors.length > 0 || detractors.length > 0) {
  const pRows = [
    row([
      cell(p("CONTRIBUTORS", { bold: true, size: 10, color: C.white }), { fill: C.green, width: 4680 }),
      cell(p("DETRACTORS", { bold: true, size: 10, color: C.white }), { fill: C.red, width: 4680 }),
    ]),
    ...Array.from({ length: Math.max(contributors.length, detractors.length) }, (_, i) => {
      const c = contributors[i] || {};
      const d = detractors[i] || {};
      return row([
        cell(p2([
          run(c.symbol ? `${c.symbol}  ` : "", { bold: true, size: 10 }),
          run(c.gain ? fmtUSD(c.gain) : "", { size: 10, color: C.green }),
          run(c.gain_pct ? `  ${fmtPct(c.gain_pct)}` : "", { size: 10, color: C.green }),
        ]), { width: 4680 }),
        cell(p2([
          run(d.symbol ? `${d.symbol}  ` : "", { bold: true, size: 10 }),
          run(d.loss ? fmtUSD(d.loss) : "", { size: 10, color: C.red }),
          run(d.loss_pct ? `  ${fmtPct(d.loss_pct)}` : "", { size: 10, color: C.red }),
        ]), { width: 4680 }),
      ]);
    }),
  ];
  children.push(new Table({ width: { size: 9360, type: WidthType.DXA }, columnWidths: [4680, 4680], rows: pRows }));
}

// SECTION 5 — BENCHMARK GRID
children.push(...sectionHeader(5, "BENCHMARK COMPARISON GRID — vs Your Portfolio"));
// Pull your portfolio period returns for comparison
const _b5ph = DATA.perf_history || {};
const _b5pds = _b5ph.periods || {};
const _portYTD = (_b5pds.YTD || {}).change_pct;
const _port1Y  = (_b5pds["1Y"] || {}).change_pct;
const _port1M  = (_b5pds["1M"] || {}).change_pct;

// Header row with YOUR PORTFOLIO column highlighted
const bRows = [
  row([
    cell(p("Benchmark", { bold: true, size: 10, color: C.white }), { fill: C.navy, width: 2400 }),
    cell(p("YTD %", { bold: true, size: 10, color: C.white }), { fill: C.navy, width: 1560 }),
    cell(p("Your YTD", { bold: true, size: 10, color: C.white }), { fill: "1B5E20", width: 1400 }),
    cell(p("Delta", { bold: true, size: 10, color: C.white }), { fill: "1A237E", width: 1000 }),
    cell(p("1-Year %", { bold: true, size: 10, color: C.white }), { fill: C.navy, width: 1500 }),
    cell(p("Your 1Y", { bold: true, size: 10, color: C.white }), { fill: "1B5E20", width: 1500 }),
  ]),
  ...benchmarks.map(b => {
    const bYTD = b.ytd_pct;
    const b1Y  = b["1yr_pct"];
    const deltaYTD = (_portYTD != null && bYTD != null) ? _portYTD - bYTD : null;
    const delta1Y  = (_port1Y  != null && b1Y  != null) ? _port1Y  - b1Y  : null;
    return row([
      cell(p2([run(b.ticker + " ", { bold: true, size: 10 }), run(b.name || "", { size: 10, color: C.gray })]), { width: 2400 }),
      cell(p(fmtPct(bYTD), { size: 10, color: gainColor(bYTD) }), { width: 1560 }),
      cell(p(_portYTD != null ? fmtPct(_portYTD) : "—", { size: 10, bold: true, color: gainColor(_portYTD || 0) }), { fill: "F1F8E9", width: 1400 }),
      cell(p(deltaYTD != null ? fmtPct(deltaYTD) : "—", { size: 10, bold: true, color: gainColor(deltaYTD || 0) }), { fill: deltaYTD > 0 ? "E8F5E9" : "FFEBEE", width: 1000 }),
      cell(p(fmtPct(b1Y), { size: 10, color: gainColor(b1Y) }), { width: 1500 }),
      cell(p(_port1Y != null ? fmtPct(_port1Y) : "—", { size: 10, bold: true, color: gainColor(_port1Y || 0) }), { fill: "F1F8E9", width: 1500 }),
    ]);
  }),
];
children.push(new Table({ width: { size: 9360, type: WidthType.DXA }, columnWidths: [2400, 1560, 1400, 1000, 1500, 1500], rows: bRows }));
const _ytdWin = benchmarks.filter(b => b.ytd_pct != null && _portYTD != null && _portYTD > b.ytd_pct).length;
const _ytdLos = benchmarks.filter(b => b.ytd_pct != null && _portYTD != null && _portYTD < b.ytd_pct).length;
if (_portYTD != null) {
  children.push(p(
    `Your YTD: ${fmtPct(_portYTD)} — beating ${_ytdWin}/${benchmarks.length} benchmarks, trailing ${_ytdLos}/${benchmarks.length}`,
    { size: 10, bold: true, color: _ytdWin >= _ytdLos ? C.green : C.red, before: 80 }
  ));
}

// SECTION 6 — HOLDINGS SIDE-BY-SIDE
children.push(...sectionHeader(6, "ACCOUNT HOLDINGS SIDE-BY-SIDE"));
const validHoldings = holdings.filter(h => !h.is_loan && (h.market_value || 0) > 0)
  .sort((a, b) => (b.market_value || 0) - (a.market_value || 0)).slice(0, 30);
const hRows = [
  row([
    cell(p("Symbol", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 900 }),
    cell(p("Account", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 2200 }),
    cell(p("Value", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 1600 }),
    cell(p("Cost", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 1400 }),
    cell(p("Gain $", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 1400 }),
    cell(p("Gain %", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 1000 }),
    cell(p("Port%", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 860 }),
  ]),
  ...validHoldings.map((h, i) => {
    const gl = h.gain_loss || 0;
    const fill = i % 2 === 0 ? C.white : "F8F9FF";
    return row([
      cell(p(h.symbol || "", { bold: true, size: 9 }), { fill, width: 900 }),
      cell(p(h.account_display || "", { size: 9, color: C.gray }), { fill, width: 2200 }),
      cell(p(fmtUSD(h.market_value), { size: 9 }), { fill, width: 1600 }),
      cell(p(fmtUSD(h.cost_basis), { size: 9, color: C.gray }), { fill, width: 1400 }),
      cell(p(fmtUSD(gl), { size: 9, color: gainColor(gl) }), { fill, width: 1400 }),
      cell(p(fmtPct(h.gain_loss_pct), { size: 9, color: gainColor(gl) }), { fill, width: 1000 }),
      cell(p(`${(h.portfolio_pct || 0).toFixed(1)}%`, { size: 9, color: (h.portfolio_pct || 0) > 15 ? C.red : C.gray }), { fill, width: 860 }),
    ]);
  }),
];
children.push(new Table({ width: { size: 9360, type: WidthType.DXA }, columnWidths: [900, 2200, 1600, 1400, 1400, 1000, 860], rows: hRows }));
// Section 6A — Top Holdings chart
const c6 = chartPara('top_holdings', 700, 420);
if (c6) children.push(c6);
// Section 6B — Gain/Loss chart
const c6b = chartPara('gain_loss', 700, 380);
if (c6b) children.push(c6b);

// SECTION 7 — SECTOR & FACTOR EXPOSURE
children.push(...sectionHeader(7, "SECTOR & FACTOR EXPOSURE (with ETF Look-Through)"));
const sectors = Object.entries(sectorPct).sort((a, b) => b[1] - a[1]).slice(0, 15);
const sRows = [
  row([
    cell(p("Sector", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 4000 }),
    cell(p("% Portfolio", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 2000 }),
    cell(p("Est. Value", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 3360 }),
  ]),
  ...sectors.map(([sector, pct], i) => {
    const mv = (pct / 100) * totalMV;
    const fill = pct > 30 ? "FFEBEE" : pct > 15 ? "FFF3E0" : (i % 2 === 0 ? C.white : "F8F9FF");
    return row([
      cell(p(sector, { size: 10, bold: pct > 20 }), { fill, width: 4000 }),
      cell(p(`${pct.toFixed(1)}%`, { size: 10, color: pct > 30 ? C.red : pct > 15 ? "E65100" : C.black }), { fill, width: 2000 }),
      cell(p(fmtUSD(mv), { size: 10 }), { fill, width: 3360 }),
    ]);
  }),
];
children.push(new Table({ width: { size: 9360, type: WidthType.DXA }, columnWidths: [4000, 2000, 3360], rows: sRows }));
// Section 7A — Sector Donut
const c7 = chartPara('sector_donut', 600, 420);
if (c7) children.push(c7);
// Section 7B — ETF Look-Through
const c7b = chartPara('etf_exposure', 700, 460);
if (c7b) children.push(c7b);

// SECTION 8 — RISK ASSESSMENT
children.push(...sectionHeader(8, "RISK ASSESSMENT"));
const rRows = [
  ["Weighted Portfolio Beta", riskMetrics.weighted_beta || "—", "vs S&P 500 = 1.0"],
  ["Annualized Volatility", riskMetrics.weighted_volatility_pct ? riskMetrics.weighted_volatility_pct + "%" : "—", "Weighted average"],
  ["Sharpe Ratio (est.)", riskMetrics.approximate_sharpe || "—", "Risk-adjusted return"],
  ["Risk Profile", riskMetrics.risk_assessment || "—", ""],
];
children.push(new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [3500, 2500, 3360],
  rows: rRows.map(([label, val, note]) => row([
    cell(p(label, { bold: true, size: 10 }), { fill: C.lightGray, width: 3500 }),
    cell(p(String(val), { bold: true, size: 10 }), { width: 2500 }),
    cell(p(note, { size: 9, color: C.gray }), { width: 3360 }),
  ])),
}));

// SECTION 9 — OSINT SENTIMENT (Trade AI Correlation)
children.push(...sectionHeader(9, "OSINT — TRADE AI CORRELATION"));
const goTickers = taCorr.go_tickers || [];
const overlaps  = taCorr.holdings_in_screener || [];
children.push(p2([
  run("GO Tickers Today: ", { bold: true, size: 11 }),
  run(goTickers.length > 0 ? goTickers.join(", ") : "None", { size: 11, color: goTickers.length > 0 ? C.green : C.gray }),
]));
children.push(p(`Holdings appearing in Trade AI screener: ${overlaps.length}`, { size: 10, color: C.gray }));
if (overlaps.length > 0) {
  const oRows = overlaps.map(o => row([
    cell(p(o.symbol || "", { bold: true, size: 10 }), { width: 1200 }),
    cell(p(o.account || "", { size: 10 }), { width: 2500 }),
    cell(p(fmtUSD(o.market_value), { size: 10 }), { width: 1800 }),
    cell(p(`${o.trade_ai_decision || "—"} (${o.trade_ai_score || 0})`, { size: 10,
      color: o.trade_ai_decision === "GO" ? C.green : C.gray }), { width: 1800 }),
    cell(p(o.alert || "", { size: 9, italic: true }), { width: 2060 }),
  ]));
  children.push(new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [1200, 2500, 1800, 1800, 2060],
    rows: [
      row([
        cell(p("Symbol", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 1200 }),
        cell(p("Account", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 2500 }),
        cell(p("Value", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 1800 }),
        cell(p("Trade AI", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 1800 }),
        cell(p("Alert", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 2060 }),
      ]),
      ...oRows,
    ],
  }));
}

// SECTION 10 — CRITICAL FLAGS (Detail)
children.push(...sectionHeader(10, "CRITICAL FLAGS — FULL DETAIL"));
(analysis.critical_flags || []).forEach((f, i) => {
  children.push(p2([
    run(`${i + 1}. [${f.severity}] `, { bold: true, size: 11,
      color: f.severity === "CRITICAL" ? C.red : f.severity === "HIGH" ? "E65100" : C.yellow }),
    run(f.message || "", { size: 10 }),
  ], { before: 80 }));
  if (f.action) children.push(p(`   → ${f.action}`, { size: 9, italic: true, color: C.gray, before: 20 }));
});

// SECTION 11 — TAX LOT INTELLIGENCE
children.push(...sectionHeader(11, "TAX LOT INTELLIGENCE — FIFO METHOD"));
const taxSummary = tax.summary || {};
children.push(new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [3800, 2780, 2780],
  rows: [
    ["Total Unrealized Gain",   fmtUSD(taxSummary.total_unrealized_gain),   ""],
    ["Taxable Account Gain",    fmtUSD(taxSummary.taxable_unrealized_gain),  "If sold, taxable events apply"],
    ["Est. Tax If All Sold",    fmtUSD(taxSummary.estimated_tax_if_all_sold),"Approx. at max rates"],
    ["Harvest Opportunities",   harvestCand.length,                          fmtUSD(taxSummary.harvest_potential_savings) + " potential savings"],
    ["YTD Dividends Received",  fmtUSD((tax.dividend_income_ytd || {}).ytd_total), ""],
  ].map(([label, val, note]) => row([
    cell(p(label, { bold: true, size: 10 }), { fill: C.lightGray, width: 3800 }),
    cell(p(String(val), { bold: true, size: 10 }), { width: 2780 }),
    cell(p(note, { size: 9, color: C.gray }), { width: 2780 }),
  ])),
}));
if (harvestCand.length > 0) {
  children.push(p("Tax Loss Harvest Candidates (Taxable Account Only):", { bold: true, size: 10, before: 120 }));
  harvestCand.forEach(c => {
    children.push(p2([
      run(`  ${c.symbol}  `, { bold: true, size: 10 }),
      run(`${fmtUSD(c.unrealized_gain)} (${fmtPct(c.unrealized_gain_pct)})  `, { size: 10, color: C.red }),
      run(`Est. savings: ${fmtUSD(c.tax_savings_estimate)}`, { size: 10, color: C.green }),
    ]));
  });
}

// SECTION 12 — REBALANCING ORDERS
children.push(...sectionHeader(12, "REBALANCING ORDERS"));
if (rebalOrders.length === 0) {
  children.push(p("✅ Portfolio is within target allocation thresholds. No rebalancing required.", { color: C.green }));
} else {
  children.push(p(`Total to rebalance: ${fmtUSD(rebal.total_to_rebalance)} across ${rebalOrders.length} orders`, { bold: true, size: 10 }));
  const rOrderRows = rebalOrders.map(o => row([
    cell(p(o.account || "", { size: 9 }), { width: 2600 }),
    cell(p(o.bucket || "", { size: 9 }), { width: 2200 }),
    cell(p(o.action || "", { bold: true, size: 9, color: o.action === "BUY" ? C.green : C.red }),
         { fill: o.action === "BUY" ? C.lightGreen : C.lightRed, width: 800 }),
    cell(p(fmtUSD(o.amount_usd), { bold: true, size: 9 }), { width: 1600 }),
    cell(p(o.note || "", { size: 9, color: C.gray }), { width: 2160 }),
  ]));
  children.push(new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [2600, 2200, 800, 1600, 2160],
    rows: [
      row([
        cell(p("Account", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 2600 }),
        cell(p("Bucket", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 2200 }),
        cell(p("Action", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 800 }),
        cell(p("Amount", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 1600 }),
        cell(p("Note", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 2160 }),
      ]),
      ...rOrderRows,
    ],
  }));
}

// SECTION 13 — WATCHLIST / STOP LEVELS
children.push(...sectionHeader(13, "STOP LOSS LEVELS — MONITORED POSITIONS"));
const stopData = [
  ["AVAV", "182.41", "165.00", "-9.5%", "Defense — binary event risk around earnings"],
  ["RKLB", "65.67", "55.00", "-16.2%", "High beta, speculative — tight stop"],
  ["KTOS", "67.00", "58.00", "-13.4%", "Defense tech — volatile"],
  ["CSWC", "22.26", "19.50", "-12.4%", "BDC — dividend yield floor support"],
  ["PFLT", "8.17",  "7.00",  "-14.3%", "BDC — monthly dividend, watch NAV"],
  ["V",    "301.01","275.00","-8.7%",  "MEGA POSITION — soft alert only"],
];
children.push(new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [900, 1500, 1500, 1200, 4260],
  rows: [
    row([
      cell(p("Symbol", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 900 }),
      cell(p("Current", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 1500 }),
      cell(p("Stop Level", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 1500 }),
      cell(p("Downside", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 1200 }),
      cell(p("Notes", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 4260 }),
    ]),
    ...stopData.map(([sym, curr, stop, down, note], i) => row([
      cell(p(sym, { bold: true, size: 9 }), { fill: i % 2 === 0 ? C.white : "F8F9FF", width: 900 }),
      cell(p("$" + curr, { size: 9 }), { fill: i % 2 === 0 ? C.white : "F8F9FF", width: 1500 }),
      cell(p("$" + stop, { size: 9, color: C.red }), { fill: i % 2 === 0 ? C.white : "F8F9FF", width: 1500 }),
      cell(p(down, { size: 9, color: C.red }), { fill: i % 2 === 0 ? C.white : "F8F9FF", width: 1200 }),
      cell(p(note, { size: 9, color: C.gray }), { fill: i % 2 === 0 ? C.white : "F8F9FF", width: 4260 }),
    ])),
  ],
}));

// SECTION 14 — ROUTING REFERENCE
children.push(...sectionHeader(14, "ROUTING REFERENCE (PERMANENT)"));
children.push(new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2500, 2500, 4360],
  rows: [
    ["Fidelity 401k",      "NetBenefits",          "workplaceservices.fidelity.com — Omnicom plan — $501,155"],
    ["Schwab Rollover IRA","Schwab.com ...258",     "WARNING: 50% in V — concentration risk critical"],
    ["Schwab Roth IRA",    "Schwab.com ...415",     "Small account — V + SCHG only"],
    ["Schwab Taxable",     "Schwab.com ...469",     "AI WWIII defense portfolio + income ETFs + BDCs"],
  ].map(([acct, route, note], i) => row([
    cell(p(acct, { bold: true, size: 9 }), { fill: C.lightGray, width: 2500 }),
    cell(p(route, { size: 9 }), { width: 2500 }),
    cell(p(note, { size: 9, color: C.gray }), { width: 4360 }),
  ])),
}));

// SECTION 15 — DIVIDEND CALENDAR
children.push(...sectionHeader(15, "DIVIDEND CALENDAR — INCOME TRACKER"));
const divByHolding = (analysis.dividends || {}).by_holding || [];
const divRows = divByHolding.slice(0, 15).map((d, i) => row([
  cell(p(d.symbol || "", { bold: true, size: 9 }), { fill: i % 2 === 0 ? C.white : "F8F9FF", width: 900 }),
  cell(p(d.account || "", { size: 9 }), { fill: i % 2 === 0 ? C.white : "F8F9FF", width: 2200 }),
  cell(p(`${(d.yield_pct || 0).toFixed(1)}%`, { size: 9 }), { fill: i % 2 === 0 ? C.white : "F8F9FF", width: 1000 }),
  cell(p(fmtUSD(d.annual_income), { size: 9, color: C.green }), { fill: i % 2 === 0 ? C.white : "F8F9FF", width: 1600 }),
  cell(p(fmtUSD(d.monthly_income), { size: 9 }), { fill: i % 2 === 0 ? C.white : "F8F9FF", width: 1500 }),
  cell(p(d.frequency || "", { size: 9 }), { fill: i % 2 === 0 ? C.white : "F8F9FF", width: 1200 }),
  cell(p(d.reinvest ? "✅ DRIP" : "💵 Cash", { size: 9 }), { fill: i % 2 === 0 ? C.white : "F8F9FF", width: 960 }),
]));
children.push(new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [900, 2200, 1000, 1600, 1500, 1200, 960],
  rows: [
    row([
      cell(p("Symbol", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 900 }),
      cell(p("Account", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 2200 }),
      cell(p("Yield", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 1000 }),
      cell(p("Annual $", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 1600 }),
      cell(p("Monthly", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 1500 }),
      cell(p("Frequency", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 1200 }),
      cell(p("Mode", { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 960 }),
    ]),
    ...divRows,
    row([
      cell(p("TOTAL", { bold: true, size: 9 }), { fill: C.lightGray, width: 900 }),
      cell(p("", { size: 9 }), { fill: C.lightGray, width: 2200 }),
      cell(p("", { size: 9 }), { fill: C.lightGray, width: 1000 }),
      cell(p(fmtUSD(divs.total_annual_income), { bold: true, size: 9, color: C.green }), { fill: C.lightGreen, width: 1600 }),
      cell(p(fmtUSD(divs.total_monthly_income), { bold: true, size: 9, color: C.green }), { fill: C.lightGreen, width: 1500 }),
      cell(p("", { size: 9 }), { fill: C.lightGray, width: 1200 }),
      cell(p("", { size: 9 }), { fill: C.lightGray, width: 960 }),
    ]),
  ],
}));

// SECTION 16 — CLIFF NOTES
children.push(...sectionHeader(16, "CLIFF NOTES — KEY METRICS GLOSSARY"));
[
  ["V (Visa)", "875 shares in Rollover IRA = 49.6% of that account. +702% gain (+$230K). Tax-free growth in IRA — but extreme concentration risk."],
  ["Beta", `Portfolio beta ${riskMetrics.weighted_beta || "N/A"} — moderate market sensitivity. Defense stocks lower beta; RKLB/KTOS raise it.`],
  ["DRIP", "Dividend Reinvestment Plan — enabled on most income positions. Creates small taxable lots in taxable account."],
  ["FIFO", "First-in-first-out cost basis. Oldest shares sold first. Oldest lots held since ~2023 estimated."],
  ["BDC", "Business Development Company — CSWC and PFLT pay high monthly dividends (10-11% yield). NAV-sensitive."],
  ["Tax Harvest", "Selling losing positions to realize losses for tax offset. Only beneficial in taxable account. 30-day wash sale rule applies."],
  ["ETF Look-Through", "Sector exposure analysis penetrates through ETF holdings to see true underlying concentration."],
].forEach(([term, desc]) => {
  children.push(p2([
    run(`${term}: `, { bold: true, size: 10 }),
    run(desc, { size: 10 }),
  ], { before: 60 }));
});

// SECTION 17 — AI STRATEGIC ANALYSIS
children.push(...sectionHeader(17, 'AI STRATEGIC ANALYSIS — Claude Sonnet 4.6'));
const aiRunType = AI_ANALYSIS.run_type || 'daily';
const aiDate = (AI_ANALYSIS.generated_at || '').slice(0, 10);
children.push(p(`Mode: ${aiRunType.toUpperCase()} | Generated: ${aiDate} | Refreshes: Monthly`, 
  { size: 9, italic: true, color: C.gray, before: 0 }));

const aiSections = [
  ['executive_summary',  'Executive Portfolio Summary'],
  ['dividend_strategy',  'Dividend Strategy & ETF/Stock Alternatives'],
  ['bond_strategy',      'Bond Strategy for Rollover IRA'],
  ['ira_opportunities',  'IRA Rollover Eligible Investments & Options'],
  ['v_concentration',    'V (Visa) Concentration Strategic Options'],
];

// ── Full markdown → docx renderer ─────────────────────────────────────────
function mdRuns(text) {
  // Convert inline **bold**, *italic*, `code` to TextRun array
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g);
  return parts.filter(Boolean).map(part => {
    if (part.startsWith('**') && part.endsWith('**'))
      return run(part.slice(2,-2), { bold: true, size: 10 });
    if (part.startsWith('*') && part.endsWith('*'))
      return run(part.slice(1,-1), { italic: true, size: 10 });
    if (part.startsWith('`') && part.endsWith('`'))
      return new TextRun({ text: part.slice(1,-1), font: 'Courier New', size: 18, color: C.navy });
    return run(part, { size: 10 });
  });
}

function mdTableToDocx(lines) {
  // Parse markdown pipe table lines into a Word table
  const dataRows = lines.filter(l => !l.match(/^\|[-:\s|]+\|?$/));
  if (dataRows.length === 0) return null;
  const parseRow = l => l.replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
  const headers = parseRow(dataRows[0]);
  const colW = Math.floor(9360 / Math.max(headers.length, 1));
  const colWidths = headers.map(() => colW);
  const tRows = [
    new TableRow({ children: headers.map((h,i) =>
      new TableCell({
        borders: allBorders(),
        width: { size: colWidths[i], type: WidthType.DXA },
        shading: shade(C.navy),
        margins: { top: 60, bottom: 60, left: 100, right: 100 },
        children: [new Paragraph({ children: [run(h, { bold: true, size: 9, color: C.white })] })]
      })
    ), tableHeader: true }),
    ...dataRows.slice(1).map((line, ri) => {
      const cells = parseRow(line);
      return new TableRow({ children: headers.map((_,ci) => {
        const txt = cells[ci] || '';
        const fill = ri % 2 === 0 ? C.white : 'F8F9FF';
        return new TableCell({
          borders: allBorders(),
          width: { size: colWidths[ci], type: WidthType.DXA },
          shading: shade(fill),
          margins: { top: 60, bottom: 60, left: 100, right: 100 },
          children: [new Paragraph({ children: mdRuns(txt), spacing: { before: 0, after: 0 } })]
        });
      })});
    }),
  ];
  return new Table({ width: { size: 9360, type: WidthType.DXA }, columnWidths: colWidths, rows: tRows });
}

function renderMarkdown(text, dest) {
  const lines = text.split('\n');
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    // Skip empty lines
    if (!trimmed) { i++; continue; }

    // Horizontal rule
    if (/^---+$/.test(trimmed)) {
      dest.push(hRule("CCCCCC")); i++; continue;
    }

    // Headers
    if (trimmed.startsWith('#### ')) {
      dest.push(p(trimmed.slice(5), { bold: true, size: 10, color: C.gray, before: 80 })); i++; continue;
    }
    if (trimmed.startsWith('### ')) {
      dest.push(p(trimmed.slice(4), { bold: true, size: 11, color: C.darkBlue, before: 120 })); i++; continue;
    }
    if (trimmed.startsWith('## ')) {
      dest.push(p(trimmed.slice(3), { bold: true, size: 12, color: C.navy, before: 140 })); i++; continue;
    }
    if (trimmed.startsWith('# ')) {
      dest.push(p(trimmed.slice(2), { bold: true, size: 13, color: C.darkBlue, before: 160 })); i++; continue;
    }

    // Code block (```)
    if (trimmed.startsWith('```')) {
      i++;
      const codeLines = [];
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i]); i++;
      }
      i++; // skip closing ```
      if (codeLines.length > 0) {
        dest.push(new Table({ width: { size: 9360, type: WidthType.DXA }, columnWidths: [9360], rows: [
          new TableRow({ children: [new TableCell({
            borders: allBorders("999999"),
            shading: shade("F5F5F5"),
            margins: { top: 80, bottom: 80, left: 160, right: 160 },
            children: codeLines.map(cl => new Paragraph({
              children: [new TextRun({ text: cl || ' ', font: 'Courier New', size: 16, color: C.gray })],
              spacing: { before: 0, after: 20 }
            }))
          })] })
        ]}));
      }
      continue;
    }

    // Markdown pipe table — collect all consecutive | lines
    if (trimmed.startsWith('|')) {
      const tableLines = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        tableLines.push(lines[i]); i++;
      }
      const tbl = mdTableToDocx(tableLines);
      if (tbl) dest.push(tbl);
      continue;
    }

    // Blockquote >
    if (trimmed.startsWith('> ')) {
      dest.push(new Paragraph({
        children: mdRuns(trimmed.slice(2)),
        spacing: { before: 40, after: 40 },
        indent: { left: 360 },
        border: { left: { style: BorderStyle.SINGLE, size: 12, color: C.accent, space: 8 } }
      }));
      i++; continue;
    }

    // Bullet list item
    if (/^[•*\-] /.test(trimmed)) {
      const body = trimmed.replace(/^[•*\-]\s+/, '');
      dest.push(new Paragraph({
        children: [run('• ', { bold: true, size: 10 }), ...mdRuns(body)],
        spacing: { before: 30, after: 30 },
        indent: { left: 240 }
      }));
      i++; continue;
    }

    // Numbered list
    if (/^\d+\.\s/.test(trimmed)) {
      const body = trimmed.replace(/^\d+\.\s+/, '');
      const num = trimmed.match(/^(\d+)/)[1];
      dest.push(new Paragraph({
        children: [run(num + '. ', { bold: true, size: 10, color: C.navy }), ...mdRuns(body)],
        spacing: { before: 30, after: 30 },
        indent: { left: 240 }
      }));
      i++; continue;
    }

    // Regular paragraph — parse inline formatting
    dest.push(new Paragraph({
      children: mdRuns(trimmed),
      spacing: { before: 40, after: 40 }
    }));
    i++;
  }
}

aiSections.forEach(([key, title]) => {
  const text = AI_ANALYSIS[key];
  if (!text) return;
  children.push(p(title, { bold: true, size: 11, color: C.darkBlue, before: 140 }));
  renderMarkdown(text, children);
});

// SECTION 18 — PERIOD PERFORMANCE
children.push(...sectionHeader(18, 'PERIOD PERFORMANCE'));
// perf_history uses .periods{}; legacy performance uses .portfolio_returns{}
const _ph = DATA.perf_history || {};
const _phPeriods = _ph.periods || {};
const _legPR = (PERFORMANCE.portfolio_returns) || {};
// Merge: perf_history periods preferred, fall back to legacy
function _getPeriod(pk) {
  const ph = _phPeriods[pk];
  if (ph && ph.change_pct != null) return { pct: ph.change_pct, dollar: ph.change, note: ph.start_date || '', src: ph.source || '' };
  const leg = _legPR[pk];
  if (leg && leg.pct != null) return { pct: leg.pct, dollar: leg.dollar, note: leg.prior_date || leg.note || '', src: 'snapshot' };
  return null;
}
const snapCount = _ph.snapshot_count || PERFORMANCE.snapshots_available || 0;
const allTime = PERFORMANCE.all_time || {};
const totalGainForPeriod = DATA.portfolio?.portfolio_totals?.total_gain || 0;
const totalGainPctForPeriod = DATA.portfolio?.portfolio_totals?.total_gain_pct || 0;
children.push(p(
  `Snapshots: ${snapCount} daily | All-Time Gain: ${fmtUSD(totalGainForPeriod)} (${fmtPct(totalGainPctForPeriod)})`,
  { size: 10, bold: true }));
const perfPeriods = ['1D','1W','1M','3M','6M','YTD','1Y'];
const perfRows = perfPeriods.map(period => {
  const d = _getPeriod(period);
  if (!d) {
    return row([
      cell(p(period, { bold: true, size: 10 }), { fill: C.lightGray, width: 900 }),
      cell(p('—', { size: 10, color: C.gray }), { width: 2000 }),
      cell(p('—', { size: 10, color: C.gray }), { width: 2500 }),
      cell(p('Accumulating...', { size: 9, color: C.gray }), { width: 3960 }),
    ]);
  }
  const pct = d.pct != null ? fmtPct(d.pct) : '—';
  const dollar = d.dollar != null ? fmtUSD(d.dollar) : '—';
  return row([
    cell(p(period, { bold: true, size: 10 }), { fill: C.lightGray, width: 900 }),
    cell(p(pct, { size: 10, color: d.pct > 0 ? C.green : d.pct < 0 ? C.red : C.gray }), { width: 2000 }),
    cell(p(dollar, { size: 10, color: d.dollar > 0 ? C.green : d.dollar < 0 ? C.red : C.gray }), { width: 2500 }),
    cell(p(String(d.note || '').slice(0,50), { size: 9, color: C.gray }), { width: 3960 }),
  ]);
});
if (perfRows.length > 0) {
  children.push(new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [900, 2000, 2500, 3960],
    rows: [
      row([
        cell(p('Period', { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 900 }),
        cell(p('Return %', { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 2000 }),
        cell(p('Return $', { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 2500 }),
        cell(p('Note', { bold: true, size: 9, color: C.white }), { fill: C.navy, width: 3960 }),
      ]),
      ...perfRows,
    ],
  }));
}
if (snapCount < 7) {
  children.push(p(`Period returns accumulate as daily snapshots build up. Currently ${snapCount} snapshot(s) saved.`,
    { size: 9, italic: true, color: C.gray, before: 80 }));
}


// ══════════════════════════════════════════════════════════════════════════
// SECTION: Technical Health Overview
// ══════════════════════════════════════════════════════════════════════════
const technical = DATA.technical || {};
const techPositions = technical.positions || {};
const techScore = technical.portfolio_score || 0;
const techGrade = technical.portfolio_grade || "yellow";
const techChanges = technical.signal_changes || [];
const techChartPaths = DATA.tech_chart_paths || {};

if (Object.keys(techPositions).length > 0) {
  children.push(hRule());
  children.push(heading2("Technical Analysis Report"));

  // Portfolio health summary
  const gradeColors = { green: C.green, yellow: C.amber, red: C.red };
  const gradeColor = gradeColors[techGrade] || C.amber;
  children.push(p(
    `Portfolio Technical Score: ${techScore.toFixed(0)}/100 (${techGrade.toUpperCase()})  ` +
    `|  Positions Analyzed: ${Object.keys(techPositions).length}  ` +
    `|  Signal Changes: ${techChanges.length}  ` +
    `|  Updated: ${technical.last_updated || ""}`,
    { size: 10, color: gradeColor, bold: true, before: 120 }
  ));

  // Critical signals
  const critSignals = (technical.critical_signals || []);
  if (critSignals.length > 0) {
    children.push(p("Critical Signals:", { size: 10, bold: true, color: C.red, before: 100 }));
    critSignals.forEach(sig => {
      children.push(p(`  🚨 [${sig.severity}] ${sig.msg}`, { size: 10, color: C.red }));
    });
  }

  // Health chart
  if (techChartPaths.health) {
    try {
      const fs2 = require('fs');
      const imgData = fs2.readFileSync(techChartPaths.health);
      const b64 = imgData.toString('base64');
      children.push(new Paragraph({
        children: [new ImageRun({
          data: Buffer.from(b64, 'base64'),
          transformation: { width: 580, height: 260 },
          type: 'png',
        })],
        spacing: { before: 120 },
      }));
    } catch(e) {}
  }

  // Technical status table
  const posEntries = Object.entries(techPositions)
    .sort((a, b) => (b[1].market_value || 0) - (a[1].market_value || 0))
    .slice(0, 20);

  if (posEntries.length > 0) {
    children.push(p("Position Technical Status:", { size: 10, bold: true, before: 120 }));
    const techRows = [
      new TableRow({ children: [
        cell("Symbol", true, 900), cell("Price", true, 900), cell("Score", true, 700),
        cell("vs SMA200", true, 1100), cell("RSI", true, 700),
        cell("From High", true, 1000), cell("Stop Suggest", true, 1200), cell("Intent", true, 1200),
      ], tableHeader: true })
    ];
    posEntries.forEach(([sym, d]) => {
      const above = d.above_sma200;
      const sma200val = d.sma200;
      const aboveStr = above === true 
        ? ("Above" + (sma200val ? " $" + sma200val.toFixed(0) : ""))
        : above === false 
        ? ("BELOW" + (sma200val ? " $" + sma200val.toFixed(0) : ""))
        : (sma200val ? "$" + sma200val.toFixed(0) : "—");
      const rsi = d.rsi ? d.rsi.toFixed(0) : "—";
      const fromHigh = d.pct_from_high != null ? d.pct_from_high.toFixed(1) + "%" : "—";
      const stopSug = d.suggested_stop ? "$" + d.suggested_stop.toFixed(2) : "—";
      techRows.push(new TableRow({ children: [
        cell(sym, false, 900),
        cell(d.price ? "$" + d.price.toFixed(2) : "—", false, 900),
        cell(d.tech_score ? d.tech_score.toString() : "—", false, 700),
        cell(aboveStr, false, 1100),
        cell(rsi, false, 700),
        cell(fromHigh, false, 1000),
        cell(stopSug, false, 1200),
        cell(d.intent || "—", false, 1200),
      ]}));
    });
    children.push(new Table({
      rows: techRows,
      width: { size: 100, type: WidthType.PERCENTAGE },
    }));
  }

  // SMA matrix and RSI charts
  if (techChartPaths.sma_matrix || techChartPaths.rsi) {
    children.push(p("Signal Analysis Charts:", { size: 10, bold: true, before: 120 }));
    ['sma_matrix', 'rsi', 'support_gap'].forEach(k => {
      if (!techChartPaths[k]) return;
      try {
        const fs2 = require('fs');
        const imgData = fs2.readFileSync(techChartPaths[k]);
        const b64 = imgData.toString('base64');
        children.push(new Paragraph({
          children: [new ImageRun({
            data: Buffer.from(b64, 'base64'),
            transformation: { width: 540, height: 220 },
            type: 'png',
          })],
          spacing: { before: 80 },
        }));
      } catch(e) {}
    });
  }

  // Top position price charts
  const priceChartKeys = Object.keys(techChartPaths).filter(k => k.startsWith('price_'));
  if (priceChartKeys.length > 0) {
    children.push(p("Position Price History (6-Month, with SMA Overlay):",
      { size: 10, bold: true, before: 120 }));
    priceChartKeys.forEach(k => {
      try {
        const fs2 = require('fs');
        const imgData = fs2.readFileSync(techChartPaths[k]);
        const b64 = imgData.toString('base64');
        children.push(new Paragraph({
          children: [new ImageRun({
            data: Buffer.from(b64, 'base64'),
            transformation: { width: 560, height: 200 },
            type: 'png',
          })],
          spacing: { before: 60 },
        }));
      } catch(e) {}
    });
  }
}

// ══════════════════════════════════════════════════════════════════════════
// SECTION: Stress Test Analysis
// ══════════════════════════════════════════════════════════════════════════
const stressData = DATA.stress || {};
const stressScenarios = stressData.scenarios || {};
const scenarioOrder = ["2022_rate_shock","2020_covid","visa_doj","defense_reversal"];

if (stressData.has_data && Object.keys(stressScenarios).length > 0) {
  children.push(hRule());
  children.push(heading2("Portfolio Stress Testing"));
  children.push(p(
    `Portfolio Value: $${(stressData.portfolio_value||0).toLocaleString()}  |  ` +
    `Worst Case: ${stressData.worst_case_scenario || ""}  |  ` +
    `Max Loss: $${Math.abs(stressData.worst_case_loss||0).toLocaleString()}`,
    { size: 10, bold: true, before: 100 }
  ));

  const stressRows = [
    new TableRow({ children: [
      cell("Scenario", true, 1800), cell("Description", true, 3000),
      cell("Loss $", true, 1200), cell("Loss %", true, 900),
      cell("Portfolio After", true, 1400), cell("Stops Save", true, 1200),
    ], tableHeader: true })
  ];
  scenarioOrder.forEach(sid => {
    const s = stressScenarios[sid];
    if (!s) return;
    stressRows.push(new TableRow({ children: [
      cell(s.name || sid, false, 1800),
      cell((s.description || "").substring(0, 80), false, 3000),
      cell(`-$${Math.abs(s.total_loss||0).toLocaleString()}`, false, 1200),
      cell(`${(s.loss_pct||0).toFixed(1)}%`, false, 900),
      cell(`$${(s.total_value_after||0).toLocaleString()}`, false, 1400),
      cell(`$${(s.stops_would_save||0).toLocaleString()}`, false, 1200),
    ]}));
  });
  children.push(new Table({
    rows: stressRows,
    width: { size: 100, type: WidthType.PERCENTAGE },
  }));
  children.push(p(
    "Note: Setting stops reduces maximum loss significantly. " +
    "Review stop levels in the Risk Manager tab and set stops for all major positions.",
    { size: 9, italic: true, color: C.gray, before: 80 }
  ));
}

// ══════════════════════════════════════════════════════════════════════════
// SECTION: Retirement Roadmap Summary
// ══════════════════════════════════════════════════════════════════════════
const retData = DATA.retirement || {};
const txData  = DATA.tax_projection || {};

if (retData.key_dates) {
  children.push(hRule());
  children.push(heading2("Retirement Roadmap"));

  const kd      = retData.key_dates || {};
  const accts   = retData.accounts || {};
  const gw      = retData.golden_window || {};
  const loan    = retData.loan || {};
  const txTax   = txData.tax || {};
  const txRoth  = txData.roth || {};

  const retRows = [
    ["Current Age",            retData.current_age ? retData.current_age.toFixed(1) : ""],
    ["Total Portfolio",         `$${(accts.total||0).toLocaleString()}`],
    ["Roth IRA Balance",        `$${(accts.roth||0).toLocaleString()} (${accts.roth_pct||0}% of portfolio)`],
    ["Traditional IRA/401k",   `$${(accts.traditional||0).toLocaleString()} — target $0 at age 73`],
    ["Golden Window",          `${kd.years_to_golden||""} years (${kd.days_to_golden||""} days)`],
    ["Roth at Golden Window",  `$${(gw.projected_roth_at_start||0).toLocaleString()}`],
    ["Optimal Annual Conversion", `$${(gw.optimal_annual_conversion||25000).toLocaleString()}/yr in Golden Window`],
    ["401k Loan Balance",      `$${(loan.balance||0).toLocaleString()} — deadline ${loan.deadline||""} (${loan.days_remaining||0}d)`],
    ["Current Tax Bracket",    txTax.current_bracket || ""],
    ["Estimated Federal Tax",  `$${(txTax.federal_tax||0).toLocaleString()}`],
    ["Total Tax Estimate",     `$${(txTax.total_est||0).toLocaleString()}`],
    ["IRMAA Exposure",         `$${(txData.irmaa||{}).annual_surcharge||0}/yr`],
    ["Remaining Roth Capacity",`$${(txRoth.remaining_capacity||0).toLocaleString()} before bracket increase`],
  ];

  const retTableRows = [
    new TableRow({ children: [cell("Metric", true, 3600), cell("Value", true, 5900)], tableHeader: true })
  ];
  retRows.forEach(([k, v]) => {
    retTableRows.push(new TableRow({ children: [cell(k, false, 3600), cell(String(v), false, 5900)] }));
  });
  children.push(new Table({
    rows: retTableRows,
    width: { size: 100, type: WidthType.PERCENTAGE },
  }));

  children.push(p(
    "Golden Window Strategy: Between ages 68.5 (disability ends) and 73 (RMD age), " +
    "income drops to Social Security only (~$3,800/mo). This is the prime Roth conversion window " +
    "— maximize conversions in this period to reach $0 traditional IRA balance at RMD age.",
    { size: 10, italic: false, before: 100 }
  ));
}


// FOOTER DISCLAIMER
children.push(hRule());
children.push(p("For informational purposes only. Not investment advice. | Portfolio Intelligence v1.0 | Trade AI v12.1d | Data as of " + asOf,
  { size: 8, italic: true, color: C.gray, align: AlignmentType.CENTER, before: 120 }));

// ── Build Document ────────────────────────────────────────────────────────────
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 720, right: 720, bottom: 720, left: 720 },
      },
    },
    children,
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(OUTPUT, buf);
  console.log("Brief generated: " + OUTPUT);
}).catch(err => {
  console.error("Error:", err);
  process.exit(1);
});

// ══════════════════════════════════════════════════════════════════════════
// NEW SECTION: Technical Health Overview
// ══════════════════════════════════════════════════════════════════════════
