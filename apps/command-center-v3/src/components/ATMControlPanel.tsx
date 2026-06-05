import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import AdminConfirmModal, { type PendingAction } from './AdminConfirmModal'
import { getToken } from '../lib/adminWrite'

// Editable ATM + proposal controls — PAPER-ONLY and GATE-INTERLOCKED (2026-06-04).
// Every write routes through the proven admin_write guard (preview->confirm->audit). The server-side
// interlock REFUSES any write targeting a live account until live_trading_allowed=true, so live
// controls render disabled here AND are blocked server-side. Nothing live is wired.

const ATM_MODES = ['disabled', 'dry_run', 'active', 'paused'] as const
const RISK_FIELDS: { field: string; label: string }[] = [
  { field: 'max_pct_per_trade', label: 'Max risk % / trade' },
  { field: 'max_pct_per_strategy', label: 'Max % / strategy' },
  { field: 'max_pct_per_sector', label: 'Max % / sector' },
  { field: 'max_concurrent', label: 'Max concurrent positions' },
  { field: 'max_new_per_day', label: 'Max new / day' },
  { field: 'daily_loss_pct_hard_pause', label: 'Daily-loss hard-pause %' },
]
const PAPER = 'alpaca_paper'
const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }
const h = { fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }
const btn = (active: boolean, disabled?: boolean) => ({
  fontSize: 11, fontWeight: 600, padding: '5px 12px', borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer',
  border: `1px solid ${active ? '#60a5fa' : 'var(--border)'}`, opacity: disabled ? 0.4 : 1,
  background: active ? 'rgba(96,165,250,.15)' : 'var(--bg2)', color: active ? '#60a5fa' : 'var(--text2)',
})

export default function ATMControlPanel() {
  const { data: gateResp } = useApi<any>('/api/v2/atm/gate-status', 60_000)
  const { data: readyResp } = useApi<any>('/api/v2/atm/schwab-readiness', 60_000)
  const { data: propResp } = useApi<any>('/api/v2/atm/actionable-proposals', 60_000)
  const gate = gateResp?.gate
  const accounts: any[] = gateResp?.accounts ?? []
  const atmMode: string = gateResp?.atm_state?.mode ?? '—'
  const riskCfg: Record<string, any> = gateResp?.risk_config ?? {}
  const ready = readyResp
  const proposals: any[] = propResp?.proposals ?? []

  const [pending, setPending] = useState<PendingAction | null>(null)
  const [riskInput, setRiskInput] = useState<Record<string, string>>({})
  const [editId, setEditId] = useState<number | null>(null)
  const [editVals, setEditVals] = useState<Record<string, string>>({})
  const tokenSet = !!getToken()

  const ck = gate?.checks ?? {}
  const Check = ({ k, label }: { k: string; label: string }) => {
    const c = ck[k] ?? {}
    return (
      <div style={{ fontSize: 11, color: c.ok ? '#22c55e' : '#f59e0b' }}>
        {c.ok ? '✓' : '○'} {label}: <b>{String(c.have)}</b> / {String(c.need)}
      </div>
    )
  }

  return (
    <div>
      {!tokenSet && (
        <div style={{ ...card, borderColor: '#f59e0b', background: 'rgba(245,158,11,.08)', color: '#f59e0b', fontSize: 11 }}>
          ⚠ Admin token not set in this browser — writes will be refused (403). Set it in System → admin token.
        </div>
      )}

      {/* GATE BANNER */}
      <div style={{ ...card, borderColor: gate?.passed ? '#22c55e' : '#ef4444' }}>
        <div style={h}>
          Live-Trading Gate —{' '}
          <span style={{ color: gate?.passed ? '#22c55e' : '#ef4444' }}>
            {gate?.passed ? 'PASSED' : 'BLOCKED (live arming refused)'}
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 4 }}>
          <Check k="days" label="Validation days" />
          <Check k="closed_trades" label="Closed trades" />
          <Check k="win_rate" label="Win rate" />
          <Check k="profit_factor" label="Profit factor" />
        </div>
        <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8 }}>
          live_trading_allowed = <b>{String(gate?.live_trading_allowed)}</b> · the interlock blocks every
          live-account write until this is true. Source: /api/v2/atm/gate-status
        </div>
      </div>

      {/* ATM STATE (paper) */}
      <div style={card}>
        <div style={h}>ATM State — <span style={{ color: '#60a5fa' }}>alpaca_paper</span> (current: {atmMode})</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {ATM_MODES.map(m => (
            <button key={m} disabled={!tokenSet} style={btn(atmMode === m, !tokenSet)}
              onClick={() => setPending({
                path: '/api/v2/admin/atm/set-state', body: { account: PAPER, mode: m },
                label: `Set ATM (paper) → ${m.toUpperCase()}`,
              })}>{m.toUpperCase()}</button>
          ))}
        </div>
      </div>

      {/* RISK CONFIG (paper) */}
      <div style={card}>
        <div style={h}>Risk Limits — paper config (atm_config.yaml)</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 10 }}>
          {RISK_FIELDS.map(rf => (
            <div key={rf.field} style={{ fontSize: 11 }}>
              <div style={{ color: 'var(--text2)', marginBottom: 3 }}>{rf.label}</div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <span style={{ color: 'var(--text0)', fontFamily: 'monospace', minWidth: 50 }}>{String(riskCfg[rf.field] ?? '—')}</span>
                <input value={riskInput[rf.field] ?? ''} placeholder="new" disabled={!tokenSet}
                  onChange={e => setRiskInput({ ...riskInput, [rf.field]: e.target.value })}
                  style={{ width: 64, fontSize: 11, padding: '2px 6px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text0)' }} />
                <button disabled={!tokenSet || !riskInput[rf.field]} style={btn(false, !tokenSet || !riskInput[rf.field])}
                  onClick={() => setPending({
                    path: '/api/v2/admin/risk-config', body: { field: rf.field, value: Number(riskInput[rf.field]) },
                    label: `Set ${rf.label} → ${riskInput[rf.field]}`,
                  })}>Set</button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ACCOUNTS — live disabled */}
      <div style={card}>
        <div style={h}>Accounts</div>
        {accounts.map(a => {
          const live = a.mode !== 'paper'
          return (
            <div key={a.account_label} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: 12 }}>
                <span style={{ fontFamily: 'monospace', color: 'var(--text0)' }}>{a.account_label}</span>
                <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 8 }}>{a.broker} · {a.mode}</span>
              </div>
              <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 600,
                background: live ? 'rgba(239,68,68,.12)' : 'rgba(34,197,94,.12)', color: live ? '#ef4444' : '#22c55e' }}>
                {live ? '🔒 requires live-trading gate pass' : 'writable (paper)'}
              </span>
            </div>
          )
        })}
      </div>

      {/* PROPOSAL ACTIONS */}
      <div style={card}>
        <div style={h}>Proposals — approve / adjust / edit ({proposals.length})</div>
        {proposals.length === 0 && <div style={{ fontSize: 11, color: 'var(--text3)' }}>No actionable proposals.</div>}
        {proposals.map(p => {
          const live = p.account !== 'paper' && !String(p.account).includes('paper')
          const liveBlocked = live // server interlock will 403; disable in UI too
          return (
            <div key={p.id} style={{ padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: 12 }}>
                  <b style={{ color: 'var(--text0)', fontFamily: 'monospace' }}>{p.symbol}</b>
                  <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 8 }}>
                    {p.strategy_id} · {p.status} · {p.account} · entry {p.proposed_entry} stop {p.proposed_stop} tgt {p.proposed_target1}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button disabled={!tokenSet || liveBlocked} style={btn(false, !tokenSet || liveBlocked)}
                    onClick={() => setPending({ path: '/api/v2/admin/proposal/approve', body: { proposal_id: p.id }, label: `Approve ${p.symbol} (paper)` })}>Approve</button>
                  <button disabled={!tokenSet || liveBlocked} style={btn(editId === p.id, !tokenSet || liveBlocked)}
                    onClick={() => { setEditId(editId === p.id ? null : p.id); setEditVals({ proposed_entry: p.proposed_entry ?? '', proposed_stop: p.proposed_stop ?? '', proposed_target1: p.proposed_target1 ?? '', proposed_shares: p.proposed_shares ?? '' }) }}>Adjust / Edit</button>
                </div>
              </div>
              {editId === p.id && (
                <div style={{ marginTop: 8, padding: 8, background: 'var(--bg2)', borderRadius: 6 }}>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {['proposed_entry', 'proposed_stop', 'proposed_target1', 'proposed_shares'].map(f => (
                      <label key={f} style={{ fontSize: 10, color: 'var(--text3)' }}>
                        {f.replace('proposed_', '')}
                        <input value={editVals[f] ?? ''} onChange={e => setEditVals({ ...editVals, [f]: e.target.value })}
                          style={{ width: 70, marginLeft: 4, fontSize: 11, padding: '2px 5px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text0)' }} />
                      </label>
                    ))}
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                    {(() => {
                      const fields: Record<string, number> = {}
                      for (const f of ['proposed_entry', 'proposed_stop', 'proposed_target1', 'proposed_shares'])
                        if (editVals[f] !== '' && editVals[f] != null) fields[f] = Number(editVals[f])
                      return (
                        <>
                          <button disabled={!Object.keys(fields).length} style={btn(false, !Object.keys(fields).length)}
                            onClick={() => setPending({ path: '/api/v2/admin/proposal/adjust-approve', body: { proposal_id: p.id, fields }, label: `Adjust & Approve ${p.symbol}` })}>Adjust &amp; Approve</button>
                          <button disabled={!Object.keys(fields).length} style={btn(false, !Object.keys(fields).length)}
                            onClick={() => setPending({ path: '/api/v2/admin/proposal/edit-criteria', body: { proposal_id: p.id, fields }, label: `Edit criteria ${p.symbol}` })}>Edit Criteria (no approve)</button>
                        </>
                      )
                    })()}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* SCHWAB READINESS (visibility only) */}
      <div style={card}>
        <div style={h}>
          Schwab Live Readiness —{' '}
          <span style={{ color: ready?.schwab_live_ready ? '#22c55e' : '#ef4444' }}>
            {ready?.schwab_live_ready ? 'READY' : 'NOT READY'}
          </span>
        </div>
        {(ready?.items ?? []).map((it: any, i: number) => (
          <div key={i} style={{ fontSize: 11, padding: '4px 0', borderBottom: '1px solid var(--border)', color: it.done ? '#22c55e' : 'var(--text2)' }}>
            <span style={{ marginRight: 6 }}>{it.done ? '✓' : '☐'}</span>{it.item}
            <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 6 }}>— {it.detail}</span>
          </div>
        ))}
        <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8 }}>{ready?.note}</div>
      </div>

      <AdminConfirmModal action={pending} onClose={() => setPending(null)} onDone={() => { setPending(null); setEditId(null) }} />
    </div>
  )
}
