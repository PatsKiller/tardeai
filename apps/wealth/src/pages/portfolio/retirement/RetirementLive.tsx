import { useEffect, useState } from 'react'
import type { Envelope } from '../../../api/client'
import { getJson } from '../../../api/client'
import { RETIREMENT_PATH, RESEARCH_PATH, adaptResearch, adaptRetirement } from './retirementAdapter'
import { RetirementPage } from './RetirementPage'

/** Two independent GETs; one failing never blanks the other. No poll, no write. */
export function RetirementLive() {
  const [a, setA] = useState<Envelope<unknown> | null>(null)
  const [b, setB] = useState<Envelope<unknown> | null>(null)
  useEffect(() => {
    const ctl = new AbortController()
    void getJson<unknown>(RETIREMENT_PATH, ctl.signal).then(r => { if (!ctl.signal.aborted) setA(r) })
    void getJson<unknown>(RESEARCH_PATH, ctl.signal).then(r => { if (!ctl.signal.aborted) setB(r) })
    return () => ctl.abort()
  }, [])
  return <RetirementPage retirement={adaptRetirement(a, Date.now())} research={adaptResearch(b)} />
}
