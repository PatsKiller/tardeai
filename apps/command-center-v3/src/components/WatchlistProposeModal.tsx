import { useEffect, useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { Ladder } from '../lib/exitLadder'
import {
  computeRiskSizedShares,
  deployCapFor,
  sizingFromShares,
  exceedsMaxRisk,
  exceedsDeployDollars,
  acctOptionLabel,
  resolveSizingBase,
  resolveEquity,
  parseProposalAccounts,
  parseSizingPolicy,
  pickDefaultProposalAccount,
  riskBudgetDollars,
  formatSizingBreakdown,
  type RiskPct,
  type ProposalAccount,
} from '../lib/watchlistProposeSizing'
import PositionSizingRiskBar from './risk/PositionSizingRiskBar'

const MUTED = '#94a3b8'
const TEXT0 = '#f8fafc'
const TEXT1 = '#dbeafe'
const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const RED = '#ef4444'
const BLUE = '#60a5fa'
const overlay = { position: 'fixed' as const, inset: 0, background: 'rgba(2,6,23,.78)', zIndex: 9000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }
const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 16, padding: 22, width: 'min(620px, 96vw)', maxHeight: '92vh', overflow: 'auto', boxShadow: '0 24px 80px rgba(0,0,0,.45)' }
const inp = { fontSize: 12, padding: '8px 10px', borderRadius: 8, border: '1px solid rgba(148,163,184,.28)', background: 'rgba(15,23,42,.6)', color: TEXT0, width: '100%', fontFamily: 'monospace' } as const
const lbl = { fontSize: 10, color: MUTED, display: 'block', marginBottom: 5, textTransform: 'uppercase' as const, letterSpacing: '0.4px' }

function money(v: number | null | undefined, compact = false) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  const n = Number(v)
  if (compact && Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}k`
  return `$${n.toFixed(2)}`
}

export type WatchlistProposeSeed = {
  it: any
  entry: number | null
  stop: number | null
  planTarget: number | null
  rr: number | null
  ladder: Ladder | null
  pa?: any
  /** Optional prefill from the card's Sizing & Account Risk module. */
  account_key?: string
  risk_pct?: RiskPct
}

type Props = {
  seed: WatchlistProposeSeed
  onClose: () => void
  onProposed?: (res: { proposal_id?: number; symbol: string; message?: string }) => void
}

function MetricBox({ label, value, sub, color = TEXT0 }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{ padding: '10px 12px', borderRadius: 10, background: 'rgba(15,23,42,.55)', border: '1px solid rgba(148,163,184,.15)' }}>
      <div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase', letterSpacing: '0.35px', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 800, color, fontFamily: 'monospace' }}>{value}</div>
      {sub && <div style={{ fontSize: 9, color: MUTED, marginTop: 3 }}>{sub}</div>}
    </div>
  )
}

export default function WatchlistProposeModal({ seed, onClose, onProposed }: Props) {
  const { it, entry, stop, planTarget, rr, ladder, pa } = seed
  const { data: acctR, loading: acctLoading, error: acctError, refetch: refetchAccounts } = useApi<any>('/api/v2/proposal-accounts', 35_000)

  const [riskPct, setRiskPct] = useState<RiskPct>(seed.risk_pct ?? 1)
  const [account, setAccount] = useState(seed.account_key ?? '')
  const [shares, setShares] = useState('')
  const [sharesTouched, setSharesTouched] = useState(false)
  const [confirmOverRisk, setConfirmOverRisk] = useState(false)
  const [confirmOverCash, setConfirmOverCash] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const accounts: ProposalAccount[] = useMemo(() => parseProposalAccounts(acctR), [acctR])
  const watchLists = String(it.watch_lists || '').split(' · ').map((s: string) => s.trim()).filter(Boolean)

  useEffect(() => { refetchAccounts() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (account || !accounts.length) return
    const pref = pickDefaultProposalAccount(accounts)
    if (pref?.account_key) setAccount(pref.account_key)
  }, [accounts, account])

  const selAcct = accounts.find(a => a.account_key === account)
  const sizingBase = resolveSizingBase(selAcct)
  const equity = resolveEquity(selAcct)

  const sizingPolicy = useMemo(() => parseSizingPolicy(acctR), [acctR])
  // Per-account cap (backend policy max_position_allocation_pct) wins over the desk fallback.
  const deployCap = deployCapFor(selAcct, sizingPolicy.maxDeployPctOfCash)

  const autoSized = useMemo(() => {
    if (!entry || !stop || !planTarget || entry <= stop || planTarget <= entry || sizingBase <= 0) return null
    return computeRiskSizedShares({
      sizingBase, equity, entry, stop, target: planTarget, riskPct,
      maxDeployDollars: deployCap?.dollars,
    })
  }, [sizingBase, equity, entry, stop, planTarget, riskPct, deployCap?.dollars])

  useEffect(() => {
    if (sharesTouched || !autoSized?.shares) return
    setShares(String(autoSized.shares))
    setConfirmOverRisk(false)
    setConfirmOverCash(false)
  }, [autoSized?.shares, sharesTouched, riskPct, account])

  const sized = useMemo(() => {
    if (!entry || !stop || !planTarget || sizingBase <= 0) return null
    const sh = Number(shares)
    if (!Number.isFinite(sh) || sh <= 0) return autoSized
    return sizingFromShares({ sizingBase, equity, entry, stop, target: planTarget, shares: sh })
  }, [sizingBase, equity, entry, stop, planTarget, shares, autoSized])

  const overMaxRisk = sized ? exceedsMaxRisk(sized.pctOfCash) : false
  const overCash = sized?.exceedsCash ?? false
  // Desk concentration limit — HARD cap, no confirm-around (unlike risk/cash which are overridable).
  const overDeploy = sized ? exceedsDeployDollars(sized.investment, deployCap) : false
  const needsRiskConfirm = overMaxRisk && !confirmOverRisk
  const needsCashConfirm = overCash && !confirmOverCash
  const needsConfirm = needsRiskConfirm || needsCashConfirm

  const cioLabel = it.latest_recommendation
    ? String(it.latest_recommendation).replace(/_/g, ' ')
    : (pa?.rec ? String(pa.rec).replace(/_/g, ' ') : 'watch')
  const conf = it.research_confidence ?? it.hermes_score_components?._confidence

  const queueProposal = async () => {
    if (!entry || !stop || !planTarget || entry <= stop || planTarget <= entry) {
      setMsg('Plan incomplete — need limit, stop, and target')
      return
    }
    if (!account) {
      setMsg('Select a destination account')
      return
    }
    if (sizingBase <= 0) {
      setMsg('Cash / buying power unavailable for this account — refresh balances or pick another account')
      return
    }
    const sh = Number(shares)
    if (!Number.isFinite(sh) || sh <= 0) {
      setMsg('Position size must be at least 1 share')
      return
    }
    if (overDeploy) {
      setMsg(`⛔ Deployment exceeds the desk concentration cap (${deployCap?.label} per position) — reduce size. Hard limit, no override.`)
      return
    }
    if (needsRiskConfirm) {
      setMsg('Confirm elevated risk (>2% of available cash) before queuing')
      return
    }
    if (needsCashConfirm) {
      setMsg('Confirm investment above available cash before queuing')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      const r = await fetch(`/api/v2/watchlist/${it.symbol}/propose`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          entry, stop, target: planTarget, shares: sh, account,
          risk_pct: riskPct, confirm_over_risk: confirmOverRisk,
          confirm_over_cash: confirmOverCash,
          source: 'watchlist_card',
        }),
      }).then(x => x.json())
      const payload = r.data ?? r
      if (r.ok || payload.ok) {
        const pid = payload.proposal_id
        setMsg(`✅ ${payload.message || `Queued proposal #${pid}`}`)
        onProposed?.({ proposal_id: pid, symbol: it.symbol, message: payload.message })
        setTimeout(onClose, 1400)
      } else {
        setMsg('⛔ ' + (payload.error || r.error || 'queue failed'))
      }
    } catch (e: any) {
      setMsg('⛔ ' + String(e).slice(0, 80))
    } finally {
      setBusy(false)
    }
  }

  const openDesk = () => {
    window.location.href = `/v3/trading?tab=Entry+Desk&symbol=${it.symbol}`
  }

  const onRiskPctChange = (pct: RiskPct) => {
    setRiskPct(pct)
    setSharesTouched(false)
    setConfirmOverRisk(false)
    setConfirmOverCash(false)
  }

  const onAccountChange = (key: string) => {
    setAccount(key)
    setSharesTouched(false)
    setConfirmOverRisk(false)
    setConfirmOverCash(false)
  }

  const onSharesChange = (v: string) => {
    setSharesTouched(true)
    setShares(v.replace(/[^0-9]/g, ''))
    setConfirmOverRisk(false)
    setConfirmOverCash(false)
  }

  const applyAutoSize = () => {
    if (sizingBase <= 0) {
      setMsg('Select an account with available cash before auto-sizing')
      return
    }
    if (!autoSized?.shares) {
      setMsg('Cannot auto-size — check limit/stop/target and account cash')
      return
    }
    setSharesTouched(false)
    setShares(String(autoSized.shares))
    setConfirmOverRisk(false)
    setConfirmOverCash(false)
    setMsg('')
  }

  const sizingLabel = selAcct?.is_retirement ? 'available cash' : (selAcct?.sizing_base_label === 'buying_power' ? 'buying power' : 'available cash')

  return (
    <div style={overlay} onClick={onClose}>
      <div style={card} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 900, color: TEXT0 }}>
              Propose entry · <span style={{ fontFamily: 'monospace' }}>{it.symbol}</span>
            </div>
            <div style={{ fontSize: 11, color: MUTED, marginTop: 5, lineHeight: 1.45 }}>
              Size at 1–2% of <b>available cash</b> (not total equity), then queue the proposal. Does not place live orders.
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: MUTED, cursor: 'pointer', fontSize: 22, lineHeight: 1 }}>×</button>
        </div>

        <div style={{ marginBottom: 14, padding: '12px 14px', borderRadius: 10, background: 'rgba(15,23,42,.45)', border: '1px solid rgba(148,163,184,.15)' }}>
          <div style={{ fontSize: 9, fontWeight: 800, color: MUTED, textTransform: 'uppercase', marginBottom: 8 }}>Trade plan</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
            <MetricBox label="Limit" value={money(entry)} />
            <MetricBox label="Stop" value={money(stop)} color={RED} />
            <MetricBox label="Target" value={money(planTarget)} color={GREEN} />
            <MetricBox label="R:R" value={rr != null ? `${rr.toFixed(2)} : 1` : '—'} color={rr != null && rr >= 1.5 ? GREEN : AMBER} />
          </div>
          <div style={{ fontSize: 10, color: MUTED, marginTop: 10, lineHeight: 1.5 }}>
            <span><b>CIO</b> {cioLabel}</span>
            {conf != null && <span> · <b>Conf</b> {Number(conf).toFixed(2)}</span>}
            {it.entry_urgency && <span> · <b>Urgency</b> {String(it.entry_urgency).replace(/_/g, ' ')}</span>}
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
          <label>
            <span style={lbl}>Destination account</span>
            <select
              style={{ ...inp, fontFamily: 'inherit' }}
              value={account}
              onChange={e => onAccountChange(e.target.value)}
              disabled={acctLoading}
            >
              <option value="">
                {acctLoading ? 'Loading accounts…' : accounts.length ? '— select account —' : 'No accounts loaded'}
              </option>
              {accounts.map(a => (
                <option key={a.account_key} value={a.account_key} disabled={!resolveSizingBase(a)}>
                  {acctOptionLabel(a)}{!resolveSizingBase(a) ? ' · cash unavailable' : ''}
                </option>
              ))}
            </select>
            {acctError && (
              <div style={{ fontSize: 10, color: RED, marginTop: 6 }}>
                Failed to load accounts: {acctError}
                <button type="button" onClick={refetchAccounts} style={{ marginLeft: 8, fontSize: 9, fontWeight: 700, cursor: 'pointer', border: 'none', background: 'none', color: BLUE }}>Retry</button>
              </div>
            )}
            {!acctLoading && !acctError && accounts.length === 0 && (
              <div style={{ fontSize: 10, color: AMBER, marginTop: 6 }}>
                No proposal accounts returned — check broker_accounts and holdings snapshot.
                <button type="button" onClick={refetchAccounts} style={{ marginLeft: 8, fontSize: 9, fontWeight: 700, cursor: 'pointer', border: 'none', background: 'none', color: BLUE }}>Retry</button>
              </div>
            )}
          </label>
          <label>
            <span style={lbl}>Watchlist membership</span>
            <div style={{
              ...inp, fontFamily: 'inherit', minHeight: 36, display: 'flex', alignItems: 'center',
              color: watchLists.length ? TEXT1 : MUTED,
            }}>
              {watchLists.length ? watchLists.join(' · ') : 'General watchlist'}
            </div>
          </label>
        </div>

        {selAcct && (
          <div style={{ marginBottom: 14, padding: '10px 12px', borderRadius: 10, background: 'rgba(96,165,250,.06)', border: '1px solid rgba(96,165,250,.2)' }}>
            <div style={{ fontSize: 9, fontWeight: 800, color: MUTED, textTransform: 'uppercase', marginBottom: 8 }}>
              Account balances · sizing uses <b style={{ color: GREEN }}>{sizingLabel}</b> only
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
              <MetricBox
                label="Total equity"
                value={money(equity, true)}
                sub={`reference only · ${selAcct.equity_source || 'portfolio'}`}
                color={BLUE}
              />
              <MetricBox
                label="Available cash"
                value={money(selAcct.cash, true)}
                sub={selAcct.is_retirement ? 'IRA — no margin' : 'settled cash'}
                color={GREEN}
              />
              {!selAcct.is_retirement && selAcct.buying_power != null && (
                <MetricBox
                  label="Buying power"
                  value={money(selAcct.buying_power, true)}
                  sub={selAcct.sizing_base_label === 'buying_power' ? 'used for sizing' : 'margin taxable'}
                />
              )}
              <MetricBox
                label="Risk budget"
                value={money(riskBudgetDollars(sizingBase, riskPct), true)}
                sub={`${riskPct}% of ${money(sizingBase, true)} ${sizingLabel}`}
                color={sizingBase > 0 ? GREEN : AMBER}
              />
            </div>
          </div>
        )}

        <div style={{ marginBottom: 14, padding: '12px 14px', borderRadius: 10, background: 'rgba(34,197,94,.05)', border: '1px solid rgba(34,197,94,.18)' }}>
          <div style={{ fontSize: 9, fontWeight: 800, color: MUTED, textTransform: 'uppercase', marginBottom: 10 }}>Risk management</div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 10, color: MUTED, fontWeight: 700 }}>Risk per trade:</span>
            {([1, 2] as RiskPct[]).map(pct => (
              <button
                key={pct}
                type="button"
                onClick={() => onRiskPctChange(pct)}
                style={{
                  fontSize: 11, fontWeight: 800, padding: '7px 14px', borderRadius: 8, cursor: 'pointer',
                  border: riskPct === pct ? `1px solid ${GREEN}` : '1px solid rgba(148,163,184,.25)',
                  background: riskPct === pct ? 'rgba(34,197,94,.15)' : 'transparent',
                  color: riskPct === pct ? GREEN : MUTED,
                }}
              >{pct}% of {sizingLabel}</button>
            ))}
            <span style={{ fontSize: 9, color: MUTED }}>Default 1% cash · max 2% without override</span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 10, alignItems: 'end' }}>
            <label>
              <span style={lbl}>
                Shares {autoSized ? `(auto ${autoSized.shares.toLocaleString()} @ ${riskPct}% cash)` : ''}
              </span>
              <input style={inp} value={shares} onChange={e => onSharesChange(e.target.value)} />
            </label>
            <button
              type="button"
              onClick={applyAutoSize}
              disabled={!autoSized?.shares}
              style={{ fontSize: 10, fontWeight: 700, padding: '9px 12px', borderRadius: 8, border: `1px solid ${GREEN}`, background: 'rgba(34,197,94,.1)', color: GREEN, cursor: 'pointer' }}
            >Apply auto-size</button>
          </div>

          {sized && sized.shares > 0 && entry && stop && (
            <div style={{ marginTop: 10, fontSize: 10, color: TEXT1, lineHeight: 1.5, padding: '8px 10px', borderRadius: 8, background: 'rgba(15,23,42,.45)', border: '1px solid rgba(148,163,184,.12)' }}>
              <span style={{ color: MUTED, fontWeight: 800 }}>Sizing math · </span>
              {formatSizingBreakdown({
                sizingBase, equity, riskPct, entry, stop,
                shares: sized.shares, sizingLabel,
              })}
            </div>
          )}

          {sized && sized.shares > 0 && (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginTop: 12 }}>
                <MetricBox
                  label="Dollar risk"
                  value={money(sized.dollarRisk, true)}
                  sub={`${sized.pctOfCash.toFixed(2)}% of ${sizingLabel} · ${sized.pctOfEquity.toFixed(2)}% of equity (ref)`}
                  color={overMaxRisk ? RED : GREEN}
                />
                <MetricBox
                  label="Investment required"
                  value={money(sized.investment, true)}
                  sub={`${sized.shares.toLocaleString()} sh × ${money(entry)}${overCash ? ' · over cash' : ''}`}
                  color={overCash ? RED : BLUE}
                />
                <MetricBox
                  label="Profit @ target"
                  value={money(sized.profitAtTarget, true)}
                  sub={planTarget ? `+${(((planTarget - (entry || 0)) / (entry || 1)) * 100).toFixed(1)}%` : undefined}
                  color={GREEN}
                />
              </div>
              {autoSized && (
                <PositionSizingRiskBar
                  queuedShares={sized.shares}
                  capShares={autoSized.shares}
                  accountLabel={selAcct?.display_name || account}
                  alwaysShow={sharesTouched}
                />
              )}
            </>
          )}

          {overMaxRisk && (
            <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8, background: 'rgba(239,68,68,.08)', border: '1px solid rgba(239,68,68,.25)' }}>
              <div style={{ fontSize: 10, fontWeight: 800, color: RED, marginBottom: 6 }}>
                Risk exceeds 2% of available cash — {sized?.pctOfCash.toFixed(2)}% ({sized?.pctOfEquity.toFixed(2)}% of equity)
              </div>
              <label style={{ fontSize: 10, color: TEXT1, display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' }}>
                <input type="checkbox" checked={confirmOverRisk} onChange={e => setConfirmOverRisk(e.target.checked)} />
                I confirm sizing above the 2% cash risk cap
              </label>
            </div>
          )}

          {overCash && (
            <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8, background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.25)' }}>
              <div style={{ fontSize: 10, fontWeight: 800, color: AMBER, marginBottom: 6 }}>
                Investment {money(sized?.investment, true)} exceeds available cash {money(sizingBase, true)}
                {sized?.cashCapShares ? ` — max ${sized.cashCapShares.toLocaleString()} shares at this limit` : ''}
              </div>
              <label style={{ fontSize: 10, color: TEXT1, display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' }}>
                <input type="checkbox" checked={confirmOverCash} onChange={e => setConfirmOverCash(e.target.checked)} />
                I confirm deploying more cash than currently available (pending settlement / transfer)
              </label>
            </div>
          )}
        </div>

        {ladder && ladder.steps.length > 0 && (
          <details style={{ marginBottom: 14 }}>
            <summary style={{ fontSize: 10, fontWeight: 700, color: MUTED, cursor: 'pointer' }}>Exit ladder</summary>
            <div style={{ marginTop: 8, padding: '10px 12px', borderRadius: 10, background: 'rgba(15,23,42,.4)', border: '1px solid rgba(148,163,184,.12)' }}>
              {ladder.steps.map((s, i) => (
                <div key={i} style={{ fontSize: 10, color: '#cbd5e1', marginTop: i ? 3 : 0, fontFamily: 'monospace' }}>
                  {s.label} {s.px.toFixed(2)} — <span style={{ color: MUTED, fontFamily: 'inherit' }}>{s.action}</span>
                </div>
              ))}
              <div style={{ fontSize: 9, color: MUTED, marginTop: 6 }}>R ${ladder.R.toFixed(2)}/sh</div>
            </div>
          </details>
        )}

        {msg && (
          <div style={{
            fontSize: 11, marginBottom: 12, padding: '8px 10px', borderRadius: 8,
            background: msg.startsWith('✅') ? 'rgba(34,197,94,.12)' : 'rgba(245,158,11,.12)',
            color: msg.startsWith('✅') ? GREEN : AMBER,
          }}>{msg}</div>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <button onClick={onClose} style={{ fontSize: 11, fontWeight: 700, padding: '9px 16px', borderRadius: 8, border: '1px solid var(--border)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>Cancel</button>
          <button onClick={openDesk} style={{ fontSize: 11, fontWeight: 700, padding: '9px 16px', borderRadius: 8, border: '1px solid var(--border)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>Open Entry Desk</button>
          <button
            onClick={queueProposal}
            disabled={busy || needsConfirm || !account || !sized?.shares || sizingBase <= 0}
            style={{ fontSize: 12, fontWeight: 800, padding: '9px 20px', borderRadius: 8, border: 'none', background: needsConfirm ? MUTED : GREEN, color: '#fff', cursor: busy || needsConfirm ? 'not-allowed' : 'pointer', opacity: busy ? 0.7 : 1 }}
          >
            {busy ? 'Queuing…' : needsConfirm ? 'Confirm to proceed' : 'Send to proposal queue'}
          </button>
        </div>
      </div>
    </div>
  )
}