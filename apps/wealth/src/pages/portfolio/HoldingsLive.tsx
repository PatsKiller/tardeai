// The live holdings route: one read of its own reader, then the same page the fixture renders.
//
// It fetches nothing else, holds no token, and sends no POST: one GET through the shell's client (single-flight,
// heavy-reader guard, last-good), whose envelope `holdingsProps` turns into page props. The page is not told which
// source it has — the book carries `source: 'LIVE'`, and the fixture banner keys off `'FIXTURE'`.

import { useEffect, useState } from 'react'
import type { Envelope } from '../../api/client'
import { getJson } from '../../api/client'
import { HoldingsPage } from './HoldingsPage'
import { HOLDINGS_PATH, holdingsProps } from './liveProps'

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

  const p = readError !== null ? { book: null, loading: false, error: readError, notice: null } : holdingsProps(env, now)
  return <HoldingsPage book={p.book} loading={p.loading} error={p.error} notice={p.notice} />
}
