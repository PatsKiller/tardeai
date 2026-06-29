import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import AdminConfirmModal, { type PendingAction } from './AdminConfirmModal'
import { getToken } from '../lib/adminWrite'

// Automation Control Center (broker/account-aware) — Phase 1.
// Shows ONLY API-capable accounts. Per-account automation policy + readiness. "Manage APIs" modal
// adds/edits broker API connections (environment: paper/sandbox/live). All writes route through the
// proven admin_write guard. AUTO_LIVE + live api_write are gate-interlocked server-side (refused
// until the live-trading gate passes). No live arming here.

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12, marginBottom: 12 }
const badge = (bg: string, fg: string) => ({ fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 5, background: bg, color: fg })
const inp = { fontSize: 11, padding: '4px 7px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text0)' }
const PAPER_MODES = ['DISABLED', 'MANUAL_REVIEW', 'AUTO_PAPER', 'PAUSED_ENTRIES', 'EMERGENCY_STOP']

function ManageApiModal({ enums, initial, onClose, onSubmit }: any) {
  const [f, setF] = useState<any>(initial ?? { account_key: '', display_name: '', broker: 'alpaca', environment: 'paper', api_read_enabled: true, api_write_enabled: false })
  const set = (k: string, v: any) => setF({ ...f, [k]: v })
  const liveWrite = f.environment === 'live' && f.api_write_enabled
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 18, width: 460, maxWidth: 'min(460px, 95vw)', maxHeight: '88vh', overflow: 'auto' }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>{initial ? 'Edit broker API' : 'Add broker API'}</div>
        <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 12 }}>Secrets (keys) live in .env/keyring — this records the connection + capabilities only.</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 11 }}>
          <label>account key<input style={{ ...inp, width: '100%' }} value={f.account_key} disabled={!!initial} onChange={e => set('account_key', e.target.value)} /></label>
          <label>display name<input style={{ ...inp, width: '100%' }} value={f.display_name} onChange={e => set('display_name', e.target.value)} /></label>
          <label>broker<input style={{ ...inp, width: '100%' }} value={f.broker} onChange={e => set('broker', e.target.value)} /></label>
          <label>environment
            <select style={{ ...inp, width: '100%' }} value={f.environment} onChange={e => set('environment', e.target.value)}>
              {(enums?.environments ?? ['paper', 'sandbox', 'live']).map((e: string) => <option key={e} value={e}>{e}</option>)}
            </select>
          </label>
        </div>
        <div style={{ display: 'flex', gap: 16, margin: '10px 0', fontSize: 11 }}>
          <label><input type="checkbox" checked={!!f.api_read_enabled} onChange={e => set('api_read_enabled', e.target.checked)} /> api read</label>
          <label><input type="checkbox" checked={!!f.api_write_enabled} onChange={e => set('api_write_enabled', e.target.checked)} /> api write</label>
        </div>
        {liveWrite && <div style={{ fontSize: 10, color: '#ef4444', marginBottom: 8 }}>⚠ live + api write is gate-interlocked — the server will refuse it until the live-trading gate passes.</div>}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: 10, color: 'var(--text2)', marginBottom: 12 }}>
          {['supports_equities', 'supports_options', 'supports_fractional', 'supports_bracket_orders', 'supports_stop_orders', 'supports_trailing_stops', 'supports_cancel_replace'].map(c => (
            <label key={c}><input type="checkbox" checked={!!f[c]} onChange={e => set(c, e.target.checked)} /> {c.replace('supports_', '')}</label>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ ...inp, cursor: 'pointer' }}>Cancel</button>
          <button onClick={() => onSubmit(f)} disabled={!f.account_key || !f.broker}
            style={{ fontSize: 11, fontWeight: 600, padding: '4px 12px', borderRadius: 4, border: '1px solid #60a5fa', background: 'rgba(96,165,250,.15)', color: '#60a5fa', cursor: 'pointer' }}>Review change</button>
        </div>
      </div>
    </div>
  )
}

function AutomationPolicyModal({ account, policy, enums, onClose, onSubmit }: any) {
  const isLive = account.environment === 'live'
  const [f, setF] = useState<any>({
    automation_mode: policy.automation_mode ?? account.automation_mode ?? 'MANUAL_REVIEW',
    approval_policy: policy.approval_policy ?? 'PROPOSAL_ONLY',
    risk_per_trade_pct: policy.risk_per_trade_pct ?? '',
    max_new_positions_per_day: policy.max_new_positions_per_day ?? '',
    max_concurrent_positions: policy.max_concurrent_positions ?? '',
    daily_loss_pause_pct: policy.daily_loss_pause_pct ?? '',
    // Percent-of-equity sizing controls (operator 2026-06-19)
    sizing_engine: policy.sizing_engine ?? 'percent_equity',
    max_position_allocation_pct: policy.max_position_allocation_pct ?? '',
    max_strategy_allocation_pct: policy.max_strategy_allocation_pct ?? '',
    max_sector_allocation_pct: policy.max_sector_allocation_pct ?? '',
    max_risk_dollars_per_trade: policy.max_risk_dollars_per_trade ?? '',
    max_notional_per_trade: policy.max_notional_per_trade ?? '',
    display_name: account.display_name ?? account.account_key,
  })
  const set = (k: string, v: any) => setF({ ...f, [k]: v })
  // AUTO_LIVE always disabled in the picker; AUTO_PAPER only for write-capable paper accounts
  const modeOpts = (enums?.automation_modes ?? PAPER_MODES.concat(['AUTO_LIVE']))
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 18, width: 440, maxWidth: 'min(440px, 95vw)' }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)', marginBottom: 2 }}>Edit Automation — {account.display_name}</div>
        <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 12 }}>{account.broker} · {account.environment} · source {policy.source ?? '—'}. {account.environment === 'live' ? 'AUTO_LIVE is gate-interlocked on live accounts (refused until the live-trading gate passes).' : 'Validation account — modes route to the sandbox endpoint (no real-money risk; legacy alpaca_paper identifier).'}</div>
        <label style={{ fontSize: 11, display: 'block', marginBottom: 10 }}>name (this section)
          <input style={{ ...inp, width: '100%' }} value={f.display_name} onChange={e => set('display_name', e.target.value)} placeholder="e.g. Alpaca Paper — Conservative Auto" />
        </label>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 11 }}>
          <label>automation mode
            <select style={{ ...inp, width: '100%' }} value={f.automation_mode} onChange={e => set('automation_mode', e.target.value)}>
              {modeOpts.map((m: string) => {
                const lock = m === 'AUTO_PAPER' && !account.api_write_enabled
                const gated = m === 'AUTO_LIVE' && account.environment === 'live'  // live = gate-interlocked; paper = allowed
                return <option key={m} value={m} disabled={lock}>{m}{lock ? ' (locked)' : gated ? ' (gated)' : ''}</option>
              })}
            </select>
          </label>
          <label>approval policy
            <select style={{ ...inp, width: '100%' }} value={f.approval_policy} onChange={e => set('approval_policy', e.target.value)}>
              {(enums?.approval_policies ?? ['PROPOSAL_ONLY', 'MANUAL_APPROVAL_REQUIRED', 'AUTO_SUBMIT_AFTER_VALIDATION']).map((a: string) => <option key={a} value={a}>{a}</option>)}
            </select>
          </label>
          <label>Risk % / trade<input style={{ ...inp, width: '100%' }} value={f.risk_per_trade_pct} onChange={e => set('risk_per_trade_pct', e.target.value)} /></label>
          <label>Max new / day<input style={{ ...inp, width: '100%' }} value={f.max_new_positions_per_day} onChange={e => set('max_new_positions_per_day', e.target.value)} /></label>
          <label>Max concurrent<input style={{ ...inp, width: '100%' }} value={f.max_concurrent_positions} onChange={e => set('max_concurrent_positions', e.target.value)} /></label>
          <label>Daily-loss pause %<input style={{ ...inp, width: '100%' }} value={f.daily_loss_pause_pct} onChange={e => set('daily_loss_pause_pct', e.target.value)} /></label>
        </div>

        {/* Position sizing engine (operator 2026-06-19) — percent-of-equity is the default */}
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', margin: '14px 0 4px' }}>Position sizing</div>
        <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>
          percent-of-equity: shares = min(equity × position%, equity × risk% ÷ stop-distance). Percentages are whole numbers (5 = 5%). Optional $ ceilings clamp the % caps.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 11 }}>
          <label>sizing engine
            <select style={{ ...inp, width: '100%' }} value={f.sizing_engine} onChange={e => set('sizing_engine', e.target.value)}>
              <option value="percent_equity">percent_equity (default)</option>
              <option value="fixed_dollar">fixed_dollar (legacy)</option>
            </select>
          </label>
          <label>Max position %<input style={{ ...inp, width: '100%' }} value={f.max_position_allocation_pct} onChange={e => set('max_position_allocation_pct', e.target.value)} placeholder="e.g. 20" /></label>
          <label>Max strategy %<input style={{ ...inp, width: '100%' }} value={f.max_strategy_allocation_pct} onChange={e => set('max_strategy_allocation_pct', e.target.value)} /></label>
          <label>Max sector %<input style={{ ...inp, width: '100%' }} value={f.max_sector_allocation_pct} onChange={e => set('max_sector_allocation_pct', e.target.value)} /></label>
          <label>Max risk $ / trade (cap)<input style={{ ...inp, width: '100%' }} value={f.max_risk_dollars_per_trade} onChange={e => set('max_risk_dollars_per_trade', e.target.value)} placeholder="optional" /></label>
          <label>Max notional $ / trade (cap)<input style={{ ...inp, width: '100%' }} value={f.max_notional_per_trade} onChange={e => set('max_notional_per_trade', e.target.value)} placeholder="optional" /></label>
        </div>

        {isLive && <div style={{ fontSize: 10, color: '#ef4444', marginTop: 8 }}>⚠ live account — AUTO_LIVE / AUTO_PAPER will be refused by the gate interlock.</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
          <button onClick={onClose} style={{ ...inp, cursor: 'pointer' }}>Cancel</button>
          <button onClick={() => {
            const body: any = { account: account.account_key, automation_mode: f.automation_mode, approval_policy: f.approval_policy, sizing_engine: f.sizing_engine }
            if (f.display_name && f.display_name !== account.display_name) body.display_name = f.display_name
            for (const k of ['risk_per_trade_pct', 'max_new_positions_per_day', 'max_concurrent_positions', 'daily_loss_pause_pct',
                             'max_position_allocation_pct', 'max_strategy_allocation_pct', 'max_sector_allocation_pct',
                             'max_risk_dollars_per_trade', 'max_notional_per_trade'])
              if (f[k] !== '' && f[k] != null) body[k] = Number(f[k])
            onSubmit(body)
          }} style={{ fontSize: 11, fontWeight: 600, padding: '4px 12px', borderRadius: 4, border: '1px solid #60a5fa', background: 'rgba(96,165,250,.15)', color: '#60a5fa', cursor: 'pointer' }}>Review change</button>
        </div>
      </div>
    </div>
  )
}

export default function ATMControlPanel() {
  const { data: accountsResp } = useApi<any>('/api/v2/broker-accounts?api_only=true', 60_000)
  const { data: enums } = useApi<any>('/api/v2/broker-accounts/enums', 300_000)
  const { data: gateResp } = useApi<any>('/api/v2/atm/gate-status', 60_000)
  const accounts: any[] = accountsResp?.accounts ?? []
  const [sel, setSel] = useState<string>('')
  const account = accounts.find(a => a.account_key === sel) ?? accounts[0]
  const acctKey = account?.account_key
  const { data: policyResp } = useApi<any>(acctKey ? `/api/v2/broker-accounts/automation-policy?account=${acctKey}` : '', 60_000)
  const { data: readyResp } = useApi<any>(acctKey ? `/api/v2/broker-accounts/readiness?account=${acctKey}` : '', 60_000)
  const policy = policyResp?.policy ?? {}
  const readiness = readyResp
  const gate = gateResp?.gate
  const operatorPath = gateResp?.operator_path
  const operatorLive = !!operatorPath?.operator_live_via_2fa_allowed
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [showApi, setShowApi] = useState<any>(null) // null=closed, {}=add, {...}=edit
  const [showAuto, setShowAuto] = useState(false)
  const tokenSet = !!getToken()
  const btn = (active: boolean, disabled?: boolean) => ({ fontSize: 11, fontWeight: 600, padding: '5px 11px', borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer', border: `1px solid ${active ? '#60a5fa' : 'var(--border)'}`, opacity: disabled ? 0.4 : 1, background: active ? 'rgba(96,165,250,.15)' : 'var(--bg2)', color: active ? '#60a5fa' : 'var(--text2)' })

  return (
    <div>
      <div style={{ ...card, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Automation Control Center</span>
        <span style={badge('rgba(34,197,94,.15)', '#22c55e')}>ALPACA PAPER</span>
        {operatorLive
          ? <span style={badge('rgba(34,197,94,.15)', '#22c55e')}>✓ LIVE VIA 2FA</span>
          : <span style={badge('rgba(245,158,11,.15)', '#f59e0b')}>🔒 OPERATOR LIVE LOCKED</span>}
        <span style={badge('rgba(239,68,68,.15)', '#ef4444')}>LEVEL 7 / AUTO OFF</span>
        <span style={badge('rgba(96,165,250,.12)', '#60a5fa')}>auto gate {gate?.passed ? 'PASSED' : 'BLOCKED'}</span>
        <button onClick={() => setShowApi({})} disabled={!tokenSet} style={{ ...btn(false, !tokenSet), marginLeft: 'auto' }}>+ Manage APIs</button>
      </div>
      {!tokenSet && <div style={{ ...card, borderColor: '#f59e0b', color: '#f59e0b', fontSize: 11 }}>⚠ Admin token not set — writes disabled (read-only inspection).</div>}

      {/* ACCOUNT SELECTOR — API-capable only */}
      <div style={card}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Accounts with trading APIs ({accounts.length})</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(240px,1fr))', gap: 8 }}>
          {accounts.map(a => {
            const isSel = a.account_key === acctKey
            return (
              <div key={a.account_key} onClick={() => setSel(a.account_key)}
                style={{ border: `1px solid ${isSel ? '#60a5fa' : 'var(--border)'}`, borderRadius: 8, padding: 8, cursor: 'pointer', background: isSel ? 'rgba(96,165,250,.08)' : 'var(--bg2)' }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text0)' }}>{a.display_name}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 3 }}>
                  {a.broker} · {a.environment} · {a.api_read_enabled ? 'read' : '—'}/{a.api_write_enabled ? 'write' : (a.environment === 'live' ? 'write not proven' : '—')}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
                  <span style={{ fontSize: 9, color: '#60a5fa' }}>{a.automation_mode}</span>
                  <span onClick={(e) => { e.stopPropagation(); setShowApi({ account_key: a.account_key, display_name: a.display_name, broker: a.broker, environment: a.environment, api_read_enabled: a.api_read_enabled, api_write_enabled: a.api_write_enabled }) }}
                    style={{ fontSize: 9, color: 'var(--text3)', textDecoration: 'underline' }}>edit API</span>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {account && (
        <>
          {/* AUTOMATION POLICY — edit via modal */}
          <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>{account.display_name} — Automation</div>
              <button disabled={!tokenSet} style={btn(false, !tokenSet)} onClick={() => setShowAuto(true)}>Edit Automation</button>
            </div>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 10 }}>
              mode <b style={{ color: '#60a5fa' }}>{policy.automation_mode ?? account.automation_mode}</b> · approval {policy.approval_policy ?? '—'} ·
              policy source <b style={{ color: policy.source === 'database' ? '#22c55e' : '#f59e0b' }}>{policy.source ?? '—'}</b>
              {policy.updated_at && ` · updated ${String(policy.updated_at).slice(0, 16).replace('T', ' ')}`}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 6 }}>
              {[['risk_per_trade_pct', 'Risk % / trade'], ['max_new_positions_per_day', 'Max new / day'], ['max_concurrent_positions', 'Max concurrent'], ['daily_loss_pause_pct', 'Daily-loss pause %']].map(([k, lbl]) => (
                <div key={k} style={{ fontSize: 11, color: 'var(--text2)' }}>{lbl}: <b style={{ color: 'var(--text0)', fontFamily: 'monospace' }}>{String(policy[k] ?? '—')}</b></div>
              ))}
            </div>
          </div>

          {/* READINESS */}
          <div style={card}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>
              {account.display_name} — Broker readiness <span style={{ color: readiness?.ready ? '#22c55e' : '#ef4444' }}>{readiness?.ready ? 'READY' : 'NOT READY'}</span>
            </div>
            {(readiness?.checks ?? []).map((c: any, i: number) => (
              <div key={i} style={{ fontSize: 10, padding: '3px 0', borderBottom: '1px solid var(--border)', color: c.status === 'ok' ? '#22c55e' : c.status === 'n/a' ? 'var(--text3)' : '#f59e0b' }}>
                <span style={{ marginRight: 6 }}>{c.status === 'ok' ? '✓' : c.status === 'n/a' ? '–' : '☐'}</span>{c.check_name} <span style={{ color: 'var(--text3)' }}>· {c.status}</span>
              </div>
            ))}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/broker-accounts/readiness</div>
          </div>
        </>
      )}

      {showAuto && account && <AutomationPolicyModal account={account} policy={policy} enums={enums}
        onClose={() => setShowAuto(false)}
        onSubmit={(body: any) => { setShowAuto(false); setPending({ path: '/api/v2/admin/broker-account/policy', body, label: `${account.account_key}: automation → ${body.automation_mode} / ${body.approval_policy}` }) }} />}
      {showApi && <ManageApiModal enums={enums} initial={Object.keys(showApi).length ? showApi : null}
        onClose={() => setShowApi(null)}
        onSubmit={(f: any) => { setShowApi(null); setPending({ path: '/api/v2/admin/broker-account/api', body: f, label: `${f.account_key}: ${f.broker}/${f.environment} API (read=${!!f.api_read_enabled} write=${!!f.api_write_enabled})` }) }} />}
      <AdminConfirmModal action={pending} onClose={() => setPending(null)} onDone={() => setPending(null)} />
    </div>
  )
}

