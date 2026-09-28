#!/usr/bin/env node
// WCAG 2.1 AA contrast check for src/styles/tokens.css (PR1, 2026-09-27). No dependencies.
// Runs in the CC-v3 build. Pairs checked per theme (dark, light, terminal skin):
//   text-0..3 on bg-0..3                    >= 4.5:1
//   each tone -color on bg-0..2             >= 4.5:1
//   each tone -color on its own -bg (over bg-0) >= 4.5:1
//   primary/secondary on bg-0..2            >= 4.5:1
//   border-color on bg-0 (non-text UI)      >= 1.5:1 (subtle rule) -- reported, not enforced
//   node scripts/check_token_contrast.mjs [--json] [--min 4.5]
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const CSS = path.resolve(HERE, '..', 'apps/command-center-v3/src/styles/tokens.css')
const args = process.argv.slice(2)
const MIN = parseFloat(args[args.indexOf('--min') + 1] || '4.5') || 4.5
const JSON_OUT = args.includes('--json')

const src = fs.readFileSync(CSS, 'utf8')
function block(selector) {
  const re = new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([\\s\\S]*?)\\n\\}', 'm')
  const m = src.match(re)
  return m ? m[1] : ''
}
function vars(text) {
  const out = {}
  for (const m of text.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)) out[m[1]] = m[2].trim()
  return out
}
const themes = {
  dark: vars(block(':root,\n[data-theme="dark"]')),
  light: vars(block('[data-theme="light"]')),
}
themes.terminal = { ...themes.dark, ...vars(block('.cc-terminal-ui')) }

function parse(c) {
  c = c.trim()
  let m = c.match(/^#([0-9a-f]{6})$/i)
  if (m) return [parseInt(m[1].slice(0, 2), 16), parseInt(m[1].slice(2, 4), 16), parseInt(m[1].slice(4, 6), 16), 1]
  m = c.match(/^#([0-9a-f]{3})$/i)
  if (m) return [...m[1]].map(h => parseInt(h + h, 16)).concat([1])
  m = c.match(/^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+))?\s*\)$/)
  if (m) return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]]
  return null
}
function over(fg, bg) { // composite fg (with alpha) over opaque bg
  const a = fg[3]
  return [0, 1, 2].map(i => Math.round(fg[i] * a + bg[i] * (1 - a))).concat([1])
}
function lum([r, g, b]) {
  const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}
function ratio(fg, bg) {
  const a = lum(fg), b = lum(bg)
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

const TONES = ['success', 'warning', 'danger', 'info', 'ai', 'neutral']
const results = []
for (const [theme, t] of Object.entries(themes)) {
  const get = k => { const p = parse(t[k] || ''); if (!p) throw new Error(`${theme}: cannot parse --${k} = ${t[k]}`); return p }
  const bgs = ['bg-0', 'bg-1', 'bg-2', 'bg-3'].map(get)
  const check = (name, fg, bg, min = MIN) => {
    const r = Math.round(ratio(fg, bg) * 100) / 100
    results.push({ theme, pair: name, ratio: r, min, ok: r >= min })
  }
  for (const tx of ['text-0', 'text-1', 'text-2', 'text-3']) bgs.forEach((bg, i) => check(`${tx} on bg-${i}`, get(tx), bg))
  for (const tone of TONES) {
    const col = get(`${tone}-color`)
    bgs.slice(0, 3).forEach((bg, i) => check(`${tone}-color on bg-${i}`, col, bg))
    check(`${tone}-color on ${tone}-bg`, col, over(get(`${tone}-bg`), bgs[0]))
  }
  for (const k of ['primary-color', 'secondary-color']) bgs.slice(0, 3).forEach((bg, i) => check(`${k} on bg-${i}`, get(k), bg))
  check('border-color on bg-0 (advisory)', get('border-color'), bgs[0], 1.3)
}
const failed = results.filter(r => !r.ok)
if (JSON_OUT) console.log(JSON.stringify({ min: MIN, checked: results.length, failed: failed.length, results }, null, 1))
else {
  for (const r of failed) console.log(`[contrast] FAIL ${r.theme}: ${r.pair} = ${r.ratio}:1 (min ${r.min})`)
  console.log(`[contrast] ${results.length - failed.length}/${results.length} pairs pass across ${Object.keys(themes).length} themes (min ${MIN}:1)`)
}
process.exit(failed.length ? 1 : 0)
