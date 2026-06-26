import { useEffect, useState } from 'react'

const MUTED = '#94a3b8', TEXT0 = '#f8fafc', TEXT1 = '#dbeafe', GREEN = '#22c55e', AMBER = '#f59e0b', BLUE = '#60a5fa', PURPLE = '#a78bfa'
const overlay = { position: 'fixed' as const, inset: 0, background: 'rgba(2,6,23,.72)', zIndex: 9000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }
const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 14, padding: 20, width: 'min(520px, 96vw)', maxHeight: '90vh', overflow: 'auto' }
const inp = { fontSize: 12, padding: '7px 10px', borderRadius: 7, border: '1px solid rgba(148,163,184,.3)', background: 'rgba(15,23,42,.55)', color: TEXT0, width: '100%' } as const
const lbl = { fontSize: 10, color: MUTED, display: 'block', marginBottom: 4 } as const

export type ManualExecSeed = {
  symbol: string
  account?: string
  proposal_id?: number
  options_proposal_id?: string
  execution_type?: 'equity' | 'option'
}

type AccountOpt = { account_key: string; label: string; broker?: string; mode?: string }

type Props = {
  seed: ManualExecSeed
  onClose: () => void
  onLogged?: (res: any) => void
}

export default function ManualExecutionModal({ seed, onClose, onLogged }: Props) {
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [data, setData] = useState<any>(null)
  const [f, setF] = useState<any>({})

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const r = await fetch('/api/v2/broker-proposals/prepare-manual', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            symbol: seed.symbol,
            account: seed.account,
            proposal_id: seed.proposal_id,
            options_proposal_id: seed.options_proposal_id,
          }),
        }).then(x => x.json())
        const d = r.data ?? r
        if (!cancelled) {
          setData(d)
          const rec = d.recommended || {}
          setF({
            account: d.account || seed.account || '',
            shares: rec.shares ?? '',
            entry_price: rec.entry_price ?? '',
            stop_price: rec.stop_price ?? '',
            target_price: rec.target_price ?? '',
            strike: rec.strike ?? '',
            expiration: rec.expiration ?? '',
            contracts: rec.contracts ?? 1,
            risk_reward: rec.risk_reward ?? '',
            origin_type: d.origin_type || '',
            origin_id: d.origin_id || '',
            notes: '',
          })
        }
      } catch (e: any) {
        if (!cancelled) setMsg('Failed to load recommendations: ' + String(e).slice(0, 80))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [seed])

  const isOption = seed.execution_type === 'option' || data?.execution_type === 'option' || !!f.strike
  const accountOptions: AccountOpt[] = data?.account_options?.length
    ? data.account_options
    : []

  const set = (k: string, v: any) => setF({ ...f, [k]: v })

  const selectedAcct = accountOptions.find(a => a.account_key === f.account)
  const isFidelity = data?.broker === 'fidelity' || selectedAcct?.broker === 'fidelity' || (f.account || '').includes('fidelity')

  const submit = async () => {
    if (!f.account) { setMsg('Select an account'); return }
    setBusy(true); setMsg('')
    try {
      const endpoint = isOption ? '/api/v2/options/executions/log-manual' : '/api/v2/executions/log-manual'
      const body: any = {
        symbol: seed.symbol,
        account: f.account,
        execution_type: isOption ? 'option' : 'equity',
        origin_type: f.origin_type || undefined,
        origin_id: f.origin_id || undefined,
        proposal_id: seed.proposal_id,
        options_proposal_id: seed.options_proposal_id,
        shares: f.shares ? Number(f.shares) : undefined,
        contracts: f.contracts ? Number(f.contracts) : undefined,
        entry_price: f.entry_price ? Number(f.entry_price) : undefined,
        stop_price: f.stop_price ? Number(f.stop_price) : undefined,
        target_price: f.target_price ? Number(f.target_price) : undefined,
        strike: f.strike ? Number(f.strike) : undefined,
        expiration: f.expiration || undefined,
        risk_reward: f.risk_reward ? Number(f.risk_reward) : undefined,
        notes: f.notes || undefined,
        adjusted_params: { modal: true, edited_fields: Object.keys(f) },
      }
      const r = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(x => x.json())
      if (r.ok) {
        setMsg('✅ ' + (r.message || 'Logged'))
        onLogged?.(r)
        setTimeout(onClose, 1200)
      } else setMsg('⛔ ' + (r.error || r.message || 'failed'))
    } catch (e: any) {
      setMsg('⛔ ' + String(e).slice(0, 80))
    } finally {
      setBusy(false)
    }
  }

  const brokerBadge = data?.execution_label || (isFidelity ? 'Manual · Fidelity' : 'Schwab · auto + 2FA')

  return (
    <div style={overlay} onClick={onClose}>
      <div style={card} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 900, color: TEXT0 }}>Manual execution — {seed.symbol}</div>
            <div style={{ fontSize: 10.5, color: MUTED, marginTop: 4 }}>
              Account auto-selected from holdings · Schwab = live+2FA · Fidelity = manual log only
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: MUTED, cursor: 'pointer', fontSize: 18 }}>×</button>
        </div>

        {loading ? <div style={{ fontSize: 11, color: MUTED }}>Loading recommendations…</div> : (
          <>
            <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 5, background: isFidelity ? 'rgba(167,139,250,.18)' : 'rgba(245,158,11,.18)', color: isFidelity ? PURPLE : AMBER }}>{brokerBadge}</span>
              {data?.account_auto_selected && (
                <span style={{ fontSize: 9, fontWeight: 700, padding: '3px 8px', borderRadius: 5, background: 'rgba(96,165,250,.14)', color: BLUE }}>Account auto-selected</span>
              )}
              {data?.origin_type && data.origin_type !== 'manual' && (
                <span style={{ fontSize: 9, fontWeight: 700, padding: '3px 8px', borderRadius: 5, background: 'rgba(96,165,250,.14)', color: BLUE }}>via {data.origin_type}{data.origin_id ? ` #${data.origin_id}` : ''}</span>
              )}
            </div>

            {(data?.origins?.length > 0) && (
              <label style={{ display: 'block', marginBottom: 10 }}>
                <span style={lbl}>Link to origin idea</span>
                <select style={inp} value={`${f.origin_type}|${f.origin_id}`} onChange={e => {
                  const [ot, oid] = e.target.value.split('|')
                  set('origin_type', ot); set('origin_id', oid)
                }}>
                  <option value="|">Auto-detect best match</option>
                  {data.origins.map((o: any) => (
                    <option key={`${o.origin_type}-${o.origin_id}`} value={`${o.origin_type}|${o.origin_id}`}>{o.label}</option>
                  ))}
                </select>
              </label>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <label style={{ gridColumn: '1 / -1' }}><span style={lbl}>Account</span>
                {accountOptions.length > 0 ? (
                  <select style={inp} value={f.account} onChange={e => set('account', e.target.value)}>
                    {accountOptions.map(a => (
                      <option key={a.account_key} value={a.account_key}>
                        {a.label} · {a.mode || (a.broker === 'fidelity' ? 'Manual' : 'Auto · 2FA')}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input style={inp} value={f.account} onChange={e => set('account', e.target.value)} placeholder="schwab_taxable" />
                )}
              </label>
              {!isOption && <label><span style={lbl}>Shares</span>
                <input style={inp} value={f.shares} onChange={e => set('shares', e.target.value.replace(/[^0-9]/g, ''))} />
              </label>}
              {isOption && <label><span style={lbl}>Contracts</span>
                <input style={inp} value={f.contracts} onChange={e => set('contracts', e.target.value.replace(/[^0-9]/g, ''))} />
              </label>}
              <label><span style={lbl}>{isOption ? 'Premium (per contract)' : 'Entry'}</span>
                <input style={inp} value={f.entry_price} onChange={e => set('entry_price', e.target.value)} />
              </label>
              {!isOption && <>
                <label><span style={lbl}>Stop</span>
                  <input style={inp} value={f.stop_price} onChange={e => set('stop_price', e.target.value)} />
                </label>
                <label><span style={lbl}>Target</span>
                  <input style={inp} value={f.target_price} onChange={e => set('target_price', e.target.value)} />
                </label>
              </>}
              {isOption && <>
                <label><span style={lbl}>Strike</span>
                  <input style={inp} value={f.strike} onChange={e => set('strike', e.target.value)} />
                </label>
                <label><span style={lbl}>Expiration</span>
                  <input style={inp} value={f.expiration} onChange={e => set('expiration', e.target.value)} placeholder="YYYY-MM-DD" />
                </label>
              </>}
              <label><span style={lbl}>Risk : Reward</span>
                <input style={inp} value={f.risk_reward} onChange={e => set('risk_reward', e.target.value)} />
              </label>
              <label style={{ gridColumn: '1 / -1' }}><span style={lbl}>Notes (optional)</span>
                <input style={inp} value={f.notes} onChange={e => set('notes', e.target.value)} placeholder="Filled at broker, partial fill, etc." />
              </label>
            </div>
          </>
        )}

        {msg && <div style={{ fontSize: 11, marginTop: 12, color: msg.startsWith('✅') ? GREEN : AMBER }}>{msg}</div>}

        <div style={{ display: 'flex', gap: 10, marginTop: 16, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ fontSize: 11, fontWeight: 700, padding: '7px 14px', borderRadius: 7, border: '1px solid var(--border)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>Cancel</button>
          <button onClick={submit} disabled={busy || loading} style={{ fontSize: 11, fontWeight: 800, padding: '7px 16px', borderRadius: 7, border: 'none', background: GREEN, color: '#0f172a', cursor: busy ? 'not-allowed' : 'pointer', opacity: busy ? 0.7 : 1 }}>
            {busy ? 'Logging…' : 'Executed manually →'}
          </button>
        </div>
      </div>
    </div>
  )
}