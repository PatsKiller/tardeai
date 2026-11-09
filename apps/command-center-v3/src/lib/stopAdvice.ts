/** LQ-20261107-1253 amendment 4 — the "Your actions" list. Pure: the CIO brief's stop_advice[] (LQ-1257, cc-deepseek-3)
 *  plus the card's quotes in, numbered action rows out. The CIO owns every verdict; this only formats it and does the
 *  dollar arithmetic the operator asked for. Advisory only: nothing here places, sizes or edits an order. */

export type StopKind = 'ADD_STOP' | 'RAISE' | 'FIX_QTY' | 'HOLD' | 'NO_ACTION'
export type Tone = 'danger' | 'success' | 'warning'

export interface StopRow {
  n: number; symbol: string; account: string | null; kind: StopKind; urgent: boolean; verb: string
  order: { qty: number | null; stop: number | null; oldStop: number | null; gtc: boolean } | null
  consequence: { text: string; tone: Tone; usd: number } | null
  worstCase: number | null
  reason: string | null; what: string | null
  /** LQ-1311: the working stop and last price, kept for HOLD rows too (they explain why nothing moves). */
  stopNow: number | null; last: number | null
  qa: { question: string | null; answer: string | null; correction: string | null } | null
}
export interface StopList { actions: StopRow[]; quiet: StopRow[]; header: string; rule: string }

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

export function stopList(
  raw: unknown, quotes: Record<string, { price: number } | undefined>, heldQty: Record<string, number | undefined> = {},
): StopList {
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
      reason: str(pick(o, ['why', 'reason', 'rationale'])), what: str(pick(o, ['what_happened', 'what', 'headline', 'event_summary'])),
      stopNow: oldStop, last,
      qa: q || a || c ? { question: q, answer: a, correction: c } : null,
    })
  }
  rows.sort((p, q) => RANK[p.kind] - RANK[q.kind] || (q.consequence?.usd ?? 0) - (p.consequence?.usd ?? 0) || p.symbol.localeCompare(q.symbol))
  const actions = rows.filter(r => r.kind === 'ADD_STOP' || r.kind === 'RAISE' || r.kind === 'FIX_QTY').map((r, i) => ({ ...r, n: i + 1 }))
  const quiet = rows.filter(r => r.kind === 'HOLD' || r.kind === 'NO_ACTION')
  return { actions, quiet, header: `Your actions · ${actions.length} stop change${actions.length === 1 ? '' : 's'} at Schwab`, rule: STOP_RULE }
}
