import { useEffect, useState } from 'react'
import type { Envelope } from '../../../api/client'
import { getJson } from '../../../api/client'
import { adaptLevels, levelsPathFor, type LevelsState } from './levelsAdapter'
import { LevelsPage } from './LevelsPage'

/**
 * One GET per submitted symbol, on user action only; no poll, and nothing is written client-side. The backend is not
 * read-only for this route: on a cache miss `_indicator_levels_handler` fetches market data from an external
 * provider, computes the levels and writes its cache (FE review L2-7). The explicit submit is the gate, and the page
 * says so before the user submits.
 */
export function LevelsLive() {
  const [draft, setDraft] = useState('')
  const [bad, setBad] = useState(false)
  const [req, setReq] = useState<{ symbol: string; path: string } | null>(null)
  const [env, setEnv] = useState<Envelope<unknown> | null>(null)
  useEffect(() => {
    if (req === null) return
    const ctl = new AbortController()
    setEnv(null)
    void getJson<unknown>(req.path, ctl.signal).then(r => { if (!ctl.signal.aborted) setEnv(r) })
    return () => ctl.abort()
  }, [req])
  const state: LevelsState = req === null ? { kind: 'idle' } : adaptLevels(req.symbol, env)
  const submit = () => {
    const path = levelsPathFor(draft)
    if (path === null) { setBad(true); return }
    setBad(false)
    setReq({ symbol: draft.trim().toUpperCase(), path })
  }
  return <LevelsPage state={state} draft={draft} onDraft={setDraft} onSubmit={submit} badInput={bad} />
}
