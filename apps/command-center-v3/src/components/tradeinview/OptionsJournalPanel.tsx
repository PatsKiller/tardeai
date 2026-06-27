import { useApi } from '../../hooks/useApi'
import { fmt$ } from '../../lib/format'

export default function OptionsJournalPanel({ account, days }: { account?: string; days: number }) {
  const q = `/api/v2/journal/options-summary?days=${days}${account ? `&account=${account}` : ''}`
  const { data } = useApi<any>(q, 120_000)
  const d = data?.data ?? data
  const greeks = d?.book_greeks || {}
  return (
    <div>
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Options command center (journal lane)</div>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 8 }}>
          {d?.options_trades ?? 0} closed option rows · net {fmt$(d?.net_pnl, 0)} · WR {d?.win_rate ?? 0}%
        </div>
        {Object.keys(greeks).length > 0 && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 6, fontSize: 9, marginBottom: 8 }}>
            {['net_delta', 'net_gamma', 'net_theta', 'net_vega'].map(k => (
              <div key={k} style={{ background: 'var(--bg2)', padding: 6, borderRadius: 4 }}>
                <div style={{ color: 'var(--text3)' }}>{k.replace('net_', 'Δ ')}</div>
                <div style={{ fontWeight: 700 }}>{greeks[k] != null ? Number(greeks[k]).toFixed(2) : '—'}</div>
              </div>
            ))}
          </div>
        )}
        <div style={{ fontSize: 9, color: 'var(--text3)' }}>Full desk: <a href="/v3/options" style={{ color: '#60a5fa' }}>Options Hub</a></div>
      </div>
      {(d?.multileg_groups || []).length > 0 && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 6 }}>Multi-leg groups (by underlying + date)</div>
          {(d.multileg_groups || []).slice(0, 12).map((g: any, i: number) => (
            <div key={i} style={{ fontSize: 10, padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
              <span style={{ fontWeight: 700, fontFamily: 'monospace' }}>{g.underlying}</span>
              <span style={{ color: 'var(--text3)', marginLeft: 8 }}>{g.close_date}</span>
              <span style={{ marginLeft: 8 }}>{(g.legs || []).length} legs</span>
              <span style={{ float: 'right', color: (g.net_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(g.net_pnl, 0)}</span>
            </div>
          ))}
        </div>
      )}
      {(d?.open_legs || []).length > 0 && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 6 }}>Open option legs</div>
          {(d.open_legs || []).slice(0, 15).map((p: any, i: number) => (
            <div key={i} style={{ fontSize: 9, padding: '2px 0' }}>{p.underlying} {p.option_type} {p.strike} · {p.side} ×{p.qty}</div>
          ))}
        </div>
      )}
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
        <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 6 }}>Closed option trades</div>
        {(d?.trades || []).slice(0, 15).map((t: any, i: number) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
            <span style={{ fontFamily: 'monospace' }}>{t.symbol}</span>
            <span style={{ color: (t.pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(t.pnl, 0)}</span>
            <span style={{ color: 'var(--text3)' }}>{t.close_date}</span>
          </div>
        ))}
      </div>
    </div>
  )
}