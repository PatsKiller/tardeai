# Source Export: DecisionQueueRail.tsx

- **Original path:** apps/command-center-v2/src/components/morning-brief/DecisionQueueRail.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:38:05-04:00
- **SHA256:** 8a0ebca0476ed43992a75746dc9c93be0768a06a998523bbef7aa494fe38ef37
- **File size:** 4310 bytes
- **Exists:** YES

```tsx
import { useNavigate } from 'react-router-dom'
import type { StephItem, ChatCtx } from './types'
import { cl } from './types'
import s from './MorningBrief.module.css'

interface Props {
  pendingApprovals: number
  stephPending: StephItem[]
  stephJohn: StephItem[]
  jd: ChatCtx['john_decisions']
  ot: ChatCtx['outcome_tracking']
}

export default function DecisionQueueRail({ pendingApprovals, stephPending, stephJohn, jd, ot }: Props) {
  const nav = useNavigate()

  return (
    <div>
      <div className={s.secHead}>
        <span className={`${s.secTitle} ${s.sans}`}>Decision Queue</span>
        <button className={`${s.secLink} ${s.sans}`} onClick={() => nav('/approvals')}>Open Approvals</button>
      </div>

      <div className={s.queuePanel}>
        <QR label="Pending approvals" val={pendingApprovals} color={pendingApprovals > 0 ? 'var(--amber)' : 'var(--green)'} onClick={() => nav('/approvals')} />
        <QR label="Steph reviewing" val={stephPending.length} color={stephPending.length > 0 ? 'var(--amber)' : 'var(--green)'} />
        <QR label="Flagged for John" val={stephJohn.length} color={stephJohn.length > 0 ? 'var(--red)' : 'var(--green)'} onClick={stephJohn.length > 0 ? () => nav('/approvals') : undefined} />
        <div className={s.queueDivider} />
        <QR label="Overdue" val={jd.overdue_count} color={jd.overdue_count > 0 ? 'var(--red)' : 'var(--green)'} />
        <QR label="Due this week" val={jd.due_this_week} color={jd.due_this_week > 0 ? 'var(--amber)' : 'var(--text2)'} />
        <QR label="Deferred" val={jd.deferred_items?.length ?? 0} color="var(--text2)" />
        <div className={s.queueDivider} />
        <QR label="Outcomes evaluated" val={ot.evaluated} color="var(--text1)" />
        {ot.avg_score != null && <QR label="Avg score" val={ot.avg_score.toFixed(2)} color={ot.avg_score >= 0.6 ? 'var(--green)' : 'var(--amber)'} fmt />}
      </div>

      {/* Steph queue detail */}
      {stephPending.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div className={s.sans} style={{ fontSize: 8, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 4 }}>Steph Queue</div>
          {stephPending.map((item, i) => (
            <div key={i} className={s.queueDetail} style={{ borderLeft: `2px solid ${item.send_to_john ? 'var(--red)' : 'var(--amber)'}` }}>
              <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                <span className={s.sans} style={{ fontSize: 10, fontWeight: 700, color: 'var(--text0)' }}>{item.symbol}</span>
                <span className={s.badge} style={{ background: 'var(--bg-card)', color: 'var(--text3)' }}>{cl(item.category)}</span>
                {item.send_to_john && <span className={s.badge} style={{ background: 'var(--red-dim)', color: 'var(--red)' }}>→ JOHN</span>}
              </div>
              <div className={s.sans} style={{ fontSize: 9, color: 'var(--text2)', marginTop: 2 }}>{(item.steph_verdict || item.reason || '').slice(0, 60)}</div>
            </div>
          ))}
        </div>
      )}

      {/* Deferred items */}
      {(jd.deferred_items?.length ?? 0) > 0 && (
        <div style={{ marginTop: 8 }}>
          <div className={s.sans} style={{ fontSize: 8, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 4 }}>Deferred</div>
          {jd.deferred_items.map(d => (
            <div key={d.id} className={s.queueDetail} style={{ borderLeft: '2px solid var(--text3)' }}>
              <div className={s.sans} style={{ fontSize: 10, fontWeight: 600, color: 'var(--text0)' }}>{d.symbol} — {d.title.slice(0, 35)}</div>
              <div className={s.sans} style={{ fontSize: 9, color: 'var(--text3)' }}>Revisit {d.revisit_on}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function QR({ label, val, color, onClick, fmt }: { label: string; val: number | string; color: string; onClick?: () => void; fmt?: boolean }) {
  return (
    <div className={s.queueRow} data-click={onClick ? '' : undefined} onClick={onClick}>
      <span className={s.sans} style={{ fontSize: 10, color: 'var(--text2)' }}>{label}</span>
      <span className={s.sans} style={{ fontSize: 12, fontWeight: 800, color }}>{fmt ? val : String(val)}</span>
    </div>
  )
}
```
