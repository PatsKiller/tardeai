// The live Fundamentals route: ONE read of the Holdings reader, then the same page the fixture renders.
//
// It fetches nothing else, holds no token, and sends no POST: one GET through the shell's client (single-flight,
// heavy-reader guard, last-good), whose envelope `holdingsProps` turns into page props — the very function the
// Holdings route uses, so the two routes cannot disagree about what the book says or how current it is.
//
// It does NOT publish into the top bar's snapshot: `bookView.barStatus` admits a snapshot only on the Holdings
// route, so publishing here would change nothing visible while implying a binding this route does not have. The
// bar therefore keeps its stated "not read on this page" state, and the page states its scope itself.

import { useEffect, useState } from 'react'
import type { Envelope } from '../../api/client'
import { getJson } from '../../api/client'
import { HOLDINGS_PATH, holdingsProps } from '../portfolio/liveProps'
import { FundamentalsPage } from './FundamentalsPage'

export function FundamentalsLive() {
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
  return <FundamentalsPage book={p.book} loading={p.loading} error={p.error} notice={p.notice} nowMs={now} />
}
