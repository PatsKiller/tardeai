import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { useReEntryExitEvidence } from '../../hooks/useReEntryExitEvidence'
import { BB } from '../../lib/holdingsTerminalTokens'
import {
  DISPOSITION_KEY,
  EVENT_KEY,
  MANDATE_KEY,
  RESISTANCE_KEY,
  REENTRY_FLAGS,
  classificationLabel,
  classificationState,
  finite,
  normalizedDisposition,
  normalizedEvent,
  normalizedMandate,
  prefMap,
  prefValue,
  rowPrice,
  rowShares,
  text,
  type ExitEvidenceField,
  type ExitEvidenceRow,
  type ReEntryDisposition,
  type ReEntryEvent,
  type ReEntryMandate,
} from '../../lib/reentrySharedContext'
import {
  buildReEntryScorecard,
  extractLevelsFromContext,
  filterByLane,
  type ReEntryLane,
  type ScoreGate,
  type ScorecardResult,
} from '../../lib/reentryDecisionScorecard'
import { HelpTip } from './ReEntryHelpGuide'
import ReEntryCommandHeader, { type ReEntryLaneCounts } from './ReEntryCommandHeader'
import ReEntryMiniChart from './ReEntryMiniChart'
import ReEntryAlertArmModal from './ReEntryAlertArmModal'

const COMPOSITE_ALERT_KEY = 'portfolio.reentry.composite-alerts.v1'

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 5 }
const field: CSSProperties = { width: '100%', boxSizing: 'border-box', fontSize: 11.5, padding: '7px 9px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }
const button = (active = false): CSSProperties => ({ fontSize: 10.5, fontWeight: 850, padding: '5px 9px', borderRadius: 4, cursor: 'pointer', border: `1px solid ${active ? BB.blue : 'var(--border)'}`, background: active ? BB.blueDim : 'var(--bg2)', color: active ? BB.blue : 'var(--text2)' })

type Summary = { symbol: string; rows: ExitEvidenceRow[]; latest: ExitEvidenceRow; shares: number | null; avgExit: number | null; proceeds: number; eventGapCount: number; derivedCount: number }
type IntelState = 'READY TO REVIEW' | 'NEAR ENTRY' | 'WAIT' | 'CURRENTLY HELD' | 'STALE' | 'MISSING PLAN' | 'MISSING MARKET'
type Intel = { price: number | null; asOf: string; rsi: number | null; trend: string; entryLow: number | null; entryHigh: number | null; stop: number | null; target: number | null; distancePct: number | null; state: IntelState; action: string; reason: string }
type Resistance = { state: string; level: number | null; distancePct: number | null; holdDays: number | null; source: string; reason: string }
type IntelWithScore = Intel & {
  score: ScorecardResult
  support: number | null
  ma20: number | null
  ma50: number | null
  ma200: number | null
  macd: string
  pe: number | null
  forwardPe: number | null
  riskReward: number | null
  rsiBand: ScorecardResult['rsiBand']
  vsExitPct: number | null
  highlights: string[]
}

function unwrap(value: any): any { let result = value; for (let i = 0; i < 4 && result?.data && typeof result.data === 'object'; i += 1) result = result.data; return result ?? {} }
function path(value: any, key: string): any { return key.split('.').reduce((result: any, part) => result?.[part], value) }
function numberFrom(objects: any[], paths: string[]): number | null { for (const object of objects) for (const key of paths) { const value = finite(path(object, key)); if (value !== null) return value } return null }
function money(value: number | null): string { return value === null ? '—' : `$${value.toFixed(2)}` }
function age(value: string): string { if (!value) return 'as-of unavailable'; const time = new Date(value).getTime(); if (!Number.isFinite(time)) return value.slice(0, 16); const hours = Math.max(0, Math.round((Date.now() - time) / 36e5)); return hours < 1 ? 'current' : hours < 48 ? `${hours}h old` : `${Math.round(hours / 24)}d old` }
function classify(symbols: string[]) { window.dispatchEvent(new CustomEvent('reentry:classify-symbol', { detail: { symbols } })) }

function deriveIntel(
  watch: any,
  card: any,
  held: boolean,
  regimeLabel: string,
  resistanceLevel: number | null,
  resistanceDistancePct: number | null,
  resistanceSide: string,
  narrative: {
    avgExit: number | null
    exitDate: string | null
    mandate: string
    flags: string[]
    classified: string
    eventGaps: number
    analystRec: string
    analystTarget: number | null
    analystCount: number | null
  },
): IntelWithScore {
  const levels = extractLevelsFromContext(watch, card)
  const score = buildReEntryScorecard({
    price: levels.price ?? null,
    asOf: levels.asOf ?? '',
    rsi: levels.rsi ?? null,
    trend: levels.trend ?? 'UNAVAILABLE',
    entryLow: levels.entryLow ?? null,
    entryHigh: levels.entryHigh ?? null,
    stop: levels.stop ?? null,
    target: levels.target ?? null,
    support: levels.support ?? null,
    resistance: resistanceLevel ?? levels.resistance ?? null,
    resistanceDistancePct,
    resistanceSide,
    ma20: levels.ma20 ?? null,
    ma50: levels.ma50 ?? null,
    ma200: levels.ma200 ?? null,
    macdHistogram: levels.macdHistogram ?? null,
    macdSlope: levels.macdSlope ?? null,
    relativeStrength: levels.relativeStrength ?? null,
    pe: levels.pe ?? null,
    forwardPe: levels.forwardPe ?? null,
    held,
    regimeLabel,
    avgExit: narrative.avgExit,
    exitDate: narrative.exitDate,
    mandate: narrative.mandate,
    flags: narrative.flags,
    classified: narrative.classified,
    eventGaps: narrative.eventGaps,
    analystRec: narrative.analystRec,
    analystTarget: narrative.analystTarget,
    analystCount: narrative.analystCount,
  })
  const macd = levels.macdHistogram === null || levels.macdHistogram === undefined
    ? 'UNAVAILABLE'
    : `${levels.macdHistogram >= 0 ? 'pos' : 'neg'}${levels.macdSlope == null ? '' : levels.macdSlope > 0 ? '↑' : levels.macdSlope < 0 ? '↓' : ''}`
  return {
    price: levels.price ?? null,
    asOf: levels.asOf ?? '',
    rsi: levels.rsi ?? null,
    trend: levels.trend ?? 'UNAVAILABLE',
    entryLow: levels.entryLow ?? null,
    entryHigh: levels.entryHigh ?? null,
    stop: levels.stop ?? null,
    target: levels.target ?? null,
    distancePct: score.distancePct,
    state: score.state,
    action: score.action,
    reason: score.reason,
    score,
    support: levels.support ?? null,
    ma20: levels.ma20 ?? null,
    ma50: levels.ma50 ?? null,
    ma200: levels.ma200 ?? null,
    macd,
    pe: levels.pe ?? null,
    forwardPe: levels.forwardPe ?? null,
    riskReward: score.riskReward,
    rsiBand: score.rsiBand,
    vsExitPct: score.vsExitPct,
    highlights: score.highlights,
  }
}

function resistanceFor(cached: any, watch: any, card: any, price: number | null): Resistance {
  if (cached && String(cached.state || '').toUpperCase() !== 'UNAVAILABLE') {
    return {
      state: String(cached.state || 'UNAVAILABLE').toUpperCase(),
      level: finite(cached.resistance),
      distancePct: finite(cached.distance_pct),
      holdDays: finite(cached.hold_days),
      source: 'CLOSED-SESSION CACHE',
      reason: text(cached.reason, cached.method, 'Closed-session resistance evidence.'),
    }
  }
  const packet = watch?.decision_packet ?? card?.decision_packet ?? {}
  const trigger = text(packet?.horizons?.tactical?.trigger, packet?.horizons?.swing?.trigger, packet?.selected_family?.mechanics?.trigger, watch?.trigger)
  const match = trigger.match(/resistance\s+\$?([0-9]+(?:\.[0-9]+)?)/i)
  const level = finite(watch?.resistance, watch?.resistance_level, card?.resistance, packet?.selected_family?.mechanics?.resistance, match?.[1])
  if (level !== null && price !== null && level > 0) {
    const distancePct = ((price - level) / level) * 100
    return {
      state: Math.abs(distancePct) <= .5 ? 'TESTING' : distancePct > 0 ? 'ABOVE' : 'BELOW',
      level,
      distancePct,
      holdDays: null,
      source: 'WATCH FALLBACK',
      reason: trigger || 'Decision-packet resistance fallback.',
    }
  }
  return { state: 'UNAVAILABLE', level: null, distancePct: null, holdDays: null, source: 'MISSING', reason: 'No valid resistance cache row or parsable Watch trigger.' }
}

function stateTone(state: IntelState): string {
  if (state === 'READY TO REVIEW') return BB.green
  if (state === 'NEAR ENTRY') return BB.amber
  if (state === 'MISSING MARKET' || state === 'MISSING PLAN' || state === 'STALE') return BB.red
  if (state === 'CURRENTLY HELD') return BB.amber
  return BB.blue
}

function gateColor(state: ScoreGate['state']): string {
  if (state === 'PASS') return BB.green
  if (state === 'BLOCK') return BB.red
  if (state === 'WAIT') return BB.amber
  return BB.text3
}

function sourceFor(row: ExitEvidenceRow, fieldName: ExitEvidenceField): string {
  return row.field_sources?.[fieldName] || row.import_source || 'source unavailable'
}

function parseLane(raw: string | null | undefined): ReEntryLane | null {
  if (!raw) return null
  const u = raw.trim().toUpperCase()
  if (u === 'NOW' || u === 'READY') return 'NOW'
  if (u === 'NEAR') return 'NEAR'
  if (u === 'WATCH' || u === 'WAIT') return 'WATCH'
  if (u === 'ALL') return 'ALL'
  return null
}

export default function ReEntryCurrentIntelligence({
  lane: laneProp,
  onLaneChange,
  focusSymbol,
}: {
  lane?: ReEntryLane
  onLaneChange?: (lane: ReEntryLane) => void
  focusSymbol?: string
} = {}) {
  const navigate = useNavigate()
  const evidence = useReEntryExitEvidence(365)
  const cards = useApi<any>('/api/v2/symbol-cards', 300_000)
  const holdings = useApi<any>('/api/v2/portfolio/holdings', 120_000)
  const mandatesPref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`, 0)
  const eventsPref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EVENT_KEY)}`, 0)
  const dispositionsPref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(DISPOSITION_KEY)}`, 0)
  const alerts = useApi<any>('/api/v2/watch/alerts/list', 120_000)
  const regime = useApi<any>('/api/v2/risk-regime/latest', 300_000)
  const resistancePref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(RESISTANCE_KEY)}`, 120_000)
  const compositePref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(COMPOSITE_ALERT_KEY)}`, 120_000)
  const analyst = useApi<any>('/api/v2/pro-analyst/pills?map=1', 300_000)
  const [watchMap, setWatchMap] = useState<Record<string, any>>({})
  const [search, setSearch] = useState('')
  const [stateFilter, setStateFilter] = useState('ALL')
  const [classificationFilter, setClassificationFilter] = useState('ALL')
  // Default ACTIVE: the queue shows work to do. SUPPRESSED is the review lane for
  // decisions already made; ALL is the audit escape hatch.
  const [queueFilter, setQueueFilter] = useState<'ACTIVE' | 'SUPPRESSED' | 'ALL'>('ACTIVE')
  const [gapOnly, setGapOnly] = useState(false)
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [watchReload, setWatchReload] = useState(0)
  const [lane, setLane] = useState<ReEntryLane>(laneProp ?? 'NOW')
  const [armSymbol, setArmSymbol] = useState<string | null>(null)
  const [toast, setToast] = useState('')

  useEffect(() => { if (laneProp) setLane(laneProp) }, [laneProp])

  useEffect(() => {
    if (!focusSymbol) return
    const sym = focusSymbol.toUpperCase()
    setSearch(sym)
    setLane('ALL')
    setExpanded(value => ({ ...value, [sym]: true }))
  }, [focusSymbol])

  const setLaneBoth = (next: ReEntryLane) => {
    setLane(next)
    onLaneChange?.(next)
    // When picking a lane chip, clear competing state filter so lanes win
    if (next !== 'ALL') setStateFilter('ALL')
  }

  const openWatch = (symbol: string) => navigate(`/watch?symbol=${encodeURIComponent(symbol)}&review=1`)
  const openRotation = (symbol: string) => navigate(`/rotation?symbol=${encodeURIComponent(symbol)}`)

  const mandates: Record<string, ReEntryMandate> = prefMap(mandatesPref.data) as Record<string, ReEntryMandate>
  const events: Record<string, ReEntryEvent> = prefMap(eventsPref.data) as Record<string, ReEntryEvent>
  const dispositions: Record<string, ReEntryDisposition> = prefMap(dispositionsPref.data) as Record<string, ReEntryDisposition>
  const regimeLabel = text(unwrap(regime.data)?.regime_label, unwrap(regime.data)?.label, 'unknown').replace(/_/g, ' ').toUpperCase()

  const summaries = useMemo(() => {
    const groups = new Map<string, ExitEvidenceRow[]>()
    for (const row of evidence.rows) {
      const symbol = String(row.symbol || '').toUpperCase()
      if (symbol) groups.set(symbol, [...(groups.get(symbol) ?? []), row])
    }
    return [...groups.entries()].map(([symbol, rows]) => {
      const sorted = rows.slice().sort((a, b) => `${b.trade_date ?? ''}T${b.trade_time ?? ''}`.localeCompare(`${a.trade_date ?? ''}T${a.trade_time ?? ''}`))
      let shares = 0; let weighted = 0; let proceeds = 0; let known = false
      for (const row of sorted) {
        const quantity = rowShares(row)
        const price = rowPrice(row)
        const cash = finite(row.proceeds_usd)
        if (quantity !== null) {
          known = true
          shares += quantity
          if (price !== null) weighted += quantity * price
        }
        if (cash !== null) proceeds += Math.abs(cash)
      }
      return {
        symbol,
        rows: sorted,
        latest: sorted[0],
        shares: known ? shares : null,
        avgExit: shares > 0 && weighted > 0 ? weighted / shares : null,
        proceeds,
        eventGapCount: sorted.reduce((sum, row) => sum + (row.evidence_gaps?.length ?? 0), 0),
        derivedCount: sorted.reduce((sum, row) => sum + (row.derived_fields?.length ?? 0), 0),
      } satisfies Summary
    })
  }, [evidence.rows])

  const symbols = useMemo(() => summaries.map(summary => summary.symbol).slice(0, 300), [summaries])
  useEffect(() => {
    if (!symbols.length) return
    let dead = false
    let cursor = 0
    const controller = new AbortController()
    const output: Record<string, any> = {}
    const worker = async () => {
      while (!dead) {
        const index = cursor++
        if (index >= symbols.length) return
        const symbol = symbols[index]
        try {
          const response = await fetch(`/api/v2/watchlist/items?symbol=${encodeURIComponent(symbol)}`, { cache: 'no-store', signal: controller.signal })
          const payload = unwrap(await response.json())
          output[symbol] = (payload?.items ?? [])[0] ?? null
        } catch {
          output[symbol] = null
        }
      }
    }
    void Promise.all(Array.from({ length: Math.min(8, symbols.length) }, () => worker())).then(() => {
      if (!dead) setWatchMap(previous => ({ ...previous, ...output }))
    })
    return () => { dead = true; controller.abort() }
  }, [symbols.join('|'), watchReload])

  const cardMap: Record<string, any> = unwrap(cards.data)?.cards ?? {}
  const heldSet = new Set<string>(
    (unwrap(holdings.data)?.holdings ?? [])
      .filter((row: any) => Number(row.shares ?? row.quantity ?? 0) > 0)
      .map((row: any) => String(row.symbol || '').toUpperCase()),
  )
  const alertRows: any[] = unwrap(alerts.data)?.alerts ?? unwrap(alerts.data)?.items ?? []
  const resistanceMap: Record<string, any> = prefValue(resistancePref.data)?.symbols ?? {}
  const analystMap: Record<string, any> = unwrap(analyst.data)?.map ?? {}
  const compositeMap = prefValue(compositePref.data) as Record<string, { armed?: boolean }> | null
  const armedCount = compositeMap
    ? Object.values(compositeMap).filter(item => item && item.armed).length
    : 0

  const rows = useMemo(() => summaries.map(summary => {
    const mandate = normalizedMandate(mandates[summary.symbol])
    const watch = watchMap[summary.symbol]
    const card = cardMap[summary.symbol]
    const held = heldSet.has(summary.symbol)
    const classified = classificationState(mandate, summary.rows, events, dispositions)
    const flags = REENTRY_FLAGS.filter(flag => mandate.flags[flag])
    const analystRow = analystMap[summary.symbol] ?? null
    // Price first so resistance distance is accurate, then full scorecard with regime + resistance.
    const priceHint = extractLevelsFromContext(watch, card).price ?? null
    const resistance = resistanceFor(resistanceMap[summary.symbol], watch, card, priceHint)
    const intel = deriveIntel(
      watch,
      card,
      held,
      regimeLabel,
      resistance.level,
      resistance.distancePct,
      resistance.state,
      {
        avgExit: summary.avgExit,
        exitDate: summary.latest?.trade_date ?? null,
        mandate: mandate.mandate,
        flags,
        classified,
        eventGaps: summary.eventGapCount,
        analystRec: text(analystRow?.rec, analystRow?.recommendation, '').replace(/_/g, ' ').toUpperCase(),
        analystTarget: finite(analystRow?.target),
        analystCount: finite(analystRow?.n),
      },
    )
    const completeness = [
      summary.shares !== null,
      summary.avgExit !== null,
      Boolean(watch),
      intel.price !== null,
      intel.rsi !== null,
      intel.entryLow !== null,
      resistance.level !== null,
      Boolean(analystRow),
    ].filter(Boolean).length
    const alertCount = alertRows.filter(row =>
      String(row.symbol || '').toUpperCase() === summary.symbol
      && !['disabled', 'expired', 'resolved'].includes(String(row.status || '').toLowerCase()),
    ).length
    // Suppression is per exit EVENT, so a symbol only leaves the queue once every one
    // of its exits is suppressed. A symbol with one suppressed exit and one live exit
    // still has an open re-entry decision and must stay visible.
    const suppressedCount = summary.rows.filter(row =>
      normalizedDisposition(dispositions[row.event_key]).state === 'suppressed',
    ).length
    const suppressed = summary.rows.length > 0 && suppressedCount === summary.rows.length
    return {
      ...summary,
      mandate,
      watch,
      card,
      intel,
      resistance,
      classified,
      flags,
      completeness,
      alertCount,
      suppressedCount,
      suppressed,
      analyst: analystRow,
      score: intel.score,
    }
  }), [summaries, mandatesPref.data, eventsPref.data, dispositionsPref.data, watchMap, cards.data, holdings.data, resistancePref.data, analyst.data, alerts.data, regimeLabel])

  const laneCounts: ReEntryLaneCounts = useMemo(() => {
    const active = rows.filter(row => !row.suppressed)
    return {
      now: active.filter(row => row.score.lane === 'NOW').length,
      near: active.filter(row => row.score.lane === 'NEAR').length,
      watch: active.filter(row => row.score.lane === 'WATCH').length,
      all: active.length,
      armed: armedCount,
      sourcesOk: evidence.sources.filter(source => source.available).length,
      sourcesTotal: evidence.sources.length,
    }
  }, [rows, armedCount, evidence.sources])

  const shown = rows.filter(row => {
    if (search.trim() && !`${row.symbol} ${row.intel.state} ${row.intel.action} ${row.classified} ${row.mandate.mandate} ${row.flags.join(' ')} ${row.latest.import_source ?? ''} ${(row.latest.evidence_gaps ?? []).join(' ')}`.toUpperCase().includes(search.trim().toUpperCase())) return false
    // SUPPRESS FROM RE-ENTRY QUEUE means gone from the working queue — suppressed
    // symbols surface only under the SUPPRESSED filter.
    if (queueFilter === 'ACTIVE' && row.suppressed) return false
    if (queueFilter === 'SUPPRESSED' && !row.suppressed) return false
    if (stateFilter !== 'ALL' && row.intel.state !== stateFilter) return false
    if (classificationFilter !== 'ALL' && row.classified !== classificationFilter) return false
    if (gapOnly && row.completeness >= 8 && row.eventGapCount === 0) return false
    return true
  })
    .filter(row => filterByLane([{ score: row.score }], lane).length > 0)
    .sort((a, b) =>
      (a.mandate.priority === 'HIGH' ? -1 : 0) - (b.mandate.priority === 'HIGH' ? -1 : 0)
      || b.completeness - a.completeness
      || String(b.latest.trade_date || '').localeCompare(String(a.latest.trade_date || '')),
    )

  const suppressedTotal = rows.filter(row => row.suppressed).length
  const selectedSymbols = shown.filter(row => selected[row.symbol]).map(row => row.symbol)
  const counts = {
    symbols: rows.length,
    classified: rows.filter(row => row.classified === 'CLASSIFIED').length,
    ready: laneCounts.now,
    near: laneCounts.near,
    missing: rows.filter(row => row.completeness < 8 || row.eventGapCount > 0).length,
  }
  const refresh = () => {
    evidence.refetch()
    cards.refetch()
    holdings.refetch()
    alerts.refetch()
    regime.refetch()
    resistancePref.refetch()
    compositePref.refetch()
    analyst.refetch()
    mandatesPref.refetch()
    eventsPref.refetch()
    dispositionsPref.refetch()
    setWatchReload(value => value + 1)
  }
  const shareCoverage = evidence.sources.map(source => `${source.label} shares ${evidence.sourceFieldCoverage[source.key]?.quantity ?? 0}`).join(' · ')
  const refreshing = evidence.loading || evidence.refreshing
  const activeAlerts = alertRows.filter(row => !['disabled', 'expired', 'resolved'].includes(String(row.status || '').toLowerCase()) && (row.active === undefined || row.active))
  const reentryArmed = activeAlerts.filter(row => {
    const sym = String(row.symbol || '').toUpperCase()
    return sym && rows.some(r => r.symbol === sym)
  })
  const armRow = armSymbol ? rows.find(r => r.symbol === armSymbol) : null

  return (
    <div style={{ ...panel, padding: 10 }}>
      <ReEntryCommandHeader
        lane={lane}
        onLane={setLaneBoth}
        counts={laneCounts}
        regimeLabel={regimeLabel}
        onRefresh={refresh}
        refreshing={refreshing}
      />

      <div
        data-testid="reentry-alert-center"
        style={{ ...panel, marginTop: 8, padding: 8, background: 'var(--bg2)', fontSize: 11, color: BB.text2 }}
      >
        <b style={{ color: 'var(--text0)' }}>ALERT CENTER</b>
        {' · '}
        {reentryArmed.length} armed Watch alerts on exited symbols
        {' · '}
        {Object.values(compositeMap ?? {}).filter((item: any) => item?.armed).length} rotation six-gate monitors
        {' · '}
        <span style={{ color: BB.text3 }}>advisory only — arm zone/RSI from any row · six-gate arms in Rotation workspace</span>
        {reentryArmed.length > 0 && (
          <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {reentryArmed.slice(0, 12).map((row: any) => (
              <span
                key={String(row.id ?? `${row.symbol}-${row.condition_type}-${row.threshold}`)}
                style={{ fontSize: 10, padding: '2px 6px', borderRadius: 4, border: '1px solid var(--border)', color: BB.text2 }}
                title={row.note || ''}
              >
                {String(row.symbol || '').toUpperCase()} {String(row.condition_type || '').replace(/_/g, ' ')} {row.threshold ?? ''}
                {row.last_fired_at ? ` · fired ${String(row.last_fired_at).slice(0, 10)}` : ''}
              </span>
            ))}
            {reentryArmed.length > 12 && <span style={{ fontSize: 10, color: BB.text3 }}>+{reentryArmed.length - 12} more</span>}
          </div>
        )}
      </div>
      {toast && (
        <div style={{ marginTop: 8, padding: '6px 10px', borderRadius: 4, border: `1px solid ${BB.green}`, color: BB.green, fontSize: 11 }}>
          {toast}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 8 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 900 }}>
            CURRENT RE-ENTRY INTELLIGENCE{' '}
            <HelpTip text="Exit events are reconciled by broker ID and compatible symbol/date/account facts. Every displayed field retains its source; deterministic arithmetic is labeled as derived. Expand a row for the decision gate scorecard." />
          </div>
          <div style={{ fontSize: 10.5, color: BB.text3 }}>
            {evidence.rows.length} reconciled exit events · contract {evidence.contractVersion} · advisory only · never auto-buys
          </div>
        </div>
      </div>

      <div style={{ ...panel, marginTop: 8, padding: 8, background: 'var(--bg2)', fontSize: 10.5 }}>
        <b>Source audit:</b> {evidence.sources.map(source => `${source.label} ${source.rows}`).join(' · ')}.<br />
        <b>Quantity-bearing rows:</b> {shareCoverage}. A remaining blank means no compatible event or aggregate supplied the field; deterministic derivations and account-alias joins are labeled in the expanded audit.
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,minmax(120px,1fr))', gap: 7, marginTop: 9 }}>
        {([
          ['EXITED SYMBOLS', counts.symbols, lane === 'ALL' && stateFilter === 'ALL' && classificationFilter === 'ALL' && !gapOnly, () => { setLaneBoth('ALL'); setStateFilter('ALL'); setClassificationFilter('ALL'); setGapOnly(false) }],
          ['CLASSIFIED', counts.classified, classificationFilter === 'CLASSIFIED', () => setClassificationFilter(value => value === 'CLASSIFIED' ? 'ALL' : 'CLASSIFIED')],
          ['READY NOW', counts.ready, lane === 'NOW', () => setLaneBoth(lane === 'NOW' ? 'ALL' : 'NOW')],
          ['NEAR ENTRY', counts.near, lane === 'NEAR', () => setLaneBoth(lane === 'NEAR' ? 'ALL' : 'NEAR')],
          ['EVIDENCE GAPS', counts.missing, gapOnly, () => setGapOnly(value => !value)],
        ] as const).map(([name, value, active, action]) => (
          <button
            key={String(name)}
            type="button"
            onClick={action}
            style={{ ...panel, padding: 9, textAlign: 'left', cursor: 'pointer', background: active ? BB.blueDim : 'var(--bg2)', color: 'var(--text0)' }}
          >
            <span style={{ color: BB.text3, fontSize: 10 }}>{String(name)}</span><br />
            <b style={{ fontSize: 20 }}>{String(value)}</b>
          </button>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px,1fr) 190px 170px 150px auto auto auto', gap: 7, marginTop: 8 }}>
        <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search symbol, state, source or missing field…" style={field} />
        <select value={queueFilter} onChange={event => setQueueFilter(event.target.value as 'ACTIVE' | 'SUPPRESSED' | 'ALL')} style={field} title="Suppressed symbols are hidden from the working queue">
          <option value="ACTIVE">ACTIVE QUEUE</option>
          <option value="SUPPRESSED">SUPPRESSED{suppressedTotal ? ` (${suppressedTotal})` : ''}</option>
          <option value="ALL">ACTIVE + SUPPRESSED</option>
        </select>
        <select value={stateFilter} onChange={event => { setStateFilter(event.target.value); if (event.target.value !== 'ALL') setLane('ALL') }} style={field}>
          <option value="ALL">ALL CURRENT STATES</option>
          {['READY TO REVIEW', 'NEAR ENTRY', 'WAIT', 'CURRENTLY HELD', 'STALE', 'MISSING PLAN', 'MISSING MARKET'].map(state => (
            <option key={state} value={state}>{state}</option>
          ))}
        </select>
        <select value={classificationFilter} onChange={event => setClassificationFilter(event.target.value)} style={field}>
          <option value="ALL">ALL CLASSIFICATIONS</option>
          <option value="CLASSIFIED">CLASSIFIED</option>
          <option value="AUTO-TAGGED">AUTO-TAGGED</option>
          <option value="UNCLASSIFIED">UNCLASSIFIED</option>
        </select>
        <button type="button" onClick={() => setSelected(Object.fromEntries(shown.map(row => [row.symbol, true])))} style={button(false)}>SELECT VISIBLE</button>
        <button type="button" onClick={() => setSelected({})} style={button(false)}>CLEAR</button>
        <button type="button" disabled={!selectedSymbols.length} onClick={() => classify(selectedSymbols)} style={{ ...button(Boolean(selectedSymbols.length)), opacity: selectedSymbols.length ? 1 : .5 }}>EDIT SELECTED {selectedSymbols.length}</button>
      </div>

      <div style={{ overflowX: 'auto', marginTop: 8 }}>
        <div style={{ minWidth: 1530 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '28px 180px 220px 125px 170px 170px 160px 160px 145px', gap: 8, padding: '7px 9px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}>
            <span></span>
            <span>Symbol / mandate</span>
            <span>Current decision</span>
            <span>Market</span>
            <span>Exit evidence</span>
            <span>Entry / levels</span>
            <span>Valuation / analyst</span>
            <span>Evidence audit</span>
            <span>Actions</span>
          </div>
          {shown.map(row => {
            const open = Boolean(expanded[row.symbol])
            const tone = stateTone(row.intel.state)
            const classTone = row.classified === 'CLASSIFIED' ? BB.green : row.classified === 'AUTO-TAGGED' ? BB.amber : BB.text3
            const mandateLabel = row.mandate.mandate === 'unclassified' && row.flags.length ? 'MANDATE NEEDED' : row.mandate.mandate.replace(/_/g, ' ').toUpperCase()
            const pe = row.intel.pe ?? numberFrom([row.watch, row.card, row.watch?.fundamentals, row.watch?.decision_packet?.blind_facts?.fundamentals], ['pe', 'trailing_pe'])
            const fpe = row.intel.forwardPe ?? numberFrom([row.watch, row.card, row.watch?.fundamentals, row.watch?.decision_packet?.blind_facts?.fundamentals], ['forward_pe', 'forwardPe', 'fwd_pe'])
            const rec = text(row.analyst?.rec, row.analyst?.recommendation, 'unavailable').replace(/_/g, ' ').toUpperCase()
            const score = row.intel.score
            return (
              <div key={row.symbol} data-testid={`reentry-row-${row.symbol}`} data-lane={score.lane}>
                <div
                  role="button"
                  tabIndex={0}
                  aria-expanded={open}
                  onKeyDown={event => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      setExpanded(value => ({ ...value, [row.symbol]: !open }))
                    }
                  }}
                  onClick={() => setExpanded(value => ({ ...value, [row.symbol]: !open }))}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '28px 180px 220px 125px 170px 170px 160px 160px 145px',
                    gap: 8,
                    padding: '9px',
                    borderBottom: '1px solid var(--border)',
                    alignItems: 'center',
                    fontSize: 10.5,
                    cursor: 'pointer',
                    background: open ? 'var(--bg2)' : 'transparent',
                    boxShadow: open ? `inset 3px 0 0 ${BB.blue}` : undefined,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={Boolean(selected[row.symbol])}
                    onClick={event => event.stopPropagation()}
                    onChange={event => setSelected(value => ({ ...value, [row.symbol]: event.target.checked }))}
                  />
                  <div>
                    <div>
                      <b style={{ fontSize: 14 }}>{row.symbol}</b>{' '}
                      <span style={{ color: classTone, fontSize: 10 }}>{classificationLabel(row.classified)}</span>{' '}
                      <span style={{ color: BB.text3 }}>{open ? '▾' : '▸'}</span>
                    </div>
                    <div style={{ marginTop: 3, color: mandateLabel === 'MANDATE NEEDED' ? BB.amber : BB.text2 }}>{mandateLabel}</div>
                    <div style={{ color: BB.text3 }}>{row.flags.join(' · ') || 'no strategy flags'}</div>
                  </div>
                  <div>
                    <span style={{ color: tone, fontWeight: 900 }}>{row.intel.state}</span>
                    <span style={{ marginLeft: 6, fontSize: 10, fontWeight: 800, color: BB.text3 }}>{score.lane}</span>
                    <div style={{ marginTop: 3, fontWeight: 800 }}>{row.intel.action}</div>
                    <div style={{ color: BB.text2, marginTop: 2, lineHeight: 1.4 }} title={row.intel.reason}>{row.intel.reason}</div>
                    {row.intel.highlights.length > 0 && (
                      <div style={{ marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {row.intel.highlights.map(h => (
                          <span key={h} style={{ fontSize: 10, fontWeight: 750, padding: '1px 5px', borderRadius: 3, border: '1px solid var(--border)', color: BB.text3, background: 'var(--bg1)' }}>{h}</span>
                        ))}
                      </div>
                    )}
                    <div style={{ color: BB.text3, marginTop: 3, fontSize: 10 }}>{score.scoreLabel}{!score.planIntegrityOk ? ' · plan integrity fail' : ''}</div>
                  </div>
                  <div>
                    <b>{money(row.intel.price)}</b><br />
                    <span style={{ color: BB.text3 }}>
                      RSI {row.intel.rsi === null ? '—' : row.intel.rsi.toFixed(1)}
                      {row.intel.rsiBand !== 'unavailable' ? ` ${row.intel.rsiBand}` : ''}
                      {' · '}{row.intel.trend}
                    </span><br />
                    <span style={{ color: BB.text3 }}>
                      {age(row.intel.asOf)} · MACD {row.intel.macd}
                      {row.intel.ma50 != null ? ` · MA50 ${money(row.intel.ma50)}` : ' · MA n/a'}
                    </span>
                  </div>
                  <div>
                    <b>{row.rows.length} exits · {row.shares === null ? 'shares unavailable' : `${row.shares.toLocaleString(undefined, { maximumFractionDigits: 4 })} sh`}</b><br />
                    <span>avg {money(row.avgExit)} · {money(row.proceeds)}</span><br />
                    <span style={{ color: BB.text3 }}>
                      {row.latest.trade_date ?? 'date unavailable'}
                      {row.intel.vsExitPct != null ? ` · vs exit ${row.intel.vsExitPct >= 0 ? '+' : ''}${row.intel.vsExitPct.toFixed(1)}%` : ''}
                    </span>
                  </div>
                  <div>
                    <b>
                      {row.intel.entryLow === null
                        ? 'entry unavailable'
                        : row.intel.entryLow === row.intel.entryHigh
                          ? money(row.intel.entryLow)
                          : `${money(row.intel.entryLow)}–${money(row.intel.entryHigh)}`}
                    </b>
                    <br />
                    <span style={{ color: BB.text3 }}>
                      stop {money(row.intel.stop)} · target {money(row.intel.target)}
                      {row.intel.riskReward != null ? ` · R:R ${row.intel.riskReward.toFixed(1)}` : ''}
                    </span><br />
                    <span>
                      R {row.resistance.state} {money(row.resistance.level)}
                      {row.resistance.distancePct === null ? '' : ` ${row.resistance.distancePct >= 0 ? '+' : ''}${row.resistance.distancePct.toFixed(1)}%`}
                      {' · S '}{money(row.intel.support)}
                    </span>
                  </div>
                  <div>
                    <b>P/E {pe === null ? '—' : pe.toFixed(2)} · Fwd {fpe === null ? '—' : fpe.toFixed(2)}</b><br />
                    <span>{rec}</span><br />
                    <span style={{ color: BB.text3 }}>
                      {row.analyst?.n ?? '—'} analysts · target {row.analyst?.target == null ? '—' : money(Number(row.analyst.target))}
                      {row.alertCount ? ` · ${row.alertCount} alerts` : ''}
                    </span>
                  </div>
                  <div>
                    <b>{row.completeness}/8 current fields</b><br />
                    <span style={{ color: row.eventGapCount ? BB.amber : BB.text3 }}>{row.eventGapCount} event gaps · {row.derivedCount} derived</span><br />
                    <span style={{ color: BB.text3 }}>{row.latest.import_source || 'source unavailable'}</span>
                  </div>
                  <div onClick={event => event.stopPropagation()}>
                    <button type="button" onClick={() => setExpanded(value => ({ ...value, [row.symbol]: true }))} style={button(true)}>OPEN GATES</button>
                    <button type="button" onClick={() => setArmSymbol(row.symbol)} style={{ ...button(false), marginTop: 5 }} data-testid={`reentry-arm-${row.symbol}`}>
                      ARM ALERT{row.alertCount ? ` (${row.alertCount})` : ''}
                    </button>
                    <button type="button" onClick={() => classify([row.symbol])} style={{ ...button(false), marginTop: 5 }}>CLASSIFY</button>
                    <button type="button" onClick={() => openWatch(row.symbol)} style={{ ...button(false), marginTop: 5 }}>OPEN WATCH</button>
                  </div>
                </div>
                {open && (
                  <div style={{ padding: '10px 14px 14px 42px', background: 'var(--bg2)', borderBottom: '1px solid var(--border)', display: 'grid', gridTemplateColumns: '1fr 1fr 0.9fr', gap: 16 }}>
                    <div>
                      <div style={{ fontSize: 10, fontWeight: 900, color: BB.text3, marginBottom: 6 }}>
                        DECISION SCORECARD — {score.scoreLabel} · lane {score.lane}
                      </div>
                      <div style={{ fontSize: 10.5, marginBottom: 8, color: BB.text2 }}>
                        <b style={{ color: tone }}>{row.intel.state}</b> — {row.intel.action}. {row.intel.reason}
                      </div>
                      <ReEntryMiniChart symbol={row.symbol} entryLow={row.intel.entryLow} entryHigh={row.intel.entryHigh} stop={row.intel.stop} resistance={row.resistance.level} avgExit={row.avgExit} />
                      {score.gates.map(gate => (
                        <div
                          key={gate.id}
                          data-testid={`reentry-gate-${row.symbol}-${gate.id}`}
                          style={{
                            display: 'grid',
                            gridTemplateColumns: '72px 34px 130px 1fr',
                            gap: 6,
                            padding: '4px 0',
                            fontSize: 10.5,
                            borderBottom: '1px solid var(--border)',
                            alignItems: 'start',
                          }}
                        >
                          <b style={{ color: gateColor(gate.state) }}>{gate.state}</b>
                          <span style={{ color: BB.text3, fontSize: 10 }}>{gate.kind}</span>
                          <b>{gate.label}</b>
                          <span style={{ color: BB.text3 }}>
                            {gate.current}
                            <span style={{ display: 'block' }}>need: {gate.threshold} — {gate.why}</span>
                          </span>
                        </div>
                      ))}
                      <div style={{ marginTop: 8, fontSize: 10, color: BB.text3 }}>
                        Support {money(row.intel.support)} · MA20 {money(row.intel.ma20)} · MA50 {money(row.intel.ma50)} · MA200 {money(row.intel.ma200)} · MACD {row.intel.macd}
                      </div>
                    </div>
                    <div>
                      <div style={{ fontSize: 10, fontWeight: 900, color: BB.text3, marginBottom: 6 }}>RECONCILED EXIT HISTORY — FIELD-BY-FIELD AUDIT</div>
                      {row.rows.map(exit => {
                        const event = normalizedEvent(exit, events[exit.event_key])
                        return (
                          <div key={exit.event_key} style={{ padding: '7px 0', borderBottom: '1px solid var(--border)' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: '85px 100px 80px 80px 90px 1fr', gap: 6, fontSize: 10 }}>
                              <span>{exit.trade_date ?? '—'}</span>
                              <span>{exit.account ?? '—'}</span>
                              <span>{rowShares(exit) === null ? '—' : `${rowShares(exit)?.toLocaleString(undefined, { maximumFractionDigits: 4 })} sh`}</span>
                              <span>{money(rowPrice(exit))}</span>
                              <span>{money(finite(exit.proceeds_usd))}</span>
                              <span>
                                <b>{event.eventType.replace(/_/g, ' ').toUpperCase()}</b><br />
                                <span style={{ color: BB.text3 }}>{event.reason || 'reason unavailable'}</span>
                              </span>
                            </div>
                            <div style={{ marginTop: 5, fontSize: 10, color: BB.text3 }}>
                              Sources — account: {sourceFor(exit, 'account')} · shares: {sourceFor(exit, 'quantity')} · price: {sourceFor(exit, 'price')} · proceeds: {sourceFor(exit, 'proceeds_usd')}
                            </div>
                            {Boolean(exit.derived_fields?.length) && (
                              <div style={{ marginTop: 3, fontSize: 10, color: BB.blue }}>Derived deterministically: {exit.derived_fields?.join(' · ')}</div>
                            )}
                            {Boolean(exit.evidence_gaps?.length) && (
                              <div style={{ marginTop: 3, fontSize: 10, color: BB.amber }}>Still missing: {exit.evidence_gaps?.join(' · ')}</div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                    <div>
                      <div style={{ fontSize: 10, fontWeight: 900, color: BB.text3, marginBottom: 6 }}>CURRENT WATCH / PORTFOLIO CONTEXT</div>
                      <div style={{ fontSize: 10.5, lineHeight: 1.55 }}>
                        <b>Mandate:</b> {mandateLabel}<br />
                        <b>Priority:</b> {row.mandate.priority}<br />
                        <b>Thesis:</b> {row.mandate.thesis || 'No operator thesis saved.'}<br />
                        <b>Watch recommendation:</b> {text(row.watch?.synthesis_recommendation, row.watch?.latest_recommendation, 'unavailable').replace(/_/g, ' ')}<br />
                        <b>Sector:</b> {text(row.watch?.profile_sector, row.card?.sector, 'unavailable')}<br />
                        <b>Catalyst:</b> {text(row.watch?.catalyst_headline, 'unavailable')}<br />
                        <b>Earnings:</b> {text(row.watch?.earnings_date, row.watch?.next_earnings_date, 'unavailable')}<br />
                        <b>Resistance source:</b> {row.resistance.source} — {row.resistance.reason}<br />
                        <b>Disposition:</b> {normalizedEvent(row.latest, events[row.latest.event_key]).eventType.replace(/_/g, ' ')}
                      </div>
                      <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
                        <button type="button" onClick={() => classify([row.symbol])} style={button(true)}>EDIT CLASSIFICATION</button>
                        <button type="button" onClick={() => setArmSymbol(row.symbol)} style={button(false)}>ARM ZONE / RSI ALERT</button>
                        <button type="button" onClick={() => openWatch(row.symbol)} style={button(false)}>OPEN {row.symbol} IN WATCH</button>
                        <button type="button" onClick={() => openRotation(row.symbol)} style={button(false)}>OPEN ROTATION</button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
      {evidence.errors.length > 0 && (
        <div style={{ marginTop: 7, color: BB.red, fontSize: 10 }}>Source warnings: {evidence.errors.join(' · ')}</div>
      )}
      {!shown.length && (
        <div style={{ padding: 14, color: BB.text3 }}>
          No symbols match the current filters.
          {lane === 'NOW' && laneCounts.now === 0 && laneCounts.near > 0 && (
            <>{' '}
              <button type="button" onClick={() => setLaneBoth('NEAR')} style={button(true)}>
                View {laneCounts.near} NEAR
              </button>
              {' '}
              <button type="button" onClick={() => setLaneBoth('ALL')} style={button(false)}>
                View all {laneCounts.all}
              </button>
            </>
          )}
        </div>
      )}
      {armRow && (
        <ReEntryAlertArmModal
          symbol={armRow.symbol}
          short={Boolean(armRow.mandate.flags.short)}
          intel={{
            entryLow: armRow.intel.entryLow,
            entryHigh: armRow.intel.entryHigh,
            price: armRow.intel.price,
            rsi: armRow.intel.rsi,
          }}
          onClose={() => setArmSymbol(null)}
          onArmed={summary => {
            setArmSymbol(null)
            setToast(`${armRow.symbol} alerts armed: ${summary}`)
            alerts.refetch()
            window.setTimeout(() => setToast(''), 6000)
          }}
        />
      )}
    </div>
  )
}

export { parseLane }
