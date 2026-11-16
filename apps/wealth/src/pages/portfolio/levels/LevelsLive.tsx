import { useEffect, useState } from 'react'
import type { Envelope } from '../../../api/client'
import { getJson } from '../../../api/client'
import { adaptLevels, levelsPathFor, type LevelsState } from './levelsAdapter'
import { LevelsPage } from './LevelsPage'

/** One GET per submitted symbol, on user action only. No poll, no write. */
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
