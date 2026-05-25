# Source Export: OpportunityPanel.tsx

- **Original path:** apps/command-center-v2/src/components/morning-brief/OpportunityPanel.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:38:05-04:00
- **SHA256:** 55c7747577ef6137ce935839bb9465444893d7e2c1c96c66e43b6ef16aa63866
- **File size:** 4641 bytes
- **Exists:** YES

```tsx
import { useNavigate } from 'react-router-dom'
import type { RecoveryItem, CoveredCall, Rotation } from './types'
import { vl } from './types'
import s from './MorningBrief.module.css'

interface Props { recovery: RecoveryItem[]; ccReview: CoveredCall[]; ccAvoid: CoveredCall[]; rotations: Rotation[] }

export default function OpportunityPanel({ recovery, ccReview, ccAvoid, rotations }: Props) {
  const nav = useNavigate()
  const hasItems = recovery.length > 0 || ccReview.length > 0 || ccAvoid.length > 0 || rotations.length > 0

  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6, padding: '10px 12px' }}>
      <div className={s.secHead}>
        <span className={`${s.secTitle} ${s.sans}`}>Recovery & Opportunities</span>
        <button className={`${s.secLink} ${s.sans}`} onClick={() => nav('/recovery')}>Full Recovery View</button>
      </div>

      {!hasItems && <div className={s.sans} style={{ fontSize: 10, color: 'var(--text3)', padding: '6px 0' }}>No recovery or opportunity items in scope.</div>}

      {/* Recovery watch with confidence bars */}
      {recovery.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div className={s.sans} style={{ fontSize: 8, fontWeight: 700, color: 'var(--accent)', textTransform: 'uppercase', marginBottom: 4 }}>Recovery Watch ({recovery.length})</div>
          {recovery.map(r => (
            <div key={r.symbol} className={s.oppRow}>
              <span className={s.sans} style={{ fontWeight: 800, color: 'var(--text0)', width: 40, fontSize: 11 }}>{r.symbol}</span>
              <VerdictChip verdict={r.analyst_verdict} />
              <span className={s.sans} style={{ color: 'var(--text2)', flex: 1, fontSize: 9 }}>{vl(r.temp_allocation_verdict)}</span>
              {r.analyst_confidence != null && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <div className={s.confBar}>
                    <div className={s.confBarFill} style={{ width: `${r.analyst_confidence * 100}%`, background: r.analyst_confidence >= 0.7 ? 'var(--green)' : 'var(--amber)' }} />
                  </div>
                  <span className={s.sans} style={{ fontSize: 9, color: 'var(--text3)', width: 24, textAlign: 'right' }}>{(r.analyst_confidence * 100).toFixed(0)}%</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Covered calls */}
      {(ccReview.length + ccAvoid.length) > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div className={s.sans} style={{ fontSize: 8, fontWeight: 700, color: 'var(--green)', textTransform: 'uppercase', marginBottom: 4 }}>Covered Calls ({ccReview.length + ccAvoid.length})</div>
          {[...ccReview, ...ccAvoid].map(c => (
            <div key={c.symbol} className={s.oppRow}>
              <span className={s.sans} style={{ fontWeight: 800, color: 'var(--text0)', width: 40, fontSize: 11 }}>{c.symbol}</span>
              <VerdictChip verdict={c.verdict} />
              <span className={s.sans} style={{ color: 'var(--text2)', flex: 1, fontSize: 9 }}>{(c.reasoning || '').slice(0, 50)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Rotations */}
      {rotations.length > 0 && (
        <div>
          <div className={s.sans} style={{ fontSize: 8, fontWeight: 700, color: 'var(--purple)', textTransform: 'uppercase', marginBottom: 4 }}>Rotation Alternatives ({rotations.length})</div>
          {rotations.slice(0, 4).map(r => (
            <div key={r.from_symbol + r.to_symbol} className={s.oppRow}>
              <span className={s.sans} style={{ fontWeight: 800, color: 'var(--text0)', width: 80, fontSize: 10 }}>{r.from_symbol} → {r.to_symbol}</span>
              <VerdictChip verdict={r.switch_verdict} />
              <span className={s.sans} style={{ color: 'var(--text2)', flex: 1, fontSize: 9 }}>{(r.evidence || '').slice(0, 40)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function VerdictChip({ verdict }: { verdict: string }) {
  const color = verdict === 'reentry_candidate' ? 'var(--green)' : verdict === 'do_not_reenter' || verdict === 'avoid' ? 'var(--red)' : verdict === 'review_needed' ? 'var(--amber)' : 'var(--accent)'
  const bg = verdict === 'reentry_candidate' ? 'var(--green-dim)' : verdict === 'do_not_reenter' || verdict === 'avoid' ? 'var(--red-dim)' : verdict === 'review_needed' ? 'var(--amber-dim)' : 'var(--accent-dim)'
  return <span className={`${s.badge} ${s.sans}`} style={{ background: bg, color }}>{vl(verdict).slice(0, 18)}</span>
}
```
