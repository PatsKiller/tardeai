import { useState } from 'react'
import { useApi } from '../hooks/useApi'

// Broker Orders surface (Schwab program, dormant phase): draft intents + exact would-be broker payloads +
// per-trade TWO-FACTOR approval lifecycle (web + telegram), guard audit trail. Execution is permanently
// blocked this phase — the banner comes from the capabilities endpoint, not hardcoded UI text.
const mono = { fontFamily: 'JetBrains Mono, monospace' as const }

const STATE_C: Record<string, string> = {
  TRANSLATED: '#22c55e', BLOCKED: '#ef4444', DRAFT: '#60a5fa', VALIDATED: '#eab308',
}

function ApprovalPanel({ intentId }: { intentId: string }) {
  const { data: st, refetch } = useApi<any>(`/api/v2/broker-orders/approval-status?intent_id=${intentId}`, 15_000)
  const [code, setCode] = useState('')
  const [msg, setMsg] = useState('')
  const s = st?.data ?? st
  const chans: any[] = s?.channels ?? []
  const web = chans.find((c: any) => c.channel === 'web')
  const tg = chans.find((c: any) => c.channel === 'telegram')
  const post = async (path: string, body: any) => {
    const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    const j = await r.json(); setMsg(JSON.stringify(j?.data ?? j).slice(0, 140)); refetch()
  }
  const badge = (c: any, label: string) => (
    <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 4,
      background: (c?.status === 'confirmed' ? '#22c55e' : c?.status === 'pending' ? '#eab308' : 'var(--text3)') + '22',
      color: c?.status === 'confirmed' ? '#22c55e' : c?.status === 'pending' ? '#eab308' : 'var(--text3)' }}>
      {label}: {c?.status ?? '—'}
    </span>
  )
  return (
    <div style={{ marginTop: 8, padding: 8, background: 'var(--bg2)', borderRadius: 6 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)' }}>🔐 2FA approval</span>
        {badge(web, 'web')} {badge(tg, 'telegram')}
        {s?.fully_approved && <span style={{ fontSize: 9, fontWeight: 800, color: '#22c55e' }}>FULLY APPROVED (execution still blocked this phase)</span>}
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
        <button onClick={() => post('/api/v2/broker-orders/request-approval', { intent_id: intentId })}
          style={btn('#1d4ed8')}>Request approval (sends Telegram code)</button>
        <button onClick={() => post('/api/v2/broker-orders/approve', { intent_id: intentId, channel: 'web' })}
          style={btn('#15803d')}>Confirm — web channel</button>
        <input value={code} onChange={e => setCode(e.target.value)} placeholder="telegram code"
          style={{ fontSize: 10, width: 90, padding: '3px 6px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg1)', color: 'var(--text1)', ...mono }} />
        <button onClick={() => post('/api/v2/broker-orders/approve', { intent_id: intentId, channel: 'telegram', code })}
          style={btn('#7c3aed')}>Confirm — telegram code</button>
      </div>
      {msg && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 5, ...mono }}>{msg}</div>}
    </div>
  )
}

const btn = (bg: string) => ({ fontSize: 9, fontWeight: 600, padding: '3px 9px', borderRadius: 4,
  border: '1px solid var(--border)', background: bg + '33', color: '#fff', cursor: 'pointer' as const })

export default function BrokerOrders() {
  const { data: capsR } = useApi<any>('/api/v2/broker-orders/capabilities?broker=schwab', 120_000)
  const { data: draftsR, refetch } = useApi<any>('/api/v2/broker-orders/drafts?broker=schwab', 30_000)
  const { data: eventsR } = useApi<any>('/api/v2/broker-orders/events', 30_000)
  const [open, setOpen] = useState<string | null>(null)
  const caps = capsR?.data ?? capsR
  const drafts: any[] = (draftsR?.data ?? draftsR)?.drafts ?? []
  const events: any[] = (eventsR?.data ?? eventsR)?.events ?? []

  return (
    <div>
      {/* execution-disabled banner — text comes from backend capability truth */}
      <div style={{ padding: '10px 14px', background: 'rgba(239,68,68,.08)', border: '1px solid rgba(239,68,68,.3)', borderRadius: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 11, fontWeight: 800, color: '#ef4444' }}>EXECUTION DISABLED — {caps?.execution_mode}</span>
        <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 3 }}>{caps?.execution_disabled_notice}</div>
        <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 3 }}>
          Environment: {caps?.environment} · Stage 2a canary session: <b style={{ color: '#eab308' }}>PARKED — awaiting operator plan approval</b> (docs/brokers/stage2a-canary-protocol.md)
        </div>
      </div>

      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>
        Draft order intents ({drafts.length}) <button onClick={() => refetch()} style={btn('#374151')}>refresh</button>
      </div>
      {drafts.slice(0, 25).map((d: any) => (
        <div key={d.intent_id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, marginBottom: 8, background: 'var(--bg1)' }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', ...mono }}>{d.symbol}</span>
            <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
              background: (STATE_C[d.state] ?? 'var(--text3)') + '22', color: STATE_C[d.state] ?? 'var(--text3)' }}>{d.state}</span>
            <span style={{ fontSize: 9, color: 'var(--text3)' }}>{d.broker} · {String(d.updated_at).slice(0, 19)}</span>
            {d.blocked_reason && <span style={{ fontSize: 9, color: '#ef4444' }}>⛔ {String(d.blocked_reason).slice(0, 80)}</span>}
            <span style={{ flex: 1 }} />
            <button onClick={() => setOpen(open === d.intent_id ? null : d.intent_id)} style={btn('#374151')}>
              {open === d.intent_id ? 'close' : 'inspect'}
            </button>
          </div>
          {open === d.intent_id && (
            <div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 8 }}>
                <div>
                  <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text2)' }}>CANONICAL INTENT</div>
                  <pre style={{ fontSize: 8.5, color: 'var(--text2)', background: 'var(--bg2)', padding: 8, borderRadius: 6, maxHeight: 260, overflow: 'auto', ...mono }}>
                    {JSON.stringify(d.intent_json, null, 1)}</pre>
                </div>
                <div>
                  <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text2)' }}>EXACT WOULD-BE SCHWAB PAYLOAD</div>
                  <pre style={{ fontSize: 8.5, color: '#86efac', background: 'var(--bg2)', padding: 8, borderRadius: 6, maxHeight: 260, overflow: 'auto', ...mono }}>
                    {JSON.stringify(d.translation_json, null, 1)}</pre>
                </div>
              </div>
              <ApprovalPanel intentId={d.intent_id} />
            </div>
          )}
        </div>
      ))}

      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', margin: '14px 0 6px' }}>Guard & state audit trail (latest 100)</div>
      <div style={{ maxHeight: 240, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 8, padding: 8, background: 'var(--bg1)' }}>
        {events.map((e: any, i: number) => (
          <div key={i} style={{ fontSize: 9, color: String(e.event).includes('BLOCK') ? '#ef4444' : 'var(--text2)', ...mono }}>
            {String(e.created_at).slice(5, 19)} · {e.event} {e.detail ? `— ${String(e.detail).slice(0, 90)}` : ''}
          </div>
        ))}
      </div>
      <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 8 }}>
        Source: /api/v2/broker-orders/* · every guard decision (grant or block) is audited · no execution path exists from this surface
      </div>
    </div>
  )
}
