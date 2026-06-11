import { useApi } from '../hooks/useApi'

// Daily Execution Coaching Queue — advisory only. Source: /api/v2/journal/daily-execution-coaching/latest
// (build_daily_execution_coaching + grok_daily_execution_digest). NO live-strategy changes; hypotheses are
// shadow-research candidates requiring operator approval.
const SEV: Record<string, string> = { critical: '#ef4444', high: '#f59e0b', medium: '#60a5fa', low: 'var(--text3)' }

export default function ExecutionCoachPanel({ onReplay }: { onReplay?: (sym: string) => void }) {
  const { data } = useApi<any>('/api/v2/journal/daily-execution-coaching/latest', 120_000)
  const d = data?.data ?? data
  const run = d?.run, items: any[] = d?.items ?? [], dg = d?.digest?.digest_json
  if (!run) return null
  const top = (t: string) => items.find(i => i.item_type === t)
  const missed = top('missed_runner'), repeated = top('repeated_mistake')
  const hyps = items.filter(i => i.item_type === 'hypothesis_candidate')

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>🎯 Execution Coach — what to fix next</div>
        <span style={{ fontSize: 8, color: '#a855f7', border: '1px solid rgba(168,85,247,.5)', borderRadius: 3, padding: '1px 4px' }}>advisory · no live changes</span>
      </div>
      <div style={{ fontSize: 9, color: 'var(--text3)', margin: '3px 0 10px' }}>
        {run.window_start ? `${run.trade_count} trades · ${run.poor_count} poor / ${run.weak_count} weak / ${run.good_count} ok+good` : ''} · advisory coaching from replay evidence; hypotheses require shadow test + operator approval.
      </div>

      {dg?.daily_headline && (
        <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: '8px 10px', marginBottom: 10 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)' }}>{dg.daily_headline}</div>
          {dg.top_behavior_to_fix && <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 3 }}>Top behavior to fix: {dg.top_behavior_to_fix}</div>}
          {dg.do_not_overfit_warning && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 3, fontStyle: 'italic' }}>⚠ {dg.do_not_overfit_warning}</div>}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 10 }}>
        {repeated && <Card title="Top repeated mistake" sev={repeated.severity} body={repeated.lesson} action={repeated.operator_action} />}
        {missed && <Card title="Worst missed runner" sev={missed.severity} body={missed.lesson} action={missed.operator_action} />}
      </div>

      {(dg?.symbols_to_replay?.length > 0) && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>Replay these:</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {dg.symbols_to_replay.slice(0, 10).map((s: string) => (
              <span key={s} onClick={() => onReplay?.(s)} style={{ fontSize: 10, fontFamily: 'monospace', padding: '2px 7px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)', cursor: onReplay ? 'pointer' : 'default' }}>📈 {s}</span>
            ))}
          </div>
        </div>
      )}

      {dg?.strategies_to_review?.length > 0 && (
        <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 10 }}>Strategy families to review: <span style={{ color: 'var(--text2)' }}>{dg.strategies_to_review.join(', ')}</span></div>
      )}

      {hyps.length > 0 && (
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 8 }}>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>Shadow-research candidates (evidence-only — never auto-applied):</div>
          {hyps.map((h, i) => (
            <div key={i} style={{ fontSize: 9, color: 'var(--text2)', padding: '2px 0' }}>
              <span style={{ color: (h.avg_delta_ps ?? 0) > 0 ? '#22c55e' : '#ef4444' }}>{(h.avg_delta_ps ?? 0) > 0 ? '◦ promising' : '◦ unsupported'}</span> — {h.lesson}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Card({ title, sev, body, action }: { title: string; sev: string; body: string; action: string }) {
  return (
    <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: '7px 9px', borderLeft: `3px solid ${SEV[sev] || 'var(--text3)'}` }}>
      <div style={{ fontSize: 9, color: SEV[sev] || 'var(--text3)', fontWeight: 700, textTransform: 'uppercase' }}>{title} · {sev}</div>
      <div style={{ fontSize: 10, color: 'var(--text1)', margin: '3px 0' }}>{body}</div>
      <div style={{ fontSize: 8, color: 'var(--text3)' }} title={action}>{action.length > 110 ? action.slice(0, 110) + '…' : action}</div>
    </div>
  )
}
