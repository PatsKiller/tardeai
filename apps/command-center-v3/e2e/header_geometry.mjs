// Header geometry — the check that would have caught the layout defect.
//
// Thirty source-shape assertions all passed while the header was unreadable,
// because every string in it was correct. What was wrong was measurable and
// nothing measured it: a price stamp painting 323px outside its own box, a
// provenance line rendered at the same size as other tiles' primary values, and
// a strip that grew from 99px to 141px as the viewport narrowed.
//
// This asserts the geometry directly, at several widths, against a live server.
// Strictly read-only: it loads pages and measures them.
//
//   node e2e/header_geometry.mjs [baseUrl] [outJson]

import { chromium } from 'playwright'
import { writeFileSync } from 'node:fs'

const BASE = process.argv[2] || 'http://127.0.0.1:7777'
const OUT = process.argv[3] || ''
// When the page is served from a static preview that has no backend, point API
// calls at the real one. Read-only: it rewrites the target host, nothing else.
const API = process.env.HEADER_GEOMETRY_API || ''
const WIDTHS = [1280, 1440, 1700, 2000]

// A header that changes height with viewport width is one that reflows.
const MAX_STRIP_HEIGHT = 88
const MAX_META_HEIGHT = 16   // one line at 10px; more means it wrapped
const MAX_WIDTH_SPREAD = 3.2 // was 8.3x

let pass = 0
let fail = 0
const check = (name, cond, detail) => {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}${detail ? ` — ${detail}` : ''}`) }
}

async function measure(page, width) {
  await page.setViewportSize({ width, height: 900 })
  await page.goto(`${BASE}/v3/`, { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {})
  await new Promise((r) => setTimeout(r, 3500))
  return page.evaluate(() => {
    const strip = document.querySelector('.metric-strip')
    if (!strip) return null
    const px = (el) => parseFloat(getComputedStyle(el).fontSize)
    const sr = strip.getBoundingClientRect()
    const stamp = strip.querySelector('[data-price-stamp]')
    const tiles = [...document.querySelectorAll('.metric-strip-tile')].map((t) => {
      const l = t.querySelector('.ms-label')
      const v = t.querySelector('.ms-value')
      const m = t.querySelector('.ms-meta')
      return {
        label: (l?.textContent || '').trim().slice(0, 18),
        labelPx: l ? px(l) : null,
        valuePx: v ? px(v) : null,
        metaPx: m ? px(m) : null,
        metaHeight: m ? m.clientHeight : null,
        metaClipped: m ? m.scrollWidth > m.clientWidth : false,
        width: Math.round(t.getBoundingClientRect().width),
        lines: (t.innerText || '').split('\n').filter(Boolean).length,
      }
    })
    // A SPILL is paint escaping a box that does not clip — the price stamp's
    // `overflow: visible` painting 323px over the PORTFOLIO tile. Content inside
    // a scrollable container that extends past the viewport is NOT a spill: the
    // strip's row is `overflow-x: auto` by design, which is the chosen
    // horizontal-scroll behaviour. Only report an element that escapes an
    // ancestor which never clips it.
    const clips = (el) => {
      for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
        const o = getComputedStyle(a)
        if (o.overflow !== 'visible' || o.overflowX !== 'visible' || o.overflowY !== 'visible') return true
      }
      return false
    }
    const escapes = [...strip.querySelectorAll('*')]
      .filter((e) => {
        const r = e.getBoundingClientRect()
        if (r.width <= 0) return false
        const p = e.parentElement
        if (!p) return false
        const pr = p.getBoundingClientRect()
        // escaping its own parent's box, and nothing above it clips.
        return (r.right > pr.right + 1 || r.bottom > pr.bottom + 1) && !clips(e)
      })
      .map((e) => `${e.className || e.tagName}@${Math.round(e.getBoundingClientRect().right)}`)
    return {
      height: Math.round(sr.height),
      tiles,
      escapes: escapes.slice(0, 6),
      stamp: stamp
        ? {
            client: stamp.clientWidth,
            scroll: stamp.scrollWidth,
            textOverflow: getComputedStyle(stamp).textOverflow,
            overflow: getComputedStyle(stamp).overflowX,
            title: (stamp.getAttribute('title') || '').slice(0, 400),
          }
        : null,
    }
  })
}

async function main() {
  const browser = await chromium.launch({ args: ['--no-sandbox'] })
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  if (API) {
    await page.route('**/api/**', (route) => {
      const u = new URL(route.request().url())
      route.continue({ url: API.replace(/\/$/, '') + u.pathname + u.search })
    })
  }
  const results = {}

  for (const w of WIDTHS) {
    const m = await measure(page, w)
    results[w] = m
    console.log(`\n── viewport ${w}px ──`)
    if (!m) { check(`${w}: strip renders`, false); continue }

    check(`${w}: strip is one row (${m.height}px)`, m.height <= MAX_STRIP_HEIGHT, `${m.height} > ${MAX_STRIP_HEIGHT}`)
    check(`${w}: nothing paints outside the strip`, m.escapes.length === 0, m.escapes.join(', '))

    // Vacuity guard. Every size check below filters on `!= null`, so against a
    // build with no .ms-label/.ms-value/.ms-meta they all find nothing and pass
    // while measuring nothing. Ask for the parts first.
    const named = m.tiles.filter((t) => t.labelPx != null && t.valuePx != null)
    check(`${w}: every tile exposes its named parts (else the size checks are vacuous)`,
      m.tiles.length > 0 && named.length === m.tiles.length,
      `${named.length}/${m.tiles.length} tiles have .ms-label + .ms-value`)

    // THE regression test for the inverted ordinal selector.
    const outsized = m.tiles.filter((t) => t.metaPx != null && t.valuePx != null && t.metaPx >= t.valuePx)
    check(`${w}: no provenance line is sized like a value`, outsized.length === 0,
      outsized.map((t) => `${t.label} meta=${t.metaPx} value=${t.valuePx}`).join('; '))

    const tinyLabels = m.tiles.filter((t) => t.labelPx != null && t.labelPx < 10)
    check(`${w}: every label is at or above the 10px house floor`, tinyLabels.length === 0,
      tinyLabels.map((t) => `${t.label}=${t.labelPx}px`).join('; '))

    const wrapped = m.tiles.filter((t) => t.metaHeight != null && t.metaHeight > MAX_META_HEIGHT)
    check(`${w}: no provenance line wrapped`, wrapped.length === 0,
      wrapped.map((t) => `${t.label} h=${t.metaHeight}`).join('; '))

    const tall = m.tiles.filter((t) => t.lines > 3)
    check(`${w}: no tile exceeds three lines`, tall.length === 0,
      tall.map((t) => `${t.label}=${t.lines}`).join('; '))

    const ws = m.tiles.map((t) => t.width).filter((x) => x > 0)
    const spread = Math.max(...ws) / Math.min(...ws)
    check(`${w}: tile width spread is bounded (${spread.toFixed(1)}x)`, spread <= MAX_WIDTH_SPREAD)

    if (m.stamp) {
      // `scrollWidth > clientWidth` here is CORRECT — it is what elision looks
      // like. The defect was a box that did not clip at all, so the property
      // that matters is a bounded width plus a clipping overflow.
      check(`${w}: price stamp box is bounded`, m.stamp.client <= 220, `${m.stamp.client}px`)
      check(`${w}: price stamp clips rather than painting over its neighbour`,
        m.stamp.overflow !== 'visible', m.stamp.overflow)
      check(`${w}: price stamp elides`, m.stamp.textOverflow === 'ellipsis', m.stamp.textOverflow)
      // What left the face must still be reachable, or it left the surface.
      check(`${w}: the full quote provenance survives in the title`,
        /observed/.test(m.stamp.title), m.stamp.title.slice(0, 80))
    } else {
      check(`${w}: price stamp present`, false)
    }
  }

  // Height must not vary with width — that is what "locked to one row" means.
  const heights = WIDTHS.map((w) => results[w]?.height).filter((h) => h != null)
  check(`strip height is identical at every width (${heights.join(', ')})`,
    new Set(heights).size === 1)

  if (OUT) writeFileSync(OUT, JSON.stringify({ generated_at: new Date().toISOString(), base: BASE, results }, null, 1))
  console.log(`\nheader_geometry: ${pass} passed, ${fail} failed`)
  await browser.close()
  if (fail) process.exit(1)
}

main().catch((e) => { console.error('geometry audit failed:', e); process.exit(1) })
