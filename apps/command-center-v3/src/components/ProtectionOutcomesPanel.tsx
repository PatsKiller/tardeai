import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import type { DrillContext } from './DetailDrawer'

// Phase 206 — Canonical all-trades profit-capture in the v3 Journal hub.
// Read-only / advisory only. Give-back is scored ONLY on trades with bar-based MFE; others are
// honest DATA_INCOMPLETE unknowns (never fabricated). Shadow rule-backtests are evidence only and
// do NOT modify GO/WAIT, strategy, stops, or orders. Source: /api/v2/atm/profit-capture.

interface Props { onDrill: (ctx: DrillContext) => void }

const FAILURE_COLOR: Record<string, string> = {
  NO_ADVISORY_GENERATED: '#ef4444',
  ADVISORY_IGNORED: '#f97316',
  ADVISORY_TOO_LATE: '#f59e0b',
  STOP_NOT_MOVED: '#f59e0b',
  NO_TAKE_PROFIT: '#f59e0b',
  DATA_INCOMPLETE: 'var(--text3)',
  NOT_PROTECTABLE: 'var(--text3)',
  UNKNOWN: 'var(--text3)',
}

const card = (label: string, value: string, color = 'var(--text0)', sub?: string) => (
  <div style={{ flex: 1, minWidth: 96, padding: '8px 10px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8 }}>
    <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.3px' }}>{label}</div>
    <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
    {sub && <div style={{ fontSize: 8, color: 'var(--text3)' }}>{sub}</div>}
  </div>
)

const Breakdown = ({ title, data, money }: { title: string, data: Record<string, number>, money?: boolean }) => {
  const entries = Object.entries(data || {}).sort((a, b) => b[1] - a[1])
  if (!entries.length) return null
  return (
    <div style={{ minWidth: 170, flex: 1 }}>
      <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 4 }}>{title}</div>
      {entries.map(([k, v]) => (
        <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text2)', padding: '1px 0', fontFamily: 'monospace' }}>
          <span style={{ color: FAILURE_COLOR[k] || 'var(--text2)' }}>{k}</span>
          <span>{money ? fmt$(v, 0) : v}</span>
        </div>
      ))}
    </div>
  )
}

export default function ProtectionOutcomesPanel({ onDrill }: Props) {
  const { data } = useApi<any>('/api/v2/atm/profit-capture', 60_000)
  if (!data) return <div style={{ color: 'var(--text3)', fontSize: 11 }}>Loading profit-capture…</div>

  const s = data.summary ?? {}
  const b = data.breakdowns ?? {}
  const labels = data.labels ?? {}
  const trades: any[] = data.trades ?? []
  // protectable misses + measurable give-backs first, then the rest
  const ranked = [...trades].sort((a, b2) => {
    const am = a.protection_missed ? 1 : 0, bm = b2.protection_missed ? 1 : 0
    if (am !== bm) return bm - am
    return (b2.money_left_usd ?? 0) - (a.money_left_usd ?? 0)
  })

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 2 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Profit-Capture & Protection (all trades)</div>
        <div style={{ display: 'flex', gap: 6 }}>
          {[labels.mode, labels.execution].filter(Boolean).map((l: string) => (
            <span key={l} style={{ fontSize: 8, color: '#60a5fa', border: '1px solid rgba(96,165,250,.3)', borderRadius: 4, padding: '1px 5px' }}>{l}</span>
          ))}
        </div>
      </div>
      <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>
        Did winners give back profit, and was protection available? Canonical {s.total_closed} closed trades · {s.measurable_closed} bar-measurable. {labels.shadow}
      </div>

      {/* Summary cards */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
        {card('Winners measured', `${s.winners_measured ?? 0}`)}
        {card('Gave back', `${s.winners_with_giveback ?? 0}`, '#ef4444')}
        {card('Money left', fmt$(s.money_left_on_table_usd ?? 0, 0), '#f59e0b')}
        {card('Protection missed', `${s.protection_missed ?? 0}`, (s.protection_missed ?? 0) > 0 ? '#ef4444' : '#22c55e')}
        {card('Advisory existed', `${s.advisory_existed ?? 0}`, '#60a5fa')}
        {card('Operator acted', `${s.operator_acted ?? 0}`, (s.operator_acted ?? 0) > 0 ? '#22c55e' : '#f59e0b')}
        {card('No advisory', `${s.no_advisory_generated ?? 0}`, '#ef4444')}
        {card('Best rule net', fmt$(s.rule_backtest_net_usd ?? 0, 0), (s.rule_backtest_net_usd ?? 0) >= 0 ? '#22c55e' : '#ef4444',
          s.rule_backtest_best_rule ? `${s.rule_backtest_best_rule} · reliable n=${s.rule_backtest_reliable_n ?? 0}` : 'shadow only')}
      </div>

      {/* Evidence-quality qualifier — path-measured premature-exit cost (Phase 206c) */}
      <div style={{ marginBottom: 14, padding: '8px 12px', background: 'rgba(167,139,250,.06)', border: '1px solid rgba(167,139,250,.2)', borderRadius: 8, fontSize: 10, color: 'var(--text2)' }}>
        <span style={{ fontWeight: 700, color: '#a78bfa' }}>Best rule (by net): {s.rule_backtest_best_rule ?? '—'}</span>
        {'  ·  '}avoided <b style={{ color: '#22c55e' }}>{fmt$(s.rule_backtest_potential_recovery_usd ?? 0, 0)}</b>
        {' − premature '}<b style={{ color: '#ef4444' }}>{fmt$(s.rule_backtest_premature_cost_usd ?? 0, 0)}</b>
        {' = net '}<b style={{ color: (s.rule_backtest_net_usd ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(s.rule_backtest_net_usd ?? 0, 0)}</b>
        {'  ·  '}reliable n: <b>{s.rule_backtest_reliable_n ?? 0}</b> (raw {s.rule_backtest_raw_n ?? 0})
        {'  ·  '}estimate: <b>{(s.rule_backtest_estimate_quality ?? 'upper_bound_single_peak').replace(/_/g, ' ')}</b>
        {'  ·  '}graft: <b style={{ color: '#f59e0b' }}>{(s.rule_backtest_graft_verdict ?? 'DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE').replace(/_/g, ' ')}</b>
        {s.rule_backtest_premature_cost_known === true ? (
          <div style={{ marginTop: 4, color: 'var(--text3)', fontSize: 9 }}>
            ✓ Premature-exit cost is path-measured from real intrabar bars. On this sample the best rule's net is {(s.rule_backtest_net_usd ?? 0) >= 0 ? 'positive but below the evidence floor' : 'negative — premature exits exceed avoided give-back'}; not decision-grade; not grafted.
          </div>
        ) : (
          <div style={{ marginTop: 4, color: '#f59e0b', fontSize: 9 }}>
            ⚠ No real intrabar path for the best rule — recovery is a single-peak upper bound; premature-exit cost unknown. Not decision-grade; not grafted.
          </div>
        )}
      </div>

      {/* Breakdowns */}
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginBottom: 14, padding: '10px 12px', background: 'var(--bg2)', borderRadius: 8 }}>
        <Breakdown title="By source" data={b.by_source_system} />
        <Breakdown title="By failure class" data={b.by_failure_class} />
        <Breakdown title="By strategy" data={b.by_strategy} />
        <Breakdown title="By operator decision" data={b.by_operator_decision} />
        <Breakdown title="$ left by source" data={b.money_left_by_source_system} money />
        <Breakdown title="$ left by strategy" data={b.money_left_by_strategy} money />
      </div>

      {/* Per-trade table */}
      <div style={{ display: 'grid', gridTemplateColumns: '0.8fr 1fr 1fr 0.8fr 0.8fr 0.7fr 0.9fr 1.4fr 0.9fr', padding: '4px 6px', fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>
        <span>Symbol</span><span>Source/Acct</span><span>Strategy</span><span>Realized</span><span>Max$</span><span>Cap%</span><span>Left</span><span>Failure / advisory</span><span>Quality</span>
      </div>
      <div style={{ maxHeight: 420, overflowY: 'auto' }}>
        {ranked.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11, padding: 8 }}>No closed trades analyzed yet</div> :
        ranked.map(t => (
          <div key={t.trade_instance_id} onClick={() => onDrill({ title: `${t.symbol} · TI#${t.trade_instance_id}`, subtitle: `${t.failure_class} · ${t.source_system}`, endpoint: '/api/v2/atm/profit-capture', rows: [t] })}
            style={{ display: 'grid', gridTemplateColumns: '0.8fr 1fr 1fr 0.8fr 0.8fr 0.7fr 0.9fr 1.4fr 0.9fr', padding: '7px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, alignItems: 'center' }}>
            <span style={{ fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>{t.symbol}</span>
            <span style={{ color: 'var(--text3)', fontSize: 9 }}>{t.source_system?.replace('_import', '').replace('_paper', '')}{t.execution_account ? `/${t.execution_account}` : ''}</span>
            <span style={{ color: 'var(--text2)', fontSize: 9 }}>{t.strategy_id ?? '—'}</span>
            <span style={{ color: (t.realized_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(t.realized_pnl, 0)}</span>
            <span style={{ color: 'var(--text2)' }}>{t.max_profit_usd != null ? fmt$(t.max_profit_usd, 0) : '—'}</span>
            <span style={{ color: 'var(--text2)' }}>{t.capture_ratio != null ? `${Math.round(t.capture_ratio * 100)}%` : '—'}</span>
            <span style={{ color: (t.money_left_usd ?? 0) > 0 ? '#f59e0b' : 'var(--text3)' }}>{t.money_left_usd != null ? fmt$(t.money_left_usd, 0) : '—'}</span>
            <span style={{ color: FAILURE_COLOR[t.failure_class] || 'var(--text2)', fontSize: 9 }}>
              {t.failure_class}{t.advisory_existed ? ` · ${t.advisory_action ?? 'advisory'}` : ''}{t.operator_acted ? ' · acted' : ''}
            </span>
            <span style={{ color: t.data_quality === 'bar_mfe' ? '#22c55e' : t.data_quality === 'no_bars' ? '#ef4444' : 'var(--text3)', fontSize: 9 }}>{t.data_quality}</span>
          </div>
        ))}
      </div>

      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>
        Source: /api/v2/atm/profit-capture · canonical trade_instance_id · give-back scored only on bar-based MFE.
        Shadow rule-backtests are evidence only — no broker/order/stop/GO-WAIT/strategy changes.
      </div>
    </div>
  )
}
