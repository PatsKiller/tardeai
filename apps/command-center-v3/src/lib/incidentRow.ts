// One incident as a phone row a person can read (FQ-045, FQ-046).
//
// The audit's phone capture showed rows that were three or four lines of ledger vocabulary: `lane coverage-stall
// unhealthy: research_up_thesis_flat:deepseek_ok, 24h=58`, `DEGRADED_STALE_SOURCE`, `tests/test_x.py:test_y`,
// `(rc=1)`. Nothing here invents a meaning. Three things happen, and each one is testable:
//
//   1. RAW IDENTIFIERS ARE PUT IN ENGLISH, NOT DELETED. `snake_case`, `dotted.paths`, camelCase and ALL_CAPS are
//      spelled out as words. A parenthetical that only carries machine detail — `(rc=1)`, a PR number in brackets, `(attempts=3)` —
//      is lifted OUT of the sentence and returned in `rawDetail`, which the detail view shows verbatim.
//   2. A TITLE THAT NEEDS NO TRANSLATION IS LEFT ALONE. `raw` and `rawDetail` are null when nothing was lifted, so a
//      plain title never carries a second, redundant copy of itself.
//   3. NEXT ACTION IS DERIVED FROM FIELDS, NEVER GUESSED. A blocked incident quotes its own `handoff`; an
//      unrecognised status says so instead of borrowing a neighbour's meaning.
import { statusLabel, type Incident, type Tone } from './incidents.ts'

export type IncidentRowModel = {
  /** the ledger's sentence, with identifiers spelled out and machine parentheticals lifted */
  headline: string
  /** the ledger's own title, ONLY when the headline differs from it — the detail view prints this verbatim */
  raw: string | null
  /** the machine detail lifted out of the sentence, ONLY when something was lifted */
  rawDetail: string | null
  status: { label: string; tone: Tone }
  /** the ledger's own P1/P2/P3. Never glossed into words: a reworded priority is a priority nobody agreed to. */
  priority: { code: string; tone: Tone }
  /** what happens next and who, in one sentence — the field the phone row exists for */
  nextAction: string
  /** age and where it came from; a phone row drops this and the detail keeps it */
  meta: string
}

const ALL_CAPS = /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g
const SNAKE = /\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/g
const CAMEL = /\b[a-z]+(?:[A-Z][a-z0-9]+)+\b/g
const DOTTED = /\b[a-z][a-z0-9]*(?:\.[a-z0-9]+)+\b/g
/** A parenthetical is machine detail when it carries an assignment, a path, a PR number or a bare code. */
const MACHINE_PAREN = /\(([^()]*(?:[=/#]|\b[A-Z]{3,}\b|\d+\s*[a-zA-Z]+\s*=)[^()]*)\)/g
/** A trailing run of `key=value` measurements — `, 24h=58,thesis_sustained=11` — is machine detail, not a sentence. */
const METRIC_TAIL = /((?:[,;]\s*[A-Za-z0-9_.]+\s*=\s*[^,;]+)+)\s*$/

const MARKERS: Array<[RegExp, string]> = [
  [/\bDISABLED:/g, 'disabled — '], [/\bMISSING:/g, 'missing — '], [/\bENABLED:/g, 'enabled — '],
]

function words(s: string): string {
  return s.replace(/\s+/g, ' ').trim()
}

/** Spelled out, not summarised: every identifier survives as words, so the sentence still says the same thing. */
export function plainWords(s: string): string {
  let out = String(s ?? '')
  for (const [re, to] of MARKERS) out = out.replace(re, to)
  out = out.replace(ALL_CAPS, m => m.replace(/_/g, ' ').toLowerCase())
  out = out.replace(SNAKE, m => m.replace(/_/g, ' '))
  out = out.replace(CAMEL, m => m.replace(/([a-z])([A-Z])/g, '$1 $2'))
  out = out.replace(DOTTED, m => m.replace(/\./g, ' '))
  return words(out)
}

const sentenceCase = (s: string) => s ? s.charAt(0).toUpperCase() + s.slice(1) : s

export function plainTitle(title: string | null | undefined): { headline: string; raw: string | null; rawDetail: string | null } {
  const original = words(String(title ?? ''))
  const lifted: string[] = []
  const withoutMetrics = original.replace(METRIC_TAIL, (_m, tail: string) => {
    lifted.push(words(tail.replace(/^[,;]\s*/, '').replace(/[,;]/g, ', ')))
    return ''
  })
  const withoutParens = withoutMetrics.replace(MACHINE_PAREN, (_m, inner: string) => {
    lifted.push(words(inner))
    return ''
  })
  const headline = sentenceCase(words(plainWords(withoutParens)))
  const rawDetail = lifted.length ? lifted.join(' · ') : null
  // Nothing changed: the ledger already spoke English. Return the title untouched and claim no translation.
  if (headline === original && rawDetail === null) return { headline: original, raw: null, rawDetail: null }
  return { headline, raw: original, rawDetail }
}

const PRIORITY_TONE: Record<string, Tone> = { P1: 'danger', P2: 'warning', P3: 'neutral' }

export function priorityOf(i: { severity?: string | null }): { code: string; tone: Tone } {
  const code = String(i.severity ?? '').toUpperCase().trim()
  return { code: code || 'Not recorded', tone: code ? (PRIORITY_TONE[code] ?? 'neutral') : 'neutral' }
}

/** The next step and who owns it. Every branch is a fact about the record; none is a guess about the world. */
export function nextActionOf(i: Incident): string {
  const handoff = words(String(i.handoff ?? ''))
  const owner = words(String(i.owner ?? ''))
  switch (i.status) {
    case 'blocked':
      return handoff ? `Needs a person. Next: ${handoff}` : 'Needs a person, and no next step is recorded.'
    case 'open':
      return owner ? `Nobody is working on it yet. Owner: ${owner}.` : 'Nobody is working on it yet.'
    case 'fixing':
      return owner ? `Being fixed. Owner: ${owner}.` : 'Being fixed.'
    case 'fixed':
      return words(`Fixed${i.resolution ? ` — ${String(i.resolution).replace(/_/g, ' ')}` : ''}.`)
    case 'closed':
      return words(`Closed as won't fix${i.resolution ? ` — ${String(i.resolution).replace(/_/g, ' ')}` : ''}.`)
    default:
      // Do not borrow another status's meaning: an unrecognised status is reported as unrecognised.
      return `The ledger reports a status this page does not know (${String(i.status)}).`
  }
}

export function rowModel(i: Incident, opts: { age: string; source: string }): IncidentRowModel {
  const t = plainTitle(i.title)
  return {
    headline: t.headline,
    raw: t.raw,
    rawDetail: t.rawDetail,
    status: statusLabel(i.status),
    priority: priorityOf(i),
    nextAction: nextActionOf(i),
    meta: `${opts.age} · ${plainWords(opts.source)}`,
  }
}
