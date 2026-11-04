// One row of the Intelligence page's "Decision implications" panel (FQ-040).
//
// The audit's phone capture showed the panel as a wall: the whole report thesis expanded at 9–11 px, next to raw source
// identifiers and estimated-error metadata. The operator could not see, in one glance, what the conclusion was, how
// sure the source is, or what to do next.
//
// The row is now three visible facts and one optional expansion:
//   conclusion   — the ledger's own action, or the first sentence of its thesis. Never generated.
//   uncertainty  — confidence and age, or the words "not recorded" when the source did not say.
//   next step    — the page's existing next-step sentence, passed in, never re-derived here.
//   expanded     — the whole thesis, the summary and the raw identifiers (model, lane, source, type), on demand.
export type ImplicationSource = {
  id: string; source: string; type: string; symbol?: string | null
  title: string; summary?: string | null; action?: string | null
  confidence?: number | null; freshnessH?: number | null
  model?: string | null; lane?: string | null
}

export type ImplicationModel = {
  /** the action, in the ledger's words, or the first sentence of the thesis */
  conclusion: string
  /** where the conclusion came from, so a reader can tell an action from a summary */
  conclusionKind: 'action' | 'thesis'
  /** every field that is machine vocabulary; empty when the source gave none */
  identifiers: Array<[string, string]>
  /** confidence and age, or an explicit "not recorded" */
  uncertainty: string
  nextStep: string
  /** the full thesis — what the row shows expanded, never truncated in the data */
  headline: string
  summary: string | null
}

const clean = (v: unknown) => String(v ?? '').replace(/\s+/g, ' ').trim()

/** The first sentence, and only the first: a sentence the source actually wrote. */
export function firstSentence(text: string | null | undefined): string {
  const s = clean(text)
  if (!s) return ''
  const m = /^(.+?[.!?])(\s|$)/.exec(s)
  return m ? m[1] : s
}

function ageWords(hours: number | null | undefined): string {
  if (hours == null || !Number.isFinite(hours)) return 'age not recorded'
  if (hours < 1) return 'just now'
  if (hours < 48) return `${Math.round(hours)} h old`
  return `${Math.round(hours / 24)} d old`
}

export function uncertaintyText(c: number | null | undefined, freshnessH: number | null | undefined): string {
  const n = typeof c === 'number' && Number.isFinite(c) ? c : null
  // A confidence outside 0..1 is not a percentage we may rescale silently: say it is not recorded instead.
  const conf = n == null || n < 0 || n > 1 ? 'confidence not recorded' : `${Math.round(n * 100)}% confidence`
  return `${conf} · ${ageWords(freshnessH)}`
}

export function implicationModel(it: ImplicationSource, nextStep: string): ImplicationModel {
  const action = clean(it.action)
  const first = firstSentence(it.title)
  const identifiers: Array<[string, string]> = []
  if (clean(it.model)) identifiers.push(['Model', clean(it.model)])
  if (clean(it.lane)) identifiers.push(['Lane', clean(it.lane)])
  if (clean(it.source)) identifiers.push(['Source', clean(it.source)])
  if (clean(it.type)) identifiers.push(['Type', clean(it.type)])
  return {
    conclusion: action || first || 'The source gave no conclusion.',
    conclusionKind: action ? 'action' : 'thesis',
    identifiers,
    uncertainty: uncertaintyText(it.confidence, it.freshnessH),
    nextStep: clean(nextStep),
    headline: clean(it.title) || 'The source gave no title.',
    summary: clean(it.summary) || null,
  }
}

/** "NVDA: earnings in two days" — the symbol is a label, never parsed out of the sentence. */
export function rowTitle(m: ImplicationModel, symbol?: string | null): string {
  const s = clean(symbol)
  return s ? `${s}: ${m.conclusion}` : m.conclusion
}
