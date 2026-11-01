/** Synthetic market-risk fixtures for GET /api/v2/market-risk/latest (design home/v002, risk/v002). No real positions. */
import type { Page } from '@playwright/test'
import { readFileSync } from 'node:fs'

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


/** Design home/v005: the YELLOW projection with the engine pass-through and the API-side dollar join. Synthetic DEMO
 *  symbols, synthetic accounts and dollars only — never real holdings. */
export function marketRiskV005(tier: 'YELLOW' | 'ORANGE' = 'YELLOW') {
  const base: any = tier === 'YELLOW' ? marketRiskYellow('shadow') : { ...marketRiskRed(), tier: 'ORANGE', score: 72, mode: 'live',
    episode: { id: 'EP-FIXTURE-5', tier: 'ORANGE', opened_at: iso(3_600_000), repeats: 1, max_repeats: 12, acknowledged_at: null, status: 'OPEN' } }
  const heat = (key: string, label: string, kind: string, state: string, rs1: number | null, rs5: number | null) => ({ key, label, kind, state, tier: state === 'STRESS' ? 'RED' : state === 'UNKNOWN' ? 'UNKNOWN' : 'GREEN', rs1, rs5, reason_unknown: state === 'UNKNOWN' ? 'insufficient history' : null })
  const exitDay = new Date(NOW - 86_400_000 * 2).toISOString().slice(0, 10)
  return { ...base,
    shock_type: { class: 'SECTOR', label: 'sector / theme', headline: 'Type: SECTOR' },
    sectors: { stressed: ['Technology', 'Semis', 'AI basket'], sectors_measured: 9 },
    heatmap: [
      heat('tech', 'Technology', 'sector', 'STRESS', -3.11, -1.5), heat('comm', 'Communications', 'sector', 'UNKNOWN', null, null),
      heat('discretionary', 'Discretionary', 'sector', 'RESILIENT', 1.1, 2.54), heat('staples', 'Staples', 'sector', 'RESILIENT', 3.23, 1.84),
      heat('healthcare', 'Healthcare', 'sector', 'RESILIENT', 2.25, 3.69), heat('utilities', 'Utilities', 'sector', 'RESILIENT', 2.5, 2.62),
      heat('energy', 'Energy', 'sector', 'RESILIENT', 3.66, 1.52), heat('financials', 'Financials', 'sector', 'RESILIENT', 1.03, 1.63),
      heat('industrials', 'Industrials', 'sector', 'RESILIENT', 0.18, 2.23), heat('materials', 'Materials', 'sector', 'RESILIENT', 2.19, 3.33),
      heat('real_estate', 'Real estate', 'sector', 'UNKNOWN', null, null), heat('semis', 'Semis', 'theme', 'STRESS', -5.78, -0.61),
      heat('ai_basket', 'AI basket', 'theme', 'STRESS', -3.0, -2.98),
    ],
    book_exposure: {
      total_usd: 500_000, home_total_usd: 500_000, reconciles: true, cash_usd: 200_000, invested_usd: 300_000,
      stressed_groups: ['ai_basket', 'semis', 'tech'], stressed_usd: 12_400, stressed_pct_book: 2.48, stressed_pct_invested: 4.13, cash_pct_book: 40,
      largest_contributor: { symbol: 'DEMOF', account_label: 'Demo IRA', group: 'tech', share: 0.08 },
      groups: { financials: { usd: 90_000, pct_book: 18 }, industrials: { usd: 60_000, pct_book: 12 }, tech: { usd: 12_400, pct_book: 2.48 },
        comm: { usd: 15_000, pct_book: 3 }, semis: { usd: 6_000, pct_book: 1.2 }, materials: { usd: 20_000, pct_book: 4 } },
      unmapped: [{ symbol: 'DEMOM', account_label: 'Demo IRA', usd: 3_000, reason: 'no sector profile' }],
      rows: [
        { symbol: 'DEMOF', account_label: 'Demo IRA', value_usd: 150_000, pct_account: 30, stressed_share: 0.08, usd_exposed: 12_000, stop_distance_pct: 6.1, stance: 'hold', material: true },
        { symbol: 'DEMOF', account_label: 'Demo Roth', value_usd: 5_000, pct_account: 10, stressed_share: 0.08, usd_exposed: 400, stop_distance_pct: null, stance: 'hold', material: true },
      ],
      more: { count: 0, usd: 0 }, zero_exposure_symbols: ['DEMOA', 'DEMOB'], as_of: '2031-03-09', stops_known: true,
    },
    review: [
      { symbol: 'DEMOA', account_label: 'Demo Roth', kinds: ['stop_near'], text: 'stop 3.5% below last', usd: 40_000, to: '/risk?tab=exposure&symbol=DEMOA' },
      { symbol: 'DEMOA', account_label: 'Demo IRA', kinds: ['no_stop'], text: 'no stop', usd: 30_000, to: '/risk?tab=exposure&symbol=DEMOA' },
      { symbol: 'DEMOB', account_label: 'Demo Taxable', kinds: ['no_stop'], text: 'no stop', usd: 20_000, to: '/risk?tab=exposure&symbol=DEMOB' },
      { symbol: 'DEMOF', account_label: 'Demo IRA', kinds: ['stressed_exposure'], text: '8% in stressed groups', usd: 12_000, to: '/prospectus/DEMOF' },
      { symbol: 'DEMOM', account_label: 'Demo IRA', kinds: ['no_stop', 'no_lookthrough'], text: 'no stop · no look-through (sector unknown)', usd: 3_000, to: '/prospectus/DEMOM' },
    ],
    budgets_detail: [
      { account_label: 'Demo Taxable', budget: 'unprotected_pct', limit: 10, actual: 46.6, unit: '%', actual_usd: 21_000, drivers: [{ name: 'DEMOB', usd: 20_000 }, { name: 'DEMOC', usd: 600 }, { name: 'DEMOD', usd: 400 }, { name: 'DEMOE', usd: 100 }] },
      { account_label: 'Demo Roth', budget: 'single_sector_pct', limit: 30, actual: 96.3, unit: '%', actual_usd: 40_000, drivers: [{ name: 'Financial Services', usd: null }] },
    ],
    reentry_watch: {
      DEMOX: { symbol: 'DEMOX', exit_date: exitDay, exit_price: 34.46, status: 'RE_ENTER_IF', conditions: [{ key: 'earnings_clear', met: true, text: '' }],
        look_through: { groups: { tech: 0.46, discretionary: 0.14, comm: 0.12, healthcare: 0.08 }, basis: 'factsheet' },
        stages: { verdict: 'Still falling', exit_price: 34.46, last_close: 34.32, swing_low: 33.97, invalidation_level: 33.97, sma10: 35.25, sma20: 35.82, pct_vs_exit: -0.41, pct_vs_sma20: -4.19, trend: 'down',
          stage1: { met: 1, of: 5, conditions: [
            { key: 'follow_through', met: false, text: 'higher low + 2 green closes' }, { key: 'volume', met: false, text: 'volume ≥1×' },
            { key: 'group_no_new_low', met: false, text: 'look-through groups still at relative lows' }, { key: 'hedging_easing', met: false, text: 'hedging easing (history 1 of 5 sessions)' },
            { key: 'tier_ok', met: true, text: 'market tier YELLOW' } ] },
          stage2: { met: false, conditions: [{ key: 'above_sma10', met: false, text: 'close above the 10-day 35.25' }, { key: 'above_exit', met: false, text: 'close above 34.46' }] } } },
      DEMOY: { symbol: 'DEMOY', exit_date: exitDay, exit_price: 137.19, status: 'RE_ENTER_IF', conditions: [{ key: 'earnings_clear', met: false, text: '' }],
        look_through: { groups: { industrials: 1.0 }, basis: 'stock' },
        stages: { verdict: 'Basing', exit_price: 137.19, last_close: 134.72, swing_low: 134.5, invalidation_level: 134.5, pct_vs_exit: -1.8, pct_vs_sma20: -12.2, trend: 'flat',
          stage1: { met: 2, of: 5, conditions: [{ key: 'follow_through', met: false, text: 'higher low + 2 green closes' }, { key: 'volume', met: false, text: 'volume ≥1×' },
            { key: 'group_no_new_low', met: true, text: '' }, { key: 'hedging_easing', met: false, text: 'hedging easing' }, { key: 'tier_ok', met: true, text: '' }] },
          stage2: { met: false, conditions: [{ key: 'above_exit', met: false, text: 'close above 137.19' }] } } },
      DEMOZ: { symbol: 'DEMOZ', exit_date: '2031-02-10', exit_price: 10, stages: { verdict: 'Confirmed', stage1: { met: 3, of: 5, conditions: [] }, stage2: { met: true, conditions: [] } } },
    },
    reentry_detail: {
      DEMOX: { exit_account_label: 'Demo IRA', held_elsewhere_labels: [], wash_sale: null },
      DEMOY: { exit_account_label: 'Demo IRA', held_elsewhere_labels: ['Demo Taxable'],
        wash_sale: { state: 'occurred', account_label: 'Demo Taxable', loss_sale_date: exitDay, rebuy_date: exitDay, rebuy_price: 144.78, deferred_loss_usd: 1049.6 } },
    },
    reentry_card: { recent_sessions: 5, max_rows: 5 },
  }
}

/** Route the market-risk endpoints on top of whatever page fixtures are already installed (later routes win). */
export async function marketRiskRoutes(page: Page, variant: 'red' | 'green' | 'not_evaluated' | 'shadow_red' | 'shadow_yellow' | 'carried_yellow' | 'yellow_live' | 'yellow_shadow' | 'yellow_stale' | 'yellow_empty' | 'yellow_nobook' | 'orange' | 'v005_yellow' | 'v005_orange' | 'v005_unreconciled' | 'v005_file', writes: string[] = []) {
  const v4: Record<string, unknown> = {
    yellow_live: marketRiskYellow('live'), yellow_shadow: marketRiskYellow('shadow'),
    yellow_stale: { ...marketRiskYellow('shadow'), state: 'stale', stale: true, age_hours: 3.2, as_of: iso(3.2 * 3_600_000) },
    yellow_empty: { ...marketRiskYellow('live'), contributors: [], book: null },
    yellow_nobook: { ...marketRiskYellow('live'), book: null },
    v005_yellow: marketRiskV005('YELLOW'), v005_orange: marketRiskV005('ORANGE'),
    v005_unreconciled: { ...marketRiskV005('YELLOW'), book_exposure: { ...marketRiskV005('YELLOW').book_exposure, reconciles: false } },
    orange: { ...marketRiskRed(), tier: 'ORANGE', score: 68, episode: { id: 'EP-FIXTURE-2', tier: 'ORANGE', opened_at: iso(3_600_000), repeats: 1, max_repeats: 12, acknowledged_at: null, status: 'OPEN' } },
  }
  // v005_file: a projection JSON from disk, for a LOCAL review render only (V005_PROJECTION_JSON; never committed)
  if (variant === 'v005_file') v4.v005_file = JSON.parse(readFileSync(String(process.env.V005_PROJECTION_JSON), 'utf-8'))
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
