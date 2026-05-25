import { useNavigate } from 'react-router-dom'
import { fmt$ } from '../../lib/format'
import type { LadderRow } from './types'
import s from './MorningBrief.module.css'

export default function PriorityActionBoard({ rows, maxExposure }: { rows: LadderRow[]; maxExposure: number }) {
  const nav = useNavigate()
  if (rows.length === 0) return (
    <div className={s.board} style={{ padding: '24px 12px', textAlign: 'center', color: 'var(--text3)', fontSize: 11 }}>
      No actionable items this morning. Portfolio is stable.
    </div>
  )

  return (
    <div className={s.board}>
      {/* Header */}
      <div className={s.boardHead}>
        <div />
        <div>#</div>
        <div>Type</div>
        <div>Symbol</div>
        <div>Issue</div>
        <div style={{ textAlign: 'right' }}>Exposure</div>
        <div>Owner</div>
        <div>Due</div>
        <div />
      </div>

      {rows.map(r => {
        const isUrgent = r.pri <= 3 && (r.typeColor === 'var(--red)' || r.typeColor === 'var(--amber)')
        const expPct = maxExposure > 0 && r.exposure > 0 ? Math.min((r.exposure / maxExposure) * 100, 100) : 0

        return (
          <div key={r.pri} className={`${s.boardRow} ${isUrgent ? s.boardRowUrgent : ''}`}>
            {/* Severity rail */}
            <div className={s.sevRail} style={{ background: r.typeColor }} />

            {/* Priority number */}
            <div className={s.boardCell} style={{ fontWeight: 800, fontSize: 11, color: r.pri <= 3 ? 'var(--red)' : r.pri <= 6 ? 'var(--text0)' : 'var(--text3)' }}>
              {r.pri}
            </div>

            {/* Type badge */}
            <div className={s.boardCell}>
              <span className={s.badge} style={{ background: `color-mix(in srgb, ${r.typeColor} 15%, transparent)`, color: r.typeColor }}>{r.type}</span>
            </div>

            {/* Symbol */}
            <div className={s.boardCell} style={{ fontWeight: 800, color: 'var(--text0)', fontSize: 11 }}>{r.symbol}</div>

            {/* Issue */}
            <div className={s.boardCell} style={{ fontSize: 10, color: 'var(--text1)' }}>{r.issue}</div>

            {/* Exposure with bar */}
            <div className={s.boardCell} style={{ textAlign: 'right' }}>
              {r.exposure > 0 ? (
                <>
                  <div style={{ fontWeight: 700, color: 'var(--red)', fontSize: 10 }}>{r.exposureFmt}</div>
                  <div className={s.expBar}>
                    <div className={s.expBarFill} style={{ width: `${expPct}%`, background: r.typeColor }} />
                  </div>
                </>
              ) : (
                <span style={{ color: 'var(--text3)', fontSize: 9 }}>—</span>
              )}
            </div>

            {/* Owner badge */}
            <div className={s.boardCell}>
              <span className={s.ownerBadge} style={{
                background: r.owner === 'John' ? 'var(--amber-dim)' : r.owner === 'Steph' ? 'var(--accent-dim)' : 'var(--bg3)',
                color: r.owner === 'John' ? 'var(--amber)' : r.owner === 'Steph' ? 'var(--accent)' : 'var(--text3)',
              }}>{r.owner}</span>
            </div>

            {/* Due chip */}
            <div className={s.boardCell}>
              <span className={s.dueBadge} style={{
                background: r.due === 'Now' || r.due === 'Overdue' ? 'var(--red-dim)' : r.due === 'Today' ? 'var(--amber-dim)' : 'transparent',
                color: r.due === 'Now' || r.due === 'Overdue' ? 'var(--red)' : r.due === 'Today' ? 'var(--amber)' : 'var(--text3)',
              }}>{r.due}</span>
            </div>

            {/* Action button */}
            <div className={s.boardCell}>
              {r.routeLabel !== '—' && (
                <button onClick={() => nav(r.route)} className={s.sans} style={{
                  fontSize: 8, fontWeight: 700, padding: '3px 8px', border: `1px solid ${r.typeColor}`,
                  borderRadius: 3, background: `color-mix(in srgb, ${r.typeColor} 8%, transparent)`,
                  color: r.typeColor, cursor: 'pointer', whiteSpace: 'nowrap',
                }}>{r.routeLabel}</button>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
