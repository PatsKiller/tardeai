import { useEffect, useState, type CSSProperties } from 'react'
import { fmt$ } from '../lib/format'
import { BB } from '../lib/holdingsTerminalTokens'

export type ShareDriftItem = {
  id: number
  account_key: string
  symbol: string
  system_shares: number
  broker_shares: number
  drift_amount: number
  source: string
  status: string
  message?: string
  notes?: string
  impact?: any
}

type Props = {
  item: ShareDriftItem | null
  open: boolean
  onClose: () => void
  onApplied?: () => void
}

/**
 * Approval modal for share-count drift (dividend reinvestment, etc.).
 * Never auto-updates broker stops — only system shares in holdings.json.
 */
export default function ShareReconciliationModal({ item, open, onClose, onApplied }: Props) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [impact, setImpact] = useState<any>(null)
  const [showImpact, setShowImpact] = useState(false)
  const [done, setDone] = useState('')

  useEffect(() => {
    setErr('')
    setDone('')
    setShowImpact(false)
    setImpact(item?.impact || null)
    if (!open || !item) return
    if (item.impact) return
    const q = new URLSearchParams({ account: item.account_key, symbol: item.symbol })
    fetch(`/api/v2/holdings/share-drift/impact?${q}`)
      .then(r => r.json())
      .then(j => setImpact(j?.data || j))
      .catch(() => {})
  }, [open, item?.id, item?.account_key, item?.symbol])

  if (!open || !item) return null

  const drift = item.drift_amount
  const sign = drift >= 0 ? `+${drift}` : String(drift)
  const srcLabel = (item.source || 'unknown').replace(/_/g, ' ')

  const apply = async () => {
    setBusy(true); setErr('')
    try {
      const r = await fetch('/api/v2/holdings/share-drift/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account: item.account_key,
          symbol: item.symbol,
          task_id: item.id,
          source: item.source || 'dividend_reinvestment',
          notes: 'Operator approved via ShareReconciliationModal',
        }),
      })
      const j = await r.json()
      const d = j?.data || j
      if (!d?.ok) {
        setErr(d?.error || 'Update failed')
        setBusy(false)
        return
      }
      setDone(d.message || 'System shares updated')
      setBusy(false)
      onApplied?.()
      setTimeout(onClose, 900)
    } catch (e: any) {
      setErr(e?.message || 'request failed')
      setBusy(false)
    }
  }

  const snooze = async (days: number) => {
    setBusy(true); setErr('')
    try {
      const r = await fetch('/api/v2/holdings/share-drift/snooze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: item.id, days }),
      })
      const j = await r.json()
      const d = j?.data || j
      if (!d?.ok) {
        setErr(d?.error || 'Snooze failed')
        setBusy(false)
        return
      }
      setBusy(false)
      onApplied?.()
      onClose()
    } catch (e: any) {
      setErr(e?.message || 'request failed')
      setBusy(false)
    }
  }

  return (
    <div
      data-testid="share-recon-modal"
      style={{
        position: 'fixed', inset: 0, zIndex: 1200, display: 'flex', alignItems: 'center',
        justifyContent: 'center', background: 'rgba(2,6,12,.65)', padding: 16,
      }}
      onClick={onClose}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 'min(520px, 96vw)', maxHeight: '90vh', overflowY: 'auto',
          background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 12,
          boxShadow: '0 20px 60px rgba(0,0,0,.55)', padding: '18px 20px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 800, color: BB.amber, textTransform: 'uppercase', letterSpacing: 0.5 }}>
              Share reconciliation
            </div>
            <div style={{ fontSize: 18, fontWeight: 800, color: BB.text0, fontFamily: BB.mono, marginTop: 4 }}>
              {item.symbol}
            </div>
            <div style={{ fontSize: 11, color: BB.text3, marginTop: 2 }}>
              {item.account_key.replace(/_/g, ' ')} · {srcLabel}
            </div>
          </div>
          <button type="button" onClick={onClose} style={{
            background: 'transparent', border: 'none', color: BB.text3, fontSize: 22, cursor: 'pointer',
          }}>×</button>
        </div>

        <div style={{
          marginTop: 14, padding: '12px 14px', borderRadius: 8,
          background: BB.amberDim, border: `1px solid ${BB.amber}44`,
          fontSize: 13, color: BB.text1, lineHeight: 1.5,
        }}>
          {item.message || (
            <>
              {item.symbol} share count drift. System shows <b>{item.system_shares}</b> shares.
              Broker shows <b>{item.broker_shares}</b> shares ({sign}).
              Update system position to match actual ownership?
            </>
          )}
        </div>

        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginTop: 14,
        }}>
          {[
            ['System', item.system_shares, BB.text2],
            ['Broker', item.broker_shares, BB.green],
            ['Delta', sign, drift >= 0 ? BB.green : BB.red],
          ].map(([lab, val, col]) => (
            <div key={String(lab)} style={{
              background: BB.bgRow, border: `1px solid ${BB.border}`, borderRadius: 8, padding: '10px 12px',
            }}>
              <div style={{ fontSize: 9, color: BB.text3, textTransform: 'uppercase' }}>{lab}</div>
              <div style={{ fontSize: 16, fontWeight: 800, fontFamily: BB.mono, color: col as string, marginTop: 4 }}>
                {val as any}
              </div>
            </div>
          ))}
        </div>

        {impact?.ok && (
          <div style={{ marginTop: 14 }}>
            <button
              type="button"
              onClick={() => setShowImpact(s => !s)}
              style={{
                fontSize: 11, fontWeight: 700, padding: '5px 10px', borderRadius: 6, cursor: 'pointer',
                border: `1px solid ${BB.border}`, background: BB.bgRow, color: BB.text2,
              }}
            >
              {showImpact ? 'Hide impact' : 'Review impact on stops & risk'}
            </button>
            {showImpact && (
              <div style={{
                marginTop: 8, padding: '10px 12px', borderRadius: 8,
                background: BB.bgRow, border: `1px solid ${BB.border}`, fontSize: 12, color: BB.text1,
              }}>
                <div>Position value: {fmt$(impact.old_market_value, 0)} → <b>{fmt$(impact.new_market_value, 0)}</b></div>
                <div>Portfolio weight: {impact.old_portfolio_pct?.toFixed?.(2) ?? '—'}% → <b>{impact.new_portfolio_pct?.toFixed?.(2) ?? '—'}%</b></div>
                {impact.live_stop && (
                  <div style={{ marginTop: 6 }}>
                    Live stop qty: <b style={{ fontFamily: BB.mono }}>{impact.live_stop.qty ?? '—'}</b>
                    {impact.live_stop.stop_price != null && <> @ ${Number(impact.live_stop.stop_price).toFixed(2)}</>}
                    {impact.stop_coverage_after && <> · after update: <b>{impact.stop_coverage_after}</b></>}
                  </div>
                )}
                {impact.warn_live_stop && (
                  <div style={{
                    marginTop: 8, padding: '8px 10px', borderRadius: 6, background: 'rgba(239,68,68,.12)',
                    border: `1px solid ${BB.red}55`, color: BB.red, fontWeight: 700, fontSize: 11, lineHeight: 1.45,
                  }}>
                    ⚠ {impact.warn_message}
                  </div>
                )}
                {impact.whole_share_note && (
                  <div style={{ marginTop: 6, fontSize: 10, color: BB.text3 }}>{impact.whole_share_note}</div>
                )}
              </div>
            )}
          </div>
        )}

        {err && <div style={{ marginTop: 10, color: BB.red, fontSize: 12 }}>{err}</div>}
        {done && <div style={{ marginTop: 10, color: BB.green, fontSize: 12, fontWeight: 700 }}>{done}</div>}

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 16 }}>
          <button
            type="button"
            data-testid="share-recon-update"
            disabled={busy}
            onClick={apply}
            style={{
              flex: 1, minWidth: 140, padding: '10px 14px', borderRadius: 8, cursor: busy ? 'wait' : 'pointer',
              border: `2px solid ${BB.amber}`, background: 'rgba(255,176,0,.22)',
              color: BB.amberAlt, fontWeight: 800, fontSize: 13,
            }}
          >
            {busy ? 'Updating…' : 'Update system shares'}
          </button>
          <button type="button" disabled={busy} onClick={() => snooze(1)} style={snoozeBtn}>
            Snooze 1d
          </button>
          <button type="button" disabled={busy} onClick={() => snooze(7)} style={snoozeBtn}>
            Snooze 7d
          </button>
          <button type="button" disabled={busy} onClick={onClose} style={snoozeBtn}>
            Cancel
          </button>
        </div>
        <div style={{ fontSize: 9, color: BB.text3, marginTop: 10, lineHeight: 1.4 }}>
          Updates Trade AI system shares only (holdings.json). Does not place, cancel, or replace live Schwab/Fidelity orders.
        </div>
      </div>
    </div>
  )
}

const snoozeBtn: CSSProperties = {
  padding: '8px 12px', borderRadius: 8, cursor: 'pointer', fontSize: 11, fontWeight: 700,
  border: `1px solid ${BB.border}`, background: BB.bgRow, color: BB.text2,
}

/** Amber pill for holdings rows when share drift is pending. */
export function ShareDriftPill({
  onClick, compact,
}: { onClick?: () => void; compact?: boolean }) {
  return (
    <button
      type="button"
      data-testid="share-drift-pill"
      onClick={e => { e.stopPropagation(); onClick?.() }}
      title="Broker share count differs from system — click to reconcile"
      style={{
        fontSize: compact ? 8 : 9, fontWeight: 800, padding: compact ? '1px 5px' : '2px 7px',
        borderRadius: 999, cursor: 'pointer', letterSpacing: 0.2,
        border: `1px solid ${BB.amber}66`, background: BB.amberDim, color: BB.amberAlt,
        whiteSpace: 'nowrap',
      }}
    >
      Shares need update
    </button>
  )
}
