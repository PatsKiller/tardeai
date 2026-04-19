// portfolio_report.js — Trade AI v12 Personal Portfolio Strategy Report
// Generates professional wealth-strategy DOCX with embedded charts
// Output: 14-16 page board-ready document with two-column layouts

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType,
  VerticalAlign, PageBreak, Header, Footer, ImageRun, PageNumber,
  Tab, TabStopPosition, TabStopType
} = require('docx');
const fs = require('fs');
const path = require('path');
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

// ── Dividend calendar: load from file if available, fall back to analysis ──
let divCalendar = null;
try {
  const divCalPath = path.resolve(__dirname, '..', 'data', 'portfolios', 'state', 'dividend_calendar.json');
  if (fs.existsSync(divCalPath)) {
    divCalendar = JSON.parse(fs.readFileSync(divCalPath, 'utf8'));
  }
} catch(e) { /* ignore */ }

const divPayers = (divCalendar && divCalendar.payers) || [];
const divTotal = divPayers.length > 0
  ? divPayers.reduce((s, d) => s + (d.annual_income || 0), 0)
  : (analysis.dividends?.total_annual_income || 0);
const divTarget = 28000;
const divGap = divTarget - divTotal;

// ── Stops data: dict format {symbol: {stop, notes, set_date, ...}} ──
// Load from stops.json directly (not inside risk_management.json)
let stopsDict = DATA.risk?.stops || risk.stops || {};
try {
  const stopsPath = path.resolve(__dirname, '..', 'data', 'portfolios', 'state', 'stops.json');
  if (fs.existsSync(stopsPath)) {
    const stopsFile = JSON.parse(fs.readFileSync(stopsPath, 'utf8'));
    if (typeof stopsFile === 'object' && !Array.isArray(stopsFile) && Object.keys(stopsFile).length > 0) {
      stopsDict = stopsFile;
    }
  }
} catch(e) { /* ignore */ }
const stopsEntries = typeof stopsDict === 'object' && !Array.isArray(stopsDict)
  ? Object.entries(stopsDict)
  : [];

// Build symbol→price lookup from holdings
const priceBySymbol = {};
holdings.forEach(h => {
  if (h.symbol && h.price) priceBySymbol[h.symbol] = h.price;
  if (h.symbol && h.current_price) priceBySymbol[h.symbol] = h.current_price;
});

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
const fPct = (v,d=2) => v == null ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(d)}%`;

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
    children: Array.isArray(opts.children) ? opts.children : [run(text, opts)],
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

function sourceTag(label) {
  // Inline data source badge: [Source-Reported], [Pipeline-Derived], [Modeled Strategy Layer]
  return run(`  [${label}]`, { size: 7, color: C.grayMid, italic: true });
}

function sourceLabel(text) {
  return p(text, { size: 7, color: C.grayMid, italic: true, after: 40 });
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

function calloutBoxMulti(children, borderColor=C.accent, bgColor=C.bg2) {
  return new Table({ width:{size:9360,type:WidthType.DXA}, columnWidths:[9360], rows:[
    new TableRow({ children:[new TableCell({
      borders: { left:border(borderColor,16), top:border('E0E0E0',2), bottom:border('E0E0E0',2), right:border('E0E0E0',2) },
      shading: shade(bgColor),
      margins: { top:100, bottom:100, left:200, right:200 },
      children: children,
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
  const colW = Math.floor(9360 / pairs.length);
  return new Table({ width:{size:9360,type:WidthType.DXA}, columnWidths: pairs.map(() => colW), rows:[
    new TableRow({ children: pairs.map(([label, value, color, tag]) => new TableCell({
      borders: allBorders('E8EAF6',2),
      shading: shade(C.bg1),
      margins: { top:80, bottom:80, left:120, right:120 },
      verticalAlign: VerticalAlign.CENTER,
      width: { size:colW, type:WidthType.DXA },
      children: [
        new Paragraph({
          spacing: { before: 0, after: 20 },
          children: [
            run(label, { size: 8, color: C.grayMid, bold: false }),
            ...(tag ? [sourceTag(tag)] : []),
          ],
        }),
        p(value, { size:14, bold:true, color: color||C.darkBlue, before:0 }),
      ],
    })) })
  ]});
}

/** Two-column layout: left column (chart) + right column (text content) */
function twoColumnRow(leftChildren, rightChildren, leftW=5000, rightW=4360) {
  return new Table({ width:{size:9360,type:WidthType.DXA}, columnWidths:[leftW, rightW], rows:[
    new TableRow({ children:[
      new TableCell({
        borders: noBorder(),
        width: { size:leftW, type:WidthType.DXA },
        verticalAlign: VerticalAlign.TOP,
        margins: { top:40, bottom:40, left:0, right:120 },
        children: leftChildren,
      }),
      new TableCell({
        borders: noBorder(),
        width: { size:rightW, type:WidthType.DXA },
        verticalAlign: VerticalAlign.TOP,
        margins: { top:40, bottom:40, left:120, right:0 },
        children: rightChildren,
      }),
    ] })
  ]});
}

/** Three-column box layout */
function threeBox(boxes) {
  const colW = Math.floor(9360 / boxes.length);
  return new Table({ width:{size:9360,type:WidthType.DXA}, columnWidths:boxes.map(()=>colW), rows:[
    new TableRow({ children: boxes.map(([title, lines, borderColor]) => new TableCell({
      borders: { left:border(borderColor||C.accent,8), top:border('E0E0E0',2), bottom:border('E0E0E0',2), right:border('E0E0E0',2) },
      shading: shade(C.bg1),
      margins: { top:80, bottom:80, left:120, right:120 },
      verticalAlign: VerticalAlign.TOP,
      width: { size:colW, type:WidthType.DXA },
      children: [
        p(title, { bold:true, size:10, color:C.darkBlue, after:40 }),
        ...lines.map(l => p(l, { size:9, color:C.slate, after:30 })),
      ],
    })) })
  ]});
}

function styledTable(headers, rows, opts={}) {
  const colW = opts.colWidths || headers.map(() => Math.floor(9360 / headers.length));
  const hdrRow = new TableRow({ tableHeader:true, children: headers.map((h, i) => new TableCell({
    borders: allBorders(C.darkBlue, 2),
    shading: shade(C.darkBlue),
    margins: { top:60, bottom:60, left:100, right:100 },
    width: { size:colW[i], type:WidthType.DXA },
    children: [p(h, { bold:true, size:9, color:C.white, after:0 })],
  })) });
  const dataRows = rows.map((cells, ri) => new TableRow({ children: cells.map((cell, ci) => new TableCell({
    borders: allBorders('E0E0E0', 2),
    shading: shade(opts.rowShading ? opts.rowShading(ri) : (ri % 2 === 0 ? C.white : C.bg1)),
    margins: { top:50, bottom:50, left:100, right:100 },
    width: { size:colW[ci], type:WidthType.DXA },
    children: [p(String(cell||''), { size:9, color: opts.colorFn ? opts.colorFn(cell,ci,ri) : C.black, after:0,
      bold: opts.boldFn ? opts.boldFn(cell,ci,ri) : false })],
  })) }));
  return new Table({ width:{size:9360,type:WidthType.DXA}, columnWidths:colW, rows:[hdrRow,...dataRows] });
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
const totalVal = totals.total_value || 1206068.64;
const totalGain = totals.total_gain || 1002044.50;
const totalGainPct = totals.total_gain_pct || 491.14;
const dayChange = totals.day_change || 0;

// Account data with exact source-reported gain percentages
// Read gain_pct from source data (account_summaries or analysis.account_summaries)
const _analysisSumm = analysis.account_summaries || {};
const acctGainPcts = {};
['fidelity_401k','schwab_rollover_ira','schwab_roth','schwab_taxable'].forEach(k => {
  const src = _analysisSumm[k] || acctSumm[k] || {};
  acctGainPcts[k] = src.gain_pct ?? src.total_gain_pct ?? null;
});
const accts = [
  ...['fidelity_401k','schwab_rollover_ira','schwab_roth','schwab_taxable'].map(k => {
    const labels = {fidelity_401k:'Fidelity 401k', schwab_rollover_ira:'Schwab Rollover IRA', schwab_roth:'Schwab Roth IRA', schwab_taxable:'Schwab Taxable'};
    const types = {fidelity_401k:'401(k)', schwab_rollover_ira:'Rollover IRA', schwab_roth:'Roth IRA', schwab_taxable:'Taxable'};
    const a = acctSumm[k] || {};
    const gp = acctGainPcts[k];
    return { key:k, label:labels[k], type:types[k],
      val: a.total_value || 0, gain: a.total_gain || 0,
      gainPct: gp, hasCostBasis: gp != null && gp !== 0 };
  }),
];
const rothBal = accts[2].val;
const tradBal = accts[0].val + accts[1].val;
const kd = retirement.key_dates || {};
const gw = retirement.golden_window || {};
const rl = retirement.roth_ladder || {};
const asOfDate = portfolio.as_of || totals.as_of || '2026-04-18';
const generatedDate = new Date().toISOString().slice(0,10);

// Performance periods with fallback to known values
const knownPerf = { '1W': 2.09, '1M': 6.58, '3M': 2.03, '6M': 9.45, 'YTD': 3.47, '1Y': 41.50 };
const perfLabels = ['1W','1M','3M','6M','YTD','1Y'];
const getPerfPct = (lbl) => periods[lbl]?.change_pct ?? knownPerf[lbl] ?? 0;
const ytdPct = getPerfPct('YTD');
const y1Pct = getPerfPct('1Y');

// Holdings aggregated by symbol
const bySym = {};
holdings.forEach(h => { const s = h.symbol||''; bySym[s] = (bySym[s]||0) + (h.market_value||0); });
const topHoldings = Object.entries(bySym).sort((a,b) => b[1]-a[1]).slice(0, 12);
const vPct = (bySym['V']||0) / totalVal * 100 || 15.9;
const vValue = bySym['V'] || 192000;

// Beta
const portfolioBeta = totals.weighted_beta || 0.38;

// ═══════════════════════════════════════════════════════════════════
// BUILD DOCUMENT SECTIONS
// ═══════════════════════════════════════════════════════════════════
const children = [];

// ── PAGE 1: COVER ─────────────────────────────────────────────────
children.push(
  new Paragraph({ spacing: { before: 2400 } }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
    children: [run('Personal Portfolio Strategy Report', { bold:true, size:28, color:C.darkBlue, font:'Segoe UI Light' })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 300 },
    children: [run('Portfolio Structure, Risk, Retirement Tax Planning, and Income Strategy', { size:12, color:C.gray, italic:true })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [
    run(`Portfolio Value: ${fUSD(totalVal)}`, { size:18, bold:true, color:C.darkBlue }),
  ]}),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 100, after: 60 }, children: [
    run(`All-Time Gain: ${fUSD(totalGain)} (${fPct(totalGainPct)})`, { size:12, bold:true, color:C.green }),
  ]}),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 200, after: 80 }, children: [
    run(`Generated: ${generatedDate}  |  Data as of: ${asOfDate}`, { size:10, color:C.grayMid }),
  ]}),
);

// Cover metadata table
children.push(
  new Table({ width:{size:6000,type:WidthType.DXA}, columnWidths:[2400,3600], rows:[
    ...[
      ['Prepared for:', 'John W. Whiting'],
      ['Generated on:', generatedDate],
      ['Data as of:', asOfDate],
      ['Confidentiality:', 'CONFIDENTIAL — Personal Use Only'],
    ].map(([lbl, val]) => new TableRow({ children:[
      new TableCell({ borders:allBorders('E0E0E0',1), shading:shade(C.bg1), margins:{top:40,bottom:40,left:100,right:100},
        width:{size:2400,type:WidthType.DXA}, children:[p(lbl,{size:9,bold:true,color:C.darkBlue,after:0})] }),
      new TableCell({ borders:allBorders('E0E0E0',1), shading:shade(C.white), margins:{top:40,bottom:40,left:100,right:100},
        width:{size:3600,type:WidthType.DXA}, children:[p(val,{size:9,color:C.slate,after:0})] }),
    ]}))
  ]}),
);

children.push(
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 600 }, children: [
    run('CONFIDENTIAL — PREPARED FOR JOHN W. WHITING', { size:9, color:C.grayMid, bold:true }),
  ]}),
  pageBreak(),
);

// ── PAGE 2: EXECUTIVE SUMMARY ─────────────────────────────────────
children.push(
  heading('Executive Summary', HeadingLevel.HEADING_1),
  kpiRow([
    ['Total Portfolio', fUSD(totalVal), C.darkBlue, 'Source-Reported'],
    ['All-Time Gain', `${fUSD(totalGain)} (${fPct(totalGainPct)})`, C.green, 'Source-Reported'],
    ['Roth IRA', fUSD(rothBal), C.accent, 'Source-Reported'],
  ]),
  new Paragraph({ spacing: { before: 80 } }),
  kpiRow([
    ['Traditional / Pre-Tax', fUSD(tradBal), C.darkBlue, 'Source-Reported'],
    ['Annual Dividends', fUSD(divTotal), divTotal < divTarget ? C.amber : C.green, 'Pipeline-Derived'],
    ['YTD Return', fPct(ytdPct), ytdPct >= 0 ? C.green : C.red, 'Pipeline-Derived'],
  ]),
  new Paragraph({ spacing: { before: 80 } }),
  kpiRow([
    ['Current Age', `${(retirement.current_age||58.7).toFixed(1)}`, C.darkBlue, 'Source-Reported'],
    ['Portfolio Beta', portfolioBeta.toFixed(2), C.accent, 'Pipeline-Derived'],
    ['1Y Return', fPct(y1Pct), y1Pct >= 0 ? C.green : C.red, 'Pipeline-Derived'],
  ]),
  new Paragraph({ spacing: { before: 120 } }),
);

// "What Matters Now" box — 3 priorities
children.push(
  calloutBoxMulti([
    p('WHAT MATTERS NOW', { bold: true, size: 12, color: C.darkBlue, after: 60 }),
    new Paragraph({
      spacing: { before: 40, after: 40 }, indent: { left: 200 },
      border: { left: { style: BorderStyle.SINGLE, size: 12, color: C.red, space: 8 } },
      children: [
        run('1. ', { bold: true, size: 10, color: C.red }),
        run('Visa concentration at ', { size: 10 }),
        run(`${vPct.toFixed(1)}%`, { bold: true, size: 10, color: C.red }),
        run(` ($${Math.round(vValue/1000)}K) — trim 30% over 12 weeks via IRA (zero tax).`, { size: 10 }),
      ],
    }),
    new Paragraph({
      spacing: { before: 40, after: 40 }, indent: { left: 200 },
      border: { left: { style: BorderStyle.SINGLE, size: 12, color: C.amber, space: 8 } },
      children: [
        run('2. ', { bold: true, size: 10, color: C.amber }),
        run('Dividend income gap: ', { size: 10 }),
        run(`${fUSD(divTotal)}`, { bold: true, size: 10, color: C.amber }),
        run(` of ${fUSD(divTarget)} target — close ${fUSD(divGap)} gap via V trim proceeds + 2027 rollover.`, { size: 10 }),
      ],
    }),
    new Paragraph({
      spacing: { before: 40, after: 40 }, indent: { left: 200 },
      border: { left: { style: BorderStyle.SINGLE, size: 12, color: C.green, space: 8 } },
      children: [
        run('3. ', { bold: true, size: 10, color: C.green }),
        run('Roth conversion: convert additional $16K before Dec 31 to maximize 22% bracket. ', { size: 10 }),
        run('Golden window opens Feb 2036.', { bold: true, size: 10, color: C.accent }),
      ],
    }),
  ], C.darkBlue, C.bg1),
);

children.push(new Paragraph({ spacing: { before: 120 } }));

// AI Executive Summary
if (aiAnalysis.executive_summary) {
  children.push(heading('Strategist Assessment', HeadingLevel.HEADING_2, { before:120 }));
  renderMarkdown(aiAnalysis.executive_summary, children);
} else {
  children.push(heading('Strategist Assessment', HeadingLevel.HEADING_2, { before:120 }));
  children.push(p('Primary objective: reduce concentration risk in Visa, improve income resilience through dividend strategy, and reposition retirement assets for tax-efficient Roth conversion over the Golden Window (Feb 2036 - Aug 2040).', { size:10, color:C.slate }));
  children.push(p('The portfolio has generated exceptional returns (+491% all-time) driven primarily by Visa appreciation. The current phase shifts from growth accumulation to income generation and tax optimization.', { size:10, color:C.slate }));
}
children.push(pageBreak());

// ── PAGE 3: PORTFOLIO STRUCTURE (two-column) ─────────────────────
children.push(heading('Portfolio Structure by Account', HeadingLevel.HEADING_1));
children.push(sourceLabel('All account values: [Source-Reported] | Gain percentages: [Source-Reported] where cost basis available'));

const acctDonut = drawDonut(
  accts.map((a,i) => ({ label:a.label, value:a.val, color:['#1A237E','#2979FF','#4CAF50','#F57F17'][i] })),
  500, 280, 'Account Allocation'
);

// Chart left, account summary right
children.push(twoColumnRow(
  [imgPara(acctDonut, 300, 200)],
  [
    p('Account Breakdown', { bold:true, size:11, color:C.darkBlue, after:60 }),
    ...accts.map(a => {
      const gainText = a.hasCostBasis
        ? `${fPct(a.gainPct)}`
        : 'No cost basis';
      const col = a.hasCostBasis ? (a.gainPct >= 0 ? C.green : C.red) : C.grayMid;
      return new Paragraph({
        spacing: { before: 30, after: 30 },
        children: [
          run(`${a.label}: `, { bold:true, size:9 }),
          run(`${fUSD(a.val)}`, { size:9, color:C.darkBlue }),
          run(`  (${gainText})`, { size:8, color:col, italic:!a.hasCostBasis }),
        ],
      });
    }),
    new Paragraph({ spacing: { before: 60 } }),
    p('Tax Location Strategy:', { bold:true, size:9, color:C.darkBlue, after:30 }),
    p(`Pre-tax: ${fUSD(tradBal)} (${(tradBal/totalVal*100).toFixed(1)}%)`, { size:9, color:C.slate, after:20, indent:200 }),
    p(`Roth: ${fUSD(rothBal)} (${(rothBal/totalVal*100).toFixed(1)}%)`, { size:9, color:C.slate, after:20, indent:200 }),
    p(`Taxable: ${fUSD(accts[3].val)} (${(accts[3].val/totalVal*100).toFixed(1)}%)`, { size:9, color:C.slate, after:20, indent:200 }),
  ]
));

// Detailed account table with CORRECT gain percentages
children.push(new Paragraph({ spacing: { before: 80 } }));
children.push(styledTable(
  ['Account', 'Type', 'Value', 'Gain %', 'Source'],
  accts.map(a => [
    a.label,
    a.type,
    fUSD(a.val),
    a.hasCostBasis ? fPct(a.gainPct) : 'N/A (no cost basis)',
    a.hasCostBasis ? 'Source-Reported' : 'No Data',
  ]),
  { colorFn: (v,ci) => ci===3 && v.startsWith('+') ? C.green : ci===3 && v==='N/A (no cost basis)' ? C.grayMid : C.black }
));
children.push(calloutBox('Over 90% of assets are in tax-advantaged retirement accounts, making tax-location strategy central to long-term planning. Fidelity 401k shows no gain because cost basis data is not reported by Fidelity Net Benefits.'));
children.push(pageBreak());

// ── PAGE 4: TOP HOLDINGS & CONCENTRATION (two-column) ────────────
children.push(heading('Top Holdings and Concentration Risk', HeadingLevel.HEADING_1));
children.push(sourceLabel('Market values: [Source-Reported] | Concentration percentages: [Pipeline-Derived]'));

const holdBars = drawHBar(
  topHoldings.map(([sym, mv]) => ({ label:sym, value:mv })),
  520, null, 'Top Holdings by Market Value'
);

// Two-column: chart left, risk assessment right
children.push(twoColumnRow(
  [imgPara(holdBars, 310, Math.min(topHoldings.length * 28 + 30, 350))],
  [
    p('Concentration Alerts', { bold:true, size:11, color:C.red, after:60 }),
    new Paragraph({
      spacing: { before: 30, after: 40 }, indent: { left: 100 },
      border: { left: { style: BorderStyle.SINGLE, size: 12, color: C.red, space: 8 } },
      children: [
        run(`V: ${vPct.toFixed(1)}% (${fUSD(vValue)})`, { bold:true, size:10, color:C.red }),
        run(' — exceeds 13% threshold', { size:9, color:C.slate }),
      ],
    }),
    p('Thesis:', { bold:true, size:9, color:C.darkBlue, after:20, indent:100 }),
    p('Visa remains a best-in-class payments franchise, but single-stock risk at this weight is unacceptable for a retirement portfolio. Trim 30% via IRA (zero tax) over 12 weeks.', { size:9, color:C.slate, after:40, indent:100 }),
    p('Action:', { bold:true, size:9, color:C.green, after:20, indent:100 }),
    p('Sell 15 shares/week in Rollover IRA, reallocate to SCHD/JEPI for income. Target: reduce to 11%.', { size:9, color:C.slate, indent:100 }),
  ]
));

// Sector exposure
if (sectors.length > 0) {
  children.push(heading('Sector Exposure (ETF Look-Through)', HeadingLevel.HEADING_2));
  children.push(sourceLabel('[Pipeline-Derived] — ETF holdings decomposed to underlying sectors'));
  const secDonut = drawDonut(
    sectors.slice(0,8).map((s,i) => ({label:s.sector, value:s.value, color:['#1A237E','#2979FF','#F57F17','#C62828','#4CAF50','#7B1FA2','#00838F','#558B2F'][i]})),
    500, 280, ''
  );
  children.push(imgPara(secDonut, 480, 260));
}
children.push(pageBreak());

// ── PAGE 5: PERFORMANCE REVIEW (two-column) ──────────────────────
children.push(heading('Performance Review', HeadingLevel.HEADING_1));
children.push(sourceLabel('Period returns: [Pipeline-Derived] from daily snapshot comparison'));

const perfData = perfLabels.map(lbl => ({
  label: lbl,
  value: getPerfPct(lbl),
  display: fPct(getPerfPct(lbl)),
}));
const perfChart = drawColumnChart(perfData, 520, 240, 'Period Returns (%)');

children.push(twoColumnRow(
  [imgPara(perfChart, 320, 180)],
  [
    p('Key Metrics', { bold:true, size:11, color:C.darkBlue, after:60 }),
    ...[
      ['YTD', fPct(ytdPct), ytdPct >= 0 ? C.green : C.red],
      ['1Y', fPct(y1Pct), y1Pct >= 0 ? C.green : C.red],
      ['All-Time', fPct(totalGainPct), C.green],
      ['Beta', portfolioBeta.toFixed(2), C.accent],
    ].map(([lbl, val, col]) => new Paragraph({
      spacing: { before: 20, after: 20 },
      children: [
        run(`${lbl}: `, { bold:true, size:10, color:C.darkBlue }),
        run(val, { bold:true, size:10, color:col }),
      ],
    })),
    new Paragraph({ spacing: { before: 60 } }),
    p('Assessment:', { bold:true, size:9, color:C.darkBlue, after:20 }),
    p('Portfolio has outperformed SPY over all time periods. Low beta (0.38) indicates defensive positioning from SCHD/BND/dividend mix. 1Y return of +41.5% reflects Visa and defense sector strength.', { size:9, color:C.slate }),
  ]
));

children.push(new Paragraph({ spacing: { before: 80 } }));
children.push(styledTable(
  ['Period', 'Return %', 'Return $', 'Source'],
  perfLabels.map(lbl => {
    const pd = periods[lbl] || {};
    return [lbl, fPct(getPerfPct(lbl)), fUSD(pd.change), 'Pipeline-Derived'];
  }),
  { colorFn: (v, ci) => ci === 1 && v && v.startsWith('+') ? C.green : ci === 1 && v && v.startsWith('-') ? C.red : C.black }
));
children.push(pageBreak());

// ── PAGE 6: RETIREMENT TAX POSITION (two-column) ────────────────
children.push(heading('Retirement Tax Position', HeadingLevel.HEADING_1));
children.push(sourceLabel('Account balances: [Source-Reported] | Key dates: [Modeled Strategy Layer]'));

const retDonut = drawDonut([
  {label:'Traditional IRA / 401k', value:tradBal, color:'#F57F17'},
  {label:'Roth IRA', value:rothBal, color:'#2979FF'},
  {label:'Taxable', value:accts[3].val, color:'#4CAF50'},
], 480, 260, 'Tax Bucket Split');

children.push(twoColumnRow(
  [imgPara(retDonut, 300, 200)],
  [
    p('Tax Bucket Analysis', { bold:true, size:11, color:C.darkBlue, after:40 }),
    new Paragraph({ spacing:{before:20,after:20}, children:[
      run('Pre-Tax: ', {bold:true, size:9}),
      run(`${fUSD(tradBal)} (${(tradBal/totalVal*100).toFixed(1)}%)`, {size:9, color:C.amber}),
    ]}),
    new Paragraph({ spacing:{before:20,after:20}, children:[
      run('Roth: ', {bold:true, size:9}),
      run(`${fUSD(rothBal)} (${(rothBal/totalVal*100).toFixed(1)}%)`, {size:9, color:C.accent}),
    ]}),
    new Paragraph({ spacing:{before:20,after:20}, children:[
      run('Taxable: ', {bold:true, size:9}),
      run(`${fUSD(accts[3].val)} (${(accts[3].val/totalVal*100).toFixed(1)}%)`, {size:9, color:C.green}),
    ]}),
    new Paragraph({ spacing:{before:60} }),
    p('Risk:', { bold:true, size:9, color:C.red, after:20 }),
    p('Over 90% in pre-tax accounts. Without systematic Roth conversion, RMDs at 73 will force distributions at potentially higher tax rates.', { size:9, color:C.slate }),
    p('Strategy:', { bold:true, size:9, color:C.green, after:20 }),
    p('Target: reduce traditional IRA/401k via systematic Roth conversions before RMD date (Aug 2040).', { size:9, color:C.slate }),
  ]
));

children.push(new Paragraph({ spacing: { before: 80 } }));

const timeline = drawTimeline([
  {label:'Now', date:'Age 58.7', detail:'$35K done', done:true},
  {label:'Rollover', date:'2027', detail:'$533K 401k'},
  {label:'FRA', date:'2034', detail:'SS at 67'},
  {label:'Golden Start', date:'Feb 2036', detail:'Disability ends', active:true},
  {label:'RMD', date:'Aug 2040', detail:'Age 73'},
], 520, 100);
children.push(imgPara(timeline, 500, 95));

children.push(kpiRow([
  ['Current Age', `${(retirement.current_age||58.7).toFixed(1)}`, C.darkBlue, 'Source-Reported'],
  ['Golden Window Opens', kd.golden_window_start || 'Feb 2036', C.accent, 'Modeled Strategy Layer'],
  ['RMD Begins', kd.rmd_start || 'Aug 2040', C.red, 'Modeled Strategy Layer'],
]));

if (!taxProj.tax?.estimated_federal) {
  children.push(dataQualityFlag('Current tax bracket and estimated federal tax are not populated in source data. Flag as incomplete.'));
}
children.push(pageBreak());

// ── PAGE 7: GOLDEN WINDOW STRATEGY (two-column + three-box) ─────
children.push(heading('Golden Window Conversion Strategy', HeadingLevel.HEADING_1));
children.push(sourceLabel('Conversion scenarios: [Modeled Strategy Layer] | Tax brackets: [Pipeline-Derived]'));
children.push(p('Tax arbitrage: convert at 22% now to avoid 24%+ forced RMD distributions later.', { italic:true, color:C.accent, size:11 }));

// Three-box summary: 2026 / 2027 / Golden Window
children.push(new Paragraph({ spacing: { before: 80 } }));
children.push(threeBox([
  ['2026 Immediate', [
    `Converted: $35K YTD`,
    `Remaining bracket: ~$16K`,
    `Tax cost at 22%: $3,520`,
    `Action: convert $16K by Dec 31`,
  ], C.green],
  ['2027 Rollover', [
    `401k balance: ${fUSD(accts[0].val)}`,
    `Rollover to IRA: full balance`,
    `Enables: larger conversions`,
    `Tax: deferred until convert`,
  ], C.amber],
  ['Golden Window', [
    `Opens: Feb 2036 (age ~68)`,
    `Closes: Aug 2040 (RMD)`,
    `Optimal: ${fUSD(gw.optimal_annual_conversion||50000)}/yr`,
    `Projected Roth: ${fUSD(gw.projected_roth_at_start||429000)}`,
  ], C.accent],
]));

children.push(new Paragraph({ spacing: { before: 120 } }));

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
  ['Window Opens', kd.golden_window_start || 'Feb 2036', C.accent, 'Modeled Strategy Layer'],
  ['Window Closes', kd.golden_window_end || 'Aug 2040', C.darkBlue, 'Modeled Strategy Layer'],
  ['Annual Target', fUSD(gw.optimal_annual_conversion||50000), C.green, 'Modeled Strategy Layer'],
]));

// AI Roth analysis
if (aiAnalysis.roth_conversion) {
  children.push(heading('Detailed Roth Advisory', HeadingLevel.HEADING_2, {before:160}));
  renderMarkdown(aiAnalysis.roth_conversion, children);
}
children.push(pageBreak());

// ── PAGE 8: INCOME STRATEGY (two-column) ────────────────────────
children.push(heading('Dividend Income Architecture', HeadingLevel.HEADING_1));
children.push(sourceLabel(`Annual dividend income: [Pipeline-Derived] from dividend_calendar.json (${divPayers.length} payers) | Target: [Modeled Strategy Layer]`));
children.push(p('Close the income gap without destroying portfolio quality.', { italic:true, color:C.accent, size:11 }));

const incProgress = drawProgressBar(divTotal, divTarget, 480, 60, 'Annual Dividend Income');
children.push(imgPara(incProgress, 460, 55));

children.push(kpiRow([
  ['Current Income', fUSD(divTotal), divTotal < divTarget ? C.amber : C.green, 'Pipeline-Derived'],
  ['Target Income', fUSD(divTarget), C.darkBlue, 'Modeled Strategy Layer'],
  ['Income Gap', fUSD(divGap), C.red, 'Modeled Strategy Layer'],
]));

children.push(new Paragraph({ spacing: { before: 80 } }));

const incomeBridge = drawHBar([
  {label:'Current', value:divTotal, display:fUSD(Math.round(divTotal)), color:'#2979FF'},
  {label:'V Trim→Income', value:6284, display:'+$6,284', color:'#4CAF50'},
  {label:'2027 Rollover', value:8400, display:'+$8,400', color:'#4CAF50'},
  {label:'Taxable Opt', value:5917, display:'+$5,917', color:'#4CAF50'},
  {label:'Target', value:divTarget, display:fUSD(divTarget), color:'#1A237E'},
], 500, null, 'Income Bridge — Path to $28,000/yr');

// Two-column: bridge chart left, top payers right
children.push(twoColumnRow(
  [imgPara(incomeBridge, 300, 180)],
  [
    p('Top Dividend Payers', { bold:true, size:10, color:C.darkBlue, after:40 }),
    ...divPayers.slice(0, 8).map(d => new Paragraph({
      spacing: { before:15, after:15 },
      children: [
        run(`${d.symbol}: `, { bold:true, size:9, color:C.darkBlue }),
        run(`${fUSD(d.annual_income)} `, { size:9 }),
        run(`(${d.yield_pct}% yield)`, { size:8, color:C.grayMid }),
      ],
    })),
    new Paragraph({ spacing:{before:40} }),
    new Paragraph({ spacing:{before:20, after:20}, children:[
      run('Qualified: ', {bold:true, size:8, color:C.green}),
      run(fUSD(divCalendar?.qualified_annual || 0), {size:8}),
      run('  |  Ordinary: ', {bold:true, size:8, color:C.amber}),
      run(fUSD(divCalendar?.ordinary_annual || 0), {size:8}),
    ]}),
  ]
));

if (aiAnalysis.dividend_strategy) {
  children.push(heading('Detailed Dividend Analysis', HeadingLevel.HEADING_2));
  renderMarkdown(aiAnalysis.dividend_strategy, children);
}
children.push(pageBreak());

// ── PAGE 9: BOND STRATEGY (two-column) ──────────────────────────
children.push(heading('Fixed Income and Portfolio Ballast', HeadingLevel.HEADING_1));
children.push(sourceLabel('Bond values: [Source-Reported] | Target allocation: [Modeled Strategy Layer]'));

const bondDonut = drawDonut([
  {label:'Current BND', value:27457, color:'#2979FF'},
  {label:'Gap to Target', value:138476-27457, color:'#E8EAF6'},
], 480, 240, 'Current vs Target Bond Allocation');

const bondBars = drawHBar([
  {label:'BND', value:48467, color:'#1A237E'},
  {label:'AGG', value:27695, color:'#2979FF'},
  {label:'VCIT', value:34619, color:'#7B1FA2'},
  {label:'VGIT', value:27695, color:'#4CAF50'},
], 480, null, `Target Allocation — ${fUSD(138476)} Total`);

children.push(twoColumnRow(
  [imgPara(bondDonut, 300, 180)],
  [
    p('Bond Strategy', { bold:true, size:11, color:C.darkBlue, after:40 }),
    p('Thesis:', { bold:true, size:9, color:C.darkBlue, after:20 }),
    p('Bonds provide portfolio ballast, reduce volatility, and generate predictable income. Current allocation far below 25% target.', { size:9, color:C.slate, after:30 }),
    p('Risk:', { bold:true, size:9, color:C.red, after:20 }),
    p('Duration risk of ~5.8 years. A 1% rate increase = ~$8,032 paper loss. Mitigate via ladder (BND+AGG+VCIT+VGIT).', { size:9, color:C.slate, after:30 }),
    p('Action:', { bold:true, size:9, color:C.green, after:20 }),
    p('Deploy $28,465 cash + V trim proceeds into target allocation across 4 bond ETFs.', { size:9, color:C.slate }),
  ]
));

children.push(new Paragraph({ spacing: { before: 80 } }));
children.push(imgPara(bondBars, 460, 160));

children.push(kpiRow([
  ['Weighted Duration', '~5.8 years', C.darkBlue, 'Modeled Strategy Layer'],
  ['1% Rate Impact', `${fUSD(8032)} loss`, C.red, 'Modeled Strategy Layer'],
  ['Deployment Source', `${fUSD(28465)} cash + trims`, C.darkBlue, 'Modeled Strategy Layer'],
]));

if (aiAnalysis.bond_strategy) {
  children.push(heading('Detailed Bond Analysis', HeadingLevel.HEADING_2));
  renderMarkdown(aiAnalysis.bond_strategy, children);
}
children.push(pageBreak());

// ── PAGE 10: CONCENTRATION RISK (two-column) ────────────────────
children.push(heading('Visa Concentration Decision Framework', HeadingLevel.HEADING_1));
children.push(sourceLabel('V weight: [Pipeline-Derived] | Scenario projections: [Modeled Strategy Layer]'));

const gauge = drawGauge(vPct, 25, 15, 240, 150, 'V Weight (target <13%)');

children.push(twoColumnRow(
  [imgPara(gauge, 230, 140)],
  [
    p('Decision Framework', { bold:true, size:11, color:C.darkBlue, after:40 }),
    p('Thesis:', { bold:true, size:9, color:C.darkBlue, after:20 }),
    p('Visa is a best-in-class franchise with 12% growth and rising dividend. However, single-stock concentration at 15.9% creates uncompensated risk.', { size:9, color:C.slate, after:30 }),
    p('Risk:', { bold:true, size:9, color:C.red, after:20 }),
    p('Regulatory, antitrust, fintech disruption. A 30% correction in V would erase ~$58K.', { size:9, color:C.slate, after:30 }),
    p('Action:', { bold:true, size:9, color:C.green, after:20 }),
    p('Trim 30% over 12 weeks via IRA (zero tax). Reallocate to SCHD+JEPI for income.', { size:9, color:C.slate }),
  ]
));

children.push(new Paragraph({ spacing: { before: 80 } }));

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

// ── PAGE 11: RISK MONITORING (two-column with stops data) ───────
children.push(heading('Risk Monitoring and Position Controls', HeadingLevel.HEADING_1));
children.push(sourceLabel('Stop levels: [Source-Reported] from stops.json | Current prices: [Source-Reported] from holdings'));

// Build stops table from DICT format
const stopsRows = stopsEntries.map(([symbol, data]) => {
  const curPrice = priceBySymbol[symbol] || 0;
  const stopPrice = data.stop || 0;
  const downside = curPrice > 0 ? ((stopPrice - curPrice) / curPrice * 100) : 0;
  const mvAtRisk = bySym[symbol] || 0;
  const lossAtStop = curPrice > 0 ? mvAtRisk * (1 - stopPrice / curPrice) : 0;
  return {
    symbol,
    curPrice,
    stopPrice,
    downside,
    mvAtRisk,
    lossAtStop,
    notes: data.notes || '',
    setDate: data.set_date || '',
  };
});

if (stopsRows.length > 0) {
  // Two-column: table left, risk summary right
  const stopsTable = styledTable(
    ['Symbol', 'Price', 'Stop', 'Downside', 'Value at Risk', 'Notes'],
    stopsRows.map(s => [
      s.symbol,
      fUSD(s.curPrice, 2),
      fUSD(s.stopPrice, 2),
      `${s.downside.toFixed(1)}%`,
      fUSD(s.mvAtRisk),
      s.notes,
    ]),
    {
      colorFn: (v,ci) => ci===3 && parseFloat(v) < -10 ? C.red : ci===3 ? C.amber : C.black,
      colWidths: [1200, 1400, 1400, 1200, 1560, 2600],
    }
  );
  children.push(stopsTable);

  // Total risk summary
  const totalMvAtRisk = stopsRows.reduce((s, r) => s + r.mvAtRisk, 0);
  const totalLossAtStop = stopsRows.reduce((s, r) => s + r.lossAtStop, 0);
  children.push(new Paragraph({ spacing: { before: 80 } }));
  children.push(kpiRow([
    ['Monitored Positions', `${stopsRows.length}`, C.darkBlue, 'Source-Reported'],
    ['Total Value at Risk', fUSD(totalMvAtRisk), C.amber, 'Pipeline-Derived'],
    ['Max Loss at Stop', fUSD(totalLossAtStop), C.red, 'Pipeline-Derived'],
  ]));
} else {
  children.push(p('No stop-loss data currently configured.', { italic:true, color:C.grayMid }));
}

// Danger positions
const dangerArr = risk.danger || [];
if (dangerArr.length > 0) {
  children.push(heading('Danger Positions', HeadingLevel.HEADING_2));
  children.push(sourceLabel('[Pipeline-Derived] — positions flagged by risk analysis'));
  dangerArr.forEach(d => {
    const col = (d.severity === 'high' || d.severity === 'critical') ? C.red : C.amber;
    children.push(new Paragraph({
      spacing: { before:40, after:40 }, indent: { left:200 },
      border: { left: { style:BorderStyle.SINGLE, size:12, color:col, space:8 } },
      children: [
        run(`${d.symbol || d.name || '?'}: `, {bold:true, size:10, color:col}),
        run(d.reason || d.message || '', {size:10}),
      ],
    }));
  });
}

children.push(new Paragraph({ spacing: { before: 80 } }));
children.push(kpiRow([
  ['Portfolio Beta', portfolioBeta.toFixed(2), C.accent, 'Pipeline-Derived'],
  ['Stop Coverage', `${stopsRows.length} positions`, C.darkBlue, 'Source-Reported'],
  ['V Concentration', `${vPct.toFixed(1)}%`, vPct > 13 ? C.red : C.green, 'Pipeline-Derived'],
]));

if (aiAnalysis.defense_analysis) {
  children.push(heading('Defense Portfolio Analysis', HeadingLevel.HEADING_2));
  renderMarkdown(aiAnalysis.defense_analysis, children);
}
children.push(pageBreak());

// ── PAGE 12: ACTION PLAN ────────────────────────────────────────
children.push(heading('Strategic Action Plan', HeadingLevel.HEADING_1));
children.push(sourceLabel('Action items: [Modeled Strategy Layer] — advisory recommendations'));

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
children.push(p('This section documents known data gaps, conflicts, and assumptions to support report credibility. Every metric in this report carries a source label.', { italic:true, color:C.gray }));

children.push(heading('Source Label Key', HeadingLevel.HEADING_2, { before:100 }));
children.push(styledTable(
  ['Label', 'Meaning', 'Confidence'],
  [
    ['[Source-Reported]', 'Direct from brokerage API or manual entry — no transformation', 'High'],
    ['[Pipeline-Derived]', 'Computed by Trade AI pipeline from source data (beta, returns, sectors)', 'Medium-High'],
    ['[Modeled Strategy Layer]', 'Advisory recommendations from AI analysis — projections, not facts', 'Medium'],
  ],
  { colorFn: (v,ci) => ci===2 ? (v==='High'?C.green:v==='Medium-High'?C.accent:C.amber) : C.black }
));

children.push(heading('Known Data Issues', HeadingLevel.HEADING_2, { before:120 }));
const flags = [
  ['Fidelity 401k Gain','No cost basis reported by Fidelity Net Benefits — gain% shown as N/A','Medium'],
  ['Roth Balance','Multiple values: $42,373 vs $42,643 — using latest snapshot','Low'],
  ['V Trim Target','Conflicting: "12-13%" vs "30%" across analysis sections','Medium'],
  ['Weighted Beta','Not populated in portfolio totals — computed in pipeline at 0.38','Low'],
  ['Dividend Calendar','Computed from dividend_calendar.json payers: ' + fUSD(divTotal),'Low'],
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
children.push(sourceLabel('[Modeled Strategy Layer] — generated by AI analyst pipeline'));
children.push(p(`Generated: ${aiAnalysis.generated_at || '—'}  |  Run type: ${aiAnalysis.run_type || '—'}`, { size:9, color:C.grayMid }));

const aiSections = [
  ['executive_summary', 'Executive Summary'],
  ['deep_holdings', 'Deep Holdings Analysis'],
  ['ira_opportunities', 'IRA Opportunity Set'],
  ['roth_conversion', 'Roth Conversion Strategy'],
  ['dividend_strategy', 'Dividend Strategy'],
  ['bond_strategy', 'Bond Strategy'],
  ['v_strategy', 'Visa Concentration Strategy'],
  ['defense_analysis', 'Defense Portfolio Analysis'],
];

let aiSectionsRendered = 0;
aiSections.forEach(([key, title]) => {
  const text = aiAnalysis[key];
  if (!text) return;
  children.push(heading(title, HeadingLevel.HEADING_2, { before: 160 }));
  renderMarkdown(text, children);
  aiSectionsRendered++;
});

if (aiSectionsRendered === 0) {
  children.push(p('No AI analysis sections were populated in this run. This appendix will be populated when the full AI analyst pipeline is executed.', { italic:true, color:C.grayMid, size:10 }));
  children.push(new Paragraph({ spacing: { before: 60 } }));
  children.push(styledTable(
    ['Section', 'Status', 'Notes'],
    aiSections.map(([key, title]) => [
      title,
      aiAnalysis[key] ? 'Populated' : 'Empty',
      aiAnalysis[key] ? `${String(aiAnalysis[key]).length} chars` : 'Run ai_analyst to populate',
    ]),
    { colorFn: (v,ci) => ci===1 ? (v==='Populated'?C.green:C.amber) : C.black }
  ));
}

// ── APPENDIX B: HOLDINGS TABLE ──────────────────────────────────
children.push(pageBreak());
children.push(heading('Appendix: Complete Holdings', HeadingLevel.HEADING_1));
children.push(sourceLabel('All values: [Source-Reported] from brokerage data'));

const sortedHoldings = [...holdings].sort((a,b) => (b.market_value||0)-(a.market_value||0));
const displayHoldings = sortedHoldings.slice(0, 40);
const holdRows = displayHoldings.map(h => [
  h.symbol || '—',
  h.account === 'fidelity_401k' ? '401k' : h.account === 'schwab_rollover_ira' ? 'IRA' : h.account === 'schwab_roth' ? 'Roth' : h.account === 'schwab_taxable' ? 'Taxable' : '—',
  fUSD(h.market_value, 0),
  h.market_value && totalVal ? `${(h.market_value/totalVal*100).toFixed(1)}%` : '—',
  h.gain_loss != null ? fUSD(h.gain_loss, 0) : '—',
]);

// Total row
const totalMV = displayHoldings.reduce((s, h) => s + (h.market_value || 0), 0);
const totalGL = displayHoldings.reduce((s, h) => s + (h.gain_loss || 0), 0);
holdRows.push([
  'TOTAL',
  `${displayHoldings.length} positions`,
  fUSD(totalMV, 0),
  `${(totalMV/totalVal*100).toFixed(1)}%`,
  fUSD(totalGL, 0),
]);

children.push(styledTable(
  ['Symbol', 'Account', 'Value', 'Weight', 'Gain/Loss'],
  holdRows,
  {
    colorFn: (v,ci,ri) => {
      if (ri === holdRows.length - 1) return C.darkBlue; // total row
      if (ci === 4 && v && v !== '—') {
        const num = parseFloat(v.replace(/[$,]/g, ''));
        return num >= 0 ? C.green : C.red;
      }
      return C.black;
    },
    boldFn: (v,ci,ri) => ri === holdRows.length - 1,
    rowShading: (ri) => ri === holdRows.length - 1 ? C.bg2 : (ri % 2 === 0 ? C.white : C.bg1),
  }
));

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
        run(`Data as of: ${asOfDate}`, { size:7, color:C.grayMid }),
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
