// AskAgents — contextual "ask the CIO/agents" box. Sends a natural-language question to
// /api/v2/portfolio/ask, which pulls the user's REAL positions + analyst ratings + look-through and
// routes to Grok or ChatGPT (operator picks lane). Reusable on any portfolio page.
import { useState } from 'react'
import { runPortfolioAsk } from '../lib/cloudLlmRun'
import { useOAuthLanes, laneReady } from '../hooks/useOAuthLanes'

const EXAMPLES = [
  "What's the R:R of trimming 5% of V to fund SpaceX exposure? V is a strong buy.",
  "Am I over-concentrated in AI? What should I trim first?",
  "If I sell NVDA down to 3%, what do I give up vs. the analyst target?",
]

const GROK = '#1d9bf0', GPT = '#10a37f'

export default function AskAgents({ examples = EXAMPLES }: { examples?: string[] }) {
  const oauth = useOAuthLanes(0)
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState<'grok' | 'chatgpt' | null>(null)
  const [res, setRes] = useState<any>(null)
  const [alertMsg, setAlertMsg] = useState('')

  const setAlert = async () => {
    if (!res?.question) return
    setAlertMsg('saving…')
    try {
      const r = await fetch('/api/v2/portfolio/ask-alert', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: res.question, context: res.context }),
      })
      const d = await r.json()
      setAlertMsg(d.ok ? `🔔 Alert set (${d.alert?.kind}) — fires to Telegram when met` : `⚠ ${d.error}`)
    } catch (e: any) { setAlertMsg('⚠ ' + String(e?.message || e)) }
  }

  const ask = async (question?: string, lane?: 'grok' | 'chatgpt') => {
    const text = (question ?? q).trim()
    if (!text) return
    const useLane = lane ?? 'grok'
    if (!laneReady(useLane === 'grok' ? oauth.grok : oauth.chatgpt)) {
      setRes({ ok: false, error: `${useLane} OAuth not ready — Ops → Consumption` })
      return
    }
    setQ(text); setBusy(useLane); setRes(null)
    try {
      setRes(await runPortfolioAsk(text, useLane))
    } catch (e: any) { setRes({ ok: false, error: String(e?.message || e) }) }
    finally { setBusy(null) }
  }

  const ctx = res?.context
  const laneBtn = (lane: 'grok' | 'chatgpt', color: string) => (
    <button type="button" onClick={() => ask(undefined, lane)} disabled={!!busy || !q.trim()}
      style={{ fontSize: 12, fontWeight: 800, padding: '8px 14px', borderRadius: 7, cursor: busy ? 'wait' : 'pointer',
        border: `1px solid ${color}66`, background: `${color}14`, color,
        opacity: busy && busy !== lane ? 0.5 : 1 }}>
      {busy === lane ? 'Analyzing…' : lane === 'grok' ? '▶ Grok' : '▶ ChatGPT'}
    </button>
  )

  return (
    <div style={{ background: 'rgba(96,165,250,.06)', border: '1px solid rgba(96,165,250,.28)', borderRadius: 10, padding: 12, marginBottom: 12 }}>
      <div style={{ fontSize: 11, fontWeight: 800, color: '#60a5fa', marginBottom: 6 }}>💬 ASK THE AGENTS — about your real positions</div>
      <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 6 }}>Pick Grok or ChatGPT — either lane is enough</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && q.trim() && !busy) ask(undefined, 'grok') }}
          placeholder="e.g. R:R of trimming 5% V to get SpaceX exposure?"
          style={{ flex: 1, minWidth: 180, fontSize: 12, padding: '8px 11px', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
        {laneBtn('grok', GROK)}
        {laneBtn('chatgpt', GPT)}
      </div>
      {!res && !busy && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 7 }}>
          {examples.map((ex, i) => (
            <button key={i} onClick={() => { setQ(ex); ask(ex, 'grok') }} style={{ fontSize: 9.5, padding: '3px 8px', borderRadius: 10, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer' }}>{ex.length > 48 ? ex.slice(0, 48) + '…' : ex}</button>
          ))}
        </div>
      )}
      {busy && <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 8 }}>Pulling your positions + analyst data, asking via {busy}…</div>}
      {res && (
        <div style={{ marginTop: 10 }}>
          {res.ok === false || res.manual_required ? (
            <div style={{ fontSize: 11, color: '#ef4444' }}>⚠ {res.error || 'blocked — pick ▶ Grok or ▶ ChatGPT'}</div>
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
                <span style={{ fontSize: 8.5, color: 'var(--text4)', marginLeft: 'auto' }}>{res.model}{res.lane ? ` · ${res.lane}` : ''}</span>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
                <button onClick={setAlert} style={{ fontSize: 10, fontWeight: 700, padding: '4px 11px', borderRadius: 6, border: '1px solid #f59e0b', background: 'rgba(245,158,11,.14)', color: '#f59e0b', cursor: 'pointer' }}>🔔 Set this as an alert</button>
                {alertMsg && <span style={{ fontSize: 10, color: alertMsg.startsWith('⚠') ? '#ef4444' : '#22c55e' }}>{alertMsg}</span>}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}