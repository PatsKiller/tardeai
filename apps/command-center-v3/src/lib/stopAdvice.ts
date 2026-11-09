/** LQ-20261107-1253 amendment 4 — the "Your actions" list. Pure: the CIO brief's stop_advice[] (LQ-1257, cc-deepseek-3)
 *  plus the card's quotes in, numbered action rows out. The CIO owns every verdict; this only formats it and does the
 *  dollar arithmetic the operator asked for. Advisory only: nothing here places, sizes or edits an order. */

export type StopKind = 'ADD_STOP' | 'RAISE' | 'FIX_QTY' | 'HOLD' | 'NO_ACTION'
export type Tone = 'danger' | 'success' | 'warning'
/** LQ-20261107-1644: what the newest broker stop read says about this ask. `done` = the book already answers it, so
 *  the row leaves "Your actions"; `open` = still to do; `unread` = the read failed, so the card may claim neither. */
export type StopState = 'done' | 'open' | 'quiet' | 'unread'
export type StopReadStatus = 'read' | 'unread' | 'missing'

/** The stops source's own clock — never the time the card was checked. Written by since_close_card.fetch_stops. */
export interface StopRead {
  status: StopReadStatus
  asOf: string | null
  asOfText: string | null
  checkedAt: string | null
}

/** The broker rows that answer one advice row (see since_close_card._stop_evidence). */
export interface StopEvidence {
  coveredQty: number | null
  bestStop: number | null
  suggestedStop: number | null
  asOf: string | null
  orders: Array<{ stop: number | null; qty: number | null; account: string | null }>
}

export interface StopRow {
  n: number; symbol: string; account: string | null; kind: StopKind; urgent: boolean; verb: string
  order: { qty: number | null; stop: number | null; oldStop: number | null; gtc: boolean } | null
  consequence: { text: string; tone: Tone; usd: number } | null
  worstCase: number | null
  reason: string | null; what: string | null
  /** LQ-1311: the working stop and last price, kept for HOLD rows too (they explain why nothing moves). */
  stopNow: number | null; last: number | null
  qa: { question: string | null; answer: string | null; correction: string | null } | null
  /** LQ-20261107-1644: the reconcile state and the broker rows that produced it. */
  state: StopState; evidence: StopEvidence | null
}
export interface StopList {
  actions: StopRow[]; quiet: StopRow[]
  /** Actionable rows the broker book already answers: shown as placed, never asked again. */
  settled: StopRow[]
  settledLine: string | null
  read: StopRead
  header: string; rule: string
}

export const STOP_RULE = 'a stop moves on price and structure, never on a headline alone; a planned insider sale (10b5-1) counts as neutral.'
const VERB: Record<StopKind, string> = { ADD_STOP: 'ADD A SELL STOP', RAISE: 'EDIT THE STOP', FIX_QTY: 'EDIT THE STOP QUANTITY', HOLD: 'HOLD', NO_ACTION: 'NO ACTION' }
const RANK: Record<StopKind, number> = { ADD_STOP: 0, FIX_QTY: 1, RAISE: 2, HOLD: 3, NO_ACTION: 4 }

const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null)
const num = (v: unknown): number | null => {
  const n = typeof v === 'string' ? Number(v.replace(/[$,]/g, '')) : typeof v === 'number' ? v : NaN
  return Number.isFinite(n) ? n : null
}
const pick = (o: Record<string, unknown>, keys: string[]): unknown => keys.map(k => o[k]).find(v => v !== undefined && v !== null && v !== '')
const usd0 = (n: number) => `$${Math.round(Math.abs(n)).toLocaleString('en-US')}`

/** The CIO's answer word, whatever spelling it uses ("ADD STOP", "add_a_stop", "Raise"), to one of five kinds. */
export function kindOf(v: unknown): StopKind | null {
  const s = (str(v) ?? '').toUpperCase().replace(/[^A-Z0-9]+/g, '_')
  if (!s) return null
  if (/^NO_|NONE|NOTHING/.test(s)) return 'NO_ACTION'
  if (/ADD|NEW_STOP|MISSING|UNPROTECTED/.test(s)) return 'ADD_STOP'
  if (/FIX|QTY|QUANTITY|SHARES/.test(s)) return 'FIX_QTY'
  if (/RAISE|EDIT|TIGHTEN|MOVE|LOCK/.test(s)) return 'RAISE'
  if (/HOLD|KEEP/.test(s)) return 'HOLD'
  return null
}

/** LQ-20261107-1644: the card's stop-read block. A snapshot built before this field existed has none — that is
 *  `missing` (the label says so), never a silent fall back to the card's own check time. */
export function stopReadOf(raw: unknown): StopRead {
  const o = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : null
  const status = str(o?.status)
  const checkedAt = str(o?.checked_at)
  if (status === 'read') return { status: 'read', asOf: str(o?.as_of), asOfText: str(o?.as_of_text), checkedAt }
  if (status === 'unread') return { status: 'unread', asOf: null, asOfText: null, checkedAt }
  return { status: 'missing', asOf: null, asOfText: null, checkedAt: null }
}

function evidenceOf(raw: unknown): StopEvidence | null {
  if (!raw || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  const orders = Array.isArray(o.orders) ? o.orders : []
  return {
    coveredQty: num(o.covered_qty), bestStop: num(o.best_stop), suggestedStop: num(o.suggested_stop), asOf: str(o.as_of),
    orders: orders.flatMap(x => {
      if (!x || typeof x !== 'object') return []
      const r = x as Record<string, unknown>
      return [{ stop: num(r.stop), qty: num(r.qty), account: str(r.account) }]
    }),
  }
}

/** "ANET $174.38 × 200 · SKYD $7.97 × 1,000" — a placed row says which working stop answers it. */
const priceText = (n: number | null) => (n == null ? '—' : `$${n.toFixed(2)}`)
function placedCell(r: StopRow): string {
  const ev = r.evidence
  const stop = ev?.bestStop ?? r.order?.stop ?? null
  const qty = ev?.coveredQty ?? r.order?.qty ?? null
  const q = qty != null && qty > 0 ? ` × ${qty.toLocaleString('en-US')}` : ''
  return `${r.symbol} ${priceText(stop)}${q}`
}

export function stopList(
  raw: unknown, quotes: Record<string, { price: number } | undefined>, heldQty: Record<string, number | undefined> = {},
  stopReadRaw: unknown = null,
): StopList {
  const read = stopReadOf(stopReadRaw)
  const rows: StopRow[] = []
  for (const x of Array.isArray(raw) ? raw : []) {
    if (!x || typeof x !== 'object') continue
    const o = x as Record<string, unknown>
    const symbol = str(pick(o, ['symbol', 'ticker']))?.toUpperCase()
    const kind = kindOf(pick(o, ['answer', 'verdict', 'action', 'recommendation']))
    if (!symbol || !kind) continue
    const last = num(pick(o, ['last', 'price', 'close'])) ?? quotes[symbol]?.price ?? null
    const oldStop = num(pick(o, ['stop_now', 'current_stop', 'stop_current', 'old_stop']))
    const newStop = num(pick(o, ['stop_suggested', 'suggested_stop', 'new_stop', 'stop_new', 'stop']))
    const held = num(pick(o, ['held_qty', 'shares_held', 'position_qty'])) ?? heldQty[symbol] ?? null
    const qty = num(pick(o, ['qty', 'quantity', 'shares', 'suggested_qty'])) ?? held
    const uncovered = num(pick(o, ['uncovered_qty', 'unprotected_qty'])) ?? qty
    let consequence: StopRow['consequence'] = null
    if (kind === 'ADD_STOP' && uncovered != null && last != null) {
      const usd = uncovered * last
      consequence = { text: `${usd0(usd)} has no stop`, tone: 'danger', usd }
    } else if (kind === 'RAISE' && oldStop != null && newStop != null && qty != null && newStop > oldStop) {
      const usd = (newStop - oldStop) * qty
      consequence = { text: `Locks in ${usd0(usd)} of Friday's gain`, tone: 'success', usd }
    } else if (kind === 'FIX_QTY') consequence = { text: 'The stop is for more shares than you hold', tone: 'warning', usd: 0 }
    const stopForWorst = newStop ?? oldStop
    const qa = pick(o, ['qa', 'question_answer']) as Record<string, unknown> | undefined
    const q = str(pick(o, ['question'])) ?? (qa ? str(qa.question) : null)
    const a = str(pick(o, ['short_answer', 'answer_text'])) ?? (qa ? str(qa.answer) : null)
    const c = str(pick(o, ['premise_correction', 'correction'])) ?? (qa ? str(qa.correction) : null)
    rows.push({
      n: 0, symbol, account: str(pick(o, ['account', 'account_name'])), kind, urgent: o.urgent === true || kind === 'ADD_STOP', verb: VERB[kind],
      order: kind === 'HOLD' || kind === 'NO_ACTION' ? null : { qty, stop: newStop, oldStop, gtc: o.gtc !== false },
      consequence, worstCase: last != null && stopForWorst != null && qty != null ? (last - stopForWorst) * qty : null,
      // LQ-20261107-1318: the writer's event lives in `event_summary`; without it a HOLD row carrying a headline
      // rendered as a bare word, which is exactly the event the operator was told to look at. (Live read the field
      // last, behind `what_happened`; a row carrying both states the writer's event, not the alias.)
      reason: str(pick(o, ['why', 'reason', 'rationale'])), what: str(pick(o, ['event_summary', 'what_happened', 'what', 'headline'])),
      stopNow: oldStop, last,
      qa: q || a || c ? { question: q, answer: a, correction: c } : null,
      // LQ-20261107-1644: the writer reconciled each row against the broker stop read. A row with no state (an older
      // snapshot) is OPEN — unverified is not done — and an unread book is `unread`, never `open` the card pretends
      // to have checked.
      state: stopStateOf(o.state, kind, read),
      evidence: evidenceOf(o.stop_evidence),
    })
  }
  rows.sort((p, q) => RANK[p.kind] - RANK[q.kind] || (q.consequence?.usd ?? 0) - (p.consequence?.usd ?? 0) || p.symbol.localeCompare(q.symbol))
  const actionable = rows.filter(r => r.kind === 'ADD_STOP' || r.kind === 'RAISE' || r.kind === 'FIX_QTY')
  const settled = actionable.filter(r => r.state === 'done')
  const actions = actionable.filter(r => r.state !== 'done').map((r, i) => ({ ...r, n: i + 1 }))
  const quiet = rows.filter(r => r.kind === 'HOLD' || r.kind === 'NO_ACTION')
  const header = actions.length
    ? `Your actions · ${actions.length} stop change${actions.length === 1 ? '' : 's'} at Schwab`
    : settled.length ? 'Your actions · every stop change is already placed at Schwab' : 'Your actions · 0 stop changes at Schwab'
  // LQ-20261107-1672: the operator's own words for a satisfied ask. It still names the stop that answers it and the
  // STOP read's clock — never a render time — so the line can be checked against the broker.
  const settledLine = settled.length
    ? `No change needed — done at Schwab${read.asOfText ? ` (${read.asOfText})` : ''}: ${settled.map(placedCell).join(' · ')}`
    : null
  return { actions, quiet, settled, settledLine, read, header, rule: STOP_RULE }
}

function stopStateOf(v: unknown, kind: StopKind, read: StopRead): StopState {
  if (kind === 'HOLD' || kind === 'NO_ACTION') return 'quiet'
  const s = str(v)
  if (s === 'done' || s === 'open' || s === 'unread') return s
  // no reconcile state on the row: an older snapshot, or a caller that did not pass the read. The card says the
  // read was not recorded (read.status === 'missing') and the row stays to do; an unread book says so per row.
  return read.status === 'unread' ? 'unread' : 'open'
}

/** LQ-20261107-1318 — the "no change needed" line. A quiet row that carries an event says the event: "ANET (hold) —
 *  analyst revisions and a planned insider sale", never a bare "hold". Pure, so the shape is testable without a DOM. */
export function quietLine(list: Pick<StopList, 'quiet'>): string | null {
  if (!list.quiet.length) return null
  const cells = list.quiet.map(r => {
    const word = r.kind === 'HOLD' ? 'hold' : 'no action'
    return r.what ? `${r.symbol} (${word}) — ${r.what}` : `${r.symbol} (${word})`
  })
  return `No change needed: ${cells.join(' · ')}`
}
