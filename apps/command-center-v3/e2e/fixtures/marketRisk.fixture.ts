/** Synthetic market-risk fixtures for GET /api/v2/market-risk/latest (design home/v002, risk/v002). No real positions. */
import type { Page } from '@playwright/test'

const NOW = Date.parse('2031-03-10T15:00:00Z')
const iso = (ago = 0) => new Date(NOW - ago).toISOString()

export function marketRiskRed() {
  return { schema: 'MarketRiskProjection@v1', state: 'evaluated', tier: 'RED', score: 83, as_of: iso(120_000), age_hours: 0.03, stale: false,
    confirming: { n: 6, of: 9 }, deescalates_if: 'the NQ proxy is above −0.75% pre-market and put/call volume is below 2.0 at 09:45 ET',
    contributors: [
      { name: 'Futures / extended hours', points: 18, detail: 'NQ −1.6%', as_of: iso(600_000) },
      { name: 'Event cluster', points: 17, detail: 'two index heavyweights reported after hours' },
      { name: 'Options flow', points: 15, detail: 'QQQ put/call volume 3.31 = 2.9× median' },
      { name: 'Breadth', points: 14, detail: '230 new lows' },
      { name: 'Semiconductors', points: 11, detail: 'SMH −2.4%' },
    ],
    uplift: { market_score: 75, vulnerability: 78 },
    categories: [
      { name: 'Extended hours', state: 'STRESS', detail: 'NQ proxy −1.6%', weight: 1.0, as_of: iso(600_000) },
      { name: 'Event', state: 'STRESS', detail: 'concentration 88', weight: 1.0 },
      { name: 'Options flow', state: 'STRESS', detail: 'put/call volume 2.9× median', weight: 0.8 },
      { name: 'Breadth', state: 'STRESS', detail: '230 new lows', weight: 1.0 },
      { name: 'Technical', state: 'STRESS', detail: 'failed retest', weight: 0.8 },
      { name: 'Volatility', state: 'WARN', detail: 'VIX down while NDX −2.7%', weight: 1.0 },
      { name: 'Cross-asset', state: 'WARN', detail: 'SPY↔VIX correlation flipped', weight: 1.0 },
      { name: 'Macro / credit', state: 'CALM', detail: 'HY OAS tightening', weight: 1.0 },
      { name: 'Seasonal', state: 'UNKNOWN', detail: 'source not read since its stale window', weight: 0 },
    ],
    episode: { id: 'EP-FIXTURE-1', tier: 'RED', opened_at: iso(3_600_000 * 11), repeats: 3, max_repeats: 12, acknowledged_at: null, status: 'OPEN' },
    book: { vulnerability: 78, budgets: [
      { budget: 'Growth style', actual: 85, limit: 50, unit: '%', breached: true },
      { budget: 'Earnings exposure, next 48h', actual: 31, limit: 25, unit: '%', breached: true },
      { budget: 'AI basket (look-through)', actual: 33, limit: 35, unit: '%', breached: false },
      { budget: 'Single sector', actual: 19, limit: 30, unit: '%', breached: false },
    ], positions: [{ symbol: 'DEMOA', stop_distance_pct: 4.5 }, { symbol: 'DEMOB', note: 'entered 4 days ago, reports in 3 sessions' }] },
    probabilities: [
      { horizon: '4h', move_1_5: 0.41, move_3: 0.12, up: 0.39, down: 0.61, vix_up_20: 0.38, trend_continues: 0.66 },
      { horizon: '24h', move_1_5: 0.68, move_3: 0.31, up: 0.36, down: 0.64, vix_up_20: 0.55, trend_continues: 0.63 },
      { horizon: '72h', move_1_5: 0.79, move_3: 0.46, up: 0.42, down: 0.58, vix_up_20: 0.62, trend_continues: 0.55 },
      { horizon: '1w', move_1_5: 0.84, move_3: 0.52, up: 0.46, down: 0.54, vix_up_20: 0.6, trend_continues: 0.52 },
    ],
    history: Array.from({ length: 10 }, (_, i) => ({ as_of: iso((10 - i) * 86_400_000), score: [38, 42, 40, 44, 47, 49, 63, 68, 83, 83][i], tier: i < 6 ? 'YELLOW' : i < 8 ? 'ORANGE' : 'RED', sent: i === 6 ? 'ORANGE' : i === 8 ? 'RED' : null })),
    sources: {} }
}

export function marketRiskGreen() {
  return { ...marketRiskRed(), tier: 'GREEN', score: 18, confirming: { n: 1, of: 9 }, episode: null, uplift: null, book: null,
    contributors: [{ name: 'Breadth', points: 6, detail: 'broadening' }, { name: 'Volatility', points: 4, detail: 'falling' }],
    categories: [{ name: 'Breadth', state: 'CALM' }, { name: 'Seasonal', state: 'WARN' }] }
}

export function marketRiskNotEvaluated() {
  return { schema: 'MarketRiskProjection@v1', state: 'not_evaluated', tier: 'NOT_EVALUATED', score: null, as_of: null, age_hours: null, stale: false,
    reason: 'Market Risk Engine not live yet (fixture); only the P0 options-flow detector reports', contributors: [], categories: [], episode: null, book: null, probabilities: null,
    sources: { options_flow: { as_of: iso(3_600_000), findings: [{ symbol: 'QQQ', state: 'STRESS', pc_vol_ratio: 3.309, pc_vol_factor: 3.4 }, { symbol: 'SPY', state: 'WARN', pc_oi_ratio: 1.51 }], priority: 'P1', session: 'regular' } } }
}

/** What the API serves from shadow_latest.json when no live snapshot exists: labelled, never with a live episode. */
export function marketRiskShadow(tier: 'RED' | 'YELLOW') {
  const base = tier === 'RED' ? marketRiskRed() : { ...marketRiskRed(), tier: 'YELLOW', score: 59.7, confirming: { n: 2, of: 9 }, uplift: null }
  return { ...base, mode: 'shadow', episode: null }
}

/** Design home/v004: the live projection's YELLOW shape (MarketRiskProjection@v1). Market figures as served on
 *  2026-11-01; the book carries budget names and synthetic DEMO symbols only (no actual/limit, as the API serves it). */
export function marketRiskYellow(mode: 'live' | 'shadow' = 'live') {
  return { schema: 'MarketRiskProjection@v1', state: 'evaluated', tier: 'YELLOW', score: 59.744, as_of: iso(1_200_000), age_hours: 0.33, stale: false, stale_after_hours: 1,
    reason: null, confirming: { n: 2, of: 9 }, uplift: null, episode: null, mode, carried_only: false,
    deescalates_if: 'YELLOW -> BLUE if score below 40 (now 60) and fewer than 3 categories at WARN or STRESS (now 2); the largest driver is options_flow.',
    contributors: [
      { name: 'Options flow', category: 'options_flow', points: 34.42, detail: 'QQQ P/C OI 3.97 (3.85x median) · SPY P/C OI 2.20 (2.32x median)', as_of: iso(86_400_000 * 2) },
      { name: 'Technical', category: 'technical', points: 25.32, detail: 'AI basket: 0% above 20-day · RS -15.3 pts vs benchmark · SOXX -28.0% off 52w high', as_of: iso(86_400_000 * 2 + 5_000_000) },
    ],
    categories: [
      { name: 'Technical', state: 'STRESS' }, { name: 'Breadth', state: 'CALM' }, { name: 'Volatility', state: 'CALM' }, { name: 'Options flow', state: 'STRESS' },
      { name: 'Macro credit', state: 'CALM' }, { name: 'Cross asset', state: 'CALM' }, { name: 'Event', state: 'CALM' }, { name: 'Seasonal', state: 'CALM' },
      { name: 'Extended hours', state: 'UNKNOWN', detail: 'no proven extended-session print for the index proxies' },
    ],
    book: { vulnerability: 8.4, note: 'components: synthetic',
      budgets: [ { budget: 'single_sector_pct', scope: 'account', breached: true }, { budget: 'growth_style_pct', scope: 'account', breached: true },
        { budget: 'unprotected_pct', scope: 'account', breached: true }, { budget: 'single_sector_pct', scope: 'account', breached: true } ],
      positions: [ { symbol: 'DEMOA', stop_distance_pct: 4.5, note: null }, { symbol: 'DEMOB', stop_distance_pct: null, note: null },
        { symbol: 'DEMOC', stop_distance_pct: null, note: null }, { symbol: 'DEMOD', stop_distance_pct: null, note: null }, { symbol: 'DEMOE', stop_distance_pct: null, note: null } ] },
    probabilities: null, history: [], sources: {} }
}

/** Route the market-risk endpoints on top of whatever page fixtures are already installed (later routes win). */
export async function marketRiskRoutes(page: Page, variant: 'red' | 'green' | 'not_evaluated' | 'shadow_red' | 'shadow_yellow' | 'carried_yellow' | 'yellow_live' | 'yellow_shadow' | 'yellow_stale' | 'yellow_empty' | 'yellow_nobook' | 'orange', writes: string[] = []) {
  const v4: Record<string, unknown> = {
    yellow_live: marketRiskYellow('live'), yellow_shadow: marketRiskYellow('shadow'),
    yellow_stale: { ...marketRiskYellow('shadow'), state: 'stale', stale: true, age_hours: 3.2, as_of: iso(3.2 * 3_600_000) },
    yellow_empty: { ...marketRiskYellow('live'), contributors: [], book: null },
    yellow_nobook: { ...marketRiskYellow('live'), book: null },
    orange: { ...marketRiskRed(), tier: 'ORANGE', score: 68, episode: { id: 'EP-FIXTURE-2', tier: 'ORANGE', opened_at: iso(3_600_000), repeats: 1, max_repeats: 12, acknowledged_at: null, status: 'OPEN' } },
  }
  const body = variant in v4 ? v4[variant] : variant === 'red' ? marketRiskRed() : variant === 'green' ? marketRiskGreen() : variant === 'shadow_red' ? marketRiskShadow('RED') : variant === 'shadow_yellow' ? marketRiskShadow('YELLOW') : variant === 'carried_yellow' ? { ...marketRiskShadow('YELLOW'), mode: 'live', carried_only: true } : marketRiskNotEvaluated()
  await page.route('**/api/v2/market-risk/**', route => {
    const req = route.request(), p = new URL(req.url()).pathname
    if (req.method() === 'POST' && p === '/api/v2/market-risk/ack') {
      writes.push(`POST ${p} ${req.postData() ?? ''}`)
      return route.fulfill({ status: 501, contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'acknowledgment store not built yet (fixture)', episode_id: 'EP-FIXTURE-1' }) })
    }
    if (req.method() === 'GET' && p === '/api/v2/market-risk/latest') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: body }) })
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
  })
}
