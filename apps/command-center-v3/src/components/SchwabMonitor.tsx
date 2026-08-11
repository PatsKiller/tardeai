import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'

// Schwab read-only integration monitor — Gate-A token health, account-hash links, capability checks,
// recent sync. Read-only; writes are fenced. Surfaced in System → Brokers.
const STATE_COLOR: Record<string, string> = {
  ok: '#22c55e', reauth_due_day5: '#f59e0b', reauth_due_day6: '#f97316',
  expired: '#ef4444', degraded: '#ef4444', no_token: 'var(--text3)',
}

export default function SchwabMonitor() {
  const { data } = useApi<any>('/api/v2/system/schwab-status', 30_000)
  const d = data ?? {}
  const tokens: any[] = d.tokens ?? []
  const caps: any[] = d.capabilities ?? []
  const sync: any[] = d.recent_sync ?? []
  if (!tokens.length && !sync.length) return null

  const needsRenew = tokens.some((t: any) =>
    ['degraded', 'expired', 'no_token', 'reauth_due_day6', 'reauth_due_day5'].includes(t.state)
    || (t.days_remaining != null && Number(t.days_remaining) <= 1))

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginTop: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4, gap: 8, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Schwab Integration (read-only)</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Link
            to="/system/schwab-reauth"
            style={{
              fontSize: 10.5, fontWeight: 800, padding: '3px 10px', borderRadius: 5, textDecoration: 'none',
              background: needsRenew ? 'var(--red-dim)' : 'var(--amber-dim)',
              color: needsRenew ? 'var(--red)' : 'var(--amber)',
              border: `1px solid ${needsRenew ? 'var(--red)' : 'var(--amber)'}`,
            }}
          >
            {needsRenew ? '🔐 Renew token now →' : 'Schwab Reauth →'}
          </Link>
          <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--green)', padding: '2px 8px', border: '1px solid var(--green)', borderRadius: 5 }}>
            WRITES FENCED · api_write_enabled={String(d.api_write_enabled)}
          </span>
        </div>
      </div>
      <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>Gate-A token health · account-hash links · capabilities · sync. No token material is ever shown.</div>

      {/* Token / Gate-A health */}
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text2)', marginBottom: 6 }}>Token health (Gate A)</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
        {tokens.map((t: any) => (
          <div key={t.account_key} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 10px', background: 'var(--bg2)', borderRadius: 7, border: '1px solid var(--border)' }}>
            <span style={{ flex: '0 0 150px', fontFamily: 'monospace', fontSize: 11, color: 'var(--text1)' }}>{t.account_key}</span>
            <span style={{ flex: '0 0 100px', fontSize: 10, fontWeight: 700, color: STATE_COLOR[t.state] || 'var(--text2)' }}>{t.state}</span>
            <span style={{ flex: '0 0 110px', fontSize: 10, color: 'var(--text2)' }}>{t.days_remaining != null ? `${t.days_remaining}d to re-auth` : '—'}</span>
            <span style={{ flex: '0 0 130px', fontSize: 10, color: t.account_linked ? '#22c55e' : 'var(--text3)' }}>{t.account_linked ? `linked ••${t.masked_last4}` : 'account not linked'}</span>
            <span style={{ flex: '1 1 auto', textAlign: 'right', fontSize: 9, color: 'var(--text3)' }}>rot {t.rotation_count ?? 0}{t.last_error ? ` · ${t.last_error.slice(0, 40)}` : ''}</span>
          </div>
        ))}
      </div>

      {/* Capability checks */}
      {!!caps.length && (
        <>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text2)', marginBottom: 6 }}>Capability checks</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
            {caps.map((c: any) => (
              <span key={c.name} style={{ fontSize: 10, padding: '3px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: c.status === 'proven' || c.status === 'ok' ? '#22c55e' : 'var(--text3)' }}>
                {c.name}: {c.status}
              </span>
            ))}
          </div>
        </>
      )}

      {/* Recent sync */}
      {!!sync.length && (
        <>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text2)', marginBottom: 6 }}>Recent sync</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {sync.slice(0, 6).map((s: any, i: number) => (
              <div key={i} style={{ display: 'flex', gap: 10, fontSize: 10, color: 'var(--text2)', padding: '4px 8px', background: 'var(--bg2)', borderRadius: 6 }}>
                <span style={{ flex: '0 0 130px', fontFamily: 'monospace' }}>{s.account_key || '—'}</span>
                <span style={{ flex: '0 0 130px', color: s.status === 'ok' ? '#22c55e' : s.status?.startsWith('rejected') ? '#ef4444' : 'var(--text2)' }}>{s.status}</span>
                <span style={{ flex: '0 0 90px' }}>{s.wrote_holdings ? 'wrote' : 'no-op'}</span>
                <span style={{ flex: '1 1 auto', textAlign: 'right', color: 'var(--text3)' }}>{s.reason?.slice(0, 50)}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
