/**
 * Operator-facing words for internal identifiers (audit FQ-035, 2026-11-04).
 *
 * The operator reads these pages. A key such as `data_quality:data_source_stale` or `buy_ready`
 * is a label for the system, not for a person: it is translated here and the raw value is always
 * kept recoverable — callers put it in `title` (or a technical-details toggle), never on the face.
 *
 * Pure. No React, no I/O.
 */
import { humanizeIdentifier, looksLikeIdentifier } from './displayLabels.ts'

/** Keys whose meaning is not obvious from the words alone. Lower-case keys. */
const KNOWN: Record<string, string> = {
  // health-agent components and finding categories
  data_quality: 'Data quality',
  data_source_stale: 'Data source stale',
  data_source_idle: 'Data source idle',
  news_symbol_mismatch: 'News symbol mismatch',
  execution_health: 'Execution health',
  intelligence_quality: 'Intelligence quality',
  risk_protection: 'Risk protection',
  retirement_planning: 'Retirement planning',
  pipeline_freshness: 'Pipeline freshness',
  // health-agent actors and remediation states
  health_agent: 'Health agent',
  escalation_handler: 'Escalation handler',
  pr_opened: 'PR opened',
  advisory_diff: 'Advisory diff',
  no_changes: 'No changes',
  verify_failed: 'Verification failed',
  no_backend_available: 'No backend available',
  // recommendation origins and lifecycle states
  'direct/manual': 'Direct / manual',
  buy_ready: 'Ready to buy',
  entry_near: 'Entry near',
  incubator: 'Incubator',
  cio: 'CIO',
  hermes_research: 'Hermes research',
  claude_challenger: 'Claude challenger',
  // price provenance keys that arrive with an internal prefix
  'broker.market_quotes': 'Broker quotes',
  'broker.cash_unit': 'Cash balances',
  technical_snapshot: 'Technical snapshot',
  market_quotes: 'Market quotes',
}

const SNAKE = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/i
const KEBAB = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$/i

const LEADING = /^[('"\[{‘“]*/ 
const TRAILING = /[.,;:!?)\]}'”’]*$/

/**
 * Split a word into the bare token and the punctuation around it, so `(data_source_stale)` and
 * `'buy_ready'` are still recognised as identifiers (review finding, 2026-11-04: only trailing
 * punctuation was stripped before, so the common wrapped forms leaked through untranslated).
 */
function splitToken(token: string): [string, string, string] {
  const lead = token.match(LEADING)?.[0] ?? ''
  const rest = token.slice(lead.length)
  const trail = rest.match(TRAILING)?.[0] ?? ''
  return [lead, rest.slice(0, rest.length - trail.length), trail]
}

/** One identifier segment → operator words. `data_source_stale` → "Data source stale". */
function one(raw: string): string {
  const lower = raw.toLowerCase()
  const known = KNOWN[lower]
  if (known) return known
  return humanizeIdentifier(raw) || raw
}

/**
 * `data_quality:data_source_stale` → "Data quality · Data source stale".
 * A plain word is returned unchanged apart from the known-key map; a sentence is returned unchanged.
 */
export function componentLabel(raw: unknown): string {
  if (raw == null) return ''
  const s = String(raw).trim()
  if (!s) return ''
  const parts = s.split(':')
  if (parts.length > 1) return parts.filter(Boolean).map(one).join(' · ')
  return one(s)
}

/**
 * Humanise snake_case identifiers inside a sentence, leaving ordinary words alone.
 * `data_quality signal needs review.` → "Data quality signal needs review."
 * Hyphenated words are left alone on purpose: `well-known` and `after-hours` are English, and a
 * kebab strategy id is a label — labels go through `componentLabel`, not through running prose.
 * Text with no identifier-shaped token is returned unchanged (byte for byte).
 */
export function sentenceIdentifiers(raw: unknown): string {
  if (raw == null) return ''
  const s = String(raw)
  if (!s) return ''
  return s.replace(/\S+/g, word => {
    const [lead, core, trail] = splitToken(word)
    if (!SNAKE.test(core) || !looksLikeIdentifier(core)) return word
    return lead + one(core) + trail
  })
}

/**
 * A dash is not an answer. Where a value is absent the page says which absence it is:
 * `not measured` (nobody recorded it), `unavailable` (the source could not be read) or
 * `not applicable` (the field does not exist for this item). Callers pass the state they know.
 */
export function absenceWords(state: 'measured' | 'unavailable' | 'not-applicable', what?: string): string {
  const subject = what ? `${what} ` : ''
  if (state === 'measured') return `${subject}not measured`
  if (state === 'unavailable') return `${subject}unavailable`
  return `${subject}not applicable`
}
