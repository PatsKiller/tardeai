// The live allocation route: one read of the Holdings reader, then the allocation page on that book.
//
// It fetches nothing else, holds no token and sends no POST — one GET through the shell's client
// (single-flight, heavy-reader guard, last-good), whose envelope `holdingsProps` turns into page props. The
// reader is `/api/v2/portfolio/holdings` and it is the SAME reader the Holdings page uses: the allocation
// view adds no source. Nothing is recomputed here beyond `bookView`-vs-view inside `allocationView.ts`.
//
// It does NOT publish into the shell's snapshot (unlike `HoldingsLive`): `bookView.isBookRoute` is true only
// for `/portfolio/holdings`, and the top bar refuses a snapshot published on another route. Publishing here
// would be a claim the bar is built to ignore, so this page keeps its own read and says "not read on this
// page" through the bar's existing rule — the UI does not contradict reality.

import { useEffect, useMemo, useState } from 'react'
import type { Envelope } from '../../api/client'
import { getJson } from '../../api/client'
import { AllocationPage } from './AllocationPage'
import { HOLDINGS_PATH, holdingsProps } from '../portfolio/liveProps'

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
  return <AllocationPage book={p.book} loading={p.loading} error={p.error} notice={p.notice} nowMs={now} />
}
