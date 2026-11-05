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
  /** true when the visible conclusion is a bounded prefix of the source; the whole text is behind the toggle */
  conclusionClamped: boolean
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

/** The visible conclusion is bounded: a very long sentence must not become the wall of text this row replaced. */
export const MAX_CONCLUSION_WORDS = 32
/** A boundary that would leave fewer words than this is a fragment, not a sentence worth showing. */
export const MIN_SENTENCE_WORDS = 3

const wordCount = (s: string) => (s.match(/[^\s]+/g) ?? []).length

function clampToWords(s: string, maxWords = MAX_CONCLUSION_WORDS): string {
  const words = s.split(' ')
  return words.length <= maxWords ? s : words.slice(0, maxWords).join(' ')
}

// Ordinary research-prose abbreviations whose period is not a sentence end. Compared without the final period.
const ABBREVIATIONS = new Set([
  'vs', 'e.g', 'i.e', 'u.s', 'u.k', 'dr', 'mr', 'mrs', 'ms', 'prof', 'inc', 'corp', 'co', 'ltd', 'jr', 'sr',
  'st', 'no', 'approx', 'fig', 'figs', 'al', 'est', 'min', 'max', 'dept', 'gov', 'sen', 'rep', 'gen', 'col',
  'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec',
])

/** True when the period at `i` closes an abbreviation or a single initial rather than a sentence. */
function isAbbreviationAt(s: string, i: number): boolean {
  const m = /([A-Za-z](?:[A-Za-z.]*))\.$/.exec(s.slice(0, i + 1))
  if (!m) return false
  const token = m[1].toLowerCase()
  return ABBREVIATIONS.has(token) || /^[a-z]$/.test(token)
}

type FirstSentenceResult = { text: string; clamped: boolean }

/**
 * The first sentence, and only the first — bounded to MAX_CONCLUSION_WORDS so the row stays one glance.
 * A sentence end must close a word ("3.5" never qualifies), be followed by the start of a new sentence, and
 * not close an abbreviation ("vs.", "U.S.", "e.g.", "Dr."). A boundary that leaves a fragment is refused.
 */
function firstSentenceDetail(text: string | null | undefined): FirstSentenceResult {
  const s = clean(text)
  if (!s) return { text: '', clamped: false }
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]
    if (ch !== '.' && ch !== '!' && ch !== '?') continue
    // A terminator must end a word: whitespace or end-of-string follows ("3.5" is never a sentence end).
    if (i + 1 < s.length && !/\s/.test(s[i + 1])) continue
    // ...and the next sentence must begin (a capital, a digit, or an opening quote), or the text must end.
    const rest = s.slice(i + 1).trimStart()
    if (rest && !/^["'“‘(\[]?[A-Z0-9]/.test(rest)) continue
    // "vs.", "U.S.", "e.g.", "Dr." and "J." do not end the sentence even when a capital follows.
    if (ch === '.' && isAbbreviationAt(s, i)) continue
    const candidate = s.slice(0, i + 1).trim()
    // A boundary that leaves a fragment is not a sentence: fall back to the bounded first words of the source.
    if (wordCount(candidate) < MIN_SENTENCE_WORDS) break
    const bounded = clampToWords(candidate)
    return { text: bounded, clamped: bounded.length < candidate.length }
  }
  const bounded = clampToWords(s)
  return { text: bounded, clamped: bounded.length < s.length }
}

/** The first sentence, and only the first: a sentence the source actually wrote, bounded for the row. */
export function firstSentence(text: string | null | undefined): string {
  return firstSentenceDetail(text).text
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
  const first = firstSentenceDetail(it.title)
  const identifiers: Array<[string, string]> = []
  if (clean(it.model)) identifiers.push(['Model', clean(it.model)])
  if (clean(it.lane)) identifiers.push(['Lane', clean(it.lane)])
  if (clean(it.source)) identifiers.push(['Source', clean(it.source)])
  if (clean(it.type)) identifiers.push(['Type', clean(it.type)])
  return {
    conclusion: action || first.text || 'The source gave no conclusion.',
    conclusionKind: action ? 'action' : 'thesis',
    conclusionClamped: !action && first.clamped,
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
