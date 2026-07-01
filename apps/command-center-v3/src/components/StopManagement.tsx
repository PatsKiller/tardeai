import { useEffect, useMemo, useState } from 'react'

// Portfolio → Stop Management. Aggregates broker-actual + advisor-planned stops with Yellow/Amber/Red alerts,
// plus an Audit sub-tab (2FA stop requests + operator confirmations). Read-only view; live adjustments route
// through the holding's existing gated 2FA panel (Schwab) or manual ticket (Fidelity) via onFocusHolding.
// See docs/MOMENTUM_SCALP_STOP_MONITORING_PROTOCOL.md.

const MUTED = '#94a3b8', TEXT0 = '#f8fafc', GREEN = '#22c55e', AMBER = '#f59e0b', RED = '#ef4444', BLUE = '#60a5fa'
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
  const jump = () => { onFocusHolding?.(row.symbol, row.account); onClose() }
  const lockIn = row.trailing_should_be_active   // advisor methodology: P&L ≥ family threshold AND price > 50d SMA
  const trailing = { label: 'Trailing stop', why: lockIn ? 'Advisor-recommended — ratchets up with price to lock in profit, never lowers' : 'Ratchets up with price (optional)', route: '2FA', recommended: lockIn }
  const schwabTypes = lockIn
    ? [trailing,
       { label: 'Fixed stop', why: 'Non-moving trigger; advisor default for core holds', route: '2FA' },
       { label: 'Stop-limit', why: 'Stop with a limit floor to cap slippage', route: '2FA' }]
    : [{ label: 'Fixed stop', why: 'Non-moving trigger; advisor default for core holds', route: '2FA' },
       trailing,
       { label: 'Stop-limit', why: 'Stop with a limit floor to cap slippage', route: '2FA' }]
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
      <div onClick={e => e.stopPropagation()} style={{ width: 480, maxWidth: '92vw', background: 'var(--bg1, #0f172a)', border: '1px solid rgba(148,163,184,.3)', borderRadius: 12, padding: 18 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <div style={{ fontSize: 16, fontWeight: 900, color: TEXT0 }}>Adjust stop — {row.symbol}</div>
          <button onClick={onClose} style={{ fontSize: 18, color: MUTED, background: 'none', border: 'none', cursor: 'pointer' }}>×</button>
        </div>
        <div style={{ fontSize: 12.5, color: TEXT0, lineHeight: 1.6, marginBottom: 12 }}>
          <b>{row.account}</b> · {row.route} · <span style={{ color: isFidelity ? AMBER : BLUE }}>{isFidelity ? 'Fidelity (manual)' : 'Schwab (2FA)'}</span><br />
          Price <b>{fmtStop(row.current_price)}</b> · Active stop <b style={{ color: row.broker_stop != null ? GREEN : AMBER }}>{row.broker_stop != null ? `${fmtStop(row.broker_stop)} (${SRC_LABEL[row.stop_source] || row.stop_source})` : 'none'}</b> · Advised <b style={{ color: AMBER }}>{fmtStop(row.planned_stop)}</b><br />
          Distance {row.distance_pct}%{row.distance_atr != null ? ` · ${row.distance_atr}ATR` : ''} · $ at risk <b>{fmt$(row.dollars_at_risk)}</b>
        </div>

        <div style={{ fontSize: 11, color: MUTED, fontWeight: 700, marginBottom: 6 }}>SELECT STOP TYPE TO REQUEST</div>
        <div style={{ display: 'grid', gap: 7, marginBottom: 12 }}>
          {(isFidelity
            ? [{ label: 'Manual ticket', why: 'Fidelity has no trading API — arm a software-monitored stop + place the order at Fidelity Active Trader', route: 'MANUAL' }]
            : schwabTypes
          ).map((s: any) => (
            <button key={s.label} onClick={jump} style={{ textAlign: 'left', padding: '9px 11px', borderRadius: 8, cursor: 'pointer',
              background: s.recommended ? `${GREEN}14` : 'rgba(15,23,42,.5)', border: `1px solid ${s.recommended ? GREEN : (isFidelity ? AMBER : BLUE) + '55'}` }}>
              <div style={{ fontSize: 13, fontWeight: 800, color: TEXT0 }}>{s.label}
                <span style={{ fontSize: 10, fontWeight: 800, color: isFidelity ? AMBER : BLUE, marginLeft: 8, border: `1px solid ${isFidelity ? AMBER : BLUE}`, borderRadius: 5, padding: '1px 6px' }}>{s.route === 'MANUAL' ? 'MANUAL TICKET' : 'PER-ORDER 2FA'}</span>
                {s.recommended && <span style={{ fontSize: 10, fontWeight: 800, color: GREEN, marginLeft: 6, border: `1px solid ${GREEN}`, borderRadius: 5, padding: '1px 6px' }}>🔒 RECOMMENDED</span>}
              </div>
              <div style={{ fontSize: 11, color: MUTED }}>{s.why}</div>
            </button>
          ))}
        </div>

        <div style={{ fontSize: 11.5, color: isFidelity ? AMBER : BLUE, marginBottom: 10 }}>
          {isFidelity
            ? 'ⓘ Fidelity stops are always manual/monitored. Selecting opens the holding card to create the ticket + arm the software monitor.'
            : 'ⓘ Selecting opens the holding card, where the request goes through quote-freshness, whole-share, preflight, and per-order 2FA gating with broker read-back. Nothing submits automatically.'}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={jump} style={{ fontSize: 13, fontWeight: 800, padding: '7px 14px', borderRadius: 7, border: `1px solid ${BLUE}`, background: `${BLUE}18`, color: BLUE, cursor: 'pointer' }}>Open holding controls →</button>
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
