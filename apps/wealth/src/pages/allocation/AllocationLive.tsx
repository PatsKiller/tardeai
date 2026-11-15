// The live allocation route: one read of the Holdings reader, then the allocation page on that book.
//
// It fetches nothing else, holds no token and sends no POST — one GET through the shell's client
// (single-flight, heavy-reader guard, last-good), whose envelope `holdingsProps` turns into page props. The
// reader is `/api/v2/portfolio/holdings` and it is the SAME reader the Holdings page uses: the allocation
// view adds no source. Nothing is recomputed here beyond `bookView`-vs-view inside `allocationView.ts`.
//
// It publishes that read into the shell's snapshot (`usePublishBook`), exactly as `HoldingsLive` does: this
// page originates the same heavy read, so the top bar renders the book THIS page read under the same scope
// instead of claiming "not read here" while the page shows real values (operator finding 2026-11-15T1745Z,
// item 2). `bookView.isBookRoute` accepts this route for the same reason. Publishing is not a second fetch —
// the effect above remains the only request — and the snapshot is withdrawn on unmount, so no other route
// can render these numbers.

import { useEffect, useMemo, useState } from 'react'
import type { Envelope } from '../../api/client'
import { getJson } from '../../api/client'
import { AllocationPage } from './AllocationPage'
import { HOLDINGS_PATH, holdingsProps } from '../portfolio/liveProps'
import { usePublishBook } from '../portfolio/snapshot'

export function AllocationLive() {
  const [env, setEnv] = useState<Envelope<unknown> | null>(null)
  const [readError, setReadError] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const ctl = new AbortController()
    let live = true
    getJson<unknown>(HOLDINGS_PATH, ctl.signal)
      .then(e => {
        if (!live) return
        setEnv(e)
        setNow(Date.now())
      })
      .catch((e: unknown) => {
        if (!live) return
        setReadError(e instanceof Error ? e.message : String(e))
        setNow(Date.now())
      })
    return () => {
      live = false
      ctl.abort()
    }
  }, [])

  const p = useMemo(
    () => (readError !== null ? { book: null, loading: false, error: readError, notice: null } : holdingsProps(env, now)),
    [env, now, readError],
  )
  usePublishBook(p)
  return <AllocationPage book={p.book} loading={p.loading} error={p.error} notice={p.notice} nowMs={now} />
}
