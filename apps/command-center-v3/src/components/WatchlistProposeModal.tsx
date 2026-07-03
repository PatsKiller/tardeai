import { useState } from 'react'
import type { Ladder } from '../lib/exitLadder'

const MUTED = '#94a3b8'
const TEXT0 = '#f8fafc'
const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const overlay = { position: 'fixed' as const, inset: 0, background: 'rgba(2,6,23,.78)', zIndex: 9000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }
const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 16, padding: 22, width: 'min(560px, 96vw)', maxHeight: '92vh', overflow: 'auto', boxShadow: '0 24px 80px rgba(0,0,0,.45)' }

function money(v: number | null | undefined) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return `$${Number(v).toFixed(2)}`
}

export type WatchlistProposeSeed = {
  it: any
  entry: number | null
  stop: number | null
  planTarget: number | null
  rr: number | null
  ladder: Ladder | null
  pa?: any
}

type Props = {
  seed: WatchlistProposeSeed
  onClose: () => void
  onProposed?: (res: { proposal_id?: number; symbol: string; message?: string }) => void
}

export default function WatchlistProposeModal({ seed, onClose, onProposed }: Props) {
  const { it, entry, stop, planTarget, rr, ladder, pa } = seed
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const cioLabel = it.latest_recommendation
    ? String(it.latest_recommendation).replace(/_/g, ' ')
    : (pa?.rec ? String(pa.rec).replace(/_/g, ' ') : 'watch')
  const conf = it.research_confidence ?? it.hermes_score_components?._confidence

  const queueProposal = async () => {
    if (!entry || !stop || !planTarget || entry <= stop || planTarget <= entry) {
      setMsg('Plan incomplete — need limit, stop, and target')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      const r = await fetch(`/api/v2/watchlist/${it.symbol}/propose`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          entry, stop, target: planTarget, shares: 10, source: 'watchlist_card',
        }),
      }).then(x => x.json())
      const payload = r.data ?? r
      if (r.ok || payload.ok) {
        const pid = payload.proposal_id
        setMsg(`✅ ${payload.message || `Queued proposal #${pid}`}`)
        onProposed?.({ proposal_id: pid, symbol: it.symbol, message: payload.message })
        setTimeout(onClose, 1400)
      } else {
        setMsg('⛔ ' + (payload.error || r.error || 'queue failed'))
      }
    } catch (e: any) {
      setMsg('⛔ ' + String(e).slice(0, 80))
    } finally {
      setBusy(false)
    }
  }

  const openDesk = () => {
    window.location.href = `/v3/trading?tab=Entry+Desk&symbol=${it.symbol}`
  }

  return (
    <div style={overlay} onClick={onClose}>
      <div style={card} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 900, color: TEXT0 }}>
              Review & propose · <span style={{ fontFamily: 'monospace' }}>{it.symbol}</span>
            </div>
            <div style={{ fontSize: 11, color: MUTED, marginTop: 5, lineHeight: 1.45 }}>
              Confirm plan levels before sending to the broker proposal queue. Does not place live orders.
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: MUTED, cursor: 'pointer', fontSize: 22, lineHeight: 1 }}>×</button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 14 }}>
          {[
            { label: 'Limit', value: money(entry) },
            { label: 'Stop', value: money(stop) },
            { label: 'Target', value: money(planTarget) },
            { label: 'R:R', value: rr != null ? rr.toFixed(2) : '—' },
          ].map(m => (
            <div key={m.label} style={{ padding: '10px 12px', borderRadius: 10, background: 'rgba(15,23,42,.55)', border: '1px solid rgba(148,163,184,.15)' }}>
              <div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase', letterSpacing: '0.35px', marginBottom: 4 }}>{m.label}</div>
              <div style={{ fontSize: 15, fontWeight: 800, color: TEXT0, fontFamily: 'monospace' }}>{m.value}</div>
            </div>
          ))}
        </div>

        <div style={{ fontSize: 10.5, color: MUTED, marginBottom: 12, lineHeight: 1.5 }}>
          <span><b style={{ color: MUTED }}>CIO</b> {cioLabel}</span>
          {conf != null && <span> · <b style={{ color: MUTED }}>Conf</b> {Number(conf).toFixed(2)}</span>}
          {it.entry_urgency && <span> · <b style={{ color: MUTED }}>Urgency</b> {String(it.entry_urgency).replace(/_/g, ' ')}</span>}
        </div>

        {ladder && ladder.steps.length > 0 && (
          <div style={{ marginBottom: 14, padding: '10px 12px', borderRadius: 10, background: 'rgba(15,23,42,.4)', border: '1px solid rgba(148,163,184,.12)' }}>
            <div style={{ fontSize: 9, fontWeight: 800, color: MUTED, textTransform: 'uppercase', marginBottom: 6 }}>Exit ladder</div>
            {ladder.steps.map((s, i) => (
              <div key={i} style={{ fontSize: 10, color: '#cbd5e1', marginTop: i ? 3 : 0, fontFamily: 'monospace' }}>
                {s.label} {s.px.toFixed(2)} — <span style={{ color: MUTED, fontFamily: 'inherit' }}>{s.action}</span>
              </div>
            ))}
            <div style={{ fontSize: 9, color: MUTED, marginTop: 6 }}>R ${ladder.R.toFixed(2)}/sh</div>
          </div>
        )}

        {msg && (
          <div style={{
            fontSize: 11, marginBottom: 12, padding: '8px 10px', borderRadius: 8,
            background: msg.startsWith('✅') ? 'rgba(34,197,94,.12)' : 'rgba(245,158,11,.12)',
            color: msg.startsWith('✅') ? GREEN : AMBER,
          }}>{msg}</div>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <button onClick={onClose} style={{ fontSize: 11, fontWeight: 700, padding: '9px 16px', borderRadius: 8, border: '1px solid var(--border)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>Cancel</button>
          <button onClick={openDesk} style={{ fontSize: 11, fontWeight: 700, padding: '9px 16px', borderRadius: 8, border: '1px solid var(--border)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>Open Entry Desk</button>
          <button onClick={queueProposal} disabled={busy} style={{ fontSize: 12, fontWeight: 800, padding: '9px 20px', borderRadius: 8, border: 'none', background: GREEN, color: '#fff', cursor: busy ? 'wait' : 'pointer', opacity: busy ? 0.7 : 1 }}>
            {busy ? 'Queuing…' : 'Send to proposal queue'}
          </button>
        </div>
      </div>
    </div>
  )
}