import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { brokerOf, fmtMoney } from '../lib/brokerThesis'
import ActionButton from './ActionButton'

const MUTED = '#94a3b8'
const TEXT0 = '#f8fafc'
const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const RED = '#ef4444'
const BLUE = '#60a5fa'
const overlay = { position: 'fixed' as const, inset: 0, background: 'rgba(2,6,23,.82)', zIndex: 9100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }
const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 16, padding: 22, width: 'min(560px, 96vw)', maxHeight: '92vh', overflow: 'auto' }
const inp = { fontSize: 12, padding: '8px 10px', borderRadius: 8, border: '1px solid rgba(148,163,184,.28)', background: 'rgba(15,23,42,.6)', color: TEXT0, width: '100%', fontFamily: 'monospace' } as const
const lbl = { fontSize: 10, color: MUTED, display: 'block', marginBottom: 5, textTransform: 'uppercase' as const, letterSpacing: '0.4px' }

type Props = {
  proposal: any
  account: string
  accounts: { account_key: string; display_name?: string }[]
  onClose: () => void
  onRouted: (res: any) => void
}

function econ(shares: number, entry: number, stop: number, target: number) {
  const riskPs = entry - stop
  if (!shares || !entry || riskPs <= 0) return null
  const rewardPs = Math.max(target - entry, 0)
  return {
    investment: shares * entry,
    risk: riskPs * shares,
    profit: rewardPs > 0 ? rewardPs * shares : 0,
    rr: rewardPs > 0 ? rewardPs / riskPs : null,
  }
}

export default function BrokerRouteConfirmModal({ proposal, account, accounts, onClose, onRouted }: Props) {
  const [f, setF] = useState({
    account: account || proposal.account || '',
    shares: String(proposal.proposed_shares ?? ''),
    entry: String(proposal.proposed_entry ?? ''),
    stop: String(proposal.proposed_stop ?? ''),
    target: String(proposal.proposed_target1 ?? ''),
  })
  const [preview, setPreview] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [previewBusy, setPreviewBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const localEcon = useMemo(() => econ(
    Number(f.shares) || 0,
    Number(f.entry) || 0,
    Number(f.stop) || 0,
    Number(f.target) || 0,
  ), [f])

  const fetchPreview = useCallback(async (fields: typeof f) => {
    if (!fields.account || !fields.shares || !fields.entry || !fields.stop || !fields.target) return
    setPreviewBusy(true)
    try {
      const r = await fetch('/api/v2/broker-proposals/route-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          proposal_id: proposal.id,
          account: fields.account,
          shares: Number(fields.shares),
          entry: Number(fields.entry),
          stop: Number(fields.stop),
          target: Number(fields.target),
        }),
      }).then(x => x.json())
      const d = r.data ?? r
      if (r.ok) {
        setPreview(d)
        setMsg('')
      } else {
        setMsg(`⛔ ${r.error || d.error || 'preview failed'}`)
      }
    } catch (e: any) {
      setMsg(`⛔ ${String(e).slice(0, 80)}`)
    } finally {
      setPreviewBusy(false)
    }
  }, [proposal.id])

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => fetchPreview(f), 450)
    return () => { if (timer.current) clearTimeout(timer.current) }
  }, [f, fetchPreview])

  const request2fa = async () => {
    setBusy(true)
    setMsg('')
    try {
      const r = await fetch('/api/v2/broker-proposals/route', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          proposal_id: proposal.id,
          account: f.account,
          shares: Number(f.shares),
          entry: Number(f.entry),
          stop: Number(f.stop),
          target: Number(f.target),
        }),
      }).then(x => x.json())
      const d = r.data ?? r
      if (r.ok && d.mode === 'awaiting_approval') {
        onRouted(d)
        onClose()
      } else if (r.ok) {
        onRouted(d)
        onClose()
      } else {
        setMsg(`⛔ ${r.error || d.error || 'route failed'}`)
      }
    } catch (e: any) {
      setMsg(`⛔ ${String(e).slice(0, 80)}`)
    } finally {
      setBusy(false)
    }
  }

  const trade = preview?.trade || {}
  const blocks = trade.hard_blocks || preview?.evaluation?.violations || []
  const warns = trade.policy_warnings || preview?.evaluation?.warnings || []
  const allowed = trade.route_allowed !== false && !blocks.length

  return (
    <div style={overlay} onClick={onClose}>
      <div style={card} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 900, color: TEXT0, fontFamily: 'monospace' }}>{proposal.symbol}</div>
            <div style={{ fontSize: 11, color: MUTED, marginTop: 4 }}>
              Review trade · edit size/prices · then request 2FA
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: MUTED, fontSize: 18, cursor: 'pointer' }}>×</button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 12 }}>
          <label><span style={lbl}>Account</span>
            <select value={f.account} onChange={e => setF({ ...f, account: e.target.value })} style={inp}>
              {accounts.map(a => (
                <option key={a.account_key} value={a.account_key}>{a.display_name || a.account_key}</option>
              ))}
            </select>
          </label>
          <label><span style={lbl}>Shares</span>
            <input value={f.shares} onChange={e => setF({ ...f, shares: e.target.value })} style={inp} />
          </label>
          <label><span style={lbl}>Entry (limit)</span>
            <input value={f.entry} onChange={e => setF({ ...f, entry: e.target.value })} style={inp} />
          </label>
          <label><span style={lbl}>Stop</span>
            <input value={f.stop} onChange={e => setF({ ...f, stop: e.target.value })} style={inp} />
          </label>
          <label style={{ gridColumn: '1 / -1' }}><span style={lbl}>Target (OCO)</span>
            <input value={f.target} onChange={e => setF({ ...f, target: e.target.value })} style={inp} />
          </label>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 12 }}>
          <div style={{ padding: '10px 12px', borderRadius: 10, background: 'rgba(15,23,42,.55)', border: '1px solid rgba(148,163,184,.15)' }}>
            <div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase' }}>Risk</div>
            <div style={{ fontSize: 15, fontWeight: 800, color: RED, fontFamily: 'monospace' }}>
              {fmtMoney(trade.dollar_risk ?? localEcon?.risk)}
            </div>
          </div>
          <div style={{ padding: '10px 12px', borderRadius: 10, background: 'rgba(15,23,42,.55)', border: '1px solid rgba(148,163,184,.15)' }}>
            <div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase' }}>Invest</div>
            <div style={{ fontSize: 15, fontWeight: 800, color: TEXT0, fontFamily: 'monospace' }}>
              {fmtMoney(trade.dollar_size ?? localEcon?.investment)}
            </div>
          </div>
          <div style={{ padding: '10px 12px', borderRadius: 10, background: 'rgba(15,23,42,.55)', border: '1px solid rgba(148,163,184,.15)' }}>
            <div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase' }}>R:R @ tgt</div>
            <div style={{ fontSize: 15, fontWeight: 800, color: GREEN, fontFamily: 'monospace' }}>
              {trade.risk_reward ?? localEcon?.rr ? `${Number(trade.risk_reward ?? localEcon?.rr).toFixed(2)}:1` : '—'}
            </div>
          </div>
        </div>

        <div style={{ fontSize: 10, color: MUTED, marginBottom: 10, lineHeight: 1.5 }}>
          {previewBusy ? 'Recalculating…' : (
            <>
              <b style={{ color: BLUE }}>{brokerOf(f.account)}</b> OTOCO: BUY {f.shares} LIMIT ${Number(f.entry || 0).toFixed(2)} · STOP ${Number(f.stop || 0).toFixed(2)}
              {f.target ? ` · TGT $${Number(f.target).toFixed(2)}` : ''}
              {trade.cash_available != null ? ` · cash $${Number(trade.cash_available).toLocaleString()}` : ''}
            </>
          )}
        </div>

        {!!warns.length && (
          <div style={{ marginBottom: 10, padding: '8px 10px', borderRadius: 8, fontSize: 9.5, background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.25)', color: AMBER }}>
            {warns.map((w: string, i: number) => <div key={i}>⚠ {w}</div>)}
          </div>
        )}
        {!!blocks.length && (
          <div style={{ marginBottom: 10, padding: '8px 10px', borderRadius: 8, fontSize: 9.5, background: 'rgba(239,68,68,.08)', border: '1px solid rgba(239,68,68,.25)', color: RED }}>
            {blocks.map((v: string, i: number) => <div key={i}>⛔ {v}</div>)}
          </div>
        )}
        {msg && <div style={{ fontSize: 10, color: msg.startsWith('⛔') ? RED : GREEN, marginBottom: 10 }}>{msg}</div>}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <ActionButton variant="secondary" onClick={onClose}>Cancel</ActionButton>
          <ActionButton
            variant="primary"
            loading={busy}
            disabled={!allowed || previewBusy}
            onClick={request2fa}
            style={{ background: `${AMBER}33`, color: AMBER, border: `1px solid ${AMBER}` }}
          >
            Request 2FA → Schwab
          </ActionButton>
        </div>
      </div>
    </div>
  )
}