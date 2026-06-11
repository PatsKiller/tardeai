import { useState } from 'react'
import { useApi } from '../hooks/useApi'

// Broker Orders surface (Schwab program, dormant phase): draft intents + exact would-be broker payloads +
// per-trade TWO-FACTOR approval lifecycle (web + telegram), guard audit trail. Execution is permanently
// blocked this phase — the banner comes from the capabilities endpoint, not hardcoded UI text.
const mono = { fontFamily: 'JetBrains Mono, monospace' as const }

const STATE_C: Record<string, string> = {
  TRANSLATED: '#22c55e', BLOCKED: '#ef4444', DRAFT: '#60a5fa', VALIDATED: '#eab308',
}

// plain-English rendering of a canonical intent — operators read sentences, not JSON
function humanSummary(it: any): { line: string; pills: string[]; purpose: string } {
  if (!it) return { line: '—', pills: [], purpose: '' }
  const q = it.quantity?.qty ?? it.quantity?.notional ?? it.quantity?.contracts
  const e = it.entry ?? {}
  const x = it.exit_policy ?? {}
  const entryTxt = e.method === 'MARKET' ? 'at market'
    : e.method === 'LIMIT' ? `limit $${e.limit_price ?? e.entry_range?.high ?? '?'}`
    : e.method === 'STOP' ? `buy-stop $${e.stop_price}`
    : e.method === 'STOP_LIMIT' ? `stop $${e.stop_price} / limit $${e.limit_price}`
    : (e.method ?? '').replace(/_/g, ' ').toLowerCase()
  const line = `${it.direction === 'SHORT' ? 'SELL SHORT' : 'BUY'} ${q} sh ${it.instrument?.symbol} ${entryTxt}`
  const pills: string[] = []
  if (x.stop?.price) pills.push(`stop $${x.stop.price}`)
  if (x.stop?.trail) pills.push(`trailing ${x.stop.trail.offset}${x.stop.trail.type === 'PERCENT' ? '%' : x.stop.trail.type === 'TICK' ? ' ticks' : '$'} off ${x.stop.trail.basis}`)
  if (!x.stop) pills.push('⚠ no stop')
  for (const t of (x.targets ?? [])) pills.push(`target $${t.price}${t.qty_pct < 100 ? ` (${t.qty_pct}%)` : ''}`)
  if (it.ladder) pills.push(`ladder ×${it.ladder.legs?.length}`)
  if (it.tif !== 'DAY') pills.push(it.tif)
  if (it.session !== 'NORMAL') pills.push(`session ${it.session}`)
  const purpose = it.meta?.thesis || 'test fixture from the Stage-1 translation review (not a real plan)'
  return { line, pills, purpose }
}

// audit trail: collapse runs of identical events into one line with a count
function groupEvents(events: any[]): { text: string; n: number; block: boolean; at: string }[] {
  const out: { text: string; n: number; block: boolean; at: string }[] = []
  for (const e of events) {
    const txt = String(e.event).startsWith('guard:')
      ? (String(e.event).includes('BLOCK')
        ? `Guard BLOCKED a ${String(e.event).split(':')[1]} attempt — ${String(e.detail).slice(0, 70)}`
        : `Guard allowed ${String(e.event).split(':')[1]} (${String(e.event).split(':')[3] ?? ''})`)
      : String(e.event).startsWith('state:')
        ? `Intent saved as ${String(e.event).slice(6)}`
        : `${e.event} ${e.detail ?? ''}`
    const last = out[out.length - 1]
    if (last && last.text === txt) { last.n += 1 } else {
      out.push({ text: txt, n: 1, block: String(e.event).includes('BLOCK'), at: String(e.created_at).slice(5, 16) })
    }
  }
  return out.slice(0, 25)
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
        <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)' }}>🔐 Two-factor approval</span>
        <span style={{ fontSize: 9, color: 'var(--text3)' }}>— before any FUTURE live order you must confirm in BOTH places: ① the green button here, ② the ✅ button Telegram sends</span>
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

      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 2 }}>
        Draft order intents <button onClick={() => refetch()} style={btn('#374151')}>refresh</button>
      </div>
      <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>
        A draft = a fully-specified order the system COULD send, with its exact Schwab translation — nothing
        here ever executes this phase. Most current drafts are Stage-1 review fixtures kept as the audit
        trail; identical fixtures are grouped.
      </div>
      {(() => {
        const seen: Record<string, { d: any; n: number }> = {}
        for (const d of drafts) {
          const h = humanSummary(d.intent_json)
          const k = `${d.symbol}|${h.line}|${h.pills.join(',')}`
          if (seen[k]) seen[k].n += 1; else seen[k] = { d, n: 1 }
        }
        return Object.values(seen).slice(0, 25)
      })().map(({ d, n }: any) => (
        <div key={d.intent_id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, marginBottom: 8, background: 'var(--bg1)' }}>
          {(() => { const h = humanSummary(d.intent_json); return (
          <div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 12.5, fontWeight: 800, color: 'var(--text0)' }}>{h.line}</span>
              {n > 1 && <span style={{ fontSize: 9, color: 'var(--text3)' }}>×{n} identical</span>}
              <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                background: (STATE_C[d.state] ?? 'var(--text3)') + '22', color: STATE_C[d.state] ?? 'var(--text3)' }}
                title="translates cleanly = converts to Schwab format with no errors">
                {d.state === 'TRANSLATED' ? 'translates cleanly' : d.state.toLowerCase()}</span>
              <span style={{ flex: 1 }} />
              <button onClick={() => setOpen(open === d.intent_id ? null : d.intent_id)} style={btn('#374151')}>
                {open === d.intent_id ? 'close' : 'details'}
              </button>
            </div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
              {h.pills.map((p2: string, i: number) => (
                <span key={i} style={{ fontSize: 9, padding: '1px 6px', borderRadius: 3,
                  background: p2.startsWith('⚠') ? 'rgba(245,158,11,.15)' : 'var(--bg2)',
                  color: p2.startsWith('⚠') ? '#f59e0b' : 'var(--text2)' }}>{p2}</span>
              ))}
            </div>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 3, fontStyle: 'italic' }}>
              Purpose: {h.purpose}
            </div>
            {d.blocked_reason && <div style={{ fontSize: 9, color: '#ef4444', marginTop: 2 }}>⛔ {String(d.blocked_reason).slice(0, 100)}</div>}
          </div>
          )})()}
          {open === d.intent_id && (
            <div>
              <div style={{ fontSize: 9.5, color: 'var(--text2)', marginTop: 8, lineHeight: 1.5 }}>
                <b style={{ color: 'var(--text1)' }}>If this were live:</b>{' '}
                Schwab would receive {(d.translation_json?.orders ?? []).length} order(s).{' '}
                {(d.translation_json?.orders?.[0]?.orderStrategyType === 'TRIGGER')
                  ? 'The entry triggers the exit order(s) automatically once filled (bracket).'
                  : 'A single standalone order.'}{' '}
                {(d.translation_json?.unverified?.length > 0) &&
                  <span style={{ color: '#f59e0b' }}>Unverified vs Schwab runtime: {d.translation_json.unverified.join('; ')}. </span>}
                <span style={{ color: '#ef4444' }}>This phase: nothing is sent — preview only.</span>
              </div>
              <details style={{ marginTop: 6 }}>
                <summary style={{ fontSize: 9, color: 'var(--text3)', cursor: 'pointer' }}>show raw JSON (engineering view)</summary>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 6 }}>
                  <pre style={{ fontSize: 8, color: 'var(--text2)', background: 'var(--bg2)', padding: 8, borderRadius: 6, maxHeight: 220, overflow: 'auto', ...mono }}>
                    {JSON.stringify(d.intent_json, null, 1)}</pre>
                  <pre style={{ fontSize: 8, color: '#86efac', background: 'var(--bg2)', padding: 8, borderRadius: 6, maxHeight: 220, overflow: 'auto', ...mono }}>
                    {JSON.stringify(d.translation_json, null, 1)}</pre>
                </div>
              </details>
              <ApprovalPanel intentId={d.intent_id} />
            </div>
          )}
        </div>
      ))}

      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', margin: '14px 0 6px' }}>Safety log — what tried to happen, and what the guard did</div>
      <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>
        Every action attempt on a broker order is decided by the guard and logged. Identical repeats are
        grouped. Red = blocked (which is CORRECT this phase — nothing may execute).
      </div>
      <div style={{ maxHeight: 240, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 8, padding: 8, background: 'var(--bg1)' }}>
        {groupEvents(events).map((g, i: number) => (
          <div key={i} style={{ fontSize: 9.5, color: g.block ? '#ef4444' : '#22c55e', marginBottom: 2 }}>
            {g.at} · {g.text}{g.n > 1 ? `  (×${g.n})` : ''}
          </div>
        ))}
      </div>
      <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 8 }}>
        Source: /api/v2/broker-orders/* · every guard decision (grant or block) is audited · no execution path exists from this surface
      </div>
    </div>
  )
}
