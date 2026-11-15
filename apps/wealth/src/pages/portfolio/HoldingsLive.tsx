// The live holdings route: one read of its own reader, then the same page the fixture renders.
//
// It fetches nothing else, holds no token, and sends no POST: one GET through the shell's client (single-flight,
// heavy-reader guard, last-good), whose envelope `holdingsProps` turns into page props. The page is not told which
// source it has — the book carries `source: 'LIVE'`, and the fixture banner keys off `'FIXTURE'`.
//
// Because the shell may not originate this heavy read, the page publishes what it read into the snapshot the top
// bar renders (snapshot.tsx): one read, one book, one scope for the page and the bar.

import { useEffect, useMemo, useState } from 'react'
import type { Envelope } from '../../api/client'
import { getJson } from '../../api/client'
import { HoldingsPage } from './HoldingsPage'
import { HOLDINGS_PATH, holdingsProps } from './liveProps'
import { usePublishBook } from './snapshot'

export function HoldingsLive() {
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

  // Memoised on the three things that can change the answer: the envelope, the clock the verdict is measured
  // against, and the read error. A new object on every render would republish the book on every render.
  const p = useMemo(
    () => (readError !== null ? { book: null, loading: false, error: readError, notice: null } : holdingsProps(env, now)),
    [env, now, readError],
  )
  usePublishBook(p)
  return <HoldingsPage book={p.book} loading={p.loading} error={p.error} notice={p.notice} nowMs={now} />
}
