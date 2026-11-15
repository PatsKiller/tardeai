// Envelope → page props for the live holdings page.
//
// The shell's `deriveRenderState` decides whether the read is current; this module decides what the page shows
// for each verdict, and states it. Pure: no React, no fetch — the tests drive it with envelopes built by hand.
//
// The rule that keeps this honest: a book that is not current is NEVER passed as current. ERROR with a last good
// body and UNKNOWN both hand the page a book whose `freshness.stale` is forced true and whose age is the age of
// the read it came from, plus a notice that says so in one sentence. The numbers stay served; only their claim to
// be today is withdrawn.

import type { Envelope } from '../../api/client'
import { deriveRenderState } from '../../components/renderState'
import { adaptHoldings } from './adapter'
import type { HoldingsBook } from './contract'

export const HOLDINGS_PATH = '/api/v2/portfolio/holdings'

export interface HoldingsProps {
  book: HoldingsBook | null
  loading: boolean
  error: string | null
  /** A one-line statement of what the reader is NOT claiming (last good, not current, health unproven). */
  notice: string | null
}

/** "Empty" for this payload is a holdings list the producer served with nothing in it — only then is it EMPTY. */
function isEmptyBody(body: unknown): boolean {
  if (body === null || typeof body !== 'object') return false
  const d = (body as { data?: unknown }).data
  if (d === null || typeof d !== 'object') return false
  const h = (d as { holdings?: unknown }).holdings
  return Array.isArray(h) && h.length === 0
}

function ageText(seconds: number | null): string {
  if (seconds === null) return 'of unknown age'
  if (seconds < 90) return `${Math.round(seconds)} s old`
  if (seconds < 5400) return `${Math.round(seconds / 60)} min old`
  return `${Math.round(seconds / 3600)} h old`
}

/** Withdraw the book's claim to be current, and say why in the note the page prints. */
function asLastKnown(book: HoldingsBook, ageSeconds: number | null, why: string): HoldingsBook {
  return {
    ...book,
    freshness: {
      ...book.freshness,
      ageSeconds: ageSeconds ?? book.freshness.ageSeconds,
      stale: true,
      withdrawn: true,
    },
    coverageNote: `${book.coverageNote} ${why}`,
  }
}

const none = (p: Partial<HoldingsProps>): HoldingsProps => ({ book: null, loading: false, error: null, notice: null, ...p })

export function holdingsProps(env: Envelope<unknown> | null, now: number): HoldingsProps {
  if (env === null) return none({ loading: true })
  const st = deriveRenderState<unknown>({ envelope: env, now, isEmpty: isEmptyBody })

  if (st.status === 'LOADING') return none({ loading: true })

  if (st.status === 'ERROR') {
    // The client keeps the last body it read. Showing it is allowed only with its age, labelled: a failed read is
    // never a current book.
    if (st.lastGood !== null) {
      const lg = adaptHoldings(st.lastGood)
      if (lg.book !== null) {
        // R2 (review 2026-11-15T1704Z, check 4): a body this browser cached is not a validated last-success
        // receipt. Say "last available read", never "last good" — §K reserves that for a receipt.
        const why = `This is the last available read (${ageText(st.lastGoodAgeSeconds)}); the current read failed: ${st.reason}.`
        return none({ book: asLastKnown(lg.book, st.lastGoodAgeSeconds, why), notice: why })
      }
    }
    return none({ error: st.reason })
  }

  // `deriveRenderState` returns UNKNOWN from a rule with `data: null` — the body was fine, what is missing is the
  // proof it is current — so the body comes from the envelope in that case. (`ERROR` and `LOADING` never reach here.)
  const body = st.data ?? env.data
  if (body === null) return none({ error: 'the read returned no body' })
  const res = adaptHoldings(body)
  if (res.book === null) return none({ error: res.error ?? 'the payload is not a holdings book' })

  if (st.status === 'UNKNOWN') {
    // The body is there; what is missing is the proof that it is current. Show it as last known, never as current.
    const why = `Not current: ${st.reason}. Every number below is the last served value, not a current one.`
    return none({ book: asLastKnown(res.book, null, why), notice: why })
  }

  // The producer's own verdict over its SOURCE clocks decides first (C1, F-2/F-3/F-5): the read's cache age is how
  // old this RESPONSE is, not how old the book is, and it must never overrule the verdict the producer computed.
  // Only an older producer, which serves no verdict, falls through to the cache rule below — and then the notice
  // says the age is the cache's.
  const served = res.book.freshness.served
  if (served !== null && served.status === 'UNKNOWN') {
    const why = `Not current: the producer could not compute a freshness verdict${
      served.gap === null ? '' : ` (${served.gap})`}. Every number below is the last served value.`
    return none({ book: asLastKnown(res.book, null, why), notice: why })
  }
  if (served !== null && served.status === 'STALE') {
    const clock = served.clockLabel ?? served.clock ?? 'a source'
    const ageS = served.ageSeconds === null ? 'of unknown age' : ageText(served.ageSeconds)
    const limit = served.limitSeconds === null ? 'limit not served' : `limit ${served.limitSeconds} s`
    const why = `Not current: the ${clock} clock is ${ageS}, past the ${limit} the producer applied${
      served.limitSource === null ? '' : ` (${served.limitSource})`}. Every number below is the last served value.`
    return none({ book: asLastKnown(res.book, null, why), notice: why })
  }
  if (served !== null) return none({ book: res.book, notice: st.healthUnproven })

  // No served verdict: the SWR layer's own cache verdict is all there is. A body past the cache window is not
  // current, and the notice says it is the CACHE that is old — never that the producer reported the book stale.
  if (res.book.freshness.stale) {
    // Three different facts, three different sentences. An ABSENT block must not be described as one that reported
    // staleness, and a block with no served age must not be aged. Both are the R1 honesty defect, in the notice text.
    const f = res.book.freshness
    // An unserved limit is said to be unserved. A 0 s limit would be a number the producer never sent (R1b).
    const limit = f.staleAfterSeconds === null ? 'limit not served' : `limit ${f.staleAfterSeconds} s`
    const why = !f.blockPresent
      ? 'Not current: the response carries no cache block and no produced freshness verdict; this body cannot be shown as current. Every number below is the last served value, of unknown age.'
      : f.ageSeconds === null
        ? `Not current: this response is past its cache window and the cache age is not served (${limit}); no produced freshness verdict was served either. Every number below is the last served value.`
        : `Not current: this response is ${f.ageSeconds} s old in the cache (${limit}) and no produced freshness verdict was served. Every number below is the last served value.`
    return none({ book: asLastKnown(res.book, null, why), notice: why })
  }

  return none({ book: res.book, notice: st.healthUnproven })
}
