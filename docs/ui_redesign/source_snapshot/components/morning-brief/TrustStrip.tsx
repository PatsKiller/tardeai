import { timeAgo } from '../../lib/format'
import type { ChatCtx, OvData, RiskData } from './types'
import s from './MorningBrief.module.css'

interface Props { ev: ChatCtx['evidence_summary']; ot: ChatCtx['outcome_tracking']; ov: OvData | null; rk: RiskData | null }

export default function TrustStrip({ ev, ot, ov, rk }: Props) {
  return (
    <div className={s.trustStrip}>
      <TC label="Evidence" val={`${ev.symbols_checked || 0} symbols`} sub={Object.entries(ev.sufficiency || {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—'} />
      <TC label="Bias" val={(ev.bias_flagged ?? 0) === 0 ? 'Clean' : `${ev.bias_flagged} flagged`} color={(ev.bias_flagged ?? 0) > 0 ? 'var(--red)' : 'var(--green)'} />
      <TC label="Conflicts" val={(ev.conflicts ?? 0) === 0 ? 'None' : `${ev.conflicts}`} color={(ev.conflicts ?? 0) > 0 ? 'var(--red)' : 'var(--green)'} />
      <TC label="Outcomes" val={`${ot.evaluated}/${ot.total}`} sub={ot.avg_score != null ? `avg ${ot.avg_score.toFixed(2)}` : ''} />
      <TC label="Pipeline" val={ov?.pipeline_status || '—'} sub={ov?.pipeline_completed ? timeAgo(ov.pipeline_completed) : ''} color={ov?.pipeline_status === 'fresh' ? 'var(--green)' : 'var(--amber)'} />
      <TC label="Protected" val={`${(rk?.pct_protected ?? 0).toFixed(0)}%`} color={(rk?.pct_protected ?? 0) >= 50 ? 'var(--green)' : 'var(--amber)'} />
    </div>
  )
}

function TC({ label, val, sub, color }: { label: string; val: string; sub?: string; color?: string }) {
  return (
    <div className={s.trustCell}>
      <div className={s.sans} style={{ fontSize: 7, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.3px' }}>{label}</div>
      <div className={s.sans} style={{ fontSize: 10, fontWeight: 700, color: color || 'var(--text0)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{val}</div>
      {sub && <div className={s.sans} style={{ fontSize: 8, color: 'var(--text3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{sub}</div>}
    </div>
  )
}
