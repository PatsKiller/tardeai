/** Tax lots tab — first-class panel (WP-E). */
import type { CSSProperties } from 'react'
import { fmt$ } from '../lib/format'
import { accountFullName } from '../lib/holdingsRowModel'

type Props = {
  taxLots: any
  loading?: boolean
  error?: string | null
  terminalUi?: boolean
  panelStyle?: CSSProperties
}

export default function TaxPanel({ taxLots, loading, error, panelStyle }: Props) {
  if (loading && !taxLots) {
    return <div data-testid="tax-panel" style={{ color: 'var(--text3)', fontSize: 12, padding: 20 }}>Loading tax lots…</div>
  }
  if (error && !taxLots) {
    return (
      <div data-testid="tax-panel" style={{ color: 'var(--text3)', fontSize: 12, padding: 20, border: '1px solid var(--border)', borderRadius: 8 }}>
        Tax lots unavailable: {error}
      </div>
    )
  }
  const lots = Array.isArray(taxLots?.lots) ? taxLots.lots : []
  const asOf = taxLots?.as_of || taxLots?.generated_at || null

  return (
    <div data-testid="tax-panel" className={undefined} style={panelStyle || { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8, display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <span>Tax lots ({taxLots?.count ?? lots.length})</span>
        {taxLots?.total_unrealized_gain != null && (
          <span style={{ fontSize: 12, fontWeight: 800, color: 'var(--text1)' }}>
            {taxLots.total_unrealized_gain >= 0 ? '+' : ''}{fmt$(taxLots.total_unrealized_gain, 0)} unrealized
          </span>
        )}
        {taxLots?.reconciled_to_holdings === false && (
          <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text3)' }}>not reconciled to holdings</span>
        )}
        {asOf && <span style={{ fontSize: 10, color: 'var(--text3)', marginLeft: 'auto' }}>As of {String(asOf).slice(0, 19)}</span>}
      </div>
      {(taxLots?.harvest_candidates ?? 0) > 0 && (
        <div style={{ marginBottom: 10, padding: '6px 10px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, fontSize: 11, color: 'var(--text2)' }}>
          {taxLots.harvest_candidates} taxable-loss harvest candidate{taxLots.harvest_candidates === 1 ? '' : 's'}
          {taxLots?.worthless_security_loss ? ` · incl. ${fmt$(taxLots.worthless_security_loss, 0)} worthless-security losses` : ''}
        </div>
      )}
      {lots.length === 0 && (
        <div style={{ fontSize: 12, color: 'var(--text3)', padding: '12px 0' }}>
          No lot rows returned. Source: <code>/api/v2/tax-lots</code>.
        </div>
      )}
      {lots.length > 0 && (
        <div style={{ overflowX: 'auto', marginBottom: 10 }}>
          <table role="table" aria-label="Tax lots" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ color: 'var(--text3)' }}>
                <th scope="col" style={{ textAlign: 'left', padding: '4px 8px' }}>Symbol</th>
                <th scope="col" style={{ textAlign: 'left', padding: '4px 8px' }}>Account</th>
                <th scope="col" style={{ textAlign: 'right', padding: '4px 8px' }}>Shares</th>
                <th scope="col" style={{ textAlign: 'right', padding: '4px 8px' }}>Cost basis</th>
                <th scope="col" style={{ textAlign: 'right', padding: '4px 8px' }}>Value</th>
                <th scope="col" style={{ textAlign: 'right', padding: '4px 8px' }}>Unrealized</th>
                <th scope="col" style={{ textAlign: 'right', padding: '4px 8px' }}>%</th>
                <th scope="col" style={{ textAlign: 'left', padding: '4px 8px' }}>Term</th>
              </tr>
            </thead>
            <tbody>
              {lots.map((l: any, i: number) => (
                <tr key={i} style={{ borderTop: '1px solid var(--border)', color: 'var(--text1)' }}>
                  <td style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 700, color: 'var(--text0)' }}>{l.symbol}{l.worthless ? ' *' : ''}</td>
                  <td style={{ textAlign: 'left', padding: '4px 8px', color: 'var(--text3)' }}>{accountFullName(String(l.account || ''))}</td>
                  <td style={{ textAlign: 'right', padding: '4px 8px', fontFamily: 'monospace' }}>{l.shares}</td>
                  <td style={{ textAlign: 'right', padding: '4px 8px', fontFamily: 'monospace' }}>{fmt$(l.cost_basis, 0)}</td>
                  <td style={{ textAlign: 'right', padding: '4px 8px', fontFamily: 'monospace' }}>{fmt$(l.current_value, 0)}</td>
                  <td style={{ textAlign: 'right', padding: '4px 8px', fontFamily: 'monospace', fontWeight: 700 }}>{(l.unrealized_gain ?? 0) >= 0 ? '+' : ''}{fmt$(l.unrealized_gain, 0)}</td>
                  <td style={{ textAlign: 'right', padding: '4px 8px', fontFamily: 'monospace' }}>{l.gain_pct}%</td>
                  <td style={{ textAlign: 'left', padding: '4px 8px', color: 'var(--text3)' }}>{l.holding_period}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div style={{ fontSize: 10, color: 'var(--text3)' }}>{taxLots?.data_note ?? 'Source: /api/v2/tax-lots — advisory only; confirm with tax counsel before harvest actions.'}</div>
    </div>
  )
}
