/** TradeInView — the per-trade journey page model (operator directive 2026-10-22). Pure; no React.
 *
 *  The page reads ONE projection: GET /api/v3/data-broker/trade-journeys (scripts/lib/data_broker/trade_journey.py,
 *  schema TradeJourneys@v1) — the CIO prospect record when its store is live, an interim adapter until then (labelled).
 *  The server owns origin, stop path, exit cause, review facts, re-entry conditions and conflicts; this file only
 *  decides filters, words, tones, tooltips and chart geometry. */
import type { Tone } from './designTokens.ts'

export type OriginKind = 'internal' | 'operator' | 'unknown'
export type ExitKind = 'stop_out' | 'trailing_ratchet' | 'target' | 'manual' | 'stop_likely_filled' | 'open' | 'unknown'

export type Side = { value?: unknown; source?: string | null; at?: string | null }
export type Conflict = { field?: string | null; summary: string; a: Side; b: Side }
export type Origin = {
  kind: OriginKind; label: string; surface: string | null; surface_href: string | null
  rank_at_entry: number | null; conviction_at_entry: number | null; stance_at_entry: string | null
  cio_entry_state: string | null; cio_entry_state_at: string | null; issued_at: string | null
  rec_id: string | null; rec_source: string | null; link_confidence: string | null
  plan: { entry_low_ref: number | null; entry_high_ref: number | null; invalidation_ref: number | null; target_ref: number | null } | null
  evidence: { source: string; detail: string }[]; link_status: string
}
export type ExitCause = { kind: ExitKind; label: string; detail: string; confirmed: boolean; level_ref: number | null; raises: number }
export type StopStep = { at: string; level_ref: number; prior_ref: number | null; change_pct: number | null; kind: 'initial' | 'raise' | 'lower'; source: string }
export type TimelineEvent = {
  at: string | null; kind: 'origin' | 'entry_fill' | 'stop_change' | 'conviction_change' | 'stance_change' | 'exit_fill'
  label: string; detail?: string | null; source?: string | null; cause?: string; unconfirmed?: boolean; approximate?: boolean
}
export type Fact = { key: string; label: string; value: string; source: string; tone: Tone }
export type Advisory = { text: string; model?: string | null; provider?: string | null; generated_at?: string | null; label: string; source: string; stop_quality?: string | null; reentry_risk?: string | null }
export type Condition = { id: string; label: string; met: boolean | null; detail?: string | null }
export type ReEntry = {
  source: string; desk_as_of: string | null; stale: boolean | null; state: string | null; action: string | null
  reason: string | null; distance_pct: number | null; price_ref: number | null; price_as_of: string | null
  zone_low_ref: number | null; zone_high_ref: number | null; invalidation_ref: number | null; target_ref: number | null
  reclaim_ref: number | null; conditions: Condition[]; summary: string | null; wash_blocked: boolean | null
  wash_until: string | null; alert_seed: { entryLow: number | null; entryHigh: number | null; price: number | null; rsi: number | null } | null
  watch_href: string | null
}
export type Bar = { time: string; open?: number | null; high?: number | null; low?: number | null; close: number | null }
export type Chart = {
  kind: 'candles' | 'closes' | 'none'; bars: Bar[]; source: string; as_of?: string | null
  marks: { entry_ref: number | null; entry_at: string | null; exit_ref: number | null; exit_at: string | null
    stops: { at: string | null; level_ref: number }[]; high_ref: number | null; high_at: string | null; low_ref: number | null
    low_at: string | null; zone_low_ref: number | null; zone_high_ref: number | null }
}
export type Journey = {
  trade_id: string; symbol: string; company?: string | null; account: string | null; status: 'open' | 'closed'
  fill_qty: number | null; entry: { price_ref: number | null; at: string | null; source?: string | null; at_basis?: string | null }
  exit: { price_ref: number | null; at: string | null; source?: string | null } | null
  mark: { price_ref: number | null; at: string | null } | null
  pl: { amount: number | null; pct: number | null; basis: 'realized' | 'unrealized' | 'pending'; note: string | null }
  hold_days: number | null; origin: Origin; exit_cause: ExitCause; stop_path: StopStep[]; timeline: TimelineEvent[]
  review: { facts: Fact[]; metrics: Record<string, number | null>; advisory: Advisory | null }
  re_entry: ReEntry; conflicts: Conflict[]; conviction_now: number | null; stance_now: string | null
  rank_now: number | null; stage: string | null; chart?: Chart | null; security_guid?: string | null; identity_status?: string
}
export type Chip = { key: string; label: string; value: string; tone: Tone; at: string | null; tip: string }
export type JourneysPayload = {
  schema: string; as_of: string; interim: boolean; source_label: string
  source: { kind: string; cio_prospect_status: string; reads: string[] }
  window_days: number | null; counts: Record<string, number>; freshness: Chip[]
  gaps: { input: string; why: string }[]; journeys: Journey[]
}

export const API_LIST = '/api/v3/data-broker/trade-journeys'
export const apiDetail = (id: string) => `${API_LIST}/${encodeURIComponent(id)}`

export function unwrap(raw: any): JourneysPayload | null {
  const d = raw?.data && Array.isArray(raw?.data?.journeys) ? raw.data : raw
  return d && Array.isArray(d.journeys) ? (d as JourneysPayload) : null
}

export function unwrapDetail(raw: any): Journey | null {
  const d = raw?.data && raw?.data?.journey ? raw.data : raw
  return d && d.journey && typeof d.journey === 'object' ? (d.journey as Journey) : null
}

// ── filters ──────────────────────────────────────────────────────────────────

export type FilterId = 'all' | 'attention' | 'open' | 'closed' | 'internal' | 'mine'
export const FILTERS: { id: FilterId; label: string; tip: string; test: (j: Journey) => boolean }[] = [
  { id: 'all', label: 'All', tip: 'Every open position and every trade closed in the window.', test: () => true },
  { id: 'attention', label: 'Needs a look', tip: 'A stop that has likely filled but is not confirmed, or a conflict between sources.',
    test: j => j.exit_cause.kind === 'stop_likely_filled' || j.conflicts.length > 0 },
  { id: 'open', label: 'Open', tip: 'Positions you still hold.', test: j => j.status === 'open' },
  { id: 'closed', label: 'Closed', tip: 'Round trips closed in the window (from the broker transaction ledger).', test: j => j.status === 'closed' },
  { id: 'internal', label: 'From internal', tip: 'Trades whose idea came from an internal surface (Home, Proposals, Trade AI, a CIO entry call).', test: j => j.origin.kind === 'internal' },
  { id: 'mine', label: 'Your picks', tip: 'Trades the recommendation linker recorded as your own idea (no internal recommendation was active).', test: j => j.origin.kind === 'operator' },
]
export function filterJourneys(js: Journey[], id: FilterId): Journey[] {
  const f = FILTERS.find(x => x.id === id) ?? FILTERS[0]
  return js.filter(f.test)
}
export function filterCounts(js: Journey[]): Record<FilterId, number> {
  return Object.fromEntries(FILTERS.map(f => [f.id, js.filter(f.test).length])) as Record<FilterId, number>
}

// ── words and tones ──────────────────────────────────────────────────────────

export const ORIGIN_TONE: Record<OriginKind, Tone> = { internal: 'ai', operator: 'info', unknown: 'neutral' }
export const EXIT_TONE: Record<ExitKind, Tone> = {
  stop_out: 'danger', trailing_ratchet: 'warning', target: 'success', manual: 'info', stop_likely_filled: 'warning',
  open: 'neutral', unknown: 'neutral',
}

/** The short origin badge for the table: "INTERNAL · Home #4 · 86" / "YOUR PICK" / "ORIGIN ?". */
export function originBadge(o: Origin): { text: string; tone: Tone } {
  if (o.kind === 'internal') {
    const bits = [o.surface ?? 'Internal']
    if (o.rank_at_entry != null && (o.surface === 'Home' || o.surface === 'Watch')) bits[0] = `${bits[0]} #${o.rank_at_entry}`
    if (o.conviction_at_entry != null) bits.push(String(Math.round(o.conviction_at_entry)))
    return { text: `INTERNAL · ${bits.join(' · ')}`, tone: ORIGIN_TONE.internal }
  }
  if (o.kind === 'operator') return { text: 'YOUR PICK', tone: ORIGIN_TONE.operator }
  return { text: 'ORIGIN ?', tone: ORIGIN_TONE.unknown }
}

export function money(v: number | null | undefined, signed = false): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const abs = Math.abs(v)
  const s = abs >= 1000 ? Math.round(abs).toLocaleString('en-US') : abs.toFixed(2)
  if (!signed) return `${v < 0 ? '−' : ''}$${s}`
  return `${v < 0 ? '−' : '+'}$${s}`
}
export function px(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? '—' : `$${v.toFixed(2)}`
}
export function pct(v: number | null | undefined, digits = 1): string {
  return v == null || !Number.isFinite(v) ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(digits)}%`
}
export function plTone(v: number | null | undefined): Tone {
  return v == null ? 'neutral' : v > 0 ? 'success' : v < 0 ? 'danger' : 'neutral'
}
/** "10-19 10:02" in New York time (no seconds, no zone suffix — the page states ET once). */
export function etShort(at: string | null | undefined): string {
  if (!at) return '—'
  const d = new Date(at)
  if (Number.isNaN(d.getTime())) return String(at).slice(0, 10)
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false }).formatToParts(d)
  const g = (t: string) => parts.find(p => p.type === t)?.value ?? ''
  const hh = g('hour') === '24' ? '00' : g('hour')
  return `${g('month')}-${g('day')} ${hh}:${g('minute')}`
}
export function plText(j: Journey): string {
  if (j.pl.amount == null && j.pl.pct == null) return j.pl.note ? 'basis pending' : '—'
  const a = j.pl.amount != null ? money(j.pl.amount, true) : ''
  const p = j.pl.pct != null ? pct(j.pl.pct, 1) : ''
  return [a, p ? `(${p})` : ''].filter(Boolean).join(' ')
}
export function exitText(j: Journey): string {
  if (j.status === 'open' && j.exit_cause.kind === 'open') {
    return j.exit_cause.level_ref != null ? `open · stop ${px(j.exit_cause.level_ref)}` : 'open · no stop on record'
  }
  return j.exit_cause.label
}

export const TIMELINE_LABEL: Record<TimelineEvent['kind'], string> = {
  origin: 'Origin', entry_fill: 'Entry', stop_change: 'Stop', conviction_change: 'Conviction',
  stance_change: 'Stance', exit_fill: 'Exit',
}
export const TIMELINE_TONE: Record<TimelineEvent['kind'], Tone> = {
  origin: 'ai', entry_fill: 'info', stop_change: 'warning', conviction_change: 'ai', stance_change: 'ai', exit_fill: 'danger',
}
export function timelineTone(e: TimelineEvent): Tone {
  if (e.kind === 'exit_fill') return EXIT_TONE[(e.cause as ExitKind) ?? 'unknown'] ?? 'danger'
  return TIMELINE_TONE[e.kind]
}

export function conditionsMet(r: ReEntry): { met: number; total: number } {
  return { met: r.conditions.filter(c => c.met === true).length, total: r.conditions.length }
}

/** The armed-alert seed for the existing ReEntryAlertArmModal (never an order). */
export function alertIntel(r: ReEntry): { entryLow: number | null; entryHigh: number | null; price: number | null; rsi: number | null } | null {
  return r.alert_seed ?? null
}

// ── tooltips (one place; every one says where the number comes from) ────────

export const TOOLTIPS = {
  origin: 'Where the idea came from. INTERNAL = an internal surface had it before you bought: the recommendation the linker '
    + 'matched (learning loop PR1), else the CIO opportunity book version in force at your entry (its rank on Home and its '
    + 'conviction) and any CIO BUY_READY / ENTRY_NEAR call in the 10 days before. YOUR PICK = the linker found no active '
    + 'recommendation. ORIGIN ? = nothing recorded either way — never assumed to be yours.',
  pl: 'Closed: net P/L from the round trip (fills and fees). Open: shares × latest mark − entry fill. "basis pending" when '
    + 'the entry fill is not in the transaction ledger yet.',
  exit: 'Why the trade ended, from fills and observed stops: a fill at (or just below) the working stop is a stop-out; a '
    + 'trailing ratchet when the stop had been raised and sat at or above your entry; at the plan target is a target; '
    + 'anything else is a manual sell. "Stop likely filled" = the latest mark is at or below the working stop, but no '
    + 'fill is synced yet.',
  conviction: 'CIO conviction 0–100 from the opportunity book: at your entry → now.',
  timeline: 'Every recorded event for this trade in time order (New York time): the origin, the entry fill, each stop level '
    + 'the scan observed, CIO conviction / stance / rank changes while you held it, and the exit.',
  chart: 'Daily bars from the data broker (market_ohlcv_bars; closes when candles are missing). Lines: entry, each stop '
    + 'level, exit; the shaded band is the re-entry zone. Dots mark the high and the low while held.',
  review: 'Facts first, each with its source. The model note below them is advisory — a stored model output, not a fact.',
  reentry: 'The deterministic re-entry desk record — the same one the Watch page\'s "Re-entry near" lane reads. No model '
    + 'sets READY / NEAR / BLOCK. Levels are reference levels for your decision, never orders.',
  setAlert: 'Arms an advisory Watch alert (price zone + RSI) through the existing alert form. It notifies you; it never '
    + 'places, sizes or moves an order.',
  conflicts: 'Two sources disagree about this trade. Both values, sources and times are shown; nothing here picks a winner '
    + '(AGENTS.md §26.5).',
  interim: 'AGENTS.md §26: pages read the CIO prospect record through its projection. Until that store is live this page '
    + 'reads an interim adapter over today\'s sources with the identical shape.',
} as const

// ── drawers ──────────────────────────────────────────────────────────────────

export function drawers(p: JourneysPayload): { id: string; title: string; summary: string; body: string }[] {
  const conflicts = p.journeys.flatMap(j => j.conflicts.map(c => `${j.symbol}: ${c.summary} — ${String(c.a.value)} (${c.a.source ?? '—'}) vs ${String(c.b.value)} (${c.b.source ?? '—'})`))
  return [
    { id: 'conflicts', title: 'Conflicts', summary: conflicts.length ? `${conflicts.length} shown, not resolved` : 'none',
      body: conflicts.length ? conflicts.join('\n') : 'No source disagrees about any trade in the window.' },
    { id: 'gaps', title: 'Data gaps', summary: p.gaps.length ? `${p.gaps.length} input${p.gaps.length === 1 ? '' : 's'} missing` : 'none',
      body: p.gaps.length ? p.gaps.map(g => `${g.input}: ${g.why}`).join('\n') : 'Every input answered.' },
    { id: 'how', title: 'How this page works', summary: 'where each column comes from',
      body: [
        'One row per trade: positions you hold and round trips closed in the last ' + (p.window_days ?? 30) + ' days.',
        'Origin: ' + TOOLTIPS.origin,
        'Exit: ' + TOOLTIPS.exit,
        'P/L: ' + TOOLTIPS.pl,
        'Re-entry: ' + TOOLTIPS.reentry,
        'Nothing on this page sizes, places, moves or cancels an order. Set alert arms an advisory notification only.',
        `Record: ${p.source_label}. Reads: ${p.source.reads.join(', ') || '—'}.`,
      ].join('\n') },
  ]
}

// ── chart geometry ───────────────────────────────────────────────────────────

export type ChartGeom = {
  w: number; h: number; pad: { l: number; r: number; t: number; b: number }
  lo: number; hi: number; y: (v: number) => number; x: (i: number) => number; xOf: (date: string | null) => number | null
  bars: { x: number; o: number | null; h: number | null; l: number | null; c: number | null; time: string }[]
  ticks: number[]
}

export const CHART_LEAD_BARS = 25

/** Scales for the price band. Shows the trade plus CHART_LEAD_BARS sessions before the entry. */
export function chartGeom(c: Chart, w = 640, h = 220): ChartGeom | null {
  const all = c.bars.filter(b => b.close != null)
  const entryDay = c.marks.entry_at ? c.marks.entry_at.slice(0, 10) : null
  const firstIn = entryDay ? all.findIndex(b => String(b.time).slice(0, 10) >= entryDay) : -1
  const bars = firstIn > CHART_LEAD_BARS ? all.slice(firstIn - CHART_LEAD_BARS) : all
  if (!bars.length) return null
  const vals: number[] = []
  for (const b of bars) for (const v of [b.high, b.low, b.close]) if (v != null) vals.push(v)
  const m = c.marks
  for (const v of [m.entry_ref, m.exit_ref, m.zone_low_ref, m.zone_high_ref, ...m.stops.map(s => s.level_ref)]) if (v != null) vals.push(v)
  let lo = Math.min(...vals), hi = Math.max(...vals)
  const span = hi - lo || hi * 0.02 || 1
  lo -= span * 0.04; hi += span * 0.04
  const pad = { l: 8, r: 74, t: 10, b: 22 }
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b
  const step = iw / Math.max(1, bars.length)
  const x = (i: number) => pad.l + step * (i + 0.5)
  const y = (v: number) => pad.t + ih - ((v - lo) / (hi - lo)) * ih
  const dates = bars.map(b => String(b.time).slice(0, 10))
  const xOf = (date: string | null) => {
    if (!date) return null
    const d = date.slice(0, 10)
    let idx = dates.findIndex(t => t >= d)
    if (idx < 0) idx = dates.length - 1
    return x(idx)
  }
  const n = 4
  const ticks = Array.from({ length: n + 1 }, (_, i) => lo + ((hi - lo) * i) / n)
  return { w, h, pad, lo, hi, y, x, xOf, ticks,
    bars: bars.map((b, i) => ({ x: x(i), o: b.open ?? null, h: b.high ?? null, l: b.low ?? null, c: b.close, time: String(b.time).slice(0, 10) })) }
}

/** Right-axis label positions that never overlap: sorted by y, each at least ``gap`` px below the previous, then
 *  shifted back up if the stack ran past ``bottom``. Returns {key: y}. */
export function spreadLabels(items: { key: string; y: number }[], gap = 11, top = 0, bottom = Infinity): Record<string, number> {
  const s = [...items].sort((a, b) => a.y - b.y)
  const ys: number[] = []
  for (const it of s) ys.push(Math.max(it.y, ys.length ? ys[ys.length - 1] + gap : top))
  const over = ys.length ? ys[ys.length - 1] - bottom : 0
  const out: Record<string, number> = {}
  s.forEach((it, i) => { out[it.key] = over > 0 ? Math.max(top, ys[i] - over) : ys[i] })
  return out
}

/** One horizontal segment per stop level. Timed stops start where they were observed and run to the next level (the
 *  last to the exit or the right edge). Untimed stops (a relayed read with only an order) share the held span evenly,
 *  in order — their position says "in this order", not "at this time". */
export function stopSegments(g: ChartGeom, m: Chart['marks']): { x1: number; x2: number; y: number; level: number; timed: boolean }[] {
  const n = m.stops.length
  if (!n) return []
  const right = g.w - g.pad.r
  const x0 = g.xOf(m.entry_at) ?? g.pad.l
  const xEnd = g.xOf(m.exit_at) ?? right
  const timed = m.stops.every(s => !!s.at)
  return m.stops.map((s, i) => {
    if (timed) {
      const x1 = g.xOf(s.at) ?? x0
      const x2 = i + 1 < n ? (g.xOf(m.stops[i + 1].at) ?? xEnd) : xEnd
      return { x1, x2: Math.max(x1 + 1, x2), y: g.y(s.level_ref), level: s.level_ref, timed: true }
    }
    const span = Math.max(1, xEnd - x0)
    return { x1: x0 + (span * i) / n, x2: x0 + (span * (i + 1)) / n, y: g.y(s.level_ref), level: s.level_ref, timed: false }
  })
}
