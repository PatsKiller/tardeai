import React from 'react'
import { useApi } from '../hooks/useApi'

// Phase 192F/G — Inline ATM profit-protection advisory + adjustment panel (v2).
// Read-only / advisory. Buttons are review-gated; execution is operator-approved only
// via the guarded /approve endpoint (Phase 192I). Paper-only.

const badge = (text: string, color: string): React.CSSProperties => ({
  display: 'inline-block', fontSize: 8, fontWeight: 700, letterSpacing: '0.4px',
  textTransform: 'uppercase', padding: '2px 6px', borderRadius: 4,
  background: 'var(--bg1)', color, border: `1px solid ${color}`, marginLeft: 6,
})
const actionColor = (a: string): string =>
  a === 'URGENT_PROTECTION_REVIEW' ? 'var(--red)'
    : (a && a !== 'NO_ACTION') ? 'var(--amber, #d79a3a)' : 'var(--green)'

const cell: React.CSSProperties = { fontSize: 11, fontFamily: 'monospace', color: 'var(--text1)' }
const lbl: React.CSSProperties = { fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase' }

export default function ProtectionAdjustmentPanel() {
  const { data: adv } = useApi<any>('/api/v2/atm/profit-protection-advisory', 30000)
  const { data: props } = useApi<any>('/api/v2/atm/protection-adjustment-proposals', 60000)

  const advisories: any[] = adv?.advisories || []
  const propTrades: any[] = props?.trades || []
  const propsFor = (tid: number) =>
    (propTrades.find((t: any) => t.trade_id === tid)?.candidates) || []

  if (!advisories.length) return null

  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginTop: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Profit-Protection Advisory</span>
        <span style={badge('PAPER ONLY', 'var(--text3)')}>paper only</span>
        <span style={badge('ADVISORY', 'var(--text3)')}>no auto-execution</span>
      </div>
      {advisories.map((a: any) => {
        const t = a.tradeai || {}
        const h = a.hermes || {}
        return (
          <div key={a.trade_id} style={{ borderTop: '1px solid var(--border)', padding: '8px 0' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>{a.symbol}</span>
              <span style={badge(t.action || 'NO_ACTION', actionColor(t.action))}>{t.action}</span>
            </div>
            <div style={{ display: 'flex', gap: 16, marginTop: 4 }}>
              <div>
                <div style={lbl}>TradeAI</div>
                <div style={cell}>{t.reason}</div>
                <div style={cell}>
                  P&L {t.unrealized_pnl != null ? `$${t.unrealized_pnl}` : '—'} ({t.unrealized_pct}%) ·
                  stop {t.current_broker_stop} · locks {t.stop_locks_profit ? 'yes' : 'no'} ·
                  giveback ${t.giveback_to_stop_usd} · TP {t.take_profit_exists ? 'set' : 'missing'}
                </div>
              </div>
              <div>
                <div style={lbl}>Hermes</div>
                <div style={cell}>{h.opinion}: {h.reason}</div>
              </div>
            </div>
            {propsFor(a.trade_id).filter((c: any) => c.action !== 'KEEP_CURRENT_STOP').length > 0 && (
              <div style={{ marginTop: 6 }}>
                <div style={lbl}>Proposed adjustments (before → after)</div>
                {propsFor(a.trade_id).filter((c: any) => c.action !== 'KEEP_CURRENT_STOP').map((c: any) => (
                  <div key={c.id} style={{ ...cell, display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                    <span>{c.action}</span>
                    <span>
                      stop {c.current_stop ?? '—'}→{c.proposed_stop ?? '—'} ·
                      lock ${c.profit_locked_before}→${c.profit_locked_after} ·
                      giveback ${c.giveback_before}→${c.giveback_after}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
              {['Review Move Stop', 'Review Add Take-Profit', 'Review Trailing Stop',
                'Keep Current', 'Reject Advisory', 'Needs More Evidence'].map((b) => (
                <button key={b} disabled title="Operator approval required (Phase 192I)"
                  style={{ fontSize: 9, padding: '3px 8px', borderRadius: 5, cursor: 'not-allowed',
                    background: 'var(--bg1)', color: 'var(--text2)', border: '1px solid var(--border)', opacity: 0.8 }}>
                  {b}
                </button>
              ))}
            </div>
          </div>
        )
      })}
      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>
        Source: /api/v2/atm/profit-protection-advisory + /protection-adjustment-proposals. Advisory only —
        no stop is moved without explicit operator approval via the guarded endpoint.
      </div>
    </div>
  )
}
