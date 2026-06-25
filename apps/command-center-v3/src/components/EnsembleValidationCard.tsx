import { useState, useRef, useCallback, useEffect } from 'react'

// Multi-LLM ensemble validation UI (Grok + ChatGPT OAuth + local gemma).
// Mirrors the real backend shape from scripts/inference_ensemble.ensemble_validate:
//   { final_decision, final_score(0-10), final_confidence(0-1), consensus_reached,
//     lanes_used[], votes[{lane,score,decision,confidence,reasoning}], reasoning_summary }
// v3 styling = inline styles + CSS vars (no Tailwind/lucide). Validation runs in a
// background worker (never blocks the single-threaded server); this just enqueues + polls.

export interface EnsembleVote {
  lane: string
  score: number
  decision: 'approve' | 'block'
  confidence: number
  reasoning?: string
  // finance/retirement sub-scores (present only on finance-substantive items — see inference_ensemble._prompt)
  retirement_relevance?: number
  finance_actionability?: number
  risk_alignment?: number
}
export interface EnsembleResult {
  final_decision: 'approve' | 'block'
  final_score: number
  final_confidence: number
  consensus_reached: boolean
  lanes_used: string[]
  votes: EnsembleVote[]
  reasoning_summary?: string
  retirement_relevance?: number
  finance_actionability?: number
  risk_alignment?: number
}

const decColor = (d?: string) => (d === 'approve' ? '#22c55e' : '#ef4444')
const scoreColor = (s?: number) => (s == null ? 'var(--text2)' : s >= 8 ? '#34d399' : s >= 6 ? '#facc15' : '#f87171')
const LANE_ICON: Record<string, string> = { grok: '𝕏', chatgpt: '◎', local: '🖥', claude: '✶' }
const LANE_LABEL: Record<string, string> = { grok: 'Grok', chatgpt: 'ChatGPT', local: 'Gemma', claude: 'Claude' }

/** Map DB score to 0–10 (some rows store 0–1 fractions). */
export function normalizeScore10(val: unknown): number {
  const n = Number(val)
  if (!Number.isFinite(n)) return 0
  if (n > 0 && n <= 1) return Math.round(n * 100) / 10
  return n
}

/** DB rows store votes/lanes_used as JSON strings — normalize for the card. */
export function normalizeEnsembleResult(raw: any): EnsembleResult | null {
  if (!raw) return null
  try {
    const votes = typeof raw.votes === 'string' ? JSON.parse(raw.votes) : raw.votes
    const lanes_used = typeof raw.lanes_used === 'string' ? JSON.parse(raw.lanes_used) : raw.lanes_used
    if (!raw.final_decision && !votes?.length) return null
    const normVotes = (Array.isArray(votes) ? votes : []).map((v: EnsembleVote) => ({
      ...v,
      score: normalizeScore10(v.score),
    }))
    return {
      final_decision: raw.final_decision === 'approve' ? 'approve' : 'block',
      final_score: normalizeScore10(raw.final_score),
      final_confidence: Number(raw.final_confidence) || 0,
      consensus_reached: !!raw.consensus_reached,
      lanes_used: Array.isArray(lanes_used) ? lanes_used : [],
      votes: normVotes,
      reasoning_summary: raw.reasoning_summary,
      retirement_relevance: raw.retirement_relevance != null ? normalizeScore10(raw.retirement_relevance) : undefined,
      finance_actionability: raw.finance_actionability != null ? normalizeScore10(raw.finance_actionability) : undefined,
      risk_alignment: raw.risk_alignment != null ? normalizeScore10(raw.risk_alignment) : undefined,
    }
  } catch {
    return null
  }
}

// ── Pure display card ────────────────────────────────────────────────────────
// finance sub-scores: prefer the aggregate the backend put on the result; else average the per-lane votes.
const SUBS: { key: keyof EnsembleResult; vkey: keyof EnsembleVote; label: string }[] = [
  { key: 'retirement_relevance', vkey: 'retirement_relevance', label: 'retirement' },
  { key: 'finance_actionability', vkey: 'finance_actionability', label: 'finance' },
  { key: 'risk_alignment', vkey: 'risk_alignment', label: 'risk' },
]
const subColor = (v: number) => (v >= 7 ? '#34d399' : v >= 4 ? '#facc15' : '#f87171')

export function EnsembleValidationCard({ result, onRevalidate }: {
  result: EnsembleResult
  onRevalidate?: () => void
}) {
  const [open, setOpen] = useState(false)
  const votes = result.votes ?? []
  const subs = SUBS.map(s => {
    const agg = (result as any)[s.key]
    if (typeof agg === 'number') return { ...s, val: agg }
    const vals = votes.map(v => v[s.vkey]).filter((x): x is number => typeof x === 'number')
    return vals.length ? { ...s, val: Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10 } : null
  }).filter(Boolean) as { label: string; val: number }[]
  return (
    <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 10, marginTop: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{
          fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 99,
          color: decColor(result.final_decision), border: `1px solid ${decColor(result.final_decision)}`,
          background: result.final_decision === 'approve' ? 'rgba(34,197,94,.12)' : 'rgba(239,68,68,.12)',
        }}>{(result.final_decision || '—').toUpperCase()}</span>
        <span style={{ fontSize: 17, fontWeight: 700, fontFamily: 'monospace', color: scoreColor(result.final_score) }}>
          {result.final_score?.toFixed(1)}<span style={{ fontSize: 10, color: 'var(--text3)' }}>/10</span>
        </span>
        <span style={{ fontSize: 10, color: 'var(--text3)' }}>conf {Math.round((result.final_confidence ?? 0) * 100)}%</span>
        <span style={{ fontSize: 10, marginLeft: 'auto', color: result.consensus_reached ? '#22c55e' : '#f59e0b' }}>
          {result.consensus_reached ? '✓ consensus' : '⚠ split'}
        </span>
      </div>
      {subs.length > 0 && (
        <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
          {subs.map(s => (
            <span key={s.label} title={`${s.label} sub-score (0-10) — finance/retirement ensemble`} style={{
              fontSize: 9.5, fontWeight: 700, padding: '2px 8px', borderRadius: 99,
              background: 'var(--bg1)', border: `1px solid ${subColor(s.val)}55`, color: subColor(s.val) }}>
              {s.label} {s.val.toFixed(1)}
            </span>
          ))}
        </div>
      )}
      {result.reasoning_summary && (
        <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4 }}>{result.reasoning_summary}</div>
      )}
      <div style={{ display: 'flex', gap: 8, marginTop: 6, alignItems: 'center' }}>
        <button onClick={() => setOpen(o => !o)} style={linkBtn}>
          {open ? 'Hide' : 'Show'} lane votes ({votes.length})
        </button>
        {onRevalidate && <button onClick={onRevalidate} style={linkBtn}>Re-validate</button>}
      </div>
      {open && (
        <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {votes.map((v, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: 10,
              padding: '4px 6px', background: 'var(--bg1)', borderRadius: 4 }}>
              <span style={{ width: 58, fontWeight: 700, color: 'var(--text1)' }}>
                {LANE_ICON[v.lane] || '•'} {v.lane}
              </span>
              <span style={{ color: scoreColor(v.score), fontFamily: 'monospace', width: 26 }}>{v.score?.toFixed(1)}</span>
              <span style={{ color: decColor(v.decision), width: 50 }}>{(v.decision || '').toUpperCase()}</span>
              {v.reasoning && <span style={{ color: 'var(--text3)', flex: 1 }}>{v.reasoning}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const linkBtn: React.CSSProperties = {
  fontSize: 10, color: '#60a5fa', background: 'none', border: 'none', cursor: 'pointer', padding: 0,
}

// ── Self-contained: button → enqueue → poll → render. Reusable on any surface. ──
export function EnsembleValidationInline({ targetType, targetId, subject, content, task, autoRequest, compact }: {
  targetType: string
  targetId: string | number
  subject?: string
  content: string
  task?: string
  /** Auto-enqueue if no fresh verdict (options desk). */
  autoRequest?: boolean
  compact?: boolean
}) {
  const [state, setState] = useState<'loading' | 'idle' | 'queued' | 'done' | 'error'>('loading')
  const [result, setResult] = useState<EnsembleResult | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval>>()
  const autoFired = useRef(false)

  // Read the latest persisted verdict / pending-job status for this target.
  const fetchOnce = useCallback(async (): Promise<'done' | 'pending' | 'none' | 'error'> => {
    try {
      const r = await fetch(`/api/v2/inference/ensemble?target_type=${targetType}&target_id=${targetId}`)
      const j = await r.json()
      const norm = normalizeEnsembleResult(j.result)
      if (norm) { setResult(norm); return 'done' }
      if (j.job?.status === 'queued' || j.job?.status === 'running') return 'pending'
      return 'none'
    } catch { return 'error' }
  }, [targetType, targetId])

  const poll = useCallback(() => {
    setState('queued')
    let tries = 0
    pollRef.current = setInterval(async () => {
      tries++
      const s = await fetchOnce()
      if (s === 'done') { setState('done'); clearInterval(pollRef.current) }
      else if (tries > 30) { setState('idle'); clearInterval(pollRef.current) }  // ~2min cap → allow retry
    }, 4000)
  }, [fetchOnce])

  // On mount: auto-display an existing verdict, resume polling a pending job, or
  // fall back to the manual validate button. This is what makes auto-enqueued
  // verdicts render on the card without an operator click.
  useEffect(() => {
    let cancelled = false
    fetchOnce().then(s => {
      if (cancelled) return
      if (s === 'done') setState('done')
      else if (s === 'pending') poll()
      else if (s === 'none' && autoRequest && !autoFired.current) { autoFired.current = true; request() }
      else setState('idle')
    })
    return () => { cancelled = true; clearInterval(pollRef.current) }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- request stable enough; autoFired prevents double enqueue
  }, [fetchOnce, poll, autoRequest])

  const request = useCallback(async () => {
    setState('queued'); setResult(null)
    try {
      await fetch('/api/v2/inference/ensemble/request', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_type: targetType, target_id: targetId, subject, content, task: task || 'inference_quality' }),
      })
      poll()
    } catch { setState('error') }
  }, [targetType, targetId, subject, content, task, poll])

  if (state === 'loading') return <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: compact ? 0 : 6 }}>checking Grok/ChatGPT/Gemma…</div>
  if (state === 'done' && result) {
    if (compact) {
      return (
        <div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, alignItems: 'center' }}>
            {(result.votes || []).map((v, i) => (
              <span key={i} title={v.reasoning || ''} style={{
                fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 5,
                color: v.decision === 'approve' ? '#22c55e' : '#ef4444',
                background: 'var(--bg1)', border: `1px solid ${v.decision === 'approve' ? '#22c55e44' : '#ef444444'}`,
                cursor: v.reasoning ? 'help' : undefined,
              }}>
                {LANE_ICON[v.lane] || '•'} {LANE_LABEL[v.lane] || v.lane} {v.score?.toFixed(1)} {(v.decision || '').toUpperCase()}
              </span>
            ))}
            <span style={{ fontSize: 9, fontWeight: 900, color: result.final_decision === 'approve' ? '#22c55e' : '#ef4444' }}>
              → {(result.final_decision || '').toUpperCase()} {result.final_score?.toFixed(1)}/10
            </span>
            <button onClick={request} style={{ ...linkBtn, marginLeft: 4 }}>re-run</button>
          </div>
          {result.reasoning_summary && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>{result.reasoning_summary}</div>}
        </div>
      )
    }
    return <EnsembleValidationCard result={result} onRevalidate={request} />
  }
  return (
    <button onClick={request} disabled={state === 'queued'} style={{
      fontSize: 10, marginTop: compact ? 0 : 6, padding: '3px 9px', borderRadius: 5, cursor: state === 'queued' ? 'default' : 'pointer',
      border: '1px solid var(--border)', background: 'var(--bg2)',
      color: state === 'error' ? '#f87171' : state === 'queued' ? 'var(--text3)' : '#a855f7',
    }}>
      {state === 'queued' ? '⏳ Grok + ChatGPT + Gemma validating…' : state === 'error' ? '⚠ validation failed — retry' : '⚖ Run Grok + ChatGPT + Gemma review'}
    </button>
  )
}

export default EnsembleValidationCard
