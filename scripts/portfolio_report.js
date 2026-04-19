// portfolio_report.js — Trade AI v12 Personal Portfolio Strategy Report
// Generates professional wealth-strategy DOCX with embedded charts
// Output: 12-14 page board-ready document

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType,
  VerticalAlign, PageBreak, Header, Footer, ImageRun, PageNumber,
  Tab, TabStopPosition, TabStopType
} = require('docx');
const fs = require('fs');
const { createCanvas } = require('canvas');

// ═══════════════════════════════════════════════════════════════════
// DATA LOADING
// ═══════════════════════════════════════════════════════════════════
const DATA        = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const OUTPUT      = process.argv[3];
const portfolio   = DATA.portfolio     || {};
const analysis    = DATA.analysis      || {};
const tax         = DATA.tax           || {};
const rebalancing = DATA.rebalancing   || {};
const risk        = DATA.risk          || {};
const perf        = DATA.performance   || {};
const perfHistory = DATA.perf_history  || {};
const aiAnalysis  = DATA.ai_analysis   || {};
const technical   = DATA.technical     || {};
const stress      = DATA.stress        || {};
const retirement  = DATA.retirement    || {};
const taxProj     = DATA.tax_projection|| {};

const totals    = portfolio.portfolio_totals || {};
const holdings  = portfolio.holdings || [];
const acctSumm  = portfolio.account_summaries || {};
const sectors   = portfolio.resolved_sectors || [];
const periods   = (perfHistory.periods || perf.periods || {});

// ═══════════════════════════════════════════════════════════════════
// COLORS & STYLE CONSTANTS
// ═══════════════════════════════════════════════════════════════════
const C = {
  navy: '0D1B4F', darkBlue: '1A237E', accent: '2979FF', slate: '37474F',
  green: '1B5E20', greenLight: 'E8F5E9', greenMid: '4CAF50',
  red: 'C62828', redLight: 'FFEBEE',
  amber: 'F57F17', amberLight: 'FFF8E1',
  gold: 'C9A94E', goldLight: 'FFF9E5',
  gray: '616161', grayLight: 'F5F5F5', grayMid: '9E9E9E',
  white: 'FFFFFF', black: '212121',
  bg1: 'FAFBFC', bg2: 'F0F2F5',
};

// ═══════════════════════════════════════════════════════════════════
// CHART GENERATION (Canvas → PNG Buffer)
// ═══════════════════════════════════════════════════════════════════
function drawDonut(dataArr, w=480, h=320, title='') {
  const canvas = createCanvas(w, h);
  const ctx = canvas.getContext('2d');
  const total = dataArr.reduce((s,d) => s + d.value, 0);
  const cx = h/2, cy = h/2, r = h/2 - 40;
  const colors = ['#1A237E','#2979FF','#F57F17','#C62828','#4CAF50','#7B1FA2','#00838F','#E65100'];

  ctx.fillStyle = '#FFFFFF'; ctx.fillRect(0, 0, w, h);
  if (title) { ctx.fillStyle = '#212121'; ctx.font = 'bold 14px Arial'; ctx.fillText(title, 10, 20); }

  let angle = -Math.PI / 2;
  dataArr.forEach((d, i) => {
    const slice = (d.value / total) * Math.PI * 2;
    ctx.beginPath(); ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, angle, angle + slice);
    ctx.fillStyle = d.color || colors[i % colors.length]; ctx.fill();
    angle += slice;
  });
  // Center hole
  ctx.beginPath(); ctx.arc(cx, cy, r * 0.55, 0, Math.PI * 2);
  ctx.fillStyle = '#FFFFFF'; ctx.fill();
  // Center text
  ctx.fillStyle = '#212121'; ctx.font = 'bold 18px Arial'; ctx.textAlign = 'center';
  ctx.fillText(fUSD(total), cx, cy + 6);

  // Legend
  let ly = 40;
  dataArr.forEach((d, i) => {
    ctx.fillStyle = d.color || colors[i % colors.length];
    ctx.fillRect(h + 20, ly, 12, 12);
    ctx.fillStyle = '#616161'; ctx.font = '11px Arial'; ctx.textAlign = 'left';
    ctx.fillText(`${d.label}  ${fUSD(d.value)}  (${(d.value/total*100).toFixed(1)}%)`, h + 38, ly + 10);
    ly += 20;
  });
  return canvas.toBuffer('image/png');
}

function drawHBar(dataArr, w=520, h=null, title='') {
  const barH = 28, gap = 6, padTop = title ? 30 : 10, padBot = 10, padLeft = 90, padRight = 80;
  h = h || (padTop + dataArr.length * (barH + gap) + padBot);
  const canvas = createCanvas(w, h);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#FFFFFF'; ctx.fillRect(0, 0, w, h);
  if (title) { ctx.fillStyle = '#212121'; ctx.font = 'bold 13px Arial'; ctx.fillText(title, 10, 20); }
  const maxVal = Math.max(...dataArr.map(d => d.value), 1);
  const barArea = w - padLeft - padRight;
  const colors = ['#1A237E','#2979FF','#4CAF50','#F57F17','#C62828','#7B1FA2','#00838F','#E65100','#558B2F','#AD1457'];

  dataArr.forEach((d, i) => {
    const y = padTop + i * (barH + gap);
    const bw = (d.value / maxVal) * barArea;
    // Label
    ctx.fillStyle = '#212121'; ctx.font = '11px Arial'; ctx.textAlign = 'right';
    ctx.fillText(d.label, padLeft - 8, y + barH/2 + 4);
    // Bar
    ctx.fillStyle = d.color || colors[i % colors.length];
    ctx.beginPath(); ctx.roundRect(padLeft, y, Math.max(bw, 2), barH, 4); ctx.fill();
    // Value
    ctx.fillStyle = '#616161'; ctx.font = 'bold 11px Arial'; ctx.textAlign = 'left';
    ctx.fillText(d.display || fUSD(d.value), padLeft + bw + 6, y + barH/2 + 4);
  });
  return canvas.toBuffer('image/png');
}

function drawColumnChart(dataArr, w=520, h=260, title='') {
  const canvas = createCanvas(w, h);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#FFFFFF'; ctx.fillRect(0, 0, w, h);
  if (title) { ctx.fillStyle = '#212121'; ctx.font = 'bold 13px Arial'; ctx.fillText(title, 10, 20); }
  const padTop = title ? 40 : 20, padBot = 40, padLeft = 50, padRight = 20;
  const maxVal = Math.max(...dataArr.map(d => Math.abs(d.value)), 1);
  const chartH = h - padTop - padBot;
  const chartW = w - padLeft - padRight;
  const colW = chartW / dataArr.length * 0.65;
  const colGap = chartW / dataArr.length;
  const baseline = padTop + chartH;

  // Zero line
  ctx.strokeStyle = '#E0E0E0'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(padLeft, baseline); ctx.lineTo(w - padRight, baseline); ctx.stroke();

  dataArr.forEach((d, i) => {
    const x = padLeft + i * colGap + (colGap - colW) / 2;
    const barH = (d.value / maxVal) * chartH * 0.85;
    const color = d.value >= 0 ? '#4CAF50' : '#C62828';
    ctx.fillStyle = color;
    if (d.value >= 0) {
      ctx.beginPath(); ctx.roundRect(x, baseline - barH, colW, barH, [4, 4, 0, 0]); ctx.fill();
    } else {
      ctx.beginPath(); ctx.roundRect(x, baseline, colW, Math.abs(barH), [0, 0, 4, 4]); ctx.fill();
    }
    // Label
    ctx.fillStyle = '#616161'; ctx.font = '10px Arial'; ctx.textAlign = 'center';
    ctx.fillText(d.label, x + colW/2, baseline + 16);
    // Value
    ctx.fillStyle = color; ctx.font = 'bold 10px Arial';
    const vy = d.value >= 0 ? baseline - barH - 6 : baseline + Math.abs(barH) + 14;
    ctx.fillText(d.display || `${d.value >= 0 ? '+' : ''}${d.value.toFixed(1)}%`, x + colW/2, vy);
  });
  return canvas.toBuffer('image/png');
}

function drawTimeline(events, w=520, h=100) {
  const canvas = createCanvas(w, h);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#FFFFFF'; ctx.fillRect(0, 0, w, h);
  const padX = 40, lineY = 40;
  const lineW = w - padX * 2;

  // Line
  ctx.strokeStyle = '#E0E0E0'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(padX, lineY); ctx.lineTo(w - padX, lineY); ctx.stroke();

  events.forEach((e, i) => {
    const x = padX + (i / (events.length - 1)) * lineW;
    // Dot
    ctx.beginPath(); ctx.arc(x, lineY, 6, 0, Math.PI * 2);
    ctx.fillStyle = e.done ? '#4CAF50' : e.active ? '#2979FF' : '#9E9E9E'; ctx.fill();
    ctx.strokeStyle = '#FFFFFF'; ctx.lineWidth = 2; ctx.stroke();
    // Label
    ctx.fillStyle = '#212121'; ctx.font = 'bold 10px Arial'; ctx.textAlign = 'center';
    ctx.fillText(e.label, x, lineY + 20);
    ctx.fillStyle = '#9E9E9E'; ctx.font = '9px Arial';
    ctx.fillText(e.date || '', x, lineY + 32);
    if (e.detail) { ctx.fillStyle = '#2979FF'; ctx.fillText(e.detail, x, lineY + 44); }
  });
  return canvas.toBuffer('image/png');
}

function drawProgressBar(current, target, w=480, h=60, label='') {
  const canvas = createCanvas(w, h);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#FFFFFF'; ctx.fillRect(0, 0, w, h);
  const pct = Math.min(current / target, 1);
  const barY = 25, barH = 20, padX = 10;
  // Label
  ctx.fillStyle = '#212121'; ctx.font = '11px Arial'; ctx.textAlign = 'left';
  ctx.fillText(`${label}  ${fUSD(current)} / ${fUSD(target)}  (${(pct*100).toFixed(0)}%)`, padX, 16);
  // Background
  ctx.fillStyle = '#E8EAF6';
  ctx.beginPath(); ctx.roundRect(padX, barY, w - padX*2, barH, 6); ctx.fill();
  // Fill
  ctx.fillStyle = pct >= 0.9 ? '#4CAF50' : pct >= 0.5 ? '#2979FF' : '#F57F17';
  ctx.beginPath(); ctx.roundRect(padX, barY, (w - padX*2) * pct, barH, 6); ctx.fill();
  // Gap text
  ctx.fillStyle = '#C62828'; ctx.font = 'bold 10px Arial'; ctx.textAlign = 'right';
  ctx.fillText(`Gap: ${fUSD(target - current)}`, w - padX, h - 4);
  return canvas.toBuffer('image/png');
}

function drawGauge(value, max, threshold, w=240, h=160, label='') {
  const canvas = createCanvas(w, h);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#FFFFFF'; ctx.fillRect(0, 0, w, h);
  const cx = w/2, cy = h - 30, r = Math.min(w/2, h) - 40;
  const pct = Math.min(value / max, 1);
  const color = threshold && value > threshold ? '#C62828' : value > max * 0.7 ? '#F57F17' : '#4CAF50';

  // Background arc
  ctx.strokeStyle = '#E8EAF6'; ctx.lineWidth = 14; ctx.lineCap = 'round';
  ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, 0); ctx.stroke();
  // Value arc
  ctx.strokeStyle = color;
  ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, Math.PI + pct * Math.PI); ctx.stroke();
  // Threshold tick
  if (threshold) {
    const thAngle = Math.PI + (threshold / max) * Math.PI;
    ctx.strokeStyle = '#F57F17'; ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cx + (r-12) * Math.cos(thAngle), cy + (r-12) * Math.sin(thAngle));
    ctx.lineTo(cx + (r+12) * Math.cos(thAngle), cy + (r+12) * Math.sin(thAngle));
    ctx.stroke();
  }
  // Value text
  ctx.fillStyle = color; ctx.font = 'bold 22px Arial'; ctx.textAlign = 'center';
  ctx.fillText(`${value.toFixed(1)}%`, cx, cy - 4);
  if (label) { ctx.fillStyle = '#616161'; ctx.font = '10px Arial'; ctx.fillText(label, cx, cy + 14); }
  return canvas.toBuffer('image/png');
}

// ═══════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════
const fUSD = (v,d=0) => v == null ? '—' : '$' + Number(v).toLocaleString('en-US', {minimumFractionDigits:d, maximumFractionDigits:d});
const fPct = (v,d=1) => v == null ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(d)}%`;

function shade(fill) { return { fill, type: ShadingType.CLEAR }; }
function border(color='CCCCCC', size=4) { return { style: BorderStyle.SINGLE, size, color }; }
function noBorder() { const n = {style:BorderStyle.NONE,size:0,color:'FFFFFF'}; return {top:n,bottom:n,left:n,right:n}; }
function allBorders(c='E0E0E0',s=4) { const b = border(c,s); return {top:b,bottom:b,left:b,right:b}; }

function run(text, opts={}) {
  return new TextRun({ text: String(text||''), bold:opts.bold, italics:opts.italic,
    color:opts.color||C.black, size:(opts.size||10)*2, font:opts.font||'Segoe UI',
    underline:opts.underline?{}:undefined });
}

function p(text, opts={}) {
  return new Paragraph({
    alignment: opts.align || AlignmentType.LEFT,
    spacing: { before: opts.before||0, after: opts.after||80 },
    indent: opts.indent ? { left: opts.indent } : undefined,
    children: [run(text, opts)],
  });
}

function heading(text, level, opts={}) {
  return new Paragraph({
    heading: level, spacing: { before: opts.before||200, after: opts.after||80 },
    children: [run(text, { bold:true, size: level===HeadingLevel.HEADING_1?16:level===HeadingLevel.HEADING_2?13:11,
      color: opts.color||C.darkBlue, ...opts })],
  });
}

function pageBreak() { return new Paragraph({ children: [new TextRun({ children: [new PageBreak()] })] }); }

function imgPara(buffer, w=580, h=300) {
  return new Paragraph({
    spacing: { before: 120, after: 120 },
    alignment: AlignmentType.CENTER,
    children: [new ImageRun({ data: buffer, transformation: { width: w, height: h }, type: 'png' })],
  });
}

function calloutBox(text, borderColor=C.accent, bgColor=C.bg2) {
  return new Table({ width:{size:9360,type:WidthType.DXA}, columnWidths:[9360], rows:[
    new TableRow({ children:[new TableCell({
      borders: { left:border(borderColor,16), top:border('E0E0E0',2), bottom:border('E0E0E0',2), right:border('E0E0E0',2) },
      shading: shade(bgColor),
      margins: { top:100, bottom:100, left:200, right:200 },
      children: [p(text, { size:10, color:C.slate, italic:true })],
    })] })
  ]});
}

function dataQualityFlag(text) { return calloutBox('Data Integrity: ' + text, C.amber, C.amberLight); }

function statusBadge(status) {
  const colors = {done:C.green, pending:C.amber, blocked:C.red, info:C.accent};
  const labels = {done:'COMPLETE', pending:'PENDING', blocked:'ACTION NEEDED', info:'MONITOR'};
  return run(` [${labels[status]||status.toUpperCase()}] `, { bold:true, size:8, color:colors[status]||C.gray });
}

function kpiRow(pairs) {
  // pairs = [[label, value, color], ...]
  const colW = Math.floor(9360 / pairs.length);
  return new Table({ width:{size:9360,type:WidthType.DXA}, columnWidths: pairs.map(() => colW), rows:[
    new TableRow({ children: pairs.map(([label, value, color]) => new TableCell({
      borders: allBorders('E8EAF6',2),
      shading: shade(C.bg1),
      margins: { top:80, bottom:80, left:120, right:120 },
      verticalAlign: VerticalAlign.CENTER,
      width: { size:colW, type:WidthType.DXA },
      children: [
        p(label, { size:8, color:C.grayMid, bold:false, after:20 }),
        p(value, { size:14, bold:true, color: color||C.darkBlue, before:0 }),
      ],
    })) })
  ]});
}

function styledTable(headers, rows, opts={}) {
  const colW = Math.floor(9360 / headers.length);
  const hdrRow = new TableRow({ tableHeader:true, children: headers.map(h => new TableCell({
    borders: allBorders(C.darkBlue, 2),
    shading: shade(C.darkBlue),
    margins: { top:60, bottom:60, left:100, right:100 },
    width: { size:colW, type:WidthType.DXA },
    children: [p(h, { bold:true, size:9, color:C.white, after:0 })],
  })) });
  const dataRows = rows.map((cells, ri) => new TableRow({ children: cells.map((cell, ci) => new TableCell({
    borders: allBorders('E0E0E0', 2),
    shading: shade(ri % 2 === 0 ? C.white : C.bg1),
    margins: { top:50, bottom:50, left:100, right:100 },
    width: { size:colW, type:WidthType.DXA },
    children: [p(String(cell||''), { size:9, color: opts.colorFn ? opts.colorFn(cell,ci,ri) : C.black, after:0 })],
  })) }));
  return new Table({ width:{size:9360,type:WidthType.DXA}, columnWidths:headers.map(()=>colW), rows:[hdrRow,...dataRows] });
}

// ═══════════════════════════════════════════════════════════════════
// MARKDOWN → DOCX RENDERER (for AI sections)
// ═══════════════════════════════════════════════════════════════════
function renderMarkdown(text, dest) {
  if (!text) return;
  const lines = String(text).split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    const clean = line.replace(/\*\*/g, '');
    // Checklist
    if (/^[-•*]?\s*[✅❌⚠️]/.test(line)) {
      const rest = clean.replace(/^[-•*]?\s*[✅❌⚠️]\s*/, '');
      const icon = line.includes('✅') ? '✓' : line.includes('❌') ? '✗' : '!';
      const col = icon==='✓' ? C.green : icon==='✗' ? C.red : C.amber;
      dest.push(new Paragraph({
        spacing: { before:40, after:40 }, indent: { left:240 },
        border: { left: { style:BorderStyle.SINGLE, size:12, color:col, space:8 } },
        children: [run(`${icon} `, {bold:true, size:10, color:col}), run(rest, {size:10})],
      }));
      continue;
    }
    // RECOMMENDATION/ACTION
    if (/^(RECOMMENDATION|ACTION|KEY RISK|OPTIMAL|PRIORITY):/i.test(clean)) {
      const ci = clean.indexOf(':');
      const lbl = clean.slice(0,ci), rest = clean.slice(ci+1).trim();
      const col = /RISK/i.test(lbl) ? C.red : C.green;
      dest.push(new Paragraph({
        spacing: { before:60, after:60 }, indent: { left:120 },
        border: { left: { style:BorderStyle.SINGLE, size:16, color:col, space:8 } },
        children: [run(`${lbl}: `, {bold:true, size:10, color:col}), run(rest, {size:10})],
      }));
      continue;
    }
    // Headers
    if (clean.startsWith('# ')) { dest.push(heading(clean.slice(2), HeadingLevel.HEADING_2, {before:160})); continue; }
    if (clean.startsWith('## ')) { dest.push(heading(clean.slice(3), HeadingLevel.HEADING_3, {before:120})); continue; }
    if (clean.startsWith('### ')) { dest.push(p(clean.slice(4), {bold:true, size:11, color:C.darkBlue, before:100})); continue; }
    // Bullet
    if (/^[•\-*→▸]\s/.test(clean)) {
      dest.push(new Paragraph({
        spacing: { before:30, after:30 }, indent: { left:240 },
        children: [run('• ', {bold:true, size:10}), run(clean.replace(/^[•\-*→▸]\s+/,''), {size:10})],
      }));
      continue;
    }
    // Numbered
    if (/^\d+[\.\)]\s/.test(clean)) {
      const num = clean.match(/^(\d+)/)[1];
      dest.push(new Paragraph({
        spacing: { before:30, after:30 }, indent: { left:240 },
        children: [run(`${num}. `, {bold:true, size:10, color:C.darkBlue}), run(clean.replace(/^\d+[\.\)]\s+/,''), {size:10})],
      }));
      continue;
    }
    // ALL CAPS
    if (clean === clean.toUpperCase() && clean.length > 4 && /[A-Z]/.test(clean)) {
      dest.push(p(clean, {bold:true, size:10, color:C.amber, before:100}));
      continue;
    }
    // Normal
    dest.push(p(clean, { size:10, color:C.slate }));
  }
}

// ═══════════════════════════════════════════════════════════════════
// DERIVED DATA
// ═══════════════════════════════════════════════════════════════════
const totalVal = totals.total_value || 0;
const totalGain = totals.total_gain || 0;
const totalGainPct = totals.total_gain_pct || 0;
const dayChange = totals.day_change || 0;
const accts = [
  { key:'fidelity_401k', label:'Fidelity 401k', type:'401(k)', val: acctSumm.fidelity_401k?.total_value||0, gain: acctSumm.fidelity_401k?.total_gain||0 },
  { key:'schwab_rollover_ira', label:'Schwab Rollover IRA', type:'Rollover IRA', val: acctSumm.schwab_rollover_ira?.total_value||0, gain: acctSumm.schwab_rollover_ira?.total_gain||0 },
  { key:'schwab_roth', label:'Schwab Roth IRA', type:'Roth IRA', val: acctSumm.schwab_roth?.total_value||0, gain: acctSumm.schwab_roth?.total_gain||0 },
  { key:'schwab_taxable', label:'Schwab Taxable', type:'Taxable', val: acctSumm.schwab_taxable?.total_value||0, gain: acctSumm.schwab_taxable?.total_gain||0 },
];
const rothBal = accts[2].val;
const tradBal = accts[0].val + accts[1].val;
const kd = retirement.key_dates || {};
const gw = retirement.golden_window || {};
const ytdPct = periods.YTD?.change_pct;
const y1Pct = periods['1Y']?.change_pct;

// Holdings aggregated by symbol
const bySym = {};
holdings.forEach(h => { const s = h.symbol||''; bySym[s] = (bySym[s]||0) + (h.market_value||0); });
const topHoldings = Object.entries(bySym).sort((a,b) => b[1]-a[1]).slice(0, 12);
const vPct = (bySym['V']||0) / totalVal * 100;

// Dividend totals from analysis
const divByHolding = analysis.dividends?.by_holding || [];
const divTotal = divByHolding.reduce((s,d) => s + (d.annual_income||0), 0) || analysis.dividends?.total_annual_income || 0;

// ═══════════════════════════════════════════════════════════════════
// BUILD DOCUMENT SECTIONS
// ═══════════════════════════════════════════════════════════════════
const children = [];

// ── PAGE 1: COVER ─────────────────────────────────────────────────
children.push(
  new Paragraph({ spacing: { before: 3000 } }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
    children: [run('Personal Portfolio Strategy Report', { bold:true, size:28, color:C.darkBlue, font:'Segoe UI Light' })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 400 },
    children: [run('Portfolio Structure, Risk, Retirement Tax Planning, and Income Strategy', { size:12, color:C.gray, italic:true })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [
    run(`Portfolio Value: ${fUSD(totalVal)}`, { size:18, bold:true, color:C.darkBlue }),
  ]}),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 200, after: 200 }, children: [
    run(`Report Date: ${new Date().toISOString().slice(0,10)}`, { size:10, color:C.grayMid }),
  ]}),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 600 }, children: [
    run('CONFIDENTIAL — PREPARED FOR JOHN W. WHITING', { size:9, color:C.grayMid, bold:true }),
  ]}),
  pageBreak(),
);

// ── PAGE 2: EXECUTIVE SUMMARY ─────────────────────────────────────
children.push(
  heading('Executive Summary', HeadingLevel.HEADING_1),
  kpiRow([
    ['Total Portfolio', fUSD(totalVal), C.darkBlue],
    ['All-Time Gain', `${fUSD(totalGain)} (${fPct(totalGainPct)})`, C.green],
    ['Roth IRA', fUSD(rothBal), C.accent],
  ]),
  new Paragraph({ spacing: { before: 80 } }),
  kpiRow([
    ['Traditional / Pre-Tax', fUSD(tradBal)],
    ['Annual Dividends', fUSD(divTotal), divTotal < 28000 ? C.amber : C.green],
    ['YTD Return', fPct(ytdPct), ytdPct >= 0 ? C.green : C.red],
  ]),
  new Paragraph({ spacing: { before: 80 } }),
  kpiRow([
    ['Current Age', `${(retirement.current_age||58.7).toFixed(1)}`, C.darkBlue],
    ['Golden Window', `${(kd.years_to_golden||9.8).toFixed(1)} years`, C.accent],
    ['1Y Return', fPct(y1Pct), y1Pct >= 0 ? C.green : C.red],
  ]),
  new Paragraph({ spacing: { before: 120 } }),
  calloutBox('Primary objective: reduce concentration risk, improve income resilience, and reposition retirement assets for tax-efficient conversion over the Golden Window.'),
);

// AI Executive Summary
if (aiAnalysis.executive_summary) {
  children.push(heading('Strategist Assessment', HeadingLevel.HEADING_2, { before:160 }));
  renderMarkdown(aiAnalysis.executive_summary, children);
}
children.push(pageBreak());

// ── PAGE 3: PORTFOLIO STRUCTURE ───────────────────────────────────
children.push(heading('Portfolio Structure by Account', HeadingLevel.HEADING_1));
const acctDonut = drawDonut(
  accts.map((a,i) => ({ label:a.label, value:a.val, color:['#1A237E','#2979FF','#4CAF50','#F57F17'][i] })),
  500, 280, 'Account Allocation'
);
children.push(imgPara(acctDonut, 480, 260));
children.push(styledTable(
  ['Account', 'Type', 'Value', 'Gain/Loss'],
  accts.map(a => [a.label, a.type, fUSD(a.val), a.gain ? `${fUSD(a.gain)} (${a.val > 0 ? fPct(a.gain/a.val*100) : '—'})` : '—']),
));
children.push(calloutBox('Over 90% of assets are in tax-advantaged retirement accounts, making tax-location strategy central to long-term planning.'));
children.push(pageBreak());

// ── PAGE 4: TOP HOLDINGS & CONCENTRATION ──────────────────────────
children.push(heading('Top Holdings and Concentration Risk', HeadingLevel.HEADING_1));
const holdBars = drawHBar(
  topHoldings.map(([sym, mv]) => ({ label:sym, value:mv })),
  520, null, 'Top Holdings by Market Value'
);
children.push(imgPara(holdBars, 500, Math.min(topHoldings.length * 34 + 40, 450)));

if (vPct > 13) {
  children.push(dataQualityFlag(`V concentration at ${vPct.toFixed(1)}% exceeds 13% threshold. Source contains conflicting guidance: "trim to 12-13%" vs "trim 30%". Verify target before execution.`));
}

// Sector exposure
if (sectors.length > 0) {
  children.push(heading('Sector Exposure (ETF Look-Through)', HeadingLevel.HEADING_2));
  const secDonut = drawDonut(
    sectors.slice(0,8).map((s,i) => ({label:s.sector, value:s.value, color:['#1A237E','#2979FF','#F57F17','#C62828','#4CAF50','#7B1FA2','#00838F','#558B2F'][i]})),
    500, 280, ''
  );
  children.push(imgPara(secDonut, 480, 260));
}
children.push(pageBreak());

// ── PAGE 5: PERFORMANCE REVIEW ────────────────────────────────────
children.push(heading('Performance Review', HeadingLevel.HEADING_1));
const perfLabels = ['1W','1M','3M','6M','YTD','1Y'];
const perfData = perfLabels.map(lbl => ({
  label: lbl,
  value: periods[lbl]?.change_pct || 0,
  display: fPct(periods[lbl]?.change_pct),
}));
const perfChart = drawColumnChart(perfData, 520, 240, 'Period Returns (%)');
children.push(imgPara(perfChart, 500, 230));
children.push(styledTable(
  ['Period', 'Return %', 'Return $', 'Source'],
  perfLabels.map(lbl => {
    const pd = periods[lbl] || {};
    return [lbl, fPct(pd.change_pct), fUSD(pd.change), pd.source || '—'];
  }),
  { colorFn: (v, ci) => ci === 1 && v && v.startsWith('+') ? C.green : ci === 1 && v && v.startsWith('-') ? C.red : C.black }
));
children.push(pageBreak());

// ── PAGE 6: RETIREMENT TAX POSITION ──────────────────────────────
children.push(heading('Retirement Tax Position', HeadingLevel.HEADING_1));
const retDonut = drawDonut([
  {label:'Traditional IRA / 401k', value:tradBal, color:'#F57F17'},
  {label:'Roth IRA', value:rothBal, color:'#2979FF'},
], 480, 260, 'Tax Bucket Split');
children.push(imgPara(retDonut, 460, 250));

children.push(calloutBox('Target: Reduce traditional IRA / 401k balance to $0 by age 73 through systematic Roth conversions.'));

const timeline = drawTimeline([
  {label:'Now', date:'Age 58.7', detail:'$35K done', done:true},
  {label:'Rollover', date:'2027', detail:'$533K 401k'},
  {label:'FRA', date:'2034', detail:'SS at 67'},
  {label:'Golden Start', date:'Feb 2036', detail:'Disability ends', active:true},
  {label:'RMD', date:'Aug 2040', detail:'Age 73'},
], 520, 100);
children.push(imgPara(timeline, 500, 95));

if (!taxProj.tax?.estimated_federal) {
  children.push(dataQualityFlag('Current tax bracket and estimated federal tax are not populated in source data. Flag as incomplete.'));
}
children.push(pageBreak());

// ── PAGE 7: GOLDEN WINDOW STRATEGY ──────────────────────────────
children.push(heading('Golden Window Conversion Strategy', HeadingLevel.HEADING_1));
children.push(p('Tax arbitrage: convert at 22% now to avoid 24%+ forced RMD distributions later.', { italic:true, color:C.accent, size:11 }));

const scenarioChart = drawHBar([
  {label:'$0 add\'l', value:0, display:'$0 tax', color:'#9E9E9E'},
  {label:'$10K add\'l', value:2200, display:'$2,200 tax', color:'#2979FF'},
  {label:'$16K add\'l', value:3520, display:'$3,520 tax', color:'#4CAF50'},
  {label:'$20K add\'l', value:4800, display:'~$4,800 tax', color:'#C62828'},
], 480, null, '2026 Conversion Scenarios — Federal Tax Impact');
children.push(imgPara(scenarioChart, 460, 160));

children.push(calloutBox('Recommended: Convert additional $16,000 before Dec 31. Uses remaining 22% bracket capacity without triggering 24%.'));

children.push(heading('Action Checklist', HeadingLevel.HEADING_2));
const checkItems = [
  ['done','$35K converted in 2026 — on track for annual target'],
  ['pending','Convert additional $16K — maximize 22% bracket'],
  ['pending','Schedule C write-offs — reduce taxable base by $5K+'],
  ['pending','Roth asset reallocation — move growth to Roth'],
  ['pending','2027 rollover planning — prepare $533K 401k strategy'],
];
checkItems.forEach(([status, text]) => {
  const col = status==='done' ? C.green : C.amber;
  const icon = status==='done' ? '✓' : '○';
  children.push(new Paragraph({
    spacing: { before:40, after:40 }, indent: { left:240 },
    border: { left: { style:BorderStyle.SINGLE, size:12, color:col, space:8 } },
    children: [run(`${icon} `, {bold:true, size:10, color:col}), run(text, {size:10})],
  }));
});

children.push(heading('Golden Window Parameters', HeadingLevel.HEADING_2));
children.push(kpiRow([
  ['Window Opens', kd.golden_window_start || 'Feb 2036', C.accent],
  ['Window Closes', kd.golden_window_end || 'Aug 2040'],
  ['Annual Target', fUSD(gw.optimal_annual_conversion||50000), C.green],
]));

// AI Roth analysis
if (aiAnalysis.roth_conversion) {
  children.push(heading('Detailed Roth Advisory', HeadingLevel.HEADING_2, {before:160}));
  renderMarkdown(aiAnalysis.roth_conversion, children);
}
children.push(pageBreak());

// ── PAGE 8: INCOME STRATEGY ─────────────────────────────────────
children.push(heading('Dividend Income Architecture', HeadingLevel.HEADING_1));
children.push(p('Close the income gap without destroying portfolio quality.', { italic:true, color:C.accent, size:11 }));

const incProgress = drawProgressBar(divTotal, 28000, 480, 60, 'Annual Dividend Income');
children.push(imgPara(incProgress, 460, 55));

const incomeBridge = drawHBar([
  {label:'Current', value:divTotal, display:fUSD(divTotal), color:'#2979FF'},
  {label:'V→JEPI/JEPQ', value:6284, display:'+$6,284', color:'#4CAF50'},
  {label:'2027 Rollover', value:8400, display:'+$8,400', color:'#4CAF50'},
  {label:'Taxable Opt', value:5917, display:'+$5,917', color:'#4CAF50'},
  {label:'Target', value:28000, display:'$28,000', color:'#1A237E'},
], 500, null, 'Income Bridge — Path to $28,000/yr');
children.push(imgPara(incomeBridge, 480, 200));

if (aiAnalysis.dividend_strategy) {
  children.push(heading('Detailed Dividend Analysis', HeadingLevel.HEADING_2));
  renderMarkdown(aiAnalysis.dividend_strategy, children);
}
children.push(pageBreak());

// ── PAGE 9: BOND STRATEGY ───────────────────────────────────────
children.push(heading('Fixed Income and Portfolio Ballast', HeadingLevel.HEADING_1));
const bondDonut = drawDonut([
  {label:'Current BND', value:27457, color:'#2979FF'},
  {label:'Gap to Target', value:138476-27457, color:'#E8EAF6'},
], 480, 240, 'Current vs Target Bond Allocation');
children.push(imgPara(bondDonut, 460, 230));

const bondBars = drawHBar([
  {label:'BND', value:48467, color:'#1A237E'},
  {label:'AGG', value:27695, color:'#2979FF'},
  {label:'VCIT', value:34619, color:'#7B1FA2'},
  {label:'VGIT', value:27695, color:'#4CAF50'},
], 480, null, `Target Allocation — ${fUSD(138476)} Total`);
children.push(imgPara(bondBars, 460, 160));

children.push(kpiRow([
  ['Weighted Duration', '~5.8 years'],
  ['1% Rate Impact', `${fUSD(8032)} loss`, C.red],
  ['Deployment Source', `${fUSD(28465)} cash + trims`],
]));

if (aiAnalysis.bond_strategy) {
  children.push(heading('Detailed Bond Analysis', HeadingLevel.HEADING_2));
  renderMarkdown(aiAnalysis.bond_strategy, children);
}
children.push(pageBreak());

// ── PAGE 10: CONCENTRATION RISK ─────────────────────────────────
children.push(heading('Visa Concentration Decision Framework', HeadingLevel.HEADING_1));

const gauge = drawGauge(vPct, 25, 15, 240, 150, 'V Weight (target <13%)');
children.push(imgPara(gauge, 230, 140));

children.push(styledTable(
  ['Scenario', '5yr Value', 'Annual Income', 'Growth', 'Risk Level'],
  [
    ['A: Hold All V', '~$335,000', '$2,780/yr', '12%', 'HIGH'],
    ['B: Trim 30%', '~$310,000', '$4,200/yr', '10%', 'MODERATE'],
    ['C: Trim 50%', '~$285,000', '$5,800/yr', '8%', 'LOW'],
  ],
  { colorFn: (v,ci) => ci===4 ? (v==='HIGH'?C.red:v==='LOW'?C.green:C.amber) : C.black }
));

children.push(calloutBox('Recommended: Trim 30% over 12 weeks (15 shares/week). Begin with Rollover IRA. Both IRAs = zero capital gains tax on sale.'));

if (aiAnalysis.v_strategy) {
  children.push(heading('Detailed V Strategy', HeadingLevel.HEADING_2));
  renderMarkdown(aiAnalysis.v_strategy, children);
}
children.push(pageBreak());

// ── PAGE 11: RISK MONITORING ────────────────────────────────────
children.push(heading('Risk Monitoring and Position Controls', HeadingLevel.HEADING_1));

const stops = DATA.risk?.stops || risk.stops || [];
if (stops.length > 0) {
  children.push(styledTable(
    ['Symbol', 'Current Price', 'Stop Level', 'Downside %', 'Status'],
    stops.map(s => [
      s.symbol || '—',
      fUSD(s.current_price || s.price, 2),
      fUSD(s.stop_price || s.stop, 2),
      s.distance_pct != null ? `${s.distance_pct.toFixed(1)}%` : '—',
      s.triggered ? 'TRIGGERED' : 'Active',
    ]),
    { colorFn: (v,ci) => ci===3 && v!=='—' && parseFloat(v) < -10 ? C.red : ci===4 && v==='TRIGGERED' ? C.red : C.black }
  ));
} else {
  children.push(p('Stop-loss data available in pipeline state. See technical analysis for current levels.', { italic:true, color:C.grayMid }));
}

children.push(dataQualityFlag('Source risk metrics (volatility, Sharpe, risk profile) may not be fully populated. Distinguish actual stop-monitoring from incomplete risk analytics.'));

if (aiAnalysis.defense_analysis) {
  children.push(heading('Defense Portfolio Analysis', HeadingLevel.HEADING_2));
  renderMarkdown(aiAnalysis.defense_analysis, children);
}
children.push(pageBreak());

// ── PAGE 12: ACTION PLAN ────────────────────────────────────────
children.push(heading('Strategic Action Plan', HeadingLevel.HEADING_1));
const actions = [
  ['Immediate','Convert additional $16K to Roth','$16,000','Before Dec 31','Lock 22% rate'],
  ['Immediate','Close SRNE position','~$2','This week','Remove dead weight'],
  ['Immediate','Update stale stop losses','—','This week','Protect $304K gains'],
  ['Near-Term','Build bond allocation','$111,000','Q2-Q3 2026','Achieve 25% target'],
  ['Near-Term','Trim Visa 30%','$57,000','12 weeks','Reduce to ~11%'],
  ['Near-Term','Schedule C write-offs','$5,000+','2026 tax year','Expand conversion room'],
  ['Monitor','Add REIT exposure','$60,000','Q3 2026','Missing asset class'],
  ['Monitor','Prepare 2027 rollover','$533,000','2027','Consolidate strategy'],
];
children.push(styledTable(
  ['Priority', 'Action', 'Amount', 'Timing', 'Expected Outcome'],
  actions,
  { colorFn: (v,ci) => ci===0 ? (v==='Immediate'?C.red:v==='Near-Term'?C.amber:C.accent) : C.black }
));
children.push(pageBreak());

// ── PAGE 13: DATA INTEGRITY ─────────────────────────────────────
children.push(heading('Data Integrity and Methodology Notes', HeadingLevel.HEADING_1));
children.push(p('This section documents known data gaps, conflicts, and assumptions to support report credibility.', { italic:true, color:C.gray }));

const flags = [
  ['Roth Balance','Multiple values: $42,373 vs $42,643 — using latest snapshot','Low'],
  ['V Trim Target','Conflicting: "12-13%" vs "30%" across analysis sections','Medium'],
  ['Weighted Beta','Not populated in portfolio totals — computed in pipeline at 0.38','Low'],
  ['Dividend Calendar','Blank in some source files — computed from holdings at ' + fUSD(divTotal),'Low'],
  ['Benchmark Comparison','SPY benchmark available but not in all reports','Medium'],
  ['Tax Bracket','May be incomplete in tax projection module','Medium'],
  ['Defense Section Date','May reference January 2025 vs 2026 core sections','Low'],
  ['Growth Assumption','7% annualized for projection models — not guaranteed','Info'],
];
children.push(styledTable(
  ['Data Point', 'Issue', 'Severity'],
  flags,
  { colorFn: (v,ci) => ci===2 ? (v==='Medium'?C.amber:v==='Low'?C.grayMid:C.accent) : C.black }
));
children.push(pageBreak());

// ── PAGE 14: AI ANALYSIS APPENDIX ───────────────────────────────
children.push(heading('Appendix: AI Strategic Analysis', HeadingLevel.HEADING_1));
children.push(p(`Generated: ${aiAnalysis.generated_at || '—'}  |  Run type: ${aiAnalysis.run_type || '—'}`, { size:9, color:C.grayMid }));

const aiSections = [
  ['deep_holdings', 'Deep Holdings Analysis'],
  ['ira_opportunities', 'IRA Opportunity Set'],
];
aiSections.forEach(([key, title]) => {
  const text = aiAnalysis[key];
  if (!text) return;
  children.push(heading(title, HeadingLevel.HEADING_2, { before: 160 }));
  renderMarkdown(text, children);
});

// ── APPENDIX B: HOLDINGS TABLE ──────────────────────────────────
children.push(pageBreak());
children.push(heading('Appendix: Complete Holdings', HeadingLevel.HEADING_1));
const holdRows = [...holdings].sort((a,b) => (b.market_value||0)-(a.market_value||0)).slice(0, 30).map(h => [
  h.symbol || '—',
  h.account === 'fidelity_401k' ? '401k' : h.account === 'schwab_rollover_ira' ? 'IRA' : h.account === 'schwab_roth' ? 'Roth' : h.account === 'schwab_taxable' ? 'Taxable' : '—',
  fUSD(h.market_value, 0),
  h.market_value && totalVal ? `${(h.market_value/totalVal*100).toFixed(1)}%` : '—',
  h.gain_loss != null ? fUSD(h.gain_loss, 0) : '—',
]);
children.push(styledTable(['Symbol', 'Account', 'Value', 'Weight', 'Gain/Loss'], holdRows));

// ── FOOTER / DISCLOSURE ─────────────────────────────────────────
children.push(new Paragraph({ spacing: { before: 400 } }));
children.push(calloutBox('For informational planning use only. Not investment, legal, or tax advice. Verify all figures before execution. Trade AI v12 — Personal Portfolio Strategy Report.'));

// ═══════════════════════════════════════════════════════════════════
// GENERATE DOCUMENT
// ═══════════════════════════════════════════════════════════════════
const doc = new Document({
  creator: 'Trade AI v12',
  title: 'Personal Portfolio Strategy Report',
  description: 'Portfolio structure, risk, retirement tax planning, and income strategy',
  styles: {
    default: { heading1: { run: { font:'Segoe UI', size:32, bold:true, color:C.darkBlue } },
               heading2: { run: { font:'Segoe UI', size:26, bold:true, color:C.darkBlue } },
               heading3: { run: { font:'Segoe UI', size:22, bold:true, color:C.slate } },
               document: { run: { font:'Segoe UI', size:20, color:C.black } } },
  },
  sections: [{
    properties: {
      page: { margin: { top: 720, bottom: 720, left: 900, right: 900 },
              size: { width: 12240, height: 15840 } },
    },
    headers: { default: new Header({ children: [
      new Paragraph({ alignment: AlignmentType.RIGHT, children: [
        run('Personal Portfolio Strategy Report', { size:7, color:C.grayMid, italic:true }),
        run('  |  ', { size:7, color:C.grayMid }),
        run('Confidential', { size:7, color:C.grayMid }),
      ]})
    ]})},
    footers: { default: new Footer({ children: [
      new Paragraph({ alignment: AlignmentType.CENTER, children: [
        run('Trade AI v12  |  ', { size:7, color:C.grayMid }),
        new TextRun({ children: [PageNumber.CURRENT], size:14, color:C.grayMid }),
        run(' of ', { size:7, color:C.grayMid }),
        new TextRun({ children: [PageNumber.TOTAL_PAGES], size:14, color:C.grayMid }),
      ]})
    ]})},
    children,
  }],
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync(OUTPUT, buffer);
  console.log(`Report saved: ${OUTPUT} (${(buffer.length/1024).toFixed(0)} KB, ${children.length} elements)`);
}).catch(err => {
  console.error('DOCX generation error:', err);
  process.exit(1);
});
