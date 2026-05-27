import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import ActionButton from '../components/ActionButton'
import StatusBadge from '../components/StatusBadge'

interface Account { id: number; account_label: string; broker: string; mode: string; enabled: boolean; auto_execution_capable: boolean; equity_source: string; routing_adapter: string | null; notes: string; atm_enabled: boolean; position_limits: any }
interface BrokerInfo { name: string; modes: string[]; auto_capable: boolean; env_vars: string[]; adapter_status: string; features: string[]; setup_steps: string[] }

const inputStyle = { width: '100%', padding: '5px 8px', background: 'var(--bg2, #161622)', border: '1px solid var(--border1, #2a2a3a)', borderRadius: 4, color: '#fff', fontSize: 11, fontFamily: 'monospace' }
const labelStyle = { fontSize: 9, fontWeight: 700 as const, color: 'var(--text3)', textTransform: 'uppercase' as const, letterSpacing: '0.04em', marginBottom: 2 }

export default function BrokerAccountAdmin() {
  const { data, refetch } = useApi<any>('/api/v2/admin/accounts', 60_000)
  const { data: brokerData } = useApi<any>('/api/v2/admin/brokers', 300_000)
  const [showAdd, setShowAdd] = useState(false)
  const [addForm, setAddForm] = useState({ account_label: '', broker: 'alpaca', mode: 'paper', notes: '', auto_execution_capable: false, equity_source: 'manual', routing_adapter: '' })
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [selectedBroker, setSelectedBroker] = useState<string | null>(null)
  const [rk, setRk] = useState(0)

  const accounts = (data?.accounts || []) as Account[]
  const brokers = (brokerData?.brokers || {}) as Record<string, BrokerInfo>
  const onboarding = data?.onboarding || {}

  const setAdd = (k: string, v: any) => {
    const next = { ...addForm, [k]: v }
    if (k === 'broker' || k === 'mode') {
      next.account_label = `${next.broker}_${next.mode}`
    }
    setAddForm(next)
  }

  const saveAccount = async () => {
    setSaving(true); setMsg('')
    try {
      const r = await fetch('/api/v2/admin/accounts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(addForm) })
      const d = await r.json()
      if (d.ok) { setShowAdd(false); refetch(); setMsg('') } else setMsg(d.error || 'Failed')
    } catch { setMsg('Network error') }
    setSaving(false)
  }

  const toggleEnabled = async (label: string, enabled: boolean) => {
    await fetch('/api/v2/admin/accounts', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account_label: label, enabled }) })
    refetch()
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* ═══ ACCOUNTS TABLE ═══ */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Broker Accounts ({accounts.length})</div>
        <ActionButton variant="primary" size="sm" onClick={() => { setShowAdd(true); setAddForm({ account_label: '', broker: 'alpaca', mode: 'paper', notes: '', auto_execution_capable: false, equity_source: 'manual', routing_adapter: '' }) }}>
          Add Account
        </ActionButton>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border1)' }}>
              {['Account', 'Broker', 'Mode', 'Enabled', 'ATM', 'Auto-Exec', 'Equity Source', 'Adapter', 'Notes', 'Actions'].map(h =>
                <th key={h} style={{ padding: '6px 8px', textAlign: 'left', color: 'var(--text3)', fontSize: 9, fontWeight: 600 }}>{h}</th>
              )}
            </tr>
          </thead>
          <tbody>
            {accounts.map(a => (
              <tr key={a.account_label} style={{ borderBottom: '1px solid var(--border1)' }}>
                <td style={{ padding: '6px 8px', fontWeight: 600, color: 'var(--text0)' }}>{a.account_label}</td>
                <td style={{ padding: '6px 8px', color: 'var(--text1)' }}>{a.broker}</td>
                <td style={{ padding: '6px 8px' }}><StatusBadge status={a.mode === 'paper' ? 'info' : 'warning'} label={a.mode} size="sm" /></td>
                <td style={{ padding: '6px 8px' }}>
                  <span onClick={() => toggleEnabled(a.account_label, !a.enabled)}
                    style={{ cursor: 'pointer', color: a.enabled ? '#0ecb81' : '#f6465d', fontWeight: 600 }}>
                    {a.enabled ? '● ON' : '○ OFF'}
                  </span>
                </td>
                <td style={{ padding: '6px 8px', color: a.atm_enabled ? '#0ecb81' : 'var(--text3)' }}>{a.atm_enabled ? '✓' : '—'}</td>
                <td style={{ padding: '6px 8px', color: a.auto_execution_capable ? '#0ecb81' : 'var(--text3)' }}>{a.auto_execution_capable ? '✓' : '—'}</td>
                <td style={{ padding: '6px 8px', color: 'var(--text3)', fontSize: 9 }}>{a.equity_source}</td>
                <td style={{ padding: '6px 8px', color: a.routing_adapter ? 'var(--accent)' : 'var(--text3)', fontSize: 9 }}>{a.routing_adapter || 'none'}</td>
                <td style={{ padding: '6px 8px', color: 'var(--text3)', fontSize: 9, maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis' }}>{a.notes || '—'}</td>
                <td style={{ padding: '6px 8px' }}>
                  <span onClick={() => toggleEnabled(a.account_label, !a.enabled)}
                    style={{ fontSize: 9, color: 'var(--accent)', cursor: 'pointer' }}>
                    {a.enabled ? 'Disable' : 'Enable'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ═══ ADD ACCOUNT FORM ═══ */}
      {showAdd && (
        <div style={{ padding: 16, background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--accent)40' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)', marginBottom: 12 }}>Add New Account</div>
          {msg && <div style={{ fontSize: 10, padding: '4px 8px', borderRadius: 4, background: 'rgba(246,70,93,.1)', color: '#f6465d', marginBottom: 8 }}>{msg}</div>}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 10 }}>
            <div>
              <div style={labelStyle}>Broker</div>
              <select value={addForm.broker} onChange={e => setAdd('broker', e.target.value)} style={inputStyle}>
                {Object.keys(brokers).map(b => <option key={b} value={b}>{brokers[b]?.name || b}</option>)}
                <option value="custom">Custom</option>
              </select>
            </div>
            <div>
              <div style={labelStyle}>Mode</div>
              <select value={addForm.mode} onChange={e => setAdd('mode', e.target.value)} style={inputStyle}>
                <option value="paper">Paper</option>
                <option value="live">Live</option>
              </select>
            </div>
            <div>
              <div style={labelStyle}>Account Label</div>
              <input value={addForm.account_label} onChange={e => setAdd('account_label', e.target.value)} style={inputStyle} placeholder="auto-generated" />
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 10 }}>
            <div>
              <div style={labelStyle}>Equity Source</div>
              <select value={addForm.equity_source} onChange={e => setAdd('equity_source', e.target.value)} style={inputStyle}>
                <option value="live_api">Live API</option>
                <option value="holdings_json">Holdings JSON</option>
                <option value="manual">Manual</option>
              </select>
            </div>
            <div>
              <div style={labelStyle}>Routing Adapter</div>
              <input value={addForm.routing_adapter} onChange={e => setAdd('routing_adapter', e.target.value)} style={inputStyle} placeholder="scripts.adapter_name" />
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, paddingBottom: 2 }}>
              <label style={{ fontSize: 10, color: 'var(--text2)', display: 'flex', alignItems: 'center', gap: 4 }}>
                <input type="checkbox" checked={addForm.auto_execution_capable} onChange={e => setAdd('auto_execution_capable', e.target.checked)} />
                Auto-execution capable
              </label>
            </div>
          </div>
          <div style={{ marginBottom: 10 }}>
            <div style={labelStyle}>Notes</div>
            <input value={addForm.notes} onChange={e => setAdd('notes', e.target.value)} style={inputStyle} placeholder="Description or setup notes" />
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <ActionButton variant="primary" size="sm" onClick={saveAccount} loading={saving}>Save Account</ActionButton>
            <ActionButton variant="ghost" size="sm" onClick={() => setShowAdd(false)}>Cancel</ActionButton>
          </div>
        </div>
      )}

      {/* ═══ BROKER ONBOARDING GUIDE ═══ */}
      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginTop: 8 }}>Broker Onboarding</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 8 }}>
        {Object.entries(brokers).map(([key, broker]) => {
          const isExpanded = selectedBroker === key
          const info = onboarding[key] || {}
          return (
            <div key={key} onClick={() => setSelectedBroker(isExpanded ? null : key)}
              style={{ padding: '10px 12px', borderRadius: 6, cursor: 'pointer',
                background: isExpanded ? 'rgba(74,144,244,.06)' : 'var(--bg1)',
                border: `1px solid ${isExpanded ? 'var(--accent)' : 'var(--border1, #2a2a3a)'}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>{broker.name}</span>
                <StatusBadge status={broker.adapter_status === 'built' ? 'fresh' : broker.adapter_status === 'manual_only' ? 'warning' : 'stale'} label={broker.adapter_status} size="sm" />
              </div>
              <div style={{ fontSize: 9, color: 'var(--text2)', marginBottom: 4 }}>
                Modes: {broker.modes.join(', ')} | Auto: {broker.auto_capable ? 'Yes' : 'No'} | IRA: {(broker as any).ira_support ? <span style={{ color: '#0ecb81' }}>Yes</span> : <span style={{ color: '#f6465d' }}>No</span>}
              </div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 2 }}>
                {broker.features.join(' · ')}
              </div>
              {(broker as any).account_types && (
                <div style={{ fontSize: 8, color: 'var(--text3)' }}>
                  Accounts: {(broker as any).account_types.map((t: string) => t.replace(/_/g, ' ')).join(', ')}
                </div>
              )}
              {isExpanded && (
                <div style={{ marginTop: 8, borderTop: '1px solid var(--border1)', paddingTop: 8 }}>
                  {broker.env_vars.length > 0 && (
                    <div style={{ marginBottom: 6 }}>
                      <div style={{ fontSize: 9, fontWeight: 600, color: 'var(--text3)', marginBottom: 2 }}>Required ENV vars:</div>
                      {broker.env_vars.map(v => (
                        <div key={v} style={{ fontSize: 10, color: 'var(--accent)', fontFamily: 'monospace' }}>{v}</div>
                      ))}
                    </div>
                  )}
                  <div style={{ fontSize: 9, fontWeight: 600, color: 'var(--text3)', marginBottom: 2 }}>Setup:</div>
                  {broker.setup_steps.map((s, i) => (
                    <div key={i} style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 1 }}>{s}</div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
