import { useApi } from '../hooks/useApi'

const MUTED = '#94a3b8', TEXT0 = '#f8fafc', TEXT1 = '#dbeafe', GREEN = '#22c55e', AMBER = '#f59e0b', BLUE = '#60a5fa', PURPLE = '#a78bfa'
const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 14 } as const

function isOptionRow(e: any): boolean {
  return e.execution_type === 'option'
    || e.origin_type === 'options_proposal'
    || !!e.options_proposal_id
    || (e.origin_id && String(e.origin_id).startsWith('opt_'))
}

export default function ManualExecutionLog({
  mode,
  borderColor = '#22c55e',
  onRefresh,
}: {
  mode: 'equity' | 'option'
  borderColor?: string
  onRefresh?: () => void
}) {
  const q = mode === 'option' ? '?limit=25&execution_type=option' : '?limit=25&execution_type=equity'
  const { data: logData, refetch } = useApi<any>(`/api/v2/executions/manual-log${q}`, 60_000)
  const executions: any[] = (logData?.executions ?? []).filter((e: any) =>
    mode === 'option' ? isOptionRow(e) : !isOptionRow(e))
  const metrics = logData?.metrics ?? {}
  const count = mode === 'option'
    ? (metrics.options_executions_logged ?? executions.length)
    : Math.max(0, (metrics.manual_executions ?? 0) - (metrics.options_executions_logged ?? 0))

  const fmtTs = (ts?: string) => ts ? new Date(ts).toLocaleString() : '—'
  const refresh = () => { refetch?.(); onRefresh?.() }

  const title = mode === 'option' ? 'Options Manual Execution Log' : 'Equity Manual Execution Log'
  const emptyHint = mode === 'option'
    ? <>No options executions logged yet. On the <b style={{ color: BLUE }}>Options</b> desk, use <b style={{ color: BLUE }}>Executed manually</b> after filling a covered call, CSP, or put at your broker.</>
    : <>No equity executions logged yet. Use <b style={{ color: BLUE }}>Executed manually</b> on a broker proposal after buying/selling stock at Schwab or Fidelity.</>

  return (
    <div style={{ ...card, borderLeft: `4px solid ${borderColor}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: TEXT0 }}>{title}</div>
        <span style={{ fontSize: 10, color: MUTED }}>{count || executions.length} logged</span>
        <span style={{ flex: 1 }} />
        <button onClick={refresh} style={{ fontSize: 10, fontWeight: 700, padding: '4px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>Refresh</button>
      </div>
      {executions.length === 0 ? (
        <div style={{ fontSize: 11, color: MUTED, lineHeight: 1.5 }}>{emptyHint}</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {executions.map(e => {
            const opt = isOptionRow(e)
            const strat = e.origin_id && String(e.origin_id).includes('covered_call') ? 'CC'
              : e.origin_id && String(e.origin_id).includes('cash_secured') ? 'CSP'
              : e.origin_id && String(e.origin_id).includes('protective') ? 'protective put'
              : opt ? 'option' : 'equity'
            return (
              <div key={e.id} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', padding: '7px 9px', borderRadius: 8, background: 'rgba(15,23,42,.45)', border: '1px solid rgba(148,163,184,.15)' }}>
                <span style={{ fontSize: 12, fontWeight: 900, color: TEXT0, fontFamily: 'monospace' }}>{e.symbol}</span>
                <span style={{ fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4, background: opt ? 'rgba(168,85,247,.15)' : 'rgba(96,165,250,.12)', color: opt ? PURPLE : BLUE }}>{strat}</span>
                <span style={{ fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4, background: e.broker === 'fidelity' ? 'rgba(167,139,250,.18)' : 'rgba(245,158,11,.18)', color: e.broker === 'fidelity' ? PURPLE : AMBER }}>{e.broker || e.account}</span>
                {opt ? (
                  <span style={{ fontSize: 9, color: MUTED }}>
                    {e.contracts ? `${e.contracts} ct` : '— ct'}
                    {e.strike != null ? ` · $${e.strike}` : ''}
                    {e.expiration ? ` · ${String(e.expiration).slice(0, 10)}` : ''}
                    {e.entry_price != null ? ` · prem $${Number(e.entry_price).toFixed(2)}` : ''}
                  </span>
                ) : (
                  <span style={{ fontSize: 9, color: MUTED }}>{e.shares ? `${e.shares} sh` : '—'}{e.entry_price != null ? ` @ $${Number(e.entry_price).toFixed(2)}` : ''}</span>
                )}
                {e.origin_type && e.origin_type !== 'manual' && (
                  <span style={{ fontSize: 8, fontWeight: 800, padding: '2px 6px', borderRadius: 4, background: 'rgba(34,197,94,.15)', color: GREEN }}>✓ {e.origin_type}</span>
                )}
                {(e.proposal_id || e.origin_proposal_id) && (
                  <a href={`/v3/trading?tab=Proposals&symbol=${encodeURIComponent(e.symbol || '')}`}
                    style={{ fontSize: 9, fontWeight: 800, color: BLUE, textDecoration: 'none' }}>
                    → proposal #{e.proposal_id || e.origin_proposal_id}
                  </a>
                )}
                <span style={{ fontSize: 9, color: MUTED }}>{e.outcome || 'pending'}</span>
                <span style={{ fontSize: 9, color: MUTED, marginLeft: 'auto' }}>{fmtTs(e.executed_at)}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}