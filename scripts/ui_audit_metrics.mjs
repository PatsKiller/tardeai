#!/usr/bin/env node
// UI audit metrics (2026-09-27): a repeatable, dependency-free census of the Command Center v3
// source. It is the data source for docs/design/UI_AUDIT_2026-09.md and, once the redesign
// ships, for the "after" numbers and the check_ui_standards gate. Read-only.
//
//   node scripts/ui_audit_metrics.mjs [--json out.json] [--md out.md] [--root apps/command-center-v3/src]
//
// Per file: raw hex colours, fontSize literals below 10 (by size), distinct border radii and
// box shadows, inline style objects vs className uses, native <details>, title= attributes,
// metric-like elements and how many of them carry help (guideKey= or tip=), token imports.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const args = process.argv.slice(2)
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d }
const ROOT = path.resolve(HERE, '..', opt('--root', 'apps/command-center-v3/src'))
const OUT_JSON = opt('--json', null)
const OUT_MD = opt('--md', null)
const SCAN_DIRS = ['pages', 'components', 'lib', 'control-plane', 'hooks']
const TOKEN_FILES = new Set(['lib/designTokens.ts', 'styles/tokens.css', 'lib/watchTokens.ts'])

const RE = {
  hex: /#[0-9a-fA-F]{3,8}\b/g,
  fontLt10: /fontSize:\s*['"]?(7|7\.5|8|8\.5|9|9\.5)(px)?['"]?/g,
  radius: /border(?:-r|R)adius:\s*['"]?([^,'"}\n]+)/g,
  shadow: /box(?:-s|S)hadow:\s*['"`]([^'"`]+)/g,
  inlineStyle: /style=\{\{/g,
  className: /className=/g,
  details: /<details\b/g,
  titleAttr: /\btitle=\{?["'`]/g,
  metricLike: /<(Metric|HeroMetricChip|CompactMetricRow|TipKpi|MetricChipTooltip|Fact|Kpi)\b[^>]*>/gs,
  guided: /\b(guideKey|tip)=/,
  imports: /from\s+['"][^'"]*(watchTokens|watchlistTerminalTokens|watchlistCardTokens|holdingsTerminalTokens|terminalCardTheme|terminalHubChrome|proposalDeskTheme|terminalUi|designTokens)['"]/g,
  cssVar: /var\(--/g,
}

function walk(dir, out = []) {
  if (!fs.existsSync(dir)) return out
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name)
    if (ent.isDirectory()) walk(p, out)
    else if (/\.(tsx?|css|mjs)$/.test(ent.name) && !/\.test\.tsx?$/.test(ent.name)) out.push(p)
  }
  return out
}

function count(re, s) { return (s.match(re) || []).length }
function tally(re, s, group = 1) {
  const m = {}
  for (const x of s.matchAll(re)) { const k = (x[group] || '').trim(); if (k) m[k] = (m[k] || 0) + 1 }
  return m
}

const files = SCAN_DIRS.flatMap(d => walk(path.join(ROOT, d)))
const perFile = {}
const totals = { files: 0, hex: 0, fontLt10: 0, inlineStyle: 0, className: 0, details: 0, titleAttr: 0,
  metricLike: 0, metricWithGuide: 0, cssVar: 0, radii: {}, shadows: {}, fontLt10By: {}, tokenImports: {} }
for (const f of files) {
  const rel = path.relative(ROOT, f).split(path.sep).join('/')
  const s = fs.readFileSync(f, 'utf8')
  const isTokenFile = TOKEN_FILES.has(rel)
  const metricTags = s.match(RE.metricLike) || []
  const withGuide = metricTags.filter(t => RE.guided.test(t)).length
  const fontBy = tally(RE.fontLt10, s)
  const radii = tally(RE.radius, s)
  const shadows = tally(RE.shadow, s)
  const row = {
    hex: isTokenFile ? 0 : count(RE.hex, s),
    hexInTokenFile: isTokenFile ? count(RE.hex, s) : 0,
    fontLt10: Object.values(fontBy).reduce((a, b) => a + b, 0),
    fontLt10By: fontBy,
    radii, shadows,
    inlineStyle: count(RE.inlineStyle, s), className: count(RE.className, s),
    details: count(RE.details, s), titleAttr: count(RE.titleAttr, s),
    metricLike: metricTags.length, metricWithGuide: withGuide,
    cssVar: count(RE.cssVar, s),
    tokenImports: [...new Set([...s.matchAll(RE.imports)].map(m => m[1]))],
    lines: s.split('\n').length,
  }
  perFile[rel] = row
  totals.files++
  for (const k of ['hex', 'fontLt10', 'inlineStyle', 'className', 'details', 'titleAttr', 'metricLike', 'metricWithGuide', 'cssVar']) totals[k] += row[k]
  for (const [k, v] of Object.entries(radii)) totals.radii[k] = (totals.radii[k] || 0) + v
  for (const [k, v] of Object.entries(shadows)) totals.shadows[k] = (totals.shadows[k] || 0) + v
  for (const [k, v] of Object.entries(fontBy)) totals.fontLt10By[k] = (totals.fontLt10By[k] || 0) + v
  for (const t of row.tokenImports) totals.tokenImports[t] = (totals.tokenImports[t] || 0) + 1
}
totals.distinctRadii = Object.keys(totals.radii).length
totals.distinctShadows = Object.keys(totals.shadows).length
totals.tooltipCoveragePct = totals.metricLike ? Math.round(1000 * totals.metricWithGuide / totals.metricLike) / 10 : null

const top = (m, n = 12) => Object.entries(m).sort((a, b) => b[1] - a[1]).slice(0, n)
const worst = (k, n = 15) => Object.entries(perFile).sort((a, b) => b[1][k] - a[1][k]).slice(0, n).filter(([, r]) => r[k] > 0)
const report = { schema: 'UiAuditMetrics@v1', generated_at: new Date().toISOString(), root: path.relative(path.resolve(HERE, '..'), ROOT), totals, files: perFile }

if (OUT_JSON) fs.writeFileSync(OUT_JSON, JSON.stringify(report, null, 1))
const md = []
md.push(`# UI audit metrics (${report.generated_at.slice(0, 10)})`, '', `Root: \`${report.root}\` · files scanned: ${totals.files}`, '')
md.push('| Signal | Value |', '|---|---|')
md.push(`| Raw hex outside token files | ${totals.hex} |`, `| fontSize < 10px | ${totals.fontLt10} (${Object.entries(totals.fontLt10By).map(([k, v]) => `${k}px: ${v}`).join(', ')}) |`)
md.push(`| Inline style objects | ${totals.inlineStyle} |`, `| className uses | ${totals.className} |`, `| var(--…) uses | ${totals.cssVar} |`)
md.push(`| Distinct border-radius values | ${totals.distinctRadii} |`, `| Distinct box-shadow values | ${totals.distinctShadows} |`)
md.push(`| Native <details> | ${totals.details} |`, `| title= attributes | ${totals.titleAttr} |`)
md.push(`| Metric-like elements | ${totals.metricLike} |`, `| … with guideKey/tip | ${totals.metricWithGuide} (${totals.tooltipCoveragePct}%) |`)
md.push(`| Token imports (files) | ${Object.entries(totals.tokenImports).map(([k, v]) => `${k}: ${v}`).join(', ')} |`, '')
md.push('## Radii (top)', '', '| value | uses |', '|---|---|', ...top(totals.radii).map(([k, v]) => `| \`${k}\` | ${v} |`), '')
md.push('## Shadows (top)', '', '| value | uses |', '|---|---|', ...top(totals.shadows, 8).map(([k, v]) => `| \`${k.slice(0, 60)}\` | ${v} |`), '')
for (const [k, title] of [['hex', 'Most raw hex'], ['fontLt10', 'Most sub-10px fonts'], ['inlineStyle', 'Most inline styles'], ['metricLike', 'Most metric-like elements']]) {
  md.push(`## ${title}`, '', '| file | count | lines |', '|---|---|---|', ...worst(k).map(([f, r]) => `| \`${f}\` | ${r[k]} | ${r.lines} |`), '')
}
md.push('## Tooltip coverage per file (metric-like ≥ 3)', '', '| file | metric-like | with help | coverage |', '|---|---|---|---|')
for (const [f, r] of Object.entries(perFile).filter(([, r]) => r.metricLike >= 3).sort((a, b) => b[1].metricLike - a[1].metricLike))
  md.push(`| \`${f}\` | ${r.metricLike} | ${r.metricWithGuide} | ${Math.round(100 * r.metricWithGuide / r.metricLike)}% |`)
const text = md.join('\n') + '\n'
if (OUT_MD) fs.writeFileSync(OUT_MD, text)
if (!OUT_JSON && !OUT_MD) process.stdout.write(text)
else console.log(`ui_audit_metrics: ${totals.files} files, hex=${totals.hex}, font<10=${totals.fontLt10}, inline=${totals.inlineStyle}, coverage=${totals.tooltipCoveragePct}%`)
