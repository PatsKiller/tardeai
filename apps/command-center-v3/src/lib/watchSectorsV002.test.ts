/** OBS-W6-a unit tests — the Sectors tab reads the momentum projection, and the two clocks stay apart. */
import assert from 'node:assert/strict'
import {
  INDUSTRIES_LINK_NOTE, SECTORS_MONITOR_API, SECTORS_TWO_CLOCKS,
  bookText, eligibilityText, leadersText, momentumText, quoteText, rsText, sectorClock, sectorLedger, sectorLine,
  sectorSignals, setupsText,
} from './watchSectorsV002.ts'
import { closeInstantMs, gradeSectors } from './watchSetupsV002.ts'

const NOW = Date.parse('2026-11-14T22:30:00Z') // 5:30 PM ET on Friday 2026-11-14
let n = 0
const t = (name: string, fn: () => void) => { fn(); n++; console.log(`PASS ${name}`) }

/** Shape measured by cc-deepseek-9 from the live read at 2026-11-14T17:15Z (sectors/monitor, 11 rows). */
const monitor = () => ({
  as_of: '2026-11-14T17:15:02Z',
  age_hours: 0.02,
  stale: false,
  stale_after_hours: 72,
  source: { table: 'market_quotes' },
  feeds: {
    market_quotes: { as_of: '2026-11-14T17:15:02Z', age_hours: 0.02, stale: false, stale_after_hours: 72 },
    // REVIEW-OBS-W6 F1: the LIVE shape of a daily-close stamp — the producer renders the session date as UTC midnight,
    // not as the 21:00Z close. A fixture that only ever carries the friendly close cannot see the age contradiction.
    sector_rs_daily: { as_of: '2026-11-13T00:00:00+00:00', age_hours: 25.5, stale: false, stale_after_hours: 96, source: { table: 'ticker_prices' } },
    sector_prices: { as_of: '2026-11-13T00:00:00+00:00', age_hours: 25.5, stale: false, stale_after_hours: 96 },
  },
  posture_basis: '20d_60d_vs_spy',
  rs_as_of: '2026-11-13',
  gap: null,
  spy_change_pct: 0.31,
  sectors: [
    {
      sector: 'Technology', etf: 'XLK', etf_change_pct: 0.42, quote_as_of: '2026-11-13T21:45:00Z', spy_change_pct: 0.31,
      rel_strength: 0.11, momentum: 'lagging', constituent_count: 60, setup_count: 12, candidate_gap: null,
      // REVIEW-OBS-W6 F2: the producer states a directive as an OBJECT (measured: 11/11 watched rows).
      is_watched: true, directive: { id: 1430, label: 'sector Semiconductor Supply Chain' },
      rs5: 1.26, rs20: -5.52, rs60: -5.18, as_of: '2026-11-13',
      rs_5d_pct: 1.26, rs_20d_pct: -5.52, rs_60d_pct: -5.18, rs_series: [], rs_n: null, rs_trend: 'lagging',
      book_weight_pct: 13.6, book_dollars: 39261, leaders: [{ symbol: 'ADSK', rs20: 11.95 }, { symbol: 'ACN', rs20: 10.53 }],
      leaders_basis: 'screened names · 20 sessions vs SPY', leaders_gap: null,
      book_flag: 'overweight_lagging', stale: false, source_age_days: 1.0, stale_sla_days: 4,
      quarantine_reason: null, recommendation_eligible: true,
      candidates: [],
    },
    {
      sector: 'Materials', etf: 'XLB', etf_change_pct: null, quote_as_of: '2026-11-14T17:15:00Z', spy_change_pct: 0.31,
      rel_strength: null, momentum: 'neutral', constituent_count: 25, setup_count: null, candidate_gap: 'Screened names unavailable',
      is_watched: false, directive: undefined, rs5: null, rs20: null, rs60: null, as_of: '2026-11-13',
      book_weight_pct: null, book_dollars: null, leaders: [], leaders_basis: 'screened names · 20 sessions vs SPY',
      leaders_gap: 'Screened names unavailable', book_flag: null, stale: true, source_age_days: 5.2, stale_sla_days: 4,
      quarantine_reason: 'source_older_than_sla', recommendation_eligible: false,
      freshness_gap: 'Sector prices are older than the freshness limit', candidates: [],
    },
  ],
  data_quality: { sectors_total: 2, sectors_stale: 1, stale_sla_days: 4, ledger: { coverage_n: 1, coverage_total: 2, quality: { level: 'partial_stale' } } },
  legend: 'setups/N: setups = score-ranked screened names after the canonical CIO avoid filter',
})

t('the endpoint is the momentum projection, not the taxonomy count read', () => {
  assert.equal(SECTORS_MONITOR_API, '/api/v2/sectors/monitor')
  assert.match(SECTORS_MONITOR_API, /sectors\/monitor/)
  assert.match(SECTORS_TWO_CLOCKS, /quote clock|market-quote clock/)
  assert.match(SECTORS_TWO_CLOCKS, /rs_as_of/)
  assert.match(INDUSTRIES_LINK_NOTE, /does not accept a sector in its address/)
})

t('rows carry the momentum projection fields', () => {
  const [xlk, xlb] = sectorSignals(monitor())
  assert.equal(xlk.sector, 'Technology')
  assert.equal(xlk.etf, 'XLK')
  assert.equal(xlk.momentum, 'lagging')
  assert.equal(xlk.momentumAsOf, '2026-11-13')
  assert.equal(xlk.rs5, 1.26)
  assert.equal(xlk.rs20, -5.52)
  assert.equal(xlk.changePct, 0.42)
  assert.equal(xlk.quoteAsOf, '2026-11-13T21:45:00Z')
  assert.equal(xlk.setups, 12)
  assert.equal(xlk.leaders.length, 2)
  assert.equal(xlk.bookWeightPct, 13.6)
  assert.equal(xlk.eligible, true)
  // REVIEW-OBS-W6 F2: the object the producer sends keeps its label; a bare string is still accepted (shape drift).
  assert.equal(xlk.watched, true)
  assert.equal(xlk.directive, 'sector Semiconductor Supply Chain')
  const stringShape: any = monitor()
  stringShape.sectors[0].directive = 'trim tech'
  assert.equal(sectorSignals(stringShape)[0].directive, 'trim tech')
  const unlabelled: any = monitor()
  unlabelled.sectors[0].directive = { id: 7 }
  assert.equal(sectorSignals(unlabelled)[0].directive, null, 'an unlabelled object is not stated, never "[object Object]"')
  assert.equal(xlb.setups, null)
  assert.equal(xlb.setupsGap, 'Screened names unavailable')
  assert.equal(xlb.leaders.length, 0)
  assert.equal(xlb.stale, true)
  assert.equal(xlb.eligible, false)
})

t('a missing momentum is not stated, never neutral', () => {
  const b: any = monitor()
  delete b.sectors[0].momentum
  const [r] = sectorSignals(b)
  assert.equal(r.momentum, null)
  assert.equal(momentumText(r), 'momentum not stated in this read')
  assert.equal(sectorSignals({}).length, 0)
})

t('momentum names its own date, not the envelope quote clock', () => {
  const [r] = sectorSignals(monitor())
  const line = momentumText(r)
  // A date-only stamp carries no clock: rendering it as an instant would invent "7:00 PM ET the day before".
  assert.equal(line, 'lagging · as of Nov 13, 2026 (daily close, no clock stated)')
  assert.doesNotMatch(line, /\d+:\d\d/)
  assert.equal(momentumText({ momentum: 'leading', momentumAsOf: null }), 'leading · momentum time not stated')
  assert.equal(momentumText({ momentum: 'leading', momentumAsOf: '2026-11-13T21:00:00Z' }), 'leading · as of Nov 13, 4:00 PM ET')
})

t('relative strength omits what is not stated and never prints a zero', () => {
  const [xlk, xlb] = sectorSignals(monitor())
  assert.equal(rsText(xlk), 'RS vs SPY 5d +1.26 / 20d -5.52 / 60d -5.18')
  assert.equal(rsText(xlb), 'relative strength not stated')
})

t('a quote carries its own time and age; a missing time says the age is unknown', () => {
  const [xlk] = sectorSignals(monitor())
  const line = quoteText(xlk, NOW)
  assert.match(line, /^ETF \+0\.42 % at Nov 13, 4:45 PM ET \(25 h old\)$/)
  assert.equal(quoteText({ changePct: 0.5, quoteAsOf: null, etf: 'X' }, NOW), 'ETF +0.5 % · quote time not stated (age unknown)')
  assert.equal(quoteText({ changePct: null, quoteAsOf: null, etf: 'X' }, NOW), 'ETF move not stated')
})

t('setups: a stated count, a named gap, and never a silent 0', () => {
  const [xlk, xlb] = sectorSignals(monitor())
  assert.equal(setupsText(xlk), '12 screened setups')
  assert.equal(setupsText(xlb), 'setups unavailable — Screened names unavailable')
  assert.equal(setupsText({ setups: null, setupsGap: null }), 'setups not stated in this read')
  assert.equal(setupsText({ setups: 0, setupsGap: null }), '0 screened setups')
  assert.equal(setupsText({ setups: 1, setupsGap: null }), '1 screened setup')
})

t('leaders keep their basis and name an unmeasured gap', () => {
  const [xlk, xlb] = sectorSignals(monitor())
  assert.equal(leadersText(xlk), 'leaders ADSK +11.95, ACN +10.53 (screened names · 20 sessions vs SPY)')
  assert.equal(leadersText(xlb), 'leaders not measured — Screened names unavailable')
  assert.equal(leadersText({ leaders: [], leadersBasis: null, leadersGap: null }), 'leaders not stated in this read')
  assert.equal(leadersText({ leaders: [{ symbol: 'MAN', rs20: null }], leadersBasis: null, leadersGap: null }), 'leaders MAN')
})

t('book weight and the overweight-lagging flag', () => {
  const [xlk, xlb] = sectorSignals(monitor())
  assert.equal(bookText(xlk), 'book 13.6 % · overweight a lagging sector')
  assert.equal(bookText(xlb), 'book weight not stated')
})

t('eligibility is the producer flag, with its age and reason', () => {
  const [xlk, xlb] = sectorSignals(monitor())
  assert.equal(eligibilityText(xlk), 'eligible to originate a recommendation')
  assert.equal(eligibilityText(xlb),
    'not eligible to originate a recommendation (5.2 d old) — Sector prices are older than the freshness limit')
  assert.equal(eligibilityText({ eligible: null, stale: false, sourceAgeDays: null, freshnessGap: null }), 'eligibility not stated in this read')
})

t('the two clocks are separate and neither borrows the other', () => {
  const c = sectorClock(monitor(), NOW)
  assert.equal(c.momentumAsOf, '2026-11-13')
  assert.equal(c.quotesAsOf, '2026-11-14T17:15:02Z')
  assert.equal(c.quotes.ageS, Math.round((NOW - Date.parse('2026-11-14T17:15:02Z')) / 1000))
  // REVIEW-OBS-W6 F1: a UTC-midnight daily-close stamp is that session's 16:00 ET close (21:00Z on 2026-11-13, EST) —
  // the SAME instant the chip grades — so the printed age and the chip age cannot disagree on one screen.
  assert.equal(c.rs.ageS, Math.round((NOW - Date.parse('2026-11-13T21:00:00Z')) / 1000))
  assert.equal(c.rs.ageS, gradeSectors(monitor(), NOW).ageS)
  assert.ok(Math.abs(c.rs.ageS! - Math.round(42.66 * 3600)) > 3600, 'a UTC-midnight stamp must not be read as a market instant 21 h older than the close')
  assert.equal(closeInstantMs('2026-11-13'), Date.parse('2026-11-13T21:00:00Z'))
  assert.equal(c.rs.stale, false)
  assert.equal(c.rs.staleAfterH, 96)
  assert.equal(c.postureBasis, '20d_60d_vs_spy')
  // A date-only feed stamp is the same close.
  const d: any = monitor()
  d.feeds.sector_rs_daily.as_of = '2026-11-13'
  assert.equal(sectorClock(d, NOW).rs.ageS, Math.round((NOW - Date.parse('2026-11-13T21:00:00Z')) / 1000))
  // An unparseable feed stamp falls back to the stated age_hours, never to 0.
  const b: any = monitor()
  b.feeds.sector_rs_daily.as_of = 'not a time'
  assert.equal(sectorClock(b, NOW).rs.ageS, Math.round(25.5 * 3600))
})

t('the ledger is the payload own, and a row-count disagreement is named', () => {
  const l = sectorLedger(monitor())
  assert.equal(l.total, 2)
  assert.equal(l.staleTotal, 1)
  assert.equal(l.staleSlaDays, 4)
  assert.equal(l.coverageN, 1)
  assert.equal(l.coverageTotal, 2)
  assert.equal(l.quality, 'partial_stale')
  assert.equal(l.rowsInRead, 2)
  assert.equal(l.rowDisagreement, null)
  assert.match(l.legend!, /canonical CIO avoid filter/)
  // The country guard: 13 rows for 11 sectors must not read as 11 sectors.
  const b: any = monitor()
  b.data_quality.sectors_total = 11
  assert.equal(sectorLedger(b).rowDisagreement, 'the ledger counts 11 sectors, this read carries 2 rows')
})

t('a broken ledger block says so instead of reporting zero coverage', () => {
  const b: any = monitor()
  b.data_quality = { error: 'quality block unavailable: boom' }
  const l = sectorLedger(b)
  assert.equal(l.total, null)
  assert.equal(l.coverageN, null)
  assert.equal(l.error, 'quality block unavailable: boom')
  assert.equal(l.rowDisagreement, null)
})

t('one line carries the facts a reader needs without opening anything', () => {
  const [xlk] = sectorSignals(monitor())
  const line = sectorLine(xlk, NOW)
  assert.match(line, /^Technology \(XLK\) · lagging · as of Nov 13, 2026 \(daily close, no clock stated\) · RS vs SPY 5d \+1\.26 \/ 20d -5\.52 \/ 60d -5\.18 · ETF \+0\.42 % at Nov 13, 4:45 PM ET \(25 h old\) · 12 screened setups · book 13\.6 % · overweight a lagging sector · eligible to originate a recommendation$/)
})

console.log(`${n} sector projection tests passed`)
