import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import type { DrillContext } from './DetailDrawer'

// Phase 197 — Profit-protection close-loop outcomes in the v3 Journal hub.
// Read-only learning telemetry. Give-back is scored ONLY on trades with bar-based MFE;
// others are honest unknowns (never fabricated). Source: /api/v2/atm/protection-advisory-outcomes.

interface Props { onDrill: (ctx: DrillContext) => void }

const kpi = (label: string, value: string, color = 'var(--text0)') => (
  <div style={{ flex: 1, minWidth: 90 }}>
    <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.3px' }}>{label}</div>
    <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
  </div>
)

export default function ProtectionOutcomesPanel({ onDrill }: Props) {
  const { data } = useApi<any>('/api/v2/atm/protection-advisory-outcomes', 60_000)
  if (!data) return <div style={{ color: 'var(--text3)', fontSize: 11 }}>Loading outcomes…</div>

  const s = data.summary ?? {}
  const outcomes: any[] = data.outcomes ?? []
  // measurable closed trades, biggest give-back first
  const measurable = outcomes
    .filter(o => o.record_kind === 'final_closed' && o.mfe_source === 'bar_analysis')
    .sort((a, b) => (b.profit_left_on_table_usd ?? 0) - (a.profit_left_on_table_usd ?? 0))
  const interim = outcomes.filter(o => o.record_kind === 'interim_open' && o.adjustment_applied)

  const rate = s.baseline_gaveback_rate_pct_of_measurable
  const left = s.baseline_profit_left_on_table_usd ?? 0

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Profit-Protection Outcomes</div>
      <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>
        Did winners give back profit? Measured from bar-based MFE on closed paper trades.
      </div>

      {/* KPI strip */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
        {kpi('Gave back', rate != null ? `${rate}%` : '—', rate >= 50 ? '#ef4444' : '#22c55e')}
        {kpi('Left on table', fmt$(left, 0), '#f59e0b')}
        {kpi('Measurable', `${s.baseline_measurable_with_bar_mfe ?? 0}/${(s.baseline_measurable_with_bar_mfe ?? 0) + (s.baseline_unmeasurable_no_mfe ?? 0)}`)}
        {kpi('Operator acted', `${s.operator_accepted ?? 0}`, '#60a5fa')}
      </div>

      {/* Operator-adjusted (interim) */}
      {interim.length > 0 && (
        <div style={{ marginBottom: 12, padding: '8px 12px', background: 'rgba(34,197,94,.06)', border: '1px solid rgba(34,197,94,.15)', borderRadius: 8 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#22c55e', marginBottom: 4 }}>Operator-adjusted (in flight)</div>
          {interim.map(o => (
            <div key={o.trade_id} onClick={() => onDrill({ title: `${o.symbol} #${o.trade_id}`, subtitle: 'protection outcome', endpoint: '/api/v2/atm/protection-advisory-outcomes', rows: [o] })}
              style={{ fontSize: 10, color: 'var(--text2)', padding: '2px 0', cursor: 'pointer', fontFamily: 'monospace' }}>
              {o.symbol}: {o.adjustment_action} · stop {o.stop_before}→{o.stop_after} · locked {fmt$(o.profit_locked_by_adjustment, 0)} · giveback avoided {fmt$(o.giveback_avoided, 0)}
            </div>
          ))}
        </div>
      )}

      {/* Per-trade give-back table */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', padding: '4px 6px', fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>
        <span>Symbol</span><span>Realized</span><span>Left on table</span><span>Gave back</span>
      </div>
      <div style={{ maxHeight: 360, overflowY: 'auto' }}>
        {measurable.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11, padding: 8 }}>No bar-measurable closed trades yet</div> :
        measurable.map(o => (
          <div key={o.trade_id} onClick={() => onDrill({ title: `${o.symbol} #${o.trade_id}`, subtitle: 'protection outcome', endpoint: '/api/v2/atm/protection-advisory-outcomes', rows: [o] })}
            style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', padding: '7px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
            <span style={{ fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>{o.symbol}</span>
            <span style={{ color: (o.realized_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(o.realized_pnl, 2)}</span>
            <span style={{ color: '#f59e0b' }}>{fmt$(o.profit_left_on_table_usd, 0)}</span>
            <span style={{ color: o.gave_back_profit ? '#ef4444' : 'var(--text3)' }}>{o.gave_back_profit ? 'yes' : 'no'}</span>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>
        Source: /api/v2/atm/protection-advisory-outcomes. Give-back scored only on bar-based MFE;
        {s.baseline_unmeasurable_no_mfe ? ` ${s.baseline_unmeasurable_no_mfe} trade(s) unmeasurable.` : ' full coverage.'} Read-only.
      </div>
    </div>
  )
}
