/**
 * WP-R3 — Arm re-entry-only Watch alerts (price zone + RSI).
 * Advisory notifications only — never orders / proposals / 2FA.
 * POSTs to existing /api/v2/watch/alerts (20-min RTH evaluator).
 */
import { useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { BB } from '../../lib/holdingsTerminalTokens'

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, padding: 12 }
const field: CSSProperties = {
  width: '100%', boxSizing: 'border-box', fontSize: 12, padding: '7px 9px',
  borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)',
}
const btn = (active = false): CSSProperties => ({
  fontSize: 11, fontWeight: 850, padding: '6px 12px', borderRadius: 4, cursor: 'pointer',
  border: `1px solid ${active ? BB.blue : 'var(--border)'}`,
  background: active ? BB.blueDim : 'var(--bg2)',
  color: active ? BB.blue : 'var(--text2)',
})

export type ReEntryAlertArmIntel = {
  entryLow: number | null
  entryHigh: number | null
  price: number | null
  rsi: number | null
}

type Props = {
  symbol: string
  intel: ReEntryAlertArmIntel
  short?: boolean
  onClose: () => void
  onArmed: (summary: string) => void
}

export default function ReEntryAlertArmModal({ symbol, intel, short = false, onClose, onArmed }: Props) {
  const defaultPrice = short
    ? (intel.entryLow ?? intel.entryHigh ?? intel.price)
    : (intel.entryHigh ?? intel.entryLow ?? intel.price)
  const [priceOn, setPriceOn] = useState(defaultPrice != null)
  const [priceType, setPriceType] = useState(short ? 'price_cross_above' : 'price_cross_below')
  const [price, setPrice] = useState(defaultPrice != null ? String(Number(defaultPrice).toFixed(2)) : '')
  const [rsiOn, setRsiOn] = useState(true)
  const [rsiType, setRsiType] = useState(short ? 'rsi_above' : 'rsi_below')
  const [rsi, setRsi] = useState(short ? '65' : '45')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const arm = async () => {
    const rules: { condition_type: string; threshold: number }[] = []
    if (priceOn) {
      const t = Number(price)
      if (!Number.isFinite(t) || t <= 0) {
        setError('Enter a valid price threshold.')
        return
      }
      rules.push({ condition_type: priceType, threshold: t })
    }
    if (rsiOn) {
      const t = Number(rsi)
      if (!Number.isFinite(t) || t < 0 || t > 100) {
        setError('Enter a valid RSI threshold (0–100).')
        return
      }
      rules.push({ condition_type: rsiType, threshold: t })
    }
    if (!rules.length) {
      setError('Select at least one alert condition.')
      return
    }
    setBusy(true)
    setError('')
    try {
      for (const rule of rules) {
        const response = await fetch('/api/v2/watch/alerts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action: 'arm',
            symbol,
            condition_type: rule.condition_type,
            threshold: rule.threshold,
            note: `reentry-desk ${symbol} advisory`,
            recurring: true,
          }),
        })
        const payload = await response.json().catch(() => ({}))
        const data = payload?.data ?? payload
        if (!response.ok || data?.ok === false) {
          throw new Error(data?.error || `arm failed (${response.status})`)
        }
      }
      onArmed(rules.map(r => `${r.condition_type} ${r.threshold}`).join(' + '))
    } catch (caught: any) {
      setError(caught?.message || 'Failed to arm alerts')
      setBusy(false)
    }
  }

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`${symbol} re-entry alerts`}
      data-testid="reentry-alert-arm-modal"
      style={{
        position: 'fixed', inset: 0, zIndex: 80,
        background: 'rgba(0,0,0,.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
      }}
      onClick={onClose}
    >
      <div
        style={{ ...panel, width: 'min(440px, 100%)', maxHeight: '90vh', overflow: 'auto' }}
        onClick={event => event.stopPropagation()}
      >
        <div style={{ fontSize: 16, fontWeight: 900, color: 'var(--text0)' }}>{symbol} · Re-Entry alerts</div>
        <div style={{ fontSize: 11, color: BB.text3, marginTop: 4, lineHeight: 1.45 }}>
          Persistent Watch notifications only. Advisory — never auto-buys, never places orders.
          Evaluator runs ~every 20 min RTH with Telegram batch + daily caps.
        </div>
        <div style={{ fontSize: 11, color: BB.text3, marginTop: 8 }}>
          Current: px {intel.price == null ? '—' : `$${intel.price.toFixed(2)}`}
          {' · '}RSI {intel.rsi == null ? '—' : intel.rsi.toFixed(1)}
          {' · '}zone{' '}
          {intel.entryLow == null && intel.entryHigh == null
            ? '—'
            : `$${(intel.entryLow ?? intel.entryHigh)!.toFixed(2)}${intel.entryHigh != null && intel.entryLow != null && intel.entryLow !== intel.entryHigh ? `–$${intel.entryHigh.toFixed(2)}` : ''}`}
        </div>

        <div style={{ ...panel, marginTop: 12, background: 'var(--bg2)' }}>
          <label style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)' }}>
            <input type="checkbox" checked={priceOn} onChange={e => setPriceOn(e.target.checked)} />{' '}
            Price reaches candidate zone
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 8, opacity: priceOn ? 1 : 0.45 }}>
            <select disabled={!priceOn} value={priceType} onChange={e => setPriceType(e.target.value)} style={field}>
              <option value="price_cross_below">Price crosses below</option>
              <option value="price_cross_above">Price crosses above</option>
            </select>
            <input disabled={!priceOn} type="number" step="any" value={price} onChange={e => setPrice(e.target.value)} style={field} />
          </div>
        </div>

        <div style={{ ...panel, marginTop: 10, background: 'var(--bg2)' }}>
          <label style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)' }}>
            <input type="checkbox" checked={rsiOn} onChange={e => setRsiOn(e.target.checked)} />{' '}
            RSI reaches review threshold
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 8, opacity: rsiOn ? 1 : 0.45 }}>
            <select disabled={!rsiOn} value={rsiType} onChange={e => setRsiType(e.target.value)} style={field}>
              <option value="rsi_below">RSI crosses below</option>
              <option value="rsi_above">RSI crosses above</option>
            </select>
            <input disabled={!rsiOn} type="number" min={0} max={100} value={rsi} onChange={e => setRsi(e.target.value)} style={field} />
          </div>
        </div>

        {error && <div style={{ marginTop: 10, color: BB.red, fontSize: 11 }}>{error}</div>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 14 }}>
          <button type="button" onClick={onClose} style={btn(false)} disabled={busy}>CANCEL</button>
          <button type="button" onClick={() => void arm()} style={btn(true)} disabled={busy} data-testid="reentry-arm-alerts-submit">
            {busy ? 'ARMING…' : 'ARM ALERTS'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
