// Existing performance response -> presentation only. No financial derivation or source reads.
// Runtime-free type imports keep this module directly loadable by node's TypeScript stripper.
import { accountDisplayLabel } from './accountLabel.ts'
import type { Envelope } from '../../api/client'
import type {
  PerformanceAccount, PerformanceAccountCoverage, PerformanceClock, PerformanceHouseholdPeriod, PerformanceMeasure,
  PerformanceNumber, PerformanceObservation, PerformancePageProps, PerformanceQualifier, PerformanceWindow,
} from './performanceView'

export const PERFORMANCE_PATH = '/api/v2/portfolio/performance'
const OWNER = 'Portfolio performance source team'
const WINDOWS: readonly [PerformanceWindow, string][] = [
  ['Latest session', '1D'], ['1W', '1W'], ['1M', '1M'], ['3M', '3M'],
  ['6M', '6M'], ['YTD', 'YTD'], ['1Y', '1Y'],
]
type Obj = Record<string, unknown>
const obj = (v: unknown): Obj => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Obj : {}
const text = (v: unknown): string | null => typeof v === 'string' && v.trim() !== '' ? v.trim() : null
const num = (v: unknown): number | null => typeof v === 'number' && Number.isFinite(v) ? v : null
const own = (o: Obj, k: string) => Object.prototype.hasOwnProperty.call(o, k)
const strings = (v: unknown): string[] => Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
const count = (v: unknown): number | null => { const n = num(v); return n !== null && Number.isInteger(n) && n >= 0 ? n : null }
const unavailable = (o: Obj): boolean => o.ok === false || o.available === false
  || ['UNKNOWN', 'UNAVAILABLE', 'ERROR', 'FAILED', 'NOT_BUILT'].includes(String(o.status).toUpperCase())

export interface PerformanceAdaptation { props: PerformancePageProps | null; reason: string | null }
export interface PerformanceRead extends PerformanceAdaptation {
  state: 'loading' | 'unavailable' | 'served' | 'last-available'
  notice: string | null
}

/** Only zoned instants can become a clock. Calendar dates/naive local stamps remain literal notes. */
function instant(v: unknown): string | null {
  const s = text(v)
  if (!s || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(s)) return null
  const n = Date.parse(s)
  const day = Date.parse(`${s.slice(0, 10)}T00:00:00Z`)
  if (!Number.isFinite(day) || new Date(day).toISOString().slice(0, 10) !== s.slice(0, 10) || Number(s.slice(11, 13)) > 23) return null
  return Number.isFinite(n) ? new Date(n).toISOString() : null
}
function clock(label: string, raw: Obj, nowMs: number): PerformanceClock {
  const asOf = instant(raw.as_of)
  // Age the SOURCE instant, never the HTTP receipt or a request-generated reference session.
  const delta = asOf !== null && Number.isFinite(nowMs) ? (nowMs - Date.parse(asOf)) / 1000 : null
  const age = delta !== null && delta >= 0 ? delta : null
  const status = String(raw.status).toUpperCase()
  // A clock's OK/KNOWN status certifies parsing, not freshness under a source policy.
  return { label: `${label} · source status: ${text(raw.status) ?? 'not served'}`, asOf, ageSeconds: age,
    freshness: raw.stale === true || raw.freshness === 'stale' || status === 'STALE' ? 'stale'
      : age !== null && raw.freshness === 'fresh' ? 'fresh' : 'unknown' }
}
function value(v: unknown, why: string | null): PerformanceNumber {
  const n = why === null ? num(v) : null
  return { value: n, unknownReason: n === null ? `${why ?? 'not served or invalid'} — owner: ${OWNER}` : null }
}
function coverage(cell: Obj): PerformanceObservation['coverage'] {
  const c = obj(cell.coverage)
  const included = count(c.included), total = count(c.total)
  return included !== null && total !== null && included <= total
    ? { included, total } : { included: null, total: null }
}
function refusedAccount(cell: Obj, account: Obj, day: boolean): string | null {
  if (unavailable(account) || unavailable(cell)) return 'source reports account measure unavailable'
  // No API evidence presently certifies account eligibility. Do not infer it from a broker/key.
  const eligibility = obj(account.eligibility)
  if (eligibility.status !== 'eligible' || text(eligibility.source) === null) return 'account eligibility unknown'
  if (/residual/i.test(String(cell.adjustment_method ?? '')) || /residual/i.test(String(cell.source ?? ''))
    || strings(cell.flags).some(f => /residual/i.test(f))) return 'household-residual account estimate withheld'
  if (text(cell.provenance_note) !== null || cell.linked_start_value != null || cell.economic_start_value != null
    || cell.rewrote_extreme_nav === true) return 'substituted account anchor; raw provenance unproven'
  if (!text(cell.source) || ['unknown', 'synthesized', 'sum_accounts'].includes(String(cell.source))) return 'raw account source not established'
  if (day && cell.snapshot_replaced === true) return 'replaced account day anchor; source evidence unproven'
  return null
}
function pinNote(cell: Obj, root: Obj): string {
  const pin = obj(root.ytd_pin)
  const created = text(pin.created_at)
  return `YTD pin date: ${text(cell.ytd_pin_date) ?? text(pin.pin_date) ?? 'unknown'}; snapshot: ${text(cell.ytd_pin_snapshot) ?? text(pin.end_snapshot) ?? 'unknown'}; source: ${text(pin.source) ?? 'unknown'}; created: ${created ?? 'unknown'}${created && instant(created) === null ? ' (zone unknown; not a UTC observation)' : ''}; version: ${text(pin.pin_version) ?? 'unknown'}.`
}
function observation(cell: Obj, root: Obj, period: string, nowMs: number, account: Obj | null): PerformanceObservation {
  const day = period === '1D', today = obj(root.today_pnl)
  const clocks: PerformanceClock[] = []
  if (day) {
    clocks.push(clock('Stored day-change observation', obj(today.observation_clock), nowMs))
    const provenance = obj(root.clock_provenance)
    for (const [key, label] of [['quote', 'Holdings marks (not attributed session)'], ['valuation', 'Holdings batch build (not market observation)']]) {
      const c = obj(provenance[key])
      const fallback = key === 'quote' ? today.mark_batch_at : today.batch_built_at
      if (Object.keys(c).length || fallback != null) clocks.push(clock(label, Object.keys(c).length ? c : { as_of: fallback }, nowMs))
    }
  } else {
    clocks.push(clock('Period observation (not the request time)', obj(cell.observation_clock), nowMs))
  }
  if (period === 'YTD') clocks.push(clock('YTD pin creation (not market observation)', { as_of: obj(root.ytd_pin).created_at }, nowMs))
  const flags = strings(cell.flags)
  const qualifiers: PerformanceQualifier[] = []
  if (day || cell.estimated === true || /estimat|repriced|funding|transfer/i.test(String(cell.quality ?? '') + String(cell.source ?? ''))) qualifiers.push('estimated')
  if (cell.partial_history === true || flags.length || cell.complete === false || account !== null && !Object.keys(obj(account.eligibility)).length) qualifiers.push('partial')
  if (cell.stale === true || String(cell.status).toUpperCase() === 'STALE' || clocks.some(c => c.freshness === 'stale')) qualifiers.push('stale')
  let why = unavailable(root) ? 'source reports performance status unavailable' : unavailable(cell) ? 'source reports measure unavailable' : null
  if (account !== null) why = refusedAccount(cell, account, day) ?? why
  else if (!day && cell.source === 'sum_accounts' && !own(cell, 'nav_change')) why = 'raw household NAV not served separately from account display sum'
  const amount = !day && account === null && own(cell, 'nav_change') ? cell.nav_change : cell.change
  const percent = !day && account === null && own(cell, 'nav_change_pct') ? cell.nav_change_pct : cell.change_pct
  // No free-text account adjustment/flow explanation: these fields may describe allocated residuals.
  const notes = [
    `Source quality: ${text(cell.quality) ?? 'unknown'}; flags: ${flags.join(', ') || 'none served'}.`,
    `Snapshot replaced: ${typeof cell.snapshot_replaced === 'boolean' ? cell.snapshot_replaced : 'unknown'}.`,
    `Start value (source anchor): ${num(cell.start_value) ?? 'unknown'}; end value: ${num(cell.end_value) ?? 'unknown'}.`,
    day ? `Marks observed calendar date (not session attribution): ${text(today.mark_session_date) ?? 'unknown'}; latest reference session (not attribution): ${text(obj(root.market_session).latest_open_session) ?? 'unknown'}.` : '',
    period === 'YTD' ? pinNote(cell, root) : '',
  ].filter(Boolean)
  const observedSession = day ? text(cell.attributed_session) : null
  return { method: day ? 'holdings-price-move' : 'raw-nav', amount: value(amount, why), percent: value(percent, why),
    qualifiers: [...new Set(qualifiers)], owner: OWNER, source: text(cell.source) ?? 'not served', clocks,
    coverage: coverage(cell), startAt: text(cell.start_date), endAt: text(cell.end_date),
    attributedSession: observedSession, note: notes.join(' ') }
}

/** Account selection is optional for future integration. Never re-label the unchanged household aggregate. */
export function adaptPerformance(body: unknown, nowMs: number, accountKey: string | null = null, labels: ReadonlyMap<string, string> = new Map()): PerformanceAdaptation {
  try {
    let root = obj(body)
    const outerUnavailable = unavailable(root)
    if (own(root, 'data')) {
      if (root.data === null || typeof root.data !== 'object' || Array.isArray(root.data)) return { props: null, reason: `Unknown — missing performance body — owner: ${OWNER}` }
      root = obj(root.data)
    }
    if (outerUnavailable) root = { ...root, status: 'UNKNOWN' }
    const sourceUnavailable = unavailable(root)
    if (!own(root, 'accounts') || root.accounts === null || typeof root.accounts !== 'object' || Array.isArray(root.accounts)) {
      return { props: null, reason: `Unknown — account membership not served — owner: ${OWNER}` }
    }
    const rawAccounts = obj(root.accounts)
    const keys = Object.keys(rawAccounts)
    if (sourceUnavailable && keys.length === 0) return { props: null, reason: `Unknown — nested performance status unavailable — owner: ${OWNER}` }
    if (accountKey !== null && !own(rawAccounts, accountKey)) return { props: null, reason: `Unknown — no matching account rows; household fallback withheld — owner: ${OWNER}` }
    const accounts: PerformanceAccount[] = (accountKey === null ? keys : [accountKey]).map(key => {
      const raw = obj(rawAccounts[key]), periods = obj(raw.periods)
      const eligibility = obj(raw.eligibility)
      const eligible = eligibility.status === 'eligible' && text(eligibility.source) !== null
      const label = accountDisplayLabel(key, labels.get(key) ?? null, text(raw.account_label) ?? text(raw.display_label))
      return { key, sourceOrdinal: keys.indexOf(key) + 1, availablePeriods: WINDOWS.filter(([, period]) => own(periods, period)).map(([label]) => label), label: label === key ? null : label,
        scopeNote: eligible ? 'Source-declared eligible account.'
          : 'Account eligibility unknown; no real-account scope inferred.',
        periods: Object.fromEntries(WINDOWS.map(([label, period]) => [label, observation(obj(periods[period]), root, period, nowMs, raw)])) }
    })
    const household: PerformancePageProps['household'] = {}
    if (accountKey === null) for (const [label, period] of WINDOWS) {
      const cell = obj(obj(root.periods)[period])
      const row: PerformanceHouseholdPeriod = { observation: observation(cell, root, period, nowMs, null), estimate: null }
      if (period !== '1D' && (own(cell, 'display_change') || own(cell, 'display_change_pct'))) {
        row.estimate = { ...row.observation!, method: 'household-estimate',
          amount: value(cell.display_change, sourceUnavailable || unavailable(cell) ? 'source reports estimate unavailable' : null),
          percent: value(cell.display_change_pct, sourceUnavailable || unavailable(cell) ? 'source reports estimate unavailable' : null),
          qualifiers: [...new Set<PerformanceQualifier>([...row.observation!.qualifiers, 'estimated'])],
          methodNote: `Source display_label (unverified terminology): ${text(cell.display_label) ?? 'not served'}; nav_is_not_market_only: ${typeof cell.nav_is_not_market_only === 'boolean' ? cell.nav_is_not_market_only : 'unknown'}; quality: ${text(cell.quality) ?? 'unknown'}; flags: ${strings(cell.flags).join(', ') || 'none served'}. Household residual approximation; external flows are not reconciled. This is not a verified investment return.` }
      }
      household[label] = row
    }
    // Scrub dynamic account keys even from producer text. Never synthesize broker/display labels.
    const availablePeriods = WINDOWS.filter(([label, period]) => own(obj(root.periods), period)
      || accounts.some(a => a.availablePeriods?.includes(label))).map(([label]) => label)
    // E: a holding account with no performance row is a missing result, not an omission to stay silent about.
    const served = obj(obj(root.today_pnl).stored_row_evidence).source_values
    const held = Array.isArray(served)
      ? [...new Set(served.map(r => text(obj(r).account_id)).filter((k): k is string => k !== null))] : null
    const accountCoverage: PerformanceAccountCoverage | null = accountKey !== null ? null : {
      holdingAccounts: held === null ? null : held.length, withResults: keys.length,
      missing: (held ?? []).filter(k => !own(rawAccounts, k)).map(k => {
        const label = accountDisplayLabel(k, labels.get(k) ?? null, null)
        return label === k ? 'Unlabelled account' : label
      }) }
    const props: PerformancePageProps = { accounts, household, gapOwner: OWNER, availablePeriods, accountCoverage }
    const idKeys = [...keys, ...(held ?? [])]
    const scrub = (s: string) => idKeys.reduce((out, key) => key ? out.split(key).join('account identifier withheld') : out, s)
    for (const account of props.accounts) {
      account.label = account.label === account.key ? null : account.label === null ? null : scrub(account.label)
      account.scopeNote = scrub(account.scopeNote)
      for (const m of Object.values(account.periods)) if (m) scrubMeasure(m, scrub)
    }
    if (accountCoverage) accountCoverage.missing = accountCoverage.missing.map(scrub)
    for (const row of Object.values(household)) { if (row?.observation) scrubMeasure(row.observation, scrub); if (row?.estimate) scrubMeasure(row.estimate, scrub) }
    return { props, reason: sourceUnavailable ? `Unknown — source reports performance status ${text(root.status) ?? 'unavailable'}; values withheld, source clocks retained — owner: ${OWNER}` : null }
  } catch {
    return { props: null, reason: `Unknown — malformed performance payload — owner: ${OWNER}` }
  }
}
function scrubMeasure(m: PerformanceMeasure, scrub: (s: string) => string) {
  m.source = scrub(m.source); m.note = m.note === null ? null : scrub(m.note)
  m.attributedSession = m.attributedSession === null ? null : scrub(m.attributedSession)
  if (m.method === 'household-estimate') m.methodNote = scrub(m.methodNote)
}

/** HTTP cache age is described separately; it never replaces or renews a financial source clock. */
export function performanceRead(env: Envelope<unknown> | null, nowMs: number, readError: string | null = null, labels: ReadonlyMap<string, string> = new Map()): PerformanceRead {
  if (env === null) return { props: null, reason: readError, state: readError ? 'unavailable' : 'loading', notice: null }
  if (!env.ok || readError !== null) {
    const cached = env.lastGood ?? (readError !== null ? env.data : null)
    const old = adaptPerformance(cached, nowMs, null, labels)
    const why = readError ?? env.error ?? `HTTP ${env.status}`
    if (old.props === null) return { props: null, reason: `Performance read failed: ${why}. ${old.reason}`, state: 'unavailable', notice: null }
    const notice = `Current read failed: ${why}. Last available response; cache receipt age: ${num(env.lastGoodAgeSeconds) ?? 'unknown'} seconds. Source clocks/ages below remain separate; this is not a validated last-success receipt.${old.reason ? ` ${old.reason}` : ''}`
    for (const account of old.props.accounts) for (const m of Object.values(account.periods)) if (m) m.qualifiers = [...new Set<PerformanceQualifier>([...m.qualifiers, 'stale'])]
    for (const row of Object.values(old.props.household)) for (const m of [row?.observation, row?.estimate]) if (m) m.qualifiers = [...new Set<PerformanceQualifier>([...m.qualifiers, 'stale'])]
    return { ...old, state: 'last-available', notice }
  }
  const adapted = adaptPerformance(env.data, nowMs, null, labels)
  return { ...adapted, state: adapted.props === null || adapted.reason !== null ? 'unavailable' : 'served',
    notice: adapted.props === null ? null : adapted.reason }
}

export function selectPerformance(props: PerformancePageProps, account: string | null, period: string | null): {
  props: PerformancePageProps; notice: string | null
} {
  const selectedAccounts = account === null || account === 'ALL' ? props.accounts : props.accounts.filter(a => a.key === account)
  const scoped = account !== null && account !== 'ALL'
  const availablePeriods = scoped ? WINDOWS.map(([label]) => label).filter(label => selectedAccounts.some(a => a.availablePeriods?.includes(label))) : props.availablePeriods ?? []
  const requested = WINDOWS.find(([, code]) => code === period)?.[0]
  const selectedPeriod = requested && availablePeriods.includes(requested) ? requested
    : availablePeriods.includes('YTD') ? 'YTD' : availablePeriods[0] ?? null
  const notice = scoped && !selectedAccounts.length ? 'Selected account is not served. Choose a source account; household fallback withheld.'
    : period !== null && (!requested || !availablePeriods.includes(requested)) ? 'Requested period is not served for this scope. Showing the selected available period.'
      : selectedPeriod === null ? 'No periods served for this scope.' : null
  return { props: { ...props, accounts: selectedAccounts, household: scoped ? {} : props.household,
    availablePeriods, selectedPeriod, showHousehold: !scoped }, notice }
}
