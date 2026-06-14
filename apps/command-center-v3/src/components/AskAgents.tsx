// AskAgents — contextual "ask the CIO/agents" box. Sends a natural-language question to
// /api/v2/portfolio/ask, which pulls the user's REAL positions + analyst ratings + look-through and
// routes to Grok. Reusable on any portfolio page.
import { useState } from 'react'

const EXAMPLES = [
  "What's the R:R of trimming 5% of V to fund SpaceX exposure? V is a strong buy.",
  "Am I over-concentrated in AI? What should I trim first?",
  "If I sell NVDA down to 3%, what do I give up vs. the analyst target?",
]

export default function AskAgents({ examples = EXAMPLES }: { examples?: string[] }) {
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<any>(null)

  const ask = async (question?: string) => {
    const text = (question ?? q).trim()
    if (!text) return
    setQ(text); setBusy(true); setRes(null)
    try {
      const r = await fetch('/api/v2/portfolio/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text }),
      })
      setRes(await r.json())
    } catch (e: any) { setRes({ ok: false, error: String(e?.message || e) }) }
    finally { setBusy(false) }
  }

  const ctx = res?.context
  return (
    <div style={{ background: 'rgba(96,165,250,.06)', border: '1px solid rgba(96,165,250,.28)', borderRadius: 10, padding: 12, marginBottom: 12 }}>
      <div style={{ fontSize: 11, fontWeight: 800, color: '#60a5fa', marginBottom: 6 }}>💬 ASK THE AGENTS — about your real positions</div>
      <div style={{ display: 'flex', gap: 6 }}>
        <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') ask() }}
          placeholder="e.g. R:R of trimming 5% V to get SpaceX exposure?"
          style={{ flex: 1, fontSize: 12, padding: '8px 11px', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
        <button onClick={() => ask()} disabled={busy || !q.trim()}
          style={{ fontSize: 12, fontWeight: 700, padding: '8px 16px', borderRadius: 7, border: 'none', cursor: busy ? 'wait' : 'pointer', background: busy || !q.trim() ? 'var(--bg2)' : '#1d4ed8', color: busy || !q.trim() ? 'var(--text3)' : '#fff' }}>
          {busy ? 'Analyzing…' : 'Ask'}
        </button>
      </div>
      {!res && !busy && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 7 }}>
          {examples.map((ex, i) => (
            <button key={i} onClick={() => ask(ex)} style={{ fontSize: 9.5, padding: '3px 8px', borderRadius: 10, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer' }}>{ex.length > 48 ? ex.slice(0, 48) + '…' : ex}</button>
          ))}
        </div>
      )}
      {busy && <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 8 }}>Pulling your positions + analyst data, asking the agents…</div>}
      {res && (
        <div style={{ marginTop: 10 }}>
          {res.ok === false ? (
            <div style={{ fontSize: 11, color: '#ef4444' }}>⚠ {res.error}</div>
          ) : (
            <>
              <div style={{ fontSize: 12, color: 'var(--text1)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{res.answer}</div>
              <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 8, alignItems: 'center' }}>
                <span style={{ fontSize: 8.5, color: 'var(--text4)' }}>using:</span>
                {(ctx?.positions ?? []).map((p: any, i: number) => (
                  <span key={i} title={p.private ? p.note : JSON.stringify(p.analyst ?? p.position ?? {})} style={{ fontSize: 9, padding: '2px 7px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: p.private ? '#f59e0b' : p.held ? '#22c55e' : 'var(--text3)', cursor: 'help' }}>
                    {p.symbol}{p.private ? ' (private)' : p.analyst?.rating ? ` · ${p.analyst.rating}` : ''}{p.position ? ` · ${p.position.pct}%` : ''}
                  </span>
                ))}
                <span style={{ fontSize: 8.5, color: 'var(--text4)', marginLeft: 'auto' }}>{res.model}</span>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
