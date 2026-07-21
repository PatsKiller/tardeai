import { useState, useRef, useEffect } from 'react'
import { BB } from '../lib/watchlistTerminalTokens'

/*
 * ShadowBatchButton — the manual "run adhoc" control for bounded batch packet
 * generation (operator-authorised 2026-07-21).
 *
 * POSTs /api/v2/shadow/strategy/batch (spawns the bounded generator detached:
 * top-N by rank in the eligible ratings + all starred), then polls GET for
 * progress. SHADOW ONLY — generates decision packets, queues/submits nothing.
 *
 * Design: BB tokens only, no sub-10px fonts.
 */
export default function ShadowBatchButton({ embedded }: { embedded?: boolean }) {
  const [state, setState] = useState<'idle' | 'running' | 'done'>('idle')
  const [prog, setProg] = useState<{ done?: number; to?: number }>({})
  const timer = useRef<number | null>(null)
  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current) }, [])

  const unwrap = (j: any) => (j && typeof j === 'object' && 'data' in j && j.data ? j.data : j)

  const poll = () => {
    if (timer.current) window.clearInterval(timer.current)
    timer.current = window.setInterval(async () => {
      try {
        const s = unwrap(await (await fetch('/api/v2/shadow/strategy/batch')).json())
        setProg({ done: s.done ?? s.generated, to: s.to_generate })
        if (s.state === 'complete') { if (timer.current) window.clearInterval(timer.current); setState('done') }
        else if (s.state === 'running') setState('running')
      } catch { /* keep polling */ }
    }, 3000)
  }

  const start = async (e: any) => {
    e.stopPropagation()
    setState('running'); setProg({})
    try {
      const r = unwrap(await (await fetch('/api/v2/shadow/strategy/batch', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: '{}' })).json())
      if (r.ok) poll()
      else setState('idle')
    } catch { setState('idle') }
  }

  const label = state === 'running'
    ? `⏳ shadow batch ${prog.done ?? 0}/${prog.to ?? '…'}`
    : state === 'done' ? '✓ shadow batch — rerun' : '⚡ shadow batch'

  return (
    <button onClick={start} disabled={state === 'running'}
      title="Generate multidimensional shadow decision packets for the top-50 by rank (buy/hold/wait-for-pullback) + all starred. Advisory only — nothing queued or submitted."
      style={{ padding: embedded ? '6px 10px' : '9px 14px', fontSize: embedded ? 10 : 12,
               fontWeight: 800, borderRadius: 2, border: `1px solid ${BB.amber}`,
               cursor: state === 'running' ? 'default' : 'pointer',
               background: BB.amberDim, color: state === 'running' ? BB.text3 : BB.amber }}>
      {label}
    </button>
  )
}
