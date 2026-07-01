import { useEffect, useMemo, useState } from 'react'
import HoldingProtectionActions from './HoldingProtectionActions'
import { mergeLiveStop } from '../lib/stopReviewTooltip'

// Portfolio → Stop Management. Aggregates broker-actual + advisor-planned stops with Yellow/Amber/Red alerts,
// plus an Audit sub-tab (2FA stop requests + operator confirmations). Read-only view; live adjustments route
// through the holding's existing gated 2FA panel (Schwab) or manual ticket (Fidelity) via onFocusHolding.
// See docs/MOMENTUM_SCALP_STOP_MONITORING_PROTOCOL.md.

const MUTED = '#94a3b8', TEXT0 = '#f8fafc', GREEN = '#22c55e', AMBER = '#f59e0b', RED = '#ef4444', BLUE = '#60a5fa', PURPLE = '#a855f7'
const unwrap = (j: any) => (j && typeof j === 'object' && 'data' in j && j.data && typeof j.data === 'object') ? j.data : j
const LEVEL_COLOR: Record<string, string> = { red: RED, amber: AMBER, yellow: '#eab308' }
const SRC_LABEL: Record<string, string> = { broker: 'broker live', confirmed: 'confirmed', broker_snapshot: 'broker (last read)', monitored: 'monitored', planned: 'planned', none: '—' }
const fmt$ = (n: any) => n == null ? '—' : `$${Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
const fmtStop = (n: any) => n == null ? '—' : `$${Number(n).toFixed(2)}`
const fmtTime = (s: any) => { if (!s) return '—'; const d = new Date(s); return isNaN(+d) ? String(s).slice(0, 16) : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }

interface Props { onFocusHolding?: (symbol: string, account: string) => void }

type Row = {
  symbol: string; account: string; broker: string; route: string; stop_type: string; stop_source: string
  current_price: number; qty: number; broker_stop: number | null; planned_stop: number | null; stop: number
  divergence: string | null; distance_pct: number | null; distance_atr: number | null; distance_r: number | null
  dollars_at_risk: number; unrealized_dollars: number | null; has_active_stop: boolean
  is_trailing: boolean; trailing_should_be_active: boolean; heat_contribution_pct: number | null
  trail_pct: number | null; trailing_trigger: number | null
  trail_recommended: boolean; rec_source: string | null; rec_model: string | null; rec_rationale: string | null
  alert_level: 'red' | 'amber' | 'yellow' | null; alert_reasons: string[]
}

function Pill({ level }: { level: string | null }) {
  if (!level) return <span style={{ fontSize: 11, color: GREEN }}>● ok</span>
  const c = LEVEL_COLOR[level] || MUTED
  return <span style={{ fontSize: 11, fontWeight: 800, color: c, background: `${c}1e`, border: `1px solid ${c}`, borderRadius: 999, padding: '2px 8px', textTransform: 'uppercase' }}>{level}</span>
}

function Card({ label, value, color = TEXT0, sub }: { label: string; value: string; color?: string; sub?: string }) {
  return (
    <div style={{ flex: '1 1 150px', padding: '11px 13px', borderRadius: 9, background: 'var(--bg2, rgba(15,23,42,.6))', border: '1px solid rgba(148,163,184,.2)' }}>
      <div style={{ fontSize: 11, color: MUTED, fontWeight: 700, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 21, fontWeight: 900, color }}>{value}</div>
      {sub && <div style={{ fontSize: 10.5, color: MUTED, marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

const QUICK = ['All', 'Needs Attention', 'No Stop Placed', 'Has Active Stop', 'Trailing Not Active', 'High Heat'] as const

export default function StopManagement({ onFocusHolding }: Props) {
  const [sub, setSub] = useState<'Monitor' | 'Audit'>('Monitor')
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [quick, setQuick] = useState<typeof QUICK[number]>('All')
  const [acct, setAcct] = useState('All')
  const [level, setLevel] = useState('All')
  const [adjust, setAdjust] = useState<Row | null>(null)

  const load = () => {
    setLoading(true)
    fetch('/api/v2/stops/management').then(x => x.json()).then(j => setData(unwrap(j))).catch(() => setData(null)).finally(() => setLoading(false))
  }
  useEffect(load, [])

  const rows: Row[] = data?.rows ?? []
  const summary = data?.summary ?? {}
  const accounts = useMemo(() => ['All', ...Array.from(new Set(rows.map(r => r.account)))], [rows])

  const filtered = rows.filter(r => {
    if (acct !== 'All' && r.account !== acct) return false
    if (level !== 'All' && r.alert_level !== level) return false
    if (quick === 'Needs Attention' && !(r.alert_level === 'amber' || r.alert_level === 'red')) return false
    if (quick === 'No Stop Placed' && r.has_active_stop) return false
    if (quick === 'Has Active Stop' && !r.has_active_stop) return false
    if (quick === 'Trailing Not Active' && !r.trailing_should_be_active) return false
    if (quick === 'High Heat' && !((r.heat_contribution_pct ?? 0) >= 1.5)) return false
    return true
  })

  return (
    <div style={{ padding: '4px 2px' }}>
      {/* sub-tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
        {(['Monitor', 'Audit'] as const).map(t => (
          <button key={t} onClick={() => setSub(t)} style={{ fontSize: 13, fontWeight: 800, padding: '5px 14px', borderRadius: 7, cursor: 'pointer',
            border: `1px solid ${sub === t ? BLUE : 'rgba(148,163,184,.3)'}`, background: sub === t ? `${BLUE}18` : 'transparent', color: sub === t ? BLUE : MUTED }}>{t}</button>
        ))}
      </div>

      {sub === 'Audit' ? <AuditView /> : (
        <>
          {/* Summary cards */}
          <div style={{ display: 'flex', gap: 9, flexWrap: 'wrap', marginBottom: 12 }}>
            <Card label="Total Open Risk" value={fmt$(summary.total_open_risk)} />
            <Card label="Active Stops" value={`${summary.broker_stops_active ?? 0} / ${summary.positions ?? 0}`}
              color={(summary.no_stop ?? 0) > 0 ? AMBER : GREEN} sub={`${summary.no_stop ?? 0} with no active stop`} />
            <Card label="Red / Amber / Yellow" value={`${summary.red ?? 0} / ${summary.amber ?? 0} / ${summary.yellow ?? 0}`}
              color={(summary.red ?? 0) > 0 ? RED : (summary.amber ?? 0) > 0 ? AMBER : GREEN} />
            <Card label="Portfolio Heat" value={`${(summary.portfolio_heat_pct ?? 0).toFixed(1)}% / ${summary.heat_cap ?? 5}%`}
              color={(summary.portfolio_heat_pct ?? 0) > (summary.heat_cap ?? 5) ? RED : TEXT0} />
            <Card label="Trailing Not Active" value={String(summary.trailing_not_active ?? 0)} color={(summary.trailing_not_active ?? 0) > 0 ? AMBER : TEXT0} />
          </div>

          {/* Filters */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
            {QUICK.map(qv => (
              <button key={qv} onClick={() => setQuick(qv)} style={{ fontSize: 12, fontWeight: 700, padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
                border: `1px solid ${quick === qv ? BLUE : 'rgba(148,163,184,.3)'}`, background: quick === qv ? `${BLUE}18` : 'transparent', color: quick === qv ? BLUE : MUTED }}>{qv}</button>
            ))}
            <span style={{ width: 8 }} />
            <select value={acct} onChange={e => setAcct(e.target.value)} style={{ fontSize: 12, padding: '4px 6px', borderRadius: 6, background: 'var(--bg2)', color: TEXT0, border: '1px solid rgba(148,163,184,.3)' }}>
              {accounts.map(a => <option key={a} value={a}>{a === 'All' ? 'All accounts' : a}</option>)}
            </select>
            <select value={level} onChange={e => setLevel(e.target.value)} style={{ fontSize: 12, padding: '4px 6px', borderRadius: 6, background: 'var(--bg2)', color: TEXT0, border: '1px solid rgba(148,163,184,.3)' }}>
              {['All', 'red', 'amber', 'yellow'].map(l => <option key={l} value={l}>{l === 'All' ? 'All levels' : l}</option>)}
            </select>
            <button onClick={load} style={{ fontSize: 12, fontWeight: 700, padding: '4px 10px', borderRadius: 6, cursor: 'pointer', border: `1px solid ${BLUE}`, background: `${BLUE}18`, color: BLUE }}>↻ Refresh</button>
            <span style={{ fontSize: 11, color: MUTED }}>{loading ? 'loading…' : `${filtered.length} of ${rows.length} · regime ${data?.regime_now ?? '—'}`}</span>
          </div>

          {/* Table */}
          <div style={{ overflowX: 'auto', border: '1px solid rgba(148,163,184,.18)', borderRadius: 9 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
              <thead>
                <tr style={{ color: MUTED, textAlign: 'left', background: 'rgba(15,23,42,.5)' }}>
                  {['Alert', 'Symbol · Account', 'Route', 'Active stop', 'Stop (broker / planned)', 'Distance', 'Unreal.', '$ at risk', 'Reasons', ''].map(h =>
                    <th key={h} style={{ padding: '8px 9px', fontWeight: 800, whiteSpace: 'nowrap' }}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {filtered.map((r, i) => (
                  <tr key={`${r.symbol}-${r.account}-${i}`} style={{ borderTop: '1px solid rgba(148,163,184,.12)', color: TEXT0 }}>
                    <td style={{ padding: '7px 9px' }}><Pill level={r.alert_level} /></td>
                    <td style={{ padding: '7px 9px', whiteSpace: 'nowrap' }}><b>{r.symbol}</b><br /><span style={{ fontSize: 10.5, color: MUTED }}>{r.account}</span></td>
                    <td style={{ padding: '7px 9px', color: MUTED, fontSize: 11 }}>{r.route}</td>
                    <td style={{ padding: '7px 9px', whiteSpace: 'nowrap' }}>
                      {r.has_active_stop
                        ? <span style={{ color: GREEN, fontWeight: 700 }}>● {r.is_trailing ? 'TRAILING' : r.stop_type}<div style={{ fontSize: 9.5, color: MUTED, fontWeight: 400 }}>{SRC_LABEL[r.stop_source] || r.stop_source}</div></span>
                        : <span style={{ color: AMBER }}>○ none<div style={{ fontSize: 9.5, color: MUTED }}>{r.planned_stop != null ? 'planned only' : '—'}</div></span>}
                      {r.trailing_should_be_active ? <span style={{ color: AMBER }} title="trailing eligible but not active"> ⚠</span> : null}
                    </td>
                    <td style={{ padding: '7px 9px', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                      <span style={{ color: r.broker_stop != null ? GREEN : MUTED }}>{fmtStop(r.broker_stop)}</span> / <span style={{ color: AMBER }}>{fmtStop(r.planned_stop)}</span>
                      {r.trailing_trigger != null && (
                        <div style={{ fontSize: 10, color: GREEN }} title="Trailing stop: ratchets up with price; shown at the current-equivalent trigger">
                          trail {r.trail_pct}% (≈{fmtStop(r.trailing_trigger)})
                        </div>
                      )}
                      {r.rec_source ? (
                        <div style={{ fontSize: 9.5, color: /grok|gpt|claude/i.test(r.rec_model || '') ? PURPLE : MUTED }}
                          title={r.rec_rationale || undefined}>
                          rec: {r.trail_recommended ? 'trail' : 'fixed'} · {r.rec_source.split(' · ')[0]}
                        </div>
                      ) : null}
                      {r.divergence ? <div style={{ fontSize: 10, color: r.has_active_stop ? RED : MUTED }}>{r.divergence}</div> : null}
                    </td>
                    <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', fontSize: 11 }}>
                      {r.distance_pct != null ? `${r.distance_pct}%` : '—'}{r.distance_atr != null ? ` · ${r.distance_atr}ATR` : ''}{r.distance_r != null ? ` · ${r.distance_r}R` : ''}
                    </td>
                    <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', color: (r.unrealized_dollars ?? 0) >= 0 ? GREEN : RED }}>{r.unrealized_dollars != null ? fmt$(r.unrealized_dollars) : '—'}</td>
                    <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', fontWeight: 700 }}>{fmt$(r.dollars_at_risk)}</td>
                    <td style={{ padding: '7px 9px', fontSize: 10.5, color: MUTED, maxWidth: 220 }}>{(r.alert_reasons || []).join(' · ')}</td>
                    <td style={{ padding: '7px 9px', whiteSpace: 'nowrap' }}>
                      {r.trailing_should_be_active && (
                        <button onClick={() => onFocusHolding?.(r.symbol, r.account)}
                          title={`Advisor recommends trailing (P&L + >50d SMA) — request a ${r.account.startsWith('fidelity') ? 'manual' : '2FA'} trailing stop to lock in profit`}
                          style={{ fontSize: 11, fontWeight: 800, padding: '3px 9px', borderRadius: 5, cursor: 'pointer', marginRight: 5,
                            border: `1px solid ${GREEN}`, background: `${GREEN}20`, color: GREEN, whiteSpace: 'nowrap' }}>
                          🔒 Trail {r.account.startsWith('fidelity') ? 'manual' : '2FA'}
                        </button>
                      )}
                      <button onClick={() => setAdjust(r)} style={{ fontSize: 11, fontWeight: 700, padding: '3px 9px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${BLUE}`, background: `${BLUE}18`, color: BLUE, whiteSpace: 'nowrap' }}>Adjust stop</button>
                    </td>
                  </tr>
                ))}
                {!loading && filtered.length === 0 && (
                  <tr><td colSpan={10} style={{ padding: 20, textAlign: 'center', color: MUTED }}>No positions match this filter.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {adjust && <AdjustModal row={adjust} onClose={() => setAdjust(null)} onFocusHolding={onFocusHolding} />}
        </>
      )}
    </div>
  )
}

// Adjust modal — broker-aware stop-type selection. Choosing a type jumps to the holding's inline gated panel
// (Schwab → per-order 2FA request; Fidelity → manual ticket). No stop is submitted from here.
function AdjustModal({ row, onClose, onFocusHolding }: { row: Row; onClose: () => void; onFocusHolding?: (s: string, a: string) => void }) {
  const isFidelity = row.account.startsWith('fidelity')
  const recKind = row.trail_recommended ? 'TRAILING' : 'FIXED'
  // Assemble the exact props the holding card passes, so the inline panel renders identical live-stop state
  // (never a false "none"). Sources: portfolio/holdings, portfolio/llm-coverage (protection + confirmed_stops),
  // holdings/live-stops (by_key), holdings/monitored-stops (by_key). Then reuse the same protective-stop panel.
  const [pack, setPack] = useState<{ h: any; pr: any; mon: any; conf: any; fetchedAt: any } | null>(null)
  const [perr, setPerr] = useState('')
  const [reloadKey, setReloadKey] = useState(0)
  useEffect(() => {
    let cancelled = false
    const key = `${row.symbol.toUpperCase()}:${row.account}`
    Promise.all([
      fetch('/api/v2/portfolio/holdings').then(x => x.json()).catch(() => null),
      fetch('/api/v2/portfolio/llm-coverage').then(x => x.json()).catch(() => null),
      fetch('/api/v2/holdings/live-stops').then(x => x.json()).catch(() => null),
      fetch('/api/v2/holdings/monitored-stops').then(x => x.json()).catch(() => null),
    ]).then(([hj, cj, lj, mj]) => {
      if (cancelled) return
      const hd = unwrap(hj) ?? {}
      const arr: any[] = Array.isArray(hd) ? hd : (hd.holdings ?? [])
      const h = arr.find(x => String(x.symbol).toUpperCase() === row.symbol.toUpperCase() && String(x.account) === row.account)
      const cov = unwrap(cj) ?? {}
      const pr = (cov.protection ?? {})[row.symbol.toUpperCase()] ?? {}
      const ls = unwrap(lj) ?? {}
      const conf = mergeLiveStop((cov.confirmed_stops ?? {})[key], (ls.by_key ?? {})[key])
      const mon = (unwrap(mj)?.by_key ?? {})[key]
      const fetchedAt = ls.fetched_at ?? cov.broker_stops_fetched_at ?? null
      if (h) setPack({ h, pr, mon, conf, fetchedAt }); else setPerr('holding not found for this symbol/account')
    }).catch(() => setPerr('could not load holding data'))
    return () => { cancelled = true }
  }, [row.symbol, row.account, reloadKey])

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', display: 'flex', alignItems: 'flex-start', justifyContent: 'center', zIndex: 1000, padding: '4vh 0', overflow: 'auto' }}>
      <div onClick={e => e.stopPropagation()} style={{ width: 760, maxWidth: '94vw', maxHeight: '92vh', overflow: 'auto', background: 'var(--bg1, #0f172a)', border: '1px solid rgba(148,163,184,.3)', borderRadius: 12, padding: 18 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <div style={{ fontSize: 16, fontWeight: 900, color: TEXT0 }}>Manage stop — {row.symbol}</div>
          <button onClick={onClose} style={{ fontSize: 18, color: MUTED, background: 'none', border: 'none', cursor: 'pointer' }}>×</button>
        </div>
        <div style={{ fontSize: 12.5, color: TEXT0, lineHeight: 1.6, marginBottom: 10 }}>
          <b>{row.account}</b> · {row.route} · <span style={{ color: isFidelity ? AMBER : BLUE }}>{isFidelity ? 'Fidelity (manual)' : 'Schwab (2FA)'}</span><br />
          Price <b>{fmtStop(row.current_price)}</b> · Active stop <b style={{ color: row.broker_stop != null ? GREEN : AMBER }}>{row.broker_stop != null ? `${fmtStop(row.broker_stop)} (${SRC_LABEL[row.stop_source] || row.stop_source})` : 'none'}</b> · Advised fixed <b style={{ color: AMBER }}>{fmtStop(row.planned_stop)}</b>{row.trailing_trigger != null ? <> · Trail <b style={{ color: GREEN }}>{row.trail_pct}% (≈{fmtStop(row.trailing_trigger)})</b></> : null}<br />
          Distance {row.distance_pct}%{row.distance_atr != null ? ` · ${row.distance_atr}ATR` : ''} · $ at risk <b>{fmt$(row.dollars_at_risk)}</b>
        </div>

        {/* Recommendation attribution — who (system vs external LLM) recommends fixed vs trailing */}
        <div style={{ fontSize: 12, padding: '8px 11px', borderRadius: 8, marginBottom: 12,
          background: row.trail_recommended ? `${GREEN}12` : 'rgba(15,23,42,.5)',
          border: `1px solid ${row.trail_recommended ? GREEN : 'rgba(148,163,184,.3)'}` }}>
          <b style={{ color: row.trail_recommended ? GREEN : AMBER }}>Recommended: {recKind} stop</b>
          {row.rec_source ? <span style={{ color: MUTED }}> · by <b style={{ color: row.rec_model && /grok|gpt|claude/i.test(row.rec_model) ? PURPLE : BLUE }}>{row.rec_source}</b>{row.rec_model ? ` (${row.rec_model})` : ''}</span> : null}
          {row.rec_rationale ? <div style={{ fontSize: 11, color: MUTED, marginTop: 3 }}>{row.rec_rationale}</div> : null}
        </div>

        {/* Inline gated 2FA / manual panel — the SAME verified holding panel; nothing submits without per-order 2FA */}
        {perr ? (
          <div style={{ fontSize: 12, color: RED, padding: 10 }}>⛔ {perr}. <button onClick={() => { onFocusHolding?.(row.symbol, row.account); onClose() }} style={{ color: BLUE, background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}>Open full holding card ↗</button></div>
        ) : !pack ? (
          <div style={{ fontSize: 12, color: MUTED, padding: 14 }}>Loading stop controls…</div>
        ) : (
          <HoldingProtectionActions h={pack.h} pr={pack.pr} monitored={pack.mon} confirmedStop={pack.conf}
            brokerStopsFetchedAt={pack.fetchedAt} onRefresh={() => setReloadKey(k => k + 1)} />
        )}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
          <button onClick={() => { onFocusHolding?.(row.symbol, row.account); onClose() }} style={{ fontSize: 12, fontWeight: 700, padding: '6px 12px', borderRadius: 7, border: `1px solid ${BLUE}55`, background: 'transparent', color: BLUE, cursor: 'pointer' }}>Open full holding card ↗</button>
          <button onClick={onClose} style={{ fontSize: 13, fontWeight: 700, padding: '7px 14px', borderRadius: 7, border: '1px solid rgba(148,163,184,.3)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>Close</button>
        </div>
      </div>
    </div>
  )
}

// Audit sub-tab — read-only trail of protective-stop actions (2FA requests + operator confirmations).
function AuditView() {
  const [d, setD] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    fetch('/api/v2/stops/audit').then(x => x.json()).then(j => setD(unwrap(j))).catch(() => setD(null)).finally(() => setLoading(false))
  }, [])
  const events = d?.events ?? []
  const counts = d?.counts ?? {}
  const KIND: Record<string, { label: string; color: string }> = {
    '2fa_stop_request': { label: '2FA stop request', color: BLUE },
    'confirmation': { label: 'confirmation / manual', color: GREEN },
  }
  const STATUS_COLOR: Record<string, string> = { confirmed: GREEN, approved: GREEN, consumed: GREEN, pending: AMBER, superseded: MUTED, expired: MUTED, rejected: RED }
  return (
    <>
      <div style={{ display: 'flex', gap: 9, flexWrap: 'wrap', marginBottom: 12 }}>
        <Card label="Audit events" value={String(d?.total ?? 0)} />
        <Card label="2FA stop requests" value={String(counts['2fa_stop_request'] ?? 0)} color={BLUE} />
        <Card label="Confirmations / manual" value={String(counts['confirmation'] ?? 0)} color={GREEN} />
      </div>
      <div style={{ overflowX: 'auto', border: '1px solid rgba(148,163,184,.18)', borderRadius: 9 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr style={{ color: MUTED, textAlign: 'left', background: 'rgba(15,23,42,.5)' }}>
              {['When', 'Action', 'Symbol · Account', 'Order', 'Status', 'Channel', 'Detail'].map(h =>
                <th key={h} style={{ padding: '8px 9px', fontWeight: 800, whiteSpace: 'nowrap' }}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {events.map((e: any, i: number) => {
              const k = KIND[e.kind] || { label: e.kind, color: MUTED }
              return (
                <tr key={i} style={{ borderTop: '1px solid rgba(148,163,184,.12)', color: TEXT0 }}>
                  <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', color: MUTED }}>{fmtTime(e.at)}</td>
                  <td style={{ padding: '7px 9px', whiteSpace: 'nowrap' }}><span style={{ color: k.color, fontWeight: 700 }}>{k.label}</span></td>
                  <td style={{ padding: '7px 9px', whiteSpace: 'nowrap' }}><b>{e.symbol || '—'}</b> <span style={{ fontSize: 10.5, color: MUTED }}>{e.account || ''}</span></td>
                  <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', fontFamily: 'monospace', fontSize: 11 }}>{e.order_type || '—'}{e.stop_price != null ? ` @ ${fmtStop(e.stop_price)}` : ''}{e.trail_pct != null ? ` ${e.trail_pct}%` : ''}</td>
                  <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', fontWeight: 700, color: STATUS_COLOR[String(e.status)] || TEXT0 }}>{e.status || '—'}</td>
                  <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', color: MUTED }}>{e.channel || '—'}</td>
                  <td style={{ padding: '7px 9px', fontSize: 10.5, color: MUTED, maxWidth: 260 }}>{e.reason || e.attestation || (e.evidence_hash ? `evidence ${e.evidence_hash}` : '') || (e.reminder_count ? `${e.reminder_count} reminders` : '')}</td>
                </tr>
              )
            })}
            {!loading && events.length === 0 && (
              <tr><td colSpan={7} style={{ padding: 20, textAlign: 'center', color: MUTED }}>No stop-action audit events yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  )
}
