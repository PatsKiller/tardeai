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
    /** The clock of the row the score came from; the score is a measurement like any other and shows its own. */
    scoreAsOf: string | null
    categories: Array<{ key: string; label: string; chip: string | null; state: FactState; asOf: string | null; source: string | null; reason: string | null; carried: boolean }>
    nextEvaluation: { at: string | null; basis: string | null } | null
  }
  hedge: { triggers: Array<{ label: string; current: number | null; threshold: number | null; unit: string | null; group: string | null } & Fact>; inverse: Array<{ symbol: string; dayPct: number | null; state: FactState }> }
  budgets: BudgetRow[]
  /** Top-level decision ledger. ``complete: false`` means the per-row history counts are partial. */
  decisionHistory: { complete: boolean | null; count: number | null; history: number }
  gaps: Array<{ member: string; key: string; reason: string | null; remediation: string | null; symbol?: string | null; field?: string | null }>
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

/** The same rule for a fact whose value is text: a measured CIO/stance with no word is not a measurement. */
function measuredNeedsText<T extends Fact>(f: T, text: string | null): T {
  if (f.state !== 'measured' || text) return f
  return { ...f, state: 'unknown', reason: f.reason ?? 'measured claim carried no value' }
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
  const priced = noValueIsUnknown(line, [line.price])
  // And a price with no observation clock is a number nobody can date: unknown, with the clock as the reason.
  if (priced.state === 'measured' && !priced.asOf) {
    return { ...priced, state: 'unknown', reason: 'the quote carries no observation clock, so its price cannot be dated', price: null }
  }
  return priced
}

/** Inverse-fund moves arrive two ways: the producer's {symbol: symbol-context} map, or an array of move facts. */
function inverseMoves(raw: unknown): Array<{ symbol: string; dayPct: number | null; state: FactState }> {
  const map = rec(raw)
  if (map && !Array.isArray(map.value)) {
    return Object.entries(map).slice(0, 12).map(([symbol, v]) => {
      const o = rec(v) ?? {}
      const day = rec(o.day_change)
      // The MOVE's own fact decides whether its number may print; a quote in a different state says nothing about it.
      const dayFact = fact(day ?? rec(o.quote) ?? o)
      return { symbol, dayPct: dayFact.state === 'measured' ? (num(rec(day?.value)?.pct) ?? num(day?.value)) : null, state: dayFact.state }
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
  if (!ctx) return { present: false, state: null, unavailable: false, blockReason: null, blockRemediation: null, symbols: [], positions: [], risk: { score: null, scoreAsOf: null, categories: [], nextEvaluation: null }, hedge: { triggers: [], inverse: [] }, budgets: [], decisionHistory: { complete: null, count: null, history: 0 }, gaps: [{ member: 'home_v007', key: 'absent', reason: 'the response carries no home_v007 block', remediation: 'wait for the additive reader' }], readErrors }

  for (const g of (Array.isArray(ctx.gaps) ? ctx.gaps : [])) {
    const o = rec(g); if (o) gaps.push({ member: [str(o.symbol), str(o.field)].filter(Boolean).join('.') || '?', key: remediationText(o.remediation) ?? '?', reason: str(o.reason), remediation: remediationText(o.remediation), symbol: str(o.symbol), field: str(o.field) })
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
      cio: measuredNeedsText({ ...fact(cioRaw), stance: str(cioVal?.stance), conviction: num(cioVal?.conviction) ?? str(cioVal?.conviction) ?? num(rec(s.conviction)?.value), stale: bool(cioVal?.stale) || bool(cioRaw?.stale) }, str(cioVal?.stance)),
      marketStance: measuredNeedsText({ ...fact(st), value: str(stVal?.stance), headline: str(stVal?.headline) } as SymbolContext['marketStance'], str(stVal?.stance)),
      volume: { ...fact(vol), ratio: num(volVal?.ratio), basis: str(volVal?.basis), sampleSessions: num(volVal?.sample_sessions), averageStartDate: str(volVal?.average_start_date), averageEndDate: str(volVal?.average_end_date) },
    }
  })

  const positions = (Array.isArray(ctx.positions) ? ctx.positions : []).filter(rec).slice(0, 60).map(p => {
    const o = rec(p) as Record<string, unknown>
    const sd = rec(o.stop) ?? rec(o.stop_distance)  // the producer names the fact `stop`
    return { symbol: str(o.symbol) ?? '?', account: str(o.account_label), pctAccount: num(o.pct_account) ?? num(o.account_pct_basis), denominator: str(o.pct_denominator) ?? str(o.account_pct_basis), stopDistancePct: num(sd?.pct) ?? num(rec(sd?.value)?.distance_pct_of_price), stopState: str(o.stored_stop_state) ?? str(rec(sd?.value)?.status) }
  })

  const riskRaw = rec(ctx.risk) ?? {}
  // The producer carries the score (and its clock) on the latest history row, not at the top level.
  const riskHistory = Array.isArray(riskRaw.history) ? riskRaw.history.filter(rec) as Record<string, unknown>[] : []
  const lastScore = riskHistory.length ? riskHistory[riskHistory.length - 1] : null
  const risk = {
    score: num(riskRaw.score) ?? num(lastScore?.score),
    scoreAsOf: str(riskRaw.as_of) ?? str(lastScore?.as_of),
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
    const stated = typeof o.state === 'string' ? fact(o) : fact({
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
    // A producer-stated "measured" row still needs a clock: an amount nobody can date is not a measurement, whatever
    // the state word says (cc2 whole-head review, 2026-11-03). The unknown row keeps its reason for the reader.
    const produced = stated.state === 'measured' && !stated.asOf
      ? { ...stated, state: 'unknown' as FactState, reason: 'measured with no observation clock, so the amount cannot be dated' }
      : stated
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
    // E's `items` is a LIST of decisions; a numeric `items` (and `count`) are legacy spellings. Reading only the
    // numeric forms made this null on every real payload, so the "N in the ledger" line could never render.
    count: num(dh?.items) ?? num(dh?.count) ?? (Array.isArray(dh?.items) ? dh!.items.length : null),
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


/** Plain names for the producer's per-symbol gap fields; anything else falls back to its own key, underscores spaced. */
const GAP_FIELD_LABEL: Record<string, string> = {
  quote: 'Price', day_change: 'Day change', since_exit: 'Since exit', since_exit_history: 'Since-exit history',
  cio: 'CIO stance', market_stance: 'Market-risk stance', volume: 'Volume', next_event: 'Next event',
  references: 'Trigger references', headlines: 'Headlines', home_v007: 'Your names today',
}
export function gapFieldLabel(field: string | null | undefined): string {
  if (!field) return 'Unnamed field'
  const [head, ...rest] = field.split('.')
  const t = head.replace(/_/g, ' ')
  const name = GAP_FIELD_LABEL[head] ?? t.charAt(0).toUpperCase() + t.slice(1)
  return [name, ...rest.map(r => r.replace(/_/g, ' '))].join(' · ')
}

export type GapGroup = {
  field: string | null; label: string; reason: string | null; remediation: string | null
  /** Every symbol in the group, in payload order; a symbol-less gap is counted but not named. */
  symbols: string[]; count: number; text: string
}

/** LIVEFIX-R (operator 2026-11-06): ~150 "gap SYMBOL.field · …" lines become one line per identical
 *  (field, reason, remediation): "CIO stance unavailable for 17 symbols: A, B, … — <reason>". Nothing is dropped:
 *  every symbol is named and the remediation is shown once per group. Groups keep first-seen order. */
export function groupGaps(gaps: HomeV007['gaps']): GapGroup[] {
  const groups = new Map<string, GapGroup>()
  for (const g of gaps) {
    const field = g.field ?? (g.symbol ? null : g.member)
    const k = JSON.stringify([field, g.reason, g.remediation])
    let grp = groups.get(k)
    if (!grp) { grp = { field, label: gapFieldLabel(field), reason: g.reason, remediation: g.remediation, symbols: [], count: 0, text: '' }; groups.set(k, grp) }
    grp.count += 1
    if (g.symbol && !grp.symbols.includes(g.symbol)) grp.symbols.push(g.symbol)
  }
  for (const grp of groups.values()) {
    const n = grp.symbols.length
    const who = n ? ` for ${n} symbol${n === 1 ? '' : 's'}: ${grp.symbols.join(', ')}` : ''
    grp.text = `${grp.label} unavailable${who}${grp.reason ? ` — ${grp.reason}` : ''}`
  }
  return [...groups.values()]
}

/** The compact one-line state of a fact for the per-symbol row: its value, or "not measured" — never a blank. */
export function compactPct(f: Fact & { pct: number | null }): string {
  if (f.state === 'not_applicable') return 'n/a'
  if (f.state !== 'measured' || f.pct == null) return 'not measured'
  return `${f.pct > 0 ? '+' : ''}${f.pct.toFixed(2)}%${f.stale ? ' (stale)' : ''}`
}

// ── v008 "Your names today" (operator-approved mockup home/v008 HomeTodaysContextActionable, 2026-11-06) ──────────
// The flat A–Z symbol list is replaced by three groups, each opening with its takeaway: today's stop-outs, held names
// in stressed groups, and older exits on watch. Facts and links only: no order, size, stop level or buy/sell word.
// Every value still comes from a measured fact; an unmeasured price says NO PRICE and why, never a bare "not measured".

/** Where Risk › Recovery lives (RecoveryViews' list path); `&case=<key>` selects one case. */
export const RECOVERY_LIST_PATH = '/risk?tab=Recovery'
/** The Protect card's generic stop review, used when a held name carries no item-level link. */
export const STOP_REVIEW_PATH = '/risk?tab=exposure'
/** Positions under this value fold into one footnote line (approved mockup: "leftover positions under $100"). */
export const TINY_POSITION_USD = 100
/** An earnings date this many trading days away or fewer is flagged on an older exit (approved mockup). */
export const EARNINGS_FLAG_TRADING_DAYS = 5

export type NamesSource = {
  reentry: Array<{ symbol: string; exitDate: string | null; exitPrice: number | null; quotePrice: number | null; quoteAsOf: string | null; quoteReason: string | null; pctVsExit: number | null; stagesMeasured: boolean; stagesNote: string | null; exitAccount: string | null; heldElsewhere: string[] }>
  holdings: Array<{ symbol: string; account: string | null; valueUsd: number; pctAccount: number | null; stopDistancePct: number | null; stance: string | null }>
  /** true = the stop read answered (a missing stop is "no stop"); false/null = stops unread ("stop unknown"). */
  stopsKnown: boolean | null
  reviewLinks: Array<{ symbol: string; to: string }>
  /** The inverse/hedge lane: these belong to the Hedge card and never appear here. */
  inverse: string[]
}

/** Read the sibling fields of the same /api/v2/market-risk/latest response. Absent fields are empty, never invented. */
export function namesSource(resp: unknown): NamesSource {
  const top = rec(resp)
  const d = top && rec(top.data) && !('home_v007' in top) ? rec(top.data)! : (top ?? {})
  const watch = rec(d.reentry_watch) ?? {}
  const detail = rec(d.reentry_detail) ?? {}
  const reentry = Object.entries(watch).filter(([k]) => !k.startsWith('_')).map(([symbol, v]) => {
    const c = rec(v) ?? {}
    const cq = rec(c.current_quote)
    const st = rec(c.stages)
    const det = rec(detail[symbol]) ?? {}
    const s1 = rec(st?.stage1)
    return {
      symbol: symbol.toUpperCase(),
      exitDate: str(c.exit_date)?.slice(0, 10) ?? null,
      exitPrice: num(c.exit_price) ?? num(st?.exit_price),
      quotePrice: num(cq?.price),
      quoteAsOf: str(cq?.as_of),
      quoteReason: str(cq?.reason),
      pctVsExit: num(cq?.pct_vs_exit) ?? num(st?.pct_vs_exit),
      stagesMeasured: !!s1 && num(s1.of) != null && num(s1.of)! > 0 && !str(st?.note),
      stagesNote: str(st?.note),
      exitAccount: str(det.exit_account_label),
      heldElsewhere: Array.isArray(det.held_elsewhere_labels) ? det.held_elsewhere_labels.filter((x): x is string => typeof x === 'string' && !!x) : [],
    }
  })
  const be = rec(d.book_exposure)
  const holdings = (Array.isArray(be?.rows) ? be!.rows : []).filter(rec).map(r => {
    const o = r as Record<string, unknown>
    return { symbol: (str(o.symbol) ?? '?').toUpperCase(), account: str(o.account_label), valueUsd: num(o.value_usd) ?? 0,
      pctAccount: num(o.pct_account), stopDistancePct: num(o.stop_distance_pct), stance: str(o.stance) }
  })
  const links: NamesSource['reviewLinks'] = []
  const prot = rec(d.protect)
  for (const it of [...(Array.isArray(prot?.items) ? prot!.items : []), ...(Array.isArray(prot?.more) ? prot!.more : []), ...(Array.isArray(d.review) ? d.review : [])]) {
    const o = rec(it); const sym = str(o?.symbol); const to = str(o?.to)
    if (sym && to && !links.some(l => l.symbol === sym.toUpperCase())) links.push({ symbol: sym.toUpperCase(), to })
  }
  const hedge = rec(d.hedge)
  const inverse = [
    ...(Array.isArray(hedge?.candidates) ? hedge!.candidates : []),
    str(rec(hedge?.entry)?.inverse),
  ].filter((x): x is string => typeof x === 'string' && !!x).map(x => x.toUpperCase())
  return { reentry, holdings, stopsKnown: typeof be?.stops_known === 'boolean' ? be.stops_known as boolean : null, reviewLinks: links, inverse }
}

export type RecoveryCaseRef = { key: string; symbol: string; account: string | null; settled: boolean }

export type ExitStatus = 'above' | 'below' | 'no_price'
export type StoppedRow = {
  symbol: string; account: string; status: ExitStatus; pill: string
  /** Why there is no price, and the last price time when one exists. Only for NO PRICE. */
  noPriceWhy: string | null
  vsExitPct: number | null; exitPrice: number | null; price: number | null; dayPct: number | null
  event: string | null; why: string | null; caseTo: string | null; askText: string
}
export type HeldRow = {
  symbol: string; accountText: string; valueUsd: number; pill: string; price: number | null; dayPct: number | null
  event: string | null; stopFacts: string[]; needsStopLook: boolean; reviewTo: string; askText: string
}
export type OlderRow = { symbol: string; vsExitPct: number | null; dayPct: number | null; flag: string | null; flagged: boolean }
export type NamesToday = {
  stoppedHeading: string; stoppedTakeaway: string; stopped: StoppedRow[]
  held: HeldRow[]; heldTakeaway: string; tiny: Array<{ symbol: string; usd: number }>
  older: OlderRow[]; olderTakeaway: string
  cioGap: { missing: number; total: number; reason: string | null } | null
  total: number
}

const DAY_MS = 86_400_000
const isoDay = (iso: string): number => Date.parse(`${iso.slice(0, 10)}T12:00:00Z`)
const weekday = (t: number) => { const w = new Date(t).getUTCDay(); return w !== 0 && w !== 6 }
/** The latest weekday on or before the ET date (holidays are not modelled; the label then names the date). */
function lastSessionDate(todayEt: string): string {
  let t = isoDay(todayEt)
  while (!weekday(t)) t -= DAY_MS
  return new Date(t).toISOString().slice(0, 10)
}
/** Trading days from `from` (exclusive) to `to` (inclusive); negative when `to` is before `from`. */
export function tradingDaysUntil(from: string, to: string): number {
  const a = isoDay(from), b = isoDay(to)
  if (!Number.isFinite(a) || !Number.isFinite(b)) return Number.NaN
  if (b < a) return -1
  let n = 0
  for (let t = a + DAY_MS; t <= b; t += DAY_MS) if (weekday(t)) n++
  return n
}
const MONTH = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const monDay = (iso: string) => { const t = new Date(isoDay(iso)); return `${MONTH[t.getUTCMonth()]} ${t.getUTCDate()}` }
const dayLabel = (iso: string) => { const t = new Date(isoDay(iso)); return `${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][t.getUTCDay()]} ${String(t.getUTCMonth() + 1).padStart(2, '0')}-${String(t.getUTCDate()).padStart(2, '0')}` }
export const signedPct1 = (v: number | null): string => v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}%`
const usd0 = (v: number) => `$${Math.round(v).toLocaleString('en-US')}`
const words = (s: string) => s.replace(/_/g, ' ').toLowerCase()

/** EXIT / TRIM from either spelling ("EXIT", "exit review", "trim_review"); anything else is not a stressed stance. */
export function stressedStance(raw: string | null | undefined): 'EXIT' | 'TRIM' | null {
  const s = String(raw ?? '').toUpperCase().replace(/[\s-]+/g, '_').replace(/_REVIEW$/, '')
  return s === 'EXIT' || s === 'TRIM' ? s : null
}

/** The measured next event as "earnings Jan 26"; null when unmeasured or past. */
function eventFact(s: SymbolContext | undefined, todayEt: string): { text: string; date: string; label: string } | null {
  const ne = s?.nextEvent
  if (!ne || ne.state !== 'measured' || !ne.at) return null
  const date = ne.at.slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || date < todayEt) return null
  const label = words(ne.label ?? 'event')
  return { text: `${label} ${monDay(date)}`, date, label }
}

export function askCioText(symbol: string): string { return `What is your view on ${symbol} today?` }

export function caseLink(symbol: string, account: string | null, cases: RecoveryCaseRef[]): string | null {
  const open = cases.filter(c => c.symbol === symbol && !c.settled)
  if (!open.length) return null
  const pick = open.find(c => account && c.account === account) ?? open[0]
  return `${RECOVERY_LIST_PATH}&case=${encodeURIComponent(pick.key)}`
}

/** Build the three groups. Pure: `now` and every input are arguments, so the rules are unit-tested. */
export function namesToday(v7: HomeV007, src: NamesSource, cases: RecoveryCaseRef[], now: Date): NamesToday {
  const todayEt = etDate(now.toISOString()) ?? now.toISOString().slice(0, 10)
  const session = lastSessionDate(todayEt)
  const ctx = new Map(v7.symbols.map(s => [s.symbol.toUpperCase(), s]))
  const inverse = new Set([...src.inverse, ...v7.hedge.inverse.map(i => i.symbol.toUpperCase())])
  const priceOf = (s: SymbolContext | undefined) => s && s.quote.state === 'measured' ? s.quote.price : null
  const dayOf = (s: SymbolContext | undefined) => s && s.dayChange.state === 'measured' ? s.dayChange.pct : null
  const vsExitOf = (r: NamesSource['reentry'][number], s: SymbolContext | undefined): number | null => {
    if (s) return s.sinceExit.state === 'measured' && s.quote.state === 'measured' ? s.sinceExit.pct : null
    return r.quotePrice != null ? r.pctVsExit : null
  }

  // 1. Stopped out in the latest session.
  const watch = src.reentry.filter(r => !inverse.has(r.symbol))
  const recent = watch.filter(r => r.exitDate && r.exitDate >= session)
  const stopped: StoppedRow[] = recent.map(r => {
    const s = ctx.get(r.symbol)
    const vs = vsExitOf(r, s)
    const price = s ? priceOf(s) : r.quotePrice
    const status: ExitStatus = vs == null ? 'no_price' : vs >= 0 ? 'above' : 'below'
    const lastAt = s?.quote.asOf ?? r.quoteAsOf
    const noPriceWhy = status === 'no_price'
      ? `${(s ? (s.quote.state !== 'measured' ? s.quote.reason : s.sinceExit.reason) : r.quoteReason) ?? 'no current quote was measured for this name'}${lastAt ? ` · last price time ${fmtAsOf(lastAt) ?? lastAt}` : ' · no earlier price on record'}`
      : null
    let why: string | null
    if (status === 'below') why = 'The stop did its job'
    else {
      const bits: string[] = []
      if (s?.cio.state === 'measured' && s.cio.stance) bits.push(`CIO ${s.cio.stance.toUpperCase()}${s.cio.conviction != null ? ` · ${s.cio.conviction}` : ''}`)
      if (s?.marketStance.state === 'measured' && s.marketStance.value) bits.push(`market-risk ${words(s.marketStance.value)}`)
      if (!r.stagesMeasured) bits.push(r.exitDate === todayEt ? 'first re-entry check after tonight’s close' : (r.stagesNote ?? 'no re-entry check measured yet'))
      why = bits.length ? bits.join(' · ') : null
    }
    const held = r.heldElsewhere.filter(h => h !== r.exitAccount)
    const account = `${r.exitAccount ?? 'account not recorded'}${held.length ? ` · still held in ${held.join(', ')}` : ''}`
    return {
      symbol: r.symbol, account, status, noPriceWhy, vsExitPct: vs, exitPrice: r.exitPrice, price, dayPct: dayOf(s),
      pill: status === 'no_price' ? 'NO PRICE' : `${status === 'above' ? 'ABOVE' : 'BELOW'} EXIT ${signedPct1(vs)}`,
      event: eventFact(s, todayEt)?.text ?? null, why,
      caseTo: status === 'below' ? null : (caseLink(r.symbol, r.exitAccount, cases) ?? RECOVERY_LIST_PATH),
      askText: askCioText(r.symbol),
    }
  }).sort((a, b) => (a.status === 'above' ? 0 : a.status === 'no_price' ? 1 : 2) - (b.status === 'above' ? 0 : b.status === 'no_price' ? 1 : 2) || (b.vsExitPct ?? 0) - (a.vsExitPct ?? 0))
  const priced = stopped.filter(r => r.status !== 'no_price')
  const above = stopped.filter(r => r.status === 'above').length
  const stoppedTakeaway = !stopped.length ? 'none'
    : `${above} of ${priced.length} now above your exit${priced.length < stopped.length ? ` · ${stopped.length - priced.length} without a price` : ''}`
  const stoppedHeading = session === todayEt ? 'Stopped out today' : `Stopped out ${dayLabel(session)}`
  const stoppedSyms = new Set(stopped.map(r => r.symbol))

  // 2. Held names in stressed groups.
  const bySym = new Map<string, NamesSource['holdings']>()
  for (const h of src.holdings) {
    if (inverse.has(h.symbol) || stoppedSyms.has(h.symbol) || h.valueUsd <= 0) continue
    const s = ctx.get(h.symbol)
    const stance = stressedStance(h.stance) ?? stressedStance(s?.marketStance.state === 'measured' ? s.marketStance.value : null)
    if (!stance) continue
    bySym.set(h.symbol, [...(bySym.get(h.symbol) ?? []), h])
  }
  const held: HeldRow[] = []
  const tiny: NamesToday['tiny'] = []
  for (const [symbol, rows] of bySym) {
    const total = rows.reduce((n, r) => n + r.valueUsd, 0)
    if (total < TINY_POSITION_USD) { tiny.push({ symbol, usd: total }); continue }
    const s = ctx.get(symbol)
    const stance = rows.map(r => stressedStance(r.stance)).find(Boolean) ?? stressedStance(s?.marketStance.value) ?? 'EXIT'
    const multi = rows.length > 1
    const stopFacts = rows.map(r => {
      const who = multi ? `${r.account ?? 'account'} ` : ''
      if (r.stopDistancePct != null) return `${who}stop ${Math.abs(r.stopDistancePct).toFixed(1)}% ${r.stopDistancePct >= 0 ? 'below' : 'above'}`
      if (src.stopsKnown === true) return `${who}no stop on ${usd0(r.valueUsd)}${r.pctAccount != null ? ` (${r.pctAccount.toFixed(1)}% of that account)` : ''}`
      return `${who}stop unknown (stops not read)`
    })
    held.push({
      symbol, valueUsd: total, pill: `MARKET-RISK ${stance}`,
      accountText: `${multi ? `${rows.length} accounts` : rows[0].account ?? 'account'} · ${usd0(total)}`,
      price: priceOf(s), dayPct: dayOf(s), event: eventFact(s, todayEt)?.text ?? null, stopFacts,
      needsStopLook: rows.some(r => r.stopDistancePct == null),
      reviewTo: src.reviewLinks.find(l => l.symbol === symbol)?.to ?? STOP_REVIEW_PATH,
      askText: askCioText(symbol),
    })
  }
  held.sort((a, b) => b.valueUsd - a.valueUsd)
  tiny.sort((a, b) => b.usd - a.usd)
  const noStop = held.filter(h => h.needsStopLook).length
  const heldTakeaway = !held.length ? 'none' : `${held.length} held${noStop ? ` · ${noStop} with an account not covered by a stop` : ''}`

  // 3. Older exits on watch: closest to the exit first; unknown distance last.
  const older: OlderRow[] = watch.filter(r => !stoppedSyms.has(r.symbol)).map(r => {
    const s = ctx.get(r.symbol)
    const vs = vsExitOf(r, s)
    const ev = eventFact(s, todayEt)
    const soon = ev && /earn/.test(ev.label) && tradingDaysUntil(todayEt, ev.date) <= EARNINGS_FLAG_TRADING_DAYS ? `${ev.label} ${dayLabel(ev.date)}` : null
    const flag = soon ?? (vs != null && vs >= 0 ? 'above exit' : vs == null ? 'no price' : null)
    return { symbol: r.symbol, vsExitPct: vs, dayPct: dayOf(s), flag, flagged: !!soon || (vs != null && vs >= 0) }
  }).sort((a, b) => (a.vsExitPct == null ? 1 : 0) - (b.vsExitPct == null ? 1 : 0) || Math.abs(a.vsExitPct ?? 0) - Math.abs(b.vsExitPct ?? 0))
  const aboveOld = older.filter(o => o.vsExitPct != null && o.vsExitPct >= 0).length
  const soonOld = older.filter(o => o.flag && /^earn/.test(o.flag)).length
  const olderTakeaway = [aboveOld ? `${aboveOld} above exit` : null, soonOld ? `${soonOld} with earnings within ${EARNINGS_FLAG_TRADING_DAYS} trading days` : null].filter(Boolean).join(' · ')

  // One CIO gap line for every name the card shows.
  const shown = [...stopped.map(r => r.symbol), ...held.map(h => h.symbol), ...older.map(o => o.symbol)]
  const missing = shown.filter(sym => ctx.get(sym)?.cio.state !== 'measured')
  const reasons = new Map<string, number>()
  for (const sym of missing) { const r = ctx.get(sym)?.cio.reason ?? (ctx.has(sym) ? null : 'the name is not in the context block'); if (r) reasons.set(r, (reasons.get(r) ?? 0) + 1) }
  const reason = [...reasons.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null
  return {
    stoppedHeading, stoppedTakeaway, stopped, held, heldTakeaway, tiny, older, olderTakeaway,
    cioGap: missing.length ? { missing: missing.length, total: shown.length, reason } : null,
    total: shown.length,
  }
}
