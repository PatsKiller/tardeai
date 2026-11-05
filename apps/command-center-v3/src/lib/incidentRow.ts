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
  /** age and where it came from; a desk row shows both */
  meta: string
  /** the age alone — a phone drops the source identifier but NEVER the age (cx-openai-4 R2 on PR 2628) */
  age: string
}

const ALL_CAPS = /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g
const SNAKE = /\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/g
const CAMEL = /\b[a-z]+(?:[A-Z][a-z0-9]+)+\b/g
const DOTTED = /\b[a-z][a-z0-9]*(?:\.[a-z0-9]+)+\b/g
/** A parenthetical is machine detail when it carries an assignment, a path or a PR number.
 *
 *  NOT every ALL_CAPS parenthetical is machine detail: "(NOT VERIFIED)" is a QUALIFICATION on the sentence beside it.
 *  Lifting it turned "Data service healthy (NOT VERIFIED)" into "Data service healthy" on the row - a healthy claim the
 *  source did not make (cx-openai-4 R1 on PR 2628). A qualification stays in the sentence; only assignments, paths and
 *  references move to the detail. */
const QUALIFICATION = /\b(NOT|UN)\s?VERIFIED\b|\bUNVERIFIED\b|\bUNKNOWN\b|\bSTALE\b|\bESTIMATED?\b|\bPARTIAL\b|\bUNCONFIRMED\b/i

/** ONE segment of a parenthetical is machine detail only when it is an assignment, a path or a reference.
 *
 *  This is deliberately not a vocabulary list (cx-openai-4, second review of PR 2628): a whitelist of qualification
 *  WORDS still let "(rc=1; UNAVAILABLE)" lift its qualification, because the `=` anywhere in the bracket made the whole
 *  bracket a machine candidate. The test is now structural — a bracket is machine detail only if EVERY segment is
 *  machine-shaped, so "(rc=1; NOT READY)" stays in the sentence whatever words the source chooses next. */
const MACHINE_SEGMENT = /^\s*(?:[A-Za-z0-9_.\-]+\s*=\s*\S+|#?\d+|[\w.\-]+\/[\w./\-]*)\s*$/
function allMachine(inner: string): boolean {
  const segments = inner.split(/[;,]|\s{2,}/).map(x => x.trim()).filter(Boolean)
  return segments.length > 0 && segments.every(seg => MACHINE_SEGMENT.test(seg))
}
const MACHINE_PAREN = /\(([^()]*)\)/g
/** A trailing run of `key=value` measurements — `, 24h=58,thesis_sustained=11` — is machine detail, not a sentence.
 *
 *  cx-openai-4 F1 (third review of PR 2628): the value used to be `[^,;]+`, i.e. any prose at all, so a sentence that
 *  QUALIFIED itself through an assignment — "Data service healthy, status=NOT VERIFIED" — lost its warning on the row
 *  and rendered as a healthy claim the source never made. Another word list would not close that class (the previous
 *  round proved it), so the test is structural, the same way the bracket rule is: a tail is lifted only when EVERY
 *  segment's value is a NUMBER, optionally with a unit. That is what a measurement looks like; a word, a verdict or a
 *  phrase stays in the sentence, whatever it says. */
const METRIC_TAIL = /((?:[,;]\s*[A-Za-z0-9_.]+\s*=\s*[^,;]+)+)\s*$/
const MEASUREMENT_VALUE = /^[+-]?\d+(?:\.\d+)?\s*(?:%|[A-Za-z]{1,6})?$/
function allMeasurements(tail: string): boolean {
  const segments = tail.split(/[,;]/).map(x => x.trim()).filter(Boolean)
  return segments.length > 0 && segments.every(seg => {
    const m = /^[A-Za-z0-9_.]+\s*=\s*(.+)$/.exec(seg)
    return !!m && MEASUREMENT_VALUE.test(m[1].trim())
  })
}

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
  // cc-deepseek-5 F2 on #2628: a decimal point is not a dotted identifier separator. "99.7" inside a word used to
  // become "99 7", losing the point on the operator's row. A dot between two digits is kept; every other dot still
  // separates the identifier's words.
  out = out.replace(DOTTED, m => m.replace(/\d\.\d/g, mm => mm.replace('.', '\u0000'))
    .replace(/\./g, ' ').replace(/\u0000/g, '.'))
  return words(out)
}

const sentenceCase = (s: string) => s ? s.charAt(0).toUpperCase() + s.slice(1) : s

/**
 * A lifted measurement tail can carry the `)` that closed a bracket it does not own — `(UNAVAILABLE; rc=1)` loses the
 * `; rc=1)` and leaves `(UNAVAILABLE`. Re-close anything left open so a qualification is never rendered with a hanging
 * bracket. Only ever adds a bracket the text is missing; it never removes one.
 */
function closeBrackets(s: string): string {
  let depth = 0
  for (const ch of s) { if (ch === '(') depth++; else if (ch === ')') depth = Math.max(0, depth - 1) }
  return depth > 0 ? s.trimEnd() + ')'.repeat(depth) : s
}

export function plainTitle(title: string | null | undefined): { headline: string; raw: string | null; rawDetail: string | null } {
  const original = words(String(title ?? ''))
  const lifted: string[] = []
  const withoutMetrics = closeBrackets(original.replace(METRIC_TAIL, (m, tail: string) => {
    // A tail that is not made of measurements is prose, and prose that qualifies the sentence stays in it.
    if (!allMeasurements(tail)) return m
    lifted.push(words(tail.replace(/^[,;]\s*/, '').replace(/[,;]/g, ', ')))
    return ''
  }))
  const withoutParens = withoutMetrics.replace(MACHINE_PAREN, (m, inner: string) => {
    // Two ways a bracket stays in the sentence: it carries a qualification, or it carries ANY prose at all.
    if (QUALIFICATION.test(inner) || !allMachine(inner)) return m
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
    age: opts.age,
  }
}
