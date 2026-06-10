import { useState } from 'react'
import { useApi } from '../hooks/useApi'

// ToS (thinkorswim) watchlists — Schwab Trader API has no watchlist endpoint, so these import from
// imports/tos_watchlists/. Manage: rename, match strategy, notes; view active + removed (with dates).
const STRATS = ['', 'swing_breakout', 'momentum_scalp', 'earnings_catalyst', 'core_growth_compounder', 'dividend_growth_compounder', 'covered_call_income']

export default function ToSWatchlists() {
  const { data, refetch } = useApi<any>('/api/v2/tos-watchlists', 60_000)
  const wls: any[] = data?.watchlists ?? []
  const [open, setOpen] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)

  const manage = async (watchlist_id: number, action: string, value: string) => {
    setBusy(true)
    try {
      await fetch('/api/v2/tos-watchlists/manage', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ watchlist_id, action, value }) })
      setTimeout(refetch, 400)
    } catch { /* */ }
    setBusy(false)
  }

  if (!wls.length) return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>ToS Watchlists</div>
      <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 4 }}>Schwab's API has no watchlist endpoint. Drop thinkorswim export CSVs into <code>imports/tos_watchlists/</code> — each file becomes a managed watchlist (rename · match strategy · notes · add/remove dates tracked).</div>
    </div>
  )

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 2 }}>ToS Watchlists ({wls.length})</div>
      <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>thinkorswim imports (Schwab API has no watchlists) · rename · match strategy · notes · add/remove dates</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {wls.map((w: any) => (
          <div key={w.id} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <input defaultValue={w.display_name || w.name} onBlur={e => e.target.value !== (w.display_name || w.name) && manage(w.id, 'rename', e.target.value)}
                style={{ flex: '0 0 200px', fontSize: 12, fontWeight: 700, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg1)', color: 'var(--text0)' }} />
              <select defaultValue={w.strategy_match || ''} onChange={e => manage(w.id, 'strategy', e.target.value)}
                style={{ fontSize: 11, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg1)', color: 'var(--text1)' }}>
                {STRATS.map(s => <option key={s} value={s}>{s || '— match strategy —'}</option>)}
              </select>
              <span style={{ fontSize: 10, color: '#22c55e' }}>{w.active?.length || 0} active</span>
              {w.removed?.length > 0 && <span style={{ fontSize: 10, color: 'var(--text3)' }}>· {w.removed.length} removed</span>}
              <span style={{ flex: 1 }} />
              <button onClick={() => setOpen(open === w.id ? null : w.id)} style={{ fontSize: 10, padding: '3px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg1)', color: 'var(--text2)', cursor: 'pointer' }}>{open === w.id ? 'hide' : 'symbols'}</button>
            </div>
            <input defaultValue={w.notes || ''} placeholder="notes…" disabled={busy} onBlur={e => e.target.value !== (w.notes || '') && manage(w.id, 'notes', e.target.value)}
              style={{ width: '100%', marginTop: 6, fontSize: 10, padding: '3px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg1)', color: 'var(--text2)' }} />
            {open === w.id && (
              <div style={{ marginTop: 8, fontSize: 10 }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  {w.active?.map((m: any) => <span key={m.symbol} title={`added ${(m.added_at || '').slice(0, 10)}`} style={{ fontFamily: 'monospace', padding: '1px 5px', background: 'rgba(34,197,94,.1)', border: '1px solid rgba(34,197,94,.3)', borderRadius: 4, color: 'var(--text1)' }}>{m.symbol}</span>)}
                </div>
                {w.removed?.length > 0 && <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  {w.removed.map((m: any) => <span key={m.symbol} title={`added ${(m.added_at || '').slice(0, 10)} · removed ${(m.removed_at || '').slice(0, 10)}`} style={{ fontFamily: 'monospace', padding: '1px 5px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text3)', textDecoration: 'line-through' }}>{m.symbol}</span>)}
                </div>}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
