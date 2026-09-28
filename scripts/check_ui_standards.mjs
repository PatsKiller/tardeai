#!/usr/bin/env node
// UI standards gate (PR1 ratchet mode, 2026-09-27; binding under AGENTS 1.4.0 §23). No deps.
// Supersedes scripts/check_design_tokens.sh (kept alongside until PR10 removes it).
//
//   node scripts/check_ui_standards.mjs [--update-baseline] [--json] [--strict]
//
// Per source file under apps/command-center-v3/src/{pages,components,lib,hooks,control-plane}:
//   hex    raw colour literals (#abc / #aabbcc[aa]); allowed ONLY in lib/designTokens.ts and styles/tokens.css
//   font   fontSize literals below 10 (7, 7.5, 8, 8.5, 9, 9.5)
//   radius borderRadius literals that are not a token (var(--radius-*), RADIUS.*) -- 999 / 50% / 0 are allowed pills/circles
//   shadow boxShadow literals that are not a token (var(--shadow-*), SHADOW.*, T.focusRing, var(--focus-ring))
//   guide  metric-like elements (<Metric|HeroMetricChip|CompactMetricRow|TipKpi|MetricChipTooltip|Fact|Kpi)
//          without a guideKey= or tip= prop (tooltip coverage)
// A file may not exceed its baseline count in config/ui_standards_baseline.json on any rule;
// files absent from the baseline must be zero on every rule; --update-baseline rewrites it
// (counts only ever go down in review). --strict makes any non-zero count a failure (PR10).
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..')
const SRC = path.join(ROOT, 'apps/command-center-v3/src')
const BASELINE = path.join(ROOT, 'config/ui_standards_baseline.json')
const args = process.argv.slice(2)
const UPDATE = args.includes('--update-baseline')
const STRICT = args.includes('--strict')
const JSON_OUT = args.includes('--json')
const DIRS = ['pages', 'components', 'lib', 'hooks', 'control-plane']
const HEX_ALLOWED = new Set(['lib/designTokens.ts', 'styles/tokens.css'])
const RULES = ['hex', 'font', 'radius', 'shadow', 'guide']

const RE = {
  hex: /#[0-9a-fA-F]{3,8}\b/g,
  font: /fontSize:\s*['"]?(7|7\.5|8|8\.5|9|9\.5)(px)?['"]?/g,
  radius: /border(?:-r|R)adius:\s*(['"`]?)([^,'"`}\n]+)\1/g,
  shadow: /box(?:-s|S)hadow:\s*(['"`])([^'"`]+)\1/g,
  metric: /<(Metric|HeroMetricChip|CompactMetricRow|TipKpi|MetricChipTooltip|Fact|Kpi)\b[^>]*>/gs,
}
const radiusOk = v => /var\(--radius-|RADIUS\.|^(0|999|9999|50%|'999'|"999"|999px|9999px)$|\$\{/.test(v.trim())
const shadowOk = v => /var\(--shadow-|var\(--focus-ring\)|SHADOW\.|T\.focusRing|^none$/.test(v.trim())

function walk(dir, out = []) {
  if (!fs.existsSync(dir)) return out
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p, out)
    else if (/\.(tsx?|css)$/.test(e.name) && !/\.test\.tsx?$/.test(e.name) && !/\.generated\.ts$/.test(e.name)) out.push(p)
  }
  return out
}
const files = [...DIRS.flatMap(d => walk(path.join(SRC, d))), ...walk(path.join(SRC, 'styles'))]
const current = {}
for (const f of files) {
  const rel = path.relative(SRC, f).split(path.sep).join('/')
  const s = fs.readFileSync(f, 'utf8')
  const row = { hex: 0, font: 0, radius: 0, shadow: 0, guide: 0 }
  if (!HEX_ALLOWED.has(rel)) row.hex = (s.match(RE.hex) || []).length
  row.font = (s.match(RE.font) || []).length
  for (const m of s.matchAll(RE.radius)) if (!radiusOk(m[2])) row.radius++
  for (const m of s.matchAll(RE.shadow)) if (!shadowOk(m[2])) row.shadow++
  for (const m of s.matchAll(RE.metric)) if (!/\b(guideKey|tip)=/.test(m[0])) row.guide++
  if (RULES.some(r => row[r] > 0)) current[rel] = row
}

if (UPDATE) {
  const sorted = Object.fromEntries(Object.keys(current).sort().map(k => [k, current[k]]))
  fs.writeFileSync(BASELINE, JSON.stringify({ schema: 'UiStandardsBaseline@v1', rules: RULES, updated_at: new Date().toISOString().slice(0, 10), files: sorted }, null, 1) + '\n')
  const t = RULES.map(r => `${r}=${Object.values(current).reduce((a, b) => a + b[r], 0)}`).join(' ')
  console.log(`[ui-standards] baseline updated: ${Object.keys(sorted).length} files with frozen debt (${t})`)
  process.exit(0)
}
if (!fs.existsSync(BASELINE)) { console.log('[ui-standards] FAIL: baseline missing — run with --update-baseline once'); process.exit(1) }
const base = JSON.parse(fs.readFileSync(BASELINE, 'utf8')).files || {}
const failures = []
for (const [rel, row] of Object.entries(current)) {
  const b = base[rel] || {}
  for (const r of RULES) {
    const allowed = STRICT ? 0 : (b[r] || 0)
    if (row[r] > allowed) failures.push({ file: rel, rule: r, count: row[r], baseline: allowed })
  }
}
const totals = Object.fromEntries(RULES.map(r => [r, Object.values(current).reduce((a, b) => a + b[r], 0)]))
if (JSON_OUT) console.log(JSON.stringify({ strict: STRICT, files: files.length, totals, failures }, null, 1))
else {
  for (const f of failures) console.log(`[ui-standards] FAIL ${f.file}: ${f.rule}=${f.count} (baseline ${f.baseline}) — tokens only (designTokens.ts), no fonts below 10, RADIUS/SHADOW tokens, guideKey on every metric`)
  console.log(`[ui-standards] ${failures.length ? 'blocked' : 'pass'} — ${files.length} files; debt ${RULES.map(r => `${r}=${totals[r]}`).join(' ')}${STRICT ? ' (strict)' : ''}`)
}
process.exit(failures.length ? 1 : 0)
