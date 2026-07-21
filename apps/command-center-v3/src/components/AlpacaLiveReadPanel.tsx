/**
 * Admin panel: Alpaca live accounts — credentials status + api_read_enabled toggle.
 * READ-ONLY DATA · execution not built. Never flips is_enabled / api_write / arm.
 */
import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { BB, T } from '../lib/watchTokens'

type Acct = {
  account_key: string
  display_name?: string
  environment?: string
  api_read_enabled?: boolean
  api_write_enabled?: boolean
  is_enabled?: boolean
  connection_status?: string
  last_sync_at?: string
  credential_slot?: string
  has_credentials?: boolean
  read_only_data?: boolean
  armed?: boolean
}

export default function AlpacaLiveReadPanel() {
  const { data, refetch } = useApi<{ accounts?: Acct[] }>('/api/v2/broker-accounts', 30_000)
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState('')
  const accounts = (data?.accounts || []).filter(
    a => a.read_only_data || (String(a.account_key || '').startsWith('alpaca_') && a.environment === 'live'),
  )

  const toggleRead = async (a: Acct, next: boolean) => {
    const ok = window.confirm(
      next
        ? 'Enables read-only data sync (positions, balances, activity). Does NOT enable trading.'
        : 'Disable read-only data sync for this account?',
    )
    if (!ok) return
    setBusy(a.account_key)
    setMsg('')
    try {
      const r = await fetch('/api/v2/broker-accounts/api-read-toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_key: a.account_key, enabled: next }),
      })
      const j = await r.json()
      const d = j?.data ?? j
      if (d?.ok) {
        setMsg(`✓ ${a.account_key} api_read_enabled=${next}`)
        refetch()
      } else setMsg(`✗ ${d?.error || 'toggle failed'}`)
    } catch {
      setMsg('✗ request failed')
    }
    setBusy(null)
  }

  const testConn = async (a: Acct) => {
    setBusy(a.account_key + ':test')
    setMsg('')
    try {
      const r = await fetch('/api/v2/broker-accounts/test-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_key: a.account_key }),
      })
      const j = await r.json()
      const d = j?.data ?? j
      if (d?.status === 'no_credentials') {
        setMsg(`${a.account_key}: no credentials — enter keys in API Keys & Secrets`)
      } else if (d?.ok) {
        setMsg(`✓ ${a.account_key} connection ${d.status} (host ${d.host || '?'})`)
      } else {
        setMsg(`✗ ${a.account_key}: ${d?.error || d?.status || 'failed'}`)
      }
      refetch()
    } catch {
      setMsg('✗ test failed')
    }
    setBusy(null)
  }

  if (!accounts.length) {
    return (
      <div style={{ fontSize: 11, color: BB.text3, padding: 8 }}>
        No Alpaca live scaffold accounts in registry.
      </div>
    )
  }

  return (
    <div style={{ background: BB.bgPanel, border: `1px solid ${BB.border}`, borderRadius: 10, padding: 14, marginTop: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: BB.text0 }}>Alpaca Live — Read-Only Data</div>
      <div style={{ fontSize: 10, color: BB.text3, marginBottom: 10 }}>
        Keys + api_read_enabled only · is_enabled / write / arm untouched · no orders · no 2FA
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {accounts.map(a => (
          <div
            key={a.account_key}
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr auto',
              gap: 8,
              padding: '10px 12px',
              borderRadius: 8,
              background: BB.bgShift,
              border: `1px solid ${BB.border}`,
            }}
          >
            <div>
              <div style={{ fontFamily: 'var(--mono)', fontWeight: 700, color: BB.text1, fontSize: 12 }}>
                {a.display_name || a.account_key}
              </div>
              <div style={{ fontSize: 10, color: BB.text3, marginTop: 3 }}>
                {a.account_key} · slot {a.credential_slot || '—'} · status {a.connection_status || 'unknown'}
                {a.last_sync_at ? ` · last sync ${String(a.last_sync_at).slice(0, 19)}` : ''}
              </div>
              <div style={{ fontSize: 10, fontWeight: 700, color: BB.amber, marginTop: 4 }}>
                READ-ONLY DATA · execution not built
                {a.has_credentials ? ' · keys present' : ' · keys not set'}
                {a.api_write_enabled ? ' · WRITE FLAG ON (unexpected)' : ''}
                {a.is_enabled ? ' · is_enabled ON (unexpected for scaffold)' : ''}
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end' }}>
              <label style={{ fontSize: 10, color: BB.text2, display: 'flex', gap: 6, alignItems: 'center' }}>
                <input
                  type="checkbox"
                  checked={!!a.api_read_enabled}
                  disabled={busy === a.account_key}
                  onChange={e => toggleRead(a, e.target.checked)}
                />
                api_read_enabled
              </label>
              <button
                type="button"
                disabled={!!busy}
                onClick={() => testConn(a)}
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  padding: '5px 10px',
                  borderRadius: 6,
                  border: `1px solid ${BB.border}`,
                  background: BB.bgPanel,
                  color: T.link,
                  cursor: 'pointer',
                }}
              >
                {busy === a.account_key + ':test' ? '…' : 'Test connection'}
              </button>
            </div>
          </div>
        ))}
      </div>
      {msg && (
        <div style={{ fontSize: 11, marginTop: 10, color: msg.startsWith('✓') ? BB.green : BB.amber }}>{msg}</div>
      )}
    </div>
  )
}
