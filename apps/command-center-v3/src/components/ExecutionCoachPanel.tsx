import { useApi } from '../hooks/useApi'

// Daily Execution Coaching Queue — advisory only, but fully drillable. Source:
// /api/v2/journal/daily-execution-coaching/latest. Every item + hypothesis drills to its evidence
// (trade keys, metrics, full action). NO live-strategy changes; hypotheses are shadow-research only.
const SEV: Record<string, string> = { critical: '#ef4444', high: '#f59e0b', medium: '#60a5fa', low: 'var(--text3)' }
const ITEM_LABEL: Record<string, string> = {
  repeated_mistake: 'Repeated mistake', premature_exit: 'Green-but-poorly-executed', missed_runner: 'Missed runner',
  symbol_review: 'Symbol review', strategy_family_review: 'Strategy review', hypothesis_candidate: 'Hypothesis',
}
// plain-English: what each backtested hypothesis actually tests
const HYP_LABEL: Record<string, string> = {
  volume_confirmed_entry: 'Wait for volume confirmation (RVOL) before entering',
  hold_above_vwap: 'Hold the position while price stays above session VWAP',
  macd_rollover_exit: 'Exit when the MACD histogram rolls over',
}
const hypName = (lesson: string) => { const m = lesson.match(/Hypothesis '([^']+)'/); return m ? m[1] : null }

export default function ExecutionCoachPanel({ onReplay, onDrill }: { onReplay?: (sym: string) => void; onDrill?: (c: any) => void }) {
  const { data } = useApi<any>('/api/v2/journal/daily-execution-coaching/latest', 120_000)
  const d = data?.data ?? data
  const run = d?.run, items: any[] = d?.items ?? [], dg = d?.digest?.digest_json
  const aiCrit = d?.ai_critique_insights
  if (!run) return null
  const coaching = items.filter(i => i.item_type !== 'hypothesis_candidate').slice(0, 6)
  const hyps = items.filter(i => i.item_type === 'hypothesis_candidate')

  const drillItem = (it: any) => onDrill?.({
    title: `${ITEM_LABEL[it.item_type] ?? it.item_type}${it.symbol ? ` — ${it.symbol}` : ''}`,
    subtitle: `${it.severity} · ${it.sample_size} trade${it.sample_size === 1 ? '' : 's'} · advisory (no live change)`,
    endpoint: '/api/v2/journal/daily-execution-coaching/latest',
    rows: [{
      lesson: it.lesson, what_to_do: it.operator_action, severity: it.severity, sample_size: it.sample_size,
      avg_capture_ratio: it.avg_capture_ratio, avg_missed_pct: it.avg_missed_pct, avg_delta_per_share: it.avg_delta_ps,
      affected_trade_keys: it.trade_keys_json,
    }],
  })

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>🎯 Execution Coach — what to fix next</div>
        <span style={{ fontSize: 8, color: '#a855f7', border: '1px solid rgba(168,85,247,.5)', borderRadius: 3, padding: '1px 4px' }}>advisory · click any item to drill</span>
      </div>
      <div style={{ fontSize: 9, color: 'var(--text3)', margin: '3px 0 10px' }}>
        {run.trade_count} trades · {run.poor_count} poor / {run.weak_count} weak / {run.good_count} ok+good · click items for the evidence + affected trades.
      </div>

      {dg?.daily_headline && (
        <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: '8px 10px', marginBottom: 10 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)' }}>{dg.daily_headline}</div>
          {dg.top_behavior_to_fix && <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 3 }}>Top behavior to fix: {dg.top_behavior_to_fix}</div>}
          {dg.do_not_overfit_warning && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 3, fontStyle: 'italic' }}>⚠ {dg.do_not_overfit_warning}</div>}
        </div>
      )}

      {(aiCrit?.coaching_bullets?.length > 0) && (
        <div style={{ background: 'rgba(167,139,250,.06)', border: '1px solid rgba(167,139,250,.3)', borderRadius: 8, padding: '8px 10px', marginBottom: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#c4b5fd', marginBottom: 4 }}>From AI trade critiques ({aiCrit.critique_count ?? 0})</div>
          {(aiCrit.coaching_bullets ?? []).slice(0, 3).map((b: string, i: number) => (
            <div key={i} style={{ fontSize: 9, color: 'var(--text2)', padding: '2px 0' }}>• {b}</div>
          ))}
        </div>
      )}

      {/* ranked coaching items — each clickable to drill */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 10 }}>
        {coaching.map((it, i) => (
          <div key={i} onClick={() => drillItem(it)}
            title="Click for the full action + the affected trades"
            style={{ background: 'var(--bg2)', borderRadius: 8, padding: '7px 9px', borderLeft: `3px solid ${SEV[it.severity] || 'var(--text3)'}`, cursor: onDrill ? 'pointer' : 'default' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 9, color: SEV[it.severity] || 'var(--text3)', fontWeight: 700, textTransform: 'uppercase' }}>#{it.rank} {ITEM_LABEL[it.item_type] ?? it.item_type} · {it.severity}</span>
              <span style={{ fontSize: 8, color: 'var(--text3)' }}>{it.sample_size} trade{it.sample_size === 1 ? '' : 's'} · drill ›</span>
            </div>
            <div style={{ fontSize: 10, color: 'var(--text1)', margin: '3px 0' }}>{it.lesson?.length > 130 ? it.lesson.slice(0, 130) + '…' : it.lesson}</div>
            <div style={{ fontSize: 8, color: '#60a5fa' }}>→ {it.operator_action?.length > 95 ? it.operator_action.slice(0, 95) + '…' : it.operator_action}</div>
          </div>
        ))}
      </div>

      {(dg?.symbols_to_replay?.length > 0) && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>Replay these (opens the chart):</div>
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
          <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 5 }}>
            Shadow-research candidates — backtested rule changes, <b>evidence-only</b>, never auto-applied. Click for the test detail:
          </div>
          {hyps.map((h, i) => {
            const name = hypName(h.lesson || '')
            const promising = (h.avg_delta_ps ?? 0) > 0
            return (
              <div key={i} onClick={() => onDrill?.({
                title: `Hypothesis: ${name ? (HYP_LABEL[name] ?? name) : 'rule change'}`,
                subtitle: `${promising ? 'promising' : 'unsupported'} · ${h.sample_size} trades backtested · shadow-research only`,
                endpoint: '/api/v2/backtesting/execution-hypotheses',
                rows: [{ hypothesis: name, plain_english: name ? HYP_LABEL[name] : null, verdict: promising ? 'promising' : 'unsupported (would have hurt on average)', sample_size: h.sample_size, avg_delta_per_share: h.avg_delta_ps, full: h.lesson, gate: 'min-sample → shadow test → operator review → A1A → rollback before any live use' }],
              })}
                style={{ fontSize: 9, color: 'var(--text2)', padding: '4px 6px', borderRadius: 5, marginBottom: 3, background: 'var(--bg2)', cursor: onDrill ? 'pointer' : 'default', display: 'flex', gap: 6, alignItems: 'baseline' }}>
                <span style={{ color: promising ? '#22c55e' : '#ef4444', fontWeight: 700, whiteSpace: 'nowrap' }}>{promising ? '◦ promising' : '✗ unsupported'}</span>
                <span style={{ flex: 1 }}><b style={{ color: 'var(--text1)' }}>{name ? (HYP_LABEL[name] ?? name) : 'rule change'}</b> — {name ? `tested on ${h.sample_size} trades, avg ${h.avg_delta_ps}/sh. ${promising ? 'Worth a shadow test.' : 'Would have hurt on average — do not graft.'}` : h.lesson}</span>
                <span style={{ color: 'var(--text3)', whiteSpace: 'nowrap' }}>drill ›</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
