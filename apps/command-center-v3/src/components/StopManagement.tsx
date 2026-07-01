import { useEffect, useMemo, useState } from 'react'

// Portfolio → Stop Management. Aggregates broker-actual + advisor-planned stops with Yellow/Amber/Red alerts.
// Read-only view; live adjustments route through the existing protective-stop 2FA path (Adjust → Full controls).
// See docs/MOMENTUM_SCALP_STOP_MONITORING_PROTOCOL.md.

const MUTED = '#94a3b8', TEXT0 = '#f8fafc', GREEN = '#22c55e', AMBER = '#f59e0b', RED = '#ef4444', BLUE = '#60a5fa'
const unwrap = (j: any) => (j && typeof j === 'object' && 'data' in j && j.data && typeof j.data === 'object') ? j.data : j
const LEVEL_COLOR: Record<string, string> = { red: RED, amber: AMBER, yellow: '#eab308' }
const fmt$ = (n: any) => n == null ? '—' : `$${Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
const fmtStop = (n: any) => n == null ? '—' : `$${Number(n).toFixed(2)}`

type Row = {
  symbol: string; account: string; broker: string; route: string; stop_type: string
  current_price: number; qty: number; broker_stop: number | null; planned_stop: number | null; stop: number
  divergence: string | null; distance_pct: number | null; distance_atr: number | null; distance_r: number | null
  dollars_at_risk: number; unrealized_dollars: number | null; unrealized_r: number | null
  is_trailing: boolean; trailing_should_be_active: boolean; heat_contribution_pct: number | null
  alert_level: 'red' | 'amber' | 'yellow' | null; alert_reasons: string[]
}

function Pill({ level }: { level: string | null }) {
  if (!level) return <span style={{ fontSize: 11, color: GREEN }}>● ok</span>
  const c = LEVEL_COLOR[level] || MUTED
  return <span style={{ fontSize: 11, fontWeight: 800, color: c, background: `${c}1e`, border: `1px solid ${c}`, borderRadius: 999, padding: '2px 8px', textTransform: 'uppercase' }}>{level}</span>
}

function Card({ label, value, color = TEXT0 }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ flex: '1 1 160px', padding: '11px 13px', borderRadius: 9, background: 'var(--bg2, rgba(15,23,42,.6))', border: '1px solid rgba(148,163,184,.2)' }}>
      <div style={{ fontSize: 11, color: MUTED, fontWeight: 700, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 21, fontWeight: 900, color }}>{value}</div>
    </div>
  )
}

const QUICK = ['All', 'Needs Attention', 'Trailing Not Active', 'High Heat'] as const

export default function StopManagement() {
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
    if (quick === 'Trailing Not Active' && !r.trailing_should_be_active) return false
    if (quick === 'High Heat' && !((r.heat_contribution_pct ?? 0) >= 1.5)) return false
    return true
  })

  return (
    <div style={{ padding: '4px 2px' }}>
      {/* Summary cards */}
      <div style={{ display: 'flex', gap: 9, flexWrap: 'wrap', marginBottom: 12 }}>
        <Card label="Total Open Risk" value={fmt$(summary.total_open_risk)} />
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
        <span style={{ width: 12 }} />
        <select value={acct} onChange={e => setAcct(e.target.value)} style={{ fontSize: 12, padding: '4px 6px', borderRadius: 6, background: 'var(--bg2)', color: TEXT0, border: '1px solid rgba(148,163,184,.3)' }}>
          {accounts.map(a => <option key={a} value={a}>{a === 'All' ? 'All accounts' : a}</option>)}
        </select>
        <select value={level} onChange={e => setLevel(e.target.value)} style={{ fontSize: 12, padding: '4px 6px', borderRadius: 6, background: 'var(--bg2)', color: TEXT0, border: '1px solid rgba(148,163,184,.3)' }}>
          {['All', 'red', 'amber', 'yellow'].map(l => <option key={l} value={l}>{l === 'All' ? 'All levels' : l}</option>)}
        </select>
        <button onClick={load} style={{ fontSize: 12, fontWeight: 700, padding: '4px 10px', borderRadius: 6, cursor: 'pointer', border: `1px solid ${BLUE}`, background: `${BLUE}18`, color: BLUE }}>↻ Refresh</button>
        <span style={{ fontSize: 11, color: MUTED }}>{loading ? 'loading…' : `${filtered.length} of ${rows.length} positions · regime ${data?.regime_now ?? '—'}`}</span>
      </div>

      {/* Table */}
      <div style={{ overflowX: 'auto', border: '1px solid rgba(148,163,184,.18)', borderRadius: 9 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr style={{ color: MUTED, textAlign: 'left', background: 'rgba(15,23,42,.5)' }}>
              {['Alert', 'Symbol · Account', 'Route', 'Stop type', 'Stop (broker / planned)', 'Distance', 'Unreal.', '$ at risk', 'Reasons', ''].map(h =>
                <th key={h} style={{ padding: '8px 9px', fontWeight: 800, whiteSpace: 'nowrap' }}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {filtered.map((r, i) => (
              <tr key={`${r.symbol}-${r.account}-${i}`} style={{ borderTop: '1px solid rgba(148,163,184,.12)', color: TEXT0 }}>
                <td style={{ padding: '7px 9px' }}><Pill level={r.alert_level} /></td>
                <td style={{ padding: '7px 9px', whiteSpace: 'nowrap' }}><b>{r.symbol}</b><br /><span style={{ fontSize: 10.5, color: MUTED }}>{r.account}</span></td>
                <td style={{ padding: '7px 9px', color: MUTED, fontSize: 11 }}>{r.route}</td>
                <td style={{ padding: '7px 9px' }}>{r.is_trailing ? '↗ TRAILING' : r.stop_type}{r.trailing_should_be_active ? <span style={{ color: AMBER }}> ⚠</span> : null}</td>
                <td style={{ padding: '7px 9px', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                  <span style={{ color: r.broker_stop != null ? GREEN : MUTED }}>{fmtStop(r.broker_stop)}</span> / <span style={{ color: AMBER }}>{fmtStop(r.planned_stop)}</span>
                  {r.divergence ? <div style={{ fontSize: 10, color: RED }}>{r.divergence}</div> : null}
                </td>
                <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', fontSize: 11 }}>
                  {r.distance_pct != null ? `${r.distance_pct}%` : '—'}{r.distance_atr != null ? ` · ${r.distance_atr}ATR` : ''}{r.distance_r != null ? ` · ${r.distance_r}R` : ''}
                </td>
                <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', color: (r.unrealized_dollars ?? 0) >= 0 ? GREEN : RED }}>{r.unrealized_dollars != null ? fmt$(r.unrealized_dollars) : '—'}</td>
                <td style={{ padding: '7px 9px', whiteSpace: 'nowrap', fontWeight: 700 }}>{fmt$(r.dollars_at_risk)}</td>
                <td style={{ padding: '7px 9px', fontSize: 10.5, color: MUTED, maxWidth: 220 }}>{(r.alert_reasons || []).join(' · ')}</td>
                <td style={{ padding: '7px 9px' }}>
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

      {adjust && <AdjustModal row={adjust} onClose={() => setAdjust(null)} />}
    </div>
  )
}

// Adjust modal — shows the suggested stop + reasoning; live changes route through the holding's protective
// controls (evidence-bound + per-order 2FA + read-back). No stop is submitted from here.
function AdjustModal({ row, onClose }: { row: Row; onClose: () => void }) {
  const entryLike = row.planned_stop ?? row.stop
  const breakeven = row.current_price // suggestion placeholders; real values computed by the advisor on Full controls
  const suggestions = [
    { label: 'Apply advised stop', value: row.planned_stop, why: 'Advisor family-band + swing-low anchor' },
    { label: 'Move to breakeven', value: null, why: 'Stop → entry once ≥ +1R (advisor computes exact entry)' },
    { label: 'Tighten by 0.5× ATR', value: row.distance_atr != null && row.current_price ? Number((row.stop + (row.current_price - row.stop) * 0.5).toFixed(2)) : null, why: 'Reduce give-back in contracted volatility' },
  ]
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
      <div onClick={e => e.stopPropagation()} style={{ width: 460, maxWidth: '92vw', background: 'var(--bg1, #0f172a)', border: '1px solid rgba(148,163,184,.3)', borderRadius: 12, padding: 18 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <div style={{ fontSize: 16, fontWeight: 900, color: TEXT0 }}>Adjust stop — {row.symbol}</div>
          <button onClick={onClose} style={{ fontSize: 18, color: MUTED, background: 'none', border: 'none', cursor: 'pointer' }}>×</button>
        </div>
        <div style={{ fontSize: 12.5, color: TEXT0, lineHeight: 1.6, marginBottom: 12 }}>
          <b>{row.account}</b> · {row.route}<br />
          Current price <b>{fmtStop(row.current_price)}</b> · Broker stop <b style={{ color: row.broker_stop != null ? GREEN : MUTED }}>{fmtStop(row.broker_stop)}</b> · Advised <b style={{ color: AMBER }}>{fmtStop(row.planned_stop)}</b><br />
          Distance {row.distance_pct}% {row.distance_atr != null ? `· ${row.distance_atr}ATR` : ''} · $ at risk <b>{fmt$(row.dollars_at_risk)}</b>
        </div>
        <div style={{ display: 'grid', gap: 7, marginBottom: 12 }}>
          {suggestions.map(s => (
            <div key={s.label} style={{ padding: '8px 10px', borderRadius: 7, background: 'rgba(15,23,42,.5)', border: '1px solid rgba(148,163,184,.2)' }}>
              <div style={{ fontSize: 13, fontWeight: 800, color: TEXT0 }}>{s.label}{s.value != null ? <span style={{ color: BLUE }}> → {fmtStop(s.value)}</span> : null}</div>
              <div style={{ fontSize: 11, color: MUTED }}>{s.why}</div>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 11.5, color: AMBER, marginBottom: 10 }}>
          ⚠ Live changes require the evidence-bound + per-order 2FA flow. Open the position's Full controls to apply with confirmation and broker read-back.
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <a href={`/v3/trading?tab=Open%20Trades&symbol=${row.symbol}`} style={{ fontSize: 13, fontWeight: 800, padding: '7px 14px', borderRadius: 7, border: `1px solid ${BLUE}`, background: `${BLUE}18`, color: BLUE, textDecoration: 'none' }}>Open Full controls →</a>
          <button onClick={onClose} style={{ fontSize: 13, fontWeight: 700, padding: '7px 14px', borderRadius: 7, border: '1px solid rgba(148,163,184,.3)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>Close</button>
        </div>
      </div>
    </div>
  )
}
