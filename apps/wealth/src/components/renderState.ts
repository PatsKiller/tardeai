// RenderState: the one place a read becomes LOADING / UNKNOWN / ERROR / EMPTY / OK.
// Framework-free so it is tested under plain node.
//
//  * The outer HTTP/`ok` flag never decides. Unavailability comes only from the reader's declared
//    nested path (readers.ts), so {"ok":true,"data":{"ok":false,...}} is UNKNOWN.
//  * Freshness comes from the declared as_of path. No as_of → freshness unproven.
//  * EMPTY needs a fresh as_of behind it. An empty list or count 0 without one is UNKNOWN
//    ("not materialised" and "nothing there" look the same on the wire).
//  * UNKNOWN is never green: its cue level is NEUTRAL with the word UNKNOWN.
import type { Envelope } from '../api/client.ts'
import type { ReaderSpec } from '../api/readers.ts'
import { readPath, ruleFires } from '../api/readers.ts'

export type RenderStatus = 'LOADING' | 'UNKNOWN' | 'ERROR' | 'EMPTY' | 'OK'

export interface RenderState<T> {
  status: RenderStatus
  /** Plain-language reason, shown in the tooltip and the UNKNOWN/ERROR body. */
  reason: string
  data: T | null
  /** Hours since the declared as_of, when one exists. */
  ageHours: number | null
  asOf: string | null
  /** On ERROR, the last good body and its age, labelled as such. */
  lastGood: T | null
  lastGoodAgeSeconds: number | null
}

export interface DeriveInput<T> {
  envelope: Envelope<T> | null
  /** Overrides envelope.spec (tests, or a page that narrows the rule). */
  spec?: ReaderSpec
  now: number
  /** The page says what "empty" means for its payload. */
  isEmpty?: (data: T) => boolean
}

function base<T>(status: RenderStatus, reason: string, extra: Partial<RenderState<T>> = {}): RenderState<T> {
  return { status, reason, data: null, ageHours: null, asOf: null, lastGood: null, lastGoodAgeSeconds: null, ...extra }
}

export function deriveRenderState<T>({ envelope, spec, now, isEmpty }: DeriveInput<T>): RenderState<T> {
  if (!envelope) return base('LOADING', 'reading')
  const s = spec ?? envelope.spec
  if (envelope.data === null) {
    return base('ERROR', envelope.error ?? 'read failed', {
      lastGood: envelope.lastGood, lastGoodAgeSeconds: envelope.lastGoodAgeSeconds,
    })
  }
  const body = envelope.data
  for (const rule of s.unavailableWhen) {
    const v = readPath(body, rule.at)
    if (ruleFires(rule, v)) {
      return base('UNKNOWN', 'notEquals' in rule && rule.notEquals !== undefined
        ? `source reports ${rule.at} = ${v === undefined ? 'missing' : JSON.stringify(v)}, not ${JSON.stringify(rule.notEquals)}`
        : `source reports ${rule.at} = ${JSON.stringify(rule.equals)}`)
    }
  }
  let asOf: string | null = null
  let ageHours: number | null = null
  if (s.asOfAt) {
    const raw = readPath(body, s.asOfAt)
    const t = typeof raw === 'string' ? Date.parse(raw) : NaN
    if (Number.isNaN(t)) return base('UNKNOWN', `no readable ${s.asOfAt}; freshness unproven`)
    asOf = raw as string
    ageHours = Math.max(0, (now - t) / 3_600_000)
    if (s.maxAgeHours !== undefined && ageHours > s.maxAgeHours) {
      return base('UNKNOWN', `stale: ${ageHours.toFixed(1)} h old (limit ${s.maxAgeHours} h)`, { asOf, ageHours })
    }
  }
  if (isEmpty && isEmpty(body)) {
    if (asOf === null) return base('UNKNOWN', 'empty with no as_of behind it: not materialised and none look the same')
    return base('EMPTY', `none as of ${asOf}`, { data: body, asOf, ageHours })
  }
  return base('OK', asOf ? `as of ${asOf}` : 'read ok; this reader declares no as_of', { data: body, asOf, ageHours })
}

/** Cue for a status. UNKNOWN and LOADING are NEUTRAL; nothing here is ever GREEN. */
export function statusCue(st: RenderState<unknown>): { level: 'NEUTRAL' | 'RED' | 'AMBER'; label: string; icon: 'unassessed' | 'alert' | 'caution' | 'info'; tooltip: string } | null {
  switch (st.status) {
    case 'LOADING': return { level: 'NEUTRAL', label: 'Loading', icon: 'info', tooltip: 'Reading the source' }
    case 'UNKNOWN': return { level: 'NEUTRAL', label: 'UNKNOWN', icon: 'unassessed', tooltip: st.reason }
    case 'ERROR': return { level: 'RED', label: st.lastGood ? 'Last good shown' : 'Read failed', icon: 'alert', tooltip: st.reason }
    case 'EMPTY': return null
    case 'OK': return null
  }
}
