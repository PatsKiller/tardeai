// Home v007 additive context (HomeMarketRiskContext@v1) — display model.
//
// Reads the OPTIONAL `home_v007` object on GET /api/v2/market-risk/latest. Every fact carries
// value/state/as_of/source/age_seconds and, when not ok, reason + remediation. This module never invents a value:
// unknown/missing/future renders as unknown with its reason; stale keeps the value AND its age; not_applicable says
// so rather than looking like a gap. Advisory only — no size, order or stop level.
// Runs under node --experimental-strip-types (homeV007.test.ts).

import { fmtAsOf } from './asOfDisplay.ts'

export type FactState = 'measured' | 'partial' | 'unknown' | 'not_applicable'

export type Fact = {
  state: FactState
  /**
   * The producer's own state word, kept verbatim. A stale observation is a real measurement of a past instant, so it
   * keeps its value — but the word must survive to the screen instead of being relabelled "measured" and forgotten.
   */
  word: string | null
  stale: boolean
  asOf: string | null
  source: string | null
  ageSeconds: number | null
  reason: string | null
  remediation: string | null
}

export type QuoteLine = Fact & {
  price: number | null
  session: string | null
  sessionDate: string | null
  expectedSessionDate: string | null
  basis: string | null
  /**
   * The producer's own dual-mark conflict when two recorded observations of the same instant disagree. The two marks
   * are the evidence a reader needs to reconcile them; the reason alone (which also drives the unknown state) is not
   * enough to show WHICH two observations disagreed.
   */
  conflict: { reason: string | null; asOf: string | null; marks: Array<{ price: number | null; source: string | null }> } | null
}

export type SymbolContext = {
  symbol: string
  quote: QuoteLine
  dayChange: { usd: number | null; pct: number | null; referenceDate: string | null } & Fact
  sinceExit: { usd: number | null; pct: number | null; exitPrice: number | null; exitDate: string | null } & Fact
  references: Array<{ label: string; price: number | null; distanceUsd: number | null; distancePct: number | null } & Fact>
  /**
   * The collection's own fact. `partial` is what the producer emits when some nested references are missing: the
   * measured rows below are still true, but the set is incomplete and the card must say so.
   */
  referencesFact: Fact
  headlines: Array<{ title: string; source: string | null; publishedAt: string | null }>
  nextEvent: { label: string | null; at: string | null } & Fact
  cio: { stance: string | null; conviction: string | number | null; stale: boolean } & Fact
  marketStance: { value: string | null; headline?: string | null } & Fact
  /** The producer's own volume basis text ("not time-adjusted"), never a flag the parser invents. */
  volume: { ratio: number | null; basis: string | null; sampleSessions: number | null; averageStartDate: string | null; averageEndDate: string | null } & Fact
}

export type BudgetRow = {
  key: string
  label: string
  current: number | null
  budget: number | null
  unit: string | null
  clearsWhen: string | null
  breach: boolean
  /** The canonical scope the measurement belongs to, when the payload names one. */
  scopeId: string | null
  /** RAW owner binding: when the numbers were measured, and the source hash they were read from. */
  sourceAsOf: string | null
  sourceSha: string | null
  /** COMPOSITE binding the decision route is scoped to; display keeps it distinct from the raw binding. */
  presentationSha: string | null
  operatorDecision: 'available' | 'unavailable'
  decisionRemediation: string | null
  /** An operator's intentional budget decision: shown, never offered. No button exists for it. */
  decision: {
    active: boolean
    intentionalUntil: string | null
    actor: string | null
    receipt: string | null
    history: number
  }
} & Fact

export type HomeV007 = {
  present: boolean
  /**
   * The producer's top-level `state`. `unavailable` is a stated failure, not an empty success: the block carries a
   * reason, a remediation, and the gaps/read errors that explain it, and the card renders that instead of a frame.
   */
  state: string | null
  unavailable: boolean
  blockReason: string | null
  blockRemediation: string | null
  symbols: SymbolContext[]
  positions: Array<{ symbol: string; account: string | null; pctAccount: number | null; denominator: string | null; stopDistancePct: number | null; stopState: string | null }>
  risk: {
    score: number | null
    categories: Array<{ key: string; label: string; chip: string | null; state: FactState; asOf: string | null; source: string | null; reason: string | null; carried: boolean }>
    nextEvaluation: { at: string | null; basis: string | null } | null
  }
  hedge: { triggers: Array<{ label: string; current: number | null; threshold: number | null; unit: string | null; group: string | null } & Fact>; inverse: Array<{ symbol: string; dayPct: number | null; state: FactState }> }
  budgets: BudgetRow[]
  /** Top-level decision ledger. ``complete: false`` means the per-row history counts are partial. */
  decisionHistory: { complete: boolean | null; count: number | null; history: number }
  gaps: Array<{ member: string; key: string; reason: string | null; remediation: string | null }>
  readErrors: Array<{ member: string; code: string; remediation: string | null }>
}

const rec = (v: unknown): Record<string, unknown> | null => (v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : null)
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null)
const bool = (v: unknown): boolean => v === true
const STATES: FactState[] = ['measured', 'partial', 'unknown', 'not_applicable']

function remediationText(v: unknown): string | null {
  const o = rec(v)
  if (o) return [str(o.action), str(o.key) ? `(${str(o.key)})` : null].filter(Boolean).join(' ') || null
  return str(v)
}

function fact(o: Record<string, unknown> | null): Fact {
  const rawWord = str(o?.state)?.toLowerCase() ?? null
  // The contract emits measured | partial | unknown | not_applicable. Legacy spellings (ok/missing/stale) are read,
  // but 'stale' is NOT folded into 'measured': the value stays and the staleness is carried as its own signal.
  const raw = (rawWord === 'ok' ? 'measured' : rawWord === 'stale' ? 'measured' : rawWord === 'missing' ? 'unknown' : rawWord) as FactState | undefined
  const stale = rawWord === 'stale' || o?.stale === true
  const asOf = str(o?.as_of)
  const future = asOf ? (() => { const t = Date.parse(asOf); return Number.isFinite(t) && t > Date.now() + 60_000 })() : false
  return {
    state: future ? 'unknown' : (raw && STATES.includes(raw) ? raw : 'unknown'),
    word: rawWord,
    stale,
    asOf,
    source: str(o?.source),
    ageSeconds: num(o?.age_seconds),
    reason: future ? 'clock skew: as_of is in the future' : str(o?.reason),
    remediation: future ? null : remediationText(o?.remediation),
  }
}

/** The ET calendar date of an instant, so a quote's own clock can be checked against its declared session. */
function etDate(iso: string | null): string | null {
  if (!iso) return null
  const at = Date.parse(iso)
  if (!Number.isFinite(at)) return null
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York',
    year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(at)).map(p => [p.type, p.value]))
  return `${parts.year}-${parts.month}-${parts.day}`
}

/** The UTC calendar date of an instant: a date-only clock (``…T00:00:00Z``) names its session in UTC. */
function utcDate(iso: string | null): string | null {
  if (!iso) return null
  const at = Date.parse(iso)
  if (!Number.isFinite(at)) return null
  return new Date(at).toISOString().slice(0, 10)
}

/**
 * A measured claim that carries no number is not a measurement. It becomes unknown with a reason, so the card can
 * neither publish an empty "measured" row nor affirm a chip over nothing (DATA R3, 2026-11-03).
 */
function noValueIsUnknown<T extends Fact>(f: T, values: ReadonlyArray<number | null>): T {
  if (f.state !== 'measured' || values.some(v => v !== null)) return f
  return { ...f, state: 'unknown', reason: 'measured claim carried no value' }
}

function quote(base: Record<string, unknown> | null): QuoteLine {
  const q = rec(base?.quote)
  const f = fact(q)
  const value = rec(q?.value)
  const sessionDate = str(q?.session_date)
  const expected = str(q?.expected_session_date)
  const mismatched = !!(sessionDate && expected && sessionDate !== expected)
  // The declared session label is not evidence on its own: a cached print can be relabelled with today's date while
  // its own clock still says yesterday (DATA R1, 2026-11-03). Bind the observation clock to the session it claims.
  // A DATE-ONLY clock (exactly midnight UTC) names its day in UTC, not ET, so it may match the session in UTC. Any
  // other instant must agree in ET: 03:00Z is 22:00 ET on the previous day and is not a print for this session.
  const clockEt = etDate(f.asOf)
  const clockUtc = utcDate(f.asOf)
  const dateOnly = !!f.asOf && /T00:00:00(?:\.000)?Z$/.test(f.asOf)
  const utcAgrees = dateOnly && !!clockUtc && clockUtc === sessionDate
  const relabelled = !!(clockEt && sessionDate && clockEt !== sessionDate && !utcAgrees)
  // Only a measured fact is ours to downgrade: an unknown fact keeps its own reason, which says more than a mismatch.
  const downgrade = (mismatched || relabelled) && f.state === 'measured'
  const line: QuoteLine = {
    ...f,
    state: downgrade ? 'unknown' : f.state,
    reason: downgrade
      ? (mismatched ? `quote belongs to session ${sessionDate}, expected ${expected}`
        : `quote clock is ${clockEt} but it is labelled session ${sessionDate}`)
      : f.reason,
    // A downgraded quote keeps no value: an unknown fact must not carry a price the card could render.
    price: downgrade ? null : (num(value?.price) ?? num(q?.value)),
    session: str(q?.session),
    sessionDate,
    expectedSessionDate: expected,
    basis: str(q?.basis),
    conflict: (() => {
      const c = rec(q?.conflict)
      if (!c) return null
      const marks = (Array.isArray(c.marks) ? c.marks : []).filter(rec).map(m => {
        const mm = rec(m) as Record<string, unknown>
        return { price: num(mm.price), source: str(mm.source) }
      })
      return { reason: str(c.reason), asOf: str(c.as_of), marks }
    })(),
  }
  // A measured quote with no price is not a measurement either: downgrade it rather than render an empty value.
  return noValueIsUnknown(line, [line.price])
}

/** Inverse-fund moves arrive two ways: the producer's {symbol: symbol-context} map, or an array of move facts. */
function inverseMoves(raw: unknown): Array<{ symbol: string; dayPct: number | null; state: FactState }> {
  const map = rec(raw)
  if (map && !Array.isArray(map.value)) {
    return Object.entries(map).slice(0, 12).map(([symbol, v]) => {
      const o = rec(v) ?? {}
      const day = rec(o.day_change)
      return { symbol, dayPct: num(rec(day?.value)?.pct) ?? num(day?.value), state: fact(rec(o.quote) ?? o).state }
    })
  }
  const list = Array.isArray(rec(raw)?.value) ? (rec(raw)!.value as unknown[]) : (Array.isArray(raw) ? raw : [])
  return list.filter(rec).map(f => {
    const o = rec(f) as Record<string, unknown>
    return { symbol: str(o.symbol) ?? '?', dayPct: num(o.day_pct ?? o.day_change_pct), state: fact(o).state }
  })
}

export function parseHomeV007(raw: unknown): HomeV007 {
  const ctx = rec(raw)
  const gaps: HomeV007['gaps'] = []
  const readErrors: HomeV007['readErrors'] = []
  if (!ctx) return { present: false, state: null, unavailable: false, blockReason: null, blockRemediation: null, symbols: [], positions: [], risk: { score: null, categories: [], nextEvaluation: null }, hedge: { triggers: [], inverse: [] }, budgets: [], decisionHistory: { complete: null, count: null, history: 0 }, gaps: [{ member: 'home_v007', key: 'absent', reason: 'the response carries no home_v007 block', remediation: 'wait for the additive reader' }], readErrors }

  for (const g of (Array.isArray(ctx.gaps) ? ctx.gaps : [])) {
    const o = rec(g); if (o) gaps.push({ member: [str(o.symbol), str(o.field)].filter(Boolean).join('.') || '?', key: remediationText(o.remediation) ?? '?', reason: str(o.reason), remediation: remediationText(o.remediation) })
  }
  for (const e of (Array.isArray(ctx.read_errors) ? ctx.read_errors : [])) {
    const o = rec(e); if (o) readErrors.push({ member: str(o.member) ?? str(o.source) ?? '?', code: str(o.code) ?? str(o.reason) ?? '?', remediation: str(o.remediation) ?? remediationText(o.remediation) })
  }

  const symbolsRaw = rec(ctx.symbols) ?? {}
  const symbols: SymbolContext[] = Object.entries(symbolsRaw).map(([symbol, v]) => {
    const s = rec(v) ?? {}
    const dc = rec(s.day_change); const dcVal = rec(dc?.value)
    const se = rec(s.since_exit); const seVal = rec(se?.value)
    const cioRaw = rec(s.cio); const cioVal = rec(cioRaw?.value)
    const vol = rec(s.volume_vs_20d); const volVal = rec(vol?.value)
    const st = rec(s.market_risk_stance); const stVal = rec(st?.value)
    const refs = rec(s.analysis_references); const refsVal = rec(refs?.value)
    const heads = rec(s.headlines); const headVal = heads?.value
    const ne = rec(s.next_event); const neVal = rec(ne?.value)
    // Producer names and the e2e fixture's names are both accepted: neither shape is invented, only read.
    const dayChange = { ...fact(dc),
      usd: num(dcVal?.price) ?? num(dcVal?.usd),
      pct: num(dcVal?.pct),
      referenceDate: str(dcVal?.reference_session_date) ?? str(dcVal?.reference_date) ?? str(dc?.reference_session_date) ?? str(dc?.reference_date) }
    const sinceExit = { ...fact(se),
      usd: num(seVal?.distance_price) ?? num(seVal?.usd),
      pct: num(seVal?.distance_pct) ?? num(seVal?.pct),
      exitPrice: num(seVal?.reference_price) ?? num(seVal?.exit_price),
      // The recorded exit date is the fact-level `reference_as_of` (the exit record's own clock, which the producer
      // deliberately keeps separate from the quote clock). `exit_date` is only a legacy spelling, never another
      // fact's field: `reference_session_date` belongs to `day_change` and is not borrowed here.
      exitDate: str(se?.reference_as_of) ?? str(seVal?.exit_date) ?? str(se?.exit_date) }
    const references = refsVal
      ? Object.entries(refsVal).slice(0, 12).map(([label, v]) => {
          const o = rec(v) ?? {}
          // The nested reference states its OWN state and reason; the collection's state/reason are only fallbacks.
          // Overwriting a nested reason with the collection's loses the one line that explains this reference.
          const nested = fact({ ...o, state: o.state ?? refs?.state, as_of: o.price_as_of ?? refs?.as_of,
            source: refs?.source, age_seconds: refs?.age_seconds,
            reason: str(o.reason) ?? str(refs?.reason), remediation: o.remediation ?? refs?.remediation })
          const ref = { ...nested, label, price: num(o.reference_price), distanceUsd: num(o.distance_price), distancePct: num(o.distance_pct) }
          return noValueIsUnknown(ref, [ref.price, ref.distanceUsd, ref.distancePct])
        })
      : []
    return {
      symbol,
      quote: quote(s),
      dayChange: noValueIsUnknown(dayChange, [dayChange.usd, dayChange.pct]),
      sinceExit: noValueIsUnknown(sinceExit, [sinceExit.usd, sinceExit.pct, sinceExit.exitPrice]),
      references,
      referencesFact: fact(refs),
      // The producer's headline row is {title, source, url, published_at, guarded}; it carries no age, so the card
      // shows the article's own published clock instead of inventing an age from the query.
      headlines: Array.isArray(headVal) ? headVal.filter(rec).slice(0, 4).map(h => {
        const o = rec(h) as Record<string, unknown>
        return { title: str(o.title) ?? '(untitled)', source: str(o.source), publishedAt: str(o.published_at) }
      }) : [],
      nextEvent: { ...fact(ne), label: str(neVal?.label) ?? str(neVal?.kind), at: str(neVal?.at) ?? str(neVal?.date) },
      cio: { ...fact(cioRaw), stance: str(cioVal?.stance), conviction: num(cioVal?.conviction) ?? str(cioVal?.conviction) ?? num(rec(s.conviction)?.value), stale: bool(cioVal?.stale) || bool(cioRaw?.stale) },
      marketStance: { ...fact(st), value: str(stVal?.stance), headline: str(stVal?.headline) } as SymbolContext['marketStance'],
      volume: { ...fact(vol), ratio: num(volVal?.ratio), basis: str(volVal?.basis), sampleSessions: num(volVal?.sample_sessions), averageStartDate: str(volVal?.average_start_date), averageEndDate: str(volVal?.average_end_date) },
    }
  })

  const positions = (Array.isArray(ctx.positions) ? ctx.positions : []).filter(rec).slice(0, 60).map(p => {
    const o = rec(p) as Record<string, unknown>
    const sd = rec(o.stop) ?? rec(o.stop_distance)  // the producer names the fact `stop`
    return { symbol: str(o.symbol) ?? '?', account: str(o.account_label), pctAccount: num(o.pct_account) ?? num(o.account_pct_basis), denominator: str(o.pct_denominator) ?? str(o.account_pct_basis), stopDistancePct: num(sd?.pct) ?? num(rec(sd?.value)?.distance_pct_of_price), stopState: str(o.stored_stop_state) ?? str(rec(sd?.value)?.status) }
  })

  const riskRaw = rec(ctx.risk) ?? {}
  const risk = {
    score: num(riskRaw.score) ?? (() => {
      // The producer carries the score on the latest history row, not at the top level.
      const hist = Array.isArray(riskRaw.history) ? riskRaw.history.filter(rec) as Record<string, unknown>[] : []
      return hist.length ? num(hist[hist.length - 1].score) : null
    })(),
    categories: (Array.isArray(riskRaw.categories) ? riskRaw.categories : []).filter(rec).map(c => {
      const o = rec(c) as Record<string, unknown>
      const f = fact(o)
      const key = str(o.category) ?? str(o.key) ?? '?'
      // An affirmative chip is a claim about a measurement. Without one, AND without the clock that says when it was
      // measured (DATA R3, 2026-11-03), the chip is not shown and the row reads as unknown rather than publishing "OK"
      // over a fact that carries no provenance.
      // `carried` is the producer's own flag: a known observation made before a market closure that lies between it
      // and now. A carried category may never render an affirmative chip, so it arrives unknown with that reason —
      // and the word "carried" is the only thing that explains why a CALM observation is not OK.
      return { key, label: str(o.label) ?? key.replace(/_/g, ' '), chip: f.state === 'measured' && f.asOf ? str(o.chip) : null, state: f.state, asOf: f.asOf, source: f.source, reason: f.reason, carried: bool(o.carried) }
    }),
    nextEvaluation: (() => {
      const n = rec(riskRaw.next_evaluation)
      if (!n) return null
      const v = rec(n.value)
      // The producer puts a bare ISO timestamp in ``value``; older payloads nested it as {at, basis}.
      return {
        at: str(v?.at) ?? str(n.value),
        basis: str(v?.basis) ?? str(n.basis) ?? str(n.reason) ?? (fact(n).state === 'unknown' ? 'not declared' : null),
      }
    })(),
  }

  const hRaw = rec(ctx.hedge) ?? {}
  const trig = (key: 'lagging_progress' | 'exposure_progress') => {
    const f = rec(hRaw[key]); const v = rec(f?.value)
    // The producer's trigger value is {current, threshold, unit?, group?}; it states no `met`, and the card does not
    // derive one — a threshold comparison belongs to the producer that owns the trigger. The FACT is carried, not
    // dropped: an unmeasured or stale trigger must not print its numbers as if they were current.
    return f ? [{ ...fact(f), label: key === 'lagging_progress' ? 'lagging sectors' : 'exposure',
      current: num(v?.current), threshold: num(v?.threshold), unit: str(v?.unit), group: str(v?.group) }] : []
  }
  const hedge = {
    triggers: [...trig('lagging_progress'), ...trig('exposure_progress')],
    inverse: inverseMoves(hRaw.inverse_moves),
  }

  const budgets: BudgetRow[] = (Array.isArray(ctx.budgets) ? ctx.budgets : []).filter(rec).slice(0, 10).map(b => {
    const o = rec(b) as Record<string, unknown>
    const od = rec(o.operator_decision)
    const sb = rec(o.source_binding), pb = rec(o.presentation_binding)
    const bpd = rec(o.budget_presentation_decision)
    const actual = num(o.actual), limit = num(o.limit)
    // The producer states whether the row is measured and when, precisely so an unclocked row cannot publish numbers.
    // Only a payload without its own state falls back to the arithmetic, and that fallback REQUIRES a clock: an
    // arithmetic result with no as_of is a number nobody can date, so it is unknown with a reason, never measured.
    const fallbackClock = str(sb?.as_of)
    const arithmeticallyMeasured = actual != null && limit != null && !!fallbackClock
    const produced = typeof o.state === 'string' ? fact(o) : fact({
      state: arithmeticallyMeasured ? 'measured' : 'unknown',
      as_of: fallbackClock,
      source: 'market_risk_budgets',
      age_seconds: null,
      reason: actual != null && limit != null && !fallbackClock
        ? 'the row carries no measurement clock, so its arithmetic cannot be dated'
        : null,
      remediation: actual != null && limit != null && !fallbackClock
        ? { key: 'HOMEV007:budget.source_binding', action: 'Restore the canonical source clock for this budget row.' }
        : null,
    })
    return {
      ...produced,
      key: str(o.budget) ?? '?', label: str(o.budget)?.replace(/_/g, ' ') ?? '?', current: actual, budget: limit, unit: str(o.unit),
      clearsWhen: str(o.clears_when),
      breach: typeof o.breached === 'boolean' ? o.breached : actual != null && limit != null && actual > limit,
      operatorDecision: str(od?.state) === 'available' ? 'available' : 'unavailable',
      decisionRemediation: remediationText(od?.remediation),
      scopeId: str(o.scope_id),
      sourceAsOf: str(sb?.as_of),
      sourceSha: str(sb?.sha256),
      presentationSha: str(pb?.sha256),
      decision: {
        active: bool(bpd?.active),
        intentionalUntil: str(bpd?.intentional_until),
        actor: str(bpd?.actor),
        receipt: str(bpd?.receipt),
        history: Array.isArray(bpd?.history) ? bpd!.history.length : 0,
      },
    }
  })

  const dh = rec(ctx.budget_presentation_decisions)
  const decisionHistory = {
    complete: typeof dh?.complete === 'boolean' ? (dh!.complete as boolean) : null,
    count: num(dh?.items) ?? num(dh?.count),
    history: Array.isArray(dh?.history) ? dh!.history.length : 0,
  }

  const blockState = str(ctx.state)?.toLowerCase() ?? null
  return {
    present: true,
    state: blockState,
    unavailable: blockState === 'unavailable',
    blockReason: str(ctx.reason),
    blockRemediation: remediationText(ctx.remediation),
    symbols, positions, risk, hedge, budgets, decisionHistory, gaps, readErrors,
  }
}

// ── Display lines ────────────────────────────────────────────────────────────────────────────────────────────────
// Pure string builders, so the rules below are unit-tested rather than only rendered. Every value-bearing line goes
// through `stateText`: a fact the parser marked unknown/partial/not_applicable must never print a normal-looking value.

export function stateText(f: Fact): string | null {
  if (f.state === 'measured') return null
  if (f.state === 'not_applicable') return 'not applicable'
  const bits = [f.reason, f.remediation].filter(Boolean).join(' · ')
  return `${f.state === 'partial' ? 'partial' : 'unknown'}${bits ? ` — ${bits}` : ''}`
}

/** A fact's own clock, source and any declared staleness, as plain text. Empty when the payload supplied none. */
export function provenanceText(f: { asOf: string | null; source: string | null; stale?: boolean; ageSeconds?: number | null }): string {
  const clock = f.asOf ? ` · ${fmtAsOf(f.asOf) ?? f.asOf}` : ''
  const stale = f.stale ? ` · stale${f.ageSeconds != null ? ` (${Math.round(f.ageSeconds / 60)}m)` : ''}` : ''
  return `${clock}${f.source ? ` · ${f.source}` : ''}${stale}`
}

const money = (v: number | null) => (v == null ? null : `$${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}`)
const pct = (v: number | null) => (v == null ? null : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)

export function referenceLine(r: SymbolContext['references'][number]): string {
  const state = stateText(r)
  if (state) return `to trigger ${r.label} ${state}${provenanceText(r)}`
  return `to trigger ${r.label} ${r.distancePct != null ? pct(r.distancePct) : ''}${r.distanceUsd != null ? ` (${money(r.distanceUsd)})` : ''}${provenanceText(r)}`
}

export function nextEventLine(ne: SymbolContext['nextEvent']): string | null {
  const state = stateText(ne)
  if (state) return `next event ${state}${provenanceText(ne)}`
  if (!ne.label && !ne.at) return null
  return `next event ${ne.label ?? ''}${ne.at ? ` · ${fmtAsOf(ne.at) ?? ne.at}` : ''}${provenanceText(ne)}`
}

export function marketStanceLine(st: SymbolContext['marketStance']): string | null {
  const state = stateText(st)
  if (state) return `market-risk stance ${state}${provenanceText(st)}`
  if (!st.value) return null
  return `market-risk stance ${st.value} (separate from CIO)${provenanceText(st)}`
}

export function volumeLine(v: SymbolContext['volume']): string {
  const state = stateText(v)
  if (state) return `volume ${state}${provenanceText(v)}`
  return `volume ${v.ratio ?? 'unknown'}× 20-day${v.basis ? ` · ${v.basis}` : ''}${provenanceText(v)}`
}

export function headlineLine(h: SymbolContext['headlines'][number]): string {
  return `${h.title}${h.publishedAt ? ` · ${fmtAsOf(h.publishedAt) ?? h.publishedAt}` : ''}`
}

export function hedgeLine(t: HomeV007['hedge']['triggers'][number]): string {
  // The trigger is a fact like every other: unknown or stale must say so instead of printing numbers as current.
  const state = stateText(t)
  if (state) return `${t.label} ${state}${provenanceText(t)}`
  return `${t.label} ${t.current ?? '?'} of ${t.threshold ?? '?'}${t.unit ? ` ${t.unit}` : ''}${t.group ? ` · ${t.group}` : ''}${provenanceText(t)}`
}

/** The two observations that disagreed, when the producer recorded a same-instant conflict on the quote. */
export function conflictLine(q: QuoteLine): string | null {
  if (!q.conflict) return null
  const marks = q.conflict.marks
    .map(m => `${money(m.price) ?? 'unknown'}${m.source ? ` (${m.source})` : ''}`)
    .join(' vs ')
  return `conflicting observations${marks ? `: ${marks}` : ''}${q.conflict.reason ? ` — ${q.conflict.reason}` : ''}`
}

/** A category chip: the word, and — for a carried or unknown one — the producer's reason, which carries "carried". */
export function categoryLine(c: HomeV007['risk']['categories'][number]): string {
  const word = c.chip ?? c.state
  if (c.state !== 'measured' && c.reason) return `${c.label} ${word} — ${c.reason}`
  return `${c.label} ${word}${c.carried ? ' · carried across a closure' : ''}`
}
