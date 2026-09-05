// Live header audit against the CURRENTLY SERVING release.
//
// The previous audit (2026-09-04, evidence cc-header-final-20260904T123018Z) ran against
// release ee200ec3 and recorded four defects. That release has since been replaced twice.
// Its findings are historical evidence, not proof of what the current build does, so this
// re-measures the same things against whatever is serving now and records the served SHA
// alongside every number.
//
// Strictly read-only: it loads pages and observes. Any non-GET the page itself issues is
// counted and reported rather than blocked, because the point is to find out whether the
// page issues one.
//
//   node e2e/live_header_audit.mjs <baseUrl> <outJsonPath>

import { chromium } from 'playwright'
import { writeFileSync } from 'node:fs'

const BASE = process.argv[2] || 'http://127.0.0.1:7777'
const OUT = process.argv[3] || '/tmp/live_header_audit.json'

const ROUTES = ['/v3', '/v3/trading']

// Hosts that would mean the browser reached a data provider directly rather than
// going through the server.
const PROVIDER_HOSTS = [
  'finviz', 'alpaca', 'schwab', 'polygon', 'yahoo', 'finnhub',
  'tradier', 'moomoo', 'iexcloud', 'tiingo', 'marketdata',
]

function isProvider(url) {
  try {
    const h = new URL(url).hostname.toLowerCase()
    return PROVIDER_HOSTS.some((p) => h.includes(p))
  } catch {
    return false
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function main() {
  const browser = await chromium.launch({ args: ['--no-sandbox'] })
  const out = {
    schema: 'LiveHeaderAudit@v2',
    generated_at: new Date().toISOString(),
    base: BASE,
    pages: {},
    consoleErrors: [],
    failed: [],
    provider_requests: [],
    mutation_requests: [],
  }

  for (const route of ROUTES) {
    const ctx = await browser.newContext({ viewport: { width: 1600, height: 1200 } })
    const page = await ctx.newPage()
    const consoleErrors = []
    const failed = []
    const requests = []

    page.on('console', (m) => {
      if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 400))
    })
    page.on('requestfailed', (r) =>
      failed.push({ url: r.url().slice(0, 300), reason: r.failure()?.errorText || 'unknown' }),
    )
    page.on('request', (r) => {
      const rec = { url: r.url(), method: r.method() }
      requests.push(rec)
      if (isProvider(rec.url)) out.provider_requests.push({ route, ...rec })
      if (rec.method !== 'GET' && rec.method !== 'HEAD' && rec.method !== 'OPTIONS') {
        out.mutation_requests.push({ route, ...rec })
      }
    })

    await page.goto(BASE + route, { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {})
    // The header resolves asynchronously; give it room to settle before reading text.
    await sleep(4000)

    const body = await page.evaluate(() => document.body?.innerText || '').catch(() => '')
    const title = await page.title().catch(() => '')

    out.pages[route] = {
      title,
      text_length: body.length,
      shell_only: body.trim().length < 200,
      console_error_count: consoleErrors.length,
      console_errors_sample: consoleErrors.slice(0, 12),
      failed_request_count: failed.length,
      failed_sample: failed.slice(0, 8),
      request_count: requests.length,
      // The specific strings the ee200ec3 audit called contradictory.
      header_counts: extract(body, [
        /(\d[\d,]*)\s*classified/i,
        /(\d[\d,]*)\s*scanned/i,
        /(\d[\d,]*)\s*excluded/i,
      ]),
      decision_counts: extract(body, [
        /(\d[\d,]*)\s*GO\b/i,
        /(\d[\d,]*)\s*WAIT\b/i,
        /(\d[\d,]*)\s*NO[- ]?GO\b/i,
      ]),
      mentions_all_accounts: /ALL[_ ]ACCOUNTS/i.test(body),
      // The 2026-09-04 capture's twelve defects, each as a positive observation
      // of the fix rather than an absence of the old string.
      clock_labels: {
        positions_observed: /positions observed/i.test(body),
        pnl_session: /P&L session/i.test(body),
        no_bare_data_as_of_on_tiles: !/\bdata_as_of\s+\d{4}-\d{2}-\d{2}/i.test(body),
        // Account census moved to hover (title) after 2026-09-04; face is date-only.
        // Observe body for dates; title attributes for oldest/coverage when present.
        coverage_pct_on_face: /covers\s+[\d.]+% of value/i.test(body),
        oldest_with_stamp_on_face: /oldest\s+\S+\s+\d{4}-\d{2}-\d{2}/i.test(body),
        oldest_with_age_on_face: /\(\d+[dh] old\)/i.test(body),
        undated_accounts: /accounts undated|contributing undated/i.test(body),
      },
      universe_kpi_labels: {
        universe_go: /UNIVERSE GO/i.test(body),
        universe_wait: /UNIVERSE WAIT/i.test(body),
      },
      count_labels: {
        run_id: /id\s+\d{4}-\d{2}-\d{2}::\d{4}/.test(body),
        manual_review: /manual review/i.test(body),
        unaccounted: /UNACCOUNTED/.test(body),
        pending_not_p0: /proposals pending review/i.test(body),
      },
      // Every distinct "N classified / M scanned" the page renders. Two
      // different values here is the contradiction, not a rendering detail.
      population_strings: [...new Set(
        (body.match(/\d[\d,]*\s+classified\s*\/\s*\d[\d,]*\s+scanned[^\n]*/gi) || [])
          .map((s) => s.trim()),
      )],
      // Every date the page shows, so two clocks disagreeing is visible.
      dates_rendered: [...new Set(body.match(/\d{4}-\d{2}-\d{2}/g) || [])].sort(),
      mentions_alpaca: /alpaca/i.test(body),
      pnl_labels: (body.match(/[A-Za-z ]{0,24}P&?L[A-Za-z ]{0,24}/gi) || []).slice(0, 12),
      body_excerpt: body.slice(0, 1500),
    }
    out.consoleErrors.push(...consoleErrors.map((e) => ({ route, text: e })))
    out.failed.push(...failed.map((f) => ({ route, ...f })))
    await ctx.close()
  }

  out.provider_call_count = out.provider_requests.length
  out.mutation_count = out.mutation_requests.length
  out.total_console_errors = out.consoleErrors.length

  await browser.close()
  writeFileSync(OUT, JSON.stringify(out, null, 1))
  console.log(`wrote ${OUT}`)
  for (const [r, p] of Object.entries(out.pages)) {
    console.log(
      `${r}: shell_only=${p.shell_only} console_errors=${p.console_error_count} ` +
        `failed=${p.failed_request_count} header=${JSON.stringify(p.header_counts)} ` +
        `decisions=${JSON.stringify(p.decision_counts)}`,
    )
  }
  console.log(`provider calls on load: ${out.provider_call_count}  non-read requests: ${out.mutation_count}`)
}

function extract(text, patterns) {
  return patterns.map((re) => {
    const m = text.match(re)
    return m ? m[1] : null
  })
}

main().catch((e) => {
  console.error('audit failed:', e)
  process.exit(1)
})
